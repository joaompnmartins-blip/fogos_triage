# fogos_triage

Serviço de triagem rápida para o sistema operacional de fogos em Portugal.

Implementa Rothermel-Andrews 2018 + Byram + Van Wagner sobre os modelos de
combustível portugueses (Fernandes 2009) e a Landscape File PT, com ingestão
da API fogos.pt e meteorologia IPMA anexa.

## Estrutura

```
fogos_triage/
├── src/fogos_triage/             # package Python (motor + domínio)
│   ├── __init__.py
│   ├── fuel_models.py            # loader .fmd/CSV + conversões de unidades
│   ├── schemas.py                # dataclasses do domínio
│   ├── landscape.py              # leitura dos rasters TIFF da LCP
│   ├── weather.py                # Open-Meteo + WAF + humidades dos combustíveis
│   ├── engine.py                 # adapter para wildfire_ROS_models (REAL)
│   ├── triage.py                 # serviço de triagem + scoring de prioridade
│   ├── ingestion/
│   │   ├── fogos_client.py       # cliente API fogos.pt (curl_cffi)
│   │   └── adapters.py           # FogosFire → Occurrence, etc.
│   └── db/
│       ├── repository.py         # OccurrenceRepository (asyncpg)
│       └── triage_repo.py        # TriageResultRepository
├── services/
│   ├── __init__.py
│   ├── worker/                   # polling fogos.pt + ingestão + triagem
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── railway.json
│   └── api/                      # API REST FastAPI
│       ├── main.py               # app + lifespan
│       ├── deps.py               # config, auth, pool
│       ├── schemas.py            # modelos Pydantic
│       ├── routes_fires.py       # /fires, /fires/{id}, /geo/within
│       ├── routes_meta.py        # /fuel-models, /simulate, /health
│       ├── Dockerfile
│       ├── railway.json
│       ├── .env.example
│       └── README.md             # documentação dos endpoints
├── migrations/
│   └── 001_initial_schema.sql    # PostGIS + 6 tabelas + view
├── data/
│   └── fuel_models_pt.csv        # 20 modelos de combustível PT
├── tests/
│   ├── test_pipeline.py          # pipeline de triagem
│   ├── test_aggregation.py       # agregação multifuel
│   ├── test_parser_offline.py    # parser fogos.pt (payload cacheado)
│   ├── test_fogos_client.py      # cliente fogos.pt (precisa de internet)
│   ├── test_api_smoke.py         # rotas registadas
│   ├── test_api_integration.py   # API com TestClient (28 testes)
│   └── test_e2e_postgres.py      # ingestão→triagem→persistência (precisa Postgres)
├── docker-compose.yml            # Postgres + Redis + worker + API
├── pyproject.toml
├── .gitignore
├── .dockerignore
├── README.md                     # este ficheiro
└── TESTING.md                    # guia de teste local passo-a-passo
```

## Componentes

```
                  ┌──────────────┐
   fogos.pt ─────▶│   worker     │──┐
   Open-Meteo ───▶│  (polling)   │  │
                  └──────────────┘  │
                                    ▼
                            ┌──────────────┐
                            │  PostgreSQL  │
                            │   + PostGIS  │
                            └──────────────┘
                                    ▲
                  ┌──────────────┐  │
   frontend ─────▶│     API      │──┘
   (futuro)       │  (FastAPI)   │
                  └──────────────┘
```

## Estado atual

**Funcional e testado:**
- Loader de modelos PT (CSV ou .fmd FARSITE)
- Engine REAL com wildfire_ROS_models.RothermelAndrews2018
- Agregação ponderada à BehavePlus dos 5 componentes
- Cenários ±vento ±humidade, Van Wagner crown fire transition
- Scoring de prioridade P1-P4
- Cliente fogos.pt com curl_cffi (passa Cloudflare)
- Schema Postgres+PostGIS com 6 tabelas + view
- Worker: polling, ingestão, triagem, graceful shutdown
- **API FastAPI completa** — 9 endpoints, autenticação Bearer, CORS,
  paginação por cursor, GeoJSON, OpenAPI docs (28 testes de integração ✓)
