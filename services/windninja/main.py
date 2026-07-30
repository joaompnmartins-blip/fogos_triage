"""
Sidecar WindNinja — campo de vento ajustado ao relevo.

Wrapper HTTP fino sobre o `WindNinja_cli`, isolado num container próprio
porque o WindNinja só se instala por conda-forge e o resto da stack é
`python:3.12-slim` + pip (ver `services/windninja/Dockerfile` e
`WINDNINJA_PLAN.md`).

**Sem estado, e de propósito.** Recebe a janela do DEM no pedido em vez
de a ler de um volume partilhado: no Railway *"each service can only have
a single volume"* e os volumes não se partilham entre serviços, portanto
o padrão do `docker-compose` local (`./data:/data:ro` nos três serviços)
não sobreviveria ao deploy. Uma janela de 15 km a ~37 m são 640 KB — nada
na rede privada. Em troca, este serviço não precisa de volume, nem de
credenciais R2, nem de descarregar 3.87 GB no arranque.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import rasterio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from rasterio.transform import Affine

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="fogos-triage WindNinja sidecar", version="0.1.0")

# Nome do binário e da pasta de dados do WindNinja dentro do container.
WINDNINJA_CLI = os.environ.get("WINDNINJA_CLI", "WindNinja_cli")
TIMEOUT_S = int(os.environ.get("WINDNINJA_TIMEOUT_S", "180"))


class PedidoVento(BaseModel):
    """Uma corrida domain-average sobre uma janela de terreno."""

    # DEM em linha. `elevacao` é uma matriz linha-maior de `altura`×`largura`
    # em metros; `nodata` marca as células sem dado.
    elevacao: list[list[float]]
    transform: list[float] = Field(
        ..., min_length=6, max_length=6,
        description="Affine (a, b, c, d, e, f) da janela, no CRS projectado",
    )
    epsg: int = Field(default=3763, description="CRS projectado da janela")
    nodata: float = -9999.0

    input_speed_ms: float = Field(..., ge=0.0, le=80.0)
    input_dir_deg: float = Field(..., ge=0.0, le=360.0)
    input_height_m: float = Field(default=10.0, gt=0.0)
    output_height_m: float = Field(default=10.0, gt=0.0)

    mesh: Literal["coarse", "medium", "fine"] = "fine"
    # Rugosidade do WindNinja. Não confundir com o WAF vegetativo do motor
    # de fogo: isto afecta o perfil do vento sobre o terreno, o WAF é
    # aplicado depois, por píxel, do lado da API.
    vegetation: Literal["grass", "brush", "trees"] = "grass"
    num_threads: int = Field(default=1, ge=1, le=8)


class RespostaVento(BaseModel):
    velocidade_ms: list[list[float]]
    direccao_deg: list[list[float]]     # de onde vem, convenção meteorológica
    transform: list[float]
    largura: int
    altura: int
    nodata: float
    segundos: float


def _le_saida(path: Path) -> tuple[np.ndarray, Affine]:
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype("float64")
        if ds.nodata is not None:
            arr[arr == ds.nodata] = np.nan
        return arr, ds.transform


@app.get("/health")
def health() -> dict:
    """Confirma que o binário existe e responde — o container pode estar
    de pé com o conda partido."""
    ok = shutil.which(WINDNINJA_CLI) is not None
    return {"status": "ok" if ok else "sem_windninja", "cli": WINDNINJA_CLI}


@app.post("/run", response_model=RespostaVento)
def run(pedido: PedidoVento) -> RespostaVento:
    dem = np.asarray(pedido.elevacao, dtype="float32")
    if dem.ndim != 2 or dem.size == 0:
        raise HTTPException(422, "elevacao tem de ser uma matriz 2D não vazia")

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="wn_") as tmp:
        tmpd = Path(tmp)
        dem_path = tmpd / "dem.tif"
        saida = tmpd / "out"
        saida.mkdir()

        perfil = {
            "driver": "GTiff", "height": dem.shape[0], "width": dem.shape[1],
            "count": 1, "dtype": "float32",
            "crs": f"EPSG:{pedido.epsg}",
            "transform": Affine(*pedido.transform),
            "nodata": pedido.nodata,
        }
        with rasterio.open(dem_path, "w", **perfil) as o:
            o.write(dem, 1)

        cmd = [
            WINDNINJA_CLI,
            "--num_threads", str(pedido.num_threads),
            "--elevation_file", str(dem_path),
            "--initialization_method", "domainAverageInitialization",
            "--input_speed", str(pedido.input_speed_ms),
            "--input_speed_units", "mps",
            "--input_direction", str(pedido.input_dir_deg),
            "--input_wind_height", str(pedido.input_height_m),
            "--units_input_wind_height", "m",
            "--output_wind_height", str(pedido.output_height_m),
            "--units_output_wind_height", "m",
            # NÃO REMOVER: o default de --output_speed_units é `mph`, mesmo
            # com a entrada em mps. Sem isto a saída vem 2.2369x maior e o
            # erro é silencioso — o campo continua plausível e o fogo
            # propaga ao dobro. Ver o teste test_unidades_mps_nao_mph.
            "--output_speed_units", "mps",
            "--vegetation", pedido.vegetation,
            "--mesh_choice", pedido.mesh,
            "--write_goog_output", "false",
            "--write_shapefile_output", "false",
            "--write_pdf_output", "false",
            "--write_ascii_output", "true",
            "--output_path", str(saida),
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"WindNinja excedeu {TIMEOUT_S}s")

        if proc.returncode != 0:
            cauda = (proc.stderr or proc.stdout or "")[-500:]
            log.warning("WindNinja rc=%s: %s", proc.returncode, cauda.replace("\n", " | "))
            raise HTTPException(502, f"WindNinja falhou (rc={proc.returncode}): {cauda}")

        vels = sorted(saida.glob("*_vel.asc"))
        angs = sorted(saida.glob("*_ang.asc"))
        if not vels or not angs:
            raise HTTPException(502, f"WindNinja não escreveu saída: {[p.name for p in saida.iterdir()]}")

        vel, tr_out = _le_saida(vels[0])
        ang, _ = _le_saida(angs[0])

    dt = time.time() - t0
    log.info(
        "campo %dx%d de %.1f m/s @ %.0f° (malha %s) em %.1fs — saída %.2f a %.2f m/s",
        vel.shape[1], vel.shape[0], pedido.input_speed_ms, pedido.input_dir_deg,
        pedido.mesh, dt, np.nanmin(vel), np.nanmax(vel),
    )

    # O .prj que o WindNinja escreve é lido pelo GDAL como EngineeringCRS e
    # rebenta qualquer reprojecção. Ignora-se: a saída está no CRS do DEM
    # que enviámos, e quem chama já o sabe.
    sub = lambda a: np.where(np.isnan(a), pedido.nodata, a).tolist()
    return RespostaVento(
        velocidade_ms=sub(vel), direccao_deg=sub(ang),
        transform=list(tr_out)[:6], largura=vel.shape[1], altura=vel.shape[0],
        nodata=pedido.nodata, segundos=round(dt, 2),
    )
