"""
Worker principal — orquestra ingestão e triagem.

Loop:
1. A cada POLL_INTERVAL_S segundos, vai à API fogos.pt
2. Para cada ocorrência:
   - upsert na BD (regista histórico)
   - se é relevante para triagem e ainda não foi triada (a triagem é
     congelada no arranque da ocorrência — ver needs_triage):
     - lookup landscape (DEM, slope, aspect, fuel)
     - fetch Open-Meteo no ponto exato (fonte primária de meteo)
     - correr triage_occurrence
     - guardar resultado
3. Marcar como inativas ocorrências que desapareceram da resposta

Variáveis de ambiente:
- DATABASE_URL: DSN Postgres (postgresql://user:pass@host:5432/db)
- LANDSCAPE_DIR: diretório com os 8 TIFFs da Landscape File PT (ou, se
  LANDSCAPE_FILE estiver definido, diretório onde esse ficheiro fica)
- LANDSCAPE_FILE: nome do ficheiro Landscape File multibanda (opcional —
  quando definido, o worker lê UM GeoTIFF de 8 bandas em vez dos 8 TIFFs
  separados, e passa a triar apenas ocorrências dentro da extensão desse
  ficheiro; usado pelos pilotos regionais, ex. Alto Minho)
- FUEL_MODELS_CSV: caminho para o CSV dos modelos PT
- POLL_INTERVAL_S: segundos entre polls (default 120)
- LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
- R2_ACCOUNT_ID: Cloudflare Account ID (para download dos TIFFs no arranque)
- R2_ACCESS_KEY_ID: R2 API Token Access Key ID
- R2_SECRET_ACCESS_KEY: R2 API Token Secret Access Key
- R2_BUCKET: nome do bucket R2 (default: fogos-landscape)
- R2_PREFIX: prefixo dos TIFFs no bucket (default: landscape/)
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
from fogos_triage.landscape import (
    LandscapeRasters, LandscapeReader, MockLandscapeReader, ensure_landscape,
)
from fogos_triage.schemas import TerrainConditions
from fogos_triage.triage import triage_neighbourhood
from fogos_triage.lfmc_climatologia import descreve as descreve_lfmc, lfmc_climatologia
from fogos_triage.weather import fetch_open_meteo, fetch_precipitation_sum

log = logging.getLogger(__name__)


class WorkerConfig:
    """Configuração lida de env vars."""
    def __init__(self):
        self.database_url = os.environ["DATABASE_URL"]
        self.landscape_dir = os.environ.get("LANDSCAPE_DIR")
        self.landscape_file = os.environ.get("LANDSCAPE_FILE")
        self.fuel_models_csv = os.environ.get(
            "FUEL_MODELS_CSV",
            "/data/fuel_models_pt.csv",
        )
        self.poll_interval_s = int(os.environ.get("POLL_INTERVAL_S", "120"))
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
        # Modo desenvolvimento — sem landscape real, usa mock
        self.dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"
        # Cloudflare R2 — download dos TIFFs no arranque
        self.r2_account_id = os.environ.get("R2_ACCOUNT_ID")
        self.r2_access_key_id = os.environ.get("R2_ACCESS_KEY_ID")
        self.r2_secret_access_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.environ.get("R2_BUCKET", "fogos-landscape")
        self.r2_prefix = os.environ.get("R2_PREFIX", "landscape/")


_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

_MIGRATIONS = [
    "001_initial_schema.sql",
    "002_add_fwi.sql",
    "003_add_fuel_moisture.sql",
    "004_free_simulation_jobs.sql",
    "005_vigilancia_terminated.sql",
    "006_triage_coords.sql",
]


async def run_migrations(database_url: str) -> None:
    """
    Aplica as migrations em ordem, com retry até o Postgres estar pronto.
    Idempotente — usa IF NOT EXISTS em todo o DDL.
    """
    import asyncpg

    log.info("A aplicar migrations...")
    conn = None
    last_err = None
    for attempt in range(1, 31):
        try:
            conn = await asyncpg.connect(database_url)
            break
        except Exception as exc:
            last_err = exc
            log.info(f"Postgres ainda não disponível (tentativa {attempt}): {exc}")
            await asyncio.sleep(2)

    if conn is None:
        raise RuntimeError(f"Não foi possível ligar ao Postgres para migrations: {last_err}")

    try:
        for filename in _MIGRATIONS:
            path = _MIGRATIONS_DIR / filename
            if not path.exists():
                log.warning(f"Migration não encontrada: {path}")
                continue
            await conn.execute(path.read_text())
            log.info(f"  {filename} — ok")
    finally:
        await conn.close()

    log.info("Migrations concluídas")


def _ensure_landscape_worker(config: WorkerConfig) -> None:
    """Wrapper que adapta WorkerConfig para ensure_landscape() partilhado."""
    if config.dev_mode or not config.landscape_dir:
        return
    ensure_landscape(
        landscape_dir=config.landscape_dir,
        r2_account_id=config.r2_account_id,
        r2_access_key_id=config.r2_access_key_id,
        r2_secret_access_key=config.r2_secret_access_key,
        r2_bucket=config.r2_bucket,
        r2_prefix=config.r2_prefix,
        filename=config.landscape_file,
    )


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
    elif config.landscape_file:
        path = Path(config.landscape_dir) / config.landscape_file
        log.info(f"A abrir Landscape File multibanda em {path}")
        ls_reader = LandscapeReader(multiband_path=path)
        ls_reader.__enter__()
        log.info(f"  extensão (WGS84): {ls_reader.bounds_wgs84}")
    else:
        log.info(f"A abrir Landscape File em {config.landscape_dir}")
        rasters = LandscapeRasters.from_directory(config.landscape_dir)
        ls_reader = LandscapeReader(rasters=rasters)
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

    # 0. Fora da extensão do landscape file carregado? Nesse caso a triagem
    #    usaria terreno fabricado (elevação/declive a 0, fuel model default)
    #    em vez de dados reais — não ingerir nem triar.
    if not ls_reader.contains(fire.latitude, fire.longitude):
        return f"{fire.fire_id} — fora da área de cobertura do landscape file"

    occ_repo = OccurrenceRepository(pool)
    triage_repo = TriageResultRepository(pool)

    # 1. Upsert ocorrência. O retorno (is_new, has_changes) já não
    #    decide a triagem — ver o comentário abaixo —, mas a chamada
    #    continua a ser precisa: é ela que escreve occurrence_history.
    await occ_repo.upsert_fire(fire)

    # 2. Decidir se triagem é necessária
    if not fire.is_triage_relevant:
        return f"{fire.fire_id} ({fire.natureza_name}) — natureza não relevante"

    if fire.is_terminated:
        return f"{fire.fire_id} — terminada"

    # A triagem é congelada no arranque da ocorrência: é um protocolo de
    # despacho, uma decisão do minuto zero, não um valor a recalcular
    # continuamente. Antes bastava a fogos.pt actualizar o número de
    # operacionais (`has_changes`) — ou passarem 15 minutos — para repetir
    # terreno, Open-Meteo, VIIRS e motor de fogo; num incêndio grande
    # eram centenas de triagens iguais, e o valor mostrado ao utilizador
    # deixava de ser o do despacho.
    #
    # A única excepção é a localização mudar — ver needs_triage.
    if not await occ_repo.needs_triage(fire.fire_id, fire.latitude, fire.longitude):
        return None  # triagem congelada, nada a fazer

    # 3. Triagem
    occurrence = fogos_to_occurrence(fire)
    terrains = ls_reader.sample_neighbourhood(fire.latitude, fire.longitude)

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

    # Humidade dos combustíveis vivos: climatologia sazonal + precipitação
    # acumulada a 180 dias (ver src/fogos_triage/lfmc_climatologia.py e
    # LFMC_CLIMATOLOGIA_PLAN.md).
    #
    # Substituiu o VIIRS/Yebra 2007, que foi validado contra 654 medições
    # de campo do ICNF e reprovou: no herbáceo dava viés de +110 pontos
    # percentuais e correlação ZERO (r = -0.03) com o terreno. Na prática
    # devolvia ~138% no pico do Verão, o que satura a fracção curada de
    # Andrews 2018 em 0% e mantinha os FM231/FM232 com a herbácea toda
    # verde de Julho a Setembro.
    #
    # Se a precipitação falhar não se inventa nada: fica None e o motor
    # usa os seus próprios defaults, como já acontecia quando o GEE
    # falhava.
    live_h_pct: Optional[float] = None
    live_w_pct: Optional[float] = None
    data_lfmc = weather_raw.timestamp or datetime.now(timezone.utc)
    p180_mm = await fetch_precipitation_sum(fire.latitude, fire.longitude, data_lfmc)
    if p180_mm is not None:
        live_h_pct, live_w_pct = lfmc_climatologia(
            data_lfmc.timetuple().tm_yday, p180_mm,
        )
        log.info(
            f"{fire.fire_id} — LFMC climatologia: herbáceo={live_h_pct:.0f}% "
            f"lenhoso={live_w_pct:.0f}% (P180={p180_mm:.0f}mm)"
        )
    else:
        log.warning(
            f"{fire.fire_id} — sem precipitação acumulada; combustível vivo "
            f"fica nos defaults do motor"
        )

    # derive_fire_weather é chamado per-pixel dentro de triage_neighbourhood
    try:
        result = triage_neighbourhood(
            occurrence, fuel_models, terrains, weather_raw, live_h_pct, live_w_pct
        )
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
             f"triagem=congelada-no-arranque "
             f"dev_mode={config.dev_mode}")
    log.info(f"LFMC por climatologia — {descreve_lfmc()}")

    # Garantir TIFFs presentes (download do R2 se necessário)
    _ensure_landscape_worker(config)

    # Correr migrations antes de tudo o resto
    await run_migrations(config.database_url)

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
