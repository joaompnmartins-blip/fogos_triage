# Wind Adjustment Factor (WAF) & Midflame Wind — Technical Reference

**Source:** Andrews, Patricia L. 2012. *Modeling wind adjustment factor and midflame wind speed for Rothermel's surface fire spread model.* Gen. Tech. Rep. RMRS-GTR-266. Fort Collins, CO: USDA Forest Service, Rocky Mountain Research Station. 39 p.

**Status:** US Government publication (public domain). Structured for machine reading.
**Underlying models:** Albini & Baughman (1979); Baughman & Albini (1980); implementation assumptions from Finney (1998, FARSITE).

---

## 1. TL;DR

`midflame_wind = WAF × U20`, where `U20` is the 20-ft wind measured **20 ft above the top of the vegetation** — above the surface fuel bed when unsheltered, above the tree tops when sheltered.

Two models, selected by a sheltering criterion that **differs between applications**:

| | Equation | Depends on |
|---|---|---|
| Unsheltered | `WAF = 1.83 / ln((20 + 0.36H) / (0.13H))` | fuel bed depth `H` (ft) |
| Sheltered | `WAF = 0.555 / (sqrt(f·H) · ln((20 + 0.36H) / (0.13H)))` | crown fill `f`, canopy height `H` (ft) |

Note both equations share the same `ln(...)` term but **`H` means something different in each**: surface fuel bed depth for unsheltered, canopy top height for sheltered. This is the single most common implementation error.

10-m wind → 20-ft wind: `U20 = U10m / 1.15` (Turner & Lawson 1978).

---

## 2. Definitions

| Symbol | Meaning | Units |
|---|---|---|
| `U20` / `U_20+H` | Wind 20 ft above top of vegetation ("free wind") | mi/h |
| `Ū` | Average wind over the height range `H` to `H+H_F` | mi/h |
| `U_C` | Wind under the canopy | mi/h |
| `H` | Fuel bed depth (unsheltered) **or** canopy top height (sheltered) | ft |
| `H_F` | Flame extent *above the fuel bed* (not flame height from ground) | ft |
| `CC` | Canopy cover, horizontal coverage | fraction or % |
| `CR` | Crown ratio = crown length / tree height | fraction |
| `CH` | Canopy height (top of canopy) | ft |
| `F` | Fraction of canopy *layer* filled with crowns = `CC/3` | fraction |
| `f` | Crown fill portion = fraction of volume under canopy top filled with crowns = `F·CR` | fraction |
| `D0` | Zero-plane displacement = `0.64H` | ft |
| `z0` | Roughness length = `0.13H` | ft |
| `K` | von Kármán constant = 0.4 | — |

"Midflame" is a **modelling convention**, not a measurable height. It is the average wind over a height range determined by the fuel bed, deliberately independent of computed flame height (otherwise flame length would be needed to compute flame length). The term applies to **surface fire only**, never crown fire.

---

## 3. Equations

### [3] Log wind profile (Sutton 1953)
```
Ū_z = (U* / K) · ln((z − D0) / z0)
```
with `D0 = 0.64H`, `z0 = 0.13H`.

### [4] Wind at height `x` above top of vegetation
```
U_{H+x} = (U* / K) · ln((H + x − 0.64H) / (0.13H))
```
Used for point-height WAF (see §6):
```
WAF(x) = ln((x + 0.36H)/(0.13H)) / ln((20 + 0.36H)/(0.13H))
```

### [5] Wind at top of vegetation relative to 20-ft wind
```
U_H / U_20+H = 1 / ln((20 + 0.36H) / (0.13H))
```

### [6] Unsheltered WAF, general form (any flame extension ratio)
```
Ū / U_20+H = ((1 + 0.36H/H_F) / ln((20 + 0.36H)/(0.13H))) · (ln((H_F/H + 0.36)/0.13) − 1)
```

### [7]/[8] Unsheltered WAF for `H_F = H` (BehavePlus, FARSITE, FlamMap, FSPro, FPA, FuelCalc, Scott 2007)
```
WAF = 1.83 / ln((20 + 0.36H) / (0.13H))
```
i.e. wind averaged from the top of the fuel bed to **twice the fuel bed depth**. Equivalent to assuming flame height (from ground) = 2 × fuel bed depth.

