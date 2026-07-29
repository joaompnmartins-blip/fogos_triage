# Plano: substituir o VIIRS/Yebra por climatologia sazonal + precipitação acumulada

**IMPLEMENTADO a 2026-07-29.** Ver a secção final para o que ficou
diferente do plano e o que continua em aberto.

Substituir a estimativa de humidade dos combustíveis vivos (LFMC) por um
modelo ajustado a medições de campo portuguesas, eliminando o Google
Earth Engine do caminho crítico.

Análise feita a 2026-07-29. Dados de campo em `LFM/`
(`lfmc_pt_field_measurements_clean.csv`, 1339 medições ICNF 2019–2022,
9 espécies, 26 sítios).

---

## O problema

`_viirs_fmc_sync` (`src/fogos_triage/weather.py`) estima o LFMC por
VIIRS + regressões de Yebra et al. (2007). Validado contra 654 medições
de campo em 338 pares (sítio, data), sai isto:

| | campo | modelo | viés | RMSE | r |
|---|---|---|---|---|---|
| **herbáceo (G4)** | média 52.9% | média 163.2% | **+110 pp** | **122 pp** | **−0.03** |
| lenhoso (S4) | média 94.0% | média 93.3% | −2.5 pp | 31.1 pp | +0.40 |

O herbáceo não é impreciso — é **correlação zero**. Num caso (Lamares,
04/08/2021) o campo mediu 9% e o modelo devolveu 110%.

**Mecanismo da falha.** No pico do Verão o termo sazonal do G4 zera
exactamente (DJ 209–227 → 0.000), portanto o valor reduz-se a
`27.95 + 331.86·NDVI − 1.194·Ts`. O NDVI é uma média de 16 dias num raio
de 1 km — mede o verde de tudo o que lá está, sobretudo árvores e matos.
Em Julho a herbácea está morta e as árvores continuam verdes: NDVI alto
dá "herbácea húmida" precisamente onde ela está mais seca. Confirma-se
no sinal — NDVI contra campo herbáceo dá **r = −0.29**, ao contrário do
+331.86 que o modelo assume.

**Consequência operacional.** Pela função de cura de Andrews 2018
(`T = −1.11·M + 1.33`, limitada a [0,1]), o valor que produção devolveu
a 28/07/2026 (138.6%) satura em **0% de carga transferida** — herbácea
totalmente verde o Verão inteiro. O campo (52%) daria 75%. Efeito no
motor, com tudo o resto igual (35 °C, 20% HR, mortos 6/7/9%,
vento midflame 2.4 m/s, declive 8°):

| modelo | LFMC 138.6% | LFMC 52% | diferença |
|---|---|---|---|
| **FM231** | ROS 1.39 m/min, chama 0.3 m | ROS **24.15**, chama 2.3 m | **+1644%** |
| **FM232** | ROS 1.02, chama 0.2 m | ROS **20.60**, chama 1.4 m | **+1924%** |
| FM225 | 6.07 | 11.15 | +84% |
| FM226 | 2.51 | 4.00 | +59% |
| FM235 | 0.98 | 1.26 | +28% |

0.3 m de chama é ataque manual directo; 2.3 m já é "directo difícil a
máquinas". O sistema está a classificar como controlável o que não é.

---

## O que foi testado e rejeitado

Vale a pena registar, para ninguém repetir:

**1. Os modelos MODIS que os autores recomendam (G2/S2).** Piores, não
melhores. O `MOD09GA`/`MYD09GA` está disponível a 500 m com todas as
bandas para VARI e GVMI (e o `VNP09GA` também tem as bandas M
equivalentes), mas nos mesmos 40 pares:

| | S4 actual | S2 recomendado |
|---|---|---|
| matos | RMSE 21.1 | RMSE **82.6** |
| herbáceo (G4 vs G2) | RMSE 121.8 | RMSE **159.2** |

Yebra 2007 foi calibrado no Parque Nacional de Cabañeros, centro de
Espanha. Os interceptos não transferem: `−129.12 + 503.51·NDVI` com o
NDVI português (média MODIS 0.57) rebenta para 208% onde o campo mede
53%. **O problema nunca foi o sensor.**

**2. Índices espectrais em geral.** Correlação com o campo:

| | herbáceo (n=17) | matos (n=40) |
|---|---|---|
| MODIS NDVI | +0.04 | +0.28 |
| MODIS VARI | +0.22 | −0.08 |
| MODIS GVMI | −0.00 | +0.12 |
| **Ts (temp. superfície)** | **−0.51** | **−0.30** |
| **dia juliano** | **−0.53** | **−0.34** |

