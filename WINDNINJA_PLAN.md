# Vento de terreno no Simulador — integração WindNinja

**Nota: plano apenas — não implementado ainda.**

## Contexto

Partindo da tese de mestrado de Forthofer (2007, Colorado State
University) sobre modelação de vento em terreno complexo para previsão
de propagação de fogo. A tese descreve dois modelos diagnósticos (CFD
via Fluent, e um modelo "mass-consistent" mais simples baseado no
método variacional de Sasaki 1958) que ajustam um vento uniforme de
entrada para um campo de vento em grelha, tendo em conta o relevo —
mostrando melhorias reais na previsão de propagação (FARSITE) em
terreno complexo.

> **CORRECÇÃO (2026-07-30).** As versões anteriores desta secção
> acrescentavam "sobretudo do lado de sotavento". Isso é enganador para o
> que este plano integra: o modelo **mass-consistent não tem separação
> nem esteira** — é um ajuste puramente cinemático de conservação de
> massa, sem momento. Medido no sidecar: numa crista simétrica, os campos
> de 270° e 90° são **bit a bit idênticos** (|dif| máxima 0.000000 m/s),
> e o mesmo no terreno real do Gerês. O solver é linear, portanto inverter
> a entrada inverte a solução e deixa o módulo inalterado — não há
> assimetria barlavento/sotavento no sentido aerodinâmico.
>
> A melhoria de sotavento que a tese reporta é, muito provavelmente, do
> modelo **CFD**, que este plano põe fora de âmbito.
>
> O que o mass-consistent entrega, e que o sistema hoje não vê de todo:
> **compressão sobre cumeadas** (vales 5.01 → cumes 6.31 m/s),
> **abrigo topográfico** em zonas baixas com terreno alto a barlavento
> (r = −0.62, exposto 6.52 → abrigado >300 m: 3.16 m/s) e
> **canalização** (desvio até 73°). São efeitos reais e grandes; só não
> são o que a frase original prometia.

Confirmado ao ler o código: hoje o Simulador usa vento **espacialmente
uniforme** — um único valor `wind_midflame_ms` (Open-Meteo + WAF
vegetativo, `weather.py:derive_fire_weather`) aplicado a todos os pontos,
tanto na grelha ROS (`_build_ros_grid`) como na propagação
Huygens/Richards (`_propagate`, ambas em `src/fogos_triage/simulation.py`).
Não há qualquer efeito de aceleração/abrigo por relevo — exactamente o
"método tradicional" que a tese mostra ser o menos preciso em terreno
montanhoso (relevante para Alto Minho e para o território nacional).

Uniforme **no espaço**, note-se, não no tempo: a propagação já varia o
vento hora a hora, e é essa distinção que define o âmbito deste plano
(ver a secção seguinte).

O modelo "mass-consistent" descrito na tese é, na prática, a pesquisa
fundadora do **WindNinja** — ferramenta open-source (MIT) do mesmo
laboratório (USFS Missoula Fire Sciences Lab), mantida activamente
(v3.13.0.1, package `windninja` em conda-forge, linux-64 confirmado),
com CLI (`WindNinja_cli`) pronta a usar. Decisão: **integrar o
WindNinja em vez de reimplementar o solver FEM/mass-consistent de
raiz** — reimplementar seria um projecto de numérica especializada de
várias semanas, sem dados de validação próprios, com risco real de
bugs subtis (campo de vento errado mas plausível). O WindNinja já
resolve exactamente este problema, validado há 15+ anos.

## Âmbito: uma corrida por hora simulada

**Duas correcções a versões anteriores deste plano (2026-07-29/30).**

**Primeira.** A versão original propunha **uma** corrida de WindNinja por
simulação, com o vento da hora 0, reutilizando esse padrão espacial em
todas as horas. A justificação dada era que isso "espelha uma
simplificação já existente: `_build_ros_grid()` já usa só
`weather_hourly[0]`". Essa justificação estava mal aplicada, e confundia
três sítios que tratam o vento de maneira diferente:

| | vento |
|---|---|
| `_build_ros_grid` (grelha de cor) | hora 0 apenas — `simulation.py:1140` |
| `_build_direction_arrows` (setas) | **por instantâneo** |
| **`_propagate` (o perímetro)** | **hora a hora** — `simulation.py:634` |

