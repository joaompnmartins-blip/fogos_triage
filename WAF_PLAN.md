# Plano: corrigir o vento midflame (WAF) contra a referência

**Nota: plano apenas — nada implementado até ser pedido explicitamente.**

O WAF (*wind adjustment factor*) converte o vento meteorológico a 10 m no
vento que a chama sente. É, segundo a própria referência do projecto,
**"a maior fonte de erro operacional depois da seleção do modelo de
combustível"** (`modelos_PFernandes/MODELO_FOGO_REFERENCIA.md`, §11).

Análise a 2026-07-30, no seguimento da integração WindNinja — que obrigou
a olhar para o WAF porque o campo de vento também sai a 10 m e precisa da
mesma conversão.

---

## A referência

`modelos_PFernandes/MODELO_FOGO_REFERENCIA.md` §3 define a cadeia
completa:

```
U(10 m)  →  U(20 ft) = U(10 m) × 1.15  →  U_midflame = U(20 ft) × WAF
```

e o WAF **calculado**, não tabelado (Albini & Baughman 1979):

```
sem abrigo:  WAF = 1.83 / ln[(20 + 0.36·h) / (0.13·h)]        h = espessura do leito, ft
sob copado:  WAF = 0.555 / [√(f·H) · ln((20 + 0.36·H)/(0.13·H))]
             f   = min(cobertura × razão_copa / 3, 0.33)      H = altura do copado, ft
```

Os valores fixos que a referência tabela (`forest_open` 0.30,
`forest_moderate` 0.20, `forest_dense` 0.10) são atalhos para quando
faltam os parâmetros do copado, não a definição.

---

## O que o código faz hoje

`weather.py:derive_fire_weather` (linha ~366):

```python
if has_overstory and canopy_cover_pct > 50:
    waf = 0.1 + 0.05 * max(0, (stand_height_m - 5) / 20)
elif has_overstory and canopy_cover_pct > 20:
    waf = 0.25
elif stand_height_m > 1.8:
    waf = 0.5
else:
    waf = 0.4
wind_midflame = wx.wind_speed_10m_ms * waf
```

E os dois chamadores usam-no de maneira diferente:

| caminho | chamada | WAF efectivo |
|---|---|---|
| triagem (`triage.py:64`) | passa altura/cobertura/coberto por píxel | 0.14 a 0.50 |
| simulação (`routes_meta.py:366`, `routes_freesim.py:280`) | só humidades vivas | **0.40 constante** |

---

## As quatro divergências, medidas

### 1. Falta o factor 1.15 (10 m → 20 ft)

A cadeia da referência tem dois passos; o código tem um. Resultado:
**subestimamos o vento midflame em 13.0%**, sempre, em triagem e em
simulação, em todos os modelos.

É a divergência mais simples de corrigir e a única que é inequivocamente
um erro — as outras três são simplificações discutíveis.

### 2. A simulação ignora o coberto

Para o mesmo ponto num pinhal denso: triagem WAF 0.14, simulação 0.40 —
quase **3×** o vento midflame, em dois números que a aplicação mostra
lado a lado ao mesmo utilizador sobre o mesmo incêndio.

### 3. O WAF é escolhido por degraus, não calculado

Comparando a fórmula sem abrigo com o valor que o código usa, para os
leitos reais dos modelos PT (`Depth` do `fuel_models_pt.csv`, em cm):

| FM | leito | A&B | código | razão |
|---|---|---|---|---|
| 214 | 0.05 m | 0.266 | 0.40 | **0.67×** |
| 213 / 226 | 0.10 m | 0.298 | 0.40 | 0.74× |
| 212 | 0.15 m | 0.318 | 0.40 | 0.79× |
| 222 / 227 / 234 | 0.50 m | 0.400 | 0.40 | 1.00× |
| 233 | 1.05 m | 0.474 | 0.40 | 1.19× |
| 237 / 255 | 0.90 m | 0.457 | 0.40 | 1.14× |
| 236 | 1.70 m | 0.536 | 0.40 | **1.34×** |

