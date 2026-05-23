"""
Simulação de propagação de fogo — Huygens / Richards (1990) sobre rasters.

O perímetro do fogo é um polígono cujos vértices se expandem a cada dt
usando as equações diferenciais de Richards, que aplicam a forma elíptica
de Anderson (1983) à taxa de propagação Rothermel em cada ponto.

Sistema de coordenadas: cálculo interno no CRS projetado dos rasters (m).
Inputs/outputs em WGS84 (lat/lon).
"""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

try:
    from shapely.geometry import MultiPolygon, Polygon, shape
    from shapely.validation import make_valid
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

try:
    import rasterio
    import rasterio.windows
    from rasterio.transform import rowcol
    from rasterio.warp import transform as rio_transform
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

from .engine import _max_spread_direction_from_phi, _rothermel_direct
from .fuel_models import FuelModelPT
from .landscape import LandscapeRasters
from .schemas import WeatherConditions, TerrainConditions

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Parâmetros de simulação
# ---------------------------------------------------------------------------

DT_MIN = 5.0
MAX_SEG_M = 150.0
MIN_SEG_M = 30.0
INIT_RADIUS_M = 75.0
N_INIT_VERTICES = 16


# ---------------------------------------------------------------------------
# Estruturas de output
# ---------------------------------------------------------------------------

@dataclass
class PerimeterSnapshot:
    t_h: float
    area_ha: float
    polygon_wgs84: dict


@dataclass
class SimulationResult:
    perimeters: list[PerimeterSnapshot]
    pixel_grid_geojson: dict
    meta: dict


# ---------------------------------------------------------------------------
# Elipse Anderson (1983) / FARSITE eq. [13]-[17]
# ---------------------------------------------------------------------------

def _ellipse_dims(ros_m_min: float, u_eff_ms: float) -> tuple[float, float, float]:
    """Calcula (a, b, c) do wavelet elíptico em m/min."""
    lb = 0.936 * math.exp(0.2566 * u_eff_ms) + 0.461 * math.exp(-0.1548 * u_eff_ms) - 0.397
    lb = max(1.0, min(8.0, lb))

    if lb > 1.0:
        hb = (lb + math.sqrt(lb * lb - 1.0)) / (lb - math.sqrt(lb * lb - 1.0))
    else:
        hb = 1.0

    a = 0.5 * (ros_m_min + ros_m_min / hb) / lb
    b = (ros_m_min + ros_m_min / hb) / 2.0
    c = b - ros_m_min / hb
    return a, b, c


# ---------------------------------------------------------------------------
# Richards (1990) eq. [1]-[2] — propagação de um vértice
# ---------------------------------------------------------------------------

def _richards_step(
    x_prev: float, y_prev: float,
    x_next: float, y_next: float,
    theta_rad: float,
    a: float, b: float, c: float,
) -> tuple[float, float]:
    """Taxa de propagação (Xt, Yt) em m/min para um vértice do perímetro."""
    xs = x_prev - x_next
    ys = y_prev - y_next

    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)

    p = xs * sin_t + ys * cos_t
    q = xs * cos_t - ys * sin_t

    denom_sq = b * b * p * p - a * a * q * q

    if denom_sq <= 1e-12:
        return c * sin_t, c * cos_t

    denom = math.sqrt(denom_sq)
    Xt = (a * a * cos_t * p - b * b * sin_t * q) / denom + c * sin_t
    Yt = (-a * a * sin_t * p - b * b * cos_t * q) / denom + c * cos_t
    return Xt, Yt


# ---------------------------------------------------------------------------
# Leitura de terreno em coordenadas projetadas
# ---------------------------------------------------------------------------

