-- "Vigilância" (status_code=9, monitorização pós-rescaldo) passa a contar
-- como terminada, tal como "Conclusão" (status_code=8) — ambas representam
-- o fogo já resolvido para efeitos de triagem/prioridade. is_terminated é
-- coluna GENERATED, por isso tem de ser recriada (Postgres não permite
-- ALTER da expressão de uma coluna gerada).
ALTER TABLE occurrences DROP COLUMN IF EXISTS is_terminated;
ALTER TABLE occurrences
    ADD COLUMN is_terminated BOOLEAN GENERATED ALWAYS AS (status_code IN (8, 9)) STORED;