A propagação, que é o que define o perímetro, **já respeita** a rotação
horária: `wx = weather_hourly[hour_idx]` está dentro do ciclo. Meter-lhe
um campo estático da hora 0 não espelharia uma simplificação existente —
**introduziria uma regressão de fidelidade** num sítio que hoje está
correcto. E as setas de propagação, que passaram a ser por instantâneo
precisamente porque eram enganadoras quando o vento roda, voltariam ao
mesmo problema por outra via.

### Porque é que isto importa mais para o WindNinja do que para vento uniforme

Um campo mass-consistent **não é um padrão fixo que se escala**: a sua
geometria depende da direcção de entrada. Uma cumeada que acelera vento
de oeste **abriga** vento de leste. Com rotação suficiente, o padrão de
aceleração/abrigo não fica só impreciso — **inverte de sinal** em parte
do terreno, e a assimetria de propagação aponta ao contrário. Que é
exactamente o efeito que esta integração existe para captar.

### Quanto o vento roda, medido

Nas 12 simulações guardadas em `simulation_jobs` (Julho 2026):

| fogo | direcções horárias (de onde vem) | rotação face à hora 0 |
|---|---|---|
| 20261061716 (3h) | 161 → 226 → 280 → 279 | **119°** |
| 20261061716 (12h) | 161 → 226 → 280 → … → 313 | **152°** |
| 20261051486 (3h) | 331 → 333 → 333 → 339 | 8° |
| 20261066106 (3h) | 270 → 267 → 270 → 272 | 3° |

Mediana da rotação total: **119°**. Máxima entre horas consecutivas:
**65°**. Há casos de 3° e 8°, portanto não é sempre um problema — mas a
mediana diz que é mais regra do que excepção.

**Segunda correcção.** A versão seguinte aceitou isto mas montou um
esquema de cache por direcção arredondada aos 22.5°, com escala pela
velocidade, para conter um custo *estimado* de 1-3 minutos por corrida.
Esse custo foi medido e é **~30× menor**, o que torna a cache
complexidade sem retorno — e dispensa a hipótese de linearidade na
velocidade, que era o ponto mais frágil desse desenho. Fica **uma corrida
por hora**, direito.

### O custo, medido

Instalado o `windninja` de conda-forge e cronometrado no terreno real de
Valpaços (DEM extraído do `Landscape_PT_2026_v2_cog.tif`, banda 1,
15×15 km — o `bbox_km` que **todas** as 159 simulações existentes usaram),
1 thread:

| malha | célula | parede | CPU | RSS pico |
|---|---|---|---|---|
| coarse | 237 m | 2.6 s | 1.0 s | 103 MB |
| medium | 150 m | 4.3 s | 2.6 s | 165 MB |
| **fine** | **106 m** | **6.5 s** | **5.0 s** | **255 MB** |

A estimativa anterior ("tipicamente 1-3 minutos") estava errada por ~30×.

Uma corrida por hora com as direcções reais das 12h do 20261061716
(161→226→280→…→313): **13 corridas em 87 s de parede**, 66.8 s de CPU,
255 MB de pico.

**O `mesh_choice` é relativo ao domínio, não absoluto.** Um domínio de
50 km levou 4.9 s — igual ao de 15 km — porque o número de células fica
constante (141×141) e é a célula que cresce (354 m em vez de 106 m). O
custo **não escala com a área**; a resolução é que degrada. Isto importa
porque a propagação não está limitada ao `bbox_km`: para incêndios longos
o domínio tem de crescer, e o preço disso é fidelidade, não tempo.

Reproduzir estas medições:

```bash
mamba create -y -p /tmp/wnenv -c conda-forge windninja   # ~700 MB
export PATH=/tmp/wnenv/bin:$PATH WINDNINJA_DATA=/tmp/wnenv/share/windninja
WindNinja_cli --num_threads 1 --elevation_file dem.tif \
  --initialization_method domainAverageInitialization \
  --input_speed 6 --input_speed_units mps --input_direction 161 \
  --input_wind_height 10 --units_input_wind_height m \
  --output_wind_height 10 --units_output_wind_height m \
  --vegetation grass --mesh_choice fine \
  --write_goog_output false --write_shapefile_output false \
  --write_ascii_output true --output_path out/
```

### Latência e custo no Railway

Impacto no tempo que o utilizador espera (mediana actual dos jobs:
**21.7 s**, n=70):

