# Medições de campo de humidade do combustível vivo — Portugal continental (2019–2022)

Conversion of `FieldMesurementsLFM_PT.xlsx`, sheet **`Dados Normalizados`** (1358 data rows,
9 columns), into CSV for programmatic use.

| File | Rows | Purpose |
|---|---|---|
| `lfmc_pt_field_measurements_raw.csv` | 1358 | Faithful export. Nothing altered except ASCII snake_case headers, ISO-8601 dates, and `HH:MM` times. Use this if you need to audit against the original workbook. |
| `lfmc_pt_field_measurements_clean.csv` | 1339 | Analysis-ready. Case-duplicate site names merged, derived date fields added, rows without an LFMC value removed, QA flags attached. |

---

## Schema — `lfmc_pt_field_measurements_clean.csv`

| Column | Type | Unit | Nulls | Notes |
|---|---|---|---|---|
| `data` | date | ISO `YYYY-MM-DD` | 0 | Sampling date |
| `ano` | int | year | 0 | Derived |
| `mes` | int | 1–12 | 0 | Derived |
| `dia_juliano` | int | 1–366 | 0 | Derived — day of year, for seasonal terms (e.g. the Yebra `FD` functions) |
| `hora` | time | `HH:MM` | 258 | Local time. Sampling clusters ~13:00–15:15 (near-peak dryness) |
| `nucleo_sub_regional` | str | — | 2 | ICNF sub-regional nucleus, 10 distinct |
| `local_recolha` | str | — | 40 | Collection site, 24 distinct after case merge |
| `especie` | str | — | 2 | 9 distinct |
| `grupo` | str | — | 2 | 6 distinct fuel groups; deterministic 1:1 function of `especie` |
| `hcv` | float | **ratio** (g water / g dry matter) | 0 | **As stored in the workbook.** Range 0.09–3.18 |
| `hcv_pct` | float | **percent** | 0 | Derived = `hcv × 100`. Range 9–318 % |
| `t_ar_c` | float | °C | 279 | Air temperature at sampling |
| `hr_pct` | float | % | 283 | Relative humidity at sampling |
| `qa_flags` | str | — | 0 | `|`-separated codes, empty when clean |

### ⚠️ The `HCV (%)` column header is misleading

The original header reads `HCV (%)` but the values are **ratios, not percentages** — the mean is
1.03, not 103. This is the standard dry-weight LFMC ratio. `hcv_pct` is provided so that the values
are directly comparable with the literature (Yebra ME thresholds of 40 % / 105 %, Chuvieco FMC_max
of 340 % / 210 %, etc.). Pick one and be consistent; mixing them silently is the likeliest way to
break a downstream regression.

### `especie` → `grupo` mapping (fully consistent, no conflicts)

| Espécie | Grupo | n |
|---|---|---|
| Urze | Matos atlânticos | 276 |
| Tojo | Matos atlânticos | 233 |
| Carqueja | Matos atlânticos | 188 |
| Esteva | Matos mediterrânicos | 222 |
| Carrasco | Matos mediterrânicos | 52 |
| Herbáceas | Herbáceas | 130 |
| P. bravo | Pinhais | 128 |
| Giesta | Giestais | 71 |
| Eucalipto | Outro | 37 |

---

## Coverage

**Period:** 2019-06-04 → 2022-08-03. Summer-season sampling only.

| Year | n |
|---|---|
| 2019 | 81 |
| 2020 | 564 |
| 2021 | 429 |
| 2022 | 265 |

| Núcleo sub-regional | n |
|---|---|
| Aveiro, Viseu e Dão Lafões | 263 |
| Alto Tâmega e Terra de Trás-os-Montes | 195 |
| Douro | 147 |
| AML e Alentejo Litoral | 143 |
| Médio Tejo e Lezíria do Tejo | 127 |
| Alto Alentejo, Alentejo Central e Baixo Alentejo | 124 |
| Alto Minho e Cávado | 122 |
| Beira Baixa, Beiras e Serra da Estrela | 116 |
| Tâmega e Sousa e Ave | 92 |
| **Algarve** | **8** |

