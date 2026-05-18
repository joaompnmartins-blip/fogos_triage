"""
Schemas Pydantic para os endpoints da API.

Camada de serialização: traduz entre as dataclasses do domínio e o que
sai/entra na API HTTP. Separar isto do domínio mantém o motor de fogo
desacoplado da framework web.

Convenções:
- Coordenadas em WGS84 (EPSG:4326)
- Distâncias em metros
- Tempos em ISO 8601 com timezone UTC
- Outputs em SI/PT (m/min, kW/m, °C, etc.) — NÃO em English Units
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Resposta genérica
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    service: str = "fogos-triage-api"
    version: str
    database_ok: bool
    worker_last_seen_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Fogos / ocorrências
# ---------------------------------------------------------------------------


class WeatherSummary(BaseModel):
    """Meteo resumida para inline em ocorrência."""
    temperature_c: Optional[float] = None
    relative_humidity_pct: Optional[float] = None
    wind_speed_ms: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    wind_direction_text: Optional[str] = None
    precipitation_mm_24h: Optional[float] = None
    fire_weather_index: Optional[float] = None
    source: str  # "ipma_fogos" / "open_meteo"
    station_location: Optional[str] = None
    station_distance_km: Optional[float] = None
    observation_at: Optional[datetime] = None


class FireBehaviorSummary(BaseModel):
    """Predição de comportamento (cenário central simplificado)."""
    scenario: str  # "central"/"worst"/"best"
    ros_m_per_min: float
    ros_km_per_h: float
    fireline_intensity_kw_m: float
    flame_length_m: float
    fire_type: str  # "surface"/"torching"/"crowning"/"no_burn"
    direction_max_spread_deg: float
    tactic_category: str  # derivado do flame_length


class TriageSummary(BaseModel):
    """Triagem resumida para a lista de fogos."""
    priority_class: str  # P1/P2/P3/P4
    priority_score: float
    fuel_model_code: str
    computed_at: datetime
    central: FireBehaviorSummary
    notes: list[str] = Field(default_factory=list)


class FireListItem(BaseModel):
    """Item da lista priorizada (endpoint /fires)."""
    fire_id: str
    latitude: float
    longitude: float
    location: str
    district: str
    municipality: str
    parish: str
    locality: Optional[str] = None
    natureza_code: int
    natureza_name: str
    status_code: int
    status_name: str
    is_important: bool
    operatives: int
    vehicles: int
    aerial: int
    started_at: datetime
    updated_at: datetime
    # Triagem (opcional — pode não estar feita ainda ou ser natureza não relevante)
    triage: Optional[TriageSummary] = None


class FireListResponse(BaseModel):
    """Resposta paginada de fogos."""
    items: list[FireListItem]
    total: int
    next_cursor: Optional[str] = None


class TerrainDetail(BaseModel):
    """Terreno no ponto da ocorrência."""
    elevation_m: float
    slope_degrees: float
    aspect_degrees: float
    fuel_model_num: int
    fuel_model_code: str
    stand_height_m: Optional[float] = None
    canopy_cover_pct: Optional[float] = None
    canopy_base_height_m: Optional[float] = None


class FireBehaviorDetail(BaseModel):
    """Predição completa de um cenário."""
    scenario: str
    ros_m_per_min: float
    ros_km_per_h: float
    fireline_intensity_kw_m: float
    flame_length_m: float
    heat_per_unit_area_kj_m2: float
    reaction_intensity_kw_m2: float
    direction_max_spread_deg: float
    effective_wind_ms: float
    fire_type: str
    tactic_category: str


class TriageDetail(BaseModel):
    """Triagem completa com todos os cenários e diagnóstico."""
    computed_at: datetime
    priority_class: str
    priority_score: float
    fuel_model_code: str
    fuel_model_num: int
    terrain: TerrainDetail
    weather: WeatherSummary
    wind_midflame_ms: Optional[float]
    wind_adjustment_factor: Optional[float]
    fuel_moisture_1h_pct: Optional[float]
    scenarios: list[FireBehaviorDetail]
    notes: list[str] = Field(default_factory=list)


class FireDetailResponse(BaseModel):
    """Detalhe completo (endpoint /fires/{fire_id})."""
    fire_id: str
    sado_id: Optional[str]
    sharepoint_id: Optional[int]
    latitude: float
    longitude: float
    location: str
    district: str
    municipality: str
    parish: str
    locality: Optional[str]
    region: Optional[str]
    subregion: Optional[str]
    dico: Optional[str]
    natureza_code: int
    natureza_name: str
    status_code: int
    status_name: str
    is_active: bool
    is_important: bool
    is_terminated: bool
    operatives: int
    vehicles: int
    aerial: int
    heli_fight: int
    heli_coord: int
    plane_fight: int
    water_means: int
    started_at: datetime
    api_updated_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    triage: Optional[TriageDetail] = None


class FireHistoryItem(BaseModel):
    snapshot_at: datetime
    change_type: str  # "created"/"status"/"resources"/"both"
    status_code: int
    status_name: str
    previous_status_code: Optional[int]
    operatives: int
    vehicles: int
    aerial: int
    heli_fight: int
    plane_fight: int


# ---------------------------------------------------------------------------
# GeoJSON para endpoints espaciais
# ---------------------------------------------------------------------------


class GeoJSONPoint(BaseModel):
    type: str = "Point"
    coordinates: list[float]  # [lng, lat]


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: GeoJSONPoint
    properties: dict
    id: str


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]


# ---------------------------------------------------------------------------
# Fuel models
# ---------------------------------------------------------------------------


class FuelModelInfo(BaseModel):
    """Informação sumária de um modelo de combustível para o frontend."""
    num: int
    code: str
    name: str
    load_dead_t_ha: float
    load_live_t_ha: float
    depth_cm: float
    moist_ext_dead_pct: float
    is_dynamic: bool


# ---------------------------------------------------------------------------
# Simulação ForeFire
# ---------------------------------------------------------------------------


class SimulationRequest(BaseModel):
    """Pedido de simulação ForeFire."""
    fire_id: str
    duration_h: float = Field(default=3.0, ge=0.5, le=12.0)
    # Override de meteo (se ausente, usa-se a meteo da ocorrência)
    wind_speed_ms: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    # Override de bbox (se ausente, usa-se janela default 20×20 km)
    bbox_km: Optional[float] = Field(default=None, ge=2.0, le=50.0)


class SimulationJob(BaseModel):
    job_id: str
    fire_id: str
    status: str  # "pending"/"running"/"done"/"failed"
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_h: float
    error_message: Optional[str] = None
    # Resultado disponível quando status=done
    perimeters_geojson: Optional[dict] = None