Os índices de verdura, onde os modelos põem quase todo o peso, não têm
sinal. Recalibrá-los localmente também não é viável: o dataset **não
tem coordenadas** (ver `LFM/README_lfmc_pt.md`), e medi a sensibilidade
— um erro de ±2 km na localização injecta ±30 pp no preditor herbáceo,
que é a totalidade do sinal. Para o lenhoso seria tolerável (±3.7 pp).

**3. Regiões administrativas (NUTS III ou núcleos ICNF).** Entre
núcleos, a correlação entre precipitação e LFMC é **r = +0.18**. Tâmega
e Sousa tem 858 mm de P180 e LFMC 118.6%; Médio Tejo tem 268 mm e
123.0%. Mais seco não dá combustível vivo mais seco *entre sítios*.
Acresce que as agregações do ICNF são administrativas (quem responde a
quem), mudam por Deliberação, e o dataset já está desactualizado num
ponto (Beira Baixa separou-se de Beiras e Serra da Estrela).

**4. Normais climáticas do local.** Testado com normais WMO de 30 anos
(1991–2020, ERA5 via Open-Meteo). Precipitação anual, aridez P/ET0 e
temperatura do mês mais quente **pioram** a previsão. Leitura provável:
aclimatação — cada comunidade vegetal ajusta-se ao seu clima e mantém-se
perto do seu óptimo.

**5. P180 como anomalia local** (rácio face à normal do sítio). Pior que
o P180 absoluto, mesmo com normais de 30 anos (28.5 vs 27.1 nos matos;
44.1 vs 35.0 no herbáceo). 180 mm de chuva parecem ser 180 mm de água no
solo, independentemente de o sítio ser habitualmente húmido ou seco —
pelo menos na gama coberta (537 a 1589 mm anuais).

---

## O modelo escolhido

```
LFMC = a0 + a1·cos(θ) + a2·sin(θ) + a3·cos(2θ) + a4·sin(2θ) + β·P180
       onde θ = 2π · dia_do_ano / 365
             P180 = precipitação acumulada nos 180 dias anteriores (mm)
```

Ajustado **por grupo de combustível**, sem região e sem normais.

### Porque é este

Corrida final, 654 medições / 338 pares, mesmo conjunto para todos os
modelos, CV honesta (a climatologia é ajustada nos dados, o S4 não —
por isso a climatologia é sempre validada fora da amostra):

**Lenhoso, prever a próxima época (deixa-um-ano-de-fora):**

| modelo | viés | RMSE | MAE | r |
|---|---|---|---|---|
| S4 VIIRS (produção) | −2.5 | 31.1 | 23.7 | +0.403 |
| climatologia só | −0.0 | 33.0 | 25.1 | +0.281 |
| **climatologia + P180** | −0.6 | **27.5** | **20.9** | **+0.573** |
| constante | −0.2 | 34.9 | 27.1 | −0.226 |

**Lenhoso, prever uma região nova (deixa-um-núcleo-de-fora):**

| modelo | viés | RMSE | MAE | r |
|---|---|---|---|---|
| S4 VIIRS | −2.5 | 31.1 | 23.7 | +0.403 |
| **climatologia + P180** | +0.4 | **29.1** | **21.7** | **+0.515** |

Ganha nas quatro combinações de validação e agregação. Ao nível de média
por sítio-data mantém-se (23.4 vs 26.2, e 25.6 vs 26.2).

**Herbáceo:** climatologia + P180 dá RMSE 32.5 contra 121.8 do G4 —
melhor por um factor de ~4.

O ganho vem quase todo do P180, e é variação **interanual**:

| ano | P180 médio | LFMC campo (Verão) |
|---|---|---|
| 2020 | 496 mm | 104.5% |
| 2021 | 604 mm | 99.5% |
| **2022** | **308 mm** | **81.6%** |

Repare-se que a constante tem **correlação negativa**: prever sempre a
média anda ao contrário do campo quando o ano de teste é
sistematicamente mais húmido ou mais seco. É essa variação que o P180
apanha.

### Coeficientes ajustados (referência, a refazer na implementação)

Ajuste a todos os dados, P180 em mm:

```
herbáceo  n=125  DJ 97-272
  a0=-101.9798  cos1=-195.9519  sin1=-37.9407
  cos2=-66.9916  sin2=-61.7614  β=+0.077718

lenhoso   n=654  DJ 11-351
  a0=+84.6538   cos1=+13.1909   sin1=+11.8008
  cos2=+3.8432  sin2=-6.0341    β=+0.057289
```

