"""
Classificação de severidade — Tedim et al. (2018).

Fonte: Tedim, F. et al. (2018). Defining Extreme Wildfire Events:
Difficulties, Challenges, and Impacts. Fire, 1(1), 9.
doi:10.3390/fire1010009 — Tabela 3 (p. 12).

Substitui o antigo score composto 0-100 sem fonte publicada
(anteriormente em triage.py, ver CLASSIFICACAO_TRIAGEM.md para a
comparação). A classificação usa a intensidade de linha de fogo (FLI)
como critério pivô — é o critério que a própria Tabela 3 usa para
definir capacidade de controlo — com ROS como segundo critério
independente para a definição estrita de "Extreme Wildfire Event"
(EWE). As classes 1-4 usam os limiares de Alexander & Lanoville (1989)
(citados em Tedim et al., nota da Tabela 3).

Módulo único de verdade: schemas.py, triage.py, routes_fires.py, e o
frontend (via services/api) devem todos importar/reflectir esta
tabela, em vez de repetir os limiares independentemente (era o que
acontecia com o antigo `tactic_category`, duplicado em 3 sítios).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeverityInfo:
    category: int
    ewe: bool
    fli_floor_kw_m: float          # limiar inferior de FLI desta categoria
    control_description: str       # "Capacidade de controlo", Tabela 3
    short_label: str               # rótulo compacto para badges


# Tedim et al. 2018, Tabela 3 — limiares de FLI (kW/m) que definem
# cada categoria (limiar inferior; a categoria seguinte começa onde
# esta acaba). Categorias 5-7 = EWE (Extreme Wildfire Event).
SEVERITY_TABLE: dict[int, SeverityInfo] = {
    1: SeverityInfo(1, False, 0,      "Bastante fácil",          "FÁCIL"),
    2: SeverityInfo(2, False, 500,    "Moderadamente difícil",   "MODERADO"),
    3: SeverityInfo(3, False, 2000,   "Muito difícil",           "DIFÍCIL"),
    4: SeverityInfo(4, False, 4000,   "Extremamente difícil",    "MUITO DIFÍCIL"),
    5: SeverityInfo(5, True,  10000,  "Virtualmente impossível", "EWE"),
    6: SeverityInfo(6, True,  30000,  "Impossível",              "EWE"),
    7: SeverityInfo(7, True,  100000, "Impossível",              "EWE"),
}

# Limiar estrito de ROS para a definição de EWE (Tedim et al. 2018,
# secção da definição de EWE) — independente do pivô de FLI usado na
# categorização: um fogo pode ser EWE por ROS mesmo com FLI abaixo de
# 10 000 kW/m (ex. combustível fino de propagação muito rápida).
EWE_ROS_THRESHOLD_M_MIN = 50.0

# Nota: a definição de EWE em Tedim et al. inclui também
# spotting > 1000 m — omitido aqui porque o motor não modela
# projecção de faúlhas (sem dados de distância de spotting).


def classify_severity(fli_kw_m: float) -> int:
    """Categoria 1-7 pela FLI (critério pivô de capacidade de controlo,
    Tedim et al. 2018, Tabela 3)."""
    category = 1
    for cat, info in SEVERITY_TABLE.items():
        if fli_kw_m >= info.fli_floor_kw_m:
            category = cat
    return category


def is_ewe(fli_kw_m: float, ros_m_min: float) -> bool:
    """True se o fogo cumpre a definição estrita de Extreme Wildfire
    Event (Tedim et al. 2018): FLI ≥ 10 000 kW/m OU ROS > 50 m/min.
    (Critério de spotting > 1000m omitido — não modelado.)
    """
    return fli_kw_m >= SEVERITY_TABLE[5].fli_floor_kw_m or ros_m_min > EWE_ROS_THRESHOLD_M_MIN


def severity_info(category: int) -> SeverityInfo:
    return SEVERITY_TABLE[category]
