"""
Adaptadores entre o schema da fogos.pt e os schemas do nosso domínio.

Conversões:
- FogosFire (API) → Occurrence (domínio)
- FogosWeatherSnapshot (API) → WeatherConditions (domínio)
"""
from __future__ import annotations

from datetime import datetime

from ..ingestion.fogos_client import FogosFire, FogosWeatherSnapshot
from ..schemas import Occurrence, WeatherConditions


def fogos_to_occurrence(fire: FogosFire) -> Occurrence:
    """Converte FogosFire → Occurrence."""
    return Occurrence(
        external_id=fire.fire_id,
        latitude=fire.latitude,
        longitude=fire.longitude,
        started_at=fire.started_at,
        status=fire.status_name,
        district=fire.district,
        municipality=fire.municipality,
        parish=fire.parish,
        locality=fire.locality,
        operatives_on_scene=fire.operatives,
        vehicles_on_scene=fire.vehicles,
        aerial_on_scene=fire.aerial + fire.heli_fight + fire.plane_fight,
    )


def fogos_weather_to_conditions(
    w: FogosWeatherSnapshot,
    fallback_timestamp: datetime,
) -> WeatherConditions:
    """
    Converte FogosWeatherSnapshot (IPMA) → WeatherConditions.

    Notas:
    - A meteo IPMA é da estação mais próxima, não exatamente no ponto.
      A distância está em station_distance_km — se >15km, marcar como menos fiável.
    - Não temos gust nem cloud_cover do IPMA → estimamos a partir de wind_speed.
    - precipitação 24h não vem no payload IPMA, só precAcumulada instantânea.
    """
    # Estimativa de rajada: tipicamente 1.4-1.6x do vento sustentado
    wind_ms = w.wind_speed_ms or 0.0
    gust_estimate = wind_ms * 1.5 if wind_ms > 0 else 0.0

    # Cloud cover: estimativa grosseira a partir de radiação (se disponível)
    # Radiação típica de céu limpo no verão em PT: ~3500-4000 W/m²·h equiv.
    # Esta heurística é fraca — substituir por Open-Meteo se preciso.
    cloud = 50.0  # default
    if w.radiation is not None and w.radiation > 0:
        # >3500 → céu limpo; <1500 → muito nublado
        cloud = max(0.0, min(100.0, 100.0 * (1.0 - (w.radiation - 1500) / 2500)))

    return WeatherConditions(
        timestamp=w.timestamp or fallback_timestamp,
        temperature_c=w.temperature_c or 20.0,
        relative_humidity_pct=w.humidity_pct or 50.0,
        wind_speed_10m_ms=wind_ms,
        wind_gust_10m_ms=gust_estimate,
        wind_direction_deg=w.wind_direction_deg or 0.0,
        precipitation_mm_24h=w.precipitation_mm or 0.0,
        cloud_cover_pct=cloud,
    )