Domínio do ajuste (fora disto é extrapolação):
P180 137–1512 mm (lenhoso), 227–1486 mm (herbáceo);
LFMC de campo 20–235% (lenhoso), 9–254% (herbáceo).

---

## Mapeamento grupo de campo → escalar do motor

| grupo | n | escalar |
|---|---|---|
| Matos atlânticos (Urze, Carqueja, Tojo) | 697 | `live_w_pct` |
| Matos mediterrânicos (Esteva, Carrasco) | 274 | `live_w_pct` |
| Herbáceas | 130 | `live_h_pct` |
| Pinhais (P. bravo) | 128 | **nenhum** |
| Giestais | 71 | **nenhum** (testado: piora 27.5→28.0) |
| Outro (Eucalipto) | 37 | **nenhum** |

**Pinhais e Eucalipto ficam de fora por razão física, não por falta de
dados:** são folhagem de **copa**, e o `LiveW_FL` de um modelo Rothermel
é a folhagem viva do **leito de superfície** (sub-coberto). A humidade de
copa entra noutro sítio do motor — a transição para fogo de copas de Van
Wagner. As 128 medições de P. bravo e 37 de eucalipto ficam disponíveis
se algum dia se quiser alimentar esse caminho.

**Não separar atlânticos de mediterrânicos.** Testado: 33.2 contra 33.0
de uma curva única — ganho nulo. Os dois escalares que já existem são a
granularidade que a evidência justifica. Também não vale variar por
píxel.

---

## A restrição do herbáceo

Cobertura mensal das medições:

| | Jan | Fev | Mar | Abr | Mai | Jun | Jul | Ago | Set | Out | Nov | Dez |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Herbáceas | 0 | 0 | 0 | 2 | 21 | 30 | 49 | 26 | 2 | 0 | 0 | 0 |
| Matos | 15 | 23 | 21 | 22 | 98 | 121 | 278 | 215 | 126 | 40 | 8 | 4 |

**Não há uma única medição de herbáceas entre Outubro e Março.** Deixar
a harmónica extrapolar nesse vazio produz lixo:

| mês | herbáceo previsto | campo |
|---|---|---|
| Jan | **−354%** | sem dados |
| Mar | **−139%** | sem dados |
| Jul | 45.4% | 61% (n=63) |
| Ago | 36.8% | 44% (n=35) |
| Dez | **−269%** | sem dados |

Dentro da janela a curva segue bem o campo; fora dela é inutilizável.

**Decisão a tomar na implementação:** limitar o herbáceo a Abril–Setembro
e assumir um valor declarado fora dessa janela. O valor fisicamente certo
é "verde" — LFMC alto, cura 0 — que é o que a herbácea faz no Inverno
português depois das chuvas. Coincide com a época de fogos, por isso não
é uma limitação grave; mas tem de ser explícito e não implícito.

O lenhoso não tem este problema: 96% previsto em Julho contra 101% de
campo, 87% em Agosto contra 88%, e plausível o ano inteiro.

---

## Implementação

### Peças

**1. `data/lfmc_climatologia_pt.csv`** — uma linha por grupo
(`herbaceo`, `lenhoso`) com os 5 coeficientes harmónicos, o β do P180, e
os metadados de proveniência: `n`, `rmse_cv`, `dj_min`, `dj_max`,
`p180_min`, `p180_max`, `fonte`. Mesmo padrão de `fuel_models_pt.csv` e
`modelos_combustivel_PT_cores.csv` — um ficheiro que o utilizador abre e
critica, com a incerteza à vista.

**2. `scripts/ajusta_lfmc_climatologia.py`** — reajusta o CSV a partir de
`LFM/`. Necessário quando chegarem dados de 2023+, e serve de registo
reproduzível de como os coeficientes saíram.

**3. `src/fogos_triage/lfmc_climatologia.py`** — carrega o CSV e expõe:

```python
def lfmc_climatologia(data: datetime, p180_mm: float) -> tuple[float, float]:
    """Devolve (live_h_pct, live_w_pct)."""
```

Com os limites do domínio aplicados (janela do herbáceo, gama do P180) e
sem efeitos secundários — é biblioteca pura, `src/` não conhece HTTP.

**4. Obter o P180.** Nova função em `weather.py`, ao lado de
`fetch_open_meteo_archive`:

```python
async def fetch_precipitation_sum(lat, lon, ate: datetime, dias: int = 180) -> float
```

