-- "Vigilância" (status_code=9, monitorização pós-rescaldo) passa a contar
-- como terminada, tal como "Conclusão" (status_code=8) — ambas representam
-- o fogo já resolvido para efeitos de triagem/prioridade. is_terminated é
-- coluna GENERATED, por isso tem de ser recriada (Postgres não permite
-- ALTER da expressão de uma coluna gerada). CASCADE porque
-- active_fires_with_triage depende da coluna — a view é recriada a seguir
-- (definição igual à de 001_initial_schema.sql).
ALTER TABLE occurrences DROP COLUMN IF EXISTS is_terminated CASCADE;
ALTER TABLE occurrences
    ADD COLUMN is_terminated BOOLEAN GENERATED ALWAYS AS (status_code IN (8, 9)) STORED;

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
