"""Diagnóstico da agregação multifuel para os modelos PT."""
import sys
sys.path.insert(0, "/home/claude/fogos_triage/src")
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

from fogos_triage.fuel_models import load_fuel_models_csv
from fogos_triage.engine import aggregate_multifuel

models = load_fuel_models_csv("/home/claude/fire_models_pt/data/fuel_models_pt.csv")

# Humidades típicas verão moderado
m1h, m10h, m100h = 0.10, 0.11, 0.12
mlh, mlw = 0.80, 1.00

print(f"{'Code':6s} {'σ_char':>8s} {'load':>6s} {'f_dead':>7s} {'f_live':>7s} "
      f"{'σ_dead':>8s} {'σ_live':>8s} {'M_x_live':>9s}")
print("-" * 70)

# Ordem útil para ler
ordered = [211, 212, 213, 214,
           221, 222, 223, 224, 225, 226, 227,
           231, 232, 233, 234, 235, 236, 237,
           98, 255]

for num in ordered:
    fm = models.get(num)
    if fm is None:
        continue
    agg = aggregate_multifuel(fm, m1h, m10h, m100h, mlh, mlw)
    if agg is None:
        print(f"{fm.code:6s}  -- não combustível --")
        continue

    print(f"{fm.code:6s} {agg['sav_char_ftinv']:8.0f} "
          f"{agg['load_total_lbft2']:6.3f} "
          f"{agg['f_dead']:7.2f} {agg['f_live']:7.2f} "
          f"{agg['sigma_dead_ftinv']:8.0f} {agg['sigma_live_ftinv']:8.0f} "
          f"{agg['M_x_live_r']:9.2f}")
