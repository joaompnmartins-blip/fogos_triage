"""
Serviço de triagem.

Orquestra: ocorrência → terreno + meteo → motor → resultado priorizado.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace
from typing import Optional

from .engine import check_crown_fire_transition, predict_surface_fire
from .fuel_models import FuelModelPT
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


NEIGHBOURHOOD_RADIUS_M = 200.0

_DEFAULT_TERRAIN = TerrainConditions(
    elevation_m=0.0, slope_fraction=0.0, slope_degrees=0.0,
    aspect_degrees=0.0, fuel_model_num=98,
)


def triage_neighbourhood(
    occurrence: Occurrence,
    fuel_models: dict[int, FuelModelPT],
    terrains: list[TerrainConditions],
    weather_raw: WeatherConditions,
    live_h_pct: Optional[float] = None,
    live_w_pct: Optional[float] = None,
) -> TriageResult:
    """
    Triagem com amostragem de vizinhança (9 pixels, raio 200 m).

    Para cada pixel: deriva meteo com WAF per-pixel (canopy/height dos rasters),
    corre Rothermel, e recolhe o ROS resultante.  Os cenários são construídos
    a partir da distribuição de ROS:
      central → mediana (P50)
      pior    → máximo  (pixel mais desfavorável)
      melhor  → mínimo  (pixel mais favorável)

    O modelo de combustível reportado é o dominante (moda) na vizinhança.
    Fallback para triagem pixel-único se nenhum pixel produzir ROS válido.
    """
    pixel_results: list[tuple] = []  # (pred, terrain, fm, wx)

    for terrain in terrains:
        fm = fuel_models.get(terrain.fuel_model_num) or fuel_models.get(98)
        if fm is None:
            continue

        has_overstory = (terrain.canopy_cover_pct or 0) > 10
        wx = derive_fire_weather(
            weather_raw,
            stand_height_m=terrain.stand_height_m or 0.0,
            canopy_cover_pct=terrain.canopy_cover_pct or 0.0,
            has_overstory=has_overstory,
            live_h_pct=live_h_pct,
            live_w_pct=live_w_pct,
        )

        try:
            pred = predict_surface_fire(fm, terrain, wx, "")
        except Exception:
            continue

        if pred.ros_m_per_min > 0:
            pixel_results.append((pred, terrain, fm, wx))

    # Fallback para pixel único se nenhum pixel produziu ROS válido
    if not pixel_results:
        terrain0 = terrains[0] if terrains else _DEFAULT_TERRAIN
        wx0 = derive_fire_weather(weather_raw, live_h_pct=live_h_pct, live_w_pct=live_w_pct)
        return triage_occurrence(occurrence, fuel_models, terrain0, wx0)

    pixel_results.sort(key=lambda x: x[0].ros_m_per_min)
    n = len(pixel_results)

    best_pred,    _,               _,          _           = pixel_results[0]
    central_pred, central_terrain, central_fm, central_wx  = pixel_results[n // 2]
    worst_pred,   _,               _,          _           = pixel_results[-1]

    best_pred    = replace(best_pred,    scenario="best")
    central_pred = replace(central_pred, scenario="central")
    worst_pred   = replace(worst_pred,   scenario="worst")

    notes = [
        f"Multi-pixel: {n}/{len(terrains)} px válidos, raio {NEIGHBOURHOOD_RADIUS_M:.0f}m"
    ]

    # Crown fire check no cenário central
    if central_terrain.canopy_base_height_m and central_pred.fireline_intensity_kw_m > 0:
        transition, I_crit = check_crown_fire_transition(
            central_pred.fireline_intensity_kw_m,
            central_terrain.canopy_base_height_m,
            foliar_moisture_pct=100.0,
        )
        if transition:
            central_pred = replace(central_pred, fire_type=FireType.TORCHING)
            notes.append(
                f"Transição para fogo de copas possível (I_critical={I_crit:.0f} kW/m)"
            )

    # Modelo dominante na vizinhança
    fm_counter = Counter(
        fuel_models[t.fuel_model_num].code
        for _, t, _, _ in pixel_results
        if t.fuel_model_num in fuel_models
    )
    dominant_fm_code = (fm_counter.most_common(1)[0][0]
                        if fm_counter else central_fm.code)

    waf = (central_wx.wind_midflame_ms / central_wx.wind_speed_10m_ms
           if (central_wx.wind_speed_10m_ms or 0) > 0 else 0.0)

    priority, score = compute_priority(central_pred, occurrence)

    return TriageResult(
        occurrence=occurrence,
        terrain=central_terrain,
        weather=central_wx,
        predictions=[central_pred, worst_pred, best_pred],
        priority=priority,
        priority_score=score,
        fuel_model_used=dominant_fm_code,
        wind_adjustment_factor=waf,
        notes=notes,
    )


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
        fm = fuel_models.get(98)
        # Scott & Burgan 40 NB codes (91-98) = Non-Burnable; mapeamos para FM98
        if 91 <= terrain.fuel_model_num <= 98:
            notes = [f"FM{terrain.fuel_model_num} (NB Scott&Burgan) → não combustível"]
        else:
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
    Score de prioridade contínuo 0-100, alinhado com as classes FWI ANEPC.

    Limiares de score → prioridade (calibrados para FLI típico de cada classe):
      P0 ≥ 87  — Extremo    FLI ≥ 10 000 kW/m, copa ativa, incontrolável
      P1 ≥ 67  — Muito El.  FLI  4 000-10 000, copa passiva, só meios aéreos pesados
      P2 ≥ 47  — Elevado    FLI  2 000- 4 000, meios aéreos necessários
      P3 ≥ 22  — Moderado   FLI    500- 2 000, terrestres efetivos
      P4 < 22  — Baixo      FLI  <    500    , sapadores

    Fórmula:
      score = (0.50×I + 0.25×T + 0.25×R) × crown_modifier
      I = intensidade log-scale, calibrada: 500→25, 2000→50, 4000→70, 10000→90
      T = tática por comprimento de chama (limiares FWI)
      R = velocidade de propagação
      crown_modifier = 1.20 (torching) / 1.50 (crowning)
    """
    fli = max(behavior.fireline_intensity_kw_m, 1.0)
    L   = behavior.flame_length_m
    ros = behavior.ros_m_per_min

    # Intensidade — calibrada nos limiares FWI: 500→25, 2000→50, 4000→70, 10000→90
    intensity_score = max(0.0, min(100.0, 50.0 * math.log10(fli) - 110.0))

    # Tática — limiares alinhados com FWI (Baixo/Moderado/Elevado/Muito El./Extremo)
    if L < 1.3:
        tactic_score = 10    # Baixo: sapadores
    elif L < 2.5:
        tactic_score = 35    # Moderado: terrestres
    elif L < 3.5:
        tactic_score = 60    # Elevado: máquinas + aéreos
    elif L < 10.0:
        tactic_score = 82    # Muito Elevado: só aéreos pesados
    else:
        tactic_score = 95    # Extremo: flancos e retaguarda

    # ROS (m/min)
    if ros < 1:
        ros_score = 5
    elif ros < 5:
        ros_score = 25
    elif ros < 15:
        ros_score = 55
    elif ros < 30:
        ros_score = 78
    else:
        ros_score = 92

    # Modificador crown fire — mais agressivo para distinguir P1 de P0
    crown_modifier = 1.0
    if behavior.fire_type == FireType.TORCHING:
        crown_modifier = 1.20   # copa passiva: eleva P2→P1, P1→P0
    elif behavior.fire_type == FireType.CROWNING:
        crown_modifier = 1.50   # copa ativa: eleva para P0 em quase todos os casos

    score = min(100.0,
                (0.50 * intensity_score
                 + 0.25 * tactic_score
                 + 0.25 * ros_score) * crown_modifier)

    # Mapeamento alinhado com classes FWI
    if score >= 87:
        prio = Priority.P0_EXTREME
    elif score >= 67:
        prio = Priority.P1_CRITICAL
    elif score >= 47:
        prio = Priority.P2_HIGH
    elif score >= 22:
        prio = Priority.P3_WATCH
    else:
        prio = Priority.P4_CONTROLLED

    return prio, score
