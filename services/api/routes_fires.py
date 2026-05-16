"""
Endpoints /fires e relacionados.

Exposição da lista priorizada e detalhe das ocorrências.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .deps import get_pool, require_api_key
from .schemas import (
    FireBehaviorDetail,
    FireBehaviorSummary,
    FireDetailResponse,
    FireHistoryItem,
    FireListItem,
    FireListResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONPoint,
    TerrainDetail,
    TriageDetail,
    TriageSummary,
    WeatherSummary,
)

router = APIRouter(prefix="/fires", tags=["fires"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tactic_category(flame_length_m: float) -> str:
    """Categoria táctica de Andrews & Rothermel."""
    if flame_length_m < 1.2:
        return "direct_attack_manual"
    elif flame_length_m < 2.4:
        return "direct_attack_difficult"
    elif flame_length_m < 3.4:
        return "indirect_attack_machinery"
    else:
        return "indirect_attack_only"


def _encode_cursor(score: float, fire_id: str) -> str:
    """Codifica cursor de paginação (score + fire_id como tiebreaker)."""
    payload = json.dumps({"s": score, "f": fire_id})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[float, str]:
    """Descodifica cursor."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return float(payload["s"]), str(payload["f"])
    except Exception:
        raise HTTPException(status_code=400, detail="Cursor inválido")


