"""
Endpoints de suporte: fuel models, simulação ForeFire, healthcheck.
"""
from __future__ import annotations

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
    SimulationRequest,
)


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
    summary="Cria job de simulação ForeFire",
    description=(
        "Cria um job na fila para simulação detalhada com ForeFire. "
        "O runner consome a fila Redis e processa assincronamente. "
        "Consultar estado via GET /jobs/{job_id}."
    ),
    status_code=202,
)
async def create_simulation(
    payload: SimulationRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
):
    async with pool.acquire() as conn:
        # Verificar que a ocorrência existe
        occ = await conn.fetchrow(
            "SELECT fire_id, is_active, is_terminated FROM occurrences WHERE fire_id = $1",
            payload.fire_id,
        )
        if occ is None:
            raise HTTPException(status_code=404, detail="Ocorrência não encontrada")

        # Inserir job
        job_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO simulation_jobs (
                job_id, fire_id, duration_h, parameters_json, status
            )
            VALUES ($1, $2, $3, $4, 'pending')
            """,
            job_id, payload.fire_id, payload.duration_h,
            payload.model_dump(),
        )

    # TODO: empurrar para fila Redis quando o runner existir.
    # Por agora fica em "pending" eternamente para mostrar o ciclo de vida.

    return SimulationJob(
        job_id=job_id,
        fire_id=payload.fire_id,
        status="pending",
        requested_at=datetime.now(timezone.utc),
        duration_h=payload.duration_h,
    )


@router_jobs.get(
    "/{job_id}",
    response_model=SimulationJob,
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

    return SimulationJob(
        job_id=str(row["job_id"]),
        fire_id=row["fire_id"],
        status=row["status"],
        requested_at=row["requested_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_h=row["duration_h"],
        error_message=row["error_message"],
        perimeters_geojson=row["result_json"],
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
