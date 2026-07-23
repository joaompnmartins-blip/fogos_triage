"""
Paleta de cores por modelo de combustível — usada pelo overlay de tiles
(services/api/routes_tiles.py) e pela legenda do frontend.

Os modelos PT (`data/fuel_models_pt.csv`) agrupam-se por centena — 21x,
22x, 23x — mais dois casos especiais (255, 98). Skill `dataviz`
confirma que uma paleta categórica plana com as ~19 cores
independentes não é possível — o próprio validador não deixa passar
mais de 3-4 matizes totalmente distintos num teste all-pairs (caso de
choropleth/mapa, onde qualquer par de cores pode ficar lado a lado).
Por isso a paleta usa **matiz por família** (211-214, 221-227, 231-237,
255, 98) — validado com `validate_palette.js --pairs all` — e
**luminosidade a variar dentro de cada família** para distinguir os
modelos individuais (mesmo padrão de um mapa de uso do solo
convencional: cor = categoria principal, tom = sub-categoria).

Validação (scripts/validate_palette.js, skill dataviz, 2026-07-23):
    node scripts/validate_palette.js \
      "#2f7d32,#1b6ea8,#c2376b,#e0a300" --mode light --pairs all
    → ALL CHECKS PASS (WARN em CVD floor-band e contraste do amarelo,
      ambos mitigados pela legenda ter sempre etiqueta de texto visível
      ao lado de cada amostra de cor — canal secundário exigido pela
      skill nesse caso).
"""
from __future__ import annotations

_FAMILY_BASE_HEX: dict[str, str] = {
    "21x": "#2f7d32",  # verde
    "22x": "#1b6ea8",  # azul
    "23x": "#c2376b",  # magenta
    "255": "#e0a300",  # âmbar
}

# Modelo 98 (não combustível — rocha/água/urbano/nodata, ver
# landscape.py) fica sempre transparente, nunca desenhado. Os restantes
# códigos NB Scott & Burgan (91-97, 99 — ver fuel_models.py,
# normalize_fuel_model_num) nunca entram em nenhuma família acima, por
# isso também ficam transparentes por omissão (nunca chegam a `palette`
# em build_fuel_model_palette) — mesmo resultado visual, sem precisar de
# mais uma cor a competir pelo já esgotado orçamento de 4 matizes
# distinguíveis. A legenda do frontend explica-os numa linha à parte
# (ver FuelModelLegend em SimulationPanels.jsx).
NODATA_FUEL_MODEL_NUM = 98


def _family_of(fuel_model_num: int) -> str:
    if fuel_model_num == 255:
        return "255"
    return f"{fuel_model_num // 10}x"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _blend(rgb: tuple[int, int, int], target: tuple[int, int, int], frac: float) -> tuple[int, int, int]:
    return tuple(round(c + (t - c) * frac) for c, t in zip(rgb, target))


def _family_members(family: str, all_nums: list[int]) -> list[int]:
    if family == "255":
        return [255]
    prefix = int(family[:-1])
    return sorted(n for n in all_nums if n // 10 == prefix)


def build_fuel_model_palette(fuel_model_nums: list[int]) -> dict[int, tuple[int, int, int, int]]:
    """
    Constrói `{fuel_model_num: (r, g, b, a)}` para todos os números
    dados — luminosidade varia dentro de cada família (mais escuro
    para o primeiro membro, mais claro para o último, ordenados pelo
    próprio número de modelo), matiz da família fixo e validado.
    Modelo 98 (ou qualquer não reconhecido) → totalmente transparente.
    """
    palette: dict[int, tuple[int, int, int, int]] = {}
    families: dict[str, list[int]] = {}
    for num in fuel_model_nums:
        if num == NODATA_FUEL_MODEL_NUM:
            continue
        families.setdefault(_family_of(num), []).append(num)

    for family, base_hex in _FAMILY_BASE_HEX.items():
        members = sorted(families.get(family, []))
        if not members:
            continue
        base_rgb = _hex_to_rgb(base_hex)
        n = len(members)
        for i, num in enumerate(members):
            # Passos monótonos de luminosidade dentro da família: do tom
            # base (i=0) até ~35% mais claro (último membro) — nunca tão
            # claro que perca separação do fundo/outras famílias.
            frac = 0.0 if n == 1 else (i / (n - 1)) * 0.35
            rgb = _blend(base_rgb, (255, 255, 255), frac)
            palette[num] = (*rgb, 255)

    palette[NODATA_FUEL_MODEL_NUM] = (0, 0, 0, 0)
    return palette