### [9]/[10] Crown fill portion
```
F = CC / 3                       # CC as fraction
f = F · CR                       # BehavePlus, FuelCalc
f = (CC/100) · (π/12)            # FARSITE/FlamMap/FSPro/FPA (implies CR = 1 and a π/4 packing factor)
```
The `/3` comes from a conical crown = 1/3 the volume of its bounding cylinder. FARSITE's extra `π/4` accounts for square packing of circular crown bases. FARSITE's `f` is therefore `π/4` larger than BehavePlus at `CR = 1`, making **FARSITE sheltered WAF 1.128× (≈1.13×) higher** than BehavePlus for the same stand.

### [11] Under-canopy wind relative to canopy-top wind
```
U_C / U_H = 0.555 / sqrt(f·H)
```

### [12]/[2] Sheltered WAF
```
WAF = 0.555 / (sqrt(f·H) · ln((20 + 0.36H) / (0.13H)))     # H = canopy height, ft
```

> **Documented erratum:** Finney (1998, rev. 2004) printed the metric constant as `0.3066`; the correct value is `0.555`. The FARSITE *code* was always correct; only the publication (including the 2004 printed revision) was wrong. The current online PDF is corrected.

### Units
All equations above are in **feet**. For metric input convert `H_m → H_ft = H_m / 0.3048` and use the 20-ft constant unchanged, or replace `20` with `6.096` m and `0.36H`, `0.13H` with `H` in metres consistently.

---

## 4. Sheltered vs unsheltered — the switch differs by application

This is where implementations diverge most and where results are most sensitive.

| System | Unsheltered model | Sheltered model | Sheltered criterion |
|---|---|---|---|
| BehavePlus | eq [6], `H_F = H` | eq [2] from `CC`, `CR`, `CH` | `f ≥ 5%` |
| FARSITE / FlamMap / FSPro / FPA | eq [6], `H_F = H` | eq [2] from `CC`, `CH`; `CR = 1` | `CC > 0` |
| FuelCalc | eq [6], `H_F = H` | eq [2] from `CC`, `CR`, `CH` | `min(WAF_sheltered, WAF_unsheltered)` |
| Nomographs (Albini 1976) | 0.5 fixed | 0.5 fixed | n/a |
| BEHAVE TSTMDL | eq [6], `H_F` = flame length | n/a | n/a |
| FVS-FFE | 0.5 fixed | interpolated from 5 points on `CC` | `CC > 5%` |
| Scott (2007) tables | per fuel model (2 dp) | binned by `CC`, `CR = 1` | `CC > 5%` |

### Consequences worth knowing

- **BehavePlus produces a step discontinuity.** At the `f = 5%` boundary WAF jumps (e.g. fuel model 2, `CC` 40%, `CH` 50 ft: WAF 0.36 at `CR` 0.3 → 0.17 at `CR` 0.5). Not a bug — it is the switch between two unrelated models.
- **FuelCalc removes the step** by taking the minimum of both models. Where they differ, FuelCalc gives lower WAF → lower modelled fire behaviour.
- **FARSITE trap:** because the criterion is `CC > 0`, a canopy cover of 1% gives sheltered WAF ≈ 0.74 — *higher* than the unsheltered value, which is physically wrong. Users who set `CC` from 0 to a small non-zero value to enable spotting silently change WAF and surface fire behaviour. Sheltered WAF should never exceed unsheltered WAF; guard for this.
- At `CR = 0.1`, BehavePlus treats fuel as unsheltered even at `CC = 100%`. At `CR = 0.9`, fuel is unsheltered below `CC ≈ 17%`.
- Sheltered WAF does **not** depend on fuel model at all — only on `CC`, `CR`, `CH`.
- Crown fill portion `f` has more influence on sheltered WAF than canopy height does.

---

## 5. Influence on modelled fire behaviour

Fuel model 2, dead FM 5%, live FM 75%, slope 0%:

| U20 (mi/h) | WAF 0.2 → ROS (ch/h) | WAF 0.4 → ROS | WAF 0.7 → ROS |
|---|---|---|---|
| 4 | 3.9 | 7.3 | 15.8 |
| 8 | 7.3 | 19.4 | 49.4 |
| 12 | 12.5 | 37.9 | 101.0 |
| 16 | 19.4 | 62.4 | 169.2 |
| 20 | 27.9 | 92.6 | 253.2 |

