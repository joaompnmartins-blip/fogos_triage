-- Adiciona fire_weather_index à tabela weather_snapshots
-- (para bases de dados já existentes criadas com 001_initial_schema.sql)

ALTER TABLE weather_snapshots
    ADD COLUMN IF NOT EXISTS fire_weather_index REAL;
