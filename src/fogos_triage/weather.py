"""
Módulo de meteorologia.

Tem duas funções principais:
1. fetch_weather() - vai buscar dados à Open-Meteo para uma coordenada
2. derive_fire_weather() - calcula humidades dos combustíveis e wind midflame
   a partir das condições atmosféricas + características da vegetação

Humidades dos combustíveis mortos: equações Simard 1968 (temperatura em
Fahrenheit, limiares de RH: ≤10%, 11-50%, >50%).

Humidades dos combustíveis vivos: regressões Yebra 2007 a partir de NDVI
(VNP09GA) e LST (VNP21A1D) via Google Earth Engine, com fallback sazonal.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .schemas import WeatherConditions

# ---------------------------------------------------------------------------
# Google Earth Engine — inicialização lazy e thread-safe
# ---------------------------------------------------------------------------

_ee_initialized: bool = False
_ee_init_attempted: bool = False


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

    Equações de Simard 1968 (Reference Fuel Moisture). A temperatura deve
    ser convertida para Fahrenheit conforme o artigo original.
    Limiares de RH: ≤10%, 11–50%, >50%.
    """
    T_f = temperature_c * 9.0 / 5.0 + 32.0  # Celsius → Fahrenheit

    if rh_pct <= 10:
        rfm = 0.03229 + 0.281073 * rh_pct - 0.000578 * T_f
    elif rh_pct <= 50:
        rfm = 2.22749 + 0.160107 * rh_pct - 0.014784 * T_f
    else:
        rfm = 21.0606 + 0.005565 * rh_pct**2 - 0.0003505 * rh_pct * T_f - 0.483199 * rh_pct

    rfm = max(1.0, min(rfm, 40.0))

    # Ajuste por exposição solar
    sun_factor = (100.0 - cloud_cover_pct) / 100.0
    if not is_shaded and sun_factor > 0.5:
        rfm -= 2.0 * (sun_factor - 0.5) * 2.0
    elif is_shaded or sun_factor < 0.5:
        rfm += 1.0 * (1.0 - sun_factor)

    return max(2.0, min(rfm, 40.0))


# ---------------------------------------------------------------------------
# Live Fuel Moisture via VIIRS/GEE — Yebra 2007
# ---------------------------------------------------------------------------

def _init_ee() -> bool:
    """Inicializa o Earth Engine com service account. True se bem-sucedido."""
    global _ee_initialized, _ee_init_attempted
    if _ee_initialized:
        return True
    if _ee_init_attempted:
        return False
    _ee_init_attempted = True

    service_account = os.environ.get('GEE_SERVICE_ACCOUNT')
    key_file = os.environ.get('GEE_KEY_FILE')
    key_json = os.environ.get('GEE_KEY_JSON')

    if not service_account or (not key_file and not key_json):
        return False

    try:
        import ee

        if key_file:
            creds = ee.ServiceAccountCredentials(service_account, key_file)
        else:
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False
            ) as fh:
                fh.write(key_json)
                tmp_path = fh.name
            creds = ee.ServiceAccountCredentials(service_account, tmp_path)

        ee.Initialize(creds)
        _ee_initialized = True
        return True
    except Exception:
        return False


