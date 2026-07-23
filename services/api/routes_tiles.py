"""
Tiles raster (XYZ) do modelo de combustível — overlay do mapa, não
ligado a nenhuma simulação (dado do terreno, não do tempo). Sem
autenticação (mesmo padrão de qualquer servidor de tiles público — os
basemaps OSM/Satélite/Topo já usados também não pedem API key; o dado
servido, classificação de vegetação, não é sensível como as
ocorrências/triagem).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response

from .deps import APIConfig, get_config

log = logging.getLogger(__name__)

router_tiles = APIRouter(prefix="/tiles", tags=["tiles"])

MIN_ZOOM = 8
MAX_ZOOM = 16
TILE_SIZE = 256

# Web Mercator — circunferência da Terra em metros (WGS84 esférico,
# convenção EPSG:3857 padrão de qualquer servidor XYZ).
_EARTH_CIRCUMFERENCE_M = 40075016.686
_ORIGIN_SHIFT_M = _EARTH_CIRCUMFERENCE_M / 2.0


def _tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Bounds (min_x, min_y, max_x, max_y) de um tile XYZ em EPSG:3857."""
    n = 2 ** z
    tile_size_m = _EARTH_CIRCUMFERENCE_M / n
    min_x = -_ORIGIN_SHIFT_M + x * tile_size_m
    max_x = -_ORIGIN_SHIFT_M + (x + 1) * tile_size_m
    max_y = _ORIGIN_SHIFT_M - y * tile_size_m
    min_y = _ORIGIN_SHIFT_M - (y + 1) * tile_size_m
    return min_x, min_y, max_x, max_y


_TRANSPARENT_TILE_PNG: bytes = b""  # preenchido lazy na primeira chamada


def _transparent_png() -> bytes:
    global _TRANSPARENT_TILE_PNG
    if not _TRANSPARENT_TILE_PNG:
        _TRANSPARENT_TILE_PNG = _encode_rgba_png(np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8))
    return _TRANSPARENT_TILE_PNG


def _encode_rgba_png(rgba: np.ndarray) -> bytes:
    """RGBA (H, W, 4) uint8 -> bytes PNG, via rasterio/GDAL — evita
    acrescentar Pillow como dependência nova só para isto."""
    import rasterio
    from rasterio.io import MemoryFile

    h, w, _ = rgba.shape
    # rasterio quer bandas em (banda, linha, coluna)
    bands = np.moveaxis(rgba, -1, 0)
    with MemoryFile() as memfile:
        with memfile.open(
            driver="PNG", width=w, height=h, count=4, dtype="uint8",
        ) as dst:
            dst.write(bands)
        return memfile.read()


def _cache_path(landscape_dir: str, z: int, x: int, y: int) -> Path:
    return Path(landscape_dir) / "tile_cache" / "fuel-model" / str(z) / str(x) / f"{y}.png"


def _render_fuel_model_tile(config: APIConfig, z: int, x: int, y: int) -> bytes:
    from fogos_triage.fuel_model_colors import build_fuel_model_palette
    from fogos_triage.landscape import LandscapeRasters, ensure_landscape
    from fogos_triage.landscape import LandscapeReader
    from rasterio.transform import from_bounds as transform_from_bounds
    from rasterio.warp import Resampling, reproject, transform_bounds

    ensure_landscape(
        landscape_dir=config.landscape_dir,
        r2_account_id=config.r2_account_id,
        r2_access_key_id=config.r2_access_key_id,
        r2_secret_access_key=config.r2_secret_access_key,
        r2_bucket=config.r2_bucket,
        r2_prefix=config.r2_prefix,
        filename=config.landscape_file,
    )

    if config.landscape_file:
        rasters_kwargs = {"multiband_path": os.path.join(config.landscape_dir, config.landscape_file)}
    else:
        rasters_kwargs = {"rasters": LandscapeRasters.from_directory(config.landscape_dir)}

    min_x_merc, min_y_merc, max_x_merc, max_y_merc = _tile_bounds_3857(z, x, y)
    dst_transform = transform_from_bounds(min_x_merc, min_y_merc, max_x_merc, max_y_merc, TILE_SIZE, TILE_SIZE)

    with LandscapeReader(**rasters_kwargs) as reader:
        # Bounds do tile, no CRS nativo do landscape file, com margem
        # para cobrir bem os cantos depois da reprojecção.
        src_min_x, src_min_y, src_max_x, src_max_y = transform_bounds(
            "EPSG:3857", reader.crs, min_x_merc, min_y_merc, max_x_merc, max_y_merc,
        )
        margin_x = (src_max_x - src_min_x) * 0.1
        margin_y = (src_max_y - src_min_y) * 0.1

        arrays, nodata, window_transform = reader.read_window(
            ["fuel_model"],
            src_min_x - margin_x, src_min_y - margin_y,
            src_max_x + margin_x, src_max_y + margin_y,
        )
        src_arr = arrays.get("fuel_model")
        if src_arr is None:
            return _transparent_png()

        src_nodata = nodata.get("fuel_model")
        dst_arr = np.full((TILE_SIZE, TILE_SIZE), src_nodata if src_nodata is not None else -32768, dtype=src_arr.dtype)

        reproject(
            source=src_arr,
            destination=dst_arr,
            src_transform=window_transform,
            src_crs=reader.crs,
            src_nodata=src_nodata,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            dst_nodata=src_nodata,
            resampling=Resampling.nearest,  # dado categórico — nunca bilinear/cubic
        )

    # Nodata -> 98 (não combustível), mesma convenção já usada em
    # _build_ros_grid()/simulation.py para pixels fora de cobertura.
    fuel_nums = dst_arr.astype(np.int32)
    if src_nodata is not None:
        fuel_nums = np.where(fuel_nums == int(src_nodata), 98, fuel_nums)

    palette = build_fuel_model_palette(sorted(set(fuel_nums.ravel().tolist())))
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    for num, color in palette.items():
        rgba[fuel_nums == num] = color

    return _encode_rgba_png(rgba)


@router_tiles.get(
    "/fuel-model/{z}/{x}/{y}.png",
    summary="Tile raster (PNG) do modelo de combustível — overlay independente de simulação",
)
async def get_fuel_model_tile(z: int, x: int, y: int, config: APIConfig = Depends(get_config)):
    if z < MIN_ZOOM or z > MAX_ZOOM:
        raise HTTPException(status_code=404, detail=f"Zoom fora do intervalo suportado ({MIN_ZOOM}-{MAX_ZOOM})")

    cache_path = _cache_path(config.landscape_dir, z, x, y)
    if cache_path.exists():
        return Response(content=cache_path.read_bytes(), media_type="image/png")

    if not Path(config.landscape_dir).exists() and not config.r2_account_id:
        return Response(content=_transparent_png(), media_type="image/png")

    try:
        png_bytes = await _run_in_executor(_render_fuel_model_tile, config, z, x, y)
    except Exception as exc:
        log.warning("Tile fuel-model z=%d x=%d y=%d falhou: %s", z, x, y, exc)
        return Response(content=_transparent_png(), media_type="image/png")

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(png_bytes)
    except OSError as exc:
        log.warning("Não consegui gravar tile em cache (%s): %s", cache_path, exc)

    return Response(content=png_bytes, media_type="image/png")


async def _run_in_executor(fn, *args):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args))
