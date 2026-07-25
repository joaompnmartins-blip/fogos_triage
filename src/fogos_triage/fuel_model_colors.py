"""
Paleta e designações oficiais dos modelos de combustível PT — usada pelo
overlay de tiles (services/api/routes_tiles.py) e pela legenda do frontend.

Fonte: `data/modelos_combustivel_PT_cores.csv` (cores e designações
oficiais da classificação usada no landscape file nacional). Os valores
abaixo são espelho fiel desse ficheiro — gerados a partir dele, não
escolhidos aqui. **Não substituir por uma paleta "melhorada"**: estas
cores são as que os utilizadores (ANEPC/bombeiros) já reconhecem da
cartografia oficial; qualquer divergência torna o mapa mais bonito e
menos utilizável.

Nota sobre acessibilidade: por serem impostas externamente, estas cores
não passam pelos critérios de separação CVD que se aplicariam a uma
paleta livre (ex. 211/223 são dois verdes saturados próximos). A legenda
compensa com etiqueta de texto sempre visível ao lado de cada amostra —
a cor nunca é o único canal de informação.

IMPORTANTE — 98 NÃO é "sem dados". No catálogo oficial 98 = "Planos de
água" (azul), uma classe real presente no raster (~2% do território).
O valor de fundo do raster nacional é **0** (~44% dos pixels, oceano e
território não-PT); o nodata declarado no GeoTIFF (-32768) não chega
sequer a ocorrer. Ambos ficam transparentes por não estarem na paleta
(ver `rgba_for`), sem precisar de nenhuma substituição especial.

Isto é independente do tratamento em simulação/triagem, onde os códigos
NB Scott & Burgan (91-99) são todos reduzidos a FM98 = não combustível
(ver `normalize_fuel_model_num` em fuel_models.py). Aqui é só desenho:
cada código mantém a sua cor e designação próprias.
"""
from __future__ import annotations

# Ordem dos grupos tal como aparecem na legenda (combustível primeiro,
# não-combustível no fim — relevância para comportamento do fogo).
FUEL_MODEL_GROUP_ORDER: tuple[str, ...] = (
    "Povoamento sem sub-coberto",
    "Povoamento com sub-coberto",
    "Herbáceas / Matos",
    "Não combustível",
)

# {código: (R, G, B, A)} — espelho de data/modelos_combustivel_PT_cores.csv
FUEL_MODEL_RGBA: dict[int, tuple[int, int, int, int]] = {
    211: (0, 255, 0, 255),        # Eucalipto sem sub-coberto
    212: (0, 121, 0, 255),        # Folhosas sem sub-coberto
    213: (0, 77, 0, 255),         # Pinheiro-bravo sem sub-coberto
    214: (201, 233, 255, 255),    # Resinosas de agulha-curta
    221: (8, 102, 100, 255),      # Caducifólias com sub-coberto
    222: (0, 160, 16, 255),       # Esclerófilas com sub-coberto
    223: (0, 216, 20, 255),       # Eucalipto com sub-coberto
    224: (162, 224, 0, 255),      # Seleção de varas de Eucalipto
    225: (22, 188, 100, 255),     # Povoamentos com sub-coberto de fetos
    226: (148, 102, 78, 255),     # Povoamentos com sub-coberto de herbáceas
    227: (39, 55, 0, 255),        # Pinheiro-bravo com sub-coberto
    231: (255, 224, 64, 255),     # Herbáceas altas (>0,5 metros)
    232: (255, 255, 0, 255),      # Herbáceas baixas (<0,5 metros)
    233: (255, 117, 51, 255),     # Matos atlânticos altos (>1 metro)
    234: (255, 152, 104, 255),    # Matos atlânticos baixos (<1 metro)
    235: (173, 229, 68, 255),     # Matos jovens
    236: (225, 195, 43, 255),     # Matos mediterrânicos altos (>1 metro)
    237: (222, 224, 32, 255),     # Matos mediterrânicos baixos (<1 metro)
    91: (212, 0, 0, 255),         # Urbano
    93: (66, 207, 183, 255),      # Agricultura de regadios
    98: (0, 87, 247, 255),        # Planos de água
    99: (189, 189, 189, 255),     # Rocha
}

# {código: (designação, grupo)} — mesma fonte.
FUEL_MODEL_INFO: dict[int, tuple[str, str]] = {
    211: ("Eucalipto sem sub-coberto", "Povoamento sem sub-coberto"),
    212: ("Folhosas sem sub-coberto", "Povoamento sem sub-coberto"),
    213: ("Pinheiro-bravo sem sub-coberto", "Povoamento sem sub-coberto"),
    214: ("Resinosas de agulha-curta", "Povoamento sem sub-coberto"),
    221: ("Caducifólias com sub-coberto", "Povoamento com sub-coberto"),
    222: ("Esclerófilas com sub-coberto", "Povoamento com sub-coberto"),
    223: ("Eucalipto com sub-coberto", "Povoamento com sub-coberto"),
    224: ("Seleção de varas de Eucalipto", "Povoamento com sub-coberto"),
    225: ("Povoamentos com sub-coberto de fetos", "Povoamento com sub-coberto"),
    226: ("Povoamentos com sub-coberto de herbáceas", "Povoamento com sub-coberto"),
    227: ("Pinheiro-bravo com sub-coberto", "Povoamento com sub-coberto"),
    231: ("Herbáceas altas (>0,5 metros)", "Herbáceas / Matos"),
    232: ("Herbáceas baixas (<0,5 metros)", "Herbáceas / Matos"),
    233: ("Matos atlânticos altos (>1 metro)", "Herbáceas / Matos"),
    234: ("Matos atlânticos baixos (<1 metro)", "Herbáceas / Matos"),
    235: ("Matos jovens", "Herbáceas / Matos"),
    236: ("Matos mediterrânicos altos (>1 metro)", "Herbáceas / Matos"),
    237: ("Matos mediterrânicos baixos (<1 metro)", "Herbáceas / Matos"),
    91: ("Urbano", "Não combustível"),
    93: ("Agricultura de regadios", "Não combustível"),
    98: ("Planos de água", "Não combustível"),
    99: ("Rocha", "Não combustível"),
}

_TRANSPARENT: tuple[int, int, int, int] = (0, 0, 0, 0)


def rgba_for(fuel_model_num: int) -> tuple[int, int, int, int]:
    """
    Cor RGBA de um código de modelo de combustível. Códigos fora do
    catálogo oficial — nomeadamente o fundo do raster (0), o nodata
    declarado (-32768) e quaisquer códigos NB não cartografados
    (92, 94-97) — ficam **transparentes**, para o overlay não pintar
    território sem informação.
    """
    return FUEL_MODEL_RGBA.get(fuel_model_num, _TRANSPARENT)
