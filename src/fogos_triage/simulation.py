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
    from shapely import set_precision
    from shapely.geometry import LineString, MultiPolygon, Point, Polygon, shape
    from shapely.strtree import STRtree
    from shapely.validation import make_valid
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

try:
    import rasterio
    from rasterio.warp import transform as rio_transform
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

from .engine import _max_spread_direction_from_phi, _rothermel_direct
from .fuel_models import FuelModelPT, SCOTT_BURGAN_NB_RANGE, normalize_fuel_model_num
from .fuel_moisture_table import FuelMoistureRow
from .fuel_moisture_table import lookup as _lookup_fuel_moisture
from .landscape import LandscapeReader, LandscapeRasters
from .schemas import WeatherConditions

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Parâmetros de simulação
# ---------------------------------------------------------------------------

INIT_RADIUS_M = 75.0
N_INIT_VERTICES = 16
AA_SURFACE = 0.115  # FARSITE fire acceleration constant (eq. [30])

# Timestep dinâmico (FARSITE "distance resolution", eq. [29]-[33]): o
# vértice mais rápido nunca avança mais do que distance_resolution_m por
# passo. MAX/MIN_TIMESTEP_MIN são tectos de segurança (fogo parado/lento
# não salta um intervalo de meteo enorme; nunca colapsa para dt≈0).
MAX_TIMESTEP_MIN = 15.0
MIN_TIMESTEP_MIN = 0.5

# Espaçamento de vértices do perímetro, como fração de distance_resolution_m
# (ex. 10m nativo -> espaçamento mantido entre 5m e 20m por _rediscretize).
PERIM_SPACING_MIN_FACTOR = 0.5
PERIM_SPACING_MAX_FACTOR = 2.0

# Limite de vértices do perímetro — protege tempo de cálculo quando o
# espaçamento é fino (10m) e o fogo cresce muito. Ao contrário da grelha
# (limitada por bbox_km), o tamanho final do perímetro não é conhecido à
# partida, por isso o ajuste é feito em runtime: se excedido, o
# espaçamento efetivo é multiplicado por PERIM_COARSEN_FACTOR para as
# iterações seguintes (unidirecional — não relaxa de volta).
MAX_PERIMETER_VERTICES = 3000
PERIM_COARSEN_FACTOR = 1.5

# Limite de células da grelha ROS (bbox completo, antes do clip ao
# perímetro) — protege tempo de cálculo e tamanho do payload quando a
# resolução nativa do landscape file é fina (ex. 10m) e o bbox pedido é
# grande. Se excedido, resolution_m é ajustada para cima.
MAX_GRID_CELLS = 500_000

# Candidatos a horas de snapshot do perímetro — filtrados por <= duration_h
# (mais duration_h no fim, se ainda não incluída). Cobre durações até 24h.
SNAPSHOT_HOURS_CANDIDATES = [1.0, 2.0, 3.0, 6.0, 9.0, 12.0, 18.0, 24.0]


# ---------------------------------------------------------------------------
# Estruturas de output
# ---------------------------------------------------------------------------

@dataclass
class PerimeterSnapshot:
    t_h: float
    area_ha: float
    polygon_wgs84: dict
    ros_max_m_min: float
    fli_max_kw_m: float
    flame_max_m: float


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
    slope_rad: float = 0.0,
    aspect_rad: float = 0.0,
) -> tuple[float, float]:
    """Taxa de propagação (Xt, Yt) em m/min para um vértice do perímetro.

    Aplica correcção de terreno inclinado (FARSITE eq. [3]-[10]) quando
    slope_rad > 0.  aspect_rad e slope_rad em radianos, azimute a partir de N.
    """
    xs = x_prev - x_next
    ys = y_prev - y_next

    # Transformação horizontal → superfície inclinada (FARSITE eq. [3]-[7])
    if slope_rad > 1e-4:
        seg_len = math.hypot(xs, ys)
        if seg_len > 1e-6:
            cos_slope = math.cos(slope_rad)
            # ai: azimute do vector normal (ângulo a partir de N = atan2(x_e, y_n))
            ai = math.atan2(xs, ys)
            di = math.atan(math.tan(aspect_rad - ai) / cos_slope)
            Di = seg_len * math.cos(di) * (1.0 - cos_slope)
            xs += Di * math.sin(aspect_rad)
            ys += Di * math.cos(aspect_rad)

    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)

    p = xs * sin_t + ys * cos_t
    q = xs * cos_t - ys * sin_t

    # Nota: a soma a²p²+b²q² é sempre > 0 (excepto tangente nula) — ao
    # contrário de b²p²-a²q², que degenera exactamente onde a tangente do
    # perímetro é perpendicular a theta (i.e. na ponta da frente de fogo,
    # a posição mais comum e mais importante), disparando o fallback
    # errado ali e valores espúrios nos vértices vizinhos.
    denom_sq = a * a * p * p + b * b * q * q

    if denom_sq <= 1e-12:
        return c * sin_t, c * cos_t

    denom = math.sqrt(denom_sq)
    Xt = (a * a * cos_t * p - b * b * sin_t * q) / denom + c * sin_t
    Yt = (-a * a * sin_t * p - b * b * cos_t * q) / denom + c * cos_t

    # Transformação superfície → horizontal (FARSITE eq. [8]-[10])
    if slope_rad > 1e-4:
        spread_len = math.hypot(Xt, Yt)
        if spread_len > 1e-6:
            Dr = spread_len * math.cos(aspect_rad - math.atan2(Xt, Yt)) * (1.0 - math.cos(slope_rad))
            Xt += Dr * math.sin(aspect_rad)
            Yt += Dr * math.cos(aspect_rad)

    return Xt, Yt


# ---------------------------------------------------------------------------
# Pré-computa grelha ROS/FLI/chama para visualização
# ---------------------------------------------------------------------------

def _point_moisture(
    fuel_moisture_table: Optional[dict[int, FuelMoistureRow]],
    fuel_model_num: int,
    default_m_1h: float, default_m_10h: float, default_m_100h: float,
    default_m_lh: float, default_m_lw: float,
) -> tuple[float, float, float, float, float]:
    """Humidades (fração 0-1) para um ponto — vindas da tabela por
    modelo de combustível (Initial Fuel Moistures .FMS, ver
    fuel_moisture_table.py) se dada, senão os valores por omissão já
    calculados a partir da meteo (Simard 1968/VIIRS/cenário BehavePlus).
    """
    if fuel_moisture_table is None:
        return default_m_1h, default_m_10h, default_m_100h, default_m_lh, default_m_lw
    row = _lookup_fuel_moisture(fuel_moisture_table, fuel_model_num)
    return (
        row.m1h_pct / 100.0, row.m10h_pct / 100.0, row.m100h_pct / 100.0,
        row.live_h_pct / 100.0, row.live_w_pct / 100.0,
    )