def _sample_terrain_projected(
    datasets: dict,
    px: float, py: float,
    fuel_models: dict[int, FuelModelPT],
) -> tuple[Optional[FuelModelPT], TerrainConditions]:
    """Lê terreno num ponto em coordenadas projectadas."""
    ref_ds = datasets["elevation"]

    def _read(name: str) -> Optional[float]:
        ds = datasets.get(name)
        if ds is None:
            return None
        try:
            row, col = rowcol(ds.transform, px, py)
            win = rasterio.windows.Window(col, row, 1, 1)
            arr = ds.read(1, window=win)
            val = float(arr[0, 0])
            if ds.nodata is not None and abs(val - ds.nodata) < 1:
                return None
            return val
        except Exception:
            return None

    elevation = _read("elevation") or 0.0
    slope_deg = _read("slope") or 0.0
    aspect_deg = _read("aspect") or 0.0
    fuel_num = int(_read("fuel_model") or 98)
    stand_height = _read("stand_height")
    canopy_cover = _read("canopy_cover")
    cbh = _read("canopy_base_height")
    cbd = _read("canopy_bulk_density")

    fm = fuel_models.get(fuel_num)
    terrain = TerrainConditions(
        elevation_m=elevation,
        slope_fraction=math.tan(math.radians(slope_deg)),
        slope_degrees=slope_deg,
        aspect_degrees=aspect_deg,
        fuel_model_num=fuel_num,
        fuel_model_code=fm.code if fm else f"FM{fuel_num}",
        stand_height_m=stand_height / 10.0 if stand_height is not None else None,
        canopy_cover_pct=canopy_cover,
        canopy_base_height_m=cbh / 10.0 if cbh is not None else None,
        canopy_bulk_density_kg_m3=cbd / 100.0 if cbd is not None else None,
    )
    return fm, terrain


# ---------------------------------------------------------------------------
# Pré-computa grelha ROS/FLI/chama para visualização
# ---------------------------------------------------------------------------

def _build_ros_grid(
    datasets: dict,
    fuel_models: dict[int, FuelModelPT],
    weather: WeatherConditions,
    cx_proj: float, cy_proj: float,
    bbox_km: float,
    resolution_m: float,
) -> dict:
    """
    Constrói uma GeoJSON FeatureCollection com uma célula por pixel (ros, fi, chama).
    Calculado para toda a grelha; clip ao perímetro feito depois.
    """
    half = bbox_km * 500.0
    ref_ds = datasets["elevation"]
    proj_crs = ref_ds.crs

    xs = np.arange(cx_proj - half + resolution_m / 2, cx_proj + half, resolution_m)
    ys = np.arange(cy_proj - half + resolution_m / 2, cy_proj + half, resolution_m)

    xx, yy = np.meshgrid(xs, ys)
    pts_x = xx.ravel()
    pts_y = yy.ravel()
    lons, lats = rio_transform(proj_crs, "EPSG:4326", pts_x, pts_y)

    m_1h   = (weather.fuel_moisture_1h_pct   or 8.0)  / 100.0
    m_10h  = (weather.fuel_moisture_10h_pct  or 9.0)  / 100.0
    m_100h = (weather.fuel_moisture_100h_pct or 10.0) / 100.0
    m_lh   = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
    m_lw   = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0
    wind_mf = weather.wind_midflame_ms or 0.0

    features = []
    for px, py, lon, lat in zip(pts_x, pts_y, lons, lats):
        fm, terrain = _sample_terrain_projected(datasets, px, py, fuel_models)
        if fm is None or fm.is_empty:
            ros, fi, flame = 0.0, 0.0, 0.0
        else:
            try:
                ros, fi, *_ = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=wind_mf,
                    slope_degrees=terrain.slope_degrees,
                )
                flame = 0.0775 * fi ** 0.46 if fi > 0 else 0.0
            except Exception:
                ros, fi, flame = 0.0, 0.0, 0.0

        d_lon = resolution_m / (111320.0 * math.cos(math.radians(lat)))
        d_lat = resolution_m / 111320.0
        square = [
            [lon - d_lon, lat - d_lat],
            [lon + d_lon, lat - d_lat],
            [lon + d_lon, lat + d_lat],
            [lon - d_lon, lat + d_lat],
            [lon - d_lon, lat - d_lat],
        ]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [square]},
            "properties": {
                "ros_m_min": round(ros, 3),
                "fi_kw_m":   round(fi, 1),
                "flame_m":   round(flame, 2),
            },
        })

    return {"type": "FeatureCollection", "features": features}


def _clip_grid_to_perimeter(grid_geojson: dict, perimeter_geojson: dict) -> dict:
    """Remove células fora do perímetro final."""
    if not HAS_SHAPELY:
        return grid_geojson
    try:
        perim = shape(perimeter_geojson)
        clipped = [
            f for f in grid_geojson["features"]
            if perim.intersects(shape(f["geometry"]))
        ]
        return {"type": "FeatureCollection", "features": clipped}
    except Exception:
        return grid_geojson


# ---------------------------------------------------------------------------
# Propagação Huygens — loop principal
# ---------------------------------------------------------------------------

