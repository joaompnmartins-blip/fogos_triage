"""
Lookup nos rasters da Landscape File (LCP) para uma coordenada (lat, lon).

Assume que todos os rasters TIFF se sobrepõem perfeitamente (mesmo CRS, transform,
e dimensões). Lê uma janela mínima à volta do ponto e devolve os valores.

Para performance em volume (muitas ocorrências por minuto), usar contexto com
ficheiros já abertos via rasterio.open ou pré-carregar em memória.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import rasterio
    from rasterio.transform import rowcol
    from rasterio.warp import transform as rio_transform
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

from .schemas import TerrainConditions


@dataclass
class LandscapeRasters:
    """Caminhos dos 7 rasters da Landscape File PT."""
    elevation: Path
    slope: Path
    aspect: Path
    fuel_model: Path
    stand_height: Optional[Path] = None
    canopy_cover: Optional[Path] = None
    canopy_base_height: Optional[Path] = None
    canopy_bulk_density: Optional[Path] = None  # opcional, deriva-se se ausente

    @classmethod
    def from_directory(cls, base_dir: str | Path,
                       filename_pattern: dict[str, str] | None = None) -> "LandscapeRasters":
        """
        Constrói os caminhos a partir de um diretório base.
        Pattern default assume nomes em português:
        elevation -> altitude.tif
        slope -> declive.tif
        aspect -> exposicao.tif
        fuel_model -> modelos_combustivel.tif
        stand_height -> altura_povoamento.tif
        canopy_cover -> cobertura_copas.tif
        canopy_base_height -> altura_base_copa.tif
        """
        base = Path(base_dir)
        if filename_pattern is None:
            filename_pattern = {
                "elevation": "Altitude.tif",
                "slope": "declive.tif",
                "aspect": "Exposicao.tif",
                "fuel_model": "modelos_combustivel.tif",
                "stand_height": "Altura_Povoamento.tif",
                "canopy_cover": "cobertura_copa.tif",
                "canopy_base_height": "altura_base_copa.tif",
                "canopy_bulk_density": "densidade_copas.tif",
            }
        return cls(
            elevation=base / filename_pattern["elevation"],
            slope=base / filename_pattern["slope"],
            aspect=base / filename_pattern["aspect"],
            fuel_model=base / filename_pattern["fuel_model"],
            stand_height=base / filename_pattern.get("stand_height", "_missing_"),
            canopy_cover=base / filename_pattern.get("canopy_cover", "_missing_"),
            canopy_base_height=base / filename_pattern.get("canopy_base_height", "_missing_"),
            canopy_bulk_density=base / filename_pattern.get("canopy_bulk_density", "_missing_"),
        )


class LandscapeReader:
    """
    Reader eficiente para os rasters da LCP.
    Abre os ficheiros uma vez e reutiliza.
    """

    def __init__(self, rasters: LandscapeRasters):
        if not HAS_RASTERIO:
            raise ImportError("rasterio é necessário para LandscapeReader")
        self.rasters = rasters
        self._datasets: dict[str, "rasterio.DatasetReader"] = {}

    def __enter__(self):
        for name, path in [
            ("elevation", self.rasters.elevation),
            ("slope", self.rasters.slope),
            ("aspect", self.rasters.aspect),
            ("fuel_model", self.rasters.fuel_model),
        ]:
            self._datasets[name] = rasterio.open(path)
        # opcionais
        for name, path in [
            ("stand_height", self.rasters.stand_height),
            ("canopy_cover", self.rasters.canopy_cover),
            ("canopy_base_height", self.rasters.canopy_base_height),
            ("canopy_bulk_density", self.rasters.canopy_bulk_density),
        ]:
            if path is not None and path.exists():
                self._datasets[name] = rasterio.open(path)
        return self

    def __exit__(self, *args):
        for ds in self._datasets.values():
            ds.close()
        self._datasets.clear()

    _NEIGHBOURHOOD_ANGLES_DEG = [0, 45, 90, 135, 180, 225, 270, 315]

    def sample_neighbourhood(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 200.0,
    ) -> list[TerrainConditions]:
        """
        Amostra 9 pontos: ignição + 8 direcções (N/NE/E/SE/S/SW/W/NW) a radius_m.
        O primeiro elemento é sempre o ponto de ignição.
        Pixels fora da extensão do raster são ignorados silenciosamente.
        """
        d_lat = radius_m / 111320.0
        d_lon = radius_m / (111320.0 * math.cos(math.radians(latitude)))

        points = [(latitude, longitude)]
        for a_deg in self._NEIGHBOURHOOD_ANGLES_DEG:
            a_rad = math.radians(a_deg)
            points.append((
                latitude  + d_lat * math.cos(a_rad),
                longitude + d_lon * math.sin(a_rad),
            ))

        results = []
        for lat_p, lon_p in points:
            try:
                results.append(self.sample(lat_p, lon_p))
            except Exception:
                pass

        return results if results else [self.sample(latitude, longitude)]

    def sample(self, latitude: float, longitude: float) -> TerrainConditions:
        """
        Lê os valores dos rasters num ponto (lat, lon em WGS84).
        Reprojeta as coordenadas para o CRS dos rasters se necessário.
        """
        # Usa o CRS do primeiro dataset
        ref_ds = self._datasets["elevation"]
        target_crs = ref_ds.crs
        if target_crs.to_epsg() != 4326:
            xs, ys = rio_transform("EPSG:4326", target_crs, [longitude], [latitude])
            x, y = xs[0], ys[0]
        else:
            x, y = longitude, latitude

        # row, col
        row, col = rowcol(ref_ds.transform, x, y)

        # Lê uma janela 1x1 em cada raster
        def _read_at(ds_name: str) -> Optional[float]:
            ds = self._datasets.get(ds_name)
            if ds is None:
                return None
            try:
                window = rasterio.windows.Window(col, row, 1, 1)
                arr = ds.read(1, window=window)
                val = float(arr[0, 0])
                # NoData?
                if ds.nodata is not None and val == ds.nodata:
                    return None
                return val
            except (IndexError, ValueError):
                return None

        elevation = _read_at("elevation") or 0.0
        slope_deg = _read_at("slope") or 0.0
        aspect_deg = _read_at("aspect") or 0.0
        fuel_num = int(_read_at("fuel_model") or 98)

        # Slope pode vir em graus ou em percent dependendo do produto
        # Assumimos graus (formato standard FARSITE/landscape file)
        slope_fraction = math.tan(math.radians(slope_deg))

        cbd_raw = _read_at("canopy_bulk_density")
        sh_raw = _read_at("stand_height")
        cbh_raw = _read_at("canopy_base_height")
        return TerrainConditions(
            elevation_m=elevation,
            slope_fraction=slope_fraction,
            slope_degrees=slope_deg,
            aspect_degrees=aspect_deg,
            fuel_model_num=fuel_num,
            # alturas armazenadas em decímetros nos rasters PT
            stand_height_m=sh_raw / 10.0 if sh_raw is not None else None,
            canopy_cover_pct=_read_at("canopy_cover"),
            canopy_base_height_m=cbh_raw / 10.0 if cbh_raw is not None else None,
            # densidade_copas.tif está em kg/m³ × 100
            canopy_bulk_density_kg_m3=cbd_raw / 100.0 if cbd_raw is not None else None,
        )


# Versão mock para testes sem rasterio
class MockLandscapeReader:
    """
    Versão mock que devolve valores fixos.
    Útil para testes unitários e desenvolvimento offline.
    """
    def __init__(self, terrain: TerrainConditions):
        self._terrain = terrain

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def sample_neighbourhood(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 200.0,
    ) -> list[TerrainConditions]:
        return [self._terrain] * 9

    def sample(self, latitude: float, longitude: float) -> TerrainConditions:
        return self._terrain
