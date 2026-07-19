"""
fogos_triage — triagem rápida de fogos para apoio à decisão ANEPC.
"""
from .fuel_models import FuelModelPT, load_fuel_models_csv, load_fuel_models_fmd
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    Occurrence,
    SeverityCategory,
    TerrainConditions,
    TriageResult,
    WeatherConditions,
)
from .severity import SEVERITY_TABLE, classify_severity, is_ewe, severity_info
from .triage import compute_priority, triage_occurrence

__version__ = "0.1.0"
__all__ = [
    "FuelModelPT",
    "load_fuel_models_csv",
    "load_fuel_models_fmd",
    "FireBehaviorPrediction",
    "FireType",
    "Occurrence",
    "SeverityCategory",
    "TerrainConditions",
    "TriageResult",
    "WeatherConditions",
    "SEVERITY_TABLE",
    "classify_severity",
    "is_ewe",
    "severity_info",
    "compute_priority",
    "triage_occurrence",
]