def _build_ros_grid(
    reader: LandscapeReader,
    fuel_models: dict[int, FuelModelPT],
    weather: WeatherConditions,
    cx_proj: float, cy_proj: float,
    bbox_km: float,
    resolution_m: float,
    fuel_moisture_table: Optional[dict[int, FuelMoistureRow]] = None,
) -> dict:
    """
    Constrói uma GeoJSON FeatureCollection com uma célula por ponto de grelha
    (ros, fi, chama). Calculado para toda a grelha; clip ao perímetro feito
    depois.

    Só `slope` e `fuel_model` influenciam o cálculo Rothermel de superfície
    (declive e modelo de combustível) — lidos uma única vez para todo o
    bbox via `LandscapeReader.read_window`, em vez de uma leitura rasterio
    por ponto da grelha.
    """
    half = bbox_km * 500.0
    min_x, max_x = cx_proj - half, cx_proj + half
    min_y, max_y = cy_proj - half, cy_proj + half

    arrays, nodata, window_transform = reader.read_window(
        ["slope", "fuel_model"], min_x, min_y, max_x, max_y,
    )
    slope_arr = arrays.get("slope")
    fuel_arr = arrays.get("fuel_model")
    if slope_arr is None or fuel_arr is None:
        log.warning("Simulação: landscape file sem bandas slope/fuel_model")
        return {"type": "FeatureCollection", "features": []}
    height, width = slope_arr.shape

    xs = np.arange(cx_proj - half + resolution_m / 2, cx_proj + half, resolution_m)
    ys = np.arange(cy_proj - half + resolution_m / 2, cy_proj + half, resolution_m)
    xx, yy = np.meshgrid(xs, ys)
    pts_x = xx.ravel()
    pts_y = yy.ravel()

    # (x, y) -> (linha, coluna) dentro da janela lida — raster north-up,
    # sem rotação, pelo que a inversão do transform é aritmética direta.
    col_idx = np.clip(
        ((pts_x - window_transform.c) / window_transform.a).astype(int), 0, width - 1
    )
    row_idx = np.clip(
        ((pts_y - window_transform.f) / window_transform.e).astype(int), 0, height - 1
    )

    slope_raw = slope_arr[row_idx, col_idx].astype(float)
    fuel_raw = fuel_arr[row_idx, col_idx]

    slope_nodata = nodata.get("slope")
    fuel_nodata = nodata.get("fuel_model")
    slope_deg = (slope_raw if slope_nodata is None
                 else np.where(slope_raw == slope_nodata, 0.0, slope_raw))
    fuel_num = (fuel_raw.astype(int) if fuel_nodata is None
                else np.where(fuel_raw == fuel_nodata, 98, fuel_raw).astype(int))
    # Códigos NB Scott & Burgan (91-99, urbano/água/agrícola/...) → FM98,
    # mesmo tratamento de "não combustível" em toda a app (ver fuel_models.py).
    fuel_num = np.where(
        (fuel_num >= SCOTT_BURGAN_NB_RANGE.start) & (fuel_num < SCOTT_BURGAN_NB_RANGE.stop),
        98, fuel_num,
    )

    lons, lats = rio_transform(reader.crs, "EPSG:4326", pts_x, pts_y)

    default_m_1h   = (weather.fuel_moisture_1h_pct   or 8.0)  / 100.0
    default_m_10h  = (weather.fuel_moisture_10h_pct  or 9.0)  / 100.0
    default_m_100h = (weather.fuel_moisture_100h_pct or 10.0) / 100.0
    default_m_lh   = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
    default_m_lw   = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0
    wind_mf = weather.wind_midflame_ms or 0.0

    features = []
    d_lat = resolution_m / 111320.0
    for lon, lat, slope, fnum in zip(lons, lats, slope_deg, fuel_num):
        fm = fuel_models.get(int(fnum))
        if fm is None or fm.is_empty:
            ros, fi, flame = 0.0, 0.0, 0.0
        else:
            try:
                m_1h, m_10h, m_100h, m_lh, m_lw = _point_moisture(
                    fuel_moisture_table, int(fnum),
                    default_m_1h, default_m_10h, default_m_100h, default_m_lh, default_m_lw,
                )
                ros, fi, *_ = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=wind_mf,
                    slope_degrees=float(slope),
                )
                flame = 0.0775 * fi ** 0.46 if fi > 0 else 0.0
            except Exception:
                ros, fi, flame = 0.0, 0.0, 0.0

        d_lon = resolution_m / (111320.0 * math.cos(math.radians(lat)))
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


# Densidade fixa da grelha de setas de direcção — independente de
# resolution_m/bbox_km (ver docstring de _build_direction_arrows).
DIRECTION_ARROWS_PER_SIDE = 25