O `archive-api.open-meteo.com/v1/archive` com `daily=precipitation_sum`
já cobre 1940 até hoje, sem autenticação. **Atenção ao rate limiting** —
apanhado durante a análise: 429 ao fim de 6–7 pedidos seguidos. Precisa
de retry com backoff.

**5. Pontos de integração** — os três sítios onde hoje entra o VIIRS:

- `services/worker/main.py` — a triagem. Substituir
  `fetch_live_fmc_viirs(...)` pelo par climatologia + P180.
- `services/api/routes_meta.py` — `/simulate`. Já foi alterado
  (commit `e46831e`) para chamar o VIIRS com o `start_time`; passa a
  chamar a climatologia com a mesma data.
- `services/api/routes_freesim.py` — Simulador Livre. Idem.

O encaixe é directo porque `derive_fire_weather(wx, live_h_pct=...,
live_w_pct=...)` já recebe exactamente os dois escalares.

### Vantagens colaterais

- **O GEE sai do caminho crítico.** Menos uma dependência
  (`earthengine-api`), menos credenciais (`GEE_SERVICE_ACCOUNT`,
  `GEE_KEY_JSON`), menos um modo de falha silencioso. O Open-Meteo de
  arquivo — que já usamos — passa a ser a única fonte externa.
- **Cobertura histórica.** ERA5 vai a 1940; o `VNP09GA` só existe desde
  2012 e o `MOD09GA` desde 2000. Uma simulação de um incêndio de 1995
  tem P180 e não tem satélite nenhum. Casa com o `start_time` que já
  existe.
- **Barato.** Uma chamada de arquivo por ocorrência — possível
  precisamente porque a triagem passou a ser congelada no arranque
  (commit `48b04a8`). O P180 e a harmónica não mudam de forma apreciável
  em 3 ou 24 horas, por isso um valor por simulação chega; não é preciso
  recalcular por hora como nas humidades mortas.

### O que NÃO fazer

- **Não emitir bandas de incerteza.** Se a climatologia é a fonte, o
  valor dela entra na função de cura tal e qual. Os cenários que o
  sistema já tem (central/rajadas) são condições físicas alternativas,
  não bandas — e as humidades mortas, o vento e o modelo de combustível
  também têm erro e não são hedgeados. Quem quiser explorar
  sensibilidade já tem `apply_fuel_moisture_scenario` (cenários
  BehavePlus) e o ficheiro `.FMS`, ambos com override das humidades
  vivas. É o sítio certo para essa escolha: o utilizador pede, o sistema
  não hedgea por omissão.
- **Não indexar por região.** Ver secção "testado e rejeitado".

### Decisões em aberto

1. **Valor do herbáceo fora de Abril–Setembro.** Proposta: um valor fixo
   declarado no CSV (ex. 200%, que satura a cura em 0). Alternativa:
   recusar responder e deixar o motor usar o seu default de 100%.
2. **Weather Stream (`.WXS`).** Traz a sua própria linha do tempo e pode
   não ter data absoluta — nesse caso não há P180 possível. Precisa de um
   caminho alternativo declarado (provavelmente: manter o default do
   motor e registá-lo em `meta`).
3. **Remover o VIIRS ou manter como fallback?** Manter significa manter a
   dependência do GEE, que é metade do ganho. Recomendação: remover, e
   se o Open-Meteo falhar usar os defaults do motor, como já acontece
   hoje quando o GEE falha.

---

## Verificação

1. **Regressão dos coeficientes** — `scripts/ajusta_lfmc_climatologia.py`
   reproduz os valores registados neste documento a partir de `LFM/`.
2. **Domínio** — herbáceo fora de Abril–Setembro devolve o valor
   declarado, nunca a extrapolação da harmónica (o teste óbvio: Janeiro
   não pode dar −354%).
3. **Julho/Agosto contra o campo** — herbáceo ~45/37%, lenhoso ~96/87%.
4. **Efeito na cura** — FM231 a 28/07 com P180 típico tem de sair da
   saturação em 0% e dar ~75% de carga transferida.
5. **Ponta a ponta** — simulação da ocorrência 20261061716 (Valpaços,
   28/07/2026 15:01, sem rajadas) com `live_fuel_moisture_source` a
   dizer `climatologia`, e ROS materialmente acima dos 12–19 m/min que
   deu com o VIIRS.
6. `test_api_integration.py` sem regressões novas (25/3 é a linha de
   base actual; os 3 falhados são pré-existentes, do catálogo
   `/fuel-models`).

