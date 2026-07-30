"""
Campo de vento — `src/fogos_triage/windfield.py`.

Duas metades:

- **amostragem** (pura, sem rede) — corre sempre;
- **integração** contra o sidecar em processo — precisa do `WindNinja_cli`
  no PATH e do landscape file; salta sem eles.

    python tests/test_windfield.py
"""
import asyncio
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "services" / "windninja"))

from rasterio.transform import Affine  # noqa: E402

from fogos_triage.windfield import (  # noqa: E402
    DEM_MAX_DIM, WindField, WindFieldSet, fetch_wind_fields,
)

COG = RAIZ / "data" / "landscape_pt" / "Landscape_PT_2026_v2_cog.tif"
TEM_CLI = shutil.which("WindNinja_cli") is not None
TEM_COG = COG.exists()

passou = falhou = saltou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def salta(nome, porque):
    global saltou
    saltou += 1
    print(f"  [SKIP] {nome} — {porque}")


def campo_teste():
    """Grelha 10x10 de 100 m, canto superior esquerdo em (0, 1000).

    Velocidade cresce para leste, para se poder afirmar qual célula foi
    lida. Uma célula a nodata, para testar o buraco.
    """
    vel = np.tile(np.arange(10, dtype="float32"), (10, 1))
    dire = np.full((10, 10), 270.0, dtype="float32")
    vel[5, 5] = -9999.0
    return WindField(velocidade_ms=vel, direccao_deg=dire,
                     transform=Affine(100.0, 0.0, 0.0, 0.0, -100.0, 1000.0))