def _build_direction_arrows(
    reader: LandscapeReader,
    fuel_models: dict[int, FuelModelPT],
    steps: list[tuple[float, WeatherConditions, dict]],
    min_x: float, min_y: float, max_x: float, max_y: float,
    n_per_side: int = DIRECTION_ARROWS_PER_SIDE,
    fuel_moisture_table: Optional[dict[int, FuelMoistureRow]] = None,
) -> dict:
    """
    Constrói uma GeoJSON FeatureCollection de pontos com a direcção de
    máxima propagação (theta_deg) e o ROS nesse ponto — para desenhar
    setas no frontend (comprimento ∝ ros_m_min).

    **Um campo de setas por instantâneo**, não um só para a simulação
    toda: `steps` é [(t_h, meteo dessa hora, perímetro dessa hora)] e cada
    feição sai marcada com `t_h`, para o frontend mostrar as setas da hora
    escolhida sem reconstruir nada. Antes usava-se sempre a meteo da hora
    0, o que era enganador assim que o vento rodava durante a simulação —
    os perímetros são propagados com a meteo horária, as setas não eram.

    A grelha de pontos é a MESMA em todas as horas (mesmo bbox, mesmo
    n_per_side): as setas ficam nas mesmas posições ao mudar de hora, só
    rodam e mudam de comprimento, o que torna a comparação entre horas
    directa. O recorte é que é por hora — cada campo é cortado ao
    perímetro dessa hora, por isso as setas vão aparecendo à medida que o
    fogo cresce.

    O terreno (declive/exposição/combustível) é lido **uma única vez**,
    fora do ciclo das horas: não depende do tempo, e é a leitura do raster
    que domina o custo. Só as avaliações Rothermel se repetem por hora
    (n_per_side² por instantâneo, aritmética pura).

    Densidade fixa (n_per_side × n_per_side) sobre o bbox dado —
    ao contrário da grelha de cor (_build_ros_grid, até MAX_GRID_CELLS),
    decimar setas a partir dessa grelha não é fiável porque
    _clip_grid_to_perimeter() já a recorta ao perímetro final, quebrando
    a indexação linha/coluna regular. Uma segunda grelha grosseira,
    calculada à parte, evita o problema.

    O bbox (`min_x..max_y`) deve cobrir a extensão do perímetro final,
    não o bbox de visualização pedido pelo utilizador (`bbox_km`) — este
    é tipicamente muito maior do que a área realmente queimada numa
    simulação de poucas horas, o que deixaria a grelha de setas quase
    vazia (poucos dos n_per_side² pontos caem dentro do perímetro
    recortado). Ver chamada em `run_simulation_sync`.
    """
    arrays, nodata, window_transform = reader.read_window(
        ["slope", "aspect", "fuel_model"], min_x, min_y, max_x, max_y,
    )
    slope_arr = arrays.get("slope")
    aspect_arr = arrays.get("aspect")
    fuel_arr = arrays.get("fuel_model")
    if slope_arr is None or aspect_arr is None or fuel_arr is None:
        return {"type": "FeatureCollection", "features": []}
    height, width = slope_arr.shape

    step_x = (max_x - min_x) / n_per_side
    step_y = (max_y - min_y) / n_per_side
    xs = np.arange(min_x + step_x / 2, max_x, step_x)
    ys = np.arange(min_y + step_y / 2, max_y, step_y)
    xx, yy = np.meshgrid(xs, ys)
    pts_x = xx.ravel()
    pts_y = yy.ravel()

    col_idx = np.clip(
        ((pts_x - window_transform.c) / window_transform.a).astype(int), 0, width - 1
    )
    row_idx = np.clip(
        ((pts_y - window_transform.f) / window_transform.e).astype(int), 0, height - 1
    )

    slope_raw = slope_arr[row_idx, col_idx].astype(float)
    aspect_raw = aspect_arr[row_idx, col_idx].astype(float)
    fuel_raw = fuel_arr[row_idx, col_idx]

    slope_nodata = nodata.get("slope")
    aspect_nodata = nodata.get("aspect")
    fuel_nodata = nodata.get("fuel_model")
    slope_deg = (slope_raw if slope_nodata is None
                 else np.where(slope_raw == slope_nodata, 0.0, slope_raw))
    aspect_deg = (aspect_raw if aspect_nodata is None
                  else np.where(aspect_raw == aspect_nodata, 0.0, aspect_raw))
    fuel_num = (fuel_raw.astype(int) if fuel_nodata is None
                else np.where(fuel_raw == fuel_nodata, 98, fuel_raw).astype(int))
    # Códigos NB Scott & Burgan (91-99, urbano/água/agrícola/...) → FM98,
    # mesmo tratamento de "não combustível" em toda a app (ver fuel_models.py).
    fuel_num = np.where(
        (fuel_num >= SCOTT_BURGAN_NB_RANGE.start) & (fuel_num < SCOTT_BURGAN_NB_RANGE.stop),
        98, fuel_num,
    )

    lons, lats = rio_transform(reader.crs, "EPSG:4326", pts_x, pts_y)

    all_features: list[dict] = []
    for t_h, weather, perimeter in steps:
        default_m_1h   = (weather.fuel_moisture_1h_pct   or 8.0)  / 100.0
        default_m_10h  = (weather.fuel_moisture_10h_pct  or 9.0)  / 100.0
        default_m_100h = (weather.fuel_moisture_100h_pct or 10.0) / 100.0
        default_m_lh   = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
        default_m_lw   = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0
        wind_mf = weather.wind_midflame_ms or 0.0
        wind_dir = weather.wind_direction_deg or 0.0

        features = []
        for lon, lat, slope, aspect, fnum in zip(lons, lats, slope_deg, aspect_deg, fuel_num):
            fm = fuel_models.get(int(fnum))
            if fm is None or fm.is_empty:
                continue
            try:
                m_1h, m_10h, m_100h, m_lh, m_lw = _point_moisture(
                    fuel_moisture_table, int(fnum),
                    default_m_1h, default_m_10h, default_m_100h, default_m_lh, default_m_lw,
                )
                ros, fi, phi_w, phi_s, *_ = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=wind_mf,
                    slope_degrees=float(slope),
                )
            except Exception:
                continue
            if ros <= 0:
                continue

            theta_deg = _max_spread_direction_from_phi(
                wind_direction_deg=wind_dir,
                aspect_degrees=float(aspect),
                phi_w=phi_w,
                phi_s=phi_s,
            )

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "t_h": t_h,
                    "theta_deg": round(theta_deg, 1),
                    "ros_m_min": round(ros, 3),
                },
            })

        # Recorte ao perímetro DESSA hora — as setas seguem o fogo em vez
        # de aparecerem já todas sobre a área final.
        clipped = _clip_grid_to_perimeter(
            {"type": "FeatureCollection", "features": features}, perimeter,
        )
        all_features.extend(clipped["features"])

    return {"type": "FeatureCollection", "features": all_features}


def _clip_grid_to_perimeter(grid_geojson: dict, perimeter_geojson: dict) -> dict:
    """Remove células fora do perímetro final.

    Usa um índice espacial (STRtree) em vez de testar `.intersects()`
    contra cada uma das (até 500k) células da grelha — necessário desde
    que o perímetro final passou a ter centenas/milhares de vértices
    (resolução de 10m), o que tornava o teste exaustivo o gargalo
    dominante da simulação (~30s medidos numa grelha de 500k células).
    """
    if not HAS_SHAPELY:
        return grid_geojson
    try:
        perim = shape(perimeter_geojson)
        features = grid_geojson["features"]
        geoms = [shape(f["geometry"]) for f in features]
        tree = STRtree(geoms)
        idx = tree.query(perim, predicate="intersects")
        clipped = [features[i] for i in idx]
        return {"type": "FeatureCollection", "features": clipped}
    except Exception:
        return grid_geojson


# ---------------------------------------------------------------------------
# Cache de terreno para a propagação — evita 1 leitura rasterio por vértice
# por timestep (mesmo padrão de _build_ros_grid, mas re-lida sob demanda
# à medida que o perímetro cresce, em vez de uma única vez para um bbox fixo).
# ---------------------------------------------------------------------------

_TERRAIN_CACHE_MARGIN_M = 300.0
_TERRAIN_FIELDS = ["slope", "aspect", "fuel_model"]


def _refresh_terrain_cache(reader: LandscapeReader, verts: list) -> dict:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    min_x, max_x = min(xs) - _TERRAIN_CACHE_MARGIN_M, max(xs) + _TERRAIN_CACHE_MARGIN_M
    min_y, max_y = min(ys) - _TERRAIN_CACHE_MARGIN_M, max(ys) + _TERRAIN_CACHE_MARGIN_M
    arrays, nodata, window_transform = reader.read_window(
        _TERRAIN_FIELDS, min_x, min_y, max_x, max_y,
    )
    return {
        "arrays": arrays, "nodata": nodata, "window_transform": window_transform,
        "bounds": (min_x, min_y, max_x, max_y),
    }


