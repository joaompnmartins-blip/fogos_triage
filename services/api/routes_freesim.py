"""
Endpoints de simulação livre — ignição definida à mão (ponto ou linha),
independente do fluxo de triagem/simulação ligado a ocorrências reais do
fogos.pt. Mesmo motor (fogos_triage.simulation, landscape files), fluxo
e persistência próprios (tabela free_simulation_jobs).
"""
from __future__ import annotations

import asyncio
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
    FreeSimulationJob,
    FreeSimulationJobDetail,
    FreeSimulationRequest,
    SimulationResultDetail,
)

log = logging.getLogger(__name__)

router_free_sim = APIRouter(prefix="/free-simulate", tags=["free-simulation"])
router_free_jobs = APIRouter(prefix="/free-jobs", tags=["free-simulation"])


@router_free_sim.post(
    "",
    response_model=FreeSimulationJob,
    summary="Cria job de simulação livre (ignição por ponto ou linha)",
    status_code=202,
)
async def create_free_simulation(
    payload: FreeSimulationRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    config: APIConfig = Depends(get_config),
    _: str = Depends(require_api_key),
):
    if not Path(config.landscape_dir).exists():
        raise HTTPException(
            status_code=501,
            detail="Simulação requer rasters reais (DEV_MODE não suportado)",
        )

    job_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO free_simulation_jobs (
                job_id, ignition_points_json, duration_h, parameters_json, status
            )
            VALUES ($1, $2, $3, $4, 'pending')
            """,
            job_id, payload.ignition_points, payload.duration_h, payload.model_dump(),
        )
    now = datetime.now(timezone.utc)

    asyncio.create_task(_run_free_simulation(
        job_id=job_id,
        pool=pool,
        ignition_points=payload.ignition_points,
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

    return FreeSimulationJob(
        job_id=job_id,
        ignition_points=payload.ignition_points,
        status="pending",
        requested_at=now,
        duration_h=payload.duration_h,
    )


@router_free_jobs.get(
    "/{job_id}",
    response_model=FreeSimulationJobDetail,
    summary="Estado e resultado de um job de simulação livre",
)
async def get_free_simulation_job(
    job_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM free_simulation_jobs WHERE job_id = $1",
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

    ignition_points = [tuple(p) for p in row["ignition_points_json"]]

    return FreeSimulationJobDetail(
        job_id=str(row["job_id"]),
        ignition_points=ignition_points,
        status=row["status"],
        requested_at=row["requested_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_h=row["duration_h"],
        error_message=row["error_message"],
        result=result,
    )


async def _run_free_simulation(
    job_id: str,
    pool: asyncpg.Pool,
    ignition_points: list[tuple[float, float]],
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
    """Task em background: corre simulação livre e grava resultado no DB.

    Sem ocorrência/triagem prévia associada: a meteo vem sempre do
    Open-Meteo ao vivo para o primeiro ponto de ignição (ou o único, se
    pontual) — sem override manual, ao contrário do fluxo ligado a
    ocorrências — a não ser que `weather_stream_text` seja dado, caso em
    que substitui o Open-Meteo por inteiro. Humidade viva do combustível
    tenta VIIRS/GEE, com fallback sazonal (mesmo caminho já usado em
    routes_meta._run_and_update).
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE free_simulation_jobs SET status='running', started_at=NOW() WHERE job_id=$1",
            job_id,
        )
    try:
        from fogos_triage.fuel_models import load_fuel_models_csv
        from fogos_triage.fuel_moisture_scenarios import apply_fuel_moisture_scenario
        from fogos_triage.fuel_moisture_table import parse_fuel_moisture_table
        from fogos_triage.landscape import LandscapeRasters, LandscapeReader, ensure_landscape
        from fogos_triage.simulation import run_simulation_async
        from fogos_triage.triage import gust_weather
        from fogos_triage.weather import (
            derive_fire_weather,
            fetch_live_fmc_viirs,
            fetch_weather_for_start_time,
        )
        from fogos_triage.weather_stream import parse_weather_stream

        lat, lon = ignition_points[0]

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

        # A ignição vem do utilizador (desenhada ou importada), por isso
        # pode cair fora do território coberto. O caso traiçoeiro é o
        # GeoJSON com lat/lon trocados: (39.5, -8.0) lido como lon/lat dá
        # um ponto perfeitamente válido no Índico, que passa por todas as
        # validações de intervalo e só se manifestaria como uma simulação
        # sem sentido. Verifica-se contra a extensão real do raster.
        with LandscapeReader(**rasters_kwargs) as _reader:
            outside = [(p_lat, p_lon) for p_lat, p_lon in ignition_points
                       if not _reader.contains(p_lat, p_lon)]
            bounds = _reader.bounds_wgs84
        if outside:
            p_lat, p_lon = outside[0]
            extent = (
                f" A landscape file cobre lon {bounds[0]:.2f}..{bounds[2]:.2f}, "
                f"lat {bounds[1]:.2f}..{bounds[3]:.2f}." if bounds else ""
            )
            raise ValueError(
                f"Ignição em (lat {p_lat:.4f}, lon {p_lon:.4f}) fora da área coberta "
                f"pela landscape file.{extent} Confirme que as coordenadas estão em "
                "EPSG:4326 (WGS84) e que latitude e longitude não estão trocadas."
            )

        fuel_dict = load_fuel_models_csv(
            os.environ.get("FUEL_MODELS_CSV", "/data/fuel_models_pt.csv")
        )

        n_hours = int(math.ceil(duration_h)) + 1

        if weather_stream_text:
            if start_time:
                log.warning(
                    "Simulação livre %s: start_time ignorado — Weather Stream "
                    "já tem a sua própria linha do tempo", job_id,
                )
            # Weather Stream File (.WXS) FARSITE — substitui o Open-Meteo
            # por inteiro; hora 0 = primeira linha do ficheiro.
            raw_hourly = parse_weather_stream(weather_stream_text)
            if len(raw_hourly) - 1 < duration_h:
                raise ValueError(
                    f"Weather Stream: só cobre {len(raw_hourly) - 1}h, "
                    f"mas a simulação pediu {duration_h}h"
                )
            weather_source = "weather_stream"
        else:
            try:
                raw_hourly = await fetch_weather_for_start_time(lat, lon, start_time, hours_ahead=n_hours)
            except Exception as exc:
                log.warning("Open-Meteo falhou para simulação livre %s: %s", job_id, exc)
                raw_hourly = []

            if not raw_hourly:
                raise RuntimeError(
                    "Open-Meteo indisponível — simulação livre requer meteo ao vivo "
                    "(sem ocorrência/triagem para usar como fallback)"
                )
            weather_source = "open_meteo"

        # Humidade viva: VIIRS/GEE se configurado, senão os valores fixos
        # 60%/80% de derive_fire_weather (NÃO são sazonais, ao contrário do
        # que este comentário dizia antes).
        #
        # Este caminho requer `earthengine-api` na imagem da API e as
        # GEE_SERVICE_ACCOUNT/GEE_KEY_JSON no serviço — sem uma das duas
        # coisas, o except abaixo engole a falha e a simulação corre com os
        # 60%/80%. Importa agora que FM231/FM232 são dinâmicos: 60% fixa a
        # fracção curada em ~0,66 o ano inteiro, sobrestimando a propagação
        # em herbáceas verdes na Primavera.
        # A data pedida, não a de hoje: o VIIRS compõe uma janela de 16
        # dias ANTES da data que lhe é dada, por isso passar-lhe sempre
        # `now` fazia uma simulação de Agosto correr com o verdor de
        # Fevereiro se fosse pedida em Fevereiro. Com as humidades mortas
        # já derivadas hora a hora da meteo histórica, o combustível vivo
        # era o único que ficava preso ao presente.
        fmc_date = start_time or datetime.now(timezone.utc)
        live_h_pct, live_w_pct = None, None
        try:
            live_fmc = await fetch_live_fmc_viirs(lat, lon, fmc_date)
            if live_fmc:
                live_h_pct, live_w_pct = live_fmc
                log.info(
                    "Simulação livre %s: LFMC VIIRS herbáceo=%.0f%% lenhoso=%.0f%% (janela até %s)",
                    job_id, live_h_pct, live_w_pct, fmc_date.date(),
                )
            else:
                log.warning(
                    "Simulação livre %s: VIIRS sem valor — a usar 60%%/80%% fixos", job_id,
                )
        except Exception as exc:
            log.warning("GEE LFMC falhou para simulação livre %s: %s", job_id, exc)

        weather_hourly = [
            derive_fire_weather(wx, live_h_pct=live_h_pct, live_w_pct=live_w_pct)
            for wx in raw_hourly[:n_hours]
        ]
        log.info("Simulação livre %s: %d snapshots horários Open-Meteo", job_id, len(weather_hourly))

        if use_gusts and weather_stream_text:
            log.warning(
                "Simulação livre %s: use_gusts ignorado — Weather Stream não "
                "tem coluna de rajada", job_id,
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
            bbox_km=bbox_km, ignition_points=ignition_points,
            fuel_moisture_table=fuel_moisture_table, **rasters_kwargs,
        )
        result["meta"]["use_gusts"] = use_gusts and not weather_stream_text
        result["meta"]["fuel_moisture_scenario"] = fuel_moisture_scenario
        result["meta"]["weather_source"] = weather_source
        result["meta"]["fuel_moisture_source"] = fuel_moisture_source
        result["meta"]["start_time"] = (
            start_time.isoformat() if start_time and not weather_stream_text else None
        )

        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE free_simulation_jobs
                   SET status='done', completed_at=NOW(), result_json=$1
                   WHERE job_id=$2""",
                result,
                job_id,
            )
    except Exception as e:
        log.error("Simulação livre %s falhou: %s", job_id, e, exc_info=True)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE free_simulation_jobs
                   SET status='failed', completed_at=NOW(), error_message=$1
                   WHERE job_id=$2""",
                str(e),
                job_id,
            )
