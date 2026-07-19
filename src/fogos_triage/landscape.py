"""
Lookup nos rasters da Landscape File (LCP) para uma coordenada (lat, lon).

Assume que todos os rasters TIFF se sobrepõem perfeitamente (mesmo CRS, transform,
e dimensões). Lê uma janela mínima à volta do ponto e devolve os valores.

Para performance em volume (muitas ocorrências por minuto), usar contexto com
ficheiros já abertos via rasterio.open ou pré-carregar em memória.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

LANDSCAPE_TIFS = [
    "Altitude.tif",
    "declive.tif",
    "Exposicao.tif",
    "modelos_combustivel.tif",
    "Altura_Povoamento.tif",
    "cobertura_copa.tif",
    "altura_base_copa.tif",
    "densidade_copas.tif",
]

# Nomes das bandas (via tag `description`) num ficheiro Landscape File
# combinado (multibanda), na ordem usada pelo ficheiro-piloto Alto Minho.
BAND_NAME_MAP = {
    "Elevation": "elevation",
    "Slope": "slope",
    "Aspect": "aspect",
    "Fuel Model": "fuel_model",
    "Canopy Cover": "canopy_cover",
    "Stand Height": "stand_height",
    "Canopy Base Height": "canopy_base_height",
    "Canopy Bulk Density": "canopy_bulk_density",
}
# Fallback caso o ficheiro não tenha as tags `description` nas bandas.
BAND_ORDER_FALLBACK = [
    "elevation", "slope", "aspect", "fuel_model",
    "canopy_cover", "stand_height", "canopy_base_height", "canopy_bulk_density",
]


def ensure_landscape(
    landscape_dir: str | Path,
    r2_account_id: str | None = None,
    r2_access_key_id: str | None = None,
    r2_secret_access_key: str | None = None,
    r2_bucket: str = "fogos-landscape",
    r2_prefix: str = "landscape/",
    filename: str | None = None,
) -> None:
    """
    Garante que os TIFFs da Landscape File estão em landscape_dir.

    Se algum ficheiro faltar e as credenciais R2 estiverem presentes,
    descarrega do bucket Cloudflare R2. Bloqueia até o download concluir.
    Levanta RuntimeError se os TIFFs estiverem em falta e não for possível descarregar.

    Se `filename` for dado, assume modo multibanda — garante apenas esse
    ficheiro único (em vez dos 8 TIFFs de LANDSCAPE_TIFS).
    """
    landscape_path = Path(landscape_dir)
    landscape_path.mkdir(parents=True, exist_ok=True)

    expected = [filename] if filename else LANDSCAPE_TIFS
    missing = [f for f in expected if not (landscape_path / f).exists()]
    if not missing:
        log.info("Landscape: %d TIFFs presentes em %s", len(expected), landscape_path)
        return

    log.info("Landscape: %d TIFFs em falta — %s", len(missing), missing)

    if not all([r2_account_id, r2_access_key_id, r2_secret_access_key]):
        raise RuntimeError(
            f"TIFFs em falta em {landscape_path} e credenciais R2 não configuradas. "
            "Definir R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY."
        )

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        raise RuntimeError("boto3 não instalado — necessário para download dos TIFFs do R2")

    endpoint = f"https://{r2_account_id}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=r2_access_key_id,
        aws_secret_access_key=r2_secret_access_key,
        config=BotoConfig(signature_version="s3v4"),
    )

    prefix = r2_prefix.rstrip("/") + "/"
    for missing_name in missing:
        key = f"{prefix}{missing_name}"
        dest = landscape_path / missing_name
        log.info("  A descarregar %s → %s ...", key, dest)
        s3.download_file(r2_bucket, key, str(dest))
        size_mb = dest.stat().st_size / 1_048_576
        log.info("  %s — %.0f MB", missing_name, size_mb)

    log.info("Landscape: download completo")

try:
    import rasterio
    from rasterio.transform import rowcol
    from rasterio.warp import transform as rio_transform, transform_bounds as rio_transform_bounds
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

    Dois modos, mutuamente exclusivos:
    - `rasters`: um raster (single-band) por camada (Landscape File PT nacional).
    - `multiband_path`: um único GeoTIFF multibanda, com as bandas
      identificadas pela tag `description` (ver BAND_NAME_MAP), ou pela
      ordem fixa em BAND_ORDER_FALLBACK se as tags estiverem ausentes.
    """

    def __init__(
        self,
        rasters: LandscapeRasters | None = None,
        multiband_path: str | Path | None = None,
    ):
        if not HAS_RASTERIO:
            raise ImportError("rasterio é necessário para LandscapeReader")
        if (rasters is None) == (multiband_path is None):
            raise ValueError("Dar exatamente um de: rasters, multiband_path")
        self.rasters = rasters
        self.multiband_path = Path(multiband_path) if multiband_path else None
        self._datasets: dict[str, "rasterio.DatasetReader"] = {}
        self._band_index: dict[str, int] = {}
        self.bounds_wgs84: Optional[tuple[float, float, float, float]] = None

    def __enter__(self):
        if self.multiband_path is not None:
            ds = rasterio.open(self.multiband_path)
            self._datasets["_multiband"] = ds
            descriptions = ds.descriptions or ()
            for i, desc in enumerate(descriptions, start=1):
                name = BAND_NAME_MAP.get(desc)
                if name:
                    self._band_index[name] = i
            if not self._band_index:
                # ficheiro sem tags description — assume ordem fixa
                for i, name in enumerate(BAND_ORDER_FALLBACK[:ds.count], start=1):
                    self._band_index[name] = i
        else:
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

        ref_ds = self._ref_dataset()
        self.bounds_wgs84 = rio_transform_bounds(
            ref_ds.crs, "EPSG:4326", *ref_ds.bounds,
        )
        return self

    def __exit__(self, *args):
        for ds in self._datasets.values():
            ds.close()
        self._datasets.clear()
        self._band_index.clear()

    def _ref_dataset(self) -> "rasterio.DatasetReader":
        """Dataset usado como referência de CRS/transform/extensão."""
        if self.multiband_path is not None:
            return self._datasets["_multiband"]
        return self._datasets["elevation"]

    @property
    def crs(self):
        return self._ref_dataset().crs

    @property
    def transform(self):
        return self._ref_dataset().transform

    @property
    def native_resolution_m(self) -> float:
        """Tamanho do pixel (m) no CRS nativo do raster carregado."""
        return abs(self._ref_dataset().transform.a)

    def contains(self, latitude: float, longitude: float) -> bool:
        """True se o ponto cai dentro da extensão coberta pelo(s) raster(s)."""
        if self.bounds_wgs84 is None:
            return True
        min_lon, min_lat, max_lon, max_lat = self.bounds_wgs84
        return min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat

    def sample_neighbourhood(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 50.0,
    ) -> list[TerrainConditions]:
        """
        Amostra uma grelha densa de pontos dentro de radius_m do ponto de
        ignição, espaçada à resolução nativa do raster (nunca mais fina que
        radius_m/10, para limitar o nº de leituras por ciclo). Com o
        raster PT a 10m e radius_m=50, dá ~81 pontos (grelha 11×11
        recortada ao círculo), em vez de amostrar só o perímetro.
        O primeiro elemento é sempre o ponto de ignição.
        Pixels fora da extensão do raster são ignorados silenciosamente.
        """
        spacing_m = max(self.native_resolution_m, radius_m / 10.0)
        n_steps = max(1, int(radius_m // spacing_m))

        offsets_m = [(0.0, 0.0)]
        for i in range(-n_steps, n_steps + 1):
            for j in range(-n_steps, n_steps + 1):
                if i == 0 and j == 0:
                    continue
                dx, dy = i * spacing_m, j * spacing_m
                if dx * dx + dy * dy <= radius_m * radius_m:
                    offsets_m.append((dx, dy))

        d_lat_per_m = 1.0 / 111320.0
        d_lon_per_m = 1.0 / (111320.0 * math.cos(math.radians(latitude)))

        results = []
        for dx, dy in offsets_m:
            lat_p = latitude + dy * d_lat_per_m
            lon_p = longitude + dx * d_lon_per_m
            try:
                results.append(self.sample(lat_p, lon_p))
            except Exception:
                pass

        return results if results else [self.sample(latitude, longitude)]

    def _read_field(self, name: str, row: int, col: int) -> Optional[float]:
        """Lê uma janela 1x1 na camada pedida (dataset próprio, ou banda do
        ficheiro multibanda, consoante o modo)."""
        if self.multiband_path is not None:
            band = self._band_index.get(name)
            if band is None:
                return None
            ds = self._datasets["_multiband"]
        else:
            ds = self._datasets.get(name)
            if ds is None:
                return None
            band = 1
        try:
            window = rasterio.windows.Window(col, row, 1, 1)
            arr = ds.read(band, window=window)
            val = float(arr[0, 0])
            nodata = ds.nodatavals[band - 1] if ds.nodatavals else ds.nodata
            if nodata is not None and val == nodata:
                return None
            return val
        except (IndexError, ValueError):
            return None

    def sample(self, latitude: float, longitude: float) -> TerrainConditions:
        """
        Lê os valores dos rasters num ponto (lat, lon em WGS84).
        Reprojeta as coordenadas para o CRS dos rasters se necessário.
        """
        target_crs = self.crs
        if target_crs.to_epsg() != 4326:
            xs, ys = rio_transform("EPSG:4326", target_crs, [longitude], [latitude])
            x, y = xs[0], ys[0]
        else:
            x, y = longitude, latitude
        return self.sample_projected(x, y)

    def sample_projected(self, x: float, y: float) -> TerrainConditions:
        """
        Lê os valores dos rasters num ponto já em coordenadas do CRS nativo
        (sem reprojeção) — usado quando o chamador já trabalha no CRS
        projetado, evitando transformar ida-e-volta desnecessariamente.
        """
        row, col = rowcol(self.transform, x, y)

        elevation = self._read_field("elevation", row, col) or 0.0
        slope_deg = self._read_field("slope", row, col) or 0.0
        aspect_deg = self._read_field("aspect", row, col) or 0.0
        fuel_num = int(self._read_field("fuel_model", row, col) or 98)

        # Slope pode vir em graus ou em percent dependendo do produto
        # Assumimos graus (formato standard FARSITE/landscape file)
        slope_fraction = math.tan(math.radians(slope_deg))

        cbd_raw = self._read_field("canopy_bulk_density", row, col)
        sh_raw = self._read_field("stand_height", row, col)
        cbh_raw = self._read_field("canopy_base_height", row, col)
        return TerrainConditions(
            elevation_m=elevation,
            slope_fraction=slope_fraction,
            slope_degrees=slope_deg,
            aspect_degrees=aspect_deg,
            fuel_model_num=fuel_num,
            # alturas armazenadas em decímetros nos rasters PT
            stand_height_m=sh_raw / 10.0 if sh_raw is not None else None,
            canopy_cover_pct=self._read_field("canopy_cover", row, col),
            canopy_base_height_m=cbh_raw / 10.0 if cbh_raw is not None else None,
            # densidade_copas.tif está em kg/m³ × 100
            canopy_bulk_density_kg_m3=cbd_raw / 100.0 if cbd_raw is not None else None,
        )

    def read_window(
        self,
        names: list[str],
        min_x: float, min_y: float, max_x: float, max_y: float,
    ) -> tuple[dict[str, np.ndarray], dict[str, Optional[float]], "rasterio.Affine"]:
        """
        Lê uma janela (bbox em coordenadas do CRS nativo) de uma vez para
        cada campo pedido — evita uma leitura rasterio por ponto quando se
        precisa de amostrar uma grelha densa (ex. grelha de simulação).

        Devolve (arrays, nodata_por_campo, window_transform). Todos os
        arrays partilham a mesma forma e georreferenciação (os rasters
        assumem-se alinhados — ver docstring do módulo); `window_transform`
        mapeia (linha, coluna) da janela para (x, y).
        Pixels fora da extensão do raster são preenchidos com o nodata da
        camada (boundless read).
        """
        window = rasterio.windows.from_bounds(min_x, min_y, max_x, max_y, self.transform)
        window = window.round_offsets().round_lengths()
        window_transform = rasterio.windows.transform(window, self.transform)

        arrays: dict[str, np.ndarray] = {}
        nodata: dict[str, Optional[float]] = {}
        for name in names:
            if self.multiband_path is not None:
                band = self._band_index.get(name)
                if band is None:
                    continue
                ds = self._datasets["_multiband"]
            else:
                ds = self._datasets.get(name)
                if ds is None:
                    continue
                band = 1
            band_nodata = ds.nodatavals[band - 1] if ds.nodatavals else ds.nodata
            fill_value = band_nodata if band_nodata is not None else -9999.0
            arr = ds.read(band, window=window, boundless=True, fill_value=fill_value)
            arrays[name] = arr
            nodata[name] = band_nodata

        return arrays, nodata, window_transform


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
        radius_m: float = 50.0,
    ) -> list[TerrainConditions]:
        return [self._terrain] * 81

    def sample(self, latitude: float, longitude: float) -> TerrainConditions:
        return self._terrain

    def contains(self, latitude: float, longitude: float) -> bool:
        return True
