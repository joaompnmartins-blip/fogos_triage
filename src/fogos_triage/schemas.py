"""
Esquemas de domínio do sistema de triagem.

Representam uma ocorrência, condições meteorológicas, e o resultado da triagem.
São intencionalmente leves (dataclasses) — podem ser convertidos para Pydantic
quando integrarmos com FastAPI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Priority(str, Enum):
    """Categorias de prioridade operacional."""
    P1_CRITICAL = "P1"   # ação imediata, risco elevado
    P2_HIGH = "P2"       # vigilância apertada, recursos a postos
    P3_WATCH = "P3"      # monitorizar evolução
    P4_CONTROLLED = "P4" # sob controlo ou baixo risco


class FireType(str, Enum):
    """Tipo de fogo previsto."""
    SURFACE = "surface"
    TORCHING = "torching"     # passive crown fire
    CROWNING = "crowning"     # active crown fire
    NO_BURN = "no_burn"       # não combustível ou apagado


@dataclass
class WeatherConditions:
    """
    Condições meteorológicas num ponto e tempo.
    Provem do Open-Meteo já interpretadas (vento midflame, humidades dos combustíveis).
    """
    timestamp: datetime
    temperature_c: float
    relative_humidity_pct: float           # 0-100
    wind_speed_10m_ms: float
    wind_gust_10m_ms: float
    wind_direction_deg: float              # 0-360, direção de onde vem
    precipitation_mm_24h: float
    cloud_cover_pct: float

    # Derivadas — calculadas pelo módulo de meteorologia
    wind_midflame_ms: Optional[float] = None  # após aplicar WAF
    fuel_moisture_1h_pct: Optional[float] = None
    fuel_moisture_10h_pct: Optional[float] = None
    fuel_moisture_100h_pct: Optional[float] = None
    fuel_moisture_live_h_pct: Optional[float] = None
    fuel_moisture_live_w_pct: Optional[float] = None


@dataclass
class TerrainConditions:
    """
    Condições do terreno num ponto.
    Provem do lookup nos rasters da Landscape File.
    """
    elevation_m: float
    slope_fraction: float          # tan(ângulo)
    slope_degrees: float
    aspect_degrees: float          # 0-360, azimute para onde olha a encosta
    fuel_model_num: int            # ex: 213, 223, 233...

    # Parâmetros de coberto (para crown fire e wind adjustment factor)
    stand_height_m: Optional[float] = None      # altura do povoamento
    canopy_cover_pct: Optional[float] = None    # cobertura de copas 0-100
    canopy_base_height_m: Optional[float] = None  # altura da base da copa
    canopy_bulk_density_kg_m3: Optional[float] = None  # se disponível


@dataclass
class Occurrence:
    """
    Uma ocorrência ativa de incêndio (vinda da fogos.pt).
    """
    external_id: str               # id da ANEPC/fogos.pt
    latitude: float
    longitude: float
    started_at: datetime
    status: str                    # "Despacho", "Em Curso", "Em Resolução", etc.
    district: str
    municipality: str
    parish: str
    locality: Optional[str] = None

    # Recursos
    operatives_on_scene: int = 0
    vehicles_on_scene: int = 0
    aerial_on_scene: int = 0


@dataclass
class FireBehaviorPrediction:
    """
    Resultado do motor de fogo para uma ocorrência num cenário meteo.
    Pode haver vários por ocorrência (central, pior, melhor).
    """
    scenario: str                  # "central", "worst", "best"

    # Comportamento principal (Rothermel + Byram)
    ros_m_per_min: float
    fireline_intensity_kw_m: float
    flame_length_m: float
    heat_per_unit_area_kj_m2: float
    reaction_intensity_kw_m2: float
    direction_max_spread_deg: float
    effective_wind_ms: float

    # Crown fire (se aplicável)
    fire_type: FireType = FireType.SURFACE
    crown_ros_m_per_min: Optional[float] = None
    crown_fraction_burned: Optional[float] = None

    # Métricas derivadas para o frontend
    @property
    def tactic_category(self) -> str:
        """
        Categoria táctica baseada no comprimento de chama.
        Convenção do Fire Behavior Field Reference Guide (USFS).
        """
        L = self.flame_length_m
        if L < 1.2:
            return "direct_attack_manual"
        elif L < 2.4:
            return "direct_attack_difficult"
        elif L < 3.4:
            return "indirect_attack_machinery"
        else:
            return "indirect_attack_only"


@dataclass
class TriageResult:
    """
    Resultado completo da triagem para uma ocorrência.
    Inclui terreno, meteo, e múltiplos cenários de previsão.
    """
    occurrence: Occurrence
    terrain: TerrainConditions
    weather: WeatherConditions
    predictions: list[FireBehaviorPrediction]  # típicamente 3: central, pior, melhor
    priority: Priority
    priority_score: float          # 0-100 contínuo

    # Exposição (calculada à parte)
    distance_to_settlement_m: Optional[float] = None
    population_at_risk_estimate: Optional[int] = None
    protected_area_nearby: bool = False

    # Diagnósticos
    fuel_model_used: str = ""
    wind_adjustment_factor: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def central_prediction(self) -> FireBehaviorPrediction:
        return next(p for p in self.predictions if p.scenario == "central")
