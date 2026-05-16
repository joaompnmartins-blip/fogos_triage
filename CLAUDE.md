# CLAUDE.md — fogos_triage

Contexto para o Claude Code. Sistema operacional de previsão e triagem de
incêndios florestais para Portugal (apoio à decisão ANEPC/bombeiros).

## O que o sistema faz

A partir das ocorrências da API fogos.pt, com dados de terreno e
meteorologia, calcula o comportamento esperado do fogo (taxa de propagação,
intensidade, comprimento de chama) e classifica cada ocorrência por
prioridade de intervenção P1-P4. Usa o motor Rothermel-Andrews 2018 + Byram
+ Van Wagner, sobre os modelos de combustível portugueses (Fernandes 2009).

## Arquitetura

Quatro componentes:
- **worker** (`services/worker/`) — faz polling à fogos.pt a cada 120s,
  ingere ocorrências, corre triagem, persiste no Postgres
- **API** (`services/api/`) — FastAPI, expõe os dados em REST
- **PostgreSQL + PostGIS** — 6 tabelas + 1 view
- **redis** — fila para simulações ForeFire (ainda não usada)

Regra de dependências fundamental: `services/` depende de `src/`, NUNCA o
contrário. O `src/fogos_triage/` é uma biblioteca pura (motor de fogo,
domínio, repositórios) — não conhece HTTP nem filas. Manter esta separação.

## Estrutura

```
src/fogos_triage/      biblioteca (importável, sem efeitos secundários)
  engine.py            adapter para wildfire_ROS_models (motor de fogo)
  triage.py            serviço de triagem + scoring P1-P4
  fuel_models.py       loader dos modelos de combustível PT
  schemas.py           dataclasses do domínio
  landscape.py         leitura dos rasters TIFF
  weather.py           Open-Meteo + wind adjustment + humidades
  ingestion/           cliente fogos.pt + adapters
  db/                  repositórios asyncpg
services/worker/       processo de ingestão + triagem
services/api/          API REST FastAPI
migrations/            schema SQL (PostGIS)
tests/                 testes (ver secção Testes)
```

## Comandos

```bash
# Subir tudo (Docker)
docker compose up postgres -d
docker compose up worker -d --build
docker compose up api -d --build

# IMPORTANTE: o comando é "docker compose" (com espaço), não "docker-compose"

# Testes que não precisam de Postgres
python tests/test_pipeline.py
python tests/test_api_integration.py    # 28 testes

# Testes que precisam de Postgres a correr
export DATABASE_URL=postgresql://localhost/fogos
python tests/test_e2e_postgres.py
python tests/test_open_meteo.py

# API local sem Docker
uvicorn services.api.main:app --reload --port 8000
```

## Armadilhas conhecidas (IMPORTANTE)

Estas foram descobertas a testar — não são óbvias a olhar para o código:

1. **Dockerfiles precisam de `git` e `scikit-learn`.** A imagem
   `python:3.12-slim` não traz `git` (necessário para o pip instalar a
   wildfire_ROS_models do GitHub). E a wildfire_ROS_models precisa de
   `scikit-learn` em runtime. Ambos têm de estar no `apt-get`/`pip install`
   dos dois Dockerfiles (worker e api). Sem eles: o build falha, ou o motor
   de fogo carrega a devolver zeros (`chamas 0.0m`).

2. **`DEV_MODE=true` usa terreno FALSO.** Com DEV_MODE, o worker usa um
   MockLandscapeReader — terreno fixo igual para todo o país (FM227, pinhal,
   400m, 15° declive). As triagens funcionam mas NÃO são previsões reais.
   Para terreno real: pôr os 7 TIFFs em `data/landscape/` e DEV_MODE=false.

3. **fogos.pt está atrás de Cloudflare.** O cliente usa `curl_cffi`
   (impersona Chrome) para passar. Se der 403, pode ser bloqueio de IP —
   ver README. NUNCA usar httpx simples para a fogos.pt.