def _lookup_cached_terrain(cache: dict, x: float, y: float) -> Optional[tuple[float, float, int]]:
    """Lê (slope_deg, aspect_deg, fuel_model_num) da janela em cache.
    Devolve None se o ponto cair fora da janela — sinal para recarregar."""
    slope_arr = cache["arrays"].get("slope")
    if slope_arr is None:
        return None
    wt = cache["window_transform"]
    # floor e não int: o int() de Python trunca em direcção a zero, por
    # isso um vértice a poucos metros para fora da margem esquerda/superior
    # da janela dava col/row = 0 em vez de cair fora — e em vez de
    # devolver None (o sinal para recarregar a janela), lia-se a célula da
    # borda como se fosse a certa.
    col = math.floor((x - wt.c) / wt.a)
    row = math.floor((y - wt.f) / wt.e)
    height, width = slope_arr.shape
    if not (0 <= row < height and 0 <= col < width):
        return None

    nodata = cache["nodata"]

    def _val(name: str) -> Optional[float]:
        arr = cache["arrays"].get(name)
        if arr is None:
            return None
        v = float(arr[row, col])
        nd = nodata.get(name)
        if nd is not None and v == nd:
            return None
        return v

    slope_deg = _val("slope") or 0.0
    aspect_deg = _val("aspect") or 0.0
    fuel_num = int(_val("fuel_model") or 98)
    return slope_deg, aspect_deg, fuel_num


# ---------------------------------------------------------------------------
# Propagação Huygens — loop principal
# ---------------------------------------------------------------------------

