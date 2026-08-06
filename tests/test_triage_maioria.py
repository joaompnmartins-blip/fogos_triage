"""
Escolha do combustível na triagem — maioria simples, não mediana do ROS.

    python tests/test_triage_maioria.py

O combustível passou a ser escolhido por maioria sobre a vizinhança
INTEIRA, não combustíveis incluídos, e tudo o resto é calculado para esse
modelo. Antes escolhia-se o píxel de ROS mediano entre os que ardiam.

Porquê: a mediana protegia contra o píxel excepcional, mas não contra a
filtragem que a precedia. Numa ocorrência real em Paranhos (Porto,
20261107430), 69 dos 81 píxeis eram urbanos, eram descartados antes da
mediana, e a categoria 4 saía de 12 píxeis de mato disperso.

O reverso — e é o que este teste guarda com mais cuidado — é que uma
vizinhança maioritariamente não combustível deixa a ocorrência sem
previsão de fogo. Isso é aceitável desde que a nota diga porquê; não é
aceitável em silêncio. Sub-triar é o erro perigoso neste sistema.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from fogos_triage.fuel_models import load_fuel_models_csv  # noqa: E402
from fogos_triage.schemas import (  # noqa: E402
    Occurrence, TerrainConditions, WeatherConditions,
)
from fogos_triage.triage import triage_neighbourhood  # noqa: E402

CSV = RAIZ / "data" / "fuel_models_pt.csv"

passou = falhou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def px(num, slope=15.0, cobertura=0.0, altura=0.0):
    return TerrainConditions(
        elevation_m=300.0, slope_fraction=0.27, slope_degrees=slope,
        aspect_degrees=180.0, fuel_model_num=num,
        stand_height_m=altura, canopy_cover_pct=cobertura,
        canopy_base_height_m=0.0, canopy_bulk_density_kg_m3=0.0,
    )


WX = WeatherConditions(
    timestamp=datetime(2026, 8, 6, 15, tzinfo=timezone.utc),
    temperature_c=30.0, relative_humidity_pct=30.0,
    wind_speed_10m_ms=6.0, wind_gust_10m_ms=11.0,
    wind_direction_deg=225.0, precipitation_mm_24h=0.0, cloud_cover_pct=10.0,
)
OCC = Occurrence(
    external_id="TESTE", latitude=41.75, longitude=-8.15,
    started_at=datetime(2026, 8, 6, 14, tzinfo=timezone.utc),
    status="Em Curso", district="Viana do Castelo",
    municipality="Ponte de Lima", parish="X",
)


def triar(terrenos, fms):
    return triage_neighbourhood(OCC, fms, terrenos, WX, 60.0, 90.0)


def notas_texto(res):
    return " | ".join(res.notes)


def main():
    fms = load_fuel_models_csv(CSV)

    print("A maioria decide o combustível, não o ROS mediano:")
    # 7 px de mato baixo (arde pouco) contra 3 de herbáceas altas (arde
    # muito). A regra antiga daria o mediano por ROS; a nova dá o que
    # ocupa mais área.
    r = triar([px(234)] * 7 + [px(231)] * 3, fms)
    check(f"maioria FM234 ganha aos 3 px de FM231 (deu {r.fuel_model_used})",
          r.fuel_model_used == "FM234")
    check("a nota diz a contagem", "7/10 px" in notas_texto(r), notas_texto(r))

    r = triar([px(231)] * 6 + [px(234)] * 4, fms)
    check(f"invertendo as contagens, ganha o FM231 (deu {r.fuel_model_used})",
          r.fuel_model_used == "FM231")

    print("\nOs não combustíveis contam para a maioria (foi a decisão):")
    # O caso de Paranhos, reduzido: urbano em maioria, mato à volta.
    r = triar([px(91)] * 69 + [px(233)] * 9 + [px(232)] * 2 + [px(234)], fms)
    check(f"dominante não combustível -> FM98 (deu {r.fuel_model_used})",
          r.fuel_model_used == "FM98")
    check("sem previsão de fogo", r.predictions[0].ros_m_per_min == 0.0)
    check(f"categoria 1 (deu {r.priority})", str(r.priority) in ("1", "SeverityCategory.CAT_1"),
          str(r.priority))

    print("\n  ...mas NUNCA em silêncio — é a parte que protege o operador:")
    txt = notas_texto(r)
    check("a nota diz que o dominante não arde", "NÃO COMBUSTÍVEL" in txt, txt)
    check("a nota quantifica o combustível que ficou de fora",
          "12/81 px combustíveis" in txt, txt)
    check("a nota nomeia o maior combustível à volta", "FM233" in txt, txt)
    check("a nota expõe o código do raster (91=urbano, não 93=regadio)",
          "raster: 91" in txt, txt)

    r_agri = triar([px(93)] * 60 + [px(233)] * 21, fms)
    check("regadio dominante distingue-se do urbano na nota",
          "raster: 93" in notas_texto(r_agri), notas_texto(r_agri))

    print("\nCom vizinhança toda combustível, nada de estranho acontece:")
    r = triar([px(233)] * 81, fms)
    check("modelo é o único presente", r.fuel_model_used == "FM233")
    check("arde", r.predictions[0].ros_m_per_min > 0)
    check("não há nota de não combustível", "NÃO COMBUSTÍVEL" not in notas_texto(r))
    check("nem nota de fracção parcial", "px combustíveis" not in notas_texto(r),
          notas_texto(r))

    print("\nO terreno vem do píxel mediano DENTRO do modelo dominante:")
    # Declives muito diferentes no mesmo modelo: o escolhido tem de ser
    # o do meio, não o extremo.
    terrenos = [px(233, slope=s) for s in (0.0, 5.0, 15.0, 30.0, 45.0)]
    r = triar(terrenos, fms)
    check(f"declive mediano, não o máximo (deu {r.terrain.slope_degrees:.0f}°)",
          r.terrain.slope_degrees == 15.0)
    check("o de 45° existia e não foi escolhido",
          any(t.slope_degrees == 45.0 for t in terrenos))

    print("\nCasos-limite:")
    check("vizinhança vazia não rebenta", triar([], fms) is not None)
    r98 = triar([px(98)] * 5, fms)
    check("tudo não combustível não rebenta (era o bug do FM98)",
          r98 is not None and r98.predictions[0].ros_m_per_min == 0.0)
    r1 = triar([px(233)], fms)
    check("um único píxel funciona", r1.fuel_model_used == "FM233")

    print("\nEmpate: a contagem é determinística, não aleatória:")
    a = triar([px(233)] * 5 + [px(234)] * 5, fms).fuel_model_used
    b = triar([px(233)] * 5 + [px(234)] * 5, fms).fuel_model_used
    check(f"duas corridas dão o mesmo ({a})", a == b)

    print(f"\n{'='*56}\nRESULTADO: {passou} passados, {falhou} falhados\n{'='*56}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
