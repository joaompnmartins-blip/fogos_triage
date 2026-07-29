"""
Climatologia de humidade dos combustíveis vivos.

Cobre os pontos de verificação de LFMC_CLIMATOLOGIA_PLAN.md que não
precisam de rede nem de Postgres.

    python tests/test_lfmc_climatologia.py
"""
import csv
import datetime as dt
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from fogos_triage.lfmc_climatologia import (  # noqa: E402
    carrega_curvas, descreve, lfmc_climatologia,
)

passou = falhou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def cura(lfmc_pct):
    """Fracção curada de Andrews 2018 (GTR-371 Tabela 7)."""
    return max(0.0, min(1.0, -1.11 * (lfmc_pct / 100.0) + 1.33))


def dj(mes, dia=15):
    return dt.date(2021, mes, dia).timetuple().tm_yday


def main():
    curvas = carrega_curvas()
    P180_TIP = 457.0   # mediana de Verão nos sítios de amostragem

    print("CSV e proveniência:")
    check("as duas curvas existem", set(curvas) == {"herbaceo", "lenhoso"})
    check("herbáceo com n e RMSE gravados",
          curvas["herbaceo"].n > 100 and curvas["herbaceo"].rmse_cv_pp > 0)
    check("lenhoso com n e RMSE gravados",
          curvas["lenhoso"].n > 500 and curvas["lenhoso"].rmse_cv_pp > 0)
    check("RMSE do herbáceo muito abaixo dos 121.8pp do VIIRS",
          curvas["herbaceo"].rmse_cv_pp < 50, f"{curvas['herbaceo'].rmse_cv_pp}")
    check("descreve() não rebenta", "herbaceo" in descreve())

    print("\nDomínio — nunca extrapolar a harmónica (o bug de -354% em Janeiro):")
    for mes in (1, 2, 3, 11, 12):
        h, w = lfmc_climatologia(dj(mes), P180_TIP)
        check(f"mês {mes:>2}: herbáceo fora da janela é positivo e verde",
              h > 100.0, f"deu {h:.1f}%")
    todos_meses = [lfmc_climatologia(dj(m), P180_TIP) for m in range(1, 13)]
    check("nenhum valor negativo em nenhum mês",
          all(h > 0 and w > 0 for h, w in todos_meses))
    check("nenhum valor acima do observado em campo",
          all(h <= curvas["herbaceo"].lfmc_max_observado
              and w <= curvas["lenhoso"].lfmc_max_observado for h, w in todos_meses))

    print("\nJulho/Agosto contra o campo (herb ~45/37%, lenh ~96/87%):")
    h7, w7 = lfmc_climatologia(dj(7), P180_TIP)
    h8, w8 = lfmc_climatologia(dj(8), P180_TIP)
    check(f"herbáceo Julho na gama 35-60% (deu {h7:.1f})", 35 <= h7 <= 60)
    check(f"herbáceo Agosto na gama 25-50% (deu {h8:.1f})", 25 <= h8 <= 50)
    check(f"lenhoso Julho na gama 85-110% (deu {w7:.1f})", 85 <= w7 <= 110)
    check(f"lenhoso Agosto na gama 78-100% (deu {w8:.1f})", 78 <= w8 <= 100)
    check("herbáceo seca de Julho para Agosto", h8 < h7)

    print("\nEfeito na cura — é isto que estava quebrado:")
    check(f"Agosto tira a herbácea da saturação em 0% (cura {100*cura(h8):.0f}%)",
          cura(h8) > 0.6)
    check("o valor que o VIIRS dava (138.6%) saturava em 0%", cura(138.6) == 0.0)
    check("Janeiro continua a saturar em 0% (herbácea verde)",
          cura(lfmc_climatologia(dj(1), P180_TIP)[0]) == 0.0)

    print("\nMonotonia no P180 — mais chuva, mais húmido:")
    serie = [lfmc_climatologia(dj(8), p) for p in (150, 300, 500, 800, 1200)]
    check("herbáceo cresce com o P180",
          all(a[0] <= b[0] for a, b in zip(serie, serie[1:])))
    check("lenhoso cresce com o P180",
          all(a[1] <= b[1] for a, b in zip(serie, serie[1:])))

    print("\nP180 fora do domínio do ajuste é limitado, não extrapolado:")
    c = curvas["lenhoso"]
    _, w_abaixo = lfmc_climatologia(dj(8), 0.0)
    _, w_min = lfmc_climatologia(dj(8), c.p180_min)
    _, w_acima = lfmc_climatologia(dj(8), 99999.0)
    _, w_max = lfmc_climatologia(dj(8), c.p180_max)
    check("P180=0 dá o mesmo que P180 mínimo do ajuste", abs(w_abaixo - w_min) < 1e-9)
    check("P180 enorme dá o mesmo que P180 máximo do ajuste", abs(w_acima - w_max) < 1e-9)

    print("\nGradiente norte-sul (mesma data, P180 real de cada sítio):")
    # Caminha 788mm vs Mértola 233mm, medidos a 2026-07-29
    h_n, _ = lfmc_climatologia(dj(8), 788.0)
    h_s, _ = lfmc_climatologia(dj(8), 233.0)
    check(f"litoral norte mais húmido que Alentejo ({h_n:.0f}% vs {h_s:.0f}%)", h_n > h_s)
    check("Alentejo satura a cura em 100%", cura(h_s) == 1.0)

    print("\nRegressão do CSV face ao que o plano documenta:")
    with (RAIZ / "data" / "lfmc_climatologia_pt.csv").open(encoding="utf-8") as f:
        linhas = {r["escalar"]: r for r in csv.DictReader(f)}
    check("herbáceo: janela começa em Maio (DJ 122)", linhas["herbaceo"]["dj_min"] == "122")
    check("herbáceo: janela acaba no último dado (DJ 272)", linhas["herbaceo"]["dj_max"] == "272")
    check("herbáceo: grupo é só Herbáceas", linhas["herbaceo"]["grupos"] == "Herbáceas")
    check("lenhoso: só matos, sem pinhais nem giestais",
          linhas["lenhoso"]["grupos"] == "Matos atlânticos|Matos mediterrânicos")

    print(f"\n{'='*44}\nRESULTADO: {passou} passados, {falhou} falhados\n{'='*44}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
