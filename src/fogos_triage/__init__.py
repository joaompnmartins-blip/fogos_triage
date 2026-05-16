"""
fogos_triage — triagem rápida de fogos para apoio à decisão ANEPC.
"""
from .fuel_models import FuelModelPT, load_fuel_models_csv, load_fuel_models_fmd
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    Occurrence,
    Priority,
    TerrainConditions,
    TriageResult,
    WeatherConditions,
)
from .triage import compute_priority, triage_occurrence

__version__ = "0.1.0"
__all__ = [
    "FuelModelPT",
    "load_fuel_models_csv",
    "load_fuel_models_fmd",
    "FireBehaviorPrediction",
    "FireType",
    "Occurrence",
    "Priority",
    "TerrainConditions",
    "TriageResult",
    "WeatherConditions",
    "compute_priority",
    "triage_occurrence",
]
