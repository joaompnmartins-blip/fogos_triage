"""
Adapter para o motor wildfire_ROS_models.

Encapsula a chamada ao RothermelAndrews2018 com os inputs do nosso domínio
(TerrainConditions, WeatherConditions, FuelModelPT) e devolve um
FireBehaviorPrediction.

Esta versão usa a biblioteca REAL wildfire_ROS_models (forefireAPI), com
agregação ponderada dos 5 componentes de fuel para single-fuel equivalente
(abordagem BehavePlus).

Importação resiliente: se a wildfire_ROS_models não estiver instalada,
o engine devolve resultados a zero com aviso. Em produção, instalar a
biblioteca com:
    pip install git+https://github.com/forefireAPI/wildfire_ROS_models.git

A biblioteca tem dependência opcional em tensorflow para o módulo de neural
network. Para evitar instalar TF (~1GB) num servidor de produção que não
precisa dele, fazemos stub das suas importações no nosso loader.
"""
from __future__ import annotations

import math
import sys
import warnings
from typing import Optional
from unittest.mock import MagicMock

from .fuel_models import FuelModelPT
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    TerrainConditions,
    WeatherConditions,
)


# ---------------------------------------------------------------------------
# Lazy import da wildfire_ROS_models, com stub de tensorflow se necessário
# ---------------------------------------------------------------------------

_RA2018 = None
_model_parameters_cls = None


def _ensure_wildfire_ros_models_loaded():
    """
    Importa wildfire_ROS_models de forma lazy, contornando a dependência
    opcional em tensorflow se não estiver instalada.
    """
    global _RA2018, _model_parameters_cls

    if _RA2018 is not None:
        return  # já carregado

    # Verificar se tensorflow está disponível; senão fazer stub
    try:
        import tensorflow  # noqa: F401
    except ImportError:
        for mod_name in [
            "tensorflow",
            "tensorflow.keras",
            "tensorflow.keras.models",
            "tensorflow.keras.layers",
            "tensorflow.keras.callbacks",
            "tensorflow.keras.optimizers",
            "tensorflow.keras.regularizers",
        ]:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = MagicMock()

    try:
        from wildfire_ROS_models.RothermelAndrews2018 import RothermelAndrews2018
        from wildfire_ROS_models.model_set import model_parameters
        _RA2018 = RothermelAndrews2018
        _model_parameters_cls = model_parameters
    except ImportError as exc:
        warnings.warn(
            f"wildfire_ROS_models não disponível ({exc}). "
            f"Engine vai devolver resultados a zero. "
            f"Instalar com: pip install git+https://github.com/forefireAPI/wildfire_ROS_models.git",
            RuntimeWarning,
        )


# ---------------------------------------------------------------------------
# Agregação ponderada à BehavePlus
# ---------------------------------------------------------------------------


