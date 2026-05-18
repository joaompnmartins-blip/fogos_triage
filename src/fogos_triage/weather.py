"""
Módulo de meteorologia.

Tem duas funções principais:
1. fetch_weather() - vai buscar dados à Open-Meteo para uma coordenada
2. derive_fire_weather() - calcula humidades dos combustíveis e wind midflame
   a partir das condições atmosféricas + características da vegetação

Para a triagem rápida, usamos um modelo simples de fuel moisture baseado em
tabelas Rothermel 1983 (fine dead fuel moisture tables).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .schemas import WeatherConditions


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_open_meteo(
    latitude: float,
    longitude: float,
    hours_ahead: int = 5,
    client: Optional["httpx.AsyncClient"] = None,
) -> list[WeatherConditions]:
    """
    Vai buscar condições à Open-Meteo para as próximas N horas.
    Devolve uma lista de WeatherConditions horárias.

    Notas:
    - Usa o modelo 'best_match' que para Portugal é tipicamente ECMWF IFS
    - Inclui rajadas (gusts) para cenário de pior caso
    """
    if not HAS_HTTPX:
        raise ImportError("httpx é necessário para fetch_open_meteo")

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
            "wind_gusts_10m",
            "wind_direction_10m",
            "precipitation",
            "cloud_cover",
        ]),
        "models": "best_match",
        "forecast_days": 2,
        "timezone": "Europe/Lisbon",
        "wind_speed_unit": "ms",
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client:
            await client.aclose()

    hourly = data["hourly"]

    now = datetime.now()
    out: list[WeatherConditions] = []

    # Acumular precipitação 24h por janela móvel
    precip_arr = hourly["precipitation"]

    for i, time_str in enumerate(hourly["time"]):
        t = datetime.fromisoformat(time_str)
        if t < now:
            continue
        if len(out) >= hours_ahead:
            break

        precip_24h = sum(precip_arr[max(0, i-24):i+1])

        out.append(WeatherConditions(
            timestamp=t,
            temperature_c=hourly["temperature_2m"][i],
            relative_humidity_pct=hourly["relative_humidity_2m"][i],
            wind_speed_10m_ms=hourly["wind_speed_10m"][i],
            wind_gust_10m_ms=hourly["wind_gusts_10m"][i],
            wind_direction_deg=hourly["wind_direction_10m"][i],
            precipitation_mm_24h=precip_24h,
            cloud_cover_pct=hourly["cloud_cover"][i],
        ))

    return out


def estimate_fine_dead_moisture_pct(
    temperature_c: float,
    rh_pct: float,
    cloud_cover_pct: float,
    is_shaded: bool = False,
) -> float:
    """
    Estimativa da humidade do combustível fino morto (1h) em percentagem.

    Baseado nas tabelas de Rothermel 1983 (Fine Dead Fuel Moisture Tables).
    Simplificação prática: começa de uma reference moisture (Simard) e ajusta
    por exposição solar.

    Esta é uma aproximação. Para precisão real, considera implementar Nelson
    2000 ou o NFDRS Fine Fuel Moisture model que a Open-Meteo pode também
    fornecer diretamente (vale a pena verificar se há endpoint).
    """
    # Reference Fuel Moisture (Simard 1968): função de temperatura e RH
    if rh_pct <= 10:
        rfm = 0.03 + 0.2626 * rh_pct
    elif rh_pct <= 20:
        rfm = 2.22749 + 0.160107 * rh_pct - 0.014784 * temperature_c
    elif rh_pct <= 30:
        rfm = 21.06 + 0.005565 * rh_pct**2 - 0.00035 * rh_pct * temperature_c - 0.483199 * rh_pct
    elif rh_pct <= 40:
        rfm = 21.06 + 0.005565 * rh_pct**2 - 0.00035 * rh_pct * temperature_c - 0.483199 * rh_pct
    else:
        rfm = 21.06 + 0.005565 * rh_pct**2 - 0.00035 * rh_pct * temperature_c - 0.483199 * rh_pct
    rfm = max(1.0, min(rfm, 40.0))

    # Ajuste por exposição (sol vs sombra). Simplificado.
    # Em hora central com céu limpo e exposto ao sol, subtrair 1-3%.
    # Em sombra ou nublado, somar.
    sun_factor = (100.0 - cloud_cover_pct) / 100.0  # 0=nublado, 1=sol
    if not is_shaded and sun_factor > 0.5:
        rfm -= 2.0 * (sun_factor - 0.5) * 2.0  # max -2%
    elif is_shaded or sun_factor < 0.5:
        rfm += 1.0 * (1.0 - sun_factor)

    return max(2.0, min(rfm, 40.0))


def derive_fire_weather(
    wx: WeatherConditions,
    stand_height_m: float = 0.0,
    canopy_cover_pct: float = 0.0,
    has_overstory: bool = False,
) -> WeatherConditions:
    """
    Enriquece WeatherConditions com derivadas necessárias para o motor de fogo:
    - vento midflame (após aplicar WAF)
    - humidades dos combustíveis 1h, 10h, 100h
    - humidades dos combustíveis vivos (sazonal, pode vir de outro modelo)

    O WAF (Wind Adjustment Factor) vem de Albini & Baughman 1979 e depende de:
    - presença de coberto (overstory)
    - altura da vegetação
    - cobertura de copas

    Tabelas típicas (Andrews 2012, BehavePlus):
    - Sem coberto, vegetação curta (<3 ft): WAF ≈ 0.4
    - Sem coberto, vegetação alta (>6 ft): WAF ≈ 0.5
    - Com coberto fechado (>50% cover): WAF ≈ 0.1-0.2
    - Com coberto aberto: WAF ≈ 0.2-0.3
    """
    # Wind adjustment factor (simplificado)
    if has_overstory and canopy_cover_pct > 50:
        waf = 0.1 + 0.05 * max(0, (stand_height_m - 5) / 20)
    elif has_overstory and canopy_cover_pct > 20:
        waf = 0.25
    elif stand_height_m > 1.8:
        waf = 0.5
    else:
        waf = 0.4

    wind_midflame = wx.wind_speed_10m_ms * waf

    # Humidades dos combustíveis mortos
    m_1h = estimate_fine_dead_moisture_pct(
        wx.temperature_c, wx.relative_humidity_pct, wx.cloud_cover_pct,
        is_shaded=has_overstory,
    )
    m_10h = m_1h + 1.0   # convenção: 10h é ~1% acima de 1h em condições estáveis
    m_100h = m_1h + 2.0  # idem para 100h

    # Live fuel moisture — depende da fenologia
    # Para verão em Portugal, valores típicos:
    # herbáceo: 60-80% (curado) ou 100-150% (verde)
    # lenhoso: 70-100%
    # Esta estimativa é GROSSEIRA — em produção vem de um índice fenológico
    # (NDVI/LFMC do Sentinel-2 ou similar)
    m_live_h = 60.0  # assume curado em pico de verão
    m_live_w = 80.0

    return WeatherConditions(
        timestamp=wx.timestamp,
        temperature_c=wx.temperature_c,
        relative_humidity_pct=wx.relative_humidity_pct,
        wind_speed_10m_ms=wx.wind_speed_10m_ms,
        wind_gust_10m_ms=wx.wind_gust_10m_ms,
        wind_direction_deg=wx.wind_direction_deg,
        precipitation_mm_24h=wx.precipitation_mm_24h,
        cloud_cover_pct=wx.cloud_cover_pct,
        wind_midflame_ms=wind_midflame,
        fuel_moisture_1h_pct=m_1h,
        fuel_moisture_10h_pct=m_10h,
        fuel_moisture_100h_pct=m_100h,
        fuel_moisture_live_h_pct=m_live_h,
        fuel_moisture_live_w_pct=m_live_w,
    )