| duração | corridas | sequencial | 4 em paralelo |
|---|---|---|---|
| 3h | 4 | 47.7 s (**2.2×**) | 28.2 s (1.3×) |
| 6h | 7 | 67.2 s (3.1×) | 33.1 s (1.5×) |
| 12h | 13 | 106.2 s (4.9×) | 42.8 s (2.0×) |

Custo (Railway: 10 USD/GB-mês de RAM, 20 USD/vCPU-mês):

| | custo |
|---|---|
| por simulação de 3h | $0.00023 |
| por simulação de 12h | $0.00073 |
| mensal a ~300 simulações/mês (ritmo actual) | **$0.07 a $0.22** |
| **ter o contentor de pé (idle 120-300 MB)** | **$1.17 a $2.93/mês** |

**O contentor parado custa 5 a 40× mais do que todo o cálculo.** O que se
paga é a existência do sidecar, e isso é fixo — não depende de quantas
simulações se corram. Se o Railway permitir adormecer o serviço, é aí que
está a economia, não em reduzir corridas.

Sequencial é o ponto de partida: 2.2× numa simulação de 3h não justifica
a complexidade de paralelizar, e paralelizar N corridas multiplica o pico
de memória por N. Revisitar só se as simulações longas se tornarem comuns.

### Opt-in, mas não pelo custo

Mantém-se `use_windninja: bool = False`, ao lado de
`use_gusts`/`fuel_moisture_scenario`. A justificação **não** é o tempo de
execução (2.2× não justifica esconder a funcionalidade) mas a **nova
dependência externa**: um sidecar que pode estar em baixo, com um solver
cujo output ainda não foi validado contra nada. Quando houver confiança no
campo de vento, reavaliar se passa a ser o comportamento por omissão.

## Arquitectura

### 1. Novo serviço `services/windninja/` (sidecar)

O WindNinja não é instalável via `apt`/`pip` (stack actual de todos os
Dockerfiles) — só via conda-forge. Em vez de poluir a imagem
`python:3.12-slim` da API com conda, isolar num container próprio,
seguindo o padrão já usado para `postgres`/`redis` no
`docker-compose.yml` (serviços externos próprios, não misturados no
código Python da app):

- `services/windninja/Dockerfile`: base `condaforge/miniforge3`,
  `conda install -c conda-forge windninja` (v3.13.0.1, MIT, linux-64
  confirmado via conda-forge), mais um wrapper HTTP fino
  (`services/windninja/main.py`, FastAPI — mesma lib já usada na API).
> **CORRECÇÃO (2026-07-30): o DEM vai por HTTP, não por volume
> partilhado.** As versões anteriores deste plano diziam que o sidecar
> lia o raster do mesmo volume `./data:/data:ro` que o `worker` e a `api`
> montam. Isso funciona em `docker-compose` local mas **não no Railway**:
> a documentação é explícita — *"Each service can only have a single
> volume"* — e os volumes não se partilham entre serviços (o
> `railway volume list` mostra cada um "Attached to" um único serviço).
>
> As alternativas eram dar ao sidecar um volume próprio e mandá-lo
> descarregar os mesmos 3.87 GB do R2 — duplicar os dados e o custo — ou
> enviar a janela do DEM no pedido. **A segunda é melhor e é a
> escolhida**: uma janela de 15 km a ~37 m são 400×400 float32 = 640 KB,
> desprezável na rede privada do Railway, e o sidecar fica **sem estado**
> — sem volume, sem R2, sem provisionamento de landscape num terceiro
> serviço. O `LandscapeReader.read_window` já faz o recorte, e o
> parâmetro `max_dim` (acrescentado a 2026-07-29) já limita a resolução.

- Endpoint único `POST /run`: recebe a **janela do DEM** (array de
  elevações + `transform` + dimensões), `input_speed_ms`,
  `input_dir_deg`, `input_height_m` (10 m, igual ao Open-Meteo) e a
  malha. Escreve o DEM num GeoTIFF temporário, invoca `WindNinja_cli`
  via subprocess em modo domain-average (sem estações/WRF — o mais
  simples e mais rápido), devolve os rasters de saída (velocidade +
  direcção) como arrays JSON (mesma filosofia de payload já usada em
  `_build_ros_grid`, não GeoTIFF — evita mais uma dependência de parsing
  no lado da API).