4. **asyncpg não desserializa JSONB por defeito.** Vem como string. O pool
   tem de ser criado com `init_pool()` (que regista codecs JSON) ou
   passando `init=_init_connection`. Sem isso, colunas como `scenarios_json`
   rebentam ao ler.

5. **A view `active_fires_with_triage` filtra `is_active`/`is_terminated`
   internamente e não as expõe.** Queries contra a VIEW não podem referir
   essas colunas. Queries contra a TABELA `occurrences` podem.

6. **Naturezas relevantes para triagem:** só 3101 (Povoamento Florestal),
   3103 (Mato), 3105 (Agrícola). As de queimada/prevenção (3109, 3111,
   4335) NÃO disparam triagem — é por design, não é bug.

## Meteorologia

A triagem usa **Open-Meteo** (API aberta, sem autenticação) para a meteo no
ponto exato do fogo. O worker chama `fetch_open_meteo()`, grava o snapshot
em `weather_snapshots` (com `source='open_meteo'`), e usa-o na triagem.
Se o Open-Meteo falhar, há fallback para defaults conservadores.

Nota: a fogos.pt também traz meteo IPMA anexa, mas optou-se por Open-Meteo
por dar interpolação à coordenada (a IPMA é da estação mais próxima, que
pode estar a 15-20 km). A função `fogos_weather_to_conditions` em
`ingestion/adapters.py` ainda existe mas já não é usada na triagem.

## Convenções

- Unidades internas do motor: English Units (Rothermel). Conversão para
  SI/métrico só na fronteira (API, logs). Outputs ao utilizador em m/min,
  kW/m, metros.
- SQL direto com asyncpg, sem ORM (decisão deliberada — queries poucas,
  PostGIS mais simples assim, container mais leve).
- API: schemas Pydantic em `services/api/schemas.py` são uma camada de
  tradução — o domínio (`src/`) usa dataclasses e não conhece a API.
- Prioridades: P1≥70, P2 50-70, P3 25-50, P4<25.
- Categorias tácticas por comprimento de chama: <1.2m manual; 1.2-2.4m
  direto difícil; 2.4-3.4m máquinas; >3.4m indireto.

## Testes

- `test_pipeline.py`, `test_aggregation.py` — motor de fogo (sem Postgres)
- `test_parser_offline.py` — parser fogos.pt com payload cacheado
- `test_api_smoke.py`, `test_api_integration.py` — API (TestClient, mocks)
- `test_e2e_postgres.py` — cadeia completa (precisa de Postgres)
- `test_open_meteo.py` — fluxo de meteo (precisa de Postgres)
- `test_fogos_client.py` — cliente fogos.pt (precisa de internet)

Antes de dar por concluída uma alteração, correr pelo menos
`test_api_integration.py` e, se mexeu na BD, `test_e2e_postgres.py`.

## Estado atual

Funcional e testado: motor de fogo, worker, schema PostGIS, API REST
(9 endpoints), ingestão fogos.pt, Open-Meteo. Testado localmente em Docker
de ponta a ponta.

Por fazer (próximos passos, por ordem sugerida):
- Setup Railway para deploy (os Dockerfiles e railway.json já existem)
- ForeFire-runner em container (simulação detalhada — estrutura de
  `simulation_jobs` e endpoints `/simulate`, `/jobs` já preparada)
- Validação histórica contra incêndios ICNF
- Frontend desktop (React + MapLibre) — consome a API REST
- Live fuel moisture real (LFMC Sentinel-2) — atualmente é placeholder
- Distância a aglomerados populacionais (CAOP + OSM) para o scoring

## Notas de trabalho

- Ao mexer nos Dockerfiles, não remover o `git` nem o `scikit-learn`.
- Ao criar pools asyncpg, usar sempre `init_pool()`.
- O projeto usa `src/` layout — instalar com `pip install -e .` antes de
  correr testes ou o código não é encontrado.
- Reportar à wildfire_ROS_models (CNRS): bug do `fuelDens_lbft3` mal
  etiquetado, e a dependência hard em TensorFlow no `__init__.py`.
