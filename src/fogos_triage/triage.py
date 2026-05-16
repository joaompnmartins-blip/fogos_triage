"""
Serviço de triagem.

Orquestra: ocorrência → terreno + meteo → motor → resultado priorizado.
"""
from __future__ import annotations

import copy
import math
from dataclasses import replace
from typing import Optional

from .engine import check_crown_fire_transition, predict_surface_fire
from .fuel_models import FuelModelPT
from .landscape import LandscapeReader
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    Occurrence,
    Priority,
    TerrainConditions,
    TriageResult,
    WeatherConditions,
)
from .weather import derive_fire_weather


def triage_occurrence(
    occurrence: Occurrence,
    fuel_models: dict[int, FuelModelPT],
    terrain: TerrainConditions,
    weather: WeatherConditions,
) -> TriageResult:
    """
    Faz a triagem completa de uma ocorrência.

    Inputs já preparados (separation of concerns):
    - occurrence: vem da fogos.pt
    - terrain: já feita amostragem dos rasters
    - weather: já enriquecida com derivações de fogo

    Devolve TriageResult com 3 cenários: central, pior, melhor.
    """
    fm = fuel_models.get(terrain.fuel_model_num)
    if fm is None:
        # modelo desconhecido — usar fallback ou rejeitar?
        # Aqui usamos FM98 (não combustível) e sinalizamos
        fm = fuel_models.get(98)
        notes = [f"Modelo {terrain.fuel_model_num} desconhecido, usando FM98"]
    else:
        notes = []

    # Verificar overstory para WAF
    has_overstory = (terrain.canopy_cover_pct is not None
                     and terrain.canopy_cover_pct > 10)
    stand_h = terrain.stand_height_m or 0.0

    # Enriquecer meteo se ainda não foi feito
    if weather.wind_midflame_ms is None:
        weather = derive_fire_weather(
            weather,
            stand_height_m=stand_h,
            canopy_cover_pct=terrain.canopy_cover_pct or 0.0,
            has_overstory=has_overstory,
        )

    # 3 cenários
    predictions = []
    predictions.append(_predict_scenario(fm, terrain, weather, "central"))
    predictions.append(_predict_scenario(fm, terrain, _worst_weather(weather), "worst"))
    predictions.append(_predict_scenario(fm, terrain, _best_weather(weather), "best"))

    # Crown fire check no cenário central
    central = predictions[0]
    if terrain.canopy_base_height_m and central.fireline_intensity_kw_m > 0:
        transition, I_crit = check_crown_fire_transition(
            central.fireline_intensity_kw_m,
            terrain.canopy_base_height_m,
            foliar_moisture_pct=100.0,
        )
        if transition:
            central.fire_type = FireType.TORCHING
            notes.append(f"Transição para fogo de copas possível "
                         f"(I_critical={I_crit:.0f} kW/m)")

    # WAF efetivo usado
    waf = (weather.wind_midflame_ms / weather.wind_speed_10m_ms
           if weather.wind_speed_10m_ms > 0 else 0)

    # Prioridade
    priority, score = compute_priority(central, occurrence)

    return TriageResult(
        occurrence=occurrence,
        terrain=terrain,
        weather=weather,
        predictions=predictions,
        priority=priority,
        priority_score=score,
        fuel_model_used=fm.code,
        wind_adjustment_factor=waf,
        notes=notes,
    )


def _predict_scenario(
    fm: FuelModelPT,
    terrain: TerrainConditions,
    weather: WeatherConditions,
    scenario_name: str,
) -> FireBehaviorPrediction:
    return predict_surface_fire(fm, terrain, weather, scenario_name)


def _worst_weather(wx: WeatherConditions) -> WeatherConditions:
    """
    Cenário pior caso plausível:
    - vento midflame +20%
    - humidade dos finos -25%
    """
    return replace(
        wx,
        wind_midflame_ms=(wx.wind_midflame_ms or 0) * 1.20,
        wind_speed_10m_ms=wx.wind_speed_10m_ms * 1.20,
        fuel_moisture_1h_pct=(wx.fuel_moisture_1h_pct or 8) * 0.75,
        fuel_moisture_10h_pct=(wx.fuel_moisture_10h_pct or 9) * 0.85,
        fuel_moisture_100h_pct=(wx.fuel_moisture_100h_pct or 10) * 0.90,
    )


def _best_weather(wx: WeatherConditions) -> WeatherConditions:
    """
    Cenário melhor caso plausível:
    - vento midflame -20%
    - humidade dos finos +25%
    """
    return replace(
        wx,
        wind_midflame_ms=(wx.wind_midflame_ms or 0) * 0.80,
        wind_speed_10m_ms=wx.wind_speed_10m_ms * 0.80,
        fuel_moisture_1h_pct=(wx.fuel_moisture_1h_pct or 8) * 1.25,
        fuel_moisture_10h_pct=(wx.fuel_moisture_10h_pct or 9) * 1.15,
        fuel_moisture_100h_pct=(wx.fuel_moisture_100h_pct or 10) * 1.10,
    )


def compute_priority(
    behavior: FireBehaviorPrediction,
    occurrence: Occurrence,
) -> tuple[Priority, float]:
    """
    Score de prioridade contínuo 0-100, com mapeamento para P1-P4.

    Fatores:
    - Intensidade prevista (Byram em kW/m), normalizada
    - Comprimento de chama (categoria táctica)
    - ROS (rapidez de propagação)
    - Modificador por crown fire
    - Modificador por meios já alocados vs necessários (placeholder)

    Esta é uma fórmula inicial. Deve ser calibrada com casos reais e
    feedback operacional. Os pesos devem ser revistos com pessoal ANEPC.
    """
    # Componente intensidade — log-scale porque varia de 100 a 100000 kW/m
    fli = max(behavior.fireline_intensity_kw_m, 1.0)
    intensity_score = min(100.0, 20.0 * math.log10(fli) - 20.0)  # 1000 kW/m → 40, 10000 → 60, 100000 → 80
    intensity_score = max(0, intensity_score)

    # Componente táctica
    L = behavior.flame_length_m
    if L < 1.2:
        tactic_score = 10
    elif L < 2.4:
        tactic_score = 35
    elif L < 3.4:
        tactic_score = 60
    elif L < 7:
        tactic_score = 80
    else:
        tactic_score = 95

    # Componente ROS (m/min)
    ros = behavior.ros_m_per_min
    if ros < 1:
        ros_score = 5
    elif ros < 5:
        ros_score = 30
    elif ros < 15:
        ros_score = 60
    elif ros < 30:
        ros_score = 80
    else:
        ros_score = 95

    # Modificador crown fire
    crown_modifier = 1.0
    if behavior.fire_type == FireType.TORCHING:
        crown_modifier = 1.15
    elif behavior.fire_type == FireType.CROWNING:
        crown_modifier = 1.30

    # Combinação ponderada
    score = (0.4 * intensity_score
             + 0.3 * tactic_score
             + 0.3 * ros_score) * crown_modifier
    score = min(100.0, score)

    # Mapeamento para prioridades
    if score >= 70:
        prio = Priority.P1_CRITICAL
    elif score >= 50:
        prio = Priority.P2_HIGH
    elif score >= 25:
        prio = Priority.P3_WATCH
    else:
        prio = Priority.P4_CONTROLLED

    return prio, score
