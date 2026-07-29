"""
Endpoints de suporte: fuel models, simulação ForeFire, healthcheck.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from .deps import APIConfig, get_config, get_pool, require_api_key
from .schemas import (
    FuelModelInfo,
    HealthResponse,
    SimulationJob,
    SimulationJobDetail,
    SimulationRequest,
    SimulationResultDetail,
)

log = logging.getLogger(__name__)


router_fuels = APIRouter(prefix="/fuel-models", tags=["fuel-models"])
router_sim = APIRouter(prefix="/simulate", tags=["simulation"])
router_jobs = APIRouter(prefix="/jobs", tags=["simulation"])
router_health = APIRouter(tags=["meta"])


# ---------------------------------------------------------------------------
# Fuel models — carregados em arranque
# ---------------------------------------------------------------------------

_fuel_cache: Optional[list[FuelModelInfo]] = None


def _load_fuel_models() -> list[FuelModelInfo]:
    """Lazy load dos modelos PT. Evita importar fogos_triage no arranque
    se não for preciso."""
    global _fuel_cache
    if _fuel_cache is not None:
        return _fuel_cache

    csv_path = os.environ.get(
        "FUEL_MODELS_CSV",
        "/data/fuel_models_pt.csv",
    )
    if not Path(csv_path).exists():
        _fuel_cache = []
        return _fuel_cache

    from fogos_triage.fuel_models import load_fuel_models_csv
    models = load_fuel_models_csv(csv_path)
    _fuel_cache = [
        FuelModelInfo(
            num=m.num,
            code=m.code,
            name=m.name,
            load_dead_t_ha=m.load_total_dead_t_ha,
            load_live_t_ha=m.load_total_live_t_ha,
            depth_cm=m.depth_cm,
            moist_ext_dead_pct=m.moist_ext_dead * 100,
            is_dynamic=m.is_dynamic,
        )
        for m in sorted(models.values(), key=lambda x: x.num)
    ]
    return _fuel_cache


@router_fuels.get(
    "",
    response_model=list[FuelModelInfo],
    summary="Lista dos modelos de combustível PT",
)
async def list_fuel_models(_: str = Depends(require_api_key)):
    return _load_fuel_models()


@router_fuels.get(
    "/{model_num}",
    response_model=FuelModelInfo,
    summary="Detalhe de um modelo de combustível",
)
async def get_fuel_model(model_num: int, _: str = Depends(require_api_key)):
    for m in _load_fuel_models():
        if m.num == model_num:
            return m
    raise HTTPException(status_code=404, detail=f"Modelo {model_num} não encontrado")


# ---------------------------------------------------------------------------
# Simulação ForeFire — apenas a estrutura. Runner virá em fase seguinte.
# ---------------------------------------------------------------------------


@router_sim.post(
    "",
    response_model=SimulationJob,
    summary="Cria job de simulação Huygens/Richards",
    status_code=202,
)
async def create_simulation(
    payload: SimulationRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    config: APIConfig = Depends(get_config),
    _: str = Depends(require_api_key),
):
    async with pool.acquire() as conn:
        occ = await conn.fetchrow(
            """
            SELECT o.fire_id, o.latitude, o.longitude,
                   t.wind_midflame_ms, t.fuel_moisture_1h_pct, t.fuel_moisture_10h_pct,
                   t.fuel_moisture_100h_pct, t.fuel_moisture_live_h_pct,
                   t.fuel_moisture_live_w_pct,
                   w.wind_speed_ms, w.wind_direction_deg, w.temperature_c,
                   w.relative_humidity_pct
            FROM occurrences o
            LEFT JOIN triage_results t ON t.fire_id = o.fire_id AND t.is_latest = TRUE
            LEFT JOIN weather_snapshots w ON w.fire_id = o.fire_id
                AND w.id = (SELECT MAX(id) FROM weather_snapshots WHERE fire_id = o.fire_id)
            WHERE o.fire_id = $1
            """,
            payload.fire_id,
        )
        if occ is None:
            raise HTTPException(status_code=404, detail="Ocorrência não encontrada")

        if not Path(config.landscape_dir).exists():
            raise HTTPException(
                status_code=501,
                detail="Simulação requer rasters reais (DEV_MODE não suportado)",
            )

        wind_speed = payload.wind_speed_ms or occ["wind_speed_ms"] or 3.0
        wind_dir = payload.wind_direction_deg or occ["wind_direction_deg"] or 0.0

        job_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO simulation_jobs (
                job_id, fire_id, duration_h, parameters_json, status
            )
            VALUES ($1, $2, $3, $4, 'pending')
            """,
            job_id, payload.fire_id, payload.duration_h, payload.model_dump(),
        )
        now = datetime.now(timezone.utc)

    asyncio.create_task(_run_and_update(
        job_id=job_id,
        pool=pool,
        lat=occ["latitude"],
        lon=occ["longitude"],
        wind_speed_ms=wind_speed,
        wind_dir_deg=wind_dir,
        wind_midflame_ms=occ["wind_midflame_ms"] or wind_speed * 0.4,
        temperature_c=occ["temperature_c"] or 25.0,
        humidity_pct=occ["relative_humidity_pct"] or 30.0,
        fm_1h=occ["fuel_moisture_1h_pct"],
        fm_10h=occ["fuel_moisture_10h_pct"],
        fm_100h=occ["fuel_moisture_100h_pct"],
        fm_live_h=occ["fuel_moisture_live_h_pct"],
        fm_live_w=occ["fuel_moisture_live_w_pct"],
        duration_h=payload.duration_h,
        bbox_km=payload.bbox_km or 15.0,
        landscape_dir=config.landscape_dir,
        landscape_file=config.landscape_file,
        use_gusts=payload.use_gusts,
        fuel_moisture_scenario=payload.fuel_moisture_scenario,
        weather_stream_text=payload.weather_stream_text,
        fuel_moisture_table_text=payload.fuel_moisture_table_text,
        start_time=payload.start_time,
    ))

    return SimulationJob(
        job_id=job_id,
        fire_id=payload.fire_id,
        status="pending",
        requested_at=now,
        duration_h=payload.duration_h,
    )


