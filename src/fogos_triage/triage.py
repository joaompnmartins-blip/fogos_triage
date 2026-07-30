"""
Serviço de triagem.

Orquestra: ocorrência → terreno + meteo → motor → resultado priorizado.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Optional

from .engine import check_crown_fire_transition, predict_surface_fire
from .fuel_models import FuelModelPT, normalize_fuel_model_num
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    Occurrence,
    SeverityCategory,
    TerrainConditions,
    TriageResult,
    WeatherConditions,
)
from .severity import classify_severity
from .weather import derive_fire_weather


NEIGHBOURHOOD_RADIUS_M = 50.0

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
    Triagem com amostragem de vizinhança (grelha densa à resolução do
    raster, até 50 m — ver LandscapeReader.sample_neighbourhood).

    Para cada pixel: deriva meteo com WAF per-pixel (canopy/height dos rasters),
    corre Rothermel, e recolhe o ROS resultante. O pixel representativo
    (mediana de ROS, P50) dá o terreno/combustível usados nos 2 cenários:
      "Vento Geral" (central) → vento sustentado (Open-Meteo)
      "Rajadas"     (gusts)   → vento de rajada (Open-Meteo), mesmo WAF

    O modelo de combustível reportado é o dominante (moda) na vizinhança.
    Fallback para triagem pixel-único se nenhum pixel produzir ROS válido.
    """
    pixel_results: list[tuple] = []  # (pred, terrain, fm, wx)

    for terrain in terrains:
        fm = fuel_models.get(normalize_fuel_model_num(terrain.fuel_model_num))
        if fm is None:
            continue

        has_overstory = (terrain.canopy_cover_pct or 0) > 10
        # `fm.depth` (pés) é o que permite calcular o WAF do leito —
        # sem ele cai-se no valor por omissão. Cada píxel tem o seu
        # modelo, logo o seu WAF: folhada rasa trava muito mais o vento
        # do que mato alto (0.27 contra 0.54).
        wx = derive_fire_weather(
            weather_raw,
            stand_height_m=terrain.stand_height_m or 0.0,
            canopy_cover_pct=terrain.canopy_cover_pct or 0.0,
            has_overstory=has_overstory,
            live_h_pct=live_h_pct,
            live_w_pct=live_w_pct,
            fuel_bed_depth_ft=fm.depth,
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

    central_pred, central_terrain, central_fm, central_wx = pixel_results[n // 2]
    central_pred = replace(central_pred, scenario="central")

    gust_wx = gust_weather(central_wx)
    gust_pred = predict_surface_fire(central_fm, central_terrain, gust_wx, "gusts")

    notes = [
        f"Multi-pixel: {n}/{len(terrains)} px válidos, raio {NEIGHBOURHOOD_RADIUS_M:.0f}m"
    ]

    central_pred = _check_crown(central_pred, central_terrain, notes)
    gust_pred = _check_crown(gust_pred, central_terrain, notes)

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
        predictions=[central_pred, gust_pred],
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

    Devolve TriageResult com 2 cenários: "Vento Geral" (central, vento
    sustentado) e "Rajadas" (gusts, vento de rajada do Open-Meteo).
    """
    normalized_num = normalize_fuel_model_num(terrain.fuel_model_num)
    fm = fuel_models.get(normalized_num)
    if normalized_num != terrain.fuel_model_num:
        notes = [f"FM{terrain.fuel_model_num} (NB Scott&Burgan) → não combustível"]
    elif fm is None:
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
            fuel_bed_depth_ft=fm.depth,
        )

    # 2 cenários: "Vento Geral" (central) e "Rajadas" (gusts)
    central = _predict_scenario(fm, terrain, weather, "central")
    gusts = _predict_scenario(fm, terrain, gust_weather(weather), "gusts")

    central = _check_crown(central, terrain, notes)
    gusts = _check_crown(gusts, terrain, notes)

    predictions = [central, gusts]

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


def gust_weather(wx: WeatherConditions) -> WeatherConditions:
    """
    Substitui o vento sustentado pela velocidade de rajada
    (wind_gusts_10m, Open-Meteo) no vento midflame (única entrada de vento
    que o motor Rothermel lê — engine.py nunca usa wind_speed_10m_ms),
    aplicando o mesmo WAF já calculado para o vento sustentado (não uma
    percentagem sintética). Humidades dos combustíveis mantêm-se — uma
    rajada dura segundos, não muda a humidade.

    wind_speed_10m_ms e wind_gust_10m_ms mantêm-se ambos no valor
    original (não sobrepostos) — só são campos de referência/exibição,
    para o vento sustentado e a rajada continuarem distintos mesmo
    quando é a rajada a conduzir a simulação.

    Usada pelo cenário "Rajadas" da triagem (ver triage_occurrence /
    triage_neighbourhood) e pelo override "usar rajadas" da simulação
    ForeFire (services/api/routes_meta.py, routes_freesim.py).
    """
    if not wx.wind_speed_10m_ms or wx.wind_gust_10m_ms is None:
        return wx
    waf = (wx.wind_midflame_ms or 0) / wx.wind_speed_10m_ms
    return replace(
        wx,
        wind_midflame_ms=wx.wind_gust_10m_ms * waf,
    )


def _check_crown(
    pred: FireBehaviorPrediction,
    terrain: TerrainConditions,
    notes: list[str],
) -> FireBehaviorPrediction:
    """Aplica o critério de transição para fogo de copas (Van Wagner) a um
    cenário. Independente por cenário — vento de rajada pode cruzar o
    limiar de copas mesmo quando o vento sustentado não cruza."""
    if not (terrain.canopy_base_height_m and pred.fireline_intensity_kw_m > 0):
        return pred
    transition, I_crit = check_crown_fire_transition(
        pred.fireline_intensity_kw_m,
        terrain.canopy_base_height_m,
        foliar_moisture_pct=100.0,
    )
    if transition:
        pred = replace(pred, fire_type=FireType.TORCHING)
        notes.append(
            f"Transição para fogo de copas possível no cenário '{pred.scenario}' "
            f"(I_critical={I_crit:.0f} kW/m)"
        )
    return pred


def compute_priority(
    behavior: FireBehaviorPrediction,
    occurrence: Occurrence,
) -> tuple[SeverityCategory, float]:
    """
    Classificação de severidade 1-7 (Tedim et al. 2018, Tabela 3) — ver
    src/fogos_triage/severity.py para os limiares, a fonte completa, e
    a justificação da substituição do antigo score composto 0-100
    (sem fonte publicada — ver CLASSIFICACAO_TRIAGEM.md).

    A FLI (fireline intensity) é o critério pivô — é o que a própria
    Tabela 3 usa para capacidade de controlo. `occurrence` mantém-se
    como parâmetro por compatibilidade de assinatura (não usado na
    classificação; era também ignorado na fórmula anterior).
    """
    category = classify_severity(behavior.fireline_intensity_kw_m)
    return SeverityCategory(category), behavior.fireline_intensity_kw_m