**A mediana é 1.00×** — o 0.40 é uma boa média para o conjunto dos
modelos PT. O problema não é o valor central, é a dispersão: erra entre
−33% e +34% conforme o modelo, e erra sistematicamente na direcção
errada (subestima nos matos altos, que são os que ardem pior).

No caso abrigado a escada está mais perto, mas ainda desvia:

| copado | A&B abrigado | triagem | razão |
|---|---|---|---|
| 8 m, 25% | 0.246 | 0.250 | 0.98× |
| 15 m, 30% | 0.199 | 0.250 | **0.80×** |
| 20 m, 60% | 0.133 | 0.138 | 0.97× |
| 25 m, 80% | 0.109 | 0.150 | **0.73×** |

### 4. O ramo `> 1.8 m → 0.50` é código morto

O leito mais espesso de todos os modelos PT é o FM236 com **1.70 m**.
A condição nunca dispara. Na prática, o caminho sem coberto devolve
sempre 0.40 — o `0.5` nunca é usado com os dados que temos.

---

## Impacto

Um exemplo, FM233 (matos atlânticos altos), vento a 10 m de 10 m/s,
declive 10°, humidades mortas 6/7/9%:

| WAF | midflame | ROS | FLI |
|---|---|---|---|
| 0.14 | 1.4 m/s | 9.42 m/min | 7 730 kW/m |
| 0.25 | 2.5 | 16.91 | 13 867 |
| **0.40 (o que a simulação usa)** | 4.0 | 27.86 | 22 848 |
| 0.50 | 5.0 | 35.50 | 29 115 |

A própria referência diz: *"Um fator 4 no WAF produz um fator ~5 na
intensidade. A escolha do abrigo é tão determinante como a escolha do
modelo de combustível."*

Nota sobre o que isto NÃO significa: as divergências 1 e 3 puxam em
sentidos opostos (o 1.15 em falta subestima 13%; o 0.40 fixo sobrestima
nos leitos rasos e subestima nos altos). Não há um "erro global" único a
anunciar — há um erro que varia por modelo de combustível, e é isso que
o torna difícil de detectar por inspecção dos resultados.

---

## Proposta

Uma função única em `src/fogos_triage/waf.py`, fonte de verdade como o
`severity.py` e o `fuel_moisture_scenarios.py`:

```python
def waf_albini_baughman(
    depth_ft: float,
    canopy_height_m: float | None = None,
    canopy_cover_frac: float | None = None,
    crown_ratio: float = 0.5,
) -> float
```

- Sem copado (ou cobertura abaixo do limiar): fórmula do leito, usando o
  `depth` que o modelo de combustível **já traz**.
- Com copado: fórmula do copado, usando altura e cobertura do raster —
  que a triagem já lê e passa.
- `derive_fire_weather` passa a aplicar `× 1.15 × waf`.

### Ordem sugerida

1. **O factor 1.15 sozinho, primeiro.** É uma linha, é inequívoco, e o
   efeito é uniforme (+13% no midflame em tudo). Fazer isolado torna-o
   fácil de verificar e de reverter.
2. **A fórmula sem abrigo.** Afecta os modelos do grupo V (matos,
   herbáceas), que são a maior parte do território ardido.
3. **A fórmula com copado**, e com ela a decisão sobre a simulação (ver
   em aberto).

### Em aberto

- **A simulação passa a usar coberto por píxel?** Isso exige ler
  `stand_height` e `canopy_cover` no `_TERRAIN_FIELDS` e na grelha —
  hoje só se lê `slope`, `aspect`, `fuel_model`. Tem custo de memória e
  de tempo em todas as simulações. A alternativa é manter a simulação
  sem coberto e assumir a discrepância com a triagem, o que é pior mas
  mais barato.
