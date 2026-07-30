"""
Wind Adjustment Factor (WAF) and midflame wind speed.

Reference implementation of the models documented in:
    Andrews, P.L. 2012. Modeling wind adjustment factor and midflame wind speed
    for Rothermel's surface fire spread model. RMRS-GTR-266. USDA Forest Service.
    (public domain)

Underlying models: Albini & Baughman (1979), Baughman & Albini (1980),
with implementation assumptions from Finney (1998, FARSITE).

All internal calculations are in FEET (the equations' native units).
Metric helpers are provided at the bottom.

Run `python waf.py` to execute the validation suite from the report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

FT_PER_M = 1.0 / 0.3048
MPH_PER_KMH = 1.0 / 1.609344

# 10-m to 20-ft wind conversion (Turner & Lawson 1978), used by BehavePlus.
U10M_TO_U20FT = 1.0 / 1.15


class Mode(str, Enum):
    """Which application's WAF implementation to reproduce."""

    BEHAVEPLUS = "behaveplus"   # sheltered if crown fill f >= 5%; f = (CC/3)*CR
    FARSITE = "farsite"         # sheltered if CC > 0; f = (CC/100)*(pi/12), CR ignored
    FUELCALC = "fuelcalc"       # min(sheltered, unsheltered); f = (CC/3)*CR
    SCOTT2007 = "scott2007"     # sheltered binned by CC (CR = 1), unsheltered by depth


# --------------------------------------------------------------------------
# Core equations
# --------------------------------------------------------------------------

def _log_term(h_ft: float) -> float:
    """ln((20 + 0.36H) / (0.13H)) -- shared denominator of eq [5]-[12].

    NOTE: H is the fuel bed depth for the unsheltered model but the CANOPY
    HEIGHT for the sheltered model. Passing the wrong one is the most common
    implementation error.
    """
    if h_ft <= 0:
        raise ValueError("height must be > 0")
    return math.log((20.0 + 0.36 * h_ft) / (0.13 * h_ft))


def waf_unsheltered(fuel_bed_depth_ft: float, flame_extent_ratio: float = 1.0) -> float:
    """Unsheltered WAF, eq [6]; eq [8] when flame_extent_ratio == 1.

    flame_extent_ratio = H_F / H, where H_F is the flame extent ABOVE the fuel
    bed (not flame height from the ground). H_F = H (ratio 1.0) is the
    assumption used by BehavePlus, FARSITE, FlamMap, FSPro, FPA, FuelCalc and
    Scott (2007): wind averaged from the top of the fuel bed to twice the depth.
    """
    h = fuel_bed_depth_ft
    r = flame_extent_ratio
    if r <= 0:
        raise ValueError("flame_extent_ratio must be > 0")
    if abs(r - 1.0) < 1e-12:
        return 1.83 / _log_term(h)  # eq [8], simplified
    return ((1.0 + 0.36 * h / (r * h)) / _log_term(h)) * (
        math.log((r + 0.36) / 0.13) - 1.0
    )  # eq [6]


def waf_at_height(fuel_bed_depth_ft: float, height_above_ground_ft: float) -> float:
    """WAF for a POINT height above ground from the log profile, eq [4].

    This is NOT the model's midflame wind (which is an average over a height
    range). Use it to compare a 2 m / eye-level anemometer reading against the
    model definition -- see section 6 of the reference. Differences are large.
    """
    h = fuel_bed_depth_ft
    z = height_above_ground_ft
    if z <= h:
        raise ValueError("height must be above the top of the fuel bed")
    return math.log((z - 0.64 * h) / (0.13 * h)) / _log_term(h)


def crown_fill_portion(
    canopy_cover: float, crown_ratio: float = 1.0, mode: Mode = Mode.BEHAVEPLUS
) -> float:
    """Crown fill portion f -- fraction of volume under canopy top filled by crowns.

    canopy_cover: FRACTION (0-1).
    BehavePlus/FuelCalc, eq [9]/[10]: F = CC/3 (conical crown), f = F * CR.
    FARSITE:                          f = CC * (pi/12) = (CC/3) * (pi/4), CR ignored.
    """
    if not 0.0 <= canopy_cover <= 1.0:
        raise ValueError("canopy_cover must be a fraction 0-1")
    if mode is Mode.FARSITE:
        return canopy_cover * math.pi / 12.0
    return (canopy_cover / 3.0) * crown_ratio


