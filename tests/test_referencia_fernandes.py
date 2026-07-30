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

**O que esta tabela já NÃO valida.** Desde que a conversão de 10 m para
20 pés passou a seguir o RMRS-GTR-266 (divisão por 1.15, contra a
multiplicação do §3 da referência), a cadeia completa deixou de ser
comparável: a tabela foi gerada com a convenção contrária. A tabela é
por isso alimentada com o vento a 20 pés que a referência usou, o que a
mantém a validar o Rothermel e as fórmulas de WAF — e deixa o passo em
disputa a ser verificado num bloco próprio, contra o RMRS e contra o
perfil logarítmico.
"""
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from fogos_triage.engine import _rothermel_direct  # noqa: E402
from fogos_triage.fuel_models import load_fuel_models_csv  # noqa: E402
from fogos_triage.waf import (  # noqa: E402
    COBERTURA_MINIMA_FRAC, waf_albini_baughman, waf_sem_abrigo, waf_sob_copado,
)
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

# Vento a 20 pés que a REFERÊNCIA usou para gerar a tabela §7.3, fixado
# aqui em vez de recalculado a partir dos 20 km/h.
#
# Não é conveniência: desde que passámos à convenção do RMRS-GTR-266
# (`U20 = U10m / 1.15`, ver weather.py), a nossa cadeia já não reproduz o
# vento de que a tabela partiu — a referência multiplicava. Alimentar o
# motor com os 20 km/h daria 0/18 com desvio uniforme de -28%, e isso
# diria apenas que as duas convenções diferem, coisa que já sabemos.
#
# Fixando o vento de 20 pés da referência, a tabela continua a fazer o
# que sabe fazer: validar o Rothermel e as fórmulas de WAF. O passo em
# disputa fica isolado e é verificado à parte, mais abaixo.
VENTO_20FT_REFERENCIA_MS = 20.0 * 1.15 / 3.6

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
    # Já não há limiar de cobertura: com o mínimo das duas fórmulas, é o
    # cruzamento das curvas que decide, e para um copado de 20 m dá-se
    # por volta dos 8% de cobertura.
    check("cobertura residual (3%) acaba na fórmula do leito",
          waf_albini_baughman(1.0, altura_copado_m=20, cobertura_frac=0.03)
          == waf_sem_abrigo(1.0))
    check("cobertura de 15% já abriga (antes era ignorada até aos 20%)",
          waf_albini_baughman(1.0, altura_copado_m=20, cobertura_frac=0.15)
          < waf_sem_abrigo(1.0))
    check("sem copado usa a fórmula do leito",
          waf_albini_baughman(1.0) == waf_sem_abrigo(1.0))

    print("\nPontos de validação do RMRS-GTR-266 §10 (Andrews 2012, USDA FS):")
    # A fonte primária do WAF, com valores publicados. A referência do
    # projecto (Fernandes) usa as mesmas duas fórmulas; estes números
    # confirmam-nas contra quem as documenta.
    for h, esperado in ((1.0, 0.362), (0.2, 0.275), (6.0, 0.547), (1.5, 0.393)):
        check(f"leito de {h} ft -> {esperado}",
              abs(waf_sem_abrigo(h) - esperado) < 5e-4, f"{waf_sem_abrigo(h):.4f}")
    # Tabela do §10: FM2, CC 40%, CH 50 ft, três razões de copa.
    for cr, esperado in ((0.5, 0.17), (0.7, 0.15), (0.9, 0.13)):
        check(f"copado CC40% CH50ft CR{cr} -> {esperado}",
              abs(waf_sob_copado(50.0, 0.40, cr) - esperado) < 5e-3,
              f"{waf_sob_copado(50.0, 0.40, cr):.4f}")
    for cc, esperado in ((0.60, 0.18), (0.80, 0.16), (1.00, 0.14)):
        check(f"copado CC{cc:.0%} CH50ft CR0.3 -> {esperado}",
              abs(waf_sob_copado(50.0, cc, 0.3) - esperado) < 5e-3,
              f"{waf_sob_copado(50.0, cc, 0.3):.4f}")

    print("\nArmadilha do FARSITE (§4) — o abrigo nunca pode acelerar o vento:")
    # Cobertura baixa com copado alto faz a fórmula abrigada passar acima
    # da do leito. O relatório manda guardar contra isto; a regra do
    # FuelCalc (mínimo dos dois) fá-lo e ainda tira o degrau no limiar.
    check("a fórmula crua sobe acima de 0.7 com 1% de cobertura (é o bug)",
          waf_sob_copado(100.0, 0.01) > 0.7, f"{waf_sob_copado(100.0, 0.01):.3f}")
    for cc in (0.20, 0.25, 0.35, 0.60, 0.90):
        w = waf_albini_baughman(1.0, altura_copado_m=30.0, cobertura_frac=cc)
        check(f"CC {cc:.0%} sob copado de 30 m nunca excede o leito",
              w <= waf_sem_abrigo(1.0) + 1e-12, f"{w:.3f} vs {waf_sem_abrigo(1.0):.3f}")
    # Sem degrau: atravessar o limiar não pode dar um salto no WAF.
    salto = abs(waf_albini_baughman(1.0, altura_copado_m=20.0,
                                    cobertura_frac=COBERTURA_MINIMA_FRAC)
                - waf_albini_baughman(1.0, altura_copado_m=20.0,
                                      cobertura_frac=COBERTURA_MINIMA_FRAC - 1e-9))
    check(f"limiar deixou de ser um degrau (salto {salto:.4f})", salto < 1e-6)

    print("\nConversão 10 m -> 20 pés: seguimos o RMRS, não a referência PT.")
    # É o único ponto em que divergimos deliberadamente do
    # MODELO_FOGO_REFERENCIA.md. A tabela §7.3 não o pode arbitrar, por
    # ter sido gerada com a convenção contrária — daí este bloco.
    v20 = VENTO_10M_MS * WIND_10M_TO_20FT
    check(f"20 pés fica ABAIXO dos 10 m ({v20:.2f} < {VENTO_10M_MS:.2f} m/s)",
          v20 < VENTO_10M_MS)
    check("é divisão por 1.15 (RMRS §1, Turner & Lawson 1978)",
          abs(v20 - VENTO_10M_MS / 1.15) < 1e-12)
    check("difere da referência PT por 1.15² = 1.3225",
          abs(VENTO_20FT_REFERENCIA_MS / v20 - 1.15 ** 2) < 1e-12,
          f"{VENTO_20FT_REFERENCIA_MS / v20:.4f}")
    # Sanidade física: o perfil logarítmico tem de dar o mesmo sentido, e
    # o 1.15 tem de corresponder a uma rugosidade plausível.
    z0 = 0.23
    razao_log = math.log(10.0 / z0) / math.log(6.096 / z0)
    check(f"perfil logarítmico com z0={z0} m confirma o 1.15 "
          f"(dá {razao_log:.3f})", abs(razao_log - 1.15) < 0.01)

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

    print(f"\nTabela §7.3 — cenário severo, declive 20%, 'open'")
    print(f"  Alimentada com os {VENTO_20FT_REFERENCIA_MS:.2f} m/s a 20 pés que a")
    print(f"  referência usou, e não com os nossos 20 km/h a 10 m: a nossa")
    print(f"  conversão segue o RMRS e daria outro vento (ver bloco acima).")
    print(f"  Assim a tabela valida o Rothermel e o WAF, que é o que pode.\n")
    print(f"  {'modelo':>7} {'ROS ref':>8} {'ROS':>7} {'erro':>6}   {'I_B ref':>8} {'I_B':>7} {'erro':>6}")
    erros = []
    for cod, (n, ros_ref, ib_ref) in sorted(
        REFERENCIA.items(), key=lambda kv: kv[1][1], reverse=True
    ):
        m = fm[n]
        midflame = VENTO_20FT_REFERENCIA_MS * waf_sem_abrigo(m.depth)
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