Canopy cover effect (FM 2, `CH` 50 ft, `CR` 0.7, `U20` 20 mi/h, PINPON DBH 18 in):

| CC % | WAF | model used | Flame length (ft) | Scorch (ft) | Mortality % |
|---|---|---|---|---|---|
| 20 | 0.36 | Unsheltered | 9.2 | 67 | 80 |
| 40 | 0.15 | Sheltered | 4.5 | 28 | 14 |
| 80 | 0.10 | Sheltered | 3.6 | 20 | 7 |

WAF propagates into every downstream module: SCORCH, MORTALITY, CROWN, SPOT, SAFETY, SIZE, CONTAIN.

---

## 6. Definition of midflame height — sensitivity

Fuel model GS2, `H` = 1.5 ft, dead FM 5%, live FM 75%, slope 0%, `U20` = 15 mi/h. Using eq [4] for point heights:

| "Midflame" height above ground | Height above fuel (ft) | WAF | Midflame wind (mi/h) | ROS (ch/h) | Flame length (ft) |
|---|---|---|---|---|---|
| 1.5–3 ft (avg to 2× depth) — **model definition** | 0–1.5 | 0.39 | 5.9 | 31 | 5.8 |
| 3 ft (2× fuel bed depth) | 1.5 | 0.50 | 7.5 | 43 | 6.8 |
| 4 ft (shorter person, hand-held) | 2.5 | 0.59 | 8.8 | 54 | 7.5 |
| 5.5 ft (taller person, hand-held) | 4.0 | 0.68 | 10.2 | 66 | 8.3 |
| 6.56 ft (2 m) | 5.06 | 0.72 | 10.8 | 72 | 8.6 |

**A hand-held eye-level observation is not the model's midflame wind.** The model uses an average over a height range; an anemometer reads a point. Treating a 2-m or eye-level reading as midflame roughly doubles ROS relative to the model definition for a shallow fuel bed. FARSITE's wording ("reduced to a nominal height equal to twice the fuel bed depth") is misleading — it uses the *average over* the range, not the wind *at* that height.

---

## 7. Data files

| File | Contents |
|---|---|
| `waf_fuel_models.csv` | 53 standard fuel models: fuel bed depth, calculated unsheltered WAF (3 dp and 2 dp), BehavePlus Help rounded value |
| `waf_tables_13fm_comparison.csv` | Unsheltered WAF for the original 13 FM across BehavePlus / Baughman & Albini / Rothermel 1983 / Fireline Handbook / Scott 2007 |
| `waf_sheltered.csv` | Sheltered & partially sheltered WAF: Baughman & Albini vs BehavePlus/Rothermel/Fireline Handbook vs Scott 2007 CC bins |
| `waf_nfdrs.csv` | WAF for 1978 / 1988 NFDRS fuel models and retired NFMAS |
| `waf.py` | Reference implementation, all variants, with the validation suite from §10 |

---

## 8. Selected table content (inline)

### Sheltered / partially sheltered guidance
| Condition | Baughman & Albini (1980) | BehavePlus / Rothermel (1983) / Fireline Handbook |
|---|---|---|
| Partially sheltered | 0.25 | 0.3 |
| Fully sheltered, sparse, shade-intolerant | 0.17 | 0.2 |
| Fully sheltered, sparse, shade-tolerant | 0.14 | 0.2 |
| Fully sheltered, dense, shade-intolerant | 0.12 | 0.1 |
| Fully sheltered, dense, shade-tolerant | 0.08 | 0.1 |

Descriptive classes (BehavePlus Help / Fireline Handbook):
- **Unsheltered** — no overstory, sparse overstory, timber that has lost its foliage, timber on high ridges offering little shelter. WAF by fuel bed depth: 0.5 (depth < 0.9 ft / 0.3 m), 0.4 (0.9–2.7 ft / 0.3–0.8 m), 0.3 (> 2.7 ft / 0.8 m).
- **Partially sheltered** — patchy timber; timber at midslope or higher with wind blowing directly at the slope. WAF 0.3, all fuel models.
- **Fully sheltered** — standing timber on flat or gentle slope; near base of mountain with steep slopes. WAF 0.2 open stands, 0.1 dense stands.

