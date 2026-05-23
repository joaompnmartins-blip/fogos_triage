# Simulação de Propagação de Incêndio — Implementação Completa

Implementação de um motor de simulação tipo FARSITE (Finney 1998) usando o
princípio de Huygens com as equações de Richards (1990) para propagar o
perímetro do fogo como um polígono vetorial ao longo do tempo.

---

## Arquitectura

```
POST /simulate  →  cria job (pending)  →  asyncio.create_task  →  run_simulation()
                                                                       │
                                                  ┌────────────────────┴──────────────────┐
                                                  │ simulation.py                         │
                                                  │  1. lê rasters na bbox               │
                                                  │  2. pré-computa grelha ROS/FLI       │
                                                  │  3. propaga Huygens (Richards 1990)  │
                                                  │  4. grava result_json no DB          │
                                                  └───────────────────────────────────────┘
GET /jobs/:id   →  devolve status + result_json (perimeters + pixel_grid)
                                                  ↑
                         frontend faz polling a cada 2s
```

**Componentes por criar / modificar:**

| Ficheiro | Acção |
|---|---|
| `src/fogos_triage/simulation.py` | NOVO — motor de simulação |
| `services/api/routes_meta.py` | ALTERAR — POST /simulate lança simulação real |
| `services/api/schemas.py` | ALTERAR — SimulationResult com pixel_grid |
| `frontend/src/api.js` | ALTERAR — postSimulate, getJob |
| `frontend/src/views/SimulacaoView.jsx` | NOVO — vista mapa + painel |
| `frontend/src/App.jsx` | ALTERAR — nova rota + Topbar |
| `frontend/src/views/DetalheView.jsx` | ALTERAR — botão "Simular" |

---

## Dependências Python

```bash
# Já presentes: rasterio, numpy, shapely (verificar)
pip install shapely   # geometria vetorial (crossovers, union)
# numpy já vem com rasterio
```

Adicionar ao `requirements.txt` / `pyproject.toml` do worker e da api:
```
shapely>=2.0
```

---

## 1. `src/fogos_triage/simulation.py`

Motor completo: pré-computa grelha ROS/FLI por célula e propaga o perímetro
com as equações de Richards (1990) sobre o raster de terreno real.

