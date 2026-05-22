"""
Motor de fogo de superfície — Rothermel 1972 implementação directa.

Calcula ROS, FLI, comprimento de chama e direcção de máxima propagação
com as equações Rothermel 1972 + Byram 1959, mantendo as categorias
morto e vivo separadas ao longo do cálculo (equivalente BehavePlus).

Pontos de diferença face à abordagem single-fuel:
- η_M_dead e η_M_live calculados separadamente antes de somar I_R
- φ_w usa β/β_op (correcto) em vez de β
- Direcção de propagação por soma vectorial de φ_w e φ_s
"""
from __future__ import annotations

import math
import warnings
from typing import Optional

from .fuel_models import FuelModelPT
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    TerrainConditions,
    WeatherConditions,
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

    # Dynamic fuel transfer (Andrews 2018, Table 7)
    # T = −1.11·M + 1.33, clipped to [0, 1]; fully cured at M=0.30, green at M=1.20
    if fm.is_dynamic and fm.load_live_h > 0:
        f_t      = max(0.0, min(1.0, -1.11 * moist_live_h + 1.33))
        w_tr     = fm.load_live_h * f_t           # transferred load, preserves live_h SAV
        w_live_h = fm.load_live_h * (1.0 - f_t)
    else:
        w_tr     = 0.0
        w_live_h = fm.load_live_h

    # Áreas de superfície por classe: A_i = sigma_i * w_i / rho_p
    # Transferred herb keeps fm.sav_live_h (BehavePlus approach, not NFDRS)
    A_1h   = fm.sav_1h     * fm.load_1h  / rho_p
    A_tr   = fm.sav_live_h * w_tr        / rho_p if w_tr > 0 else 0.0
    A_10h  = sav_10h       * fm.load_10h / rho_p
    A_100h = sav_100h      * fm.load_100h / rho_p
    A_lh   = fm.sav_live_h * w_live_h   / rho_p if w_live_h > 0 else 0.0
    A_lw   = fm.sav_live_w * fm.load_live_w / rho_p if fm.load_live_w > 0 else 0.0

    A_dead = A_1h + A_tr + A_10h + A_100h
    A_live = A_lh + A_lw
    A_total = A_dead + A_live

    if A_total <= 0:
        return None

    # Frações de área dentro de cada categoria
    f_1h   = A_1h   / A_dead if A_dead > 0 else 0.0
    f_tr   = A_tr   / A_dead if A_dead > 0 else 0.0
    f_10h  = A_10h  / A_dead if A_dead > 0 else 0.0
    f_100h = A_100h / A_dead if A_dead > 0 else 0.0
    f_lh   = A_lh   / A_live if A_live > 0 else 0.0
    f_lw   = A_lw   / A_live if A_live > 0 else 0.0

    # Frações entre categorias
    f_dead = A_dead / A_total
    f_live = A_live / A_total

    # SAV característico
    sigma_dead = (f_1h * fm.sav_1h + f_tr * fm.sav_live_h
                  + f_10h * sav_10h
                  + f_100h * sav_100h)
    sigma_live = (f_lh * fm.sav_live_h + f_lw * fm.sav_live_w) if A_live > 0 else 0.0
    sigma_char = f_dead * sigma_dead + f_live * sigma_live

    # Carga total (com transfer aplicado)
    w_total = (fm.load_1h + w_tr + fm.load_10h + fm.load_100h
               + w_live_h + fm.load_live_w)

    # Humidade ponderada por área (mortos e vivos separadamente)
    # transferred herb uses dead 1h moisture
    m_dead = (((f_1h + f_tr) * moist_1h + f_10h * moist_10h + f_100h * moist_100h)
              if A_dead > 0 else 0.0)
    m_live = ((f_lh * moist_live_h + f_lw * moist_live_w)
              if A_live > 0 else 0.0)

    # Humidade efetiva ponderada (combinando mortos+vivos por f_dead/f_live)
    m_eff = f_dead * m_dead + f_live * m_live

    # Humidade de extinção dos vivos (Albini 1976)
    # K_dead=138, K_live=500 (Andrews 2018, Table 6a)
    if A_live > 0 and fm.moist_ext_dead > 0:
        sum_dead_we = fm.load_1h * math.exp(-138.0 / fm.sav_1h) if fm.sav_1h > 0 else 0.0
        if w_tr > 0 and fm.sav_live_h > 0:
            sum_dead_we += w_tr * math.exp(-138.0 / fm.sav_live_h)
        sum_dead_we += fm.load_10h * math.exp(-138.0 / sav_10h)
        sum_dead_we += fm.load_100h * math.exp(-138.0 / sav_100h)
        sum_live_we = 0.0
        if w_live_h > 0 and fm.sav_live_h > 0:
            sum_live_we += w_live_h * math.exp(-500.0 / fm.sav_live_h)
        if fm.load_live_w > 0 and fm.sav_live_w > 0:
            sum_live_we += fm.load_live_w * math.exp(-500.0 / fm.sav_live_w)
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
    Rothermel 1972 surface fire com categorias morto/vivo separadas (BehavePlus-equivalent).
    η_M_dead e η_M_live calculados independentemente antes de somar I_R.
    """
    if fm.is_empty:
        return _zero_prediction(scenario, FireType.NO_BURN)

    # humidades em fração
    m_1h  = (weather.fuel_moisture_1h_pct  or 8.0)   / 100.0
    m_10h = (weather.fuel_moisture_10h_pct or 9.0)   / 100.0
    m_100h= (weather.fuel_moisture_100h_pct or 10.0) / 100.0
    m_lh  = (weather.fuel_moisture_live_h_pct or 100.0) / 100.0
    m_lw  = (weather.fuel_moisture_live_w_pct or 100.0) / 100.0

    ros_m_min, fi_kw_m, phi_w, phi_s, I_R, sigma, effective_wind_ms = _rothermel_direct(
        fm, m_1h, m_10h, m_100h, m_lh, m_lw,
        wind_midflame_ms=weather.wind_midflame_ms or 0.0,
        slope_degrees=terrain.slope_degrees,
    )

    if ros_m_min <= 0 and fi_kw_m <= 0:
        return _zero_prediction(scenario, FireType.NO_BURN)

    flame_length_m = 0.0775 * fi_kw_m ** 0.46 if fi_kw_m > 0 else 0.0

    # heat per unit area e reaction intensity derivados de I_R e ROS
    t_r = 384.0 / sigma if sigma > 0 else 0.0
    hpa_kj_m2 = I_R * t_r * 11.357          # I_R [BTU/ft²/min] × t_r [min] → BTU/ft² → kJ/m²
    ri_kw_m2 = I_R * 0.1893                  # BTU/ft²/min → kW/m²

    direction = _max_spread_direction_from_phi(
        wind_direction_deg=weather.wind_direction_deg,
        aspect_degrees=terrain.aspect_degrees,
        phi_w=phi_w,
        phi_s=phi_s,
    )

    return FireBehaviorPrediction(
        scenario=scenario,
        ros_m_per_min=ros_m_min,
        fireline_intensity_kw_m=fi_kw_m,
        flame_length_m=flame_length_m,
        heat_per_unit_area_kj_m2=hpa_kj_m2,
        reaction_intensity_kw_m2=ri_kw_m2,
        direction_max_spread_deg=direction,
        effective_wind_ms=effective_wind_ms,
        fire_type=FireType.SURFACE,
    )


def _rothermel_direct(
    fm: FuelModelPT,
    m_1h: float, m_10h: float, m_100h: float,
    m_live_h: float, m_live_w: float,
    wind_midflame_ms: float,
    slope_degrees: float,
) -> tuple[float, float, float, float, float, float, float]:
    """
    Rothermel 1972 surface fire — implementação directa com η_M_dead/live separados.

    Devolve (ros_m_per_min, fi_kw_m, phi_w, phi_s, I_R_btu_ft2_min, sigma_ftinv, effective_wind_ms).
    Humidades em fração (0-1).
    """
    rho_p = 32.0      # lb/ft³ — densidade da partícula
    S_T   = 0.0555    # conteúdo mineral total (Rothermel default)
    S_e   = 0.01      # mineral efetivo
    sav_10h  = 109.0  # 1/ft — fixo (Rothermel 1972)
    sav_100h = 30.0

    # --- Dynamic fuel transfer (Andrews 2018, Table 7) ---
    # T = −1.11·M + 1.33, clipped to [0, 1]; fully cured at M=0.30, green at M=1.20
    if fm.is_dynamic and fm.load_live_h > 0:
        f_t      = max(0.0, min(1.0, -1.11 * m_live_h + 1.33))
        w_tr     = fm.load_live_h * f_t           # transferred load, preserves live_h SAV
        w_live_h = fm.load_live_h * (1.0 - f_t)
    else:
        w_tr     = 0.0
        w_live_h = fm.load_live_h

    # --- Áreas de superfície ---
    # Transferred herb keeps fm.sav_live_h (BehavePlus approach, not NFDRS)
    A_1h   = fm.sav_1h     * fm.load_1h  / rho_p
    A_tr   = fm.sav_live_h * w_tr        / rho_p if w_tr > 0 else 0.0
    A_10h  = sav_10h       * fm.load_10h / rho_p
    A_100h = sav_100h      * fm.load_100h / rho_p
    A_lh   = fm.sav_live_h * w_live_h   / rho_p if w_live_h > 0 else 0.0
    A_lw   = fm.sav_live_w * fm.load_live_w / rho_p if fm.load_live_w > 0 else 0.0

    A_dead  = A_1h + A_tr + A_10h + A_100h
    A_live  = A_lh + A_lw
    A_total = A_dead + A_live
    if A_total <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0

    # fracções dentro de cada categoria
    f_1h   = A_1h   / A_dead if A_dead > 0 else 0.0
    f_tr   = A_tr   / A_dead if A_dead > 0 else 0.0
    f_10h  = A_10h  / A_dead if A_dead > 0 else 0.0
    f_100h = A_100h / A_dead if A_dead > 0 else 0.0
    f_lh   = A_lh   / A_live if A_live > 0 else 0.0
    f_lw   = A_lw   / A_live if A_live > 0 else 0.0
    f_dead = A_dead / A_total
    f_live = A_live / A_total

    # --- SAV característico (eq 27) ---
    sigma_dead = (f_1h * fm.sav_1h + f_tr * fm.sav_live_h
                  + f_10h * sav_10h + f_100h * sav_100h)
    sigma_live = (f_lh * fm.sav_live_h + f_lw * fm.sav_live_w) if A_live > 0 else 0.0
    sigma = f_dead * sigma_dead + f_live * sigma_live
    if sigma <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0

    # --- Geometria do leito ---
    w_dead  = fm.load_1h + w_tr + fm.load_10h + fm.load_100h
    w_live  = w_live_h + fm.load_live_w
    w_total = w_dead + w_live
    rho_b   = w_total / fm.depth if fm.depth > 0 else 0.0
    beta    = max(1e-6, rho_b / rho_p)

    # --- Velocidade de reação Γ' (eq 36-38) ---
    beta_op    = 3.348 * sigma ** (-0.8189)
    beta_ratio = beta / beta_op
    sigma_15   = sigma ** 1.5
    gamma_max  = sigma_15 / (495.0 + 0.0594 * sigma_15)
    A_c        = 133.0 * sigma ** (-0.7913)
    gamma      = gamma_max * (beta_ratio ** A_c) * math.exp(A_c * (1.0 - beta_ratio))

    # --- Humidades ponderadas por categoria ---
    # transferred herb uses dead 1h moisture
    m_dead = (f_1h + f_tr) * m_1h + f_10h * m_10h + f_100h * m_100h
    m_live = (f_lh * m_live_h + f_lw * m_live_w) if A_live > 0 else 0.0

    # M_x dos vivos (Albini 1976) — K_dead=138, K_live=500 (Andrews 2018, Table 6a)
    M_x_dead = fm.moist_ext_dead
    M_x_live = M_x_dead
    if A_live > 0 and M_x_dead > 0:
        W_d = fm.load_1h * math.exp(-138.0 / fm.sav_1h) if fm.sav_1h > 0 else 0.0
        if w_tr > 0 and fm.sav_live_h > 0:
            W_d += w_tr * math.exp(-138.0 / fm.sav_live_h)
        W_d += fm.load_10h * math.exp(-138.0 / sav_10h)
        W_d += fm.load_100h * math.exp(-138.0 / sav_100h)
        W_l = sum(w * math.exp(-500.0 / s) for w, s in [
            (w_live_h, fm.sav_live_h), (fm.load_live_w, fm.sav_live_w)
        ] if w > 0 and s > 0)
        if W_l > 0:
            M_x_live = max(2.9 * (W_d / W_l) * (1.0 - m_1h / M_x_dead) - 0.226, M_x_dead)

    # --- η_M separados por categoria (eq 29 — ponto central da melhoria) ---
    def _eta_M(m: float, Mx: float) -> float:
        if Mx <= 0 or m >= Mx:
            return 0.0
        r = m / Mx
        return max(0.0, 1.0 - 2.59 * r + 5.11 * r**2 - 3.52 * r**3)

    eta_M_dead = _eta_M(m_dead, M_x_dead)
    eta_M_live = _eta_M(m_live, M_x_live) if A_live > 0 else 0.0

    # η_s — amortecimento mineral (eq 56)
    eta_s = 0.174 * S_e ** (-0.19)

    # --- Intensidade de reação (Andrews 2018, Table 6b) — cargas ponderadas por área ---
    wn_dead = f_1h * fm.load_1h + f_tr * w_tr + f_10h * fm.load_10h + f_100h * fm.load_100h
    wn_live = (f_lh * w_live_h + f_lw * fm.load_live_w) if A_live > 0 else 0.0
    I_R_dead = gamma * wn_dead * (1.0 - S_T) * fm.heat_dead * eta_M_dead * eta_s
    I_R_live = (gamma * wn_live * (1.0 - S_T) * fm.heat_live * eta_M_live * eta_s
                if A_live > 0 else 0.0)
    I_R = I_R_dead + I_R_live
    if I_R <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, sigma, 0.0

    # --- Propagating flux ratio ξ (eq 42) ---
    xi = (math.exp((0.792 + 0.681 * sigma ** 0.5) * (beta + 0.1))
          / (192.0 + 0.2595 * sigma))

    # --- φ_w e φ_s (eq 47, 51) — β/β_op corrigido ---
    wind_ftmin = wind_midflame_ms * 196.85
    B = 0.02526 * sigma ** 0.54
    C = 7.47  * math.exp(-0.133  * sigma ** 0.55)
    E = 0.715 * math.exp(-3.59e-4 * sigma)
    phi_w = C * (wind_ftmin ** B) * (beta_ratio ** (-E)) if wind_ftmin > 0 else 0.0
    phi_s = (5.275 * beta ** (-0.3) * math.tan(math.radians(slope_degrees)) ** 2
             if slope_degrees > 0 else 0.0)

    # --- Heat sink por classe (Andrews 2018, Table 6c) ---
    eps_Qig_dead = 0.0
    if fm.sav_1h > 0:
        eps_Qig_dead += f_1h * math.exp(-138.0 / fm.sav_1h) * (250.0 + 1116.0 * m_1h)
    if w_tr > 0 and fm.sav_live_h > 0:
        eps_Qig_dead += f_tr * math.exp(-138.0 / fm.sav_live_h) * (250.0 + 1116.0 * m_1h)
    eps_Qig_dead += f_10h  * math.exp(-138.0 / sav_10h)  * (250.0 + 1116.0 * m_10h)
    eps_Qig_dead += f_100h * math.exp(-138.0 / sav_100h) * (250.0 + 1116.0 * m_100h)
    eps_Qig_live = 0.0
    if A_live > 0:
        if fm.sav_live_h > 0:
            eps_Qig_live += f_lh * math.exp(-138.0 / fm.sav_live_h) * (250.0 + 1116.0 * m_live_h)
        if fm.sav_live_w > 0:
            eps_Qig_live += f_lw * math.exp(-138.0 / fm.sav_live_w) * (250.0 + 1116.0 * m_live_w)
    eps_Qig = f_dead * eps_Qig_dead + f_live * eps_Qig_live

    # --- ROS (eq 52) ---
    denom = rho_b * eps_Qig
    ros_ftmin = I_R * xi * (1.0 + phi_w + phi_s) / denom if denom > 0 else 0.0
    ros_m_min = max(0.0, ros_ftmin * 0.3048)

    # --- FLI Byram (I_B = I_R × t_r × R) ---
    t_r      = 384.0 / sigma
    fi_kw_m  = max(0.0, I_R * t_r * ros_ftmin * 0.05767)

    # --- Vento efetivo combinado vento+declive (Andrews 2018, §4.1) ---
    # U_E = (φ_E · (β/β_op)^E / C)^(1/B), convertido de ft/min para m/s
    phi_E = phi_w + phi_s
    if phi_E > 0:
        effective_wind_ms = ((phi_E * beta_ratio ** E / C) ** (1.0 / B)) / 196.85
    else:
        effective_wind_ms = wind_midflame_ms

    return ros_m_min, fi_kw_m, phi_w, phi_s, I_R, sigma, effective_wind_ms


def _max_spread_direction_from_phi(
    wind_direction_deg: float,
    aspect_degrees: float,
    phi_w: float,
    phi_s: float,
) -> float:
    """
    Azimute de máxima propagação por soma vectorial de φ_w e φ_s.
    Usa os valores já calculados em _rothermel_direct — sem recalcular β.
    """
    if phi_w + phi_s < 1e-6:
        return 0.0

    wind_az  = (wind_direction_deg + 180.0) % 360.0  # downwind
    slope_az = (aspect_degrees    + 180.0) % 360.0   # upslope

    rx = math.sin(math.radians(wind_az))  * phi_w + math.sin(math.radians(slope_az)) * phi_s
    ry = math.cos(math.radians(wind_az))  * phi_w + math.cos(math.radians(slope_az)) * phi_s

    if abs(rx) < 1e-9 and abs(ry) < 1e-9:
        return wind_az if phi_w >= phi_s else slope_az
    return math.degrees(math.atan2(rx, ry)) % 360.0


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
