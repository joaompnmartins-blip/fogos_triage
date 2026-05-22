-- Humidades dos combustíveis completas (Simard 1968 + Yebra 2007)
ALTER TABLE triage_results
    ADD COLUMN IF NOT EXISTS fuel_moisture_10h_pct REAL,
    ADD COLUMN IF NOT EXISTS fuel_moisture_100h_pct REAL,
    ADD COLUMN IF NOT EXISTS fuel_moisture_live_h_pct REAL,
    ADD COLUMN IF NOT EXISTS fuel_moisture_live_w_pct REAL;
