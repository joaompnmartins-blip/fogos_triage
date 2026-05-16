-- =====================================================================
-- Schema inicial fogos_triage
-- =====================================================================
-- PostGIS é obrigatório (queries espaciais, geometria das ocorrências)
-- Versão mínima: PostgreSQL 14 + PostGIS 3.2
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- para fuzzy search em nomes


-- =====================================================================
-- TABELA: occurrences
-- Ocorrências ativas e inativas (mantemos histórico)
-- =====================================================================

CREATE TABLE IF NOT EXISTS occurrences (
    -- Identificadores
    fire_id          VARCHAR(64) PRIMARY KEY,         -- id da fogos.pt
    sado_id          VARCHAR(64),
    sharepoint_id    BIGINT,

    -- Geografia
    geom             GEOMETRY(Point, 4326) NOT NULL,  -- WGS84
    latitude         DOUBLE PRECISION NOT NULL,
    longitude        DOUBLE PRECISION NOT NULL,
    has_reliable_coords BOOLEAN NOT NULL DEFAULT TRUE,

    -- Localização administrativa
    location_text    TEXT,
    district         VARCHAR(64),
    municipality     VARCHAR(96),
    parish           VARCHAR(128),
    dico             VARCHAR(8),
    locality         TEXT,
    region           VARCHAR(64),
    subregion        VARCHAR(96),

    -- Tipologia
    natureza_code    INTEGER NOT NULL,
    natureza_name    VARCHAR(96),
    is_triage_relevant BOOLEAN NOT NULL DEFAULT FALSE,

    -- Estado atual (snapshot mais recente; histórico em occurrence_history)
    status_code      INTEGER NOT NULL,
    status_name      VARCHAR(64),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    is_important     BOOLEAN NOT NULL DEFAULT FALSE,
    is_terminated    BOOLEAN GENERATED ALWAYS AS (status_code = 8) STORED,

    -- Recursos
    operatives       INTEGER NOT NULL DEFAULT 0,
    vehicles         INTEGER NOT NULL DEFAULT 0,
    aerial           INTEGER NOT NULL DEFAULT 0,
    heli_fight       INTEGER NOT NULL DEFAULT 0,
    heli_coord       INTEGER NOT NULL DEFAULT 0,
    plane_fight      INTEGER NOT NULL DEFAULT 0,
    water_means      INTEGER NOT NULL DEFAULT 0,

    -- Timestamps
    started_at       TIMESTAMPTZ NOT NULL,
    api_created_at   TIMESTAMPTZ NOT NULL,
    api_updated_at   TIMESTAMPTZ NOT NULL,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Raw para debug
    raw_payload      JSONB
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_occurrences_geom ON occurrences USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_occurrences_active ON occurrences (is_active, last_seen_at DESC)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_occurrences_district ON occurrences (district);
CREATE INDEX IF NOT EXISTS idx_occurrences_status ON occurrences (status_code);
CREATE INDEX IF NOT EXISTS idx_occurrences_started ON occurrences (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_occurrences_natureza ON occurrences (natureza_code);


-- =====================================================================
-- TABELA: occurrence_history
-- Histórico de mudanças relevantes (status, recursos)
-- =====================================================================

CREATE TABLE IF NOT EXISTS occurrence_history (
    id               BIGSERIAL PRIMARY KEY,
    fire_id          VARCHAR(64) NOT NULL REFERENCES occurrences(fire_id) ON DELETE CASCADE,
    snapshot_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Snapshot do estado
    status_code      INTEGER NOT NULL,
    status_name      VARCHAR(64),
    operatives       INTEGER,
    vehicles         INTEGER,
    aerial           INTEGER,
    heli_fight       INTEGER,
    plane_fight      INTEGER,

    -- Trigger da mudança
    change_type      VARCHAR(32) NOT NULL,  -- 'status', 'resources', 'both', 'created'
    previous_status_code INTEGER
);

CREATE INDEX IF NOT EXISTS idx_history_fire_id ON occurrence_history (fire_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_snapshot ON occurrence_history (snapshot_at DESC);


-- =====================================================================
-- TABELA: weather_snapshots
-- Snapshots IPMA anexos à ocorrência (vindo da fogos.pt) e do Open-Meteo
-- =====================================================================

CREATE TABLE IF NOT EXISTS weather_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    fire_id          VARCHAR(64) NOT NULL REFERENCES occurrences(fire_id) ON DELETE CASCADE,
    snapshot_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Fonte: 'ipma_fogos' (vem da fogos.pt) ou 'open_meteo'
    source           VARCHAR(32) NOT NULL,

    -- IPMA: estação ----------------------------
    ipma_station_id  INTEGER,
    ipma_station_location TEXT,
    ipma_station_distance_km REAL,

    -- Open-Meteo: hora prevista ----------------
    forecast_for     TIMESTAMPTZ,
    forecast_hour_offset INTEGER,  -- 0 = agora, 1 = +1h, etc.

    -- Dados meteorológicos
    temperature_c    REAL,
    relative_humidity_pct REAL,
    wind_speed_ms    REAL,
    wind_speed_kmh   REAL,
    wind_gust_ms     REAL,
    wind_direction_deg REAL,
    wind_direction_text VARCHAR(4),
    precipitation_mm REAL,
    precipitation_24h_mm REAL,
    cloud_cover_pct  REAL,
    radiation        REAL,
    pressure_hpa     REAL,

    -- Timestamp original do dado meteorológico
    observation_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_weather_fire_id ON weather_snapshots (fire_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_source ON weather_snapshots (source);


-- =====================================================================
-- TABELA: triage_results
-- Resultados de triagem por ocorrência (atualizado quando há mudanças)
-- =====================================================================

CREATE TABLE IF NOT EXISTS triage_results (
    id               BIGSERIAL PRIMARY KEY,
    fire_id          VARCHAR(64) NOT NULL REFERENCES occurrences(fire_id) ON DELETE CASCADE,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Terreno usado
    elevation_m      REAL,
    slope_degrees    REAL,
    aspect_degrees   REAL,
    fuel_model_num   INTEGER,
    fuel_model_code  VARCHAR(16),
    stand_height_m   REAL,
    canopy_cover_pct REAL,
    canopy_base_height_m REAL,

    -- Cenário central (mais usado em queries)
    central_ros_m_per_min       REAL,
    central_fireline_intensity_kw_m REAL,
    central_flame_length_m      REAL,
    central_fire_type           VARCHAR(16),
    central_direction_deg       REAL,

    -- Cenários todos (incluindo central, worst, best) em JSONB
    scenarios_json   JSONB NOT NULL,

    -- Prioridade
    priority_class   VARCHAR(4) NOT NULL,  -- P1/P2/P3/P4
    priority_score   REAL NOT NULL,

    -- Diagnósticos
    wind_midflame_ms REAL,
    wind_adjustment_factor REAL,
    fuel_moisture_1h_pct REAL,
    notes            TEXT[],

    -- Sinalização "stale"
    is_latest        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_triage_fire_latest ON triage_results (fire_id, computed_at DESC)
    WHERE is_latest = TRUE;
CREATE INDEX IF NOT EXISTS idx_triage_priority ON triage_results (priority_class, computed_at DESC)
    WHERE is_latest = TRUE;
CREATE INDEX IF NOT EXISTS idx_triage_score ON triage_results (priority_score DESC)
    WHERE is_latest = TRUE;


-- =====================================================================
-- TABELA: meteo_cache
-- Cache de Open-Meteo por célula geográfica (~5km bin)
-- Reduz chamadas à API quando há vários fogos próximos
-- =====================================================================

CREATE TABLE IF NOT EXISTS meteo_cache (
    cell_id          VARCHAR(32) PRIMARY KEY,  -- ex: "lat41p3_lng-7p7"
    geom             GEOMETRY(Point, 4326) NOT NULL,  -- centro da célula
    forecast_json    JSONB NOT NULL,  -- forecast hourly completo
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meteo_cache_geom ON meteo_cache USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_meteo_cache_expires ON meteo_cache (expires_at);


-- =====================================================================
-- TABELA: simulation_jobs
-- Jobs assíncronos de simulação ForeFire (preparado para o futuro)
-- =====================================================================

CREATE TABLE IF NOT EXISTS simulation_jobs (
    job_id           UUID PRIMARY KEY,
    fire_id          VARCHAR(64) NOT NULL REFERENCES occurrences(fire_id) ON DELETE CASCADE,
    requested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    status           VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending/running/done/failed
    duration_h       REAL NOT NULL,
    parameters_json  JSONB,
    result_json      JSONB,  -- perímetros em GeoJSON
    error_message    TEXT
);

CREATE INDEX IF NOT EXISTS idx_simjobs_fire ON simulation_jobs (fire_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_simjobs_status ON simulation_jobs (status, requested_at);


-- =====================================================================
-- VIEW: active_fires_with_triage
-- View útil para a API: ocorrências ativas com triagem mais recente
-- =====================================================================

CREATE OR REPLACE VIEW active_fires_with_triage AS
SELECT
    o.fire_id, o.latitude, o.longitude, o.location_text,
    o.district, o.municipality, o.parish, o.locality,
    o.natureza_code, o.natureza_name,
    o.status_code, o.status_name,
    o.is_important,
    o.operatives, o.vehicles, o.aerial,
    o.started_at, o.api_updated_at,
    t.priority_class, t.priority_score,
    t.central_ros_m_per_min, t.central_fireline_intensity_kw_m,
    t.central_flame_length_m, t.central_fire_type,
    t.fuel_model_code, t.computed_at AS triage_computed_at
FROM occurrences o
LEFT JOIN triage_results t ON t.fire_id = o.fire_id AND t.is_latest = TRUE
WHERE o.is_active = TRUE
  AND NOT o.is_terminated
ORDER BY
    t.priority_score DESC NULLS LAST,
    o.started_at DESC;