def _propagate(
    reader: LandscapeReader,
    fuel_models: dict[int, FuelModelPT],
    weather_hourly: list[WeatherConditions],
    cx_proj: float, cy_proj: float,
    duration_h: float,
    snapshot_hours: list[float],
    distance_resolution_m: float,
    ignition_points_proj: Optional[list[tuple[float, float]]] = None,
    fuel_moisture_table: Optional[dict[int, FuelMoistureRow]] = None,
) -> tuple[list[PerimeterSnapshot], bool]:
    """Propaga o fogo usando Richards (1990); devolve snapshots do perímetro.

    weather_hourly: lista com um WeatherConditions por hora de simulação.
    A cada timestep seleciona-se a entrada correspondente à hora atual
    (int(t/60)), permitindo incorporar a previsão horária do Open-Meteo.

    distance_resolution_m: alvo de espaçamento de vértices e também a
    distância que o vértice mais rápido percorre por timestep (FARSITE
    eq. [29]-[33]) — o timestep é recalculado a cada iteração a partir
    do ROS máximo actual, em vez de um DT fixo.

    ignition_points_proj: pontos de ignição (coordenadas já projetadas),
    2+ para uma linha de ignição. Se None, ignição pontual em
    (cx_proj, cy_proj) — comportamento idêntico ao anterior.

    Devolve (snapshots, perimeter_resolution_coarsened) — o segundo
    valor indica se MAX_PERIMETER_VERTICES foi alguma vez atingido.
    """
    proj_crs = reader.crs

    # Forma inicial de ignição: buffer à volta de um ponto (círculo,
    # quad_segs=4 dá os mesmos 16 vértices de sempre) ou de uma linha
    # (LineString.buffer dá naturalmente uma "cápsula" ao longo dela) —
    # uma só implementação para os dois casos.
    if ignition_points_proj and len(ignition_points_proj) >= 2:
        ignition_base = LineString(ignition_points_proj)
    else:
        px, py = ignition_points_proj[0] if ignition_points_proj else (cx_proj, cy_proj)
        ignition_base = Point(px, py)
    ignition_shape = ignition_base.buffer(INIT_RADIUS_M, quad_segs=4)
    # Vértices como (x, y, ros_actual, fi_actual) — ambos iniciam em 0
    # (fogo acabou de acender)
    verts = [(x, y, 0.0, 0.0) for x, y in ignition_shape.exterior.coords[:-1]]

    min_seg_m = PERIM_SPACING_MIN_FACTOR * distance_resolution_m
    max_seg_m = PERIM_SPACING_MAX_FACTOR * distance_resolution_m
    coarsened = False

    # Polígono acumulado — só cresce por união (ver _merge_into_accumulated).
    # Garante que a área já queimada nunca retrocede nem "salta" para uma
    # forma desligada entre timesteps/snapshots.
    accumulated_poly = ignition_shape

    terrain_cache = _refresh_terrain_cache(reader, verts)

    snapshots: list[PerimeterSnapshot] = []
    merge_stats: dict = {}
    snap_idx = 0
    t = 0.0
    total_min = duration_h * 60.0
    snap_minutes = [h * 60.0 for h in snapshot_hours]

    while t < total_min and len(verts) >= 3:
        # Meteo da hora atual — actualiza a cada hora de simulação
        hour_idx = min(int(t / 60), len(weather_hourly) - 1)
        wx = weather_hourly[hour_idx]
        default_m_1h   = (wx.fuel_moisture_1h_pct   or 8.0)  / 100.0
        default_m_10h  = (wx.fuel_moisture_10h_pct  or 9.0)  / 100.0
        default_m_100h = (wx.fuel_moisture_100h_pct or 10.0) / 100.0
        default_m_lh   = (wx.fuel_moisture_live_h_pct or 100.0) / 100.0
        default_m_lw   = (wx.fuel_moisture_live_w_pct or 100.0) / 100.0
        wind_mf = wx.wind_midflame_ms or 0.0
        wind_dir = wx.wind_direction_deg

        while snap_idx < len(snap_minutes) and t >= snap_minutes[snap_idx]:
            snap = _make_snapshot(verts, snap_minutes[snap_idx] / 60.0, proj_crs)
            if snap:
                snapshots.append(snap)
            snap_idx += 1

        # --- timestep dinâmico (FARSITE "distance resolution") ---
        # O vértice mais rápido (ros_actual do passo anterior, sem
        # recalcular Rothermel) não deve avançar mais do que
        # distance_resolution_m neste passo. Capado também pelo próximo
        # snapshot pedido e pela próxima fronteira horária de meteo, para
        # não "saltar" por cima de nenhum dos dois.
        max_ros = max((v[2] for v in verts), default=0.0)
        dt_candidate = distance_resolution_m / max_ros if max_ros > 1e-9 else MAX_TIMESTEP_MIN
        next_hour_boundary = (int(t // 60) + 1) * 60.0
        caps = [dt_candidate, MAX_TIMESTEP_MIN, next_hour_boundary - t, total_min - t]
        if snap_idx < len(snap_minutes):
            caps.append(snap_minutes[snap_idx] - t)
        dt = max(min(caps), MIN_TIMESTEP_MIN)

        n = len(verts)
        new_verts = []

        for i in range(n):
            x_cur, y_cur, ros_cur, _ = verts[i]
            x_prev, y_prev, _, _ = verts[(i - 1) % n]
            x_next, y_next, _, _ = verts[(i + 1) % n]

            cached = _lookup_cached_terrain(terrain_cache, x_cur, y_cur)
            if cached is None:
                terrain_cache = _refresh_terrain_cache(reader, verts)
                cached = _lookup_cached_terrain(terrain_cache, x_cur, y_cur)
            if cached is not None:
                slope_deg, aspect_deg, fuel_num = cached
            else:
                # fallback raro — ponto fora de qualquer janela razoável
                terrain = reader.sample_projected(x_cur, y_cur)
                slope_deg, aspect_deg, fuel_num = (
                    terrain.slope_degrees, terrain.aspect_degrees, terrain.fuel_model_num,
                )
            # Códigos NB Scott & Burgan (91-99) → FM98, mesmo tratamento de
            # "não combustível" em toda a app (ver fuel_models.py).
            fm = fuel_models.get(normalize_fuel_model_num(fuel_num))

            if fm is None or fm.is_empty:
                new_verts.append((x_cur, y_cur, 0.0, 0.0))
                continue

            try:
                m_1h, m_10h, m_100h, m_lh, m_lw = _point_moisture(
                    fuel_moisture_table, fuel_num,
                    default_m_1h, default_m_10h, default_m_100h, default_m_lh, default_m_lw,
                )
                ros_m_min, fi_kw, phi_w, phi_s, _, sigma, eff_ms = _rothermel_direct(
                    fm, m_1h, m_10h, m_100h, m_lh, m_lw,
                    wind_midflame_ms=wind_mf,
                    slope_degrees=slope_deg,
                )
            except Exception:
                new_verts.append((x_cur, y_cur, 0.0, 0.0))
                continue

            if ros_m_min <= 0:
                new_verts.append((x_cur, y_cur, 0.0, 0.0))
                continue

            # Aceleração / desaceleração (FARSITE eq. [29]-[33])
            R_eq = ros_m_min
            if ros_cur >= R_eq:
                # Desaceleração instantânea (FARSITE)
                ros_step = R_eq
            else:
                # Aceleração logarítmica: ros_cur = R_eq*(1 - exp(-AA*Tt))
                frac = ros_cur / R_eq if ros_cur > 1e-9 else 0.0
                Tt = -math.log(1.0 - frac) / AA_SURFACE if frac > 0.0 else 0.0
                ros_step = R_eq * (1.0 - math.exp(-AA_SURFACE * (Tt + dt)))
                ros_step = min(ros_step, R_eq)

            # fi_kw (Byram) é calculado para o ROS de equilíbrio (R_eq);
            # escala-se linearmente para o ROS real do passo (I_B ∝ R,
            # Byram 1959), consistente com o ros_step já acelerado/travado.
            fi_step = fi_kw * (ros_step / R_eq) if R_eq > 0 else 0.0

            theta_deg = _max_spread_direction_from_phi(
                wind_direction_deg=wind_dir,
                aspect_degrees=aspect_deg,
                phi_w=phi_w,
                phi_s=phi_s,
            )
            theta_rad = math.radians(theta_deg)
            slope_rad = math.radians(slope_deg)
            aspect_rad = math.radians(aspect_deg)

            a, b, c = _ellipse_dims(ros_step, eff_ms)
            Xt, Yt = _richards_step(
                x_prev, y_prev, x_next, y_next,
                theta_rad, a, b, c,
                slope_rad=slope_rad, aspect_rad=aspect_rad,
            )
            new_verts.append((x_cur + Xt * dt, y_cur + Yt * dt, ros_step, fi_step))

        verts = new_verts
        t += dt
        verts, accumulated_poly = _merge_into_accumulated(verts, accumulated_poly, merge_stats)
        verts = _rediscretize(verts, min_seg_m, max_seg_m)
        # Resincroniza accumulated_poly com o verts simplificado — sem isto,
        # o polígono acumulado cresce em complexidade sem limite a cada
        # união (verts fica limitado por _rediscretize, mas o Shapely
        # Polygon usado na PRÓXIMA união não ficava), tornando cada .union()
        # progressivamente mais lento ao longo da simulação.
        if HAS_SHAPELY and len(verts) >= 3:
            accumulated_poly = _accumulated_from_verts(verts)

        if len(verts) > MAX_PERIMETER_VERTICES:
            min_seg_m *= PERIM_COARSEN_FACTOR
            max_seg_m *= PERIM_COARSEN_FACTOR
            coarsened = True
            log.warning(
                "Simulação: perímetro excedeu %d vértices (%d) — espaçamento "
                "ajustado para min=%.1fm max=%.1fm",
                MAX_PERIMETER_VERTICES, len(verts), min_seg_m, max_seg_m,
            )
            verts = _rediscretize(verts, min_seg_m, max_seg_m)
            if HAS_SHAPELY and len(verts) >= 3:
                accumulated_poly = _accumulated_from_verts(verts)

        if len(verts) < 3:
            log.warning("Simulação: polígono degenerado após fusão/rediscretização a t=%.1f min", t)
            break

    while snap_idx < len(snap_minutes):
        snap = _make_snapshot(verts, snap_minutes[snap_idx] / 60.0, proj_crs)
        if snap:
            snapshots.append(snap)
        snap_idx += 1

    # Um perímetro congelado dá perímetros iguais entre snapshots com o
    # ROS/FLI a variar normalmente — sem esta linha, o sintoma chega ao
    # utilizador sem nada nos logs que o explique.
    if merge_stats.get("frozen_steps"):
        log.error(
            "Simulação: o perímetro ficou congelado em %d timestep(s) — a "
            "área acumulada não avançou nesses passos e os perímetros "
            "exportados estão subestimados",
            merge_stats["frozen_steps"],
        )

    return snapshots, coarsened


def _make_snapshot(verts: list, t_h: float, proj_crs) -> Optional[PerimeterSnapshot]:
    """Converte vértices projetados num PerimeterSnapshot GeoJSON WGS84.

    ros_max/fli_max/flame_max são o máximo entre os vértices activos do
    perímetro neste instante — reflectem o ponto mais intenso da frente
    de fogo, não um valor médio.
    """
    if len(verts) < 3:
        return None
    try:
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        ros_vals = [v[2] for v in verts]
        fi_vals = [v[3] for v in verts]
        lons, lats = rio_transform(proj_crs, "EPSG:4326", xs, ys)
        coords = list(zip(lons, lats))
        coords.append(coords[0])

        poly_geojson = {"type": "Polygon", "coordinates": [coords]}

        if HAS_SHAPELY:
            area_m2 = Polygon(list(zip(xs, ys))).area
            area_ha = area_m2 / 10000.0
        else:
            area_ha = 0.0

        ros_max = max(ros_vals) if ros_vals else 0.0
        fli_max = max(fi_vals) if fi_vals else 0.0
        flame_max = 0.0775 * fli_max ** 0.46 if fli_max > 0 else 0.0

        return PerimeterSnapshot(
            t_h=t_h, area_ha=round(area_ha, 1), polygon_wgs84=poly_geojson,
            ros_max_m_min=round(ros_max, 2),
            fli_max_kw_m=round(fli_max, 1),
            flame_max_m=round(flame_max, 2),
        )
    except Exception as e:
        log.warning("Simulação: erro ao criar snapshot t=%.1fh: %s", t_h, e)
        return None


def _rediscretize(verts: list, min_seg_m: float, max_seg_m: float) -> list:
    """Insere vértices em segmentos longos; remove em segmentos curtos.
    Vértices como (x, y, ros_actual, fi_actual); ambos interpolados linearmente.
    """
    n = len(verts)
    result = []
    for i in range(n):
        x1, y1, r1, f1 = verts[i]
        x2, y2, r2, f2 = verts[(i + 1) % n]
        dist = math.hypot(x2 - x1, y2 - y1)
        result.append((x1, y1, r1, f1))
        if dist > max_seg_m:
            n_insert = int(dist / max_seg_m)
            for k in range(1, n_insert + 1):
                frac = k / (n_insert + 1)
                result.append((
                    x1 + frac * (x2 - x1),
                    y1 + frac * (y2 - y1),
                    r1 + frac * (r2 - r1),
                    f1 + frac * (f2 - f1),
                ))
    cleaned = [result[0]]
    for pt in result[1:]:
        if math.hypot(pt[0] - cleaned[-1][0], pt[1] - cleaned[-1][1]) >= min_seg_m:
            cleaned.append(pt)
    return cleaned


def _reassign_ros_fi(new_pts: list, source_verts: list) -> list:
    """Atribui ros_actual/fi_actual a new_pts pelo vizinho mais próximo em
    source_verts — vectorizado com numpy (era um duplo loop Python O(n²),
    caro com as centenas/milhares de vértices que a resolução de 10m já
    produz)."""
    if not new_pts:
        return []
    new_xy = np.array(new_pts)
    old_xy = np.array([(v[0], v[1]) for v in source_verts])
    old_ros = np.array([v[2] for v in source_verts])
    old_fi = np.array([v[3] for v in source_verts])
    dists = np.hypot(
        new_xy[:, 0:1] - old_xy[None, :, 0],
        new_xy[:, 1:2] - old_xy[None, :, 1],
    )
    nearest_idx = np.argmin(dists, axis=1)
    return [
        (float(nx), float(ny), float(old_ros[i]), float(old_fi[i]))
        for (nx, ny), i in zip(new_pts, nearest_idx)
    ]


# Grelha de coordenadas usada para recuperar de falhas de robustez do
# GEOS na união (ver _union_robust). 1 cm — duas ordens de grandeza
# abaixo da resolução do terreno (dezenas de metros), por isso não muda
# o perímetro de forma observável.
UNION_PRECISION_M = 0.01


def _largest_polygon(geom):
    """Maior componente Polygon de uma geometria, ou None se não houver."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]
    return max(parts, key=lambda p: p.area) if parts else None


def _repair_polygon(poly):
    """Versão válida de `poly`, ou None se não for recuperável.

    make_valid() nem sempre resolve bem muitas auto-intersecções pequenas
    (pode devolver uma GeometryCollection de fragmentos); buffer(0) é o
    truque clássico do shapely para esses casos — mais tolerante,
    tenta-se a seguir antes de desistir.
    """
    if poly.is_valid:
        return poly
    for repair in (make_valid, lambda p: p.buffer(0)):
        try:
            best = _largest_polygon(repair(poly))
        except Exception:
            continue
        if best is not None and best.is_valid:
            return best
    return None


def _union_robust(accumulated_poly, candidate):
    """União tolerante a falhas de robustez do GEOS.

    O union() do GEOS levanta `TopologyException: side location conflict`
    quando as duas formas têm arestas quase coincidentes — o que aqui
    acontece sistematicamente, porque o candidato de cada timestep nasce
    dos vértices do acumulado anterior e partilha com ele quase toda a
    fronteira.

    Isto não era um contratempo, era fatal: ao falhar, o chamador repetia
    o acumulado anterior, cujos vértices geravam no timestep seguinte um
    candidato outra vez quase coincidente, a mesma união falhava na mesma
    aresta, e o perímetro ficava congelado até ao fim da simulação
    (observado numa corrida de 3h: três perímetros com 77.5 ha e 310
    vértices exactamente iguais, com o ROS a variar normalmente por
    baixo).

    A cura documentada é reduzir a precisão das coordenadas antes da
    operação — com uma grelha explícita o GEOS deixa de ter arestas
    "quase" coincidentes para desempatar. Só se tenta depois de a união
    directa falhar, para não degradar o caso normal.
    """
    if accumulated_poly is None:
        return candidate
    try:
        return accumulated_poly.union(candidate)
    except Exception as e:
        log.warning(
            "Simulação: união directa falhou (%s) — nova tentativa com "
            "precisão reduzida a %g m", e, UNION_PRECISION_M,
        )
    a = _repair_polygon(set_precision(accumulated_poly, UNION_PRECISION_M))
    b = _repair_polygon(set_precision(candidate, UNION_PRECISION_M))
    if a is None or b is None:
        raise ValueError("redução de precisão não produziu polígonos utilizáveis")
    return a.union(b)


def _accumulated_from_verts(verts: list):
    """Polígono acumulado ressincronizado com os vértices, já validado.

    O acumulado é reconstruído a partir do `verts` rediscretizado a cada
    timestep (ver ciclo em _propagate) para não crescer em complexidade
    sem limite. Mas a rediscretização insere e remove pontos ao longo da
    frente, o que pode introduzir auto-intersecções — e era exactamente
    isso que envenenava a união seguinte: o candidato passava por
    make_valid(), o acumulado ressincronizado não passava por nada.
    Validar aqui é o que evita o congelamento na origem; o retry de
    _union_robust é a rede de segurança.
    """
    poly = Polygon([(x, y) for x, y, _, _ in verts])
    repaired = _repair_polygon(poly)
    if repaired is None:
        log.warning(
            "Simulação: acumulado ressincronizado inválido e não reparável "
            "— mantido como está"
        )
        return poly
    return repaired


def _merge_into_accumulated(new_verts: list, accumulated_poly, stats: Optional[dict] = None):
    """Funde a forma deste timestep (new_verts, possivelmente
    auto-intersectante) no polígono acumulado, em vez de reconstruir do
    zero — garante que a área já queimada nunca retrocede nem "salta"
    para uma forma desligada (a área queimada mantém-se sempre queimada).

    Devolve (novos_vertices_com_ros_fi, novo_accumulated_poly). Nunca
    devolve new_verts em bruto quando este está auto-intersectante — a
    propagação Richards por pontos-marcadores auto-intersecta-se
    facilmente sobre terreno/combustível heterogéneo (pontos vizinhos com
    ROS muito diferentes "ultrapassam-se", dobrando a frente sobre si
    própria em forma de "flor"); se não for possível limpar a forma deste
    timestep (make_valid/buffer(0) a devolverem algo que não seja um
    Polygon/MultiPolygon utilizável), repete o último polígono acumulado
    válido em vez de deixar passar o anel corrompido para o snapshot.
    """
    if not HAS_SHAPELY or len(new_verts) < 3:
        return new_verts, accumulated_poly

    def _repeat_last_good():
        # Repetir o acumulado é congelar o perímetro neste timestep: a
        # área queimada não avança, só o ROS/FLI dos vértices é
        # reatribuído. Conta-se para o chamador poder dizê-lo em vez de
        # devolver perímetros iguais sem explicação.
        if stats is not None:
            stats["frozen_steps"] = stats.get("frozen_steps", 0) + 1
        if accumulated_poly is not None and not accumulated_poly.is_empty:
            pts = list(accumulated_poly.exterior.coords[:-1])
            return _reassign_ros_fi(pts, new_verts), accumulated_poly
        return new_verts, accumulated_poly

    try:
        pts_2d = [(v[0], v[1]) for v in new_verts]
        candidate = Polygon(pts_2d)
        if not candidate.is_valid:
            candidate = make_valid(candidate)
        if not isinstance(candidate, (Polygon, MultiPolygon)) or candidate.is_empty:
            # make_valid() nem sempre resolve bem muitas auto-intersecções
            # pequenas (pode devolver GeometryCollection com fragmentos);
            # buffer(0) é o truque clássico do shapely para estes casos —
            # mais tolerante, tenta-se antes de desistir.
            candidate = Polygon(pts_2d).buffer(0)
        if not isinstance(candidate, (Polygon, MultiPolygon)) or candidate.is_empty:
            log.warning("Simulação: candidato inválido/vazio neste timestep — repete último acumulado")
            return _repeat_last_good()

        merged = _union_robust(accumulated_poly, candidate)

        if isinstance(merged, MultiPolygon):
            geoms = sorted(merged.geoms, key=lambda p: p.area, reverse=True)
            main = geoms[0]
            if len(geoms) > 1 and geoms[1].area > 0.01 * main.area:
                log.warning(
                    "Simulação: união produziu componente secundário não "
                    "negligenciável (%.3f%% do principal) — descartado",
                    100.0 * geoms[1].area / main.area,
                )
            merged_shape = main
        else:
            merged_shape = merged

        if merged_shape.is_empty or not isinstance(merged_shape, Polygon):
            log.warning("Simulação: forma fundida inválida neste timestep — repete último acumulado")
            return _repeat_last_good()

        new_pts = list(merged_shape.exterior.coords[:-1])
        result = _reassign_ros_fi(new_pts, new_verts)
        return result, merged_shape
    except Exception as e:
        log.warning("Simulação: erro a fundir polígono acumulado: %s", e)
        return _repeat_last_good()


# ---------------------------------------------------------------------------
# Conversão WGS84 → CRS projetado
# ---------------------------------------------------------------------------

def _wgs84_to_proj(lat: float, lon: float, proj_crs) -> tuple[float, float]:
    xs, ys = rio_transform("EPSG:4326", proj_crs, [lon], [lat])
    return xs[0], ys[0]


def _wgs84_list_to_proj(points: list[tuple[float, float]], proj_crs) -> list[tuple[float, float]]:
    """Converte uma lista de (lat, lon) para o CRS projetado, de uma vez."""
    lons = [lon for _, lon in points]
    lats = [lat for lat, _ in points]
    xs, ys = rio_transform("EPSG:4326", proj_crs, lons, lats)
    return list(zip(xs, ys))


# ---------------------------------------------------------------------------
# Ponto de entrada principal (síncrono — corre em thread)
# ---------------------------------------------------------------------------

def run_simulation_sync(
    lat: float,
    lon: float,
    weather_hourly: list[WeatherConditions],
    fuel_models: dict[int, FuelModelPT],
    duration_h: float,
    *,
    rasters: Optional[LandscapeRasters] = None,
    multiband_path: Optional[str] = None,
    bbox_km: float = 15.0,
    resolution_m: Optional[float] = None,
    distance_resolution_m: Optional[float] = None,
    ignition_points: Optional[list[tuple[float, float]]] = None,
    fuel_moisture_table: Optional[dict[int, FuelMoistureRow]] = None,
) -> dict:
    """Corre a simulação completa. Devolve dict para gravar em result_json.

    `fuel_moisture_table`: se dado (Initial Fuel Moistures .FMS FARSITE,
    ver fuel_moisture_table.py), substitui as humidades calculadas a
    partir da meteo por uma procura por modelo de combustível em cada
    ponto/vértice — mais preciso do que os cenários BehavePlus de
    fuel_moisture_scenarios.py, que aplicam um único conjunto de
    humidades a toda a simulação independentemente do combustível local.

    weather_hourly: lista com um WeatherConditions derivado por hora de simulação
    (índice 0 = hora de ignição, 1 = t+1h, …).  A grelha ROS é calculada
    com a meteo inicial (índice 0).

    `rasters`/`multiband_path`: exatamente um dos dois (mesmo contrato de
    `LandscapeReader.__init__`).

    `resolution_m`: se None (default), usa a resolução nativa do landscape
    file carregado (10m). Sujeito a
    `MAX_GRID_CELLS` — se `bbox_km` × resolução implicar mais células do
    que o orçamento, a resolução é ajustada para cima automaticamente; a
    resolução pedida e a efetivamente usada ficam registadas em `meta`.
    Aplica-se apenas à grelha ROS/FLI/chama visualizada, não ao perímetro.

    `distance_resolution_m`: se None (default), usa também a resolução
    nativa do landscape file. Controla o espaçamento dos vértices do
    perímetro e o timestep dinâmico da propagação (FARSITE "distance
    resolution") — independente de `resolution_m`/`bbox_km`, já que a
    propagação não é limitada pelo bbox. Sujeito a `MAX_PERIMETER_VERTICES`
    (ajuste unidirecional em runtime — ver `_propagate`).

    `ignition_points`: se None (default), ignição pontual em `(lat, lon)`
    — comportamento idêntico ao anterior. Se dado, `(lat, lon)` são
    ignorados para a forma inicial (mas continuam a ir para `meta`); 1
    ponto = ignição pontual "livre" noutro local, 2+ = linha de ignição
    (buffer ao longo da linha — ver `_propagate`). A grelha ROS é
    centrada no centróide dos pontos dados.
    """
    if not HAS_RASTERIO or not HAS_SHAPELY:
        raise RuntimeError("rasterio e shapely são necessários para simulação espacial")
    if not weather_hourly:
        raise ValueError("weather_hourly não pode ser vazio")

    snapshot_hours = [h for h in SNAPSHOT_HOURS_CANDIDATES if h <= duration_h]
    if duration_h not in snapshot_hours:
        snapshot_hours.append(duration_h)
    snapshot_hours.sort()

    wx0 = weather_hourly[0]
    requested_resolution_m = resolution_m
    requested_distance_resolution_m = distance_resolution_m

    with LandscapeReader(rasters=rasters, multiband_path=multiband_path) as reader:
        effective_resolution_m = resolution_m if resolution_m is not None else reader.native_resolution_m
        effective_distance_resolution_m = (
            distance_resolution_m if distance_resolution_m is not None else reader.native_resolution_m
        )

        grid_side_cells = (bbox_km * 1000.0) / effective_resolution_m
        if grid_side_cells * grid_side_cells > MAX_GRID_CELLS:
            coarsened_resolution_m = (bbox_km * 1000.0) / math.sqrt(MAX_GRID_CELLS)
            log.warning(
                "Simulação: %.1fm em %.1fkm implicaria %.0f células "
                "(limite %d) — resolução ajustada para %.1fm",
                effective_resolution_m, bbox_km,
                grid_side_cells * grid_side_cells, MAX_GRID_CELLS, coarsened_resolution_m,
            )
            effective_resolution_m = coarsened_resolution_m

        if ignition_points:
            ignition_points_proj = _wgs84_list_to_proj(ignition_points, reader.crs)
            xs = [p[0] for p in ignition_points_proj]
            ys = [p[1] for p in ignition_points_proj]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)  # centróide, só para centrar a grelha
            log.info("Simulação: ignição livre (%d ponto(s)) → centróide proj (%.0f, %.0f)",
                      len(ignition_points), cx, cy)
        else:
            ignition_points_proj = None
            cx, cy = _wgs84_to_proj(lat, lon, reader.crs)
            log.info("Simulação: ignição (%.4f, %.4f) → proj (%.0f, %.0f)", lat, lon, cx, cy)

        log.info("Simulação: a calcular grelha %.1fm (%.0f×%.0f km)...",
                 effective_resolution_m, bbox_km, bbox_km)
        grid = _build_ros_grid(
            reader, fuel_models, wx0, cx, cy, bbox_km, effective_resolution_m,
            fuel_moisture_table=fuel_moisture_table,
        )

        log.info("Simulação: a propagar %.1fh (distance_resolution=%.1fm, %d snapshots meteo)...",
                 duration_h, effective_distance_resolution_m, len(weather_hourly))
        snapshots, perimeter_coarsened = _propagate(
            reader, fuel_models, weather_hourly, cx, cy, duration_h, snapshot_hours,
            effective_distance_resolution_m, ignition_points_proj,
            fuel_moisture_table=fuel_moisture_table,
        )

        # Setas de direcção: grelha grosseira centrada na extensão do
        # perímetro FINAL (não no bbox_km de visualização, tipicamente
        # muito maior do que a área queimada numa simulação de poucas
        # horas — deixaria a grelha de setas quase vazia após o recorte).
        arrows = {"type": "FeatureCollection", "features": []}
        if snapshots:
            final_lons, final_lats = zip(*snapshots[-1].polygon_wgs84["coordinates"][0])
            corners_proj = _wgs84_list_to_proj(
                list(zip(final_lats, final_lons)), reader.crs,
            )
            xs_f = [p[0] for p in corners_proj]
            ys_f = [p[1] for p in corners_proj]
            margin_m = max(0.15 * max(max(xs_f) - min(xs_f), max(ys_f) - min(ys_f)), 100.0)
            # Um campo de setas por instantâneo, cada um com a meteo da sua
            # hora — mesmo índice horário que a propagação usa
            # (weather_hourly[min(int(t), len-1)], ver _propagate).
            arrow_steps = [
                (
                    snap.t_h,
                    weather_hourly[min(int(snap.t_h), len(weather_hourly) - 1)],
                    snap.polygon_wgs84,
                )
                for snap in snapshots
            ]
            arrows = _build_direction_arrows(
                reader, fuel_models, arrow_steps,
                min(xs_f) - margin_m, min(ys_f) - margin_m,
                max(xs_f) + margin_m, max(ys_f) + margin_m,
                fuel_moisture_table=fuel_moisture_table,
            )

    if not snapshots:
        raise RuntimeError("Simulação não produziu perímetros válidos")

    final_perim = snapshots[-1].polygon_wgs84
    clipped_grid = _clip_grid_to_perimeter(grid, final_perim)
    # As setas já vêm recortadas ao perímetro de cada hora (ver
    # _build_direction_arrows), todos contidos no final — não se recorta
    # outra vez.
    clipped_arrows = arrows

    log.info("Simulação concluída: %d perímetros, %d células, %d setas",
             len(snapshots), len(clipped_grid["features"]), len(clipped_arrows["features"]))

    return {
        "perimeters": [
            {
                "t_h": s.t_h, "area_ha": s.area_ha, "geojson": s.polygon_wgs84,
                "ros_max_m_min": s.ros_max_m_min,
                "fli_max_kw_m": s.fli_max_kw_m,
                "flame_max_m": s.flame_max_m,
            }
            for s in snapshots
        ],
        "pixel_grid": clipped_grid,
        "spread_arrows": clipped_arrows,
        "weather_hourly": [
            {
                "t_h": i,
                "timestamp": wx.timestamp.isoformat() if wx.timestamp else None,
                "temperature_c": wx.temperature_c,
                "relative_humidity_pct": wx.relative_humidity_pct,
                "wind_speed_ms": wx.wind_speed_10m_ms,
                "wind_gust_ms": wx.wind_gust_10m_ms,
                "wind_direction_deg": wx.wind_direction_deg,
            }
            for i, wx in enumerate(weather_hourly)
            if i <= duration_h
        ],
        "meta": {
            "bbox_km":               bbox_km,
            "resolution_m":          effective_resolution_m,
            "resolution_requested_m": requested_resolution_m,  # None = nativa do landscape file
            "distance_resolution_m": effective_distance_resolution_m,
            "distance_resolution_requested_m": requested_distance_resolution_m,  # None = nativa
            "perimeter_resolution_coarsened": perimeter_coarsened,
            "ignition":              [lat, lon],
            "ignition_points":       ignition_points,  # None = ignição pontual em (lat, lon)
            "wind_speed_ms":         wx0.wind_speed_10m_ms,
            "wind_gust_ms":          wx0.wind_gust_10m_ms,
            "wind_dir_deg":          wx0.wind_direction_deg,
            "duration_h":            duration_h,
            "wx_snapshots":          len(weather_hourly),
        },
    }


async def run_simulation_async(
    lat: float,
    lon: float,
    weather_hourly: list[WeatherConditions],
    fuel_models: dict[int, FuelModelPT],
    duration_h: float,
    *,
    rasters: Optional[LandscapeRasters] = None,
    multiband_path: Optional[str] = None,
    bbox_km: float = 15.0,
    resolution_m: Optional[float] = None,
    distance_resolution_m: Optional[float] = None,
    ignition_points: Optional[list[tuple[float, float]]] = None,
    fuel_moisture_table: Optional[dict[int, FuelMoistureRow]] = None,
) -> dict:
    """Wrapper assíncrono — corre run_simulation_sync num executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: run_simulation_sync(
            lat, lon, weather_hourly, fuel_models, duration_h,
            rasters=rasters, multiband_path=multiband_path,
            bbox_km=bbox_km, resolution_m=resolution_m,
            distance_resolution_m=distance_resolution_m,
            ignition_points=ignition_points,
            fuel_moisture_table=fuel_moisture_table,
        ),
    )
