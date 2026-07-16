-- Simulação livre — ignição definida à mão (ponto ou linha), sem
-- depender de uma ocorrência real do fogos.pt. Tabela própria, sem FK
-- para occurrences (o simulation_jobs original exige fire_id NOT NULL,
-- não reutilizável aqui) — mesmo motor de simulação, fluxo independente.

CREATE TABLE IF NOT EXISTS free_simulation_jobs (
    job_id               UUID PRIMARY KEY,
    ignition_points_json JSONB NOT NULL,  -- lista de [lat, lon]; 1 ponto ou linha (2+)
    requested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    status               VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending/running/done/failed
    duration_h           REAL NOT NULL,
    parameters_json      JSONB,
    result_json          JSONB,  -- perímetros em GeoJSON (mesmo formato de simulation_jobs)
    error_message        TEXT
);

CREATE INDEX IF NOT EXISTS idx_freesimjobs_status ON free_simulation_jobs (status, requested_at);