- Dockerfiles + railway.json para worker e API
- docker-compose.yml para dev local

**Próximos passos:**
- [ ] Setup Railway concreto (deploy real)
- [ ] ForeFire-runner container
- [ ] Validação histórica contra incêndios ICNF
- [ ] Frontend desktop React+MapLibre
- [ ] Live fuel moisture do LFMC Sentinel-2
- [ ] Distância a aglomerados populacionais (CAOP + OSM)

## Tabelas Postgres

| Tabela | Função |
|---|---|
| `occurrences` | Estado atual de cada ocorrência (PK = fire_id da fogos.pt) |
| `occurrence_history` | Cada mudança de status ou recursos |
| `weather_snapshots` | Meteo IPMA por ocorrência + futuras chamadas Open-Meteo |
| `triage_results` | Resultados do motor de triagem (com flag is_latest) |
| `meteo_cache` | Cache Open-Meteo por célula geográfica |
| `simulation_jobs` | Jobs ForeFire (estrutura pronta) |

Mais a view `active_fires_with_triage` para consumo pelo frontend.

## Setup local

Para um guia completo de teste local — passo-a-passo, checkpoints em cada
etapa, e troubleshooting — ver **[TESTING.md](TESTING.md)**.

Resumo rápido:

```bash
# 1. Subir Postgres+PostGIS (aplica o schema automaticamente)
docker-compose up postgres -d

# 2. Worker em modo dev (MockLandscape — sem TIFFs reais)
docker-compose up worker          # ver logs do polling; Ctrl-C para sair

# 3. API
docker-compose up api -d          # depois: http://localhost:8000/docs

# Validar a cadeia sem depender da fogos.pt:
python tests/test_e2e_postgres.py # (precisa de Postgres a correr)
```

Para passar a Landscape File real:
- Pôr os 7 TIFFs em `./data/landscape/`:
  `altitude.tif`, `declive.tif`, `exposicao.tif`, `modelos_combustivel.tif`,
  `altura_povoamento.tif`, `cobertura_copas.tif`, `altura_base_copa.tif`
- Mudar `DEV_MODE: "false"` no `docker-compose.yml`

## Deployment Railway

```bash
railway init
railway add postgres
# instalar PostGIS no Postgres via SQL: CREATE EXTENSION postgis;

railway variables set \
  FUEL_MODELS_CSV=/data/fuel_models_pt.csv \
  LANDSCAPE_DIR=/data/landscape \
  POLL_INTERVAL_S=120

railway run psql $DATABASE_URL < migrations/001_initial_schema.sql
railway up
```

## Variáveis de ambiente

| Variável | Default | Descrição |
|---|---|---|
| `DATABASE_URL` | (obrigatória) | DSN Postgres |
| `FUEL_MODELS_CSV` | `/data/fuel_models_pt.csv` | Caminho CSV modelos PT |
| `LANDSCAPE_DIR` | (vazia → DEV_MODE) | Diretório TIFFs Landscape File |
| `POLL_INTERVAL_S` | `120` | Segundos entre polls fogos.pt |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `DEV_MODE` | `false` | Se true usa MockLandscape (terreno fixo) |

## Naturezas relevantes para triagem

Apenas estas disparam triagem completa:
- `3101` Povoamento Florestal
- `3103` Mato
- `3105` Agrícola

Excluídas (queimadas controladas/prevenção):
- `3109` Gestão de Combustível
- `3111` Queima
- `4335` Prevenção a Queimadas

## Acesso à API fogos.pt

A API está atrás de Cloudflare e bloqueia clientes HTTP comuns por TLS
fingerprint. O cliente usa `curl_cffi` para passar (impersonação de Chrome).

Para produção a longo prazo recomenda-se:
1. Contactar Tiago Henriques (fogos.pt) para whitelist/API-key
2. Ou usar fonte oficial direta ANEPC/PROCIV
