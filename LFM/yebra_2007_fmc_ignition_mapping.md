---
title: "Fuel moisture estimation for fire ignition mapping"
authors:
  - Yebra, Marta
  - Aguado, Inmaculada
  - García, Mariano
  - Nieto, Héctor
  - Chuvieco, Emilio
  - Salas, Javier
affiliation: "Departamento de Geografía, Universidad de Alcalá, Colegios 2, 28801 Alcalá de Henares, España"
venue: "Wildfire 2007 — 4th International Wildland Fire Conference, Sevilla, España"
year: 2007
short_ref: "Yebra et al. (2007)"
topics: [LFMC, DFMC, MODIS, NOAA-AVHRR, moisture of extinction, ignition potential, Firemap]
source_file: YebraWildfire2007.pdf
---

# Fuel moisture estimation for fire ignition mapping

> **Conversion note.** This Markdown is a faithful transcription of the source PDF, including its
> original typos and internal inconsistencies. Where OCR of equations or tables is ambiguous, the
> ambiguity is flagged inline in a `⚠️ OCR/consistency note` block. Do not treat flagged equations
> as authoritative without checking the original PDF or Chuvieco et al. (2004).

---

## Abstract

Fuel moisture content (FMC) is a critical variable for fire danger estimation since it affects fire
ignition and fire propagation. Current methods for FMC estimation rely on meteorological data,
which are good predictors of dead fuels, but they do not provide a reliable estimation of live
fuels. Additionally, the integration of dead and live fuels is not commonly pursued.

This paper presents the results of a Spanish research project that has tested the operational
estimation of FMC from satellite data and meteorological danger codes for fire ignition probability
mapping. Live FMC (LFMC) has been derived from NOAA-AVHRR and Terra-MODIS satellite data. Different
models for grasslands and shrublands have been derived, using empirical and simulation approaches.
FMC of dead fuels (DFMC) has been estimated from the 10 h moisture code. In order to integrate dead
and live FMC, both values have been converted to ignition probability using the moisture of
extinction (ME). ME for dead fuels was taken from the BEHAVE fire simulation system, assigned values
of 12 % (model 1), 15 % (model 2) and 25 % (model 9), while for live fuels average values of 40 %
and 105 % were used for grassland and shrublands respectively. Both indices have been mapped at
1 km² spatial resolution, and will be integrated with other fire danger variables within a
comprehensive index of fire risk.

---

## 1. Introduction

FMC of both live (LFMC) and dead (DFMC) fuels is one of the most important variables in fire
ignition and fire behaviour modelling, and is therefore considered in most fire danger rating
systems worldwide. Fuel water content is inversely related to the probability of ignition, because
part of the energy necessary to start a fire is consumed by evaporation immediately before ignition
(Dimitrakopoulos and Papaioannou 2001). Water content also affects fire propagation, since the
flame source is reduced with humid materials, thereby reducing flammability (Viegas 1998).

FMC estimation has been based on several methods: field sampling, meteorological indices and remote
sensing.

- **Field sampling** — most direct, but the most costly; unfeasible at regional or global scale.
- **Meteorological indices** — measure FMC indirectly through atmospheric characteristics. Reasonably
  well suited for dead fuels, whose water content is highly related to atmospheric conditions.
  However, live fuels have different physiological characteristics and drought adaptations, so a
  great diversity of moisture conditions can be found under the same meteorological inputs
  (Viegas and others 2001). Therefore meteorological indices are **not** appropriate for LFMC.
- **Remote sensing** (reflectance or surface temperature) — directly derived from vegetation
  condition, so a better alternative for LFMC but **not** for DFMC: dead materials sit under the
  canopy (not directly sensed) and are less sensitive to changes in radiance
  (Chuvieco, Aguado and others 2004).

Consequently, operational estimation of fire occurrence given a particular FMC should be derived
from the **joint use** of meteorological danger codes and remote sensing techniques (empirical or
simulation-based).

FMC is not the only variable in a wildfire risk system; socio-economic factors also affect
occurrence probability. Combining all fire danger variables into a synthetic index is difficult,
especially inside a GIS. Few fire danger systems operationally use GIS technologies
(Lee, Alexander and others 2002), mainly due to difficulties in generating the spatial distribution
of key variables such as lightning activity or human factors (Chuvieco, Allgöwer and others 2003)
and the difficulty of integrating those factors into the same "danger scale".