- **`crown_ratio`** não existe em lado nenhum nos nossos dados. A
  referência usa-o na fórmula abrigada. Assumir 0.5 é o que fiz nas
  medições acima; convém confirmar com o Paulo Fernandes se é razoável
  para os povoamentos portugueses.
- **Qual dos dois está certo hoje**, triagem ou simulação, para efeitos
  de comunicação: quando isto for corrigido, os números que os
  utilizadores viram até agora mudam, e convém saber dizer em que
  sentido.

---

## ESTADO — o que ficou feito

### Passo 1, triagem (commit `b04a203`, 2026-07-30)

`src/fogos_triage/waf.py` criado com as três funções; `derive_fire_weather`
ganhou `fuel_bed_depth_ft` e o factor 1.15; `WeatherConditions` ganhou
`wind_20ft_ms`; FM225/226/235 passaram a dinâmicos.

Calibração contra a tabela §7.3, em `tests/test_referencia_fernandes.py`:

| | \|erro\| mediano | dentro de 15% |
|---|---|---|
| ponto de partida | 16% | 6/18 |
| + factor 1.15 | 10% | 11/18 |
| + modelos dinâmicos | 10% | 12/18 |
| + WAF de A&B | **0.1%** | **18/18** |

### Passo 2, simulação (2026-07-30)

A pergunta "em aberto" acima foi respondida com **sim**: as duas bandas
entraram no `_TERRAIN_FIELDS` e nas duas leituras de janela da grelha e
das setas. O argumento que decidiu não foi o custo — foi que sem elas o
mesmo píxel de pinhal era triado com WAF 0.17 e simulado com 0.40, mais
do dobro do vento na simulação do que na triagem que lhe deu a
prioridade. `tests/test_waf_simulacao.py` fixa a igualdade.

O vento que a simulação transporta passou a ser o de **20 pés** e não o
midflame: o midflame já traz um WAF aplicado, e o WAF só se pode escolher
depois de se saber o modelo de combustível do píxel. `_WAF_SIMULACAO`
desapareceu.

**Dois erros apanhados por esta passagem**, ambos introduzidos pelo
factor 1.15 do passo 1 e ambos em produção desde então:

1. `gust_weather` não propagava a rajada para `wind_20ft_ms`. Como a
   simulação passou a ler esse campo, ligar as rajadas teria voltado ao
   vento sustentado, em silêncio. Mesma família da avaria de 2026-07-30
   no windfield.
2. O `windfield` mandava ao WindNinja o vento de 20 pés rotulado como
   sendo a 10 m — 15% acima. Passou despercebido porque o
   `_vento_no_ponto` cometia o erro simétrico na volta (convertia o campo
   sem repor o 1.15) e os dois quase se cancelavam.

**Impacto medido**, 15×15 km no Alto Minho, 39 409 píxeis combustíveis,
vento de 6 m/s (21% dos píxeis têm copado):

| modelo | % área | WAF médio | ROS antes | ROS agora | |
|---|---|---|---|---|---|
| FM232 herbáceas | 23.8% | 0.372 | 23.35 | 21.27 | −9% |
| FM233 mato atlântico | 19.3% | 0.474 | 21.15 | 24.84 | **+17%** |
| FM221 M-CAD | 17.0% | 0.220 | 14.44 | 8.20 | **−43%** |
| FM223 M-EUC | 8.0% | 0.241 | 20.44 | 12.73 | −38% |
| FM227 M-PIN | 4.5% | 0.246 | 16.13 | 10.12 | −37% |
| FM214 F-RAC | 0.5% | 0.160 | 1.29 | 0.55 | −58% |

Média da janela −10%; 37% dos píxeis aceleram, 45% abrandam. **O sinal
depende do modelo** — os V sobem, os F e M descem —, portanto não é um
factor de escala que se possa comunicar como "menos X%".

Área queimada em simulações de 3 h, mesma ignição e meteo:

| | 1 h | 2 h | 3 h |
|---|---|---|---|
| Alto Minho (mato) | −5% | −3% | −8% |
| Gerês (copado) | **−49%** | **−47%** | **−41%** |