def _viirs_fmc_sync(
    latitude: float,
    longitude: float,
    date: datetime,
) -> Optional[tuple[float, float]]:
    """
    Estima humidade dos combustíveis vivos por VIIRS + Yebra 2007.

    NDVI: VNP09GA (NASA/VIIRS/002/VNP09GA), bandas I1/I2.
    LST : VNP21A1D (NASA/VIIRS/002/VNP21A1D), banda LST_1KM.
    Janela temporal: 16 dias antes de `date`.

    Correção sazonal para anos Normais (Yebra 2007):
      FDp (herbáceo): (sin(1.5π(DJ + DJ^0.5) / 365))^6 × 1.5
      FDm (lenhoso) : ((sin(1.6π × DJ / 365))^2 + 1) × 0.5

    Regressões Yebra 2007 Tabela 1:
      FMC_G = 27.95 + 115.51×FDp + 331.86×NDVI − 1.194×Ts_C
      FMC_S =  8.73 + 125.87×FDm +  40.79×NDVI − 0.2294×Ts_C

    Devolve (fmc_grass_pct, fmc_shrub_pct) ou None.
    """
    if not _init_ee():
        return None

    try:
        import ee

        point = ee.Geometry.Point([longitude, latitude])
        end_date = date.strftime('%Y-%m-%d')
        start_date = (date - timedelta(days=16)).strftime('%Y-%m-%d')

        # NDVI — bandas I1 (red, 640nm) e I2 (NIR, 865nm)
        # Escala de reflectância (0.0001) cancela no rácio
        vnp09 = (
            ee.ImageCollection('NASA/VIIRS/002/VNP09GA')
            .filterDate(start_date, end_date)
            .filterBounds(point)
            .select(['SurfReflect_I1', 'SurfReflect_I2'])
            .mean()
        )
        i1 = vnp09.select('SurfReflect_I1')
        i2 = vnp09.select('SurfReflect_I2')
        ndvi_img = i2.subtract(i1).divide(i2.add(i1)).rename('ndvi')

        # LST — escala 0.02 K/DN → converter para °C
        vnp21 = (
            ee.ImageCollection('NASA/VIIRS/002/VNP21A1D')
            .filterDate(start_date, end_date)
            .filterBounds(point)
            .select(['LST_1KM'])
            .mean()
        )
        lst_img = vnp21.multiply(0.02).subtract(273.15).rename('lst_c')

        vals = (
            ndvi_img.addBands(lst_img)
            .reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=point,
                scale=1000,
                maxPixels=1,
            )
            .getInfo()
        )

        ndvi = vals.get('ndvi')
        lst_c = vals.get('lst_c')
        if ndvi is None or lst_c is None:
            return None

        # Correção sazonal — anos Normais (Yebra 2007 Eq. 3 e 4)
        dj = float(date.timetuple().tm_yday)
        fdp = (math.sin(1.5 * math.pi * (dj + dj**0.5) / 365)) ** 6 * 1.5
        fdm = ((math.sin(1.6 * math.pi * dj / 365)) ** 2 + 1) * 0.5

        fmc_grass = 27.95 + 115.51 * fdp + 331.86 * ndvi - 1.194 * lst_c
        fmc_shrub = 8.73 + 125.87 * fdm + 40.79 * ndvi - 0.2294 * lst_c

        return (
            float(max(0.0, min(250.0, fmc_grass))),
            float(max(0.0, min(250.0, fmc_shrub))),
        )
    except Exception:
        return None


async def fetch_live_fmc_viirs(
    latitude: float,
    longitude: float,
    date: datetime,
) -> Optional[tuple[float, float]]:
    """
    Estima humidade dos combustíveis vivos via VIIRS/GEE (Yebra 2007).

    Devolve (fmc_herbáceo_pct, fmc_lenhoso_pct) ou None se GEE não
    disponível. Requer GEE_SERVICE_ACCOUNT e GEE_KEY_FILE (ou GEE_KEY_JSON).
    Executa em thread-executor para não bloquear o event loop.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _viirs_fmc_sync, latitude, longitude, date
    )


def derive_fire_weather(
    wx: WeatherConditions,
    stand_height_m: float = 0.0,
    canopy_cover_pct: float = 0.0,
    has_overstory: bool = False,
    live_h_pct: Optional[float] = None,
    live_w_pct: Optional[float] = None,
) -> WeatherConditions:
    """
    Enriquece WeatherConditions com derivadas necessárias para o motor de fogo:
    - vento midflame (após aplicar WAF)
    - humidades dos combustíveis 1h, 10h, 100h (Simard 1968)
    - humidades dos combustíveis vivos (Yebra 2007 via GEE, ou fallback sazonal)

    m_10h  = 1.28 × m_1h        (Rothermel 1972)
    m_100h = m_10h + 1.0%

    live_h_pct / live_w_pct: se fornecidos (de fetch_live_fmc_viirs), usados
    directamente; caso contrário, fallback conservador (Portugal, verão).

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

    # Humidades dos combustíveis mortos (Simard 1968 + Rothermel 1972)
    m_1h = estimate_fine_dead_moisture_pct(
        wx.temperature_c, wx.relative_humidity_pct, wx.cloud_cover_pct,
        is_shaded=has_overstory,
    )
    m_10h = 1.28 * m_1h
    m_100h = m_10h + 1.0

    # Live fuel moisture — de GEE/VIIRS se disponível, senão fallback
    m_live_h = live_h_pct if live_h_pct is not None else 60.0
    m_live_w = live_w_pct if live_w_pct is not None else 80.0

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