### 1.1 The Firemap project

The use of GIS webmapping and remote sensing in a semi-operational fire danger assessment is the
objective of the **Firemap** project, funded by the Spanish Ministry of Science and Technology,
which aims to provide daily fire danger information to fire managers. The danger index (Fig. 1) was
based on a proposal within the European **Spread** project (Chuvieco, Allgöwer and others 2003). In
that terminology, *fire risk* = probability that a fire occurs (**danger**) + potential damage
(**vulnerability**). Vulnerability is not covered in this paper.

Within the danger component, Spread proposed:

- **Ignition danger** — causal agents of fire plus the condition of the fuel (dead and live).
- **Propagation danger** — predictable fire behaviour, driven by wind, slope and fuel load.

This paper addresses the role of FMC in **fire ignition**. The likelihood is defined as the ignition
potential associated with fuel moisture status, identified as **IP_f**. These values are ready to be
integrated with other ignition-source variables (lightning IP_l, human IP_h), so that final ignition
danger is expressed on a common scale as a product of several ignition probabilities within a
GIS-based fire danger rating system.

**Figure 1** *(image, not transcribed)*: Framework of the Firemap project. Tree structure:
`Risk Index` → {`Occurrence Probability` → {`Ignition Danger` → {`Cause` → {Human, Natural
(lightning)}, `Fuel Moisture Status` → {Dead, Live}}, `Propagation Danger` → {Fuel model, Wind,
Slope}}, `Vulnerability` → {`Socio-economic value` → {Landscape, Houses, Products}, `Natural value`
→ {`Degradation potential` → {Erosion, Plant dynamic}, `Landscape value` → {Protected areas,
Intrinsic value}}}.

The Firemap system started in May 2006 in four Spanish regions (Aragón, Huelva, Madrid, Valencia).
The case study presented here is the **region of Madrid, 12 August 2006**.

---

## 2. Methodology

### 2.1 Field sampling

A standard field campaign was carried out in **Cabañeros National Park** (central Spain) from spring
(April) to end of summer (September) to obtain LFMC and DFMC measurements and the critical
biophysical parameters for generating the simulated dataset.

| Item | Detail |
|---|---|
| LFMC species | Grasslands + Mediterranean shrubs: *Cistus ladanifer*, *Erica australis*, *Phillyrea angustifolia*, *Rosmarinus officinalis* |
| LFMC period | 1996–2005, every 8 or 16 days |
| Biophysical measures | 2004 and 2005, for grassland and *Cistus ladanifer* (the latter chosen as representative of Mediterranean shrubland) |
| DFMC samples | Litter and cured grass, 1998–2003 |
| Extra validation campaign | 2001 and 2002 — Comunidad Autónoma de Madrid (CAM), Castilla y León, Andalucía; LFMC every 16 days |

Detailed field-work description: Chuvieco and others (2003); Yebra, Chuvieco and others.

### 2.2 Live fuel moisture content estimation

Empirical and simulation approaches were explored, with remotely sensed reflectance at different
spatial and spectral resolutions.

**Empirical methods** — multivariate linear regression (MLR) between field-measured LFMC
(*Cistus ladanifer* and herbaceous species) and remotely sensed data from Terra-MODIS
(Yebra, Chuvieco and others 2006) and NOAA-AVHRR.

**MODIS source data**

- Product **MOD09A1** (atmospherically corrected reflectance), 8-day composite, first seven bands,
  500 m (Vermote and Vermeulen 1999).
- Downloaded from LP DAAC (USGS), reprojected sinusoidal → UTM, resampled to a common **1 km**
  resolution by nearest neighbour.

**AVHRR source data**

- Daily 1 km NOAA-AVHRR acquired by the HRPT receiving station at the Dept. of Geography,
  University of Alcalá.
- Raw data → reflectance using NOAA coefficients and degradation rates.
- Surface temperature (T_s) derived with the method of Coll and Caselles (1997).
- Geometric correction with orbital models; multitemporal coregistration assured with GCPs.
- Daily images composited using the MVC–brightness temperature criterion.

**Plot extraction** — median of a 3 × 3 pixel kernel centred on the field plot, to reduce noise from
residual atmospheric effects and geo-referencing errors.

#### 2.2.1 Temporal (day-of-year) variable

A temporal variable based on the day of the year (`DJ`, 1–365) was included in the MLR, as suggested
by Chuvieco and others (2004b), to account for seasonal FMC trends. Periodic functions were fitted
to the temporal average of sampled FMC for grassland and *Cistus ladanifer*, separately for **dry
years** (1999 and 2005) and **normal/wet years** (rest of the series). Dry/wet classification used
Cabañeros meteorological data for 1998–2003 and 2005.

**Dry years**

```
(1)  FDp = ( sin( 1.5  × π × (DJ + DJ^(1/3)) / 365 ) )^6 × 0.55
(2)  FDm = ( ( sin( 1.55 × π ×  DJ / 365 ) )^2 + 0.65 ) × 0.5
```

**Normal years**

```
(3)  FDp = ( sin( 1.5 × π × (DJ + DJ^(1/2)) / 365 ) )^6 × 1.5
(4)  FDm = ( ( sin( 1.6 × π ×  DJ / 365 ) )^2 + 1 ) × 0.5
```

> ⚠️ **OCR/consistency note**
> - Eq. (2) is printed in the PDF with unbalanced parentheses (`FDm = (sin(1.55×π×DJ/365))² + 0.65) * 0.5`).
>   The bracketing above is the only reading that is dimensionally consistent with Eq. (4).
> - `FDp` / `FDm` almost certainly stand for *pastizal* (grass) and *matorral* (shrub); Table 1 refers
>   to the same terms as `FD_G` and `FD_S`. Treat `FDp ≡ FD_G` and `FDm ≡ FD_S`.

#### 2.2.2 Simulation approach (RTM inversion)

Inversion of two radiative transfer models: **PROSPECT** (Jacquemoud 1990) at leaf level and
**SAILH** (Verhoef 1984; Kuusk 1985) at canopy level. The inversion technique built empirical
relationships over RTM simulations and vegetation indices derived from MOD09A1 simulated reflectance
bands, as explained in Yebra (2006).

- Leaf biophysical parameter ranges: from field measurements.
- Viewing geometry and canopy structure: from MOD09A1 and **MOD15A2** respectively, plus literature.
- MOD15A2 = MODIS LAI product, generated daily at 1 km, composited over 8 days on the maximum value
  of the photosynthetic radiation product (Knyazikhin, Glassy and others 1999).

#### 2.2.3 Validation approach

All calibrated equations were validated on a MODIS/AVHRR validation dataset for the same study area
(Cabañeros) at different dates. Best performers were then validated at the extra study sites. RMSE
was computed and decomposed into:

- **RMSEs** (systematic) — errors from uncontrolled factors.
- **RMSEu** (unsystematic) — errors from model performance and the predictors included.

A good model is considered to have **RMSEu ≫ RMSEs**.

### 2.3 Dead fuel moisture estimation

A two-step process (Aguado and others, in review): (1) develop an empirical model to estimate DFMC
from meteorological data by selecting the index best adapted to Mediterranean areas; (2) compute the
selected index for the whole study region from forecast weather data via spatial interpolation.

Calibration was based on the Cabañeros field sampling. Since the model targets FMC of **cured
grasses and litter**, it had to be based on moisture indices for the finest dead fuels. Two codes
were selected:

| Code | System | Reference |
|---|---|---|
| Fine Fuel Moisture Code (FFMC) | Canadian FWI | Van Wagner (1987) |
| 10-hour code | US NFDRS | Bradshaw, Deeming and others (1983) |

Index selection was based on multitemporal correlation between field data and the meteorological
moisture codes, with yearly correlations computed per fuel type. Linear regression produced separate
models for grasses and litter plus a joint model. For all regressions, a random **70 %** of the
study periods was used for calibration and the remaining **30 %** for validation. Performance was
measured by Pearson *r* and RMSE.

#### 2.3.1 Meteorological field generation

Spatial interpolation was applied to **forecast** variables rather than measured ones. Estimated
fields of **14:00 GMT** meteorological inputs for the Madrid region were obtained with a two-step
method:

1. **Statistical downscaling** of ECMWF NWPM surface temperature and relative humidity forecasts.
   The ECMWF horizontal grid (0.5° × 0.5°) is too coarse for topographically complex regions like
   Madrid, so empirical relationships between ECMWF forecasts and observations at **35 weather
   stations** were used to produce forecasts for those 35 sites.
2. **Spatial interpolation** to a regular **500 × 500 m** grid, using a quadratic inverse-distance
   algorithm on horizontal distances between grid point and surrounding stations. Altitude effects
   were accounted for via the variable/altitude gradient detected in the 35-site prediction.

### 2.4 Conversion of FMC values to fire ignition danger

All danger variables are transformed to a common scale from **0** (null probability) to **1**
(maximum probability). The probability of fire occurrence associated with FMC is based on the
**moisture of extinction (ME)** concept, successfully tested previously (Chuvieco, Aguado and others
2004). ME is the threshold moisture content above which a fire cannot be sustained (Rothermel 1972);
despite some criticism the concept is widely used (Burgan, Klaver and others 1998).

**ME values used**

| Fuel | ME | Source / note |
|---|---|---|
| Dead — BEHAVE model 1 (grass with FMC < 30 %) | 12 % | Burgan and Rothermel (1984) |
| Dead — BEHAVE model 2 (grass with FMC < 30 %) | 15 % | Burgan and Rothermel (1984) |
| Dead — BEHAVE model 9 (litter) | 25 % | Burgan and Rothermel (1984) |
| Live — annual grassland | 40 % | Chuvieco, Aguado and others (2004) |
| Live — shrubs | 105 % | Chuvieco, Aguado and others (2004) |

ME of dead fuels generally varies between 12–40 % depending on fuel type. Grasslands with FMC below
30 % were treated as dead fuels.

**IP algorithm.** ME values act as relative ignition thresholds above which ignition potential drops
sharply. Rather than forcing IP = 0 above ME, a conservative approach assumes a marginal IP persists
at high FMC: Chuvieco (2004) assigns a **maximum IP of 0.2** at FMC = ME. Below ME, IP ranges 0.2–1
(linearly inversely proportional to FMC); above ME, IP ranges 0.2–0. Null ignition potential
(IP = 0) is assigned at the **maximum FMC recorded in the 1996–2005 historical field series**.

```
If FMC > ME:
    IP = ( 1 − ( (FMC − ME) / (FMC_max − ME) ) ) × 0.2
Else:
    IP =   ( 0.2 + (ME − FMC) / (ME − FMC_min) ) × 0.8      # as printed in the PDF
```

> ⚠️ **OCR/consistency note on the `Else` branch.** As printed, the branch yields IP = 0.16 at
> FMC = ME and IP = 0.96 at FMC = FMC_min, which contradicts the surrounding text (IP should span
> 0.2 → 1). The formulation consistent with the text is:
> ```
> IP = 0.2 + ( (ME − FMC) / (ME − FMC_min) ) × 0.8
> ```
> Verify against Chuvieco et al. (2004), *Can. J. For. Res.* 34(11): 2284–2293, before implementing.

`FMC_max` and `FMC_min` are the maximum and minimum FMC values of each fuel type from field
sampling. Although site specific, they can reasonably be applied to relatively large regions with
similar environmental conditions. Applying the algorithm yields **IP_live** and **IP_dead**.

**Integration of live and dead IP**, weighting by the fuel load associated with each BEHAVE fuel
model:

```
IP_f = ( IP_live × %livefuelload ) + ( IP_dead × (100 − %livefuelload) )
```

where `%livefuelload` is the proportion of live fuel load in each grid cell, related to land cover
extracted from **CORINE Land Cover 2000**.

> ⚠️ **Consistency note.** As written, the weights are on a 0–100 scale while IP is on 0–1, so IP_f
> is not normalised to 0–1. A division by 100 is implied.

---

## 3. Results

### 3.1 Live fuel moisture content estimation

Differences between grassland models in R² and standard error (SE) are small. All independent
variables had significance below 0.01. MODIS-derived models have slightly higher R² and lower SE.
Similar adjustments hold for shrubland models — all independent variables significant at 99 %,
except GVMI in shrub model 2 (significant at 90 %). Shrub model 1 performs somewhat worse (lowest
R², highest SE).

**Table 1.** Grass (G) and Shrub (S) calibrated models. R² = determination coefficient; SE =
standard error. NDVI = Normalized Difference Vegetation Index (Rouse, Haas and others 1974);
NDII = Normalized Difference Infrared Index (Hunt and Rock 1989); VARI = Visible Atmospheric
Resistant Index (Gitelson, Kaufman and others 2002); GVMI = Global Vegetation Moisture Index
(Ceccato, Gobron and others 2002); FDx = day-of-year function (eqs. 1–4); T_s = surface temperature;
DM = dry matter content; LAI = leaf area index; PE = (see note).

| Veg. | Sensor | Method | # | Model | R² | SE (pct) |
|---|---|---|---|---|---|---|
| G | MODIS | Empirical | 1 | `FMC_G = −161.1 + 650.2 × NDVI` | 0.91 | 30.1 |
| G | MODIS | Empirical | 2 | `FMC_G = −129.12 + 503.51 × NDVI + 52.55 × FD_G` | 0.93 | 26.3 |
| G | MODIS | RTM | 3 | `FMC_G = −6.7 + 131.4 × LAI + 296.7 × NDII` | 0.89 | 29.5 |
| G | AVHRR | Empirical | 4 | `FMC_G = 27.95 + 115.51 × FDp + 331.86 × NDVI − 1.194 × T_s` | 0.85 | 36.9 |
| S | MODIS | Empirical | 1 | `FMC_S = 229.1 + 887.2 × VARI − 300.7 × GVMI` | 0.73 | 17.5 |
| S | MODIS | Empirical | 2 | `FMC_S = 104.38 + 427.57 × VARI − 163.67 × GVMI + 88.44 × FD_S` | 0.78 | 15.2 |
| S | MODIS | RTM | 3 | `FMC_S = 200.3 − 5322.8 × PE + 92.3 × GVMI` | 0.82 | 12.9 |
| S | AVHRR | Empirical | 4 | `FMC_S = 8.73 + 125.87 × FD_S + 40.79 × NDVI − 0.2294 × T_s` | 0.81 | 13.3 |

> ⚠️ **OCR notes on Table 1**
> - **Shrub model 2**: the PDF renders the last two terms as `−163.67 × GVMI × 88.44 × FD_S`
>   (a multiplication sign between the GVMI and FD_S terms). A `+` is almost certainly intended, as
>   transcribed above, but this is the single most important item to verify against the original.
> - The source uses comma decimal separators in the AVHRR rows (`1,194`, `0,2294`, `8,73`, `27,95`,
>   `115,51`, `125,87`, `40,79`); these are rendered as decimal points above.
> - The caption defines **DM** ("dry matter content") but no model in the table uses it; conversely
>   shrub RTM model 3 uses **PE**, which the caption does not define. PE is likely an equivalent
>   water thickness / dry matter related leaf parameter from the PROSPECT inversion.
> - In the PDF the grass model 2 equation is also duplicated as an overlapping artefact on top of
>   Table 2 (`FMC_Grass = −129.12 + 503.51 × NDVI + 52.55 × FD_G`); it is the same equation.

Validation at Cabañeros (Table 2): all grassland models have R² ≈ 0.9 with estimated–observed
relations close to the 1:1 slope. RMSE values are similar; the worst (model 2) is 6 % higher than
the best (model 3). Model 3 (MODIS + RTM) has a slightly lower tendency to overestimate, but is less
operational because it combines two MODIS products (MOD09 and MOD15); since accuracy is not greatly
improved, it is not worth using. **Model 1 is concluded to be the most appropriate** for grass at
this site.

For shrubland, determination coefficients are lower than for grassland. Model 3 has the lowest R²
and highest RMSE, with the systematic portion exceeding the unsystematic — it should be discarded.
Model 4 (AVHRR) has the second best adjustment but a higher tendency to overestimate, confirmed by
the constant of the validation fit. **Model 1 is again the most appropriate**, its observed–estimated
relation being closest to the 1:1 slope.

**Table 2.** Validation of the models at the Cabañeros National Park site. RMSE = root mean square
error; RMSEs and RMSEu = systematic and unsystematic portions.

| Vegetation | Model | R² | Slope | Const. | RMSE (pct) | RMSEs (pct) | RMSEu (pct) | Best (rank) |
|---|---|---|---|---|---|---|---|---|
| Grass | 1 | 0.91 | 0.93 | 12.69 | 27.38 | 10.24 | 25.40 | 2 |
| Grass | 2 | 0.87 | 0.93 | 14.70 | 33.41 | 11.90 | 31.22 | 4 |
| Grass | 3 | 0.93 | 0.92 | 0.17 | 24.57 | 8.69 | 23.00 | 1 |
| Grass | 4 | 0.91 | 0.89 | 10.46 | 27.43 | 13.50 | 23.88 | 3 |
| Shrub | 1 | 0.73 | 0.922 | 9.75 | 16.03 | 3.43 | 15.66 | 1 |
| Shrub | 2 | 0.68 | 0.768 | 28.67 | 17.79 | 9.96 | 14.74 | 2 |
| Shrub | 3 | 0.56 | 0.513 | 23.03 | 23.04 | 19.30 | 12.57 | 4 |
| Shrub | 4 | 0.76 | 0.819 | 22.40 | 14.30 | 7.44 | 12.21 | 3 |

Assessment at the other study sites (Table 3) was worse than expected. Grassland model 1 has
RMSE 42.6 % and a high tendency to overestimate; shrubland model 1 has R² = 0.63. Because models 2
were not much worse than models 1 at Cabañeros, they were also tested on this validation sample:
grassland and shrubland **models 2 perform better** at these extra sites (higher determination
coefficients, lower tendency to overestimate for the grassland model).

> **Operational conclusion of the paper:** the MODIS-derived models that include the Julian-day
> function — **model 2 for both grassland and shrubland** — are the ones chosen.

**Table 3.** Validation of the Grassland (G) and Shrubland (S) models at other sites.

| Veg. | Model | R² | Slope | Const. | RMSE (pct) | RMSEs (pct) | RMSEu (pct) | Best (rank) |
|---|---|---|---|---|---|---|---|---|
| G | 1 | 0.88 | 0.78 | 36.39 | 42.60 | 27.56 | 32.48 | 2 |
| G | 2 | 0.90 | 0.85 | 18.17 | 36.08 | 16.50 | 32.09 | 1 |
| S | 1 | 0.63 | 0.90 | −8.26 | 27.98 | 18.10 | 21.34 | 2 |
| S | 2 | 0.85 | 0.90 | −0.40 | 10.47 | 11.71 | 15.71 | 1 |

### 3.2 Dead fuel moisture estimation

Comparative analysis of observed vs. estimated FMC from the FFMC and from the 10-h code showed **no
significant differences**. The **10-h code was selected** for the remaining phases, since it requires
fewer meteorological variables (temperature and relative humidity only). To make estimation
operational, a joint equation for both fuel models (cured grass and litter) was assessed, giving:

```
FMC = 10h × 1.0317 + 2.1608
```

The 30 % validation sample did not differ from the rest of the sample.

Figure 2 shows the fit between observed and predicted FMC for the validation data using the 10 h
code. The adjustment is stronger for cured grass, with no outstanding deviations. For litter, a
deviation between observed and estimated FMC appeared in some rainy periods; the remaining periods
show a generalised tendency to **overestimate** the water content of this fuel type.

**Figure 2** *(scatter plot, axes FMC_est vs FMC, both 0–35)*: observed and predicted dead FMC for
the validation data. Fitted lines as printed:

| Series (legend marker) | Fit | R² |
|---|---|---|
| Litter (●) | `y = 1.9967x − 5.3698` | 0.5713 |
| Cured grass (□) | `y = 1.2839x − 3.0466` | 0.4418 |

> ⚠️ **Consistency note.** The series-to-equation assignment above follows the marker glyphs printed
> next to each equation, but it contradicts the body text, which states the adjustment is stronger
> for cured grass (the cured-grass fit here has the lower R²). The legend glyph for cured grass is
> also degraded in the PDF. Treat the assignment as uncertain.

### 3.3 Conversion of FMC to ignition probability (Madrid case study)

Estimated 14:00 GMT temperature and relative humidity at 2 m for the Madrid region were obtained
with the two-step method described above. That method is currently operative for high-quality,
high-resolution forecasts of forest-fire related meteorological variables in many Spanish regions
and was provided by **Meteológica S.A.**

Moisture of extinction and available fuel load per grid cell were obtained from a fuel type map
provided by the Regional Environmental Office; dead-fuel ME values were derived from the BEHAVE fuel
models (Burgan and Rothermel 1984).

**Figure 3** *(maps, not transcribed)*: IP_live (a), IP_dead (b) and IP_f (c) computed for
12 August 2006 in Madrid. Legend classes: `< 0.2`, `0.2–0.4`, `0.4–0.6`, `0.6–0.8`, `> 0.8`,
`No Data`.

**IP_live**

- Low values (mainly 0–0.4) from the north to the south-west border of the region, coinciding with
  the mountain areas: "Sierra Norte", "Cuenca alta del Manzanares", "Cuenca del Guadarrama",
  "Sierra Oeste". There LFMC is high and close to the maximum values in the historical field series
  (**340 % for grass, 210 % for shrubland**) and to the ME value (105 %). Reason: shrubland-dominated
  vegetation at higher altitudes is not water-stressed (rainfall above 800 mm).
- Some elevated values (0.6–0.8) coincide with **mid-elevation grassland**, which stays green longer
  than southern grassland but still drops below 40 % (grassland ME) mid-summer, due to high
  temperatures and lower precipitation in that season.
- Empty pixels occur in woodland areas, since that cover type was not treated in this paper.
- Values 0.6–1 occur in the central and south-east part of the region where mountains give way to
  the Tajo Valley plain (sands, loams and clays; moors and large areas of cultivated land). The
  central area has more no-data because it coincides with the metropolitan area.
- Middle IP_live values dotted with high values and no-data pixels occur in the south-east fertile
  plain, dominated by crops and gallery communities.

**IP_dead** — less variability. **No values below 0.4 anywhere** in the study region, due to high
temperatures and low relative humidity producing the lowest DFMC values. A slight tendency toward
higher values from north-west to south-east follows the altitudinal gradient.

**IP_f** — the combination shows higher heterogeneity than either component, although middle values
(0.4–0.6) dominate the region.

---

## 4. Conclusions

- The paper presents a simple procedure to integrate FMC information into fire danger assessment
  systems, focused on ignition danger rating.
- Since fire ignition results from several variables (causal agents and fuel water status), a common
  danger scale is required. Each danger variable is transformed into an **ignition potential (IP)**,
  the likelihood of a starting fire, in the range 0–1.
- IP_f is computed from the **moisture of extinction (ME)** concept, which expresses a physical
  threshold for flammability. The FMC → IP function is **linear**, since Mediterranean species show
  a continuous increase in flammability as FMC decreases.
- Because FMC can be mapped from gridded meteorological data or satellite imagery, IP_f can be
  mapped, making ignition danger assessment spatially explicit.
- The information integrates easily with other danger sources (lightning, socio-economic causes)
  within a GIS, and can be overlaid with available dispatch resources or potential fire effects on
  human and natural resources, improving the selection of fire prevention activities.

---

## 5. References

- Bradshaw, L., J. Deeming, and others (1983). *The 1978 National Fire-Danger Rating System: Technical Documentation.* Ogden, Utah: USDA Forest Service: 44.
- Burgan, R. E., R. W. Klaver, and others (1998). Fuel models and fire potential from satellite and surface observations. *International Journal of Wildland Fire* 8(3): 159–170.
- Burgan, R. E. and R. C. Rothermel (1984). *BEHAVE: Fire Behavior Prediction and Fuel Modeling System. Fuel Subsystem.* Ogden, Utah: USDA Forest Service.
- Ceccato, P., N. Gobron, and others (2002). Designing a spectral index to estimate vegetation water content from remote sensing data: Part 1 Theoretical approach. *Remote Sensing of Environment* 82: 188–197.
- Chuvieco, E., I. Aguado, and others (2004). Conversion of fuel moisture content values to ignition potential for integrated fire danger assessment. *Canadian Journal of Forest Research* 34(11): 2284–2293.
- Chuvieco, E., B. Allgöwer, and others (2003). Integration of physical and human factors in fire danger assessment. In: *Wildland Fire Danger Estimation and Mapping. The Role of Remote Sensing Data* (E. Chuvieco, ed.). Singapore: World Scientific Publishing. Series in Remote Sensing, vol. 4: 197–218.
- Chuvieco, E., D. Cocero, and others (2004). Combining NDVI and Surface Temperature for the estimation of live fuel moisture content in forest fire danger rating. *Remote Sensing of Environment* 92: 322–331.
- Dimitrakopoulos, A. and K. K. Papaioannou (2001). Flammability assessment of Mediterranean forest fuels. *Fire Technology* 37: 143–152.
- Gitelson, A., J. Y. Kaufman, and others (2002). Novel algorithms for remote estimation of vegetation fraction. *Remote Sensing of Environment* 80: 76–87.
- Hunt, E. R. and B. N. Rock (1989). Detection of changes in leaf water content using near and middle-infrared reflectances. *Remote Sensing of Environment* 30: 43–54.
- Jacquemoud, S. (1990). PROSPECT: a model to leaf optical properties spectra. *Remote Sensing of Environment* 34: 74–91.
- Knyazikhin, Y., J. Glassy, and others (1999). *MODIS Leaf Area Index (LAI) and Fraction of Photosynthetically Active Radiation Absorbed by Vegetation (FPAR) Product (MOD15). Algorithm Theoretical Basis Document.* http://eospso.gsfc.nasa.gov/atbd/modistables.html
- Kuusk, A. (1985). The hot spot effect of a uniform vegetative cover. *Soviet Journal of Remote Sensing* 3: 645–658.
- Lee, B. S., M. E. Alexander, and others (2002). Information systems in support of wildland fire management decision making in Canada. *Computers and Electronics in Agriculture* 37: 185–198.
- Rothermel, R. C. (1972). *A Mathematical Model for Predicting Fire Spread in Wildland Fuels.* Ogden, Utah: USDA Forest Service.
- Rouse, J. W., R. W. Haas, and others (1974). *Monitoring the vernal advancement and retrogradation (Greenwave effect) of natural vegetation.* Greenbelt, MD: NASA/GSFC.
- Van Wagner, C. E. (1987). *Development and structure of the Canadian Forest Fire Weather Index System.* Ottawa: Canadian Forest Service: 48.
- Verhoef, W. (1984). Light scattering by leaf layers with application to canopy reflectance modeling: the SAIL model. *Remote Sensing of Environment* 16: 125–141.
- Vermote, E. F. and A. Vermeulen (1999). *Atmospheric correction algorithm: Spectral Reflectances (MOD09).* NASA: 109 pp.
- Viegas, D. X. (1998). Fuel moisture evaluation for fire behaviour assessment. *Advanced Study Course on Wildfire Management*, Final Report, Marathon.
- Yebra, M., E. Chuvieco, and others (2006). Estimation of live Fuel Moisture Content from MODIS images for fire risk assessment. *Agricultural and Forest Meteorology* (submitted).

---

## Appendix A — Quick reference for implementation

**Recommended operational LFMC models (paper's own choice, MODIS + Julian-day term):**

```
FMC_grass = -129.12 + 503.51 * NDVI + 52.55 * FD_G
FMC_shrub =  104.38 + 427.57 * VARI - 163.67 * GVMI + 88.44 * FD_S   # see OCR note
```

**Best-at-calibration-site alternatives (no seasonal term):**

```
FMC_grass = -161.1 + 650.2 * NDVI
FMC_shrub =  229.1 + 887.2 * VARI - 300.7 * GVMI
```

**Dead fuel:**

```
DFMC = 1.0317 * FMC_10h + 2.1608
```

**Constants:**

| Constant | Grass | Shrub |
|---|---|---|
| ME (live) | 40 % | 105 % |
| FMC_max (Cabañeros 1996–2005 series) | 340 % | 210 % |
| ME (dead, BEHAVE 1 / 2 / 9) | 12 % / 15 % | — (litter 25 %) |

**Index definitions referenced (not given in the paper — from the cited sources):**

- NDVI = (NIR − RED) / (NIR + RED)
- NDII = (NIR − SWIR) / (NIR + SWIR)
- VARI = (GREEN − RED) / (GREEN + RED − BLUE)
- GVMI = ((NIR + 0.1) − (SWIR + 0.02)) / ((NIR + 0.1) + (SWIR + 0.02))