### Passo 3, confronto com o RMRS-GTR-266 (2026-07-30)

Chegaram a `WAF/` os ficheiros do **Andrews 2012, RMRS-GTR-266** (USDA FS,
domínio público) — a fonte primária do WAF, com implementação de
referência que passa 36/36 verificações documentadas.

**As nossas duas fórmulas batem ao dígito com a dela**, testado em
`waf_sem_abrigo` (H = 0.2/1.0/1.5/3.0/6.0 ft) e `waf_sob_copado`
(FM2, CC 40%, CH 50 ft, CR 0.5/0.7/0.9). Doze pontos de validação do §10
entraram no `test_referencia_fernandes.py`.

Aplicado, com a regra do FuelCalc (§4):

- **`min(copado, leito)`**, nunca o do copado sozinho. O relatório
  chama-lhe a armadilha do FARSITE e manda guardar contra ela: com
  cobertura baixa e copado alto a fórmula abrigada devolve valores
  *acima* da do leito — diria que estar sob árvores acelera o vento.
  Acontecia em 13 píxeis da janela do Gerês, um a 1.95× o descoberto.
- **Fim do limiar de 20% de cobertura.** Um limiar cria um degrau entre
  píxeis vizinhos quase iguais; com o mínimo, o cruzamento das curvas
  dá-se sozinho (≈8% para copado de 20 m) e a transição é contínua.
- O WAF deixou de depender do `has_overstory`, que continua a decidir só
  o sombreamento das humidades. São perguntas diferentes.

Efeito medido: **0.04–0.06% dos píxeis**, −11% a −14% de WAF neles. É
quase nulo porque a cobertura no raster é binária — 73% a 0%, 27% a
≥20%, nada pelo meio. Vale como garantia de que o impossível não
acontece, não como mudança de números.

### RESOLVIDO — a direcção do factor 1.15 (2026-07-30)

**Decisão: seguir o RMRS-GTR-266.** `WIND_10M_TO_20FT = 1.0 / 1.15`.

O projecto diverge deliberadamente do §3 do
`MODELO_FOGO_REFERENCIA.md`, que manda multiplicar. Razão: 20 pés são
6.10 m, **abaixo** dos 10 m, e o vento cresce com a altura. O perfil
logarítmico confirma o próprio valor — resolver
`ln(10/z₀)/ln(6.096/z₀) = 1.15` dá `z₀ ≈ 0.23 m`, rugosidade de pastagem
alta ou mato baixo, plausível para estações de meteorologia de
incêndios. O 1.15 estava certo; o que estava em disputa era o lado da
fracção.

**Custo: a tabela §7.3 deixou de poder validar a cadeia completa.** Foi
gerada com a convenção contrária, e alimentá-la com os nossos 20 km/h
daria 0/18 — o que só diria que as duas convenções diferem. O
`test_referencia_fernandes.py` passou a alimentá-la com o vento a 20 pés
que a referência usou (6.39 m/s), o que a mantém a validar o Rothermel e
as fórmulas de WAF (18/18, |erro| mediano 0.1%) e isola o passo em
disputa, agora verificado em bloco próprio contra o RMRS e contra o
perfil logarítmico.

**Impacto.** ROS da triagem, 8 m/s e declive 20%, uniforme entre modelos:

| modelo | antes | depois | |
|---|---|---|---|
| FM232 herbáceas | 30.00 | 20.42 | −32% |
| FM227 pinhal | 21.05 | 14.60 | −31% |
| FM231 herbáceas altas | 39.69 | 27.82 | −30% |
| FM233 mato atlântico | 30.77 | 22.82 | −26% |

Área queimada a 3 h: Alto Minho −32%, Gerês −36%.

Ao contrário do WAF por píxel, **este é um factor de escala**: desce
tudo, e pode comunicar-se como tal. Os comprimentos de chama descem com
ele (FM233 8.21 → 7.15 m), o que desloca ocorrências entre categorias
tácticas junto às fronteiras de 1.2 / 2.4 / 3.4 m.