```python
"""
Simulação de propagação de fogo — Huygens / Richards (1990) sobre rasters.

Princípio:
  O perímetro do fogo é um polígono cujos vértices se expandem a cada dt
  usando as equações diferenciais de Richards, que aplicam a forma elíptica
  de Anderson (1983) à taxa de propagação Rothermel em cada ponto.

Sistema de coordenadas:
  Todo o cálculo interno é no CRS projetado dos rasters (metros).
  Inputs/outputs em WGS84 (lat/lon).
"""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    from shapely.geometry import (
        LinearRing, MultiPolygon, Point, Polygon, mapping, shape
    )
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

try:
    import rasterio
    from rasterio.warp import transform as rio_transform
    from rasterio.transform import rowcol, xy as rasterio_xy
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

from .engine import _rothermel_direct, _max_spread_direction_from_phi
from .fuel_models import FuelModelPT
from .landscape import LandscapeReader, LandscapeRasters
from .schemas import WeatherConditions, TerrainConditions

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Parâmetros de simulação
# ---------------------------------------------------------------------------

DT_MIN = 5.0          # passo de tempo (minutos)
MAX_SEG_M = 150.0     # distância máxima entre vértices (m) — rediscretização
MIN_SEG_M = 30.0      # distância mínima — remoção de vértices desnecessários
INIT_RADIUS_M = 75.0  # raio inicial do círculo de ignição (m)
N_INIT_VERTICES = 16  # vértices do círculo inicial


# ---------------------------------------------------------------------------
# Estruturas de output
# ---------------------------------------------------------------------------

@dataclass
class PerimeterSnapshot:
    t_h: float
    area_ha: float
    polygon_wgs84: dict       # GeoJSON Polygon


@dataclass
class SimulationResult:
    perimeters: list[PerimeterSnapshot]
    pixel_grid_geojson: dict  # GeoJSON FeatureCollection (cells dentro do perímetro final)
    meta: dict


# ---------------------------------------------------------------------------
# Elipse Anderson 1983 / FARSITE eq. [13]-[17]
# ---------------------------------------------------------------------------

def _ellipse_dims(ros_m_min: float, u_eff_ms: float) -> tuple[float, float, float]:
    """
    Calcula as dimensões do wavelet elíptico (a, b, c) em m/min.

    u_eff_ms: vento efetivo combinado (vento + declive) em m/s.
    Devolve (a, b, c) com a=semi-eixo lateral, b=semi-eixo forward, c=offset ignição.
    """
    # LB — Anderson (1983), modificado FARSITE: -0.397 para LB=1 com U=0
    lb = 0.936 * math.exp(0.2566 * u_eff_ms) + 0.461 * math.exp(-0.1548 * u_eff_ms) - 0.397
    lb = max(1.0, min(8.0, lb))  # clamp [1, 8]

    # HB — relação head/back
    hb = (lb + math.sqrt(lb * lb - 1.0)) / (lb - math.sqrt(lb * lb - 1.0)) if lb > 1.0 else 1.0

    # dimensões em m/min (eq. [15]-[17])
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
    """
    Taxa de propagação (Xt, Yt) em m/min para um vértice do perímetro.

    x_prev, y_prev: vértice anterior (i-1)
    x_next, y_next: vértice seguinte (i+1)
    theta_rad: azimute de máxima propagação (radianos, Norte=0, CW)
    a, b, c: dimensões da elipse em m/min

    Sem correcção de terreno inclinado (v1 — assume-se pequena distorção).
    """
    # Diferenciais da normal ao perímetro (xs, ys)
    xs = x_prev - x_next
    ys = y_prev - y_next

    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)

    # Projecções no referencial da elipse
    p = xs * sin_t + ys * cos_t   # componente paralela ao eixo principal
    q = xs * cos_t - ys * sin_t   # componente perpendicular

    denom_sq = b * b * p * p - a * a * q * q

    if denom_sq <= 1e-12:
        # vértice alinhado com a direcção backing — propaga apenas c
        return c * sin_t, c * cos_t

    denom = math.sqrt(denom_sq)

    Xt = (a * a * cos_t * p - b * b * sin_t * q) / denom + c * sin_t
    Yt = (-a * a * sin_t * p - b * b * cos_t * q) / denom + c * cos_t

    return Xt, Yt


# ---------------------------------------------------------------------------
# Leitura de terreno num ponto (CRS projetado)
# ---------------------------------------------------------------------------

def _sample_terrain_projected(
    datasets: dict,
    px: float, py: float,         # coordenadas no CRS dos rasters
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
        slope_degrees=slope_deg,
        aspect_degrees=aspect_deg,
        fuel_model_num=fuel_num,
        fuel_model_code=fm.code if fm else f"FM{fuel_num}",
        stand_height_m=stand_height,
        canopy_cover_pct=canopy_cover,
        canopy_base_height_m=cbh,
        canopy_bulk_density_kg_m3=cbd,
    )
    return fm, terrain


# ---------------------------------------------------------------------------
# Pré-computa grelha ROS/FLI/chama para visualização
# ---------------------------------------------------------------------------

def _build_ros_grid(
    datasets: dict,
    fuel_models: dict[int, FuelModelPT],
    weather: WeatherConditions,
    cx_proj: float, cy_proj: float,   # centro em CRS projetado
    bbox_km: float,
    resolution_m: float,
) -> dict:
    """
    Constrói uma GeoJSON FeatureCollection com uma célula por pixel,
    cada célula com ros_m_min, fi_kw_m, flame_m.

    Calculado para TODA a grelha (não apenas a área ardida — o clip é feito
    depois com o perímetro final).
    """
    half = bbox_km * 500.0   # metade da bbox em metros
    ref_ds = datasets["elevation"]
    proj_crs = ref_ds.crs

    # Grelha de pontos centrais das células
    xs = np.arange(cx_proj - half + resolution_m / 2,
                   cx_proj + half,
                   resolution_m)
    ys = np.arange(cy_proj - half + resolution_m / 2,
                   cy_proj + half,
                   resolution_m)

    # Converter todos os pontos de uma vez para WGS84
    xx, yy = np.meshgrid(xs, ys)
    pts_x = xx.ravel()
    pts_y = yy.ravel()
    lons, lats = rio_transform(proj_crs, "EPSG:4326", pts_x, pts_y)

    features = []
    half_r = resolution_m / 2.0

    for i, (px, py, lon, lat) in enumerate(zip(pts_x, pts_y, lons, lats)):
        fm, terrain = _sample_terrain_projected(datasets, px, py, fuel_models)
        if fm is None or fm.is_empty:
            ros, fi, flame = 0.0, 0.0, 0.0
        else:
            m_1h  = (weather.fuel_moisture_1h_pct  or 8.0)  / 100.0
            m_10h = (weather.fuel_moisture_10h_pct or 9.0)  / 100.0
            m_100h= (weather.fuel_moisture_100h_pct or 10.0)/ 100.0
            m_lh  = (weather.fuel_moisture_live_h_pct or 100.0)/ 100.0
            m_lw  = (weather.fuel_moisture_live_w_pct or 100.0)/ 100.0
            try:
                ros_ft, fi_kw, phi_w, phi_s, _, sigma, eff_ms = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=weather.wind_midflame_ms or 0.0,
                    slope_degrees=terrain.slope_degrees,
                )
                ros   = ros_ft
                fi    = fi_kw
                flame = 0.0775 * fi_kw ** 0.46 if fi_kw > 0 else 0.0
            except Exception:
                ros, fi, flame = 0.0, 0.0, 0.0

        # Quadrado em WGS84 (aproximação — válida para bbox pequenas)
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
            }
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
    """
    Propaga o fogo usando Richards (1990) a partir de (cx_proj, cy_proj).
    Devolve snapshots do perímetro às horas indicadas em snapshot_hours.
    """
    proj_crs = datasets["elevation"].crs

    # Círculo inicial de ignição
    angles = [2 * math.pi * i / N_INIT_VERTICES for i in range(N_INIT_VERTICES)]
    verts = [
        (cx_proj + INIT_RADIUS_M * math.sin(a),
         cy_proj + INIT_RADIUS_M * math.cos(a))
        for a in angles
    ]

    snapshots: list[PerimeterSnapshot] = []
    snap_idx = 0
    t = 0.0
    total_min = duration_h * 60.0
    snap_minutes = [h * 60.0 for h in snapshot_hours]

    m_1h  = (weather.fuel_moisture_1h_pct  or 8.0)  / 100.0
    m_10h = (weather.fuel_moisture_10h_pct or 9.0)  / 100.0
    m_100h= (weather.fuel_moisture_100h_pct or 10.0)/ 100.0
    m_lh  = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
    m_lw  = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0

    while t < total_min and len(verts) >= 3:
        # --- Guardar snapshot antes do passo (se a hora chegou) ---
        while snap_idx < len(snap_minutes) and t >= snap_minutes[snap_idx]:
            snap = _make_snapshot(verts, snap_minutes[snap_idx] / 60.0, proj_crs)
            if snap:
                snapshots.append(snap)
            snap_idx += 1

        # --- Propagar cada vértice ---
        n = len(verts)
        new_verts = []

        for i in range(n):
            x_cur, y_cur = verts[i]
            x_prev, y_prev = verts[(i - 1) % n]
            x_next, y_next = verts[(i + 1) % n]

            # Terreno local
            fm, terrain = _sample_terrain_projected(datasets, x_cur, y_cur, fuel_models)

            if fm is None or fm.is_empty:
                new_verts.append((x_cur, y_cur))
                continue

            try:
                ros_m_min, fi_kw, phi_w, phi_s, _, sigma, eff_ms = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=weather.wind_midflame_ms or 0.0,
                    slope_degrees=terrain.slope_degrees,
                )
            except Exception:
                new_verts.append((x_cur, y_cur))
                continue

            if ros_m_min <= 0:
                new_verts.append((x_cur, y_cur))
                continue

            # Direcção de máxima propagação
            theta_deg = _max_spread_direction_from_phi(
                wind_direction_deg=weather.wind_direction_deg or 0.0,
                aspect_degrees=terrain.aspect_degrees,
                phi_w=phi_w,
                phi_s=phi_s,
            )
            theta_rad = math.radians(theta_deg)

            # Dimensões da elipse
            a, b, c = _ellipse_dims(ros_m_min, eff_ms)

            # Richards
            Xt, Yt = _richards_step(
                x_prev, y_prev, x_next, y_next,
                theta_rad, a, b, c
            )

            new_verts.append((x_cur + Xt * DT_MIN, y_cur + Yt * DT_MIN))

        verts = new_verts
        t += DT_MIN

        # --- Rediscretização ---
        verts = _rediscretize(verts)

        # --- Correcção topológica (crossovers) via Shapely ---
        verts = _fix_crossovers(verts)
        if len(verts) < 3:
            log.warning("Simulação: polígono degenerado após crossover fix a t=%.1f min", t)
            break

    # Snapshots restantes
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
        coords.append(coords[0])  # fechar o anel

        poly_geojson = {"type": "Polygon", "coordinates": [coords]}

        # Área em hectares
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
    """
    Insere vértices no meio dos segmentos longos (> MAX_SEG_M).
    Remove vértices desnecessários em segmentos curtos (< MIN_SEG_M).
    """
    n = len(verts)
    result = []
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        dist = math.hypot(x2 - x1, y2 - y1)
        result.append((x1, y1))
        if dist > MAX_SEG_M:
            # Inserir ponto(s) intermédios
            n_insert = int(dist / MAX_SEG_M)
            for k in range(1, n_insert + 1):
                frac = k / (n_insert + 1)
                result.append((x1 + frac * (x2 - x1), y1 + frac * (y2 - y1)))
    # Remover duplicados muito próximos
    cleaned = [result[0]]
    for pt in result[1:]:
        if math.hypot(pt[0] - cleaned[-1][0], pt[1] - cleaned[-1][1]) >= MIN_SEG_M:
            cleaned.append(pt)
    return cleaned


def _fix_crossovers(verts: list) -> list:
    """
    Usa Shapely para corrigir auto-intersecções do polígono.
    Devolve a maior componente válida.
    """
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
        return list(poly.exterior.coords[:-1])  # sem vértice de fecho repetido
    except Exception:
        return verts


# ---------------------------------------------------------------------------
# Converter ponto WGS84 para CRS projetado dos rasters
# ---------------------------------------------------------------------------

def _wgs84_to_proj(lat: float, lon: float, proj_crs) -> tuple[float, float]:
    xs, ys = rio_transform("EPSG:4326", proj_crs, [lon], [lat])
    return xs[0], ys[0]


# ---------------------------------------------------------------------------
# Ponto de entrada principal (corre em thread)
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
    """
    Corre a simulação completa num thread síncrono.
    Devolve dict pronto para gravar em result_json.
    """
    if not HAS_RASTERIO or not HAS_SHAPELY:
        raise RuntimeError("rasterio e shapely são necessários para simulação espacial")

    snapshot_hours = [h for h in [1.0, 2.0, 3.0, 6.0] if h <= duration_h]
    if duration_h not in snapshot_hours:
        snapshot_hours.append(duration_h)
    snapshot_hours.sort()

    with LandscapeReader(rasters) as reader:
        datasets = reader._datasets
        proj_crs = datasets["elevation"].crs

        cx, cy = _wgs84_to_proj(lat, lon, proj_crs)
        log.info("Simulação: ignição (%.4f, %.4f) → proj (%.0f, %.0f)", lat, lon, cx, cy)

        # 1. Grelha ROS/FLI
        log.info("Simulação: a calcular grelha %.0fm (%.0f×%.0f km)...",
                 resolution_m, bbox_km, bbox_km)
        grid = _build_ros_grid(datasets, fuel_models, weather, cx, cy, bbox_km, resolution_m)

        # 2. Propagação Huygens
        log.info("Simulação: a propagar %.1fh (dt=%.0f min)...", duration_h, DT_MIN)
        snapshots = _propagate(datasets, fuel_models, weather, cx, cy, duration_h, snapshot_hours)

    if not snapshots:
        raise RuntimeError("Simulação não produziu perímetros válidos")

    # 3. Clip da grelha ao perímetro final
    final_perim = snapshots[-1].polygon_wgs84
    clipped_grid = _clip_grid_to_perimeter(grid, final_perim)

    log.info("Simulação concluída: %d perímetros, %d células",
             len(snapshots), len(clipped_grid["features"]))

    return {
        "perimeters": [
            {
                "t_h":     s.t_h,
                "area_ha": s.area_ha,
                "geojson": s.polygon_wgs84,
            }
            for s in snapshots
        ],
        "pixel_grid": clipped_grid,
        "meta": {
            "bbox_km":        bbox_km,
            "resolution_m":   resolution_m,
            "ignition":       [lat, lon],
            "wind_speed_ms":  weather.wind_speed_ms,
            "wind_dir_deg":   weather.wind_direction_deg,
            "duration_h":     duration_h,
        }
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
```