> **Algarve is effectively absent.** 8 records under `Algarve`, plus 6 more at the `Faro` site
> mislabelled under `AML e Alentejo Litoral` (see QA below) — 14 in total, all at one site. This
> dataset will not support Algarve-specific calibration; it is a national dataset dominated by the
> north and centre. `Matos mediterrânicos` (Esteva + Carrasco, n=274) is the closest proxy for
> Algarve fuel types.

## LFMC distribution by species (`hcv_pct`)

| Espécie | n | mean | sd | min | median | max |
|---|---|---|---|---|---|---|
| P. bravo | 128 | 145.2 | 23.5 | 62.0 | 138.0 | 223.0 |
| Eucalipto | 37 | 140.8 | 27.4 | 87.0 | 137.2 | 187.0 |
| Tojo | 233 | 115.9 | 39.3 | 36.0 | 116.0 | 235.0 |
| Giesta | 71 | 110.3 | 41.1 | 65.9 | 95.0 | 318.0 |
| Carqueja | 188 | 99.7 | 26.9 | 55.0 | 92.0 | 196.0 |
| Esteva | 222 | 94.6 | 32.0 | 41.0 | 88.8 | 228.0 |
| Urze | 276 | 91.9 | 27.4 | 19.2 | 91.0 | 197.4 |
| Carrasco | 52 | 78.0 | 30.1 | 20.0 | 75.5 | 165.0 |
| Herbáceas | 130 | 76.7 | 47.2 | 9.0 | 65.3 | 254.0 |

---

## Data quality

### Applied in the clean file (unambiguous, case-only)

| Original | Merged to | Rows |
|---|---|---|
| `Arrábida - setúbal` | `Arrábida - Setúbal` | 1 |
| `frança - Bragança` | `França - Bragança` | 9 |
| `Castelo branco` | `Castelo Branco` | 21 |

Two `Hora` cells stored Excel 1900-epoch datetimes (`1900-01-27 12:00`, `1900-01-31 14:25`) rather
than time values; the time component was extracted.

19 rows with no LFMC measurement were removed (4 carried temperature/humidity only, the rest were
blank placeholder rows, 8 of them from June 2021 and 4 with no date at all). They remain in the raw
file.

### Flagged, not corrected

| Flag | Rows | Issue |
|---|---|---|
| `local_em_falta` | 40 | `local_recolha` and/or `nucleo_sub_regional` missing |
| `nucleo_faro_inconsistente` | 6 | Site `Faro` recorded under `AML e Alentejo Litoral`; the other 8 Faro records are under `Algarve`. Faro is in Algarve — but confirm before reassigning |
| `especie_em_falta` | 2 | LFMC value present, species missing |
| `temperatura_fora_intervalo` | 1 | 2022-05-02, Lamares - Vila Real: 53.1 °C with RH 64 % — internally implausible; likely a transcription error for 35.1 or 33.1 |

### Site names needing a human decision (NOT merged)

The 2019 records use municipality names while later records use the specific site. These are
probably the same locations, but merging them changes the site count and any per-site statistic, so
it was left to you:

| Coarse name | Likely specific site(s) |
|---|---|
| `Bragança` (16) | `França - Bragança` (66), `Oleirinhos - Bragança` (8) |
| `Vila Real` (18) | `Lamares - Vila Real` (136) |
| `Ponte de Lima` (24) | `Labruja - Ponte de Lima` (20) |
| `Castro d'Aire` (8) | `Granja - Castro Daire` (119) |
| `Penha - Portalegre` (32) | `S.Penha - Portalegre` (92) |

Two site names are uninformative on their own: `Olelas` (63) and `Zona industrial` (32), both under
Beira Baixa. There are **no coordinates anywhere in the workbook** — if you need to join this to
raster or weather data, geocoding these 24 sites is the missing prerequisite.

### Missingness in the meteorological columns

`t_ar_c` and `hr_pct` are absent for ~21 % of records, concentrated in 2019 and mid-2021. Any model
fitting LFMC against on-site T/RH loses those rows; using gridded reanalysis (AROME / ERA5-Land) for
the sampling date and hour would recover them, and `dia_juliano` plus `hora` are already in place for
that join.

---

## Loading

```python
import pandas as pd

df = pd.read_csv('lfmc_pt_field_measurements_clean.csv', parse_dates=['data'])

# analysis subset: complete records only
ok = df[df['qa_flags'].isna() & df['t_ar_c'].notna() & df['hr_pct'].notna()]
```
