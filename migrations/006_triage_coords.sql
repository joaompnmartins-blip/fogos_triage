-- =====================================================================
-- 006: coordenadas usadas na triagem
--
-- A triagem passou a ser congelada no arranque da ocorrência (deixou de
-- correr de 15 em 15 minutos e a cada mudança de efectivos). A única
-- coisa que a volta a disparar enquanto a ocorrência está activa é a
-- fogos.pt corrigir a localização — nesse caso o terreno e a meteo da
-- triagem congelada são do sítio errado.
--
-- Para detectar isso é preciso saber em que coordenada a triagem
-- congelada foi calculada. Comparar com a linha anterior de `occurrences`
-- não servia: só apanharia a correcção no ciclo exacto em que acontece, e
-- perdia-a se o worker estivesse em baixo nesse momento. Guardando aqui,
-- a comparação é sempre contra o que foi realmente usado.
-- =====================================================================

ALTER TABLE triage_results
    ADD COLUMN IF NOT EXISTS latitude  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;

COMMENT ON COLUMN triage_results.latitude IS
    'Coordenada da ocorrência no momento desta triagem (ver 006 e needs_triage)';
COMMENT ON COLUMN triage_results.longitude IS
    'Coordenada da ocorrência no momento desta triagem (ver 006 e needs_triage)';