> **ARMADILHA — `--output_speed_units` tem default `mph`.** Mesmo dando
> `--input_speed_units mps`, a saída vem em milhas por hora. Uma corrida
> com entrada de 6.0 m/s devolveu média 12.73 (mph); com
> `--output_speed_units mps`, 5.69 m/s. Ler a saída como m/s sem passar a
> flag **sobrestima o vento em 2.2369×** — e seria um erro silencioso e
> catastrófico, porque o campo continuaria a parecer plausível e o fogo
> propagaria ao dobro. Passar a flag **e** afirmá-lo num teste.

- Sem volume, o sidecar também não tem custo de armazenamento nem
  arranque lento à espera de descarregar 3.87 GB — só a RAM enquanto está
  de pé (ver "Latência e custo no Railway").
- Outra armadilha, menor: o `.prj` que o WindNinja escreve ao lado dos
  `.asc` é lido pelo GDAL como `EngineeringCRS`, não como EPSG:3763, e
  qualquer `reproject` a partir dele falha com
  `Cannot find coordinate operations`. Como a saída está no mesmo CRS do
  DEM de entrada, o sidecar deve ignorar o `.prj` e devolver só os arrays
  mais o `window_transform`, que é o que o `WindField` precisa.
- `docker-compose.yml`: novo serviço `windninja`, **sem volume nenhum**
  (é sem estado); `api` ganha `WINDNINJA_URL` (env var) +
  `depends_on: windninja` (sem `condition: service_healthy` estrito —
  a integração deve falhar aberta, ver secção seguinte).

### 2. `src/fogos_triage/windfield.py` (novo módulo, biblioteca pura)

Mesma filosofia dos módulos "fonte única de verdade" já estabelecidos
(`severity.py`, `fuel_moisture_scenarios.py`):

- `WindField` — dataclass com os arrays de velocidade/direcção +
  `window_transform` (mesmo contrato de `LandscapeReader.read_window`)
  e um método `sample(x, y) -> tuple[float, float]` (velocidade m/s,
  direcção deg) por coordenada projectada — espelha
  `_lookup_cached_terrain` em `simulation.py`.
- `WindFieldSet` — uma lista de `WindField`, **um por hora simulada**,
  mais `sample(x, y, hora)`. Sem arredondamento de direcções, sem escala
  pela velocidade, sem lógica de cache: com 6.5 s por corrida não há nada
  a optimizar, e a versão simples não tem hipóteses por verificar.
- `fetch_wind_fields(windninja_url, elevation_path, bbox, weather_hourly)
  -> Optional[WindFieldSet]` — uma chamada ao sidecar por hora, em série,
  via `httpx` (já é dependência da API). **Falha aberta**: em caso de
  erro/timeout/serviço em baixo devolve `None` e a simulação continua com
  vento uniforme — mesmo padrão de fallback já usado no resto da app
  (Open-Meteo, `fetch_precipitation_sum`). Se falhar a meio, devolve
  `None` e não um conjunto parcial: metade das horas com relevo e metade
  sem seria pior do que nenhuma, e mais difícil de diagnosticar.

### 3. `src/fogos_triage/simulation.py`

- `run_simulation_sync`/`run_simulation_async` ganham
  `wind_fields: Optional[WindFieldSet] = None`.
- `_build_ros_grid()`: se dado, para cada ponto da grelha faz
  `wind_fields.sample(x, y, wx0)` em vez do escalar constante. Continua
  a ser hora 0 aqui, porque a grelha inteira é hora 0 — mudar isso é
  assunto de `SIMULATION_HOURLY_GRID_PLAN.md`, não deste plano.
- `_propagate()`: dentro do ciclo de vértices,
  `wind_fields.sample(x_cur, y_cur, hour_idx)` substitui
  `wind_mf`/`wind_dir`. O `hour_idx` já é calculado ali
  (`simulation.py:634`) para escolher a meteo da hora — reutiliza-se o
  mesmo índice, e o campo de vento fica alinhado com a meteo por
  construção. É este o ponto onde a corrida por hora paga: o perímetro
  passa a ver relevo *e* rotação horária, em vez de um dos dois.
- `_build_direction_arrows()`: já recebe `steps` com a meteo por
  instantâneo, portanto ganha o campo pelo mesmo mecanismo — sem isto as
  setas passariam a discordar do perímetro que as acompanha.