def _propagate(
    datasets: dict,
    fuel_models: dict[int, FuelModelPT],
    weather: WeatherConditions,
    cx_proj: float, cy_proj: float,
    duration_h: float,
    snapshot_hours: list[float],
) -> list[PerimeterSnapshot]:
    """Propaga o fogo usando Richards (1990); devolve snapshots do perímetro."""
    proj_crs = datasets["elevation"].crs

    angles = [2 * math.pi * i / N_INIT_VERTICES for i in range(N_INIT_VERTICES)]
    verts = [
        (cx_proj + INIT_RADIUS_M * math.sin(a),
         cy_proj + INIT_RADIUS_M * math.cos(a))
        for a in angles
    ]

    m_1h   = (weather.fuel_moisture_1h_pct   or 8.0)  / 100.0
    m_10h  = (weather.fuel_moisture_10h_pct  or 9.0)  / 100.0
    m_100h = (weather.fuel_moisture_100h_pct or 10.0) / 100.0
    m_lh   = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
    m_lw   = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0
    wind_mf = weather.wind_midflame_ms or 0.0
    wind_dir = weather.wind_direction_deg

    snapshots: list[PerimeterSnapshot] = []
    snap_idx = 0
    t = 0.0
    total_min = duration_h * 60.0
    snap_minutes = [h * 60.0 for h in snapshot_hours]

    while t < total_min and len(verts) >= 3:
        while snap_idx < len(snap_minutes) and t >= snap_minutes[snap_idx]:
            snap = _make_snapshot(verts, snap_minutes[snap_idx] / 60.0, proj_crs)
            if snap:
                snapshots.append(snap)
            snap_idx += 1

        n = len(verts)
        new_verts = []

        for i in range(n):
            x_cur, y_cur = verts[i]
            x_prev, y_prev = verts[(i - 1) % n]
            x_next, y_next = verts[(i + 1) % n]

            fm, terrain = _sample_terrain_projected(datasets, x_cur, y_cur, fuel_models)

            if fm is None or fm.is_empty:
                new_verts.append((x_cur, y_cur))
                continue

            try:
                ros_m_min, fi_kw, phi_w, phi_s, _, sigma, eff_ms = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=wind_mf,
                    slope_degrees=terrain.slope_degrees,
                )
            except Exception:
                new_verts.append((x_cur, y_cur))
                continue

            if ros_m_min <= 0:
                new_verts.append((x_cur, y_cur))
                continue

            theta_deg = _max_spread_direction_from_phi(
                wind_direction_deg=wind_dir,
                aspect_degrees=terrain.aspect_degrees,
                phi_w=phi_w,
                phi_s=phi_s,
            )
            theta_rad = math.radians(theta_deg)

            a, b, c = _ellipse_dims(ros_m_min, eff_ms)
            Xt, Yt = _richards_step(x_prev, y_prev, x_next, y_next, theta_rad, a, b, c)
            new_verts.append((x_cur + Xt * DT_MIN, y_cur + Yt * DT_MIN))

        verts = new_verts
        t += DT_MIN
        verts = _rediscretize(verts)
        verts = _fix_crossovers(verts)

        if len(verts) < 3:
            log.warning("Simulação: polígono degenerado após crossover fix a t=%.1f min", t)
            break

    while snap_idx < len(snap_minutes):
        snap = _make_snapshot(verts, snap_minutes[snap_idx] / 60.0, proj_crs)
        if snap:
            snapshots.append(snap)
        snap_idx += 1

    return snapshots


def _make_snapshot(verts: list, t_h: float, proj_crs) -> Optional[PerimeterSnapshot]:
    """Converte vértices projetados num PerimeterSnapshot GeoJSON WGS84."""
    if len(verts) < 3:
        return None
    try:
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        lons, lats = rio_transform(proj_crs, "EPSG:4326", xs, ys)
        coords = list(zip(lons, lats))
        coords.append(coords[0])

        poly_geojson = {"type": "Polygon", "coordinates": [coords]}

        if HAS_SHAPELY:
            area_m2 = Polygon(list(zip(xs, ys))).area
            area_ha = area_m2 / 10000.0
        else:
            area_ha = 0.0

        return PerimeterSnapshot(t_h=t_h, area_ha=round(area_ha, 1), polygon_wgs84=poly_geojson)
    except Exception as e:
        log.warning("Simulação: erro ao criar snapshot t=%.1fh: %s", t_h, e)
        return None


