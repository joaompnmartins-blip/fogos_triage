# Cross-referência: motor de fogo vs. literatura — achados e plano de implementação

Documento de trabalho. Compara `src/fogos_triage/engine.py` e
`src/fogos_triage/simulation.py` contra três referências fornecidas:

- **Rothermel, Andrews 2018** (RMRS-GTR-371) — explicação de referência das
  equações Rothermel 1972 + correções Albini 1976a. Fonte autoritativa para
  o motor de fogo de superfície.
- **FARSITE, Finney 1998** (RMRS-RP-4) — propagação de perímetro por
  Huygens/Richards (1990), elipse de Anderson (1983), crown fire de Van
  Wagner (1977/1993), spotting de Albini (1979).
- **Forthofer 2007** (tese CSU) — modelação de vento em terreno complexo:
  compara um modelo CFD completo (Fluent, conservação de massa+momento)
  com um modelo "mass-consistent" (só conservação de massa) contra vento
  espacialmente uniforme, medindo o impacto de cada um na propagação de
  fogo simulada em FARSITE.

Não há alterações de código neste documento — apenas achados e um plano.
**Não implementar nada até o plano ser revisto.**

---

## O que já está correto (validado por leitura linha a linha)

- `_rothermel_direct` em `engine.py` segue as Tabelas 6a-6c do Andrews 2018
  quase termo a termo (η_M separados dead/live, φ_w com β/β_op, coeficientes
  B/C/E em unidades inglesas — `B=0.02526σ^0.54`, não a versão métrica
  `0.15988` do Apêndice A, que já foi corrigida antes, per memória do
  projeto).
- **Sem limite de vento** imposto (`U=0.9·IR`) — alinhado com a recomendação
  atual de Andrews et al. 2013 (secção 5.4.4 / 3.2.7), que o próprio
  Rothermel passou a recomendar não impor.
- `simulation.py` implementa a elipse de Anderson (1983) (eq. [13]-[17] do
  FARSITE) e a propagação Richards (1990) (eq. [1]-[2]) de forma fiel,
  incluindo a correção de terreno inclinado (eq. [3]-[10]) e a aceleração
  logarítmica (eq. [29], versão simplificada — ver achado F).
- `_max_spread_direction_from_phi` usa soma vetorial de φ_w/φ_s, coerente
  com a abordagem de vetorização de vento+declive do FARSITE (secção 2.2)
  em vez do vetoring "manual" mais antigo do Rothermel 1983.

---

## Achados (por ordem de impacto)

### A. Fogo de copas ativo (`FireType.CROWNING`) nunca é calculado — CONFIRMADO

`schemas.py` define `FireType.CROWNING` e `triage.py` (`compute_priority`,
linha ~319) já tem um multiplicador de prioridade específico para ele
(`crown_modifier = 1.50`, mais agressivo que o de TORCHING `1.20`) — mas
**nenhum código do repositório atribui `FireType.CROWNING` a nada**
(confirmado por grep: só aparece na definição do enum e nesse `elif`).