def main():
    print("WindField.sample:")
    c = campo_teste()
    check("centro da célula (0,0)", c.sample(50.0, 950.0) == (0.0, 270.0))
    check("célula (0,3) devolve 3.0", c.sample(350.0, 950.0)[0] == 3.0)
    check("linha de baixo", c.sample(750.0, 50.0)[0] == 7.0)
    check("fora à esquerda devolve None", c.sample(-10.0, 950.0) is None)
    check("fora em cima devolve None", c.sample(50.0, 1500.0) is None)
    check("fora à direita devolve None", c.sample(5000.0, 950.0) is None)
    check("nodata devolve None (não o -9999)", c.sample(550.0, 450.0) is None)

    print("\nWindFieldSet.sample — o índice é o mesmo hour_idx do motor:")
    a = WindField(np.full((4, 4), 1.0, "float32"), np.full((4, 4), 10.0, "float32"),
                  Affine(100.0, 0, 0, 0, -100.0, 400.0))
    b = WindField(np.full((4, 4), 2.0, "float32"), np.full((4, 4), 20.0, "float32"),
                  Affine(100.0, 0, 0, 0, -100.0, 400.0))
    s = WindFieldSet(campos=(a, b))
    check("len reflecte o nº de horas", len(s) == 2)
    check("hora 0 -> primeiro campo", s.sample(50.0, 350.0, 0) == (1.0, 10.0))
    check("hora 1 -> segundo campo", s.sample(50.0, 350.0, 1) == (2.0, 20.0))
    # O motor satura o hour_idx quando a simulação passa a última hora de
    # meteo (simulation.py:634 faz min(int(t/60), len-1)); o campo tem de
    # saturar igual, senão dessincroniza no fim das simulações longas.
    check("hora além do fim satura na última", s.sample(50.0, 350.0, 9) == (2.0, 20.0))
    check("hora negativa satura na primeira", s.sample(50.0, 350.0, -3) == (1.0, 10.0))
    check("conjunto vazio devolve None", WindFieldSet(campos=()).sample(0, 0, 0) is None)

    print("\nfalha aberta:")
    check("sem URL devolve None",
          asyncio.run(fetch_wind_fields("", None, 0, 0, 1000, [object()])) is None)
    check("sem horas devolve None",
          asyncio.run(fetch_wind_fields("http://x", None, 0, 0, 1000, [])) is None)

    # ---- integração ----
    print("\nintegração com o sidecar:")
    if not (TEM_CLI and TEM_COG):
        porque = "sem WindNinja_cli" if not TEM_CLI else f"sem {COG.name}"
        for n in ("um campo por hora", "cada hora usa o seu vento",
                  "campos horários diferem", "sidecar em baixo devolve None"):
            salta(n, porque)
    else:
        import httpx
        from main import app
        from fogos_triage.landscape import LandscapeReader
        from fogos_triage.schemas import WeatherConditions
        from rasterio.warp import transform as rio_transform

        def wx(v, d):
            return WeatherConditions(
                timestamp=datetime(2026, 7, 28, tzinfo=timezone.utc),
                temperature_c=30, relative_humidity_pct=25,
                wind_speed_10m_ms=v, wind_gust_10m_ms=v * 1.5,
                wind_direction_deg=d, precipitation_mm_24h=0, cloud_cover_pct=0)

        horas = [wx(4.3, 161.0), wx(3.3, 280.0)]
        # derive_fire_weather nao corre aqui, por isso o midflame vem do
        # WAF da simulacao aplicado a mao
        from dataclasses import replace as _replace
        horas = [_replace(h, wind_midflame_ms=h.wind_speed_10m_ms * 0.40) for h in horas]
        xs, ys = rio_transform("EPSG:4326", "EPSG:3763", [-8.15], [41.75])  # Gerês
        cx, cy = xs[0], ys[0]

        async def corre():
            cli = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://sidecar", timeout=300)
            try:
                with LandscapeReader(multiband_path=str(COG)) as r:
                    s = await fetch_wind_fields("http://sidecar", r, cx, cy, 7500.0,
                                                horas, mesh="coarse", client=cli)
                    mau = await fetch_wind_fields("http://127.0.0.1:1", r, cx, cy, 7500.0,
                                                  horas, mesh="coarse")
                return s, mau
            finally:
                await cli.aclose()

        conj, mau = asyncio.run(corre())
        check("devolveu um conjunto", conj is not None)
        if conj is not None:
            check(f"um campo por hora (deu {len(conj)})", len(conj) == len(horas))
            medias = []
            for c in conj.campos:
                v = np.where(c.velocidade_ms == c.nodata, np.nan, c.velocidade_ms)
                medias.append(float(np.nanmean(v)))
            # entrada 4.3 na hora 0 e 3.3 na hora 1: a média de saída tem
            # de acompanhar, senão as horas trocaram-se
            check(f"cada hora usa o seu vento ({medias[0]:.2f} > {medias[1]:.2f})",
                  medias[0] > medias[1])
            check("média perto da entrada, não 2.24x (mph)", medias[0] < 8.0, f"{medias[0]:.2f}")
            a0 = conj.campos[0].velocidade_ms
            a1 = conj.campos[1].velocidade_ms
            ok = (a0 != conj.campos[0].nodata) & (a1 != conj.campos[1].nodata)
            r_ = np.corrcoef(a0[ok], a1[ok])[0, 1]
            check(f"161° e 280° dão campos diferentes (r={r_:+.2f})", r_ < 0.95)
            check("amostra no centro dá valor", conj.sample(cx, cy, 0) is not None)
        check("sidecar em baixo devolve None (falha aberta)", mau is None)

        # --- rajadas: o campo tem de seguir o midflame, nao o vento de 10m ---
        # gust_weather altera SO o wind_midflame_ms e deixa o
        # wind_speed_10m_ms no valor sustentado. Ler o campo errado mandava
        # o vento sustentado ao WindNinja enquanto o motor propagava com a
        # rajada — apanhado em producao a 2026-07-30.
        from fogos_triage.triage import gust_weather
        base = _replace(wx(3.0, 225.0), wind_gust_10m_ms=9.0,
                        wind_midflame_ms=3.0 * 0.40)
        com_rajada = gust_weather(base)
        check(f"gust_weather mantem o vento de 10m ({com_rajada.wind_speed_10m_ms})",
              com_rajada.wind_speed_10m_ms == 3.0)
        check(f"gust_weather sobe o midflame ({com_rajada.wind_midflame_ms:.2f})",
              com_rajada.wind_midflame_ms > base.wind_midflame_ms)

        pedidos = []
        async def espia():
            cli = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://sidecar", timeout=300)
            orig = cli.post
            async def post(url, **kw):
                pedidos.append(kw.get("json", {}))
                return await orig(url, **kw)
            cli.post = post
            try:
                with LandscapeReader(multiband_path=str(COG)) as r:
                    return await fetch_wind_fields("http://sidecar", r, cx, cy, 7500.0,
                                                   [com_rajada], mesh="coarse",
                                                   client=cli, waf_simulacao=0.40)
            finally:
                await cli.aclose()
        asyncio.run(espia())
        enviado = pedidos[0]["input_speed_ms"] if pedidos else None
        esperado = com_rajada.wind_midflame_ms / 0.40
        check(f"WindNinja recebe a rajada ({enviado:.2f}), nao o sustentado (3.0)",
              enviado is not None and abs(enviado - esperado) < 1e-6 and enviado > 3.5,
              f"enviou {enviado}")

    print(f"\n{'='*52}\nRESULTADO: {passou} passados, {falhou} falhados, "
          f"{saltou} saltados\n{'='*52}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