@router_jobs.get(
    "/{job_id}",
    response_model=SimulationJobDetail,
    summary="Estado e resultado de um job de simulação",
)
async def get_simulation_job(
    job_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM simulation_jobs WHERE job_id = $1",
            job_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Job não encontrado")

    result = None
    if row["result_json"] and row["status"] == "done":
        try:
            result = SimulationResultDetail(**row["result_json"])
        except Exception as exc:
            log.warning("Erro ao desserializar result_json de %s: %s", job_id, exc)

    return SimulationJobDetail(
        job_id=str(row["job_id"]),
        fire_id=row["fire_id"],
        status=row["status"],
        requested_at=row["requested_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_h=row["duration_h"],
        error_message=row["error_message"],
        result=result,
    )


async def _run_and_update(
    job_id: str,
    pool: asyncpg.Pool,
    lat: float,
    lon: float,
    wind_speed_ms: float,
    wind_dir_deg: float,
    wind_midflame_ms: float,
    temperature_c: float,
    humidity_pct: float,
    fm_1h: Optional[float],
    fm_10h: Optional[float],
    fm_100h: Optional[float],
    fm_live_h: Optional[float],
    fm_live_w: Optional[float],
    duration_h: float,
    bbox_km: float,
    landscape_dir: str,
    landscape_file: Optional[str] = None,
    use_gusts: bool = False,
    fuel_moisture_scenario: Optional[str] = None,
    weather_stream_text: Optional[str] = None,
    fuel_moisture_table_text: Optional[str] = None,
    start_time: Optional[datetime] = None,
):
    """Task em background: corre simulação e grava resultado no DB."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE simulation_jobs SET status='running', started_at=NOW() WHERE job_id=$1",
            job_id,
        )
    try:
        from fogos_triage.fuel_models import load_fuel_models_csv
        from fogos_triage.fuel_moisture_scenarios import apply_fuel_moisture_scenario
        from fogos_triage.fuel_moisture_table import parse_fuel_moisture_table
        from fogos_triage.landscape import LandscapeRasters, ensure_landscape
        from fogos_triage.schemas import WeatherConditions
        from fogos_triage.simulation import run_simulation_async
        from fogos_triage.triage import gust_weather
        from fogos_triage.lfmc_climatologia import lfmc_climatologia
        from fogos_triage.weather import (
            derive_fire_weather, fetch_precipitation_sum, fetch_weather_for_start_time,
        )
        from fogos_triage.weather_stream import parse_weather_stream

        import asyncio as _asyncio
        await _asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ensure_landscape(
                landscape_dir=landscape_dir,
                r2_account_id=os.environ.get("R2_ACCOUNT_ID"),
                r2_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
                r2_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
                r2_bucket=os.environ.get("R2_BUCKET", "fogos-landscape"),
                r2_prefix=os.environ.get("R2_PREFIX", "landscape/"),
                filename=landscape_file,
            ),
        )

        if landscape_file:
            rasters_kwargs = {"multiband_path": os.path.join(landscape_dir, landscape_file)}
        else:
            rasters_kwargs = {"rasters": LandscapeRasters.from_directory(landscape_dir)}

        fuel_dict = load_fuel_models_csv(
            os.environ.get("FUEL_MODELS_CSV", "/data/fuel_models_pt.csv")
        )

        n_hours = int(math.ceil(duration_h)) + 1

        if weather_stream_text:
            if start_time:
                log.warning(
                    "Simulação %s: start_time ignorado — Weather Stream já "
                    "tem a sua própria linha do tempo", job_id,
                )
            # Weather Stream File (.WXS) FARSITE — substitui o Open-Meteo
            # por inteiro; hora 0 = primeira linha do ficheiro (é um
            # cenário/timeline próprio, não alinhado ao instante actual).
            # Erro de parsing propaga-se e falha o job com mensagem clara
            # (mesmo padrão de run_simulation_async abaixo).
            raw_hourly = parse_weather_stream(weather_stream_text)
            if len(raw_hourly) - 1 < duration_h:
                raise ValueError(
                    f"Weather Stream: só cobre {len(raw_hourly) - 1}h, "
                    f"mas a simulação pediu {duration_h}h"
                )
            weather_source = "weather_stream"
        else:
            # Previsão horária do Open-Meteo (ou arquivo histórico, se
            # start_time for antigo — ver fetch_weather_for_start_time)
            # para toda a duração da simulação. Fallback para meteo única
            # da triagem se a API falhar.
            try:
                raw_hourly = await fetch_weather_for_start_time(lat, lon, start_time, hours_ahead=n_hours)
            except Exception as exc:
                log.warning("Open-Meteo falhou para simulação %s: %s — usando meteo da triagem", job_id, exc)
                raw_hourly = []
            weather_source = "open_meteo" if raw_hourly else "triagem"

        # Humidade viva: climatologia sazonal + precipitação acumulada a
        # 180 dias, para a data da simulação (ver lfmc_climatologia e
        # LFMC_CLIMATOLOGIA_PLAN.md).
        #
        # `start_time` é respeitado de propósito. As humidades mortas já
        # eram derivadas hora a hora da meteo da data pedida; o
        # combustível vivo era o único que ficava preso ao presente,
        # porque herdava o valor da triagem da ocorrência. Com o P180 a
        # vir do arquivo ERA5 (1940 até hoje), uma simulação de um
        # incêndio antigo passa a correr com o combustível vivo desse ano
        # — coisa que o satélite não permitia (o VNP09GA só existe desde
        # 2012).
        #
        # Se falhar, o valor da triagem é o fallback; se nem esse existir,
        # o motor usa os seus defaults.
        data_lfmc = start_time if (start_time and not weather_stream_text) else datetime.now()
        fmc_source = "triagem"
        p180_mm = await fetch_precipitation_sum(lat, lon, data_lfmc)
        if p180_mm is not None:
            fm_live_h, fm_live_w = lfmc_climatologia(data_lfmc.timetuple().tm_yday, p180_mm)
            fmc_source = "climatologia"
            log.info(
                "Simulação %s: LFMC climatologia para %s — herbáceo=%.0f%% "
                "lenhoso=%.0f%% (P180=%.0fmm)",
                job_id, data_lfmc.date(), fm_live_h, fm_live_w, p180_mm,
            )
        else:
            log.warning(
                "Simulação %s: sem precipitação acumulada para %s — mantém o da triagem",
                job_id, data_lfmc.date(),
            )

        if raw_hourly:
            # derive_fire_weather aplica Simard 1968 (humidades mortas) + WAF
            # para cada hora
            weather_hourly = [
                derive_fire_weather(
                    wx,
                    live_h_pct=fm_live_h,
                    live_w_pct=fm_live_w,
                )
                for wx in raw_hourly[:n_hours]
            ]
            log.info("Simulação %s: %d snapshots horários Open-Meteo", job_id, len(weather_hourly))
        else:
            # Fallback: meteo estática da triagem para toda a duração
            weather_hourly = [WeatherConditions(
                timestamp=datetime.now(timezone.utc),
                temperature_c=temperature_c,
                relative_humidity_pct=humidity_pct,
                wind_speed_10m_ms=wind_speed_ms,
                wind_gust_10m_ms=wind_speed_ms,
                wind_direction_deg=wind_dir_deg,
                precipitation_mm_24h=0.0,
                cloud_cover_pct=0.0,
                wind_midflame_ms=wind_midflame_ms,
                fuel_moisture_1h_pct=fm_1h,
                fuel_moisture_10h_pct=fm_10h,
                fuel_moisture_100h_pct=fm_100h,
                fuel_moisture_live_h_pct=fm_live_h,
                fuel_moisture_live_w_pct=fm_live_w,
            )]

        if use_gusts and weather_stream_text:
            log.warning(
                "Simulação %s: use_gusts ignorado — Weather Stream não tem "
                "coluna de rajada", job_id,
            )
        elif use_gusts:
            # Vento de rajada (Open-Meteo) em vez de sustentado, em todas
            # as horas — ver fogos_triage.triage.gust_weather.
            weather_hourly = [gust_weather(wx) for wx in weather_hourly]

        if fuel_moisture_scenario:
            # Cenário-padrão BehavePlus/NWCG em vez das humidades
            # calculadas, em todas as horas — ver
            # fogos_triage.fuel_moisture_scenarios.apply_fuel_moisture_scenario.
            weather_hourly = [
                apply_fuel_moisture_scenario(wx, fuel_moisture_scenario)
                for wx in weather_hourly
            ]

        fuel_moisture_table = None
        fuel_moisture_source = "calculado"
        if fuel_moisture_table_text:
            # Initial Fuel Moistures File (.FMS) FARSITE — humidade por
            # modelo de combustível, aplicada por ponto/vértice dentro de
            # run_simulation_async (ver fogos_triage.fuel_moisture_table).
            fuel_moisture_table = parse_fuel_moisture_table(fuel_moisture_table_text)
            fuel_moisture_source = "table"
        elif fuel_moisture_scenario:
            fuel_moisture_source = "scenario"

        result = await run_simulation_async(
            lat, lon, weather_hourly, fuel_dict, duration_h,
            bbox_km=bbox_km, fuel_moisture_table=fuel_moisture_table, **rasters_kwargs,
        )
        result["meta"]["use_gusts"] = use_gusts and not weather_stream_text
        result["meta"]["fuel_moisture_scenario"] = fuel_moisture_scenario
        result["meta"]["weather_source"] = weather_source
        result["meta"]["fuel_moisture_source"] = fuel_moisture_source
        # Distinto de fuel_moisture_source (que é sobre as MORTAS): diz se
        # o combustível vivo veio da triagem da ocorrência ou foi
        # recalculado no VIIRS para a data pedida. Sem isto não se
        # distingue uma simulação histórica correcta de uma que correu com
        # o verdor de hoje porque o GEE falhou.
        result["meta"]["live_fuel_moisture_source"] = fmc_source
        result["meta"]["live_fuel_moisture_h_pct"] = fm_live_h
        result["meta"]["live_fuel_moisture_w_pct"] = fm_live_w
        result["meta"]["start_time"] = (
            start_time.isoformat() if start_time and not weather_stream_text else None
        )

        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE simulation_jobs
                   SET status='done', completed_at=NOW(), result_json=$1
                   WHERE job_id=$2""",
                result,
                job_id,
            )
    except Exception as e:
        log.error("Simulação %s falhou: %s", job_id, e, exc_info=True)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE simulation_jobs
                   SET status='failed', completed_at=NOW(), error_message=$1
                   WHERE job_id=$2""",
                str(e),
                job_id,
            )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router_health.get(
    "/health",
    response_model=HealthResponse,
    summary="Healthcheck",
    description="Estado do serviço — usado pelo Railway/Docker para healthcheck.",
)
async def health(
    pool: asyncpg.Pool = Depends(get_pool),
    config: APIConfig = Depends(get_config),
):
    db_ok = False
    last_seen = None
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            db_ok = True
            # last_seen do worker = max(last_seen_at)
            last_seen = await conn.fetchval(
                "SELECT MAX(last_seen_at) FROM occurrences"
            )
    except Exception:
        db_ok = False

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=config.version,
        database_ok=db_ok,
        worker_last_seen_at=last_seen,
    )
