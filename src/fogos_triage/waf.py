"""
WAF — wind adjustment factor (Albini & Baughman 1979).

Converte o vento à altura de referência no vento que a chama sente. É,
segundo `modelos_PFernandes/MODELO_FOGO_REFERENCIA.md` §11, *"a maior
fonte de erro operacional depois da seleção do modelo de combustível"*.

Cadeia completa (referência §3):

    U(10 m)  ->  U(20 ft) = U(10 m) x 1.15  ->  U_midflame = U(20 ft) x WAF

Os dois passos importam. O WAF está definido sobre o vento a **20 pés**
(6.1 m, altura de referência do NFDRS) e a meteorologia dá 10 m; sem o
1.15 o vento midflame sai 13% abaixo em tudo.

Substituiu uma escada de `if` com quatro degraus fixos (0.10/0.25/0.40/
0.50). Medido contra os 18 modelos da tabela §7.3 da referência, cenário
severo, 20 km/h a 10 m, declive 20%:

    escada de degraus  |erro| mediano 10.3%   dentro de 15%:  12/18
    Albini & Baughman  |erro| mediano  0.1%   dentro de 15%:  18/18

O que a escada errava não era a média — era a dispersão. Leitos rasos
(folhada de 5-15 cm: F-RAC, F-PIN, F-FOL, M-H) levavam vento a mais,
+28% a +54% no ROS; matos altos (V-MMa a 1.70 m, V-MAa a 1.05 m) levavam
vento a menos, -23% e -16%.
"""
from __future__ import annotations

import math
from typing import Optional

# Altura de referência do NFDRS, em pés — a altura sobre a qual o WAF de
# Albini & Baughman está definido.
ALTURA_REFERENCIA_FT = 20.0

M_TO_FT = 1 / 0.3048

# Abaixo desta cobertura de copas o copado não abriga de forma
# significativa e usa-se a fórmula do leito. A referência (§3.3) associa
# `forest_open` a "copado aberto, povoamento esparso"; 20% é o limiar que
# a escada anterior já usava para distinguir "com coberto" de "sem".
COBERTURA_MINIMA_FRAC = 0.20

# Razão de copa (comprimento de copa viva / altura total) assumida quando
# não é conhecida. NÃO existe nos nossos dados — nem no raster nem nos
# modelos de combustível — e a fórmula do copado precisa dela. 0.5 é o
# valor médio típico de povoamento gerido; convém confirmar com fonte de
# domínio antes de tratar os resultados abrigados como definitivos.
RAZAO_COPA_ASSUMIDA = 0.5

# Limites físicos. O WAF é uma fracção do vento a 20 pés: valores acima de
# 1 significariam que a chama sente mais vento do que existe a 6 m, e
# valores muito baixos matam qualquer propagação. Serve de rede contra
# entradas absurdas (leito de 1 mm, copado de 200 m).
WAF_MIN, WAF_MAX = 0.05, 1.0


def waf_sem_abrigo(espessura_leito_ft: float) -> float:
    """WAF para combustível não abrigado (Albini & Baughman 1979).

        WAF = 1.83 / ln[(20 + 0.36*h) / (0.13*h)]

    `h` é a espessura do leito de combustível em pés — o `depth` que os
    modelos de combustível já trazem. Quanto mais fundo o leito, mais
    perto da chama passa o vento de referência, logo maior o WAF: 0.27
    para folhada de 5 cm, 0.54 para mato de 1.70 m.
    """
    if espessura_leito_ft <= 0:
        raise ValueError("espessura do leito tem de ser positiva")
    h = espessura_leito_ft
    return min(max(1.83 / math.log((20.0 + 0.36 * h) / (0.13 * h)), WAF_MIN), WAF_MAX)


def waf_sob_copado(
    altura_copado_ft: float,
    cobertura_frac: float,
    razao_copa: float = RAZAO_COPA_ASSUMIDA,
) -> float:
    """WAF para combustível abrigado sob copado (referência §3.2).

        WAF = 0.555 / [sqrt(f*H) * ln((20 + 0.36*H)/(0.13*H))]
        f   = min(cobertura * razao_copa / 3, 0.33)

    `H` é a altura do copado em pés. Ao contrário da fórmula do leito,
    esta ignora a espessura do combustível de superfície: o que trava o
    vento é a copa, não o leito.
    """
    if altura_copado_ft <= 0:
        raise ValueError("altura do copado tem de ser positiva")
    if not (0.0 <= cobertura_frac <= 1.0):
        raise ValueError("cobertura tem de estar entre 0 e 1")
    H = altura_copado_ft
    f = min(cobertura_frac * razao_copa / 3.0, 0.33)
    if f <= 0:
        raise ValueError("fracção de copa resultante é nula")
    waf = 0.555 / (math.sqrt(f * H) * math.log((20.0 + 0.36 * H) / (0.13 * H)))
    return min(max(waf, WAF_MIN), WAF_MAX)


def waf_albini_baughman(
    espessura_leito_ft: float,
    altura_copado_m: Optional[float] = None,
    cobertura_frac: Optional[float] = None,
    razao_copa: float = RAZAO_COPA_ASSUMIDA,
    cobertura_minima: float = COBERTURA_MINIMA_FRAC,
) -> float:
    """WAF, escolhendo a fórmula conforme haja ou não copado a abrigar.

    Sem copado — ou com cobertura abaixo de `cobertura_minima`, ou sem
    altura conhecida — usa a fórmula do leito. Com copado, a do copado.

    **Qual usar não é uma escolha livre**: os modelos F (folhada) e M
    (folhada com sub-bosque) são de sub-coberto e em uso real devem levar
    a fórmula do copado; os V (mato ou herbáceas sem coberto arbóreo)
    levam a do leito. A tabela §7.3 da referência corre os F e M com a do
    leito **só para comparabilidade**, e diz-o expressamente — é por isso
    que o teste de regressão a força, e não é isso que o terreno pede.
    """
    tem_copado = (
        altura_copado_m is not None
        and altura_copado_m > 0
        and cobertura_frac is not None
        and cobertura_frac >= cobertura_minima
    )
    if tem_copado:
        return waf_sob_copado(altura_copado_m * M_TO_FT, cobertura_frac, razao_copa)
    return waf_sem_abrigo(espessura_leito_ft)
