# API fogos_triage

API REST do sistema de triagem de fogos. Construída com FastAPI.

## Arrancar

### Local (sem Docker)

```bash
cd fogos_triage
pip install -e ".[full]"
pip install fastapi "uvicorn[standard]"

# Variáveis (ou usar .env)
export DATABASE_URL=postgresql://fogos:fogos_dev_pass@localhost:5432/fogos
export API_KEYS=dev-key
export FUEL_MODELS_CSV=$PWD/data/fuel_models_pt.csv

uvicorn services.api.main:app --reload --port 8000
```

### Com docker-compose

```bash
docker-compose up postgres -d        # base de dados
docker-compose up api                # API em :8000
```

Documentação interativa: `http://localhost:8000/docs` (Swagger UI).

## Autenticação

Todos os endpoints (exceto `/health`) requerem um Bearer token:

```
Authorization: Bearer <api-key>
```

As keys válidas vêm da variável `API_KEYS` (separadas por vírgula).
Em desenvolvimento pode-se desligar com `REQUIRE_AUTH=false`.

## Endpoints

### `GET /health`
Healthcheck. Sem autenticação. Devolve estado do serviço e da BD.

```json
{
  "status": "ok",
  "service": "fogos-triage-api",
  "version": "0.3.0",
  "database_ok": true,
  "worker_last_seen_at": "2026-05-16T14:30:00Z"
}
```

### `GET /fires`
Lista priorizada de ocorrências ativas.

**Query params:**
- `limit` (1-200, default 50)
- `cursor` — paginação (devolvido em `next_cursor`)
- `district` — filtrar por distrito
- `min_priority` — `P1`/`P2`/`P3`/`P4` (devolve essa prioridade e acima)
- `only_triaged` — `true` exclui ocorrências sem triagem

```bash
curl -H "Authorization: Bearer dev-key" \
  "http://localhost:8000/fires?min_priority=P2&limit=20"
```

Resposta: `{ items: [...], total: N, next_cursor: "..." }`

### `GET /fires/{fire_id}`
Detalhe completo: ocorrência + triagem (3 cenários) + terreno + meteo.

### `GET /fires/{fire_id}/history`
Histórico de mudanças de estado e recursos.

### `GET /fires/geo/within`
Ocorrências dentro de uma bounding box, em formato **GeoJSON FeatureCollection**.

**Query params (obrigatórios):** `min_lat`, `min_lng`, `max_lat`, `max_lng`

```bash
curl -H "Authorization: Bearer dev-key" \
  "http://localhost:8000/fires/geo/within?min_lat=38&min_lng=-10&max_lat=42&max_lng=-6"
```

Consumível diretamente por MapLibre/Leaflet.

### `GET /fuel-models` e `GET /fuel-models/{num}`
Lista / detalhe dos modelos de combustível PT.

### `POST /simulate`
Cria um job de simulação ForeFire (assíncrono).

```json
{ "fire_id": "20260674022", "duration_h": 3.0 }
```

Devolve `202 Accepted` com `job_id`. O runner processará quando existir.

### `GET /jobs/{job_id}`
Estado e resultado de um job de simulação.

## Categorias tácticas

O campo `tactic_category` é derivado do comprimento de chama:

| Categoria | Comp. chama | Significado |
|---|---|---|
| `direct_attack_manual` | < 1.2 m | Ataque direto com ferramenta manual viável |
| `direct_attack_difficult` | 1.2-2.4 m | Ataque direto difícil, indireto preferível |
| `indirect_attack_machinery` | 2.4-3.4 m | Máquina pesada, problemas de controlo prováveis |
| `indirect_attack_only` | > 3.4 m | Ataque direto não recomendado |

## Prioridades

| Classe | Score | Significado |
|---|---|---|
| `P1` | ≥ 70 | Crítica — ação imediata |
| `P2` | 50-70 | Alta — vigilância apertada |
| `P3` | 25-50 | Vigilância — monitorizar |
| `P4` | < 25 | Controlada / baixo risco |

## Deployment Railway

```bash
# A API é um serviço separado do worker no mesmo projeto Railway
railway service create api
railway up --service api

# Variáveis (DATABASE_URL é partilhada via referência ao Postgres)
railway variables set --service api \
  API_KEYS=$(python -c "import secrets;print(secrets.token_urlsafe(32))") \
  ALLOWED_ORIGINS=https://o-teu-frontend.app \
  FUEL_MODELS_CSV=/data/fuel_models_pt.csv
```

O `railway.json` já define `healthcheckPath: /health`.