> **CORRECÇÃO (2026-07-30): não há WAF por píxel a respeitar.** As
> versões anteriores desta secção diziam que a velocidade do WindNinja
> "tem de passar pelo mesmo WAF vegetativo já usado hoje", e faziam disso
> um pré-requisito: ler `stand_height` e `canopy_cover` por píxel. A
> premissa é falsa. Medido:
>
> | caminho | chamada a `derive_fire_weather` | WAF |
> |---|---|---|
> | triagem (`triage.py:64`) | com altura/cobertura/coberto | **por píxel**, 0.14 a 0.50 |
> | **simulação** (`routes_meta.py:366`, `routes_freesim.py:280`) | só humidades vivas | **constante 0.40** |
>
> A simulação já ignora o WAF vegetativo por completo — aplica 0.40 em
> todo o território. Portanto:
>
> - **Aplica-se o mesmo 0.40 à velocidade do WindNinja.** A única
>   diferença entre ligar e desligar passa a ser o campo espacial, o que é
>   o que torna a fase 5 interpretável: uma mudança no perímetro só pode
>   vir do relevo. Introduzir WAF por píxel ao mesmo tempo daria duas
>   causas possíveis e nenhuma maneira de as separar.
> - **A fase 3a desaparece.** Não é preciso ler bandas extra, nem pagar
>   esse custo nas simulações com o WindNinja desligado.
>
> **Fica registada uma inconsistência real, agora com plano próprio:**
> para o mesmo ponto num pinhal denso, a triagem usa WAF 0.14 e a
> simulação 0.40 — quase 3x o vento midflame, em dois números que o
> sistema mostra lado a lado ao mesmo utilizador. Isso, mais um factor
> 1.15 em falta na conversão de 10 m para 20 pés e a escada de `if` em
> vez da fórmula de Albini & Baughman, estão em **`WAF_PLAN.md`**.
>
> Esse trabalho vem **depois** desta integração estar validada: as duas
> alterações mexem no mesmo número (o vento midflame) e, feitas juntas,
> tornam impossível atribuir uma mudança nos perímetros a uma delas.
- Sem `wind_fields`, comportamento actual inalterado byte a byte.
- `meta` ganha `"wind_field_source": "windninja" | "uniforme"` e
  `"wind_field_runs": <n>` (quantas corridas foram feitas, = número de
  horas) — mesmo padrão de transparência de
  `use_gusts`/`fuel_moisture_scenario` já exposto ao frontend.

### 4. `services/api/routes_meta.py` / `routes_freesim.py`

Depois de `ensure_landscape` e **depois de `weather_hourly` estar
construído** (incluindo o `gust_weather` e o cenário de humidades, que já
alteram o vento), antes de `run_simulation_async`: se
`payload.use_windninja`, chamar `fetch_wind_fields(...)` com o caminho do
raster de elevação (já resolvido via `rasters_kwargs`) e a **série
horária inteira** — é dela que saem as direcções a resolver. Passar o
resultado (`WindFieldSet` ou `None`) a `run_simulation_async`. Mesmo
padrão dos blocos `if use_gusts: ...` / `if fuel_moisture_scenario: ...`
já existentes nos dois ficheiros.

A ordem importa: com `use_gusts`, o vento de cada hora é o de rajada, e
é esse que tem de alimentar o WindNinja — chamar antes daria os campos
para o vento sustentado.

`services/api/schemas.py`: `SimulationRequest`/`FreeSimulationRequest`
ganham `use_windninja: bool = False`.

### 5. Frontend

- `FuelMoistureScenarioSelect`-style checkbox nova, "Vento de terreno
  (WindNinja)", ao lado do checkbox "Usar rajadas" já existente em
  `SimulacaoView.jsx`/`SimuladorLivreView.jsx`.
- `api.js`: `postSimulate`/`postFreeSimulate` passam `use_windninja`.
- Rodapé de meta do resultado: mostrar `result.meta.wind_field_source`
  ("Vento: WindNinja (terreno)" vs "Vento: uniforme"), mesmo padrão já
  usado para `fuel_moisture_scenario`.
- Aviso de tempo de execução mais longo quando o checkbox está activo.
  **Com os números medidos**: uma simulação de 3h passa de ~22 s para
  ~48 s, e uma de 12h para ~106 s. Não escrever "1-3 minutos por corrida"
  como a versão anterior deste plano dizia — era errado por ~30× e
  assustaria sem razão.
- **Avisar quando foi pedido e não foi cumprido.** Se o sidecar falhar, a
  simulação corre com vento uniforme e regista-o no
  `meta.wind_field_source` — mas quem marcou a caixa pode não olhar para
  lá e assumir que teve vento de terreno. Quando
  `use_windninja == true` e `wind_field_source == "uniforme"`, o rodapé
  tem de o dizer de forma visível, não só registar. É a diferença entre
  falhar aberto e falhar em silêncio.

