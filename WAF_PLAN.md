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
