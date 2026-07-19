"""
Teste end-to-end do pipeline de triagem.

Simula 3 ocorrências em condições típicas:
1. Pinhal (FM213) em Vila Real, vento NE moderado
2. Mato alto (FM233) em Castelo Branco, vento de leste forte
3. Eucaliptal jovem (FM224) em Aveiro, condições brandas
"""
import sys
import os
import warnings
sys.path.insert(0, "/home/claude/fogos_triage/src")
sys.path.insert(0, "/home/claude/fire_models_pt")

# silenciar warnings do fallback durante o teste
warnings.filterwarnings("ignore", category=RuntimeWarning)

from datetime import datetime

from fogos_triage.fuel_models import load_fuel_models_csv
from fogos_triage.schemas import Occurrence, TerrainConditions, WeatherConditions
from fogos_triage.triage import triage_occurrence
from fogos_triage.weather import derive_fire_weather


# Carregar modelos PT
fuel_models = load_fuel_models_csv("/home/claude/fire_models_pt/data/fuel_models_pt.csv")
print(f"Carregados {len(fuel_models)} modelos PT")
print()


def run_scenario(name, occurrence, terrain, raw_weather):
    """Corre um cenário e imprime resultado formatado."""
    # enriquecer meteo
    weather = derive_fire_weather(
        raw_weather,
        stand_height_m=terrain.stand_height_m or 0,
        canopy_cover_pct=terrain.canopy_cover_pct or 0,
        has_overstory=(terrain.canopy_cover_pct or 0) > 10,
    )

    result = triage_occurrence(occurrence, fuel_models, terrain, weather)

    print(f"=== {name} ===")
    print(f"Modelo combustível: {result.fuel_model_used}")
    print(f"Vento 10m: {weather.wind_speed_10m_ms:.1f} m/s "
          f"({weather.wind_speed_10m_ms*3.6:.1f} km/h)")
    print(f"WAF aplicado: {result.wind_adjustment_factor:.2f} "
          f"→ midflame {weather.wind_midflame_ms:.1f} m/s")
    print(f"Humidade fino morto: {weather.fuel_moisture_1h_pct:.1f}%")
    print(f"Declive: {terrain.slope_degrees:.0f}° ({terrain.slope_fraction*100:.0f}%)")
    print()
    print(f"Cenários:")
    for pred in result.predictions:
        print(f"  [{pred.scenario:7s}] ROS={pred.ros_m_per_min:6.1f} m/min  "
              f"FLI={pred.fireline_intensity_kw_m:7.0f} kW/m  "
              f"FL={pred.flame_length_m:5.2f} m  "
              f"tipo={pred.fire_type.value}")
    print()
    print(f"SEVERIDADE: categoria {result.priority.value} "
          f"(FLI central {result.priority_score:.0f} kW/m, EWE={result.central_prediction.is_ewe})")
    print(f"Capacidade de controlo: {result.central_prediction.control_description}")
    if result.notes:
        print(f"Notas: {'; '.join(result.notes)}")
    print()


# Cenário 1 — Pinhal de pinhal-bravo (M-PIN, FM227), Vila Real
# folhada de pinheiro com sub-bosque arbustivo
run_scenario(
    "Pinhal P. pinaster com sub-bosque (FM227), Vila Real, vento moderado",
    occurrence=Occurrence(
        external_id="vr-001",
        latitude=41.30,
        longitude=-7.74,
        started_at=datetime(2025, 8, 15, 14, 30),
        status="Em Curso",
        district="Vila Real",
        municipality="Vila Real",
        parish="Mateus",
        operatives_on_scene=18,
        vehicles_on_scene=5,
        aerial_on_scene=1,
    ),
    terrain=TerrainConditions(
        elevation_m=580,
        slope_fraction=0.27,  # 15°
        slope_degrees=15,
        aspect_degrees=180,  # virado a sul
        fuel_model_num=227,
        stand_height_m=18,
        canopy_cover_pct=65,
        canopy_base_height_m=4.0,
    ),
    raw_weather=WeatherConditions(
        timestamp=datetime(2025, 8, 15, 14, 30),
        temperature_c=32,
        relative_humidity_pct=28,
        wind_speed_10m_ms=6.5,  # ~23 km/h
        wind_gust_10m_ms=10,
        wind_direction_deg=45,  # NE
        precipitation_mm_24h=0,
        cloud_cover_pct=10,
    ),
)


# Cenário 2 — Mato alto V-MAa (FM233), Castelo Branco
# verão severo, vento forte de leste (lestada)
run_scenario(
    "Mato alto V-MAa (FM233), Castelo Branco, severo c/ lestada",
    occurrence=Occurrence(
        external_id="cb-002",
        latitude=39.83,
        longitude=-7.49,
        started_at=datetime(2025, 8, 20, 15, 0),
        status="Em Curso",
        district="Castelo Branco",
        municipality="Castelo Branco",
        parish="Almaceda",
        operatives_on_scene=42,
        vehicles_on_scene=12,
        aerial_on_scene=3,
    ),
    terrain=TerrainConditions(
        elevation_m=420,
        slope_fraction=0.36,  # 20°
        slope_degrees=20,
        aspect_degrees=270,  # virado a oeste
        fuel_model_num=233,
        stand_height_m=2.0,   # mato alto
        canopy_cover_pct=0,
        canopy_base_height_m=None,
    ),
    raw_weather=WeatherConditions(
        timestamp=datetime(2025, 8, 20, 15, 0),
        temperature_c=39,
        relative_humidity_pct=18,
        wind_speed_10m_ms=10,  # ~36 km/h, lestada
        wind_gust_10m_ms=15,
        wind_direction_deg=90,  # leste
        precipitation_mm_24h=0,
        cloud_cover_pct=0,
    ),
)


# Cenário 3 — Eucaliptal jovem (FM224), Aveiro
# condições brandas, mas potencial de evolução
run_scenario(
    "Eucaliptal jovem M-EUCd (FM224), Aveiro, condições brandas",
    occurrence=Occurrence(
        external_id="av-003",
        latitude=40.64,
        longitude=-8.50,
        started_at=datetime(2025, 7, 10, 12, 0),
        status="Em Resolução",
        district="Aveiro",
        municipality="Águeda",
        parish="Macinhata do Vouga",
        operatives_on_scene=8,
        vehicles_on_scene=2,
        aerial_on_scene=0,
    ),
    terrain=TerrainConditions(
        elevation_m=120,
        slope_fraction=0.09,  # 5°
        slope_degrees=5,
        aspect_degrees=90,
        fuel_model_num=224,
        stand_height_m=4,
        canopy_cover_pct=20,  # jovem, copa rala
        canopy_base_height_m=1.5,
    ),
    raw_weather=WeatherConditions(
        timestamp=datetime(2025, 7, 10, 12, 0),
        temperature_c=24,
        relative_humidity_pct=55,
        wind_speed_10m_ms=3.5,
        wind_gust_10m_ms=5.5,
        wind_direction_deg=315,  # NW (nortada atlântica)
        precipitation_mm_24h=2,
        cloud_cover_pct=40,
    ),
)