## Ficheiros principais

- Novo: `services/windninja/Dockerfile`, `services/windninja/main.py`
- Novo: `src/fogos_triage/windfield.py`
- `src/fogos_triage/simulation.py` — `_build_ros_grid`, `_propagate`,
  `run_simulation_sync`/`async`, `terrain_cache`/`_refresh_terrain_cache`
  (incluir `stand_height`/`canopy_cover` na leitura)
- `services/api/schemas.py`, `routes_meta.py`, `routes_freesim.py`
- `docker-compose.yml`
- `frontend/src/components/SimulationPanels.jsx`,
  `frontend/src/views/SimulacaoView.jsx`,
  `frontend/src/views/SimuladorLivreView.jsx`, `frontend/src/api.js`

## Ordem de implementação

As secções acima estão organizadas por componente. Esta é a ordem de
execução, com as paragens de decisão marcadas — o ponto é **não construir
as fases 2-5 antes de a fase 1 provar que o campo de vento vale alguma
coisa**.

### Fase 1 — Provar o sidecar, isolado (sem tocar na app)

`services/windninja/Dockerfile` + `main.py` com o `POST /run`, e o
serviço no `docker-compose.yml`.

> **PARAGEM DE DECISÃO — PASSOU (2026-07-30).**
>
> Validada a **qualidade** do campo antes de escrever o sidecar (a
> validação não precisa dele: corre-se o `WindNinja_cli` directamente).
> Serra do Gerês, 15×15 km, 1335 m de amplitude altimétrica, entrada
> uniforme de 6.0 m/s de 270° (oeste), malha `fine`:
>
> | teste | resultado |
> |---|---|
> | campo não-uniforme | 0.62 a 10.61 m/s (dp 27% da média) |
> | aceleração em cumeadas | vales 5.01 → encostas 5.86 → cumes 6.31 m/s |
> | **abrigo a sotavento** | exposto 6.52 → abrigado >300 m: **3.16 m/s**, r = −0.62 |
> | canalização | desvio mediano 5°, p90 17°, máx 73° |
>
> O abrigo mede-se por *"há terreno mais alto a barlavento?"* — a altura
> do terreno a oeste acima da célula, em janelas de 1/2/4 km. Monótono e
> estável nas três janelas.
>
> **Nota metodológica:** uma primeira tentativa classificou
> barlavento/sotavento pelo sinal do gradiente numa célula e deu razão
> 1.01 — nenhum efeito. Estava errada, não o modelo: o gradiente local
> mistura escalas (uma lomba pequena numa encosta grande). Quem repetir
> isto deve usar a obstrução a barlavento, não o declive.

### Fase 2 — A biblioteca (`windfield.py`)

`WindField`, `WindFieldSet`, `fetch_wind_fields`. Testável contra o
sidecar local sem passar pela simulação (ponto 2 da verificação),
incluindo os dois modos de falha: sidecar em baixo e falha a meio das
horas.

### Fase 3 — O motor (`simulation.py`)

A parte mais delicada, e com um pré-requisito que as versões anteriores
deste plano subestimavam:

1. **O WAF vegetativo primeiro.** `stand_height` e `canopy_cover` por
   píxel não são lidos em lado nenhum hoje (`_TERRAIN_FIELDS` é
   `["slope", "aspect", "fuel_model"]`). Sem isto, a velocidade a 10 m do
   WindNinja não se converte em midflame. Vem antes dos três
   consumidores.
2. `_propagate()` — reutilizar o `hour_idx` já existente.
3. `_build_ros_grid()` (fica em hora 0) e `_build_direction_arrows()`
   (por instantâneo).

> **PARAGEM.** Ponto 4 da verificação: sem `wind_fields`, output idêntico
> byte a byte. Não avançar com uma regressão no caminho por omissão, que
> é o que 100% das simulações usam hoje.

### Fase 4 — API e frontend

`use_windninja` nos dois schemas, o bloco de chamada **depois** do
`weather_hourly` construído (ver secção 4 — a ordem importa por causa do
`use_gusts`), checkbox, `meta` no rodapé e o aviso de fallback.

### Fase 5 — Validar que serve para alguma coisa

