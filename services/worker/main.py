"""
Worker principal — orquestra ingestão e triagem.

Loop:
1. A cada POLL_INTERVAL_S segundos, vai à API fogos.pt
2. Para cada ocorrência:
   - upsert na BD (regista histórico)
   - se é relevante para triagem e não foi triada recentemente:
     - lookup landscape (DEM, slope, aspect, fuel)
     - fetch Open-Meteo no ponto exato (fonte primária de meteo)
     - correr triage_occurrence
     - guardar resultado
3. Marcar como inativas ocorrências que desapareceram da resposta

Variáveis de ambiente:
- DATABASE_URL: DSN Postgres (postgresql://user:pass@host:5432/db)
- LANDSCAPE_DIR: diretório com os 7 TIFFs da Landscape File PT
- FUEL_MODELS_CSV: caminho para o CSV dos modelos PT
- POLL_INTERVAL_S: segundos entre polls (default 120)
- TRIAGE_MAX_AGE_MIN: minutos a partir dos quais re-triar (default 15)
- LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fogos_triage.db.repository import OccurrenceRepository, init_pool
from fogos_triage.db.triage_repo import TriageResultRepository
from fogos_triage.fuel_models import load_fuel_models_csv
from fogos_triage.ingestion.adapters import fogos_to_occurrence
from fogos_triage.ingestion.fogos_client import FogosFire, fetch_fires
from fogos_triage.landscape import LandscapeRasters, LandscapeReader, MockLandscapeReader
from fogos_triage.schemas import TerrainConditions
from fogos_triage.triage import triage_occurrence
from fogos_triage.weather import derive_fire_weather, fetch_open_meteo

log = logging.getLogger(__name__)


class WorkerConfig:
    """Configuração lida de env vars."""
    def __init__(self):
        self.database_url = os.environ["DATABASE_URL"]
        self.landscape_dir = os.environ.get("LANDSCAPE_DIR")
        self.fuel_models_csv = os.environ.get(
            "FUEL_MODELS_CSV",
            "/data/fuel_models_pt.csv",
        )
        self.poll_interval_s = int(os.environ.get("POLL_INTERVAL_S", "120"))
        self.triage_max_age_min = int(os.environ.get("TRIAGE_MAX_AGE_MIN", "15"))
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
        # Modo desenvolvimento — sem landscape real, usa mock
        self.dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"


@asynccontextmanager
async def worker_resources(config: WorkerConfig):
    """Context manager que prepara e limpa recursos do worker."""
    # 1. Pool Postgres — com retry, porque em docker-compose o Postgres
    #    pode ainda estar a correr os init scripts quando o worker arranca.
    log.info("A inicializar pool Postgres...")
    pool = None
    last_err = None
    for attempt in range(1, 31):  # até ~60s de espera
        try:
            pool = await init_pool(config.database_url, min_size=2, max_size=5)
            # Verificar que o schema existe (tabela occurrences)
            async with pool.acquire() as conn:
                has_schema = await conn.fetchval(
                    "SELECT to_regclass('public.occurrences') IS NOT NULL"
                )
            if has_schema:
                log.info(f"Postgres pronto (tentativa {attempt})")
                break
            else:
                log.warning(
                    f"Postgres acessível mas schema ainda não criado "
                    f"(tentativa {attempt}) — a aplicar migrations?"
                )
                await pool.close()
                pool = None
        except Exception as exc:
            last_err = exc
            log.info(f"Postgres ainda não disponível (tentativa {attempt}): {exc}")
            if pool is not None:
                await pool.close()
                pool = None
        await asyncio.sleep(2)

    if pool is None:
        raise RuntimeError(
            f"Não foi possível ligar ao Postgres com schema válido. "
            f"Último erro: {last_err}. "
            f"Verificar que as migrations foram aplicadas "
            f"(migrations/001_initial_schema.sql)."
        )

    # 2. Modelos de combustível (em memória, ~20 entradas)
    log.info(f"A carregar modelos de combustível de {config.fuel_models_csv}")
    fuel_models = load_fuel_models_csv(config.fuel_models_csv)
    log.info(f"  {len(fuel_models)} modelos carregados")

    # 3. Landscape Reader (mantido aberto durante todo o run)
    if config.dev_mode or not config.landscape_dir:
        log.warning("DEV_MODE — usando MockLandscapeReader (terreno fixo)")
        ls_reader = MockLandscapeReader(_default_dev_terrain())
        ls_reader.__enter__()
    else:
        log.info(f"A abrir Landscape File em {config.landscape_dir}")
        rasters = LandscapeRasters.from_directory(config.landscape_dir)
        ls_reader = LandscapeReader(rasters)
        ls_reader.__enter__()

    try:
        yield {
            "pool": pool,
            "fuel_models": fuel_models,
            "landscape": ls_reader,
            "config": config,
        }
    finally:
        log.info("A fechar recursos...")
        ls_reader.__exit__(None, None, None)
        await pool.close()


def _default_dev_terrain() -> TerrainConditions:
    """Terreno default para dev_mode — pinhal com declive moderado."""
    return TerrainConditions(
        elevation_m=400,
        slope_fraction=0.27,
        slope_degrees=15,
        aspect_degrees=180,
        fuel_model_num=227,  # M-PIN
        stand_height_m=15,
        canopy_cover_pct=50,
        canopy_base_height_m=3.0,
    )


async def process_fire(
    fire: FogosFire,
    resources: dict,
) -> Optional[str]:
    """
    Processa uma ocorrência: upsert + triagem (se necessário).
    Devolve string descritiva ou None se nada relevante aconteceu.
    """
    pool = resources["pool"]
    fuel_models = resources["fuel_models"]
    ls_reader = resources["landscape"]
    config: WorkerConfig = resources["config"]

    occ_repo = OccurrenceRepository(pool)
    triage_repo = TriageResultRepository(pool)

    # 1. Upsert ocorrência
    is_new, has_changes = await occ_repo.upsert_fire(fire)

    # 2. Decidir se triagem é necessária
    if not fire.is_triage_relevant:
        return f"{fire.fire_id} ({fire.natureza_name}) — natureza não relevante"

    if fire.is_terminated:
        return f"{fire.fire_id} — terminada"

    needs = is_new or has_changes
    if not needs:
        needs = await occ_repo.needs_retriage(
            fire.fire_id,
            max_age_minutes=config.triage_max_age_min,
        )

    if not needs:
        return None  # nada a fazer

    # 3. Triagem
    occurrence = fogos_to_occurrence(fire)
    terrain = ls_reader.sample(fire.latitude, fire.longitude)

    # Meteo: Open-Meteo no ponto exato do fogo.
    # Vantagem sobre a IPMA da fogos.pt: a IPMA é da estação mais próxima
    # (pode estar a 15-20 km e noutro terreno); o Open-Meteo é interpolado
    # à coordenada da ocorrência.
    weather_raw = None
    try:
        forecast = await fetch_open_meteo(
            fire.latitude, fire.longitude, hours_ahead=1,
        )
        if forecast:
            weather_raw = forecast[0]  # hora atual
    except Exception as exc:
        log.warning(f"Open-Meteo falhou para {fire.fire_id}: {exc}")

    if weather_raw is None:
        # Fallback — Open-Meteo indisponível. Triagem com defaults
        # conservadores (verão moderado) para não bloquear.
        from fogos_triage.schemas import WeatherConditions
        log.warning(f"{fire.fire_id} — sem meteo, a usar defaults")
        weather_raw = WeatherConditions(
            timestamp=fire.updated_at,
            temperature_c=25.0,
            relative_humidity_pct=50.0,
            wind_speed_10m_ms=3.0,
            wind_gust_10m_ms=4.5,
            wind_direction_deg=0.0,
            precipitation_mm_24h=0.0,
            cloud_cover_pct=30.0,
        )
    else:
        # Persistir o snapshot — sem isto a API mostra weather a null
        try:
            await occ_repo.save_open_meteo_snapshot(fire.fire_id, weather_raw)
        except Exception as exc:
            log.warning(f"Não guardou snapshot meteo de {fire.fire_id}: {exc}")

    weather = derive_fire_weather(
        weather_raw,
        stand_height_m=terrain.stand_height_m or 0,
        canopy_cover_pct=terrain.canopy_cover_pct or 0,
        has_overstory=(terrain.canopy_cover_pct or 0) > 10,
    )

    try:
        result = triage_occurrence(occurrence, fuel_models, terrain, weather)
        await triage_repo.save(result)
        return (f"{fire.fire_id} → {result.priority.value} "
                f"(score {result.priority_score:.0f}, "
                f"chamas {result.central_prediction.flame_length_m:.1f}m, "
                f"FM {result.fuel_model_used})")
    except Exception as exc:
        log.exception(f"Erro a triar {fire.fire_id}: {exc}")
        return f"{fire.fire_id} — ERRO: {exc}"


async def poll_cycle(resources: dict) -> dict:
    """Um ciclo completo de polling: fetch → process → cleanup."""
    cycle_started = datetime.now(timezone.utc)
    stats = {"fetched": 0, "new": 0, "triaged": 0, "errors": 0, "marked_inactive": 0}

    try:
        fires = await fetch_fires()
        stats["fetched"] = len(fires)
        log.info(f"fogos.pt: {len(fires)} ocorrências")
    except Exception as exc:
        log.exception(f"Erro a ir à fogos.pt: {exc}")
        stats["errors"] += 1
        return stats

    current_ids = set()
    for fire in fires:
        current_ids.add(fire.fire_id)
        try:
            msg = await process_fire(fire, resources)
            if msg:
                log.info(f"  {msg}")
                if "→" in msg:
                    stats["triaged"] += 1
        except Exception as exc:
            log.exception(f"Erro a processar {fire.fire_id}: {exc}")
            stats["errors"] += 1

    # Marcar ocorrências em falta como inativas
    occ_repo = OccurrenceRepository(resources["pool"])
    inactive_count = await occ_repo.mark_inactive_missing(current_ids)
    stats["marked_inactive"] = inactive_count
    if inactive_count > 0:
        log.info(f"Marcadas {inactive_count} ocorrências como inativas")

    cycle_dur = (datetime.now(timezone.utc) - cycle_started).total_seconds()
    log.info(f"Ciclo concluído em {cycle_dur:.1f}s: {stats}")

    # Marcar liveness para o healthcheck do Docker/Railway
    try:
        Path("/tmp/worker_alive").write_text(
            datetime.now(timezone.utc).isoformat()
        )
    except OSError:
        pass  # healthcheck é best-effort, não deve quebrar o ciclo

    return stats


async def run_worker():
    """Entry point do worker — corre em loop até receber sinal de paragem."""
    config = WorkerConfig()

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log.info("=== fogos_triage worker a iniciar ===")
    log.info(f"poll_interval={config.poll_interval_s}s "
             f"triage_max_age={config.triage_max_age_min}min "
             f"dev_mode={config.dev_mode}")

    # Sinal de paragem (Ctrl-C, SIGTERM do Railway/Docker)
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async with worker_resources(config) as resources:
        while not stop_event.is_set():
            try:
                await poll_cycle(resources)
            except Exception as exc:
                log.exception(f"Erro no ciclo: {exc}")

            # Esperar próximo ciclo ou sinal de paragem
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=config.poll_interval_s,
                )
            except asyncio.TimeoutError:
                continue  # tempo expirou, próximo ciclo

    log.info("Worker terminou graciosamente")


if __name__ == "__main__":
    asyncio.run(run_worker())