---

## Ressalvas

Ficam registadas porque limitam o alcance das conclusões, não porque as
invalidem:

- **As coordenadas dos 10 sítios foram atribuídas por mim** a partir dos
  nomes, ao nível da freguesia/concelho. O dataset não tem coordenadas.
  Isto afecta o P180 pouco (a meteo é espacialmente suave, o ERA5 tem
  grelha de 9–31 km) e afectaria muito uma recalibração espectral — foi
  uma das razões para a rejeitar.
- **3 anos úteis.** 2019 tem 3 pares. A CV deixa-um-ano-de-fora assenta
  em 2020, 2021 e 2022.
- **Nenhuma validação contra perímetros reais.** O que está estabelecido
  é qual dos modelos prevê melhor as **medições de campo portuguesas** —
  não que as simulações resultantes acertem melhor no terreno. Isso é a
  validação histórica contra o ICNF, que continua na lista de "por
  fazer" do projecto.
- **Sítios costeiros.** Arrábida deu amplitude de NDVI de 0.84 a 1 km
  (píxeis de mar). Irrelevante para este plano, que não usa satélite,
  mas relevante se alguém retomar a via espectral.

---

## O que ficou diferente do plano (implementação, 2026-07-29)

**1. A janela do herbáceo é DJ 122–272, não 97–272.** O plano dizia
"limitar à janela amostrada". Ao implementar, a janela com dados (DJ 97)
mostrou-se má escolha: Abril tem 2 registos, ambos de sítio seco, e
sozinhos arrastam a harmónica para 30% a meio de Abril — o que diria
herbácea totalmente curada na primavera, contra 106% a meio de Maio. Não
é monótono nem é credível. O limite inferior passou a exigir densidade
(primeiro mês com n≥15, que é Maio); o superior continua a aceitar a
cauda fina, porque Setembro é época de fogos a sério e assumi-lo verde
estaria errado com certeza. `janela_util()` no script documenta a
assimetria.

**2. O valor fora da janela é 128.9%, medido, não 200% inventado.** É a
média do mês mais verde amostrado (Maio, n=21). Qualquer valor ≥120%
satura a cura em 0, que é o resultado físico certo; preferiu-se um número
que veio dos dados.

**3. `fetch_precipitation_sum` limita a data a hoje.** O arquivo devolve
400 para datas futuras (confirmado: `end_date=amanhã` dá "out of allowed
range"). Numa simulação com `start_time` no futuro a janela relevante é
a que termina agora — a chuva que ainda não caiu não está no solo.

**4. O VIIRS foi removido, não desactivado.** Saíram `_init_ee`,
`_viirs_fmc_sync` e `fetch_live_fmc_viirs` de `weather.py`, o
`earthengine-api` dos dois Dockerfiles e do `pyproject.toml`, e a
configuração GEE do worker. As variáveis `GEE_*` no Railway ficaram e
podem ser apagadas.

**5. A decisão 2 do plano (Weather Stream) resolveu-se sem caso
especial.** Com `weather_stream_text`, `data_lfmc` passa a ser `now` — o
P180 de hoje no ponto de ignição. É defensável: o ficheiro dá a linha do
tempo meteorológica, não a data do ano, e a água no solo é a que está lá
agora.

### Verificação

| ponto do plano | resultado |
|---|---|
| 1. coeficientes reproduzíveis | `ajusta_lfmc_climatologia.py` dá 32.5 e 27.5 pp |
| 2. domínio respeitado | 30/30 em `tests/test_lfmc_climatologia.py` |
| 3. Julho/Agosto vs campo | herb 45.4/36.7%, lenh 96.0/87.3% |
| 4. efeito na cura | FM231 a 28/07 (P180=425mm): cura 0%→95.4%, ROS 1.39→28.94 m/min |
| 5. ponta a ponta | ver abaixo |
| 6. sem regressões | `test_api_integration.py` 25/3 (os mesmos 3 pré-existentes) |

### Continua em aberto

- **Validação contra perímetros reais.** Está estabelecido que a
  climatologia prevê melhor as medições de campo; não que as simulações
  resultantes acertem melhor no terreno.
- **Humidade de copa.** Pinhais (128 medições de P. bravo) e Eucalipto
  (37) continuam sem uso. Alimentariam a transição para fogo de copas de
  Van Wagner, que é outro estrato e outro caminho no motor.
- **Reajustar com dados de 2023+** quando existirem — é para isso que o
  script está no repo.
