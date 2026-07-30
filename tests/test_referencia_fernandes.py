"""
Calibração do motor contra `modelos_PFernandes/MODELO_FOGO_REFERENCIA.md`.

É o único teste que compara o motor com uma fonte externa em vez de com
o seu próprio comportamento. A referência (Fernandes & Loureiro 2021) dá
valores esperados de ROS e intensidade para os 18 modelos portugueses num
cenário totalmente especificado (§7.3), e fixa a tolerância em 15% no ROS
(§7.1).

    python tests/test_referencia_fernandes.py

Histórico do que este teste apanhou, por ordem:

  situação                                   |erro| mediano   dentro de 15%
  ponto de partida                                    16%          6/18
  + factor 1.15 de 10 m para 20 pés                   10%         11/18
  + FM225/226/235 marcados dinâmicos                  10%         12/18
  + WAF de Albini & Baughman (era escada fixa)       0.1%         18/18
"""
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from fogos_triage.engine import _rothermel_direct  # noqa: E402
from fogos_triage.fuel_models import load_fuel_models_csv  # noqa: E402
from fogos_triage.waf import waf_albini_baughman, waf_sem_abrigo, waf_sob_copado  # noqa: E402
from fogos_triage.weather import WIND_10M_TO_20FT  # noqa: E402

CSV = RAIZ / "data" / "fuel_models_pt.csv"

# Tabela §7.3: cenário severo, 20 km/h a 10 m, declive 20%, shelter="open".
# codigo: (FMNum, ROS m/min, I_B kW/m)
REFERENCIA = {
    "V-MAa": (233, 22.86, 18895), "V-MMa": (236, 23.40, 11318),
    "M-EUC": (223, 19.83, 8962),  "M-PIN": (227, 14.30, 6155),
    "V-MAb": (234, 12.36, 5535),  "M-CAD": (221, 14.01, 4899),
    "M-ESC": (222, 10.94, 4057),  "V-MMb": (237, 14.17, 3864),
    "M-F":   (225, 17.10, 3283),  "V-MH":  (235, 13.48, 2368),
    "V-Ha":  (231, 35.08, 2293),  "F-EUC": (211,  6.80, 1470),
    "F-PIN": (213,  4.01,  790),  "V-Hb":  (232, 25.37,  603),
    "M-EUCd": (224, 4.49,  471),  "M-H":   (226,  4.03,  393),
    "F-FOL": (212,  2.66,  361),  "F-RAC": (214,  0.73,   55),
}
# Cenário `severo` (§6): humidades em percentagem
M_1H, M_10H, M_100H, M_HERB, M_LENH = 6.0, 7.0, 8.0, 30.0, 80.0
VENTO_10M_MS = 20.0 / 3.6
DECLIVE_DEG = math.degrees(math.atan(0.20))     # 20% de declive
TOLERANCIA_ROS = 0.15                            # §7.1

passou = falhou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def main():
    fm = load_fuel_models_csv(CSV)

    print("Fórmulas de WAF (referência §3.1 e §3.2):")
    # Valores calculados à mão a partir das fórmulas da referência.
    check("leito de 1 ft -> 0.3621", abs(waf_sem_abrigo(1.0) - 0.3621) < 5e-4,
          f"{waf_sem_abrigo(1.0):.4f}")
    check("leito mais fundo dá WAF maior",
          waf_sem_abrigo(5.0) > waf_sem_abrigo(0.2))
    check("copado abriga mais do que leito nu",
          waf_sob_copado(65.0, 0.70) < waf_sem_abrigo(1.0))
    check("mais cobertura abriga mais",
          waf_sob_copado(65.0, 0.80) < waf_sob_copado(65.0, 0.25))
    check("cobertura abaixo do limiar usa a fórmula do leito",
          waf_albini_baughman(1.0, altura_copado_m=20, cobertura_frac=0.10)
          == waf_sem_abrigo(1.0))
    check("sem copado usa a fórmula do leito",
          waf_albini_baughman(1.0) == waf_sem_abrigo(1.0))

    print("\nDomínio dos modelos PT — WAF sempre fisicamente plausível:")
    wafs = {n: waf_sem_abrigo(m.depth) for n, m in fm.items() if n != 98}
    check(f"todos entre 0.2 e 0.6 ({min(wafs.values()):.3f}–{max(wafs.values()):.3f})",
          all(0.2 < w < 0.6 for w in wafs.values()))
    check("folhada rasa (FM214) trava mais que mato alto (FM236)",
          wafs[214] < wafs[236], f"{wafs[214]:.3f} vs {wafs[236]:.3f}")

    print("\nModelos com herbácea viva têm de ser dinâmicos (referência §5.2:")
    print("  'Afeta sobretudo V-Ha, V-Hb, V-MH, M-H e M-F'):")
    for n in (231, 232, 235, 226, 225):
        m = fm[n]
        check(f"FM{n} tem carga herbácea e está dinâmico",
              m.load_live_h > 0 and m.is_dynamic,
              f"herb={m.load_live_h} dynamic={m.is_dynamic}")

    print(f"\nTabela §7.3 — cenário severo, 20 km/h a 10 m, declive 20%, 'open'")
    print(f"  (WAF calculado do leito; a referência corre os F e M com 'open'")
    print(f"   nesta tabela para comparabilidade, e di-lo expressamente)\n")
    print(f"  {'modelo':>7} {'ROS ref':>8} {'ROS':>7} {'erro':>6}   {'I_B ref':>8} {'I_B':>7} {'erro':>6}")
    erros = []
    for cod, (n, ros_ref, ib_ref) in sorted(
        REFERENCIA.items(), key=lambda kv: kv[1][1], reverse=True
    ):
        m = fm[n]
        midflame = VENTO_10M_MS * WIND_10M_TO_20FT * waf_sem_abrigo(m.depth)
        ros, ib, *_ = _rothermel_direct(
            m, M_1H / 100, M_10H / 100, M_100H / 100, M_HERB / 100, M_LENH / 100,
            wind_midflame_ms=midflame, slope_degrees=DECLIVE_DEG,
        )
        e_ros = ros / ros_ref - 1
        erros.append((cod, e_ros))
        print(f"  {cod:>7} {ros_ref:>8.2f} {ros:>7.2f} {100*e_ros:>+5.0f}%   "
              f"{ib_ref:>8.0f} {ib:>7.0f} {100*(ib/ib_ref-1):>+5.0f}%")

    print()
    fora = [f"{c} {100*e:+.0f}%" for c, e in erros if abs(e) > TOLERANCIA_ROS]
    check(f"os 18 modelos dentro da tolerância de {100*TOLERANCIA_ROS:.0f}% no ROS",
          not fora, "fora: " + ", ".join(fora))
    absolutos = sorted(abs(e) for _, e in erros)
    mediana = absolutos[len(absolutos) // 2]
    check(f"|erro| mediano abaixo de 5% (deu {100*mediana:.1f}%)", mediana < 0.05)

    print(f"\n{'='*56}\nRESULTADO: {passou} passados, {falhou} falhados\n{'='*56}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
