# RMRS-GTR-266 — Wind Adjustment Factor reference

Machine-readable transcription of Andrews (2012), *Modeling wind adjustment factor and
midflame wind speed for Rothermel's surface fire spread model* (USDA FS, public domain).

## Files
- `RMRS-GTR-266_WAF_reference.md` — full technical reference: equations, sheltering
  criteria per application, tables, limitations, validation checkpoints, errata.
- `waf.py` — reference implementation (BehavePlus / FARSITE / FuelCalc / Scott 2007
  modes). `python waf.py` runs 36 validation checks against values published in the
  report. All pass.
- `waf_fuel_models.csv` — 53 standard fuel models, depth + unsheltered WAF.
- `waf_tables_13fm_comparison.csv` — original 13 FM across 5 published sources.
- `waf_sheltered.csv` — sheltered/partially sheltered tables incl. Scott 2007 CC bins.
- `waf_nfdrs.csv` — 1978/1988 NFDRS and retired NFMAS WAF values.

## The three things that bite
1. `H` means **fuel bed depth** in the unsheltered equation and **canopy height** in the
   sheltered one. Same symbol, same `ln()` term, different quantity.
2. The **sheltered/unsheltered switch differs by application** (BehavePlus `f >= 5%`,
   FARSITE `CC > 0`, FuelCalc `min()`). This causes larger divergence between systems
   than the equations themselves.
3. "Midflame" wind is an **average over a height range**, not the wind at a height. A
   2 m or eye-level anemometer reading is not the model's midflame wind — for a 1.5 ft
   fuel bed it is ~1.8x higher and nearly doubles modelled ROS.

## Usage
```python
from waf import compute_waf, compute_waf_metric, Mode

r = compute_waf(fuel_bed_depth_ft=1.5, canopy_cover=0.40,
                canopy_height_ft=50.0, crown_ratio=0.5, mode=Mode.BEHAVEPLUS)
r.waf, r.sheltered, r.crown_fill, r.warning
r.midflame_wind(u20=15.0)          # mi/h in, mi/h out

compute_waf_metric(fuel_bed_depth_m=0.46, canopy_cover=0.40, canopy_height_m=15.0)
```
Units: equations are native in feet; WAF is dimensionless so wind speed units pass
through unchanged. 10 m -> 20 ft: divide by 1.15 (`u10m_to_u20ft`).