---

## 2. `services/api/routes_meta.py` — POST /simulate

Substituir o stub `TODO: empurrar para Redis` pelo lançamento real:

```python
# Adicionar aos imports no topo do ficheiro
import json
import asyncio
from datetime import datetime, timezone

from ..simulation import run_simulation_async   # novo
from fogos_triage.landscape import LandscapeRasters
from fogos_triage.fuel_models import load_fuel_models_csv
from fogos_triage.schemas import WeatherConditions

# Substitui create_simulation() inteiro:

@router_sim.post("", response_model=SimulationJob, status_code=202)
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

        # Override de meteo se pedido
        wind_speed = payload.wind_speed_ms or occ["wind_speed_ms"] or 3.0
        wind_dir   = payload.wind_direction_deg or occ["wind_direction_deg"] or 0.0

        job_id = str(uuid.uuid4())
        await conn.execute(
            """INSERT INTO simulation_jobs
               (job_id, fire_id, duration_h, parameters_json, status)
               VALUES ($1, $2, $3, $4, 'pending')""",
            job_id, payload.fire_id, payload.duration_h, payload.model_dump(),
        )
        now = datetime.now(timezone.utc)

    # Lançar simulação em background
    asyncio.create_task(_run_and_update(
        job_id=job_id,
        pool=pool,
        lat=occ["latitude"],
        lon=occ["longitude"],
        weather=WeatherConditions(
            wind_speed_ms=wind_speed,
            wind_direction_deg=wind_dir,
            wind_midflame_ms=occ["wind_midflame_ms"] or wind_speed * 0.4,
            temperature_c=occ["temperature_c"],
            relative_humidity_pct=occ["relative_humidity_pct"],
            fuel_moisture_1h_pct=occ["fuel_moisture_1h_pct"],
            fuel_moisture_10h_pct=occ["fuel_moisture_10h_pct"],
            fuel_moisture_100h_pct=occ["fuel_moisture_100h_pct"],
            fuel_moisture_live_h_pct=occ["fuel_moisture_live_h_pct"],
            fuel_moisture_live_w_pct=occ["fuel_moisture_live_w_pct"],
        ),
        duration_h=payload.duration_h,
        bbox_km=payload.bbox_km or 15.0,
        landscape_dir=config.landscape_dir,   # acrescentar ao APIConfig
    ))

    return SimulationJob(
        job_id=job_id, fire_id=payload.fire_id,
        status="pending", requested_at=now, duration_h=payload.duration_h,
    )


async def _run_and_update(
    job_id: str,
    pool: asyncpg.Pool,
    lat: float, lon: float,
    weather: WeatherConditions,
    duration_h: float,
    bbox_km: float,
    landscape_dir: str,
):
    """Task em background: corre simulação e grava resultado no DB."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE simulation_jobs SET status='running', started_at=NOW() WHERE job_id=$1",
            job_id,
        )
    try:
        from fogos_triage.landscape import LandscapeRasters
        from fogos_triage.fuel_models import load_fuel_models_csv
        import os

        rasters = LandscapeRasters.from_directory(landscape_dir)
        fuel_models = load_fuel_models_csv(
            os.environ.get("FUEL_MODELS_CSV", "/data/fuel_models_pt.csv")
        )
        fuel_dict = {fm.num: fm for fm in fuel_models}

        result = await run_simulation_async(
            lat, lon, weather, fuel_dict, rasters, duration_h, bbox_km,
        )

        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE simulation_jobs
                   SET status='done', completed_at=NOW(), result_json=$1
                   WHERE job_id=$2""",
                json.dumps(result), job_id,
            )
    except Exception as e:
        log.error("Simulação %s falhou: %s", job_id, e, exc_info=True)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE simulation_jobs
                   SET status='failed', completed_at=NOW(), error_message=$1
                   WHERE job_id=$2""",
                str(e), job_id,
            )
```