### Histórico da questão (o que levou à decisão)

**As duas fontes contradizem-se, e a diferença é de 32% no vento.**

| Fonte | Diz |
|---|---|
| `modelos_PFernandes/MODELO_FOGO_REFERENCIA.md` §3 | `U(20 ft) = U(10 m) × 1.15` |
| RMRS-GTR-266 §1 (Turner & Lawson 1978) | `U20 = U10m / 1.15` |

O RMRS está fisicamente certo: 20 pés são 6.10 m, **abaixo** dos 10 m, e
o vento cresce com a altura, logo `U(20ft) < U(10m)`. Multiplicar só pode
ser a conversão invertida.

A referência do projecto é internamente consistente com o `×1.15` (§3.3:
20 km/h × 1.15 × 0.40 = 9.2 km/h), e a tabela §7.3 é a saída do
`run_validation()` dela. **Não pode arbitrar**: o nosso 18/18 diz que
reproduzimos a implementação do Fernandes, não que a física esteja certa.

Inverter para `/1.15` dá `|erro| mediano 27.6%` e `0/18` — um desvio
sistemático de −22% a −31%, sem dispersão. Essa uniformidade é a
assinatura de um erro puro de escala do vento, e é a prova de que as duas
fontes divergem num escalar só.

Decidido a favor do RMRS — ver a secção acima. Vale a pena confirmar com
o Paulo Fernandes, não para reverter, mas porque o §3 da referência dele
tem então um erro que convém que ele saiba.

### Por fazer

- Deploy e verificação em produção.
- `crown_ratio` = 0.5 continua a ser uma suposição, por decisão: o
  RMRS §8 dá a tipificação do Albini & Baughman (intolerante à sombra,
  maduro aberto 0.5, maduro denso 0.2), mas é norte-americana e
  transpô-la para pinhal bravo e eucaliptal precisa de confirmação. Pesa
  em 21% dos píxeis da janela medida, e o WAF varia com 1/√crown_ratio
  (1.53× entre 0.3 e 0.7). É o único número desta cadeia que não vem de
  dados nem de fonte.
- A fórmula do copado **não tem validação externa nenhuma**: a tabela
  §7.3 corre todos os modelos com `shelter="open"`, portanto os 18/18
  exercitam só a fórmula do leito.

---

## Verificação

1. `waf_albini_baughman` reproduz as tabelas §3.3 da referência para os
   casos `forest_open`/`moderate`/`dense`.
2. Nenhum modelo PT produz WAF fora de [0.05, 0.6] — sanidade física.
3. O caso `M-PIN, 20 km/h a 10 m, open` da tabela §3 da referência dá
   ROS 13.58 m/min e I_B 5847 kW/m. É o único ponto de calibração
   ponta-a-ponta que temos contra a fonte; se não bater, algo mais está
   errado além do WAF.
4. Regressão: correr triagem e simulação numa ocorrência conhecida antes
   e depois, e registar a diferença por modelo de combustível — não para
   confirmar que não muda (vai mudar), mas para saber quanto.

---

## Ressalvas

- **Não fazer isto ao mesmo tempo que o WindNinja.** As duas alterações
  mexem no mesmo número (o vento midflame) e, feitas juntas, tornam
  impossível atribuir uma mudança nos perímetros a uma delas. O
  `WINDNINJA_PLAN.md` fixa deliberadamente `_WAF_SIMULACAO = 0.40` para
  isolar o efeito do relevo; este plano vem depois.
- A referência é `modelos_PFernandes/MODELO_FOGO_REFERENCIA.md`, que está
  **untracked** no repo. Vale a pena decidir se entra no git, já que
  passa a ser a fonte citada por código.
- Não validei nada disto contra fogos reais. O argumento aqui é de
  conformidade com a referência do projecto, não de acerto empírico.