def _rediscretize(verts: list) -> list:
    """Insere vértices em segmentos longos; remove em segmentos curtos."""
    n = len(verts)
    result = []
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        dist = math.hypot(x2 - x1, y2 - y1)
        result.append((x1, y1))
        if dist > MAX_SEG_M:
            n_insert = int(dist / MAX_SEG_M)
            for k in range(1, n_insert + 1):
                frac = k / (n_insert + 1)
                result.append((x1 + frac * (x2 - x1), y1 + frac * (y2 - y1)))
    cleaned = [result[0]]
    for pt in result[1:]:
        if math.hypot(pt[0] - cleaned[-1][0], pt[1] - cleaned[-1][1]) >= MIN_SEG_M:
            cleaned.append(pt)
    return cleaned


def _fix_crossovers(verts: list) -> list:
    """Usa Shapely para corrigir auto-intersecções; devolve maior componente."""
    if not HAS_SHAPELY or len(verts) < 3:
        return verts
    try:
        poly = Polygon(verts)
        if not poly.is_valid:
            poly = make_valid(poly)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda p: p.area)
        if poly.is_empty or not isinstance(poly, Polygon):
            return verts
        return list(poly.exterior.coords[:-1])
    except Exception:
        return verts


# ---------------------------------------------------------------------------
# Conversão WGS84 → CRS projetado
# ---------------------------------------------------------------------------

def _wgs84_to_proj(lat: float, lon: float, proj_crs) -> tuple[float, float]:
    xs, ys = rio_transform("EPSG:4326", proj_crs, [lon], [lat])
    return xs[0], ys[0]


# ---------------------------------------------------------------------------
# Ponto de entrada principal (síncrono — corre em thread)
# ---------------------------------------------------------------------------

def run_simulation_sync(
    lat: float,
    lon: float,
    weather: WeatherConditions,
    fuel_models: dict[int, FuelModelPT],
    rasters: LandscapeRasters,
    duration_h: float,
    bbox_km: float = 15.0,
    resolution_m: float = 100.0,
) -> dict:
    """Corre a simulação completa. Devolve dict para gravar em result_json."""
    if not HAS_RASTERIO or not HAS_SHAPELY:
        raise RuntimeError("rasterio e shapely são necessários para simulação espacial")

    snapshot_hours = [h for h in [1.0, 2.0, 3.0, 6.0] if h <= duration_h]
    if duration_h not in snapshot_hours:
        snapshot_hours.append(duration_h)
    snapshot_hours.sort()

    from .landscape import LandscapeReader
    with LandscapeReader(rasters) as reader:
        datasets = reader._datasets
        proj_crs = datasets["elevation"].crs

        cx, cy = _wgs84_to_proj(lat, lon, proj_crs)
        log.info("Simulação: ignição (%.4f, %.4f) → proj (%.0f, %.0f)", lat, lon, cx, cy)

        log.info("Simulação: a calcular grelha %.0fm (%.0f×%.0f km)...",
                 resolution_m, bbox_km, bbox_km)
        grid = _build_ros_grid(datasets, fuel_models, weather, cx, cy, bbox_km, resolution_m)

        log.info("Simulação: a propagar %.1fh (dt=%.0f min)...", duration_h, DT_MIN)
        snapshots = _propagate(datasets, fuel_models, weather, cx, cy, duration_h, snapshot_hours)

    if not snapshots:
        raise RuntimeError("Simulação não produziu perímetros válidos")

    final_perim = snapshots[-1].polygon_wgs84
    clipped_grid = _clip_grid_to_perimeter(grid, final_perim)

    log.info("Simulação concluída: %d perímetros, %d células",
             len(snapshots), len(clipped_grid["features"]))

    return {
        "perimeters": [
            {"t_h": s.t_h, "area_ha": s.area_ha, "geojson": s.polygon_wgs84}
            for s in snapshots
        ],
        "pixel_grid": clipped_grid,
        "meta": {
            "bbox_km":       bbox_km,
            "resolution_m":  resolution_m,
            "ignition":      [lat, lon],
            "wind_speed_ms": weather.wind_speed_10m_ms,
            "wind_dir_deg":  weather.wind_direction_deg,
            "duration_h":    duration_h,
        },
    }


async def run_simulation_async(
    lat: float,
    lon: float,
    weather: WeatherConditions,
    fuel_models: dict[int, FuelModelPT],
    rasters: LandscapeRasters,
    duration_h: float,
    bbox_km: float = 15.0,
    resolution_m: float = 100.0,
) -> dict:
    """Wrapper assíncrono — corre run_simulation_sync num executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        run_simulation_sync,
        lat, lon, weather, fuel_models, rasters, duration_h, bbox_km, resolution_m,
    )
