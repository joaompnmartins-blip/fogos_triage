# Classificação da triagem — cenários e limiares

Documento de referência. Descreve exactamente o que o motor calcula
para os 3 cenários de cada ocorrência e como a prioridade P0-P4 é
determinada, lido directamente de `src/fogos_triage/triage.py` e
`src/fogos_triage/schemas.py` (não é um resumo aproximado — os números
abaixo são os usados em produção).

## 1. Os 3 cenários — o que é calculado

Os três cenários correm o mesmo motor Rothermel+Byram
(`predict_surface_fire`, `engine.py`), diferindo apenas na meteo usada
como entrada (`triage.py:231-260`):

| Cenário | Vento (midflame e 10m) | Humidade dos combustíveis mortos (1h / 10h / 100h) |
|---|---|---|
| **Central** | valor real/previsto, sem alteração | valor real/previsto, sem alteração |
| **Pior caso** (`worst`) | ×1.20 | ×0.75 / ×0.85 / ×0.90 (−25% / −15% / −10%) |
| **Melhor caso** (`best`) | ×0.80 | ×1.25 / ×1.15 / ×1.10 (+25% / +15% / +10%) |

Cada cenário produz o mesmo conjunto de saídas
(`FireBehaviorPrediction`, `schemas.py:100-140`): `ros_m_per_min`,
`fireline_intensity_kw_m`, `flame_length_m`, `heat_per_unit_area_kj_m2`,
`reaction_intensity_kw_m2`, `direction_max_spread_deg`,
`effective_wind_ms`, `fire_type` (surface/torching/crowning), e a
propriedade derivada `tactic_category` (ver secção 3).

**Só se aplicam ao cenário central**, não a pior/melhor caso
(`triage.py:189-207`):
- A verificação de transição para fogo de copas (pode subir
  `fire_type` para `torching`).
- O cálculo da prioridade (secção 2) — a prioridade da ocorrência
  reflecte sempre o cenário central, nunca o pior nem o melhor caso.

## 2. Prioridade P0-P4

Calculada apenas a partir do cenário central
(`compute_priority`, `triage.py:263-339`), por uma pontuação
ponderada 0-100:

```
score = (0.50 × Intensidade + 0.25 × Táctica + 0.25 × ROS) × modificador_copa
```

| Componente | Base | Limiares |
|---|---|---|
| Intensidade (peso 50%) | `50×log10(FLI) − 110`, limitado a 0-100 | FLI 500→25, 2000→50, 4000→70, 10000→90 |
| Táctica (peso 25%) | comprimento de chama L | L<1.3m→10, <2.5m→35, <3.5m→60, <10m→82, senão→95 |
| ROS (peso 25%) | m/min | ROS<1→5, <5→25, <15→55, <30→78, senão→92 |
| Modificador de copa | `fire_type` do cenário central | torching ×1.20, crowning ×1.50, senão ×1.0 |

Classe final a partir da pontuação (0-100):

| Classe | Score | Equivalente FWI | Significado |
|---|---|---|---|
| **P0** | ≥ 87 | Extremo | FLI ≥10 000 kW/m, copa activa, incontrolável |
| **P1** | ≥ 67 | Muito Elevado | FLI 4 000-10 000, só meios aéreos pesados |
| **P2** | ≥ 47 | Elevado | FLI 2 000-4 000, meios aéreos necessários |
| **P3** | ≥ 22 | Moderado | FLI 500-2 000, terrestres efectivos |
| **P4** | < 22 | Baixo | FLI < 500, sapadores |

## 3. Categoria táctica (independente da prioridade)

Propriedade derivada por cenário (`FireBehaviorPrediction.tactic_category`,
`schemas.py:122-140`), função só do comprimento de chama **desse**
cenário — não depende da pontuação de prioridade:

| Comprimento de chama | `tactic_category` | Rótulo |
|---|---|---|
| < 1.3m | `direct_attack_manual` | ataque directo manual |
| < 2.5m | `direct_attack_difficult` | ataque directo difícil |
| < 3.5m | `indirect_attack_machinery` | máquinas / aéreos |
| ≥ 3.5m | `indirect_attack_only` | só indirecto |

## 4. Comparação com Andrews & Rothermel 1982 (INT-131)

Cross-check dos limiares acima contra a Tabela 1 de Andrews, P.L. &
Rothermel, R.C., *Charts for Interpreting Wildland Fire Behavior
Characteristics*, USDA Forest Service Gen. Tech. Rep. INT-131 (1982) —
a referência clássica de onde vem a fórmula de Byram usada em
`engine.py`. A tabela original está em unidades imperiais (pés,
Btu/ft/s); convertida aqui para métrico:

