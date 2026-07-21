"""
Initial Fuel Moistures File (.FMS) — formato nativo do FARSITE.

Tabela de humidade de combustível por modelo de combustível — override
no Simulador mais preciso do que os cenários BehavePlus de
`fuel_moisture_scenarios.py` (um único conjunto de humidades para toda
a simulação): aqui cada modelo de combustível pode ter a sua própria
humidade, aplicada por ponto/vértice consoante o `fuel_model_num` lido
do terreno nesse local (ver uso em `simulation.py`).

Formato (confirmado via documentação FARSITE, owfflammaphelp62.
firenet.gov):

    ! FuelMod 1Hour 10Hour 100Hour LiveH LiveW 1000Hour
    0 6 7 8 60 90 12
    211 4 5 7 30 60 10
    ...

O modelo "0" é obrigatório — serve de catch-all para qualquer modelo de
combustível encontrado no terreno sem entrada explícita no ficheiro
(mesma semântica do FARSITE). Linhas a começar por "!" são comentário.

A coluna "1000Hour" é parseada e guardada mas não é usada pelo motor —
`_rothermel_direct()` (Rothermel 1972 de superfície) não tem parâmetro
de humidade 1000h; essa classe só existe em extensões FARSITE de
smouldering/duff, fora do âmbito do motor actual.
"""
from __future__ import annotations

from dataclasses import dataclass

_EXPECTED_COLUMNS = 7  # FuelMod 1Hour 10Hour 100Hour LiveH LiveW 1000Hour


@dataclass(frozen=True)
class FuelMoistureRow:
    fuel_model_num: int
    m1h_pct: float
    m10h_pct: float
    m100h_pct: float
    live_h_pct: float
    live_w_pct: float
    load_1000h_pct: float  # guardado, não consumido pelo motor — ver docstring do módulo


def parse_fuel_moisture_table(text: str) -> dict[int, FuelMoistureRow]:
    """Parseia um Initial Fuel Moistures File (.FMS) FARSITE.

    Levanta ValueError (com o número da linha em causa) se alguma linha
    de dados não tiver as 7 colunas esperadas ou valores não numéricos,
    ou se a entrada obrigatória "0" (catch-all) estiver ausente.
    """
    table: dict[int, FuelMoistureRow] = {}

    for i, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue

        fields = line.split()
        if len(fields) != _EXPECTED_COLUMNS:
            raise ValueError(
                f"Initial Fuel Moistures: linha {i + 1}: esperava "
                f"{_EXPECTED_COLUMNS} colunas (FuelMod 1Hour 10Hour 100Hour "
                f"LiveH LiveW 1000Hour), encontrei {len(fields)}"
            )
        try:
            fuel_model_num = int(fields[0])
            m1h, m10h, m100h, live_h, live_w, load_1000h = (float(v) for v in fields[1:])
        except ValueError as exc:
            raise ValueError(f"Initial Fuel Moistures: linha {i + 1}: valor inválido ({exc})") from exc

        table[fuel_model_num] = FuelMoistureRow(
            fuel_model_num=fuel_model_num,
            m1h_pct=m1h, m10h_pct=m10h, m100h_pct=m100h,
            live_h_pct=live_h, live_w_pct=live_w,
            load_1000h_pct=load_1000h,
        )

    if 0 not in table:
        raise ValueError(
            "Initial Fuel Moistures: falta a entrada obrigatória para o "
            "modelo \"0\" (catch-all — usada para qualquer modelo de "
            "combustível sem entrada explícita no ficheiro)"
        )

    return table


def lookup(table: dict[int, FuelMoistureRow], fuel_model_num: int) -> FuelMoistureRow:
    """Devolve a entrada do modelo de combustível dado, com fallback
    para o modelo "0" (catch-all) se não houver entrada explícita."""
    return table.get(fuel_model_num, table[0])