O que existe (`check_crown_fire_transition` em `engine.py`) só testa o
**limiar de transição** de Van Wagner (1977), eq. [21]:
`Io = (0.01·CBH·(460+25.9·M))^1.5`. Quando `Ib >= Io`, o código marca sempre
`FireType.TORCHING` — que é correto **apenas para o caso passivo**
(FARSITE eq. secção 3.2: "passive crown fire spread rate = surface fire
spread rate"). O que falta é o segundo teste, que distingue passivo de
ativo (FARSITE eq. [22]-[27]):

- `RAC = 3.0 / CBD` (eq. [22]) — taxa crítica de propagação para fogo de
  copas ativo.
- `RCmax = 3.34 · R10 · Ei` (eq. [24]) — taxa máxima de propagação ativa.
- `CFB = 1 - exp(-a_c·(R - Ro))` (eq. [25]-[27]) — fração de copa queimada.
- `RCactual = R + CFB·(RCmax - R)` (eq. [23]); se `RCactual >= RAC` →
  **ativo** → `FireType.CROWNING`, com ROS efetivo `RCactual` (tipicamente
  vários múltiplos do ROS de superfície).

**Impacto real**: qualquer ocorrência que hoje seria classificada como
fogo de copas ativo é sub-classificada como TORCHING (passiva) e a
prioridade calculada usa o multiplicador errado (1.20 em vez de 1.50) e o
ROS de superfície em vez de RCactual — ambos apontam para **subestimar
prioridade e intensidade** exatamente nos casos mais perigosos.

### B. Pesos de carga líquida usam f_ij (Rothermel 1972), não g_ij (Albini 1976a) — CONFIRMADO, atualmente adormecido

Andrews 2018, Tabela 6a/6b, é explícito: os pesos `g_ij` (subclasses de SAV
fixas: ≥1200, [192,1200), [96,192), [48,96), [16,48), <16) existem
**especificamente** para a carga líquida (`wn`), porque `f_ij` sofre da
"falha lógica" de o resultado depender de como a carga é dividida entre
classes quase-idênticas. `wn_dead`/`wn_live` em `engine.py`
(`_rothermel_direct`, `aggregate_multifuel`) usam `f_1h`, `f_10h`, `f_100h`,
`f_lh`, `f_lw` diretamente — o mesmo "technical oversight" que a própria
Andrews 2018 documenta ter acontecido no NFDRS 1978 (Cohen 1985, citado no
documento: "the loading computation change was missed").

**Verifiquei os 19 modelos de combustível PT (`data/fuel_models_pt.csv`)
um a um**: nenhum tem duas classes (dead ou live) na mesma subclasse de
SAV hoje — logo `f_ij` e `g_ij` coincidem exatamente, **sem impacto atual
nos números de triagem**. Mas:

- Todos os 19 modelos têm `FMType=static`; o código de transferência
  dinâmica (`is_dynamic`, cura de herbácea viva → 1h morto, Andrews 2018
  Tabela 7) já existe em `engine.py` mas nunca é exercitado.
- **FM225 e FM226 já têm exatamente a configuração que dispara o bug**: SAV
  do 1h morto ≥1200 ft⁻¹ e SAV do vivo herbáceo também ≥1200 ft⁻¹ — a
  classe transferida (que herda o SAV do herbáceo vivo, comentário
  "Transferred herb keeps fm.sav_live_h") cairia na mesma subclasse do 1h
  morto no dia em que `is_dynamic=True` for ligado para algum destes
  modelos.

É uma bomba-relógio, não um bug ativo — mas relevante porque cura
sazonal de herbáceas é precisamente o tipo de refinamento que faz sentido
para Portugal (verão/seca) e está listado como possível evolução.

### C. `simulation.py` nunca aplica fogo de copas — CONFIRMADO

A grelha ROS (`_build_ros_grid`) e o loop de propagação (`_propagate`)
chamam sempre `_rothermel_direct` (superfície) e nunca
`check_crown_fire_transition` nem qualquer lógica de copa — apesar de
lerem `canopy_base_height_m`/`canopy_bulk_density_kg_m3` do terreno
(`_sample_terrain_projected`, linhas 189-190) e esses valores nunca serem
usados depois. Isto significa que uma ocorrência que a triagem pontual
(`triage.py`) já classificaria como TORCHING vai propagar-se na simulação
espacial **sempre à taxa de superfície**, subestimando alcance e área
queimada em terreno com copa densa — precisamente onde o achado A também
se aplica (o mesmo cálculo de transição que falta em `triage.py` falta
aqui, duplicado).

### D. Vento espacialmente uniforme na simulação — o cenário que Forthofer mediu como pior

`_propagate`/`_build_ros_grid` usam um único valor `wind_mf`/`wind_dir`
(do Open-Meteo no ponto de ignição) replicado em toda a grelha, para toda
a duração da simulação — exatamente o "traditional method of spatially
uniform winds" que a tese do Forthofer testa contra dois modelos de vento
grelhados (CFD e mass-consistent) em dois incêndios históricos (South
Canyon, Mann Gulch) e conclui:

- Vento uniforme: pior ajuste em todas as métricas (área coincidente
  46.6% em média no South Canyon vs. 55.6% mass-consistent vs. 74.9% CFD).
- CFD é o mais preciso mas **demora 0.5-1.5h por simulação** — inviável
  para o caso de uso do fogos_triage (worker faz poll a cada 120s; o
  endpoint `/simulate` deve responder em segundos-minutos, per
  `simulation.md`, "Performance estimada": 5-90s).
- O **modelo mass-consistent** (só conservação de massa, equação de
  Poisson elíptica resolvida por elementos finitos — Sasaki 1958/1970)
  demora **1-15 minutos** e captura grande parte do efeito de canalização
  de vento por vales/cristas que o vento uniforme perde por completo. O
  próprio autor recomenda-o especificamente para "short time constraints
  or limited computing resources" — a descrição quase literal do
  ambiente Railway deste projeto.
- Achado prático relevante: agora que existe terreno real de alta
  resolução (10m) para Alto Minho (`data/AltoMinho/...tif`), com relevo
  genuíno (não o `MockLandscapeReader` plano), é o candidato natural para
  pilotar isto — em terreno plano o ganho seria pequeno.

### E. `simulation.md` está desatualizado — cosmético

A tabela "Limitações da v1" (secção 8) lista "sem correção de terreno
inclinado" e "sem aceleração" como trabalho futuro — mas `simulation.py`
já implementa ambos (achados confirmados na leitura acima). O documento é
o spec original, escrito antes da implementação evoluir; vale a pena
atualizar a tabela para não induzir em erro quem o ler a seguir.

### F. Sub-passo de tempo fixo em vez de "distance resolution" dinâmica — menor

FARSITE controla três parâmetros (secção 4.4): timestep máximo,
**distance resolution** (recalcula o timestep dinamicamente a partir do
vértice mais rápido, eq. [29]-[33] via método de Newton) e perimeter
resolution. `simulation.py` só implementa perimeter resolution
(`_rediscretize`, `MAX_SEG_M`/`MIN_SEG_M`) e um timestep fixo
(`DT_MIN=5.0`). Em fogos muito rápidos sobre o raster de 10m do Alto
Minho isto pode saltar detalhe de terreno dentro de um único passo de 5
min. Impacto provavelmente pequeno face aos achados A-D; mencionado por
completude.

### G. Spotting — deliberadamente fora de âmbito

FARSITE secção 3.4 (Albini 1979) não está implementado, e nem devia ser
prioridade: o próprio documento fornecido assinala que a OCR das
equações [34]-[43] está "heavily garbled" mesmo na fonte original, exige
um modelo de pluma de brasas com várias constantes empíricas, e
`simulation.md` já classifica isto como "Muito complexo, V2". Confirmo
essa decisão — não incluir no plano abaixo.

---

## Plano de implementação (proposto, por ordem)

1. **Corrigir/completar fogo de copas ativo (achados A + C), num único
   lugar reutilizável.**
   - Adicionar a `engine.py` uma função `check_active_crown_fire` (ou
     estender `check_crown_fire_transition`) implementando eq. [22]-[27]:
     `RAC`, `Ro` (usa Ib/R, já disponíveis), `a_c`, `CFB`, `RCmax` (precisa
     de R10 — taxa de propagação do fuel model 10 nas mesmas condições de
     vento/declive; pode calcular-se chamando `_rothermel_direct` com os
     parâmetros do FM10/equivalente PT), `RCactual`.
   - Atualizar `triage.py` (`_predict_scenario`/`triage_neighbourhood`,
     ambos os locais que hoje só testam a transição) para: se
     `RCactual >= RAC` → `FireType.CROWNING` com `ros_m_per_min=RCactual`
     (convertido) e `fireline_intensity_kw_m` recalculada pela eq. [28];
     senão, manter `FireType.TORCHING` como está.
   - Atualizar `simulation.py` (`_sample_terrain_projected` já lê
     `canopy_bulk_density_kg_m3`/`canopy_base_height_m`) para chamar a
     mesma função em `_propagate` e usar `RCactual`/elipse de copa em vez
     da elipse de superfície quando o vértice está em fogo de copas ativo.
   - Verificação: escolher um ponto sintético com CBH baixo + CBD alto
     (ex. dados de Monchique/Pedrógão já usados no memory de projeto) e
     confirmar que `FireType.CROWNING` aparece pela primeira vez nos
     testes; correr `test_pipeline.py`/`test_api_integration.py`.

2. **Resolver a bomba-relógio dos pesos g_ij (achado B) antes de qualquer
   modelo de combustível dinâmico ser ligado.**
   - Implementar `g_ij` (agrupamento por subclasse de SAV fixa) em
     `aggregate_multifuel`/`_rothermel_direct`, só para o cálculo de
     `wn_dead`/`wn_live` (as restantes ponderações, ex. SAV característico
     e heat sink, continuam corretamente a usar `f_ij`).
   - Como os 19 modelos estáticos atuais não têm sobreposição de
     subclasse, esta mudança é matematicamente um no-op para o
     comportamento atual — pode ser verificada por regressão exata
     (mesmos ROS/FLI antes/depois para os 19 fuel models).
   - Só depois disto, considerar ativar `is_dynamic=True` nalgum modelo PT
     (ex. herbáceas, cura de verão) — sem esta correção primeiro, ativar
     dynamic em FM225/FM226 introduziria o erro documentado.

3. **Atualizar a tabela de limitações em `simulation.md` (achado E).**
   - Trivial; fazer como parte do mesmo PR que resolver A/C, já que nessa
     altura a lista de limitações reais muda de qualquer forma.

4. **Piloto de vento mass-consistent para Alto Minho (achado D).**
   - Fase de investigação primeiro: confirmar viabilidade de runtime
     (1-15 min por simulação do Forthofer foi medido em CFD comercial
     Fluent + malha de elementos finitos em C/Fortran — replicar em
     Python puro pode ser mais lento; medir antes de comprometer).
   - Se viável: novo módulo (ex. `src/fogos_triage/wind_field.py`)
     implementando a formulação variacional de Sasaki (eq. [19]-[26] do
     Forthofer) sobre o raster de elevação já carregado — resolve `λ` num
     grid 3D (elementos finitos hexaédricos, como descrito na secção
     3.2.2-3.2.3), depois `u,v,w` a partir de `λ` (eq. [22]).
   - Inicializar o campo com um perfil logarítmico a partir do vento
     Open-Meteo no ponto de ignição (mesma abordagem do Forthofer, secção
     3.2.4 — sem dados de estações meteorológicas adicionais disponíveis).
   - Integrar em `simulation.py`: `_build_ros_grid`/`_propagate` passam a
     amostrar `wind_mf`/`wind_dir` por vértice/pixel a partir do campo
     resolvido, em vez do valor único atual.
   - Pilotar especificamente sobre `data/AltoMinho/Landscape_10x10_AMinho_2026.tif`
     (tem relevo real de 10m) — comparar visualmente perímetros com/sem
     campo de vento para um caso sintético antes de qualquer validação
     quantitativa (não há dados de vento medidos em torres como o
     Forthofer tinha para Askervein/Waterworks Hill).
   - Este é o item de maior esforço do plano — só avançar depois de A-C
     estarem resolvidos, dado que o achado A tem impacto direto e imediato
     na prioridade calculada hoje, enquanto D é uma melhoria de precisão
     espacial da simulação (feature já parcialmente funcional).

5. **(Opcional, baixa prioridade) Sub-passo dinâmico (achado F).**
   - Só reconsiderar se, após o item 4, se observarem artefactos de
     propagação (perímetros a "saltar" feições de terreno) em fogos
     rápidos sobre o raster de 10m do Alto Minho. Não faz sentido
     investir nisto antes de haver vento espacialmente variável — com
     vento uniforme o ganho de resolução temporal é marginal.

---

## Notas de verificação transversais

- Correr `python tests/test_pipeline.py` e
  `PYTHONPATH=. python3 tests/test_api_integration.py` depois de cada
  passo (per convenção do CLAUDE.md) — o segundo já corre localmente com
  `PYTHONPATH=.` neste ambiente (25/28 passam à partida; as 3 falhas são
  de um caminho `/home/claude/...` hardcoded no teste, não relacionadas).
- Os achados A-C afetam **valores já em produção** (prioridade P1-P4
  calculada hoje); B é adormecido; D é uma feature nova sobre uma feature
  já parcialmente implementada. Se só houver tempo para um item, é o A.
