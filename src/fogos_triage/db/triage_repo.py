"""Repositório para resultados de triagem."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Optional

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

from ..schemas import TriageResult

log = logging.getLogger(__name__)


class TriageResultRepository:
    """Operações sobre triage_results."""

    def __init__(self, pool: "asyncpg.Pool"):
        if not HAS_ASYNCPG:
            raise ImportError("asyncpg é necessário")
        self.pool = pool

    async def save(self, result: TriageResult) -> int:
        """
        Guarda um resultado de triagem.
        Marca os anteriores como is_latest=FALSE.
        Devolve o id da nova linha.
        """
        central = result.central_prediction
        scenarios_json = [_prediction_to_dict(p) for p in result.predictions]

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Marcar anteriores como stale
                await conn.execute(
                    """
                    UPDATE triage_results
                    SET is_latest = FALSE
                    WHERE fire_id = $1 AND is_latest = TRUE
                    """,
                    result.occurrence.external_id,
                )

                # Inserir novo
                row = await conn.fetchrow(
                    """
                    INSERT INTO triage_results (
                        fire_id, elevation_m, slope_degrees, aspect_degrees,
                        fuel_model_num, fuel_model_code,
                        stand_height_m, canopy_cover_pct, canopy_base_height_m,
                        central_ros_m_per_min, central_fireline_intensity_kw_m,
                        central_flame_length_m, central_fire_type, central_direction_deg,
                        scenarios_json, priority_class, priority_score,
                        wind_midflame_ms, wind_adjustment_factor,
                        fuel_moisture_1h_pct, fuel_moisture_10h_pct,
                        fuel_moisture_100h_pct, fuel_moisture_live_h_pct,
                        fuel_moisture_live_w_pct, notes,
                        latitude, longitude
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9,
                        $10, $11, $12, $13, $14, $15, $16, $17, $18, $19,
                        $20, $21, $22, $23, $24, $25, $26, $27
                    )
                    RETURNING id
                    """,
                    result.occurrence.external_id,
                    result.terrain.elevation_m,
                    result.terrain.slope_degrees,
                    result.terrain.aspect_degrees,
                    result.terrain.fuel_model_num,
                    result.fuel_model_used,
                    result.terrain.stand_height_m,
                    result.terrain.canopy_cover_pct,
                    result.terrain.canopy_base_height_m,
                    central.ros_m_per_min,
                    central.fireline_intensity_kw_m,
                    central.flame_length_m,
                    central.fire_type.value,
                    central.direction_max_spread_deg,
                    scenarios_json,
                    str(result.priority.value),
                    result.priority_score,
                    result.weather.wind_midflame_ms,
                    result.wind_adjustment_factor,
                    result.weather.fuel_moisture_1h_pct,
                    result.weather.fuel_moisture_10h_pct,
                    result.weather.fuel_moisture_100h_pct,
                    result.weather.fuel_moisture_live_h_pct,
                    result.weather.fuel_moisture_live_w_pct,
                    result.notes,
                    # Guardadas para o congelamento da triagem poder
                    # detectar correcções de localização — ver
                    # OccurrenceRepository.needs_triage e migração 006.
                    result.occurrence.latitude,
                    result.occurrence.longitude,
                )
                return row["id"]

    async def get_latest_for_fire(self, fire_id: str) -> Optional[dict]:
        """Devolve o resultado mais recente para uma ocorrência."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM triage_results
                WHERE fire_id = $1 AND is_latest = TRUE
                """,
                fire_id,
            )
            return dict(row) if row else None


def _prediction_to_dict(p) -> dict:
    """Serializa FireBehaviorPrediction para JSON, lidando com Enum."""
    d = asdict(p)
    # FireType enum
    d["fire_type"] = p.fire_type.value
    return d