Acrescentar `landscape_dir` ao `APIConfig` em `deps.py`:
```python
landscape_dir: str = os.getenv("LANDSCAPE_DIR", "data/landscape")
```

---

## 3. `services/api/schemas.py` — SimulationResult

Acrescentar após `SimulationJob`:

```python
class PerimeterSnapshot(BaseModel):
    t_h: float
    area_ha: float
    geojson: dict          # GeoJSON Polygon

class SimulationResultDetail(BaseModel):
    perimeters: list[PerimeterSnapshot]
    pixel_grid: dict       # GeoJSON FeatureCollection
    meta: dict

class SimulationJobDetail(SimulationJob):
    """Detalhe completo — inclui resultado quando status=done."""
    result: Optional[SimulationResultDetail] = None
```

O endpoint `GET /jobs/{job_id}` devolve `SimulationJobDetail` e mapeia
`result_json` → `result`:

```python
result = None
if row["result_json"] and row["status"] == "done":
    result = SimulationResultDetail(**row["result_json"])

return SimulationJobDetail(
    ...,
    result=result,
)
```

---

## 4. `frontend/src/api.js`

Acrescentar ao ficheiro existente:

```js
export async function postSimulate(apiKey, fireId, { duration_h = 3, wind_speed_ms, wind_direction_deg, bbox_km } = {}) {
  const res = await fetch(`${API_BASE}/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...auth(apiKey) },
    body: JSON.stringify({
      fire_id: fireId,
      duration_h,
      wind_speed_ms: wind_speed_ms || null,
      wind_direction_deg: wind_direction_deg || null,
      bbox_km: bbox_km || null,
    }),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function getSimulationJob(apiKey, jobId) {
  return get(`/jobs/${encodeURIComponent(jobId)}`, apiKey)
}
```

---

## 5. `frontend/src/views/SimulacaoView.jsx`

Vista completa: mapa (60 vh) + painel de controlos e resultados (40 vh).

```jsx
import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFireDetail, postSimulate, getSimulationJob } from '../api'
import { fmt, fmtDateTime } from '../constants'

