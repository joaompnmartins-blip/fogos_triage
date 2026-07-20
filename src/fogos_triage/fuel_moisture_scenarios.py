"""
Cenários-padrão de humidade de combustível — BehavePlus/NWCG.

Fonte: Andrews, P.L. (2009). BehavePlus fire modeling system, version
5.0: Variables. USDA Forest Service, RMRS-GTR-213WWW; NWCG Fire
Behavior Field Reference Guide (PMS 437). Tabela D1-D4 (humidade dos
combustíveis mortos) × L1-L4 (estado de cura do herbáceo) — 16
combinações-padrão usadas em BehavePlus para testar comportamento do
fogo sob condições de humidade fixas, independentes da meteo do dia.

Override opcional para o Simulador: substitui as humidades calculadas
(Simard 1968 para os mortos, VIIRS/GEE ou fallback sazonal para os
vivos — ver weather.py) pelas deste cenário. Vento/temperatura/humidade
relativa mantêm-se sempre do Open-Meteo — estes cenários definem só
humidade de combustível, não meteo completa (mesma filosofia do
override "usar rajadas" em triage.py:gust_weather).

Módulo único de verdade: services/api/schemas.py (validação) e o
frontend (via constants.js) devem reflectir esta tabela, não repetir
as 16 chaves independentemente.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .schemas import WeatherConditions


@dataclass(frozen=True)
class FuelMoistureScenario:
    key: str            # "D1L1".."D4L4"
    label_pt: str        # rótulo traduzido, para a UI
    m1h_pct: float
    m10h_pct: float
    m100h_pct: float
    live_h_pct: float    # herbáceo
    live_w_pct: float    # lenhoso


# BehavePlus/NWCG — Dx = nível de humidade dos mortos (1=muito baixo ..
# 4=alto), Lx = estado de cura do herbáceo vivo (1=totalmente curado ..
# 4=totalmente verde). Valores em % — (m1h, m10h, m100h, live_h, live_w).
FUEL_MOISTURE_SCENARIOS: dict[str, FuelMoistureScenario] = {
    "D1L1": FuelMoistureScenario("D1L1", "Morto muito seco, herbáceo curado (3,4,5,30,60)", 3, 4, 5, 30, 60),
    "D1L2": FuelMoistureScenario("D1L2", "Morto muito seco, herbáceo 2/3 cura (3,4,5,60,90)", 3, 4, 5, 60, 90),
    "D1L3": FuelMoistureScenario("D1L3", "Morto muito seco, herbáceo 1/3 cura (3,4,5,90,120)", 3, 4, 5, 90, 120),
    "D1L4": FuelMoistureScenario("D1L4", "Morto muito seco, herbáceo verde (3,4,5,120,150)", 3, 4, 5, 120, 150),
    "D2L1": FuelMoistureScenario("D2L1", "Morto seco, herbáceo curado (6,7,8,30,60)", 6, 7, 8, 30, 60),
    "D2L2": FuelMoistureScenario("D2L2", "Morto seco, herbáceo 2/3 cura (6,7,8,60,90)", 6, 7, 8, 60, 90),
    "D2L3": FuelMoistureScenario("D2L3", "Morto seco, herbáceo 1/3 cura (6,7,8,90,120)", 6, 7, 8, 90, 120),
    "D2L4": FuelMoistureScenario("D2L4", "Morto seco, herbáceo verde (6,7,8,120,150)", 6, 7, 8, 120, 150),
    "D3L1": FuelMoistureScenario("D3L1", "Morto pouco seco, herbáceo curado (9,10,11,30,60)", 9, 10, 11, 30, 60),
    "D3L2": FuelMoistureScenario("D3L2", "Morto pouco seco, herbáceo 2/3 cura (9,10,11,60,90)", 9, 10, 11, 60, 90),
    "D3L3": FuelMoistureScenario("D3L3", "Morto pouco seco, herbáceo 1/3 cura (9,10,11,90,120)", 9, 10, 11, 90, 120),
    "D3L4": FuelMoistureScenario("D3L4", "Morto pouco seco, herbáceo verde (9,10,11,120,150)", 9, 10, 11, 120, 150),
    "D4L1": FuelMoistureScenario("D4L1", "Morto húmido, herbáceo curado (12,13,14,30,60)", 12, 13, 14, 30, 60),
    "D4L2": FuelMoistureScenario("D4L2", "Morto húmido, herbáceo 2/3 cura (12,13,14,60,90)", 12, 13, 14, 60, 90),
    "D4L3": FuelMoistureScenario("D4L3", "Morto húmido, herbáceo 1/3 cura (12,13,14,90,120)", 12, 13, 14, 90, 120),
    "D4L4": FuelMoistureScenario("D4L4", "Morto húmido, herbáceo verde (12,13,14,120,150)", 12, 13, 14, 120, 150),
}


def apply_fuel_moisture_scenario(wx: WeatherConditions, scenario_key: str) -> WeatherConditions:
    """Substitui as humidades de combustível calculadas pelas do cenário
    BehavePlus/NWCG indicado — vento/temperatura/humidade relativa
    mantêm-se do Open-Meteo, só as 5 humidades de combustível mudam."""
    s = FUEL_MOISTURE_SCENARIOS[scenario_key]
    return replace(
        wx,
        fuel_moisture_1h_pct=s.m1h_pct,
        fuel_moisture_10h_pct=s.m10h_pct,
        fuel_moisture_100h_pct=s.m100h_pct,
        fuel_moisture_live_h_pct=s.live_h_pct,
        fuel_moisture_live_w_pct=s.live_w_pct,
    )
