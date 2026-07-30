"""
WAF por píxel na simulação — `simulation.py`, `windfield.py`, `triage.py`.

Até aqui a simulação usava um WAF único de 0.40 para toda a paisagem,
enquanto a triagem já calculava o de Albini & Baughman por píxel. O mesmo
pinhal era triado com um vento e simulado com outro. Este teste fixa a
regra nova: **um píxel, um WAF**, quem quer que pergunte.

    python tests/test_waf_simulacao.py

O que este teste apanhou ao ser escrito:

  - `gust_weather` não propagava a rajada para `wind_20ft_ms`, e a
    simulação passou a ler esse campo. Com rajadas ligadas o fogo teria
    voltado ao vento sustentado — em silêncio.
  - o `windfield` mandava ao WindNinja o vento a 20 pés rotulado como
    sendo a 10 m, 15% acima. Entrou com o factor 1.15 (b04a203) e passou
    despercebido porque o erro simétrico na volta quase o cancelava.
"""
import asyncio
import math
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from rasterio.transform import Affine  # noqa: E402

from fogos_triage.fuel_models import load_fuel_models_csv  # noqa: E402
from fogos_triage.schemas import WeatherConditions  # noqa: E402
from fogos_triage.simulation import (  # noqa: E402
    _amostra_copado, _midflame_no_ponto, _ou_none,
    _vento_20ft_no_ponto, _vento_20ft_uniforme,
)
from fogos_triage.triage import gust_weather  # noqa: E402
from fogos_triage.waf import waf_sem_abrigo, waf_sob_copado  # noqa: E402
from fogos_triage.weather import (  # noqa: E402
    WAF_SEM_MODELO, WIND_10M_TO_20FT, derive_fire_weather,
)
from fogos_triage.windfield import WindField, WindFieldSet  # noqa: E402

CSV = RAIZ / "data" / "fuel_models_pt.csv"

passou = falhou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def wx_base(v10=6.0, rajada=11.0, direccao=225.0):
    return WeatherConditions(
        timestamp=datetime(2026, 7, 30, 15, tzinfo=timezone.utc),
        temperature_c=32.0, relative_humidity_pct=22.0,
        wind_speed_10m_ms=v10, wind_gust_10m_ms=rajada,
        wind_direction_deg=direccao, precipitation_mm_24h=0.0,
        cloud_cover_pct=10.0,
    )


