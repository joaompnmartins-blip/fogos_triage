"""
Campo de vento ajustado ao relevo, vindo do sidecar WindNinja.

O motor usa hoje vento **espacialmente uniforme**: um único
`wind_midflame_ms` aplicado a todos os pontos. Este módulo é a alternativa
— um campo por hora simulada, amostrável por coordenada projectada.

Ver `WINDNINJA_PLAN.md` para a validação do modelo, o custo medido e as
armadilhas. Em resumo do que interessa a quem lê este ficheiro:

- É **um campo por hora**, não um por simulação: o padrão espacial depende
  da direcção de entrada, e nas simulações reais o vento roda 119° em
  mediana. Reutilizar o campo da hora 0 poria o abrigo no sítio errado.
- O modelo é *mass-consistent*: dá compressão sobre cumeadas, abrigo
  topográfico e canalização. **Não** dá esteira de sotavento — é linear,
  e inverter o vento 180° devolve exactamente a mesma velocidade.
- A velocidade que sai é a **10 m**, como a do Open-Meteo. Tem de passar
  pelo mesmo WAF vegetativo que o vento uniforme já passa; este módulo
  não o aplica.

Falha aberta em todo o lado: se o sidecar não responder, `fetch_wind_fields`
devolve `None` e o motor continua com vento uniforme.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

import numpy as np

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

log = logging.getLogger(__name__)

# Lado máximo da janela de DEM enviada ao sidecar. O WindNinja reamostra
# para a sua própria malha (a `fine` dá ~106 m num domínio de 15 km), por
# isso mandar mais do que isto é largura de banda desperdiçada; 400 dá
# ~37 m num domínio de 15 km, folgado. A 400x400 float32 são 640 KB.
DEM_MAX_DIM = 400

# Margem à volta da área de interesse, para o campo cobrir os vértices que
# saem do bbox durante a propagação. Mesmo espírito do
# _TERRAIN_CACHE_MARGIN_M do simulation.py, mas maior: o campo é calculado
# uma vez por hora e não se recarrega a meio.
MARGEM_M = 2000.0

TIMEOUT_S = 240.0


@dataclass(frozen=True)
class WindField:
    """Velocidade e direcção numa grelha regular, no CRS projectado.

    `transform` é um Affine no mesmo contrato de
    `LandscapeReader.read_window`, e o `sample` espelha
    `_lookup_cached_terrain` — inteiro por divisão, sem interpolação.
    Interpolar seria mais suave mas daria uma falsa sensação de precisão:
    a célula do WindNinja tem ~106 m e o campo dentro dela é uma média.
    """

    velocidade_ms: np.ndarray      # (altura, largura)
    direccao_deg: np.ndarray       # de onde vem, convenção meteorológica
    transform: "object"            # rasterio.Affine
    nodata: float = -9999.0

    def sample(self, x: float, y: float) -> Optional[tuple[float, float]]:
        """(velocidade m/s, direcção deg) no ponto, ou None fora da grelha
        ou em nodata. `None` significa "usa o vento uniforme aqui"."""
        t = self.transform
        # floor e não int: o int() de Python trunca em direcção a zero,
        # portanto um ponto a -10 m da origem daria col=0 em vez de ficar
        # fora da grelha, e a amostra vinha da célula errada em silêncio.
        col = math.floor((x - t.c) / t.a)
        row = math.floor((y - t.f) / t.e)
        h, w = self.velocidade_ms.shape
        if not (0 <= row < h and 0 <= col < w):
            return None
        v = float(self.velocidade_ms[row, col])
        d = float(self.direccao_deg[row, col])
        if v == self.nodata or d == self.nodata or np.isnan(v) or np.isnan(d):
            return None
        return v, d


@dataclass(frozen=True)
class WindFieldSet:
    """Um campo por hora simulada.

    Quem consome não precisa de saber quantas corridas houve nem como
    foram indexadas — pede pelo mesmo `hour_idx` que já usa para escolher
    a meteo, e o alinhamento fica garantido por construção.
    """

    campos: tuple[WindField, ...]

    def __len__(self) -> int:
        return len(self.campos)

    def sample(self, x: float, y: float, hour_idx: int) -> Optional[tuple[float, float]]:
        if not self.campos:
            return None
        # Mesma saturação do simulation.py quando a simulação passa da
        # última hora de meteo disponível.
        i = min(max(hour_idx, 0), len(self.campos) - 1)
        return self.campos[i].sample(x, y)


def _janela_dem(reader, cx: float, cy: float, meia_largura_m: float) -> Optional[dict]:
    """Recorta a banda de elevação à volta de um ponto, já decimada."""
    arrays, nodata, transform = reader.read_window(
        ["elevation"],
        cx - meia_largura_m, cy - meia_largura_m,
        cx + meia_largura_m, cy + meia_largura_m,
        max_dim=DEM_MAX_DIM,
    )
    dem = arrays.get("elevation")
    if dem is None or dem.size == 0:
        log.warning("Campo de vento: janela de elevação vazia em %.0f,%.0f", cx, cy)
        return None
    nd = nodata.get("elevation")
    dem = np.asarray(dem, dtype="float64")
    if nd is not None:
        dem = np.where(dem == nd, -9999.0, dem)
    return {"elevacao": dem.tolist(), "transform": list(transform)[:6]}


async def fetch_wind_fields(
    windninja_url: str,
    reader,
    cx: float,
    cy: float,
    meia_largura_m: float,
    weather_hourly: Sequence,
    epsg: int = 3763,
    mesh: str = "fine",
    client: Optional["httpx.AsyncClient"] = None,
) -> Optional[WindFieldSet]:
    """
    Um campo por hora de `weather_hourly`, do sidecar WindNinja.

    `reader` é um `LandscapeReader` já aberto; a janela do DEM vai no
    pedido porque no Railway os volumes não se partilham entre serviços
    (ver WINDNINJA_PLAN.md).

    O vento de cada hora tem de ser **o que a simulação vai usar** — se
    houver `use_gusts` ou cenário de humidades, esta função deve ser
    chamada depois de esses já terem alterado o `weather_hourly`.

    Devolve `None` em qualquer falha, incluindo falha a meio: um conjunto
    parcial daria metade das horas com relevo e metade sem, o que é pior
    do que nenhuma e muito mais difícil de diagnosticar.
    """
    if not HAS_HTTPX:
        log.warning("Campo de vento: httpx não instalado")
        return None
    if not windninja_url or not weather_hourly:
        return None

    janela = _janela_dem(reader, cx, cy, meia_largura_m + MARGEM_M)
    if janela is None:
        return None

    from rasterio.transform import Affine

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=TIMEOUT_S)
    campos: list[WindField] = []
    try:
        for i, wx in enumerate(weather_hourly):
            # O vento de entrada é o de 10 m, não o midflame: o WindNinja
            # trabalha à altura de referência e o WAF vegetativo é aplicado
            # depois, por píxel, do lado do motor.
            velocidade = getattr(wx, "wind_speed_10m_ms", None)
            direccao = getattr(wx, "wind_direction_deg", None)
            if velocidade is None or direccao is None:
                log.warning("Campo de vento: hora %d sem vento — desiste", i)
                return None
            corpo = {
                **janela, "epsg": epsg, "nodata": -9999.0,
                "input_speed_ms": float(velocidade),
                "input_dir_deg": float(direccao) % 360.0,
                "mesh": mesh,
            }
            try:
                resp = await client.post(f"{windninja_url.rstrip('/')}/run", json=corpo)
                resp.raise_for_status()
                d = resp.json()
            except Exception as exc:
                log.warning(
                    "Campo de vento: sidecar falhou na hora %d/%d (%s) — "
                    "simulação continua com vento uniforme",
                    i + 1, len(weather_hourly), exc,
                )
                return None

            campos.append(WindField(
                velocidade_ms=np.asarray(d["velocidade_ms"], dtype="float32"),
                direccao_deg=np.asarray(d["direccao_deg"], dtype="float32"),
                transform=Affine(*d["transform"]),
                nodata=float(d.get("nodata", -9999.0)),
            ))
    finally:
        if own:
            await client.aclose()

    v0 = campos[0].velocidade_ms
    log.info(
        "Campo de vento: %d corridas, grelha %dx%d, %.1f a %.1f m/s na hora 0",
        len(campos), v0.shape[1], v0.shape[0],
        float(np.nanmin(np.where(v0 == campos[0].nodata, np.nan, v0))),
        float(np.nanmax(np.where(v0 == campos[0].nodata, np.nan, v0))),
    )
    return WindFieldSet(campos=tuple(campos))