def waf_sheltered(crown_fill: float, canopy_height_ft: float) -> float:
    """Sheltered WAF, eq [12]/[2]. Independent of fuel model.

    The 0.555 constant is correct; Finney (1998, rev. 2004) printed 0.3066 in
    error (the FARSITE code itself was always right).
    """
    if crown_fill <= 0:
        raise ValueError("crown_fill must be > 0")
    return 0.555 / (math.sqrt(crown_fill * canopy_height_ft) * _log_term(canopy_height_ft))


def waf_sheltered_scott2007(canopy_cover_pct: float) -> float | None:
    """Scott (2007) binned sheltered WAF. Returns None if CC <= 5% (use unsheltered)."""
    cc = canopy_cover_pct
    if cc <= 5:
        return None
    if cc <= 10:
        return 0.30
    if cc <= 15:
        return 0.25
    if cc <= 30:
        return 0.20
    if cc <= 50:
        return 0.15
    return 0.10


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------

@dataclass
class WafResult:
    waf: float
    sheltered: bool
    crown_fill: float
    waf_unsheltered: float
    waf_sheltered: float | None
    mode: Mode
    warning: str | None = None

    def midflame_wind(self, u20: float) -> float:
        """Midflame wind for a 20-ft wind speed (same units in, same units out)."""
        return self.waf * u20


def compute_waf(
    fuel_bed_depth_ft: float,
    canopy_cover: float = 0.0,
    canopy_height_ft: float = 0.0,
    crown_ratio: float = 1.0,
    mode: Mode = Mode.BEHAVEPLUS,
) -> WafResult:
    """Full WAF calculation including the sheltered/unsheltered decision.

    canopy_cover: FRACTION (0-1). Set to 0 for no overstory.

    The sheltering criterion differs by application and is the largest source
    of divergence between systems:
        BEHAVEPLUS  sheltered when crown fill f >= 5%
        FARSITE     sheltered whenever CC > 0  (see warning below)
        FUELCALC    always takes min(sheltered, unsheltered) -- no step change
        SCOTT2007   sheltered when CC > 5%, from the binned table
    """
    unsh = waf_unsheltered(fuel_bed_depth_ft)
    warning = None

    if canopy_cover <= 0.0 or canopy_height_ft <= 0.0:
        return WafResult(unsh, False, 0.0, unsh, None, mode)

    if mode is Mode.SCOTT2007:
        sh = waf_sheltered_scott2007(canopy_cover * 100.0)
        f = crown_fill_portion(canopy_cover, 1.0, Mode.BEHAVEPLUS)
        if sh is None:
            return WafResult(unsh, False, f, unsh, None, mode)
        return WafResult(sh, True, f, unsh, sh, mode)

    f = crown_fill_portion(canopy_cover, crown_ratio, mode)
    sh = waf_sheltered(f, canopy_height_ft)

    if sh > unsh:
        warning = (
            f"sheltered WAF ({sh:.3f}) exceeds unsheltered ({unsh:.3f}) -- "
            "physically inconsistent, typical of very low canopy cover in FARSITE"
        )

    if mode is Mode.FUELCALC:
        use_sheltered = sh < unsh
    elif mode is Mode.FARSITE:
        use_sheltered = True  # CC > 0 already established
    else:  # BEHAVEPLUS
        use_sheltered = f >= 0.05

    return WafResult(sh if use_sheltered else unsh, use_sheltered, f, unsh, sh, mode, warning)


# --------------------------------------------------------------------------
# Metric / convenience wrappers
# --------------------------------------------------------------------------

def compute_waf_metric(
    fuel_bed_depth_m: float,
    canopy_cover: float = 0.0,
    canopy_height_m: float = 0.0,
    crown_ratio: float = 1.0,
    mode: Mode = Mode.BEHAVEPLUS,
) -> WafResult:
    """Same as compute_waf() with heights in metres. WAF itself is dimensionless."""
    return compute_waf(
        fuel_bed_depth_m * FT_PER_M,
        canopy_cover,
        canopy_height_m * FT_PER_M,
        crown_ratio,
        mode,
    )


def u10m_to_u20ft(u10m: float) -> float:
    """Convert 10-m wind to 20-ft wind (divide by 1.15). Any speed unit."""
    return u10m * U10M_TO_U20FT


def midflame_from_10m(u10m: float, waf: float) -> float:
    """10-m wind -> 20-ft wind -> midflame wind."""
    return u10m_to_u20ft(u10m) * waf


# --------------------------------------------------------------------------
# Validation suite -- every check is a documented value from RMRS-GTR-266
# --------------------------------------------------------------------------