Pontos 3, 6 e 7 da verificação: rotação horária aplicada, assimetria
correlacionada com o relevo, e latência medida **no contentor Railway** —
os números desta análise são de uma máquina de 4 cores.

### O risco, dito com clareza

Não é técnico. As peças são conhecidas, o custo está medido e é
desprezável face ao resto da conta. **O que ninguém sabe ainda é se o
campo de vento melhora as previsões em Portugal.** A tese do Forthofer
mostra que melhora em terreno complexo nos EUA e não há razão para
duvidar — mas não é o mesmo que ter visto. Daí a fase 1 ser uma paragem a
sério e não uma formalidade.

## Verificação

1. **Sidecar isolado**: `docker compose build windninja && docker
   compose up windninja` — confirmar `WindNinja_cli --help` corre
   dentro do container; correr um `.cfg` de teste contra o raster de
   elevação real do Alto Minho (`data/AltoMinho/` ou `data/landscape/`)
   recortado a um bbox pequeno, confirmar output com variação espacial
   (não uniforme) coerente com o relevo (aceleração em cumeadas, abrigo
   em vales).
2. **`windfield.py` isolado**: chamada directa a `fetch_wind_fields`
   contra o sidecar local; confirmar `None` gracioso se o sidecar estiver
   em baixo (parar o container e testar), e `None` — não um conjunto
   parcial — se falhar a meio das horas.
3. **Rotação — o teste que a versão anterior deste plano não teria
   passado.** Simular o fogo 20261061716 a 28/07/2026 15:01 (o vento roda
   161° → 226° → 280°, ver secção de âmbito) e confirmar que o campo
   usado em cada hora é o da direcção dessa hora, não o da hora 0.
   Comparar com uma corrida forçada a campo único: as duas têm de dar
   perímetros visivelmente diferentes; se derem o mesmo, o campo horário
   não está a ser aplicado.
4. **Regressão**: correr uma simulação com `wind_fields=None` (caminho
   por omissão) e confirmar output idêntico ao actual (nenhuma
   simulação existente muda de comportamento sem o opt-in).
5. **Uma corrida por hora, confirmada**: `meta.wind_field_runs` tem de
   ser igual ao número de horas simuladas + 1 (4 para 3h, 13 para 12h).
6. **End-to-end real**: activar o checkbox no Simulador Livre sobre
   terreno do Alto Minho com relevo variado, comparar visualmente o
   perímetro/grelha com e sem WindNinja — o teste mais convincente é
   ver assimetria de propagação correlacionada com o relevo em vez do
   crescimento aproximadamente circular actual.
7. **Latência real no contentor**: cronometrar uma simulação de 3h e uma
   de 12h com o opt-in ligado. Os números da secção de âmbito foram
   medidos numa máquina de 4 cores, não no Railway — confirmar que se
   mantêm na mesma ordem de grandeza, e ajustar o aviso do frontend ao
   que for medido lá.
8. `test_pipeline.py` / `test_api_integration.py` — confirmar sem
   regressões nos testes existentes (que não passam `wind_fields`).

## Fora de âmbito (não implementar agora)

- **Cache de campos por direcção arredondada.** Fazia sentido com o custo
  estimado (1-3 min/corrida); com o custo medido (6.5 s) é complexidade
  sem retorno. Só revisitar se surgirem domínios ou malhas muito mais
  caros do que os medidos.
- **Paralelizar as corridas.** Sequencial custa 2.2× numa simulação de
  3h, e paralelizar multiplica o pico de memória pelo número de corridas
  simultâneas. Revisitar se as simulações de 12h+ se tornarem comuns.
- **Sub-hora.** O timestep da propagação é dinâmico e desce a 0.5 min; o
  campo de vento é por hora, como a meteo. Interpolar campos entre horas
  é outra discussão.
- **Vento de terreno na triagem.** Este plano é só para o Simulador. A
  triagem corre uma vez por ocorrência e amostra uma vizinhança, não uma
  grelha; e está congelada no arranque, portanto o campo de vento seria
  de um instante só. Assunto separado.
- Modo CFD completo do WindNinja (mais lento, precisão adicional
  sobretudo em recirculação de sotavento) — o modo mass-consistent
  (domain-average) é o único considerado neste plano.
- Inicialização por estações meteo ou modelos mesoscala (WRF/HRRR) do
  WindNinja — só o modo domain-average (input único de
  velocidade/direcção, já disponível via Open-Meteo).
