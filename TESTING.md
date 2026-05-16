# Guia de Teste Local — fogos_triage

Guia passo-a-passo para validar o sistema na tua máquina antes do deploy.

Cada secção tem **checkpoints** — o que deves ver se estiver tudo bem — e
uma secção de **troubleshooting** no fim.

---

## Índice

1. [O que vais testar](#1-o-que-vais-testar)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Caminho A — docker-compose (recomendado)](#3-caminho-a--docker-compose)
4. [Caminho B — Postgres local sem Docker](#4-caminho-b--postgres-local-sem-docker)
5. [Testes automatizados](#5-testes-automatizados)
6. [Verificar a base de dados à mão](#6-verificar-a-base-de-dados-à-mão)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. O que vais testar

O sistema tem quatro componentes:

```
   fogos.pt ──▶ worker ──▶ PostgreSQL+PostGIS ◀── API ◀── (futuro: frontend)
   Open-Meteo ──┘
```

- **worker** — vai à fogos.pt a cada 2 min, ingere ocorrências, corre triagem
- **PostgreSQL+PostGIS** — guarda ocorrências, histórico, meteo, triagens
- **API** — expõe os dados em REST para o frontend consumir
- **redis** — fila para simulações ForeFire (ainda não usada)

O objetivo do teste local é ver os quatro a funcionar juntos com dados reais.

---

## 2. Pré-requisitos

**Caminho A (docker-compose):**
- Docker Engine 24+
- docker-compose v2 (`docker compose version`)

**Caminho B (sem Docker):**
- PostgreSQL 16 + PostGIS 3.4
- Python 3.10 ou superior

Verifica:

```bash
docker --version           # caminho A
docker compose version     # caminho A
python3 --version          # caminho B
psql --version             # caminho B
```

---

## 3. Caminho A — docker-compose

**Recomendado.** Sobe os quatro serviços com a configuração já feita.

### 3.1 Preparar

```bash
cd fogos_triage

# Confirmar que o CSV dos modelos está no sítio
ls data/fuel_models_pt.csv
```

> **Checkpoint:** o ficheiro `data/fuel_models_pt.csv` existe. Se não,
> copia-o de onde o tiveres — o worker e a API precisam dele.

### 3.2 Subir o Postgres

```bash
docker-compose up postgres -d
```

A imagem `postgis/postgis:16-3.4` aplica automaticamente o
`migrations/001_initial_schema.sql` na primeira inicialização (o ficheiro
está montado em `/docker-entrypoint-initdb.d`).

Espera ~15 segundos e confirma o schema:

```bash
docker-compose exec postgres psql -U fogos -d fogos -c "\dt"
```

> **Checkpoint:** deves ver 6 tabelas — `occurrences`, `occurrence_history`,
> `weather_snapshots`, `triage_results`, `meteo_cache`, `simulation_jobs`
> (mais `spatial_ref_sys` do PostGIS).
>
> Se aparecer só `spatial_ref_sys`, o schema não foi aplicado — ver
> Troubleshooting, "Schema não foi aplicado".

### 3.3 Subir o worker

```bash
docker-compose up worker
```

Deixa correr em primeiro plano para veres os logs. O worker está em
`DEV_MODE=true` (default no compose) — usa um terreno fixo (MockLandscape)
em vez de ler TIFFs reais.

> **Checkpoint:** nos logs deves ver, por esta ordem:
> ```
> === fogos_triage worker a iniciar ===
> A inicializar pool Postgres...
> Postgres pronto (tentativa 1)
> A carregar modelos de combustível de /data/fuel_models_pt.csv
>   20 modelos carregados
> DEV_MODE — usando MockLandscapeReader (terreno fixo)
> fogos.pt: N ocorrências
> Ciclo concluído em X.Xs: {'fetched': N, ...}
> ```
>
> A cada 120 segundos repete um ciclo. Cada ocorrência relevante
> (Mato, Povoamento, Agrícola) aparece com uma linha de triagem
> `→ P1/P2/P3/P4`. As de prevenção/queimadas aparecem como
> `natureza não relevante`.
>
> `Ctrl-C` para parar — deve terminar graciosamente com
> `Worker terminou graciosamente`.

**Se o worker falhar a aceder à fogos.pt** (erro 403 ou timeout): a API
fogos.pt está atrás de Cloudflare. Ver Troubleshooting, "Worker não acede
à fogos.pt". O resto do sistema testa-se na mesma com o
`test_e2e_postgres.py` (secção 5).

### 3.4 Subir a API

Noutro terminal:

```bash
docker-compose up api -d
```

Testa:

```bash
# Health — sem autenticação
curl http://localhost:8000/health

# Lista de fogos — precisa de API key
curl -H "Authorization: Bearer dev-key-change-me-in-prod" \
  http://localhost:8000/fires
```

> **Checkpoint:** `/health` devolve `{"status":"ok","database_ok":true,...}`.
> `/fires` devolve `{"items":[...],"total":N,...}`.
>
> Se o worker já correu pelo menos um ciclo, `items` terá ocorrências.
> Se não, virá vazio — corre o worker primeiro.

Documentação interativa (Swagger UI):

```
http://localhost:8000/docs
```

Aqui podes experimentar todos os endpoints no browser. Carrega em
"Authorize" e mete a key `dev-key-change-me-in-prod`.

### 3.5 Parar tudo

```bash
docker-compose down

# Para apagar também os dados (recomeçar do zero):
docker-compose down -v
```

---

## 4. Caminho B — Postgres local sem Docker

Para quem prefere correr sem containers.

### 4.1 Criar a base de dados

```bash
# Criar BD
createdb fogos

# Aplicar o schema (cria PostGIS + tabelas)
psql -d fogos -f migrations/001_initial_schema.sql
```

> **Checkpoint:** o output termina com `CREATE VIEW` e não tem erros.
> Confirma: `psql -d fogos -c "\dt"` deve listar as 6 tabelas.

### 4.2 Instalar dependências Python

```bash
# Recomendado: ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar o pacote com todas as dependências
pip install -e ".[full]"
```

> **Checkpoint:** instalação termina sem erros. Inclui rasterio, asyncpg,
> httpx, curl_cffi, fastapi, uvicorn, e a wildfire_ROS_models do GitHub.
>
> Se a wildfire_ROS_models falhar, ver Troubleshooting,
> "Falha a instalar wildfire_ROS_models".

### 4.3 Validar a cadeia com o teste end-to-end

Este teste é o mais importante — valida ingestão → triagem → persistência
contra o teu Postgres real, usando um payload fogos.pt cacheado (não
precisa de internet).

```bash
export FUEL_MODELS_CSV=$PWD/data/fuel_models_pt.csv
export DATABASE_URL=postgresql://localhost/fogos   # ajustar se necessário

python tests/test_e2e_postgres.py
```

> **Checkpoint:** o teste termina com `TESTE END-TO-END PASSOU`. Vais ver:
> - 3 ocorrências parsed
> - triagem de 2 (Mato → P1, Povoamento → P2; a de Prevenção é ignorada)
> - contagens nas tabelas
> - verificação de idempotência (reprocessar não duplica)

### 4.4 Arrancar o worker

```bash
export DATABASE_URL="postgresql://localhost/fogos"
export FUEL_MODELS_CSV=$PWD/data/fuel_models_pt.csv
export DEV_MODE=true
export LOG_LEVEL=INFO

python -m services.worker.main
```

Mesmos checkpoints da secção 3.3.

### 4.5 Arrancar a API

Noutro terminal (com o venv ativado):

```bash
export DATABASE_URL="postgresql://localhost/fogos"
export API_KEYS=dev-key
export FUEL_MODELS_CSV=$PWD/data/fuel_models_pt.csv

uvicorn services.api.main:app --reload --port 8000
```

Testa como na secção 3.4, mas com a key `dev-key`:

```bash
curl http://localhost:8000/health
curl -H "Authorization: Bearer dev-key" http://localhost:8000/fires
```

---

## 5. Testes automatizados

Estes não precisam do worker nem da API a correr.

### Sem Postgres (usam mocks ou payloads cacheados)

```bash
python tests/test_pipeline.py         # motor de triagem, 3 cenários PT
python tests/test_aggregation.py      # agregação multifuel dos modelos
python tests/test_parser_offline.py   # parser do payload fogos.pt
python tests/test_api_smoke.py        # confirma rotas registadas
python tests/test_api_integration.py  # API completa — 28 testes
```

> **Checkpoint:** `test_api_integration.py` termina com
> `RESULTADO: 28 passados, 0 falhados`.

### Com Postgres a correr

```bash
export DATABASE_URL=postgresql://localhost/fogos
python tests/test_e2e_postgres.py     # ingestão→triagem→persistência
```

### Teste do cliente fogos.pt (precisa de internet)

```bash
python tests/test_fogos_client.py
```

> **Checkpoint:** lista ocorrências reais da fogos.pt. Se falhar com
> 403, ver Troubleshooting, "Worker não acede à fogos.pt".

---

## 6. Verificar a base de dados à mão

Útil para confirmar que o worker está mesmo a escrever.

```bash
# docker-compose:
docker-compose exec postgres psql -U fogos -d fogos

# Postgres local:
psql -d fogos
```

Queries úteis:

```sql
-- Quantas ocorrências, por estado
SELECT status_name, count(*) FROM occurrences GROUP BY status_name;

-- Ocorrências ativas com triagem, por prioridade
SELECT fire_id, district, priority_class, priority_score,
       central_flame_length_m
FROM active_fires_with_triage
ORDER BY priority_score DESC NULLS LAST;

-- Histórico de uma ocorrência
SELECT snapshot_at, change_type, status_code, operatives
FROM occurrence_history
WHERE fire_id = '<algum-fire-id>'
ORDER BY snapshot_at;

-- Última triagem de cada fogo
SELECT fire_id, priority_class, fuel_model_code, computed_at
FROM triage_results WHERE is_latest = TRUE;

-- Contagens gerais
SELECT 'occurrences' AS t, count(*) FROM occurrences
UNION ALL SELECT 'triagens', count(*) FROM triage_results WHERE is_latest
UNION ALL SELECT 'weather', count(*) FROM weather_snapshots
UNION ALL SELECT 'historico', count(*) FROM occurrence_history;
```

---

## 7. Troubleshooting

### Schema não foi aplicado

A imagem `postgis/postgis` só corre os scripts de `/docker-entrypoint-initdb.d`
**na primeira inicialização**, quando o volume de dados está vazio. Se já
tinhas subido o Postgres antes (com schema antigo ou vazio):

```bash
docker-compose down -v      # apaga o volume
docker-compose up postgres -d
```

Em Postgres local, aplica à mão:
```bash
psql -d fogos -f migrations/001_initial_schema.sql
```

### Worker não acede à fogos.pt

A API `api-dev.fogos.pt` está atrás de Cloudflare e bloqueia clientes HTTP
comuns por TLS fingerprint. O cliente usa `curl_cffi` para passar
(impersonação de Chrome).

Se mesmo assim falhar com 403:
- Confirma que `curl_cffi` está instalado (`pip show curl_cffi`)
- Pode ser bloqueio de IP. Em produção, contactar a fogos.pt
  (Tiago Henriques) para whitelist, ou usar fonte oficial ANEPC/PROCIV

Entretanto, o resto do sistema valida-se com `test_e2e_postgres.py`,
que usa um payload cacheado e não precisa de internet.

### `column "is_active" does not exist`

A view `active_fires_with_triage` filtra `is_active` e `is_terminated`
internamente e não as expõe como colunas. Queries contra a *view* não
devem referir essas colunas. Se modificaste `routes_fires.py`, verifica
que não reintroduziste essas condições nas queries à view.

### Colunas JSONB vêm como string / erro a ler cenários

O pool tem de registar codecs JSON. Usa sempre `init_pool()` (de
`fogos_triage.db.repository`) ou passa `init=_init_connection` ao
`asyncpg.create_pool`. Sem isso, as colunas `scenarios_json` e
`result_json` vêm como string e a desserialização falha.

### Worker arranca mas diz "schema ainda não criado"

O worker espera até 60s pelo Postgres com schema. Se passa esse tempo:
- Confirma que o Postgres está mesmo a correr (`docker-compose ps`)
- Confirma que o schema foi aplicado (ver "Schema não foi aplicado")

### Falha a instalar wildfire_ROS_models

A `wildfire_ROS_models` instala-se do GitHub e tem uma dependência
opcional em TensorFlow. O nosso código faz *stub* do TensorFlow, por
isso **não precisas de o instalar**. Se a instalação falhar por outra
razão, instala sem dependências e depois o resto:

```bash
pip install --no-deps git+https://github.com/forefireAPI/wildfire_ROS_models.git
pip install numpy scipy   # dependências reais que ela usa
```

### API responde 401 em tudo

Falta o header de autenticação ou a key está errada. Todos os endpoints
exceto `/health` precisam de:
```
Authorization: Bearer <key>
```
A key vem da env var `API_KEYS`. No docker-compose é
`dev-key-change-me-in-prod`; no caminho B é o que puseste em `API_KEYS`.

Para desligar a autenticação em testes locais: `REQUIRE_AUTH=false`.

### A porta 8000 ou 5432 já está ocupada

Outro processo está a usá-las. Ou paras esse processo, ou mudas o
mapeamento no `docker-compose.yml` (ex: `"8001:8000"`).

### Em maio/inverno quase não há triagens

Fora da época de fogos, a maioria das ocorrências fogos.pt são queimadas
e ações de prevenção (naturezas 3109, 3111, 4335), que **não disparam
triagem** por design. É esperado ver muitos `natureza não relevante`.
No verão a proporção inverte-se.

---

## Resumo rápido

```bash
# Caminho mais curto para ver tudo a funcionar:
cd fogos_triage
docker-compose up postgres -d        # base de dados
sleep 15
docker-compose up worker             # ver logs do polling (Ctrl-C para sair)
docker-compose up api -d             # API em background
open http://localhost:8000/docs      # explorar a API

# Validar a cadeia sem depender da fogos.pt:
export DATABASE_URL=postgresql://localhost/fogos
python tests/test_e2e_postgres.py    # (precisa de Postgres a correr)
```