def _run_checks() -> int:
    checks: list[tuple[str, float, float, float]] = []  # label, got, want, tol

    def add(label, got, want, tol=5e-3):
        checks.append((label, got, want, tol))

    # eq [8] unsheltered, table 8 / table 9 / figure 18
    for depth, want in [(1.0, 0.362), (0.2, 0.275), (2.5, 0.440), (6.0, 0.547),
                        (2.3, 0.431), (3.0, 0.459), (2.0, 0.418), (1.5, 0.393)]:
        # NOTE H=3.0: report table 9 prints 0.469 for FM13; eq [8] gives 0.4587.
        # Figure 18 and Scott (2007) both show 0.46, so 0.469 is a report typo.
        add(f"eq[8] unsheltered H={depth}", waf_unsheltered(depth), want, 1e-3)

    # Baughman & Albini used H_F/H = 2.5 for FM 8 and 9 -> 0.36
    add("eq[6] FM8/9 with H_F/H=2.5", waf_unsheltered(0.2, 2.5), 0.36, 5e-3)

    # Table 4 -- point heights, GS2, H = 1.5 ft
    for z, want in [(3.0, 0.50), (4.0, 0.59), (5.5, 0.68), (6.56, 0.72)]:
        add(f"eq[4] point height z={z} ft", waf_at_height(1.5, z), want, 5e-3)

    # Figure 20 -- FM2 (H=1), CC 40%, CH 50 ft, BehavePlus
    for cr, want_f, want_waf, want_sh in [
        (0.1, 0.013, 0.362, False), (0.3, 0.040, 0.362, False),
        (0.5, 0.067, 0.17, True), (0.7, 0.093, 0.15, True), (0.9, 0.120, 0.13, True),
    ]:
        r = compute_waf(1.0, 0.40, 50.0, cr, Mode.BEHAVEPLUS)
        add(f"fig20 f CR={cr}", r.crown_fill, want_f, 1e-3)
        add(f"fig20 WAF CR={cr}", round(r.waf, 2), want_waf, 5e-3)
        assert r.sheltered is want_sh, f"fig20 shelter flag CR={cr}"

    # Figure 23 -- CH 50 ft, CR 0.3 and 1.0
    for cc, w03, w10 in [(0.60, 0.18, 0.10), (0.80, 0.16, 0.09), (1.00, 0.14, 0.08)]:
        add(f"fig23 CC={cc} CR=0.3", round(compute_waf(1.0, cc, 50.0, 0.3).waf, 2), w03)
        add(f"fig23 CC={cc} CR=1.0", round(compute_waf(1.0, cc, 50.0, 1.0).waf, 2), w10)

    # Figure 5 -- FM2, CH 50, CR 0.7
    for cc, want in [(0.20, 0.36), (0.40, 0.15), (0.80, 0.10)]:
        add(f"fig5 CC={cc}", round(compute_waf(1.0, cc, 50.0, 0.7).waf, 2), want)

    # FARSITE: CC 1%, CH 100 ft -> 0.74, and flagged as inconsistent
    rf = compute_waf(1.0, 0.01, 100.0, 1.0, Mode.FARSITE)
    add("FARSITE CC=1% CH=100", round(rf.waf, 2), 0.74)
    assert rf.warning is not None, "FARSITE low-CC warning not raised"

    # FARSITE / BehavePlus ratio at CR = 1 -> sqrt(4/pi) ~ 1.128
    rb = compute_waf(1.0, 0.50, 100.0, 1.0, Mode.BEHAVEPLUS)
    rf2 = compute_waf(1.0, 0.50, 100.0, 1.0, Mode.FARSITE)
    add("FARSITE/BehavePlus ratio", rf2.waf / rb.waf, math.sqrt(4 / math.pi), 1e-6)

    # FuelCalc never exceeds unsheltered (table 11 behaviour)
    for cc in [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60]:
        r = compute_waf(1.5, cc, 100.0, 0.5, Mode.FUELCALC)
        assert r.waf <= r.waf_unsheltered + 1e-12, f"FuelCalc exceeded unsheltered at CC={cc}"

    # Table 4 midflame wind, U20 = 15 mi/h
    add("table4 midflame wind", compute_waf(1.5).midflame_wind(15.0), 5.9, 0.05)

    # Metric round-trip
    add("metric equivalence", compute_waf_metric(1.5 * 0.3048).waf, waf_unsheltered(1.5), 1e-9)

    failures = 0
    for label, got, want, tol in checks:
        ok = abs(got - want) <= tol
        if not ok:
            failures += 1
        print(f"{'PASS' if ok else 'FAIL'}  {label:38s} got={got:.4f} want={want:.4f}")
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_checks() else 0)