def main():
    fm_todos = load_fuel_models_csv(CSV)
    mato = fm_todos[236]      # V-MMa, leito de 1.70 m — o WAF mais alto
    folhada = fm_todos[214]   # F-RAC, leito raso — o mais baixo
    pinhal = fm_todos[227]    # M-PIN, sub-coberto — leva a fórmula do copado

    print("gust_weather leva a rajada aos DOIS campos de vento de trabalho:")
    # A simulação lê `wind_20ft_ms`; se só o midflame subisse, ligar as
    # rajadas não teria efeito nenhum nos perímetros.
    base = derive_fire_weather(wx_base(), fuel_bed_depth_ft=mato.depth)
    raj = gust_weather(base)
    check(f"midflame sobe ({base.wind_midflame_ms:.2f} -> {raj.wind_midflame_ms:.2f})",
          raj.wind_midflame_ms > base.wind_midflame_ms)
    check(f"20 pés sobe ({base.wind_20ft_ms:.2f} -> {raj.wind_20ft_ms:.2f})",
          raj.wind_20ft_ms > base.wind_20ft_ms)
    check("20 pés da rajada = rajada de 10 m x 1.15",
          abs(raj.wind_20ft_ms - 11.0 * WIND_10M_TO_20FT) < 1e-9,
          f"{raj.wind_20ft_ms:.4f}")
    check("os dois sobem na mesma proporção (mesmo WAF)",
          abs((raj.wind_midflame_ms / base.wind_midflame_ms)
              - (raj.wind_20ft_ms / base.wind_20ft_ms)) < 1e-9)
    check("vento sustentado de 10 m fica intacto (é de exibição)",
          raj.wind_speed_10m_ms == 6.0)
    check("sem derive_fire_weather, 20 pés continua a None (não se inventa)",
          gust_weather(replace(wx_base(), wind_midflame_ms=2.0)).wind_20ft_ms is None)

    print("\n_vento_20ft_uniforme — de onde a simulação tira o vento:")
    check("lê wind_20ft_ms quando existe",
          abs(_vento_20ft_uniforme(base) - base.wind_20ft_ms) < 1e-12)
    # Meteo do fallback estático do routes_meta: sem 20 pés, só midflame.
    legado = replace(wx_base(), wind_midflame_ms=6.0 * WIND_10M_TO_20FT * WAF_SEM_MODELO)
    check("sem ele, desfaz o WAF por omissão e dá o mesmo (exacto)",
          abs(_vento_20ft_uniforme(legado) - 6.0 * WIND_10M_TO_20FT) < 1e-9,
          f"{_vento_20ft_uniforme(legado):.6f}")

    print("\n_midflame_no_ponto — o WAF passa a variar com o píxel:")
    v20 = 10.0
    mf_mato = _midflame_no_ponto(v20, mato, None, None)
    mf_folhada = _midflame_no_ponto(v20, folhada, None, None)
    check(f"mato alto apanha mais vento que folhada rasa "
          f"({mf_mato:.2f} vs {mf_folhada:.2f})", mf_mato > mf_folhada)
    check("mato alto = 20 pés x WAF do seu leito",
          abs(mf_mato - v20 * waf_sem_abrigo(mato.depth)) < 1e-12)
    razao = mf_mato / mf_folhada
    check(f"a dispersão que o 0.40 achatava é de {razao:.2f}x", razao > 1.8)

    mf_desc = _midflame_no_ponto(v20, pinhal, 0.0, 0.0)
    mf_cop = _midflame_no_ponto(v20, pinhal, 70.0, 18.0)
    check(f"copado denso abriga ({mf_cop:.2f} < {mf_desc:.2f})", mf_cop < mf_desc)
    check("sob copado = 20 pés x WAF do copado",
          abs(mf_cop - v20 * waf_sob_copado(18.0 / 0.3048, 0.70)) < 1e-12)
    # Não há limiar de cobertura: o mínimo das duas fórmulas é que decide,
    # e abaixo de ~8% a do leito ganha sozinha (ver waf.py).
    check("cobertura residual acaba no leito, sem degrau",
          _midflame_no_ponto(v20, pinhal, 3.0, 18.0) == mf_desc)
    check("cobertura de 15% já abriga",
          _midflame_no_ponto(v20, pinhal, 15.0, 18.0) < mf_desc)
    check("o abrigo nunca acelera o vento (armadilha do FARSITE)",
          all(_midflame_no_ponto(v20, pinhal, c, 30.0) <= mf_desc + 1e-12
              for c in (1.0, 5.0, 10.0, 20.0, 50.0, 90.0)))
    check("sem altura conhecida não abriga",
          _midflame_no_ponto(v20, pinhal, 70.0, None) == mf_desc)

    class _Vazio:
        depth = 0.0
    check("modelo sem espessura cai no WAF por omissão, não rebenta",
          abs(_midflame_no_ponto(v20, _Vazio(), None, None) - v20 * WAF_SEM_MODELO) < 1e-12)

    print("\nFM98 não combustível (depth=0) não pode rebentar a triagem:")
    # Regressão de produção: sem o guarda, o ValueError do waf_sem_abrigo
    # subia do derive_fire_weather até ao worker e matava a triagem
    # INTEIRA da ocorrência, não só a do píxel não combustível.
    fm98 = fm_todos[98]
    check(f"FM98 tem mesmo depth 0 (é o gatilho)", fm98.depth == 0.0)
    try:
        wx98 = derive_fire_weather(wx_base(), fuel_bed_depth_ft=fm98.depth)
        ok98 = abs(wx98.wind_midflame_ms
                   - wx98.wind_20ft_ms * WAF_SEM_MODELO) < 1e-12
    except Exception as exc:
        wx98, ok98 = None, False
        print(f"        rebentou: {exc}")
    check("derive_fire_weather com depth=0 devolve o WAF por omissão", ok98)
    check("e com copado também não rebenta",
          derive_fire_weather(wx_base(), stand_height_m=20.0, canopy_cover_pct=70.0,
                              has_overstory=True,
                              fuel_bed_depth_ft=0.0).wind_midflame_ms > 0)

    print("\nO MESMO PÍXEL tem de dar o mesmo vento na triagem e na simulação:")
    # É esta a regra que justifica a alteração toda. Antes, um pinhal com
    # copado era triado com WAF 0.17 e simulado com 0.40 — mais do dobro
    # do vento na simulação do que na triagem que lhe deu a prioridade.
    for nome, fm, cob, alt in (
        ("mato descoberto (FM236)", mato, 0.0, 0.0),
        ("pinhal com copado (FM227)", pinhal, 70.0, 18.0),
        ("folhada sob eucaliptal (FM214)", folhada, 45.0, 25.0),
    ):
        tem_copado = cob > 10.0
        wx_triagem = derive_fire_weather(
            wx_base(), stand_height_m=alt, canopy_cover_pct=cob,
            has_overstory=tem_copado, fuel_bed_depth_ft=fm.depth,
        )
        wx_sim = derive_fire_weather(wx_base())     # como as rotas chamam
        mf_sim = _midflame_no_ponto(_vento_20ft_uniforme(wx_sim), fm, cob, alt)
        check(f"{nome}: triagem {wx_triagem.wind_midflame_ms:.3f} == "
              f"simulação {mf_sim:.3f}",
              abs(wx_triagem.wind_midflame_ms - mf_sim) < 1e-9)
        antigo = wx_sim.wind_speed_10m_ms * WIND_10M_TO_20FT * WAF_SEM_MODELO
        print(f"          (o WAF fixo dava {antigo:.3f} — "
              f"{100 * (antigo / mf_sim - 1):+.0f}%)")

    print("\nCampo WindNinja: sai a 10 m, tem de subir a 20 pés:")
    campo = WindField(velocidade_ms=np.full((4, 4), 8.0, "float32"),
                      direccao_deg=np.full((4, 4), 315.0, "float32"),
                      transform=Affine(100.0, 0, 0, 0, -100.0, 400.0))
    conj = WindFieldSet(campos=(campo,))
    v, d = _vento_20ft_no_ponto(conj, 50.0, 350.0, 0, 99.0, 0.0)
    check(f"8 m/s a 10 m -> {v:.2f} a 20 pés", abs(v - 8.0 * WIND_10M_TO_20FT) < 1e-6)
    check("direcção vem do campo", d == 315.0)
    check("fora da grelha devolve o uniforme",
          _vento_20ft_no_ponto(conj, -500.0, 350.0, 0, 99.0, 42.0) == (99.0, 42.0))
    check("sem campo devolve o uniforme",
          _vento_20ft_no_ponto(None, 50.0, 350.0, 0, 99.0, 42.0) == (99.0, 42.0))

    print("\nwindfield manda ao sidecar o vento a 10 m, não o de 20 pés:")
    # Sem WindNinja_cli: intercepta-se o POST e lê-se o corpo. O teste de
    # integração (test_windfield.py) só corre com o binário instalado, e
    # foi por isso que os 15% a mais passaram despercebidos.
    import httpx

    from fogos_triage.windfield import fetch_wind_fields

    class ReaderFalso:
        crs = "EPSG:3763"

        def read_window(self, nomes, *a, **kw):
            return ({"elevation": np.full((8, 8), 300.0)}, {"elevation": None},
                    Affine(100.0, 0, 0.0, 0, -100.0, 800.0))

    enviados = []

    async def corre(wx_horas):
        async def handler(request):
            import json
            enviados.append(json.loads(request.content))
            return httpx.Response(200, json={
                "velocidade_ms": np.full((8, 8), 5.0).tolist(),
                "direccao_deg": np.full((8, 8), 225.0).tolist(),
                "transform": [100.0, 0, 0.0, 0, -100.0, 800.0],
                "nodata": -9999.0,
            })
        cli = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                base_url="http://sidecar")
        try:
            return await fetch_wind_fields("http://sidecar", ReaderFalso(),
                                           0.0, 0.0, 500.0, wx_horas, client=cli)
        finally:
            await cli.aclose()

    asyncio.run(corre([base]))
    enviado = enviados[0]["input_speed_ms"]
    check(f"vento sustentado: enviou {enviado:.3f} = os 6.0 de 10 m",
          abs(enviado - 6.0) < 1e-9)
    check("NÃO enviou os 20 pés (6.90) — era o erro dos 15%",
          abs(enviado - 6.0 * WIND_10M_TO_20FT) > 0.5)

    enviados.clear()
    asyncio.run(corre([raj]))
    check(f"com rajada: enviou {enviados[0]['input_speed_ms']:.3f} = os 11.0 de 10 m",
          abs(enviados[0]["input_speed_ms"] - 11.0) < 1e-9)

    enviados.clear()
    asyncio.run(corre([legado]))
    check(f"meteo sem 20 pés: recurso pelo midflame dá {enviados[0]['input_speed_ms']:.3f}",
          abs(enviados[0]["input_speed_ms"] - 6.0) < 1e-9)

    print("\n_amostra_copado — ausência de dado distingue-se de zero:")
    arrays = {"canopy_cover": np.array([[40.0, 0.0], [-9999.0, 55.0]]),
              "stand_height": np.array([[180.0, 0.0], [-9999.0, 220.0]])}
    nodata = {"canopy_cover": -9999.0, "stand_height": -9999.0}
    linhas = np.array([0, 0, 1, 1])
    colunas = np.array([0, 1, 0, 1])
    cob, alt = _amostra_copado(arrays, nodata, linhas, colunas)
    check("cobertura lida", cob[0] == 40.0)
    check("altura em decímetros -> metros", abs(alt[0] - 18.0) < 1e-9)
    check("cobertura 0% é um valor, não um buraco", cob[1] == 0.0 and _ou_none(cob[1]) == 0.0)
    check("nodata vira NaN -> None", math.isnan(cob[2]) and _ou_none(cob[2]) is None)
    sem_banda, _ = _amostra_copado({}, {}, linhas, colunas)
    check("banda ausente vira tudo None (não paisagem rasa)",
          all(_ou_none(v) is None for v in sem_banda))

    print(f"\n{'='*58}\nRESULTADO: {passou} passados, {falhou} falhados\n{'='*58}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