No WAF in the BehavePlus Help table exceeds 0.5.

### Scott (2007) sheltered WAF by canopy cover (`CR = 1` assumed)
| Canopy cover | WAF |
|---|---|
| CC ≤ 5% | use unsheltered table |
| 5 < CC ≤ 10 | 0.30 |
| 10 < CC ≤ 15 | 0.25 |
| 15 < CC ≤ 30 | 0.20 |
| 30 < CC ≤ 50 | 0.15 |
| CC > 50 | 0.10 |

### Albini & Baughman (1979) stand typing (for reference / defaults)
| | Shade-tolerant young | tolerant mature | Shade-intolerant young | intolerant mature |
|---|---|---|---|---|
| `F` dense / open | 0.4 / 0.1 | 0.4 / 0.1 | 0.4 / 0.1 | 0.4 / 0.1 |
| `CR` dense / open | 0.8 / 0.9 | 0.6 / 0.7 | 0.4 / 0.7 | 0.2 / 0.5 |
| `f` dense / open | 0.32 / 0.09 | 0.24 / 0.07 | 0.16 / 0.07 | 0.08 / 0.05 |

Typical/extreme `f` values used by the authors for plotting: 5%, 15%, 32%. The 5% value — considered *extreme* by Albini & Baughman — is what BehavePlus adopted as its sheltered/unsheltered cutoff.

---

## 9. Model limitations (Albini & Baughman 1979, "Applicability of Results")

1. **Flat terrain assumed** throughout. Substantial slope or roughness changes the windfield; deviations may be large.
2. **Adequate fetch assumed** to establish a uniform friction layer. Near forest edges, lakeshores, or vegetation transitions the results may be inaccurate.
3. **Well-behaved (steady) windfield assumed.** If speed/direction fluctuate significantly, the friction layer is in a transient state and results may not apply.
4. **No fire–wind interaction.** Any fire-induced disturbance of the windfield invalidates the results.

Additional:
- Neutral atmospheric stability assumed near the ground; convective slope winds have a different profile.
- Sheltered model assumes wind is **constant with height under the canopy**. Schroeder & Buck (1970) observed that in stands open beneath the main canopy, speed increases with height to mid-trunk space then decreases in the canopy zone.
- Crowns are assumed uniform cones; the same `CC` can come from many narrow trees or few broad ones.
- WAF uses the canopy description **at the point only** — not surrounding vegetation, wind direction, or slope position. Two stands with identical structure and `U20` can have very different real midflame wind (small thinned patch in closed timber vs large thinned unit next to a meadow).
- WAF addresses **only vertical adjustment**. Horizontal variation of `U20` across terrain is a separate problem — use WindNinja / WindWizard (Butler et al. 2006; Forthofer et al. 2009). FARSITE applies WAF per pixel using that pixel's vegetation only, ignoring neighbours.
- Geospatial systems assume conditions constant per pixel (often 30 m).

**Reporting practice recommended by the author:** report fire modelling results together with the source — reference, program, version number — and ideally the model assumptions, because WAF implementations legitimately differ between systems.

---

## 10. Validation checkpoints for any implementation

All of these are reproduced by `waf.py`:

| Check | Inputs | Expected |
|---|---|---|
| Unsheltered eq [8] | `H` = 1.0 ft | 0.362 (→ 0.36) |
| Unsheltered eq [8] | `H` = 0.2 ft | 0.275 (→ 0.28) |
| Unsheltered eq [8] | `H` = 6.0 ft | 0.547 (→ 0.55, table shows 0.5 when rounded to tenths) |
| Unsheltered eq [8] | `H` = 1.5 ft (GS2) | 0.39 |
| All 53 fuel models | depths in `waf_fuel_models.csv` | match Scott (2007) fig. 28 / BehavePlus fig. 18 at 2 dp |
| Sheltered, BehavePlus | FM2, `CC` 40%, `CH` 50, `CR` 0.5/0.7/0.9 | `f` = 6.7/9.3/12.0%; WAF 0.17/0.15/0.13 |
| Sheltered, BehavePlus | FM2, `CC` 40%, `CH` 50, `CR` 0.1/0.3 | `f` = 1.3/4.0% → unsheltered, WAF 0.36 |
| Sheltered, BehavePlus | `CC` 60/80/100, `CH` 50, `CR` 0.3 | 0.18 / 0.16 / 0.14 |
| Sheltered, BehavePlus | `CC` 60/80/100, `CH` 50, `CR` 1.0 | 0.10 / 0.09 / 0.08 |
| Sheltered, FARSITE | `CC` 1%, `CH` 100 | 0.74 (and > unsheltered → flag) |
| FARSITE vs BehavePlus | same stand, `CR` = 1 | ratio = sqrt(4/π) ≈ 1.128 |
| Point-height WAF eq [4] | `H` 1.5, z = 3.0 / 4.0 / 5.5 / 6.56 ft | 0.50 / 0.59 / 0.68 / 0.72 |