// Estilos do mapa (reutilizados de MapView)
const OSM_STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: 'raster',
      tiles: [
        'https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
      ],
      tileSize: 256,
      attribution: '© Google',
      maxzoom: 20,
    },
  },
  layers: [{ id: 'satellite-bg', type: 'raster', source: 'satellite' }],
}

// Escala de cor ROS (m/min)
const ROS_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'ros_m_min'],
  0,  '#3b82f6',
  1,  '#22c55e',
  5,  '#f97316',
  20, '#ef4444',
]
// Escala FLI (kW/m)
const FLI_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'fi_kw_m'],
  0,    '#3b82f6',
  100,  '#22c55e',
  500,  '#f97316',
  2000, '#ef4444',
]
// Escala Chama (m)
const FLAME_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'flame_m'],
  0,   '#3b82f6',
  1,   '#22c55e',
  2.5, '#f97316',
  4,   '#ef4444',
]

const COLOR_EXPRS = { ros: ROS_COLOR_EXPR, fi: FLI_COLOR_EXPR, flame: FLAME_COLOR_EXPR }
const COLOR_LABELS = { ros: 'ROS m/min', fi: 'FLI kW/m', flame: 'Chama m' }
const COLOR_STOPS = {
  ros:   [{ v: 0, c: '#3b82f6' }, { v: 1, c: '#22c55e' }, { v: 5, c: '#f97316' }, { v: '20+', c: '#ef4444' }],
  fi:    [{ v: 0, c: '#3b82f6' }, { v: 100, c: '#22c55e' }, { v: 500, c: '#f97316' }, { v: '2000+', c: '#ef4444' }],
  flame: [{ v: 0, c: '#3b82f6' }, { v: 1, c: '#22c55e' }, { v: 2.5, c: '#f97316' }, { v: '4+', c: '#ef4444' }],
}