- 1 ft = 0.3048 m
- 1 Btu/ft/s = 3.4619 kW/m (de 1 Btu = 1055.06 J, 1 ft = 0.3048 m)

### Tabela 1 (INT-131) convertida para métrico

| Comprimento de chama | Intensidade de linha de fogo | Interpretação (INT-131) |
|---|---|---|
| < 1.22 m | < 346 kW/m | equipas manuais, ataque directo |
| 1.22–2.44 m | 346–1 731 kW/m | máquinas necessárias (charruas, bulldozers, retardante) |
| 2.44–3.35 m | 1 731–3 462 kW/m | problemas sérios de controlo — torching/crowning/spotting prováveis |
| > 3.35 m | > 3 462 kW/m | crowning, spotting, corridas maiores prováveis |

### Comparação com os limiares da app

**Comprimento de chama (`tactic_category`) — correspondência muito próxima:**

| App (`schemas.py`) | INT-131 (convertido) | Diferença |
|---|---|---|
| 1.3 m | 1.22 m | +6.5% |
| 2.5 m | 2.44 m | +2.5% |
| 3.5 m | 3.35 m | +4.5% |

**FLI (componente de intensidade da pontuação de prioridade) — mesma ordem de grandeza, não idêntico:**

| App (`triage.py`) | INT-131 (convertido) | Diferença |
|---|---|---|
| 500 kW/m | 346 kW/m | +45% |
| 2 000 kW/m | 1 731 kW/m | +16% |
| 4 000 kW/m | 3 462 kW/m | +16% |

### Validação do coeficiente de Byram

O INT-131 dá a relação de Byram (eq. 3) em unidades imperiais:
`F_L(ft) = 0.45 × I_B(Btu/ft/s)^0.46`. Convertendo o coeficiente 0.45
para SI (F_L em m, I_B em kW/m):

```
0.45 × 0.3048 / 3.4619^0.46 = 0.0775
```

Isto é **exactamente** o coeficiente já usado em `engine.py`:
`flame_length_m = 0.0775 × fi_kw_m ** 0.46` — confirma que a
implementação de Byram na app é uma conversão métrica correcta e
exacta desta fórmula, não uma aproximação.

Isto também explica as duas tabelas de comparação acima: como
comprimento de chama e FLI se relacionam por `FL ∝ FLI^0.46` (ou seja
`FLI ∝ FL^2.17`), os limiares de chama ligeiramente mais altos/
arredondados da app (1.3/2.5/3.5 vs. a conversão literal 1.22/2.44/
3.35) amplificam-se através desse expoente 2.17 numa diferença maior
em FLI (16-45%) — pequenas diferenças à entrada tornam-se maiores ao
inverter a lei de potência. Aplicando os próprios limiares de chama da
app à sua própria fórmula de Byram dá FLI implícito de ≈459/1905/
3960 kW/m — muito mais próximo dos 500/2000/4000 kW/m citados do que
dos 346/1731/3462 do INT-131. Ou seja, os limiares de FL e FLI da app
são consistentes entre si; estão só calibrados para pontos de corte
ligeiramente diferentes (mais arredondados, ~5-15% mais altos) do que
uma conversão literal da Tabela 1 deste documento de 1982 — consistente
com o comentário em `triage.py` de que foram "alinhados com classes
FWI ANEPC" (uma calibração portuguesa separada), não uma cópia directa
do INT-131.

**Sem comparação possível para ROS**: a Tabela 1 do INT-131 classifica
severidade só por comprimento de chama/FLI — não tem tabela de
limiares por taxa de propagação, por isso não há nada neste documento
para verificar os limiares `ros_score` da app (<1/<5/<15/<30 m/min).

## Nota — discrepância com CLAUDE.md

`CLAUDE.md` documenta só 4 classes de prioridade com limiares
diferentes (P1≥70, P2 50-70, P3 25-50, P4<25) e os limiares de
comprimento de chama a 1.2/2.4/3.4m. O código real tem **5** classes
(inclui P0) a 87/67/47/22, e os limiares de chama a 1.3/2.5/3.5m — a
descrição em `CLAUDE.md` está desactualizada face ao código actual.
Não foi corrigido neste documento por pedido explícito (sem alterações
à app por agora) — a decidir se `CLAUDE.md` deve ser actualizado
separadamente.
