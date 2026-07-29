"""
Humidade dos combustíveis vivos (LFMC) por climatologia sazonal +
precipitação acumulada.

Substitui a estimativa por satélite (VIIRS + Yebra 2007), que foi
validada contra 654 medições de campo do ICNF e reprovou: no herbáceo
dava viés de +110 pontos percentuais e **correlação zero** (r = −0.03)
com o que está no terreno. Detalhe e o que mais foi testado e rejeitado
em `LFMC_CLIMATOLOGIA_PLAN.md`.

    LFMC = a0 + a1·cos(θ) + a2·sin(θ) + a3·cos(2θ) + a4·sin(2θ) + β·P180
    θ = 2π · dia_do_ano / 365
    P180 = precipitação acumulada nos 180 dias anteriores, mm

Coeficientes em `data/lfmc_climatologia_pt.csv`, ajustados por
`scripts/ajusta_lfmc_climatologia.py`. O CSV é a fonte de verdade e traz
a proveniência de cada curva (n, RMSE em validação cruzada, domínio) —
está feito para ser aberto e criticado, como o `fuel_models_pt.csv`.

Módulo puro: sem HTTP, sem I/O além de ler o CSV uma vez. Quem obtém o
P180 é `weather.fetch_precipitation_sum`.
"""
from __future__ import annotations

import csv
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CSV_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "lfmc_climatologia_pt.csv"


@dataclass(frozen=True)
class CurvaLFMC:
    """Uma curva ajustada, com o seu domínio de validade."""
    escalar: str                # "herbaceo" | "lenhoso"
    a0: float
    cos1: float
    sin1: float
    cos2: float
    sin2: float
    beta_p180: float
    dj_min: int                 # dia do ano mínimo com medições
    dj_max: int                 # dia do ano máximo com medições
    fora_janela_pct: float      # valor a assumir fora de [dj_min, dj_max]
    p180_min: float
    p180_max: float
    lfmc_min_observado: float   # gama medida em campo — limita o avalia()
    lfmc_max_observado: float
    n: int
    rmse_cv_pp: float
    grupos: str
    nota: str

    def avalia(self, dia_juliano: int, p180_mm: float) -> float:
        """LFMC em percentagem para este dia do ano e esta precipitação.

        Fora da janela com medições devolve `fora_janela_pct` em vez de
        extrapolar: a harmónica só está constrangida onde há dados, e
        fora disso produz valores impossíveis — para o herbáceo, que só
        tem medições de Abril a Setembro, Janeiro daria −354%.

        O P180 é limitado ao intervalo do ajuste. Extrapolar linearmente
        um coeficiente de regressão para além dos dados que o
        determinaram é onde estes modelos costumam produzir absurdos
        (foi exactamente assim que o Yebra chegou a 208% de humidade
        herbácea em Portugal com coeficientes de Cabañeros).
        """
        if not (self.dj_min <= dia_juliano <= self.dj_max):
            return self.fora_janela_pct

        p180 = min(max(p180_mm, self.p180_min), self.p180_max)
        t = 2.0 * math.pi * dia_juliano / 365.0
        valor = (
            self.a0
            + self.cos1 * math.cos(t)
            + self.sin1 * math.sin(t)
            + self.cos2 * math.cos(2 * t)
            + self.sin2 * math.sin(2 * t)
            + self.beta_p180 * p180
        )
        # Rede de segurança: mesmo dentro da janela, um P180 no extremo do
        # intervalo com um dia do ano no extremo pode sair fora da gama
        # observada. Limita-se ao que foi medido em campo.
        return min(max(valor, self.lfmc_min_observado), self.lfmc_max_observado)


_curvas: Optional[dict[str, CurvaLFMC]] = None


def carrega_curvas(path: str | Path | None = None) -> dict[str, CurvaLFMC]:
    """Lê o CSV das curvas. Resultado em cache no módulo."""
    global _curvas
    if _curvas is not None and path is None:
        return _curvas

    p = Path(path or os.environ.get("LFMC_CLIMATOLOGIA_CSV") or _CSV_DEFAULT)
    curvas: dict[str, CurvaLFMC] = {}
    with p.open(encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            curvas[linha["escalar"]] = CurvaLFMC(
                escalar=linha["escalar"],
                a0=float(linha["a0"]),
                cos1=float(linha["cos1"]), sin1=float(linha["sin1"]),
                cos2=float(linha["cos2"]), sin2=float(linha["sin2"]),
                beta_p180=float(linha["beta_p180"]),
                dj_min=int(linha["dj_min"]), dj_max=int(linha["dj_max"]),
                fora_janela_pct=float(linha["fora_janela_pct"]),
                p180_min=float(linha["p180_min"]), p180_max=float(linha["p180_max"]),
                n=int(linha["n"]), rmse_cv_pp=float(linha["rmse_cv_pp"]),
                grupos=linha["grupos"], nota=linha.get("nota", ""),
                lfmc_min_observado=float(linha["lfmc_min"]),
                lfmc_max_observado=float(linha["lfmc_max"]),
            )
    faltam = {"herbaceo", "lenhoso"} - set(curvas)
    if faltam:
        raise ValueError(f"{p}: faltam curvas para {sorted(faltam)}")
    if path is None:
        _curvas = curvas
    return curvas


def lfmc_climatologia(
    dia_juliano: int,
    p180_mm: float,
    path: str | Path | None = None,
) -> tuple[float, float]:
    """
    Devolve `(live_h_pct, live_w_pct)` — herbáceo e lenhoso, em percento
    de peso seco, prontos para `derive_fire_weather`.

    `dia_juliano`: 1-366. `p180_mm`: precipitação acumulada nos 180 dias
    anteriores à data em causa (ver `weather.fetch_precipitation_sum`).

    O lenhoso corresponde à folhagem viva do **leito de superfície**
    (mato/sub-coberto), que é o que `LiveW_FL` representa nos modelos
    Rothermel. A folhagem de copa (pinhal, eucalipto) é outro estrato e
    não entra aqui, apesar de haver medições dela no ficheiro de campo.
    """
    curvas = carrega_curvas(path)
    return (
        curvas["herbaceo"].avalia(dia_juliano, p180_mm),
        curvas["lenhoso"].avalia(dia_juliano, p180_mm),
    )


def descreve() -> str:
    """Uma linha por curva, para os logs de arranque."""
    try:
        curvas = carrega_curvas()
    except Exception as exc:
        return f"climatologia LFMC indisponível: {exc}"
    return " | ".join(
        f"{c.escalar}: n={c.n} RMSE={c.rmse_cv_pp}pp DJ{c.dj_min}-{c.dj_max}"
        for c in curvas.values()
    )