**Known inconsistency in the source:** Table 11 (FuelCalc vs BehavePlus, `CH` 100 ft) states `CR` = 0.5 in its footnote, but its WAF column is only reproducible with `CR ≈ 0.4`. Equations [9]/[10] as documented reproduce figures 5, 20 and 23 exactly, so `waf.py` follows the equations, not table 11.

Documented differences that are *not* implementation errors:
- Baughman & Albini (1980) list 0.36 for fuel models 8 and 9 (they used `H_F/H` = 2.5 there); eq [6] with `H_F = H` gives 0.28.
- Rothermel (1983) used computed flame height as `H_F`, so his hundredths differ; his table values were then set by judgement, not strict rounding (e.g. computed 0.32 for FM 8 published as 0.4).
- BehavePlus versions prior to 5.0.3 listed SH4 with WAF 0.4 in error (correct: 0.46 → 0.5).
- Burgan (1988) incorrectly listed the 1978 NFDRS WAF for fuel model E as 0.5 (correct: 0.4).

**Additional erratum found during validation of this transcription:** report table 9 prints the BehavePlus calculated WAF for fuel model 13 (`H` = 3.0 ft) as **0.469**; equation [8] gives **0.4587**. Every other value in that column reproduces to three decimals, and both figure 18 and Scott (2007) list 0.46 for FM 13 and for GR7 (also 3.0 ft). Treat 0.469 as a typo — the CSV and `waf.py` use 0.459.

---

## 11. NFDRS notes

- NFDRS produces fire danger **indices**, not fire behaviour values. Stations are in the open, worst-case assumption, so sheltering is not modelled.
- 1972 NFDRS: single WAF (`r`) = 0.5 for all 9 fuel models. Schroeder et al. (1972) found `r` between 0.4 and 0.6 across models and fixed it at 0.5.
- 1978 NFDRS: WAF per fuel model — 0.6 grass, 0.5 shrub/brush, 0.4 timber.
- 1988 NFDRS: constant WAF if no live woody component or if woody is evergreen; **variable seasonal WAF** if woody is deciduous — maximum in winter (leaf drop, less reduction), minimum in summer (fully green), varying with the woody greenness factor. In practice variable WAF applies only to fuel models C, E, Q and R. Designating woody as deciduous for models G and H effectively changes WAF from 0.4 to 0.3.
- 1988 NFDRS precipitation rule: if > 0.1 in fell on the current or previous day, **WAF is multiplied by 0.3**. This is an artificial index adjustment to reduce wind sensitivity until dead fuels have had a day of drying — it does not represent any real wind effect.
- NFMAS is retired, replaced by FPA (which uses fire behaviour fuel models and FlamMap modelling). Its WAF values are kept in `waf_nfdrs.csv` for historical documentation only.

---

## 12. Practical guidance

- Point systems (BehavePlus, nomographs) leave room for **judgement**: consider wind direction, adjacent vegetation, slope position, ability of wind to penetrate the overstory. Direct WAF entry remains valid and is often preferable to calculation.
- Geospatial systems (FARSITE, FlamMap, FPA) **must** calculate — judgement has no place across thousands of pixels — so they inherit all the uniformity assumptions.
- Never run a single calculation near the sheltered/unsheltered transition. Sweep `CC` and `CR` and look at where the model switches; that transition is exactly where fuel treatment assessments are most sensitive.
- Variation in fuel bed depth, stand characteristics, and wind speed/direction is often a larger source of uncertainty than WAF itself — but WAF is not negligible, and it is fully under the modeller's control.