// Perímetros: cor e opacidade por hora
const PERIM_STYLES = {
  1: { color: '#f97316', fillOpacity: 0.08 },
  2: { color: '#ef4444', fillOpacity: 0.12 },
  3: { color: '#991b1b', fillOpacity: 0.18 },
  6: { color: '#7f1d1d', fillOpacity: 0.22 },
}

export default function SimulacaoView({ apiKey }) {
  const { fireId } = useParams()
  const mapRef = useRef(null)
  const containerRef = useRef(null)

  const [fire, setFire] = useState(null)
  const [basemap, setBasemap] = useState('osm')
  const [layer, setLayer] = useState('ros')       // ros | fi | flame
  const [opacity, setOpacity] = useState(0.75)
  const [durationH, setDurationH] = useState(3)
  const [windOverride, setWindOverride] = useState({ speed: '', dir: '' })
  const [jobStatus, setJobStatus] = useState(null)  // null | 'pending' | 'running' | 'done' | 'failed'
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  // Carregar detalhe do fogo
  useEffect(() => {
    fetchFireDetail(apiKey, fireId)
      .then(setFire)
      .catch(e => setError(e.message))
  }, [apiKey, fireId])

  // Inicializar mapa
  useEffect(() => {
    if (!containerRef.current || mapRef.current || !fire) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: [fire.longitude, fire.latitude],
      zoom: 12,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')

    // Marcador de ignição
    new maplibregl.Marker({ color: '#ef4444' })
      .setLngLat([fire.longitude, fire.latitude])
      .addTo(map)

    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
  }, [fire])

  // Troca de basemap
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.setStyle(basemap === 'osm' ? OSM_STYLE : SATELLITE_STYLE)
    map.once('styledata', () => { if (result) _renderLayers(map, result, layer, opacity) })
  }, [basemap])

  // Actualizar layers quando resultado chega ou muda layer/opacity
  useEffect(() => {
    const map = mapRef.current
    if (!map || !result) return
    const onReady = () => _renderLayers(map, result, layer, opacity)
    if (map.isStyleLoaded()) onReady()
    else map.once('styledata', onReady)
  }, [result, layer, opacity])

  // Polling do job
  function startPolling(jobId) {
    pollRef.current = setInterval(async () => {
      try {
        const job = await getSimulationJob(apiKey, jobId)
        setJobStatus(job.status)
        if (job.status === 'done') {
          clearInterval(pollRef.current)
          setResult(job.result)
        } else if (job.status === 'failed') {
          clearInterval(pollRef.current)
          setError(job.error_message || 'Simulação falhou')
        }
      } catch (e) {
        clearInterval(pollRef.current)
        setError(e.message)
      }
    }, 2000)
  }

  useEffect(() => () => clearInterval(pollRef.current), [])

  async function handleSimulate() {
    setJobStatus('pending')
    setResult(null)
    setError(null)
    try {
      const job = await postSimulate(apiKey, fireId, {
        duration_h: durationH,
        wind_speed_ms: windOverride.speed ? parseFloat(windOverride.speed) : undefined,
        wind_direction_deg: windOverride.dir ? parseFloat(windOverride.dir) : undefined,
      })
      setJobStatus(job.status)
      startPolling(job.job_id)
    } catch (e) {
      setJobStatus(null)
      setError(e.message)
    }
  }

  if (!fire) return <div className="state-center" style={{ height: '100%' }}>A carregar…</div>

  const triage = fire.triage
  const isRunning = jobStatus === 'pending' || jobStatus === 'running'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* Breadcrumb */}
      <div className="breadcrumb" style={{ flexShrink: 0 }}>
        <Link to="/lista">Ocorrências</Link>
        <span className="sep">›</span>
        <Link to={`/fogo/${fireId}`}>{[fire.municipality, fire.district].filter(Boolean).join(', ')}</Link>
        <span className="sep">›</span>
        <span>Simulação</span>
      </div>

      {/* MAPA */}
      <div style={{ flex: '0 0 60%', position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

        {/* Controlos overlay — canto sup. dir. */}
        <div style={{
          position: 'absolute', top: 10, right: 10, zIndex: 10,
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          {/* Basemap toggle */}
          <div style={{ display: 'flex', gap: 4 }}>
            {['osm', 'satellite'].map(b => (
              <button key={b} className={`btn btn-ghost${basemap === b ? ' active' : ''}`}
                style={{ fontSize: 10, padding: '3px 8px' }}
                onClick={() => setBasemap(b)}>
                {b === 'osm' ? 'OSM' : 'SAT'}
              </button>
            ))}
          </div>
          {/* Layer toggle */}
          {result && (
            <>
              <div style={{ display: 'flex', gap: 4 }}>
                {Object.entries(COLOR_LABELS).map(([k, label]) => (
                  <button key={k} className={`btn btn-ghost${layer === k ? ' active' : ''}`}
                    style={{ fontSize: 9, padding: '3px 6px' }}
                    onClick={() => setLayer(k)}>
                    {label.split(' ')[0]}
                  </button>
                ))}
              </div>
              {/* Opacidade */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6,
                background: 'var(--bg2)', borderRadius: 4, padding: '4px 8px' }}>
                <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
                  TRANSP
                </span>
                <input type="range" min={0} max={1} step={0.05}
                  value={opacity} onChange={e => setOpacity(parseFloat(e.target.value))}
                  style={{ width: 80, cursor: 'pointer' }} />
              </div>
              {/* Legenda */}
              <Legend stops={COLOR_STOPS[layer]} label={COLOR_LABELS[layer]} />
            </>
          )}
        </div>
      </div>

      {/* PAINEL INFERIOR */}
      <div style={{
        flex: '0 0 40%', overflowY: 'auto', borderTop: '1px solid var(--border)',
        padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12,
      }}>

        {/* Controlos de simulação */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
              DURAÇÃO
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {[1, 2, 3, 6].map(h => (
                <button key={h} className={`btn btn-ghost${durationH === h ? ' active' : ''}`}
                  style={{ fontSize: 11, padding: '4px 10px' }}
                  onClick={() => setDurationH(h)}>
                  {h}h
                </button>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
              VENTO OVERRIDE (opcional)
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input className="form-input" type="number" placeholder="m/s"
                style={{ width: 70, fontSize: 12 }}
                value={windOverride.speed}
                onChange={e => setWindOverride(p => ({ ...p, speed: e.target.value }))} />
              <input className="form-input" type="number" placeholder="° dir"
                style={{ width: 70, fontSize: 12 }}
                value={windOverride.dir}
                onChange={e => setWindOverride(p => ({ ...p, dir: e.target.value }))} />
            </div>
          </div>

          <button
            className="btn btn-primary"
            disabled={isRunning || !triage}
            onClick={handleSimulate}
            style={{ padding: '6px 18px', alignSelf: 'flex-end' }}
          >
            {isRunning ? (
              <><span className="dot" style={{ marginRight: 6, animation: 'blink 1s infinite' }} />A calcular…</>
            ) : '▶ Simular'}
          </button>

          {!triage && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)' }}>
              Sem triagem — simulação não disponível
            </span>
          )}
        </div>

        {/* Erro */}
        {error && (
          <div style={{ color: 'var(--danger)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            ✗ {error}
          </div>
        )}

        {/* Tabela de resultados */}
        {result && <ResultsTable perimeters={result.perimeters} />}

        {/* Meta */}
        {result && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--dim)', marginTop: 4 }}>
            Meteo: Open-Meteo · vento {fmt(result.meta.wind_speed_ms, 1)} m/s {fmt(result.meta.wind_dir_deg, 0)}°
            {triage && ` · Triagem: ${fmtDateTime(triage.computed_at)}`}
            {` · Resolução: ${result.meta.resolution_m}m`}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Componentes auxiliares
// ---------------------------------------------------------------------------

function Legend({ stops, label }) {
  return (
    <div style={{
      background: 'var(--bg2)', borderRadius: 4, padding: '6px 8px',
      fontFamily: 'var(--font-mono)', fontSize: 9,
    }}>
      <div style={{ color: 'var(--muted)', marginBottom: 4 }}>{label.toUpperCase()}</div>
      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        {stops.map(({ v, c }) => (
          <div key={v} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
            <div style={{ width: 16, height: 10, borderRadius: 2, background: c }} />
            <span style={{ color: 'var(--dim)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ResultsTable({ perimeters }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 6 }}>
        RESULTADOS DA SIMULAÇÃO
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {['Hora', 'Área (ha)', 'ROS máx', 'FLI máx', 'Chama máx'].map(h => (
              <th key={h} style={{ padding: '4px 8px', textAlign: 'left',
                color: 'var(--muted)', fontWeight: 400, fontSize: 9 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {perimeters.map(p => (
            <tr key={p.t_h} style={{ borderBottom: '1px solid rgba(37,52,39,.3)' }}>
              <td style={{ padding: '6px 8px', color: 'var(--accent2)', fontWeight: 700 }}>
                t={p.t_h}h
              </td>
              <td style={{ padding: '6px 8px' }}>{fmt(p.area_ha, 0)}</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>—</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>—</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>—</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 9, color: 'var(--dim)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
        * ROS/FLI/Chama máx calculados a partir da grelha de pixels
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Render MapLibre layers
// ---------------------------------------------------------------------------

function _renderLayers(map, result, layer, opacity) {
  // Limpar layers anteriores
  ['sim-pixels-fill', 'sim-pixels-outline',
   'perim-1h-fill', 'perim-1h-line',
   'perim-2h-fill', 'perim-2h-line',
   'perim-3h-fill', 'perim-3h-line',
   'perim-6h-fill', 'perim-6h-line',
  ].forEach(id => { try { map.removeLayer(id) } catch {} })
  ['sim-pixels', 'perim-1h', 'perim-2h', 'perim-3h', 'perim-6h',
  ].forEach(id => { try { map.removeSource(id) } catch {} })

  // Pixel grid (apenas dentro do perímetro final)
  if (result.pixel_grid) {
    map.addSource('sim-pixels', { type: 'geojson', data: result.pixel_grid })
    map.addLayer({
      id: 'sim-pixels-fill',
      type: 'fill',
      source: 'sim-pixels',
      paint: {
        'fill-color': COLOR_EXPRS[layer],
        'fill-opacity': opacity,
      },
    })
  }

  // Perímetros
  result.perimeters.forEach(({ t_h, geojson }) => {
    const style = PERIM_STYLES[t_h] || PERIM_STYLES[3]
    const id = `perim-${t_h}h`
    map.addSource(id, { type: 'geojson', data: geojson })
    map.addLayer({
      id: `${id}-fill`,
      type: 'fill',
      source: id,
      paint: { 'fill-color': style.color, 'fill-opacity': style.fillOpacity },
    })
    map.addLayer({
      id: `${id}-line`,
      type: 'line',
      source: id,
      paint: { 'line-color': style.color, 'line-width': t_h === Math.max(...result.perimeters.map(p => p.t_h)) ? 2 : 1 },
    })
  })
}
```

---

## 6. `frontend/src/App.jsx`

### Nova rota

```jsx
// Adicionar import
import SimulacaoView from './views/SimulacaoView'

// Dentro de <Routes>, após a rota /historico:
<Route path="/fogo/:fireId/simulacao" element={<SimulacaoView apiKey={apiKey} />} />
```

### Topbar — reconhecer a nova rota

```jsx
// Em Topbar(), adicionar antes do isHistory check:
const isSimulation = location.pathname.match(/^\/fogo\/([^/]+)\/simulacao$/)

// No bloco if/else:
if (isSimulation) {
  title = 'Simulação'
  sub = `#${isSimulation[1]}`
} else if (isHistory) {
  ...
```

---

## 7. `frontend/src/views/DetalheView.jsx`

Adicionar botão "Simular" no breadcrumb, ao lado do "Ver histórico":

```jsx
// No breadcrumb, após o link "Ver histórico":
{t && (
  <>
    <span className="sep">·</span>
    <Link to={`/fogo/${fireId}/historico`} style={{ color: 'var(--accent2)' }}>
      Ver histórico
    </Link>
    <span className="sep">·</span>
    <Link to={`/fogo/${fireId}/simulacao`} style={{ color: 'var(--p1)' }}>
      ▶ Simular
    </Link>
  </>
)}
```

---

## 8. Notas de implementação e limitações

### Ordem de implementação sugerida

1. `simulation.py` — testar isoladamente com `python -c "..."`
2. Actualizar `routes_meta.py` — testar POST + polling com curl
3. `api.js` — adicionar as duas funções
4. `SimulacaoView.jsx` + rota + botão — testar UI com job real

### Limitações da v1

| Limitação | Impacto | Solução futura |
|---|---|---|
| Sem correcção de terreno inclinado (eq. 3-10 FARSITE) | Fire shapes ligeiramente distorcidas em declives > 30° | Implementar transformações para o plano superficial |
| Meteo constante no espaço | Não reflecte variação de vento com topografia | Grids de vento (NWP) |
| Sem aceleração (eq. 29-33) | Salto instantâneo para ROS de equilíbrio | Implementar Canadian FBP acceleration |
| Sem spotting (Albini 1979) | Sub-estima alcance em condições extremas | Muito complexo, V2 |
| Resolução grelha fixa 100m | Pode ser lenta para bbox > 20km | Ajustar `resolution_m` via payload |

### DEV_MODE

Com `DEV_MODE=true` (MockLandscapeReader), a simulação não funciona — requer os TIFFs reais. Lançar `HTTPException(501)` se `landscape_dir` estiver ausente.

### Performance estimada

| Configuração | Células | Tempo aprox. |
|---|---|---|
| 15km bbox, 100m res | 22 500 | ~5-15s |
| 20km bbox, 100m res | 40 000 | ~15-30s |
| 15km bbox, 50m res | 90 000 | ~60-90s |

Com `asyncio.create_task` + `ThreadPoolExecutor`, a API responde imediatamente (202) e o cliente faz polling sem bloquear.