def aggregate_multifuel(
    fm: FuelModelPT,
    moist_1h: float,
    moist_10h: float,
    moist_100h: float,
    moist_live_h: float,
    moist_live_w: float,
) -> Optional[dict]:
    """
    Agrega os 5 componentes do fuel model num equivalente single-fuel,
    seguindo a abordagem do BehavePlus.

    Devolve dict com SAV característico, carga total, humidade ponderada
    e humidade de extinção efetiva — prontos para passar à RothermelAndrews2018.

    Todas as cargas em lb/ft², SAVs em 1/ft, humidades em fração.
    Devolve None se o modelo é não-combustível.
    """
    if fm.is_empty:
        return None

    rho_p = 32.0  # lb/ft³, densidade da partícula (Rothermel default)
    sav_10h = 109.0  # 1/ft (fixos no Rothermel)
    sav_100h = 30.0

    # Áreas de superfície por classe: A_i = sigma_i * w_i / rho_p
    A_1h = fm.sav_1h * fm.load_1h / rho_p
    A_10h = sav_10h * fm.load_10h / rho_p
    A_100h = sav_100h * fm.load_100h / rho_p
    A_lh = fm.sav_live_h * fm.load_live_h / rho_p if fm.load_live_h > 0 else 0.0
    A_lw = fm.sav_live_w * fm.load_live_w / rho_p if fm.load_live_w > 0 else 0.0

    A_dead = A_1h + A_10h + A_100h
    A_live = A_lh + A_lw
    A_total = A_dead + A_live

    if A_total <= 0:
        return None

    # Frações de área dentro de cada categoria
    f_1h = A_1h / A_dead if A_dead > 0 else 0.0
    f_10h = A_10h / A_dead if A_dead > 0 else 0.0
    f_100h = A_100h / A_dead if A_dead > 0 else 0.0
    f_lh = A_lh / A_live if A_live > 0 else 0.0
    f_lw = A_lw / A_live if A_live > 0 else 0.0

    # Frações entre categorias
    f_dead = A_dead / A_total
    f_live = A_live / A_total

    # SAV característico
    sigma_dead = (f_1h * fm.sav_1h
                  + f_10h * sav_10h
                  + f_100h * sav_100h)
    sigma_live = (f_lh * fm.sav_live_h + f_lw * fm.sav_live_w) if A_live > 0 else 0.0
    sigma_char = f_dead * sigma_dead + f_live * sigma_live

    # Carga total
    w_total = (fm.load_1h + fm.load_10h + fm.load_100h
               + fm.load_live_h + fm.load_live_w)

    # Humidade ponderada por área (mortos e vivos separadamente)
    m_dead = ((f_1h * moist_1h + f_10h * moist_10h + f_100h * moist_100h)
              if A_dead > 0 else 0.0)
    m_live = ((f_lh * moist_live_h + f_lw * moist_live_w)
              if A_live > 0 else 0.0)

    # Humidade efetiva ponderada (combinando mortos+vivos por f_dead/f_live)
    m_eff = f_dead * m_dead + f_live * m_live

    # Humidade de extinção dos vivos (Albini 1976)
    if A_live > 0 and fm.moist_ext_dead > 0:
        K = 138.0
        sum_dead_we = (fm.load_1h * math.exp(-K / fm.sav_1h)
                       if fm.sav_1h > 0 else 0.0)
        sum_live_we = 0.0
        if fm.load_live_h > 0 and fm.sav_live_h > 0:
            sum_live_we += fm.load_live_h * math.exp(-K / fm.sav_live_h)
        if fm.load_live_w > 0 and fm.sav_live_w > 0:
            sum_live_we += fm.load_live_w * math.exp(-K / fm.sav_live_w)
        if sum_live_we > 0:
            W = sum_dead_we / sum_live_we
            M_x_live = max(
                2.9 * W * (1.0 - moist_1h / fm.moist_ext_dead) - 0.226,
                fm.moist_ext_dead,
            )
        else:
            M_x_live = fm.moist_ext_dead
    else:
        M_x_live = fm.moist_ext_dead

    # Extinction moisture efetiva
    M_x_eff = f_dead * fm.moist_ext_dead + f_live * M_x_live

    return {
        "sav_char_ftinv": sigma_char,
        "load_total_lbft2": w_total,
        "moist_eff_r": m_eff,
        "moist_ext_eff_r": M_x_eff,
        # diagnóstico
        "f_dead": f_dead,
        "f_live": f_live,
        "sigma_dead_ftinv": sigma_dead,
        "sigma_live_ftinv": sigma_live,
        "M_x_live_r": M_x_live,
    }


# ---------------------------------------------------------------------------
# Predição de fogo de superfície
# ---------------------------------------------------------------------------