def _row_to_list_item(row: asyncpg.Record) -> FireListItem:
    """Converte uma linha da view active_fires_with_triage em FireListItem."""
    triage = None
    if row["priority_class"] is not None:
        central = FireBehaviorSummary(
            scenario="central",
            ros_m_per_min=row["central_ros_m_per_min"] or 0.0,
            ros_km_per_h=(row["central_ros_m_per_min"] or 0.0) * 0.06,
            fireline_intensity_kw_m=row["central_fireline_intensity_kw_m"] or 0.0,
            flame_length_m=row["central_flame_length_m"] or 0.0,
            fire_type=row["central_fire_type"] or "surface",
            direction_max_spread_deg=row.get("central_direction_deg") or 0.0,
            tactic_category=_tactic_category(row["central_flame_length_m"] or 0.0),
        )
        triage = TriageSummary(
            priority_class=row["priority_class"],
            priority_score=row["priority_score"],
            fuel_model_code=row["fuel_model_code"] or "",
            computed_at=row["triage_computed_at"],
            central=central,
            notes=[],
        )

    return FireListItem(
        fire_id=row["fire_id"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        location=row["location_text"] or "",
        district=row["district"] or "",
        municipality=row["municipality"] or "",
        parish=row["parish"] or "",
        locality=row["locality"],
        natureza_code=row["natureza_code"],
        natureza_name=row["natureza_name"] or "",
        status_code=row["status_code"],
        status_name=row["status_name"] or "",
        is_important=row["is_important"],
        operatives=row["operatives"],
        vehicles=row["vehicles"],
        aerial=row["aerial"],
        started_at=row["started_at"],
        updated_at=row["api_updated_at"],
        triage=triage,
    )


# ---------------------------------------------------------------------------
# GET /fires — lista priorizada
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=FireListResponse,
    summary="Lista priorizada de ocorrências ativas",
    description=(
        "Devolve ocorrências ativas, ordenadas por prioridade decrescente. "
        "Ocorrências sem triagem (naturezas não relevantes ou ainda não "
        "processadas) aparecem no fim."
    ),
)
async def list_fires(
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None, description="Cursor de paginação"),
    district: Optional[str] = Query(default=None, description="Filtrar por distrito"),
    min_priority: Optional[str] = Query(
        default=None,
        pattern="^P[1-4]$",
        description="Devolver apenas P1/P2/... e acima",
    ),
    only_triaged: bool = Query(default=False, description="Excluir ocorrências sem triagem"),
):
    # WHERE dinâmico.
    # NOTA: a view active_fires_with_triage já filtra is_active=TRUE e
    # NOT is_terminated internamente — não repetir essas condições aqui
    # (a view não expõe essas colunas).
    conditions = []
    params: list = []

    if district:
        params.append(district)
        conditions.append(f"district ILIKE ${len(params)}")

    if min_priority:
        # P1 → score >= 70, P2 → >= 50, P3 → >= 25, P4 → >= 0
        thresholds = {"P1": 70.0, "P2": 50.0, "P3": 25.0, "P4": 0.0}
        params.append(thresholds[min_priority])
        conditions.append(f"priority_score >= ${len(params)}")

    if only_triaged:
        conditions.append("priority_class IS NOT NULL")

    if cursor:
        score, fire_id = _decode_cursor(cursor)
        params.extend([score, fire_id])
        conditions.append(
            f"(priority_score < ${len(params)-1} "
            f"OR (priority_score = ${len(params)-1} AND fire_id > ${len(params)}))"
        )

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit + 1)  # pedir um a mais para saber se há próxima página

    query = f"""
        SELECT * FROM active_fires_with_triage
        {where_clause}
        ORDER BY priority_score DESC NULLS LAST, fire_id ASC
        LIMIT ${len(params)}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        # Total geral (sem paginação) — a view já filtra ativas/não-terminadas
        total_row = await conn.fetchrow(
            "SELECT COUNT(*) AS c FROM active_fires_with_triage"
        )
        total = total_row["c"] if total_row else 0

    has_more = len(rows) > limit
    items_rows = rows[:limit]

    next_cursor = None
    if has_more and items_rows:
        last = items_rows[-1]
        next_cursor = _encode_cursor(
            last["priority_score"] or 0.0,
            last["fire_id"],
        )

    return FireListResponse(
        items=[_row_to_list_item(r) for r in items_rows],
        total=total,
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# GET /fires/geo/within — query espacial GeoJSON
# ---------------------------------------------------------------------------


@router.get(
    "/geo/within",
    response_model=GeoJSONFeatureCollection,
    summary="Ocorrências dentro de uma bounding box (GeoJSON)",
)
async def fires_within_bbox(
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
    min_lat: float = Query(..., ge=-90, le=90),
    min_lng: float = Query(..., ge=-180, le=180),
    max_lat: float = Query(..., ge=-90, le=90),
    max_lng: float = Query(..., ge=-180, le=180),
    only_active: bool = Query(default=True),
):
    conditions = [
        "geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)",
    ]
    if only_active:
        conditions.append("is_active = TRUE AND NOT is_terminated")

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT o.fire_id, o.latitude, o.longitude, o.district, o.municipality,
               o.parish, o.natureza_code, o.natureza_name,
               o.status_code, o.status_name,
               o.operatives, o.vehicles, o.aerial,
               t.priority_class, t.priority_score,
               t.central_flame_length_m, t.central_fire_type
        FROM occurrences o
        LEFT JOIN triage_results t ON t.fire_id = o.fire_id AND t.is_latest = TRUE
        WHERE {where_clause}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, min_lng, min_lat, max_lng, max_lat)

    features = [
        GeoJSONFeature(
            id=r["fire_id"],
            geometry=GeoJSONPoint(coordinates=[r["longitude"], r["latitude"]]),
            properties={
                "fire_id": r["fire_id"],
                "district": r["district"],
                "municipality": r["municipality"],
                "parish": r["parish"],
                "natureza_code": r["natureza_code"],
                "natureza_name": r["natureza_name"],
                "status_code": r["status_code"],
                "status_name": r["status_name"],
                "operatives": r["operatives"],
                "vehicles": r["vehicles"],
                "aerial": r["aerial"],
                "priority_class": r["priority_class"],
                "priority_score": r["priority_score"],
                "flame_length_m": r["central_flame_length_m"],
                "fire_type": r["central_fire_type"],
            },
        )
        for r in rows
    ]

    return GeoJSONFeatureCollection(features=features)


# ---------------------------------------------------------------------------
# GET /fires/{fire_id} — detalhe completo
# ---------------------------------------------------------------------------


@router.get(
    "/{fire_id}",
    response_model=FireDetailResponse,
    summary="Detalhe completo de uma ocorrência",
)
async def get_fire_detail(
    fire_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
):
    async with pool.acquire() as conn:
        # 1. Ocorrência
        occ = await conn.fetchrow(
            "SELECT * FROM occurrences WHERE fire_id = $1",
            fire_id,
        )
        if occ is None:
            raise HTTPException(status_code=404, detail="Ocorrência não encontrada")

        # 2. Triagem mais recente
        tri = await conn.fetchrow(
            """
            SELECT * FROM triage_results
            WHERE fire_id = $1 AND is_latest = TRUE
            """,
            fire_id,
        )

        # 3. Meteo mais recente
        wx = await conn.fetchrow(
            """
            SELECT * FROM weather_snapshots
            WHERE fire_id = $1
            ORDER BY snapshot_at DESC LIMIT 1
            """,
            fire_id,
        )

    triage_detail = None
    if tri is not None:
        scenarios_json = tri["scenarios_json"]
        scenarios = [
            FireBehaviorDetail(
                scenario=s["scenario"],
                ros_m_per_min=s["ros_m_per_min"],
                ros_km_per_h=s["ros_m_per_min"] * 0.06,
                fireline_intensity_kw_m=s["fireline_intensity_kw_m"],
                flame_length_m=s["flame_length_m"],
                heat_per_unit_area_kj_m2=s["heat_per_unit_area_kj_m2"],
                reaction_intensity_kw_m2=s["reaction_intensity_kw_m2"],
                direction_max_spread_deg=s["direction_max_spread_deg"],
                effective_wind_ms=s["effective_wind_ms"],
                fire_type=s["fire_type"],
                tactic_category=_tactic_category(s["flame_length_m"]),
            )
            for s in scenarios_json
        ]

        weather_summary = WeatherSummary(
            temperature_c=wx["temperature_c"] if wx else None,
            relative_humidity_pct=wx["relative_humidity_pct"] if wx else None,
            wind_speed_ms=wx["wind_speed_ms"] if wx else None,
            wind_speed_kmh=wx["wind_speed_kmh"] if wx else None,
            wind_direction_deg=wx["wind_direction_deg"] if wx else None,
            wind_direction_text=wx["wind_direction_text"] if wx else None,
            source=wx["source"] if wx else "unknown",
            station_location=wx["ipma_station_location"] if wx else None,
            station_distance_km=wx["ipma_station_distance_km"] if wx else None,
            observation_at=wx["observation_at"] if wx else None,
        )

        triage_detail = TriageDetail(
            computed_at=tri["computed_at"],
            priority_class=tri["priority_class"],
            priority_score=tri["priority_score"],
            fuel_model_code=tri["fuel_model_code"] or "",
            fuel_model_num=tri["fuel_model_num"] or 0,
            terrain=TerrainDetail(
                elevation_m=tri["elevation_m"] or 0,
                slope_degrees=tri["slope_degrees"] or 0,
                aspect_degrees=tri["aspect_degrees"] or 0,
                fuel_model_num=tri["fuel_model_num"] or 0,
                fuel_model_code=tri["fuel_model_code"] or "",
                stand_height_m=tri["stand_height_m"],
                canopy_cover_pct=tri["canopy_cover_pct"],
                canopy_base_height_m=tri["canopy_base_height_m"],
            ),
            weather=weather_summary,
            wind_midflame_ms=tri["wind_midflame_ms"],
            wind_adjustment_factor=tri["wind_adjustment_factor"],
            fuel_moisture_1h_pct=tri["fuel_moisture_1h_pct"],
            scenarios=scenarios,
            notes=tri["notes"] or [],
        )

    return FireDetailResponse(
        fire_id=occ["fire_id"],
        sado_id=occ["sado_id"],
        sharepoint_id=occ["sharepoint_id"],
        latitude=occ["latitude"],
        longitude=occ["longitude"],
        location=occ["location_text"] or "",
        district=occ["district"] or "",
        municipality=occ["municipality"] or "",
        parish=occ["parish"] or "",
        locality=occ["locality"],
        region=occ["region"],
        subregion=occ["subregion"],
        dico=occ["dico"],
        natureza_code=occ["natureza_code"],
        natureza_name=occ["natureza_name"] or "",
        status_code=occ["status_code"],
        status_name=occ["status_name"] or "",
        is_active=occ["is_active"],
        is_important=occ["is_important"],
        is_terminated=occ["is_terminated"],
        operatives=occ["operatives"],
        vehicles=occ["vehicles"],
        aerial=occ["aerial"],
        heli_fight=occ["heli_fight"],
        heli_coord=occ["heli_coord"],
        plane_fight=occ["plane_fight"],
        water_means=occ["water_means"],
        started_at=occ["started_at"],
        api_updated_at=occ["api_updated_at"],
        first_seen_at=occ["first_seen_at"],
        last_seen_at=occ["last_seen_at"],
        triage=triage_detail,
    )


# ---------------------------------------------------------------------------
# GET /fires/{fire_id}/history — histórico de mudanças
# ---------------------------------------------------------------------------


@router.get(
    "/{fire_id}/history",
    response_model=list[FireHistoryItem],
    summary="Histórico de mudanças (estado, recursos)",
)
async def get_fire_history(
    fire_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    _: str = Depends(require_api_key),
    limit: int = Query(default=100, ge=1, le=500),
):
    async with pool.acquire() as conn:
        # Verificar que a ocorrência existe
        exists = await conn.fetchval(
            "SELECT 1 FROM occurrences WHERE fire_id = $1", fire_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Ocorrência não encontrada")

        rows = await conn.fetch(
            """
            SELECT snapshot_at, change_type,
                   status_code, status_name, previous_status_code,
                   operatives, vehicles, aerial, heli_fight, plane_fight
            FROM occurrence_history
            WHERE fire_id = $1
            ORDER BY snapshot_at DESC
            LIMIT $2
            """,
            fire_id, limit,
        )

    return [
        FireHistoryItem(
            snapshot_at=r["snapshot_at"],
            change_type=r["change_type"],
            status_code=r["status_code"],
            status_name=r["status_name"] or "",
            previous_status_code=r["previous_status_code"],
            operatives=r["operatives"] or 0,
            vehicles=r["vehicles"] or 0,
            aerial=r["aerial"] or 0,
            heli_fight=r["heli_fight"] or 0,
            plane_fight=r["plane_fight"] or 0,
        )
        for r in rows
    ]