def predict_surface_fire(
    fm: FuelModelPT,
    terrain: TerrainConditions,
    weather: WeatherConditions,
    scenario: str = "central",
) -> FireBehaviorPrediction:
    """
    Calcula comportamento de fogo de superfície usando RothermelAndrews2018
    da wildfire_ROS_models, com agregação multifuel à BehavePlus.
    """
    if fm.is_empty:
        return _zero_prediction(scenario, FireType.NO_BURN)

    _ensure_wildfire_ros_models_loaded()
    if _RA2018 is None:
        return _zero_prediction(scenario, FireType.NO_BURN)

    # Humidades em fração
    m_1h = (weather.fuel_moisture_1h_pct or 8.0) / 100.0
    m_10h = (weather.fuel_moisture_10h_pct or 9.0) / 100.0
    m_100h = (weather.fuel_moisture_100h_pct or 10.0) / 100.0
    m_lh = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
    m_lw = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0

    # Agregar 5 componentes em single-fuel equivalente
    agg = aggregate_multifuel(fm, m_1h, m_10h, m_100h, m_lh, m_lw)
    if agg is None:
        return _zero_prediction(scenario, FireType.NO_BURN)

    wind_ftmin = (weather.wind_midflame_ms or 0.0) * 196.85

    # Heat content ponderado mortos vs vivos
    heat_eff = (agg["f_dead"] * fm.heat_dead
                + agg["f_live"] * fm.heat_live)

    # IMPORTANTE: passar fuelDens_kgm3 (não _lbft3, devido a interpretação
    # SI no model_set.py — 32 lb/ft³ = 512.59 kg/m³)
    params = {
        "CODE": fm.code,
        "H_BTUlb": heat_eff,
        "SAVcar_ftinv": agg["sav_char_ftinv"],
        "fd_ft": fm.depth,
        "fuelDens_kgm3": 512.59,
        "Dme_r": agg["moist_ext_eff_r"],
        "fl1h_lbft2": agg["load_total_lbft2"],
        "wind_ftmin": wind_ftmin,
        "slope_deg": terrain.slope_degrees,
        "mdOnDry1h_r": agg["moist_eff_r"],
        "totMineral_r": 0.0555,
        "effectMineral_r": 0.01,
    }

    try:
        Z = _model_parameters_cls(params)
        result = _RA2018(Z)
    except Exception as exc:
        warnings.warn(f"Erro a correr RothermelAndrews2018: {exc}", RuntimeWarning)
        return _zero_prediction(scenario, FireType.NO_BURN)

    ros_ftmin = float(result.get("ROS_ftmin", 0.0))
    ros_m_min = ros_ftmin * 0.3048

    fi_btu_ft_min = float(result.get("FI_BTUftmin", 0.0))
    fi_kw_m = fi_btu_ft_min * 0.05767  # BTU/(ft·min) → kW/m

    # Flame length (Byram 1959): L = 0.0775 * I^0.46 (I em kW/m, L em m)
    flame_length_m = 0.0775 * fi_kw_m**0.46 if fi_kw_m > 0 else 0.0

    # Heat per unit area
    rt = 384.0 / agg["sav_char_ftinv"] if agg["sav_char_ftinv"] > 0 else 0
    hpa_btu_ft2 = float(result.get("PR_r", 0.0)) * rt
    hpa_kj_m2 = hpa_btu_ft2 * 11.357

    # Reaction intensity em kW/m²
    ri_btu_ft2_min = float(result.get("PR_r", 0.0))
    ri_kw_m2 = ri_btu_ft2_min * 0.1893

    # Direção da máxima propagação
    if weather.wind_speed_10m_ms > 0:
        direction = (weather.wind_direction_deg - 180.0) % 360.0
    else:
        direction = ((terrain.aspect_degrees + 180.0) % 360.0
                     if terrain.slope_degrees > 0 else 0.0)

    return FireBehaviorPrediction(
        scenario=scenario,
        ros_m_per_min=ros_m_min,
        fireline_intensity_kw_m=fi_kw_m,
        flame_length_m=flame_length_m,
        heat_per_unit_area_kj_m2=hpa_kj_m2,
        reaction_intensity_kw_m2=ri_kw_m2,
        direction_max_spread_deg=direction,
        effective_wind_ms=weather.wind_midflame_ms or 0.0,
        fire_type=FireType.SURFACE,
    )


def _zero_prediction(scenario: str, fire_type: FireType) -> FireBehaviorPrediction:
    return FireBehaviorPrediction(
        scenario=scenario,
        ros_m_per_min=0.0,
        fireline_intensity_kw_m=0.0,
        flame_length_m=0.0,
        heat_per_unit_area_kj_m2=0.0,
        reaction_intensity_kw_m2=0.0,
        direction_max_spread_deg=0.0,
        effective_wind_ms=0.0,
        fire_type=fire_type,
    )


# ---------------------------------------------------------------------------
# Crown fire — Van Wagner 1977
# ---------------------------------------------------------------------------


def check_crown_fire_transition(
    surface_fli_kw_m: float,
    canopy_base_height_m: Optional[float],
    foliar_moisture_pct: float = 100.0,
) -> tuple[bool, float]:
    """
    Testa se há transição para fogo de copas (Van Wagner 1977).

    Critério: I_surface >= I'_o
    onde I'_o = (0.01 * CBH * (460 + 25.9 * FMC))^1.5  [kW/m]

    Devolve (transition_occurs, critical_intensity_kw_m).
    """
    if canopy_base_height_m is None or canopy_base_height_m <= 0:
        return False, float("inf")

    critical_intensity = (
        0.01 * canopy_base_height_m * (460.0 + 25.9 * foliar_moisture_pct)
    ) ** 1.5

    return surface_fli_kw_m >= critical_intensity, critical_intensity
