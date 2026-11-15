"""Multi-sensor historical fusion (added in PyroSync 1.5).

Goal
----
One consistent daily activity indicator for an AOI from November 2000 to the present, built from every eligible
satellite (MODIS Terra and Aqua, VIIRS S-NPP, NOAA-20 and NOAA-21) WITHOUT adding raw detections from different sensors.

Method (Preprocess -> Align -> Calibrate -> Fuse -> Validate)
-------------------------------------------------------------
* Preprocess: the app's own filters (quality, type, day/night, AOI) and its per-sensor daily totals (`query.daily`).
  Original observations are never changed.
* Align: UTC days on the AOI. A platform's day is "known" only when the series has a known coverage state that day
  (detections or an imported request interval), the day lies inside the platform's own record (Aqua starts 2002-07-04,
  S-NPP 2012-01-20, NOAA-20 2018-04-01, NOAA-21 2023-03-01 in the imported archive) and the platform is not missing from
  the whole import that day (a likely data gap). Unknown days are never read as zero.
* Calibrate: reference scale = MODIS Aqua detections per day ("MODIS-Aqua-equivalent detections"). Every other platform
  p gets a day-level ratio c_p = Σ Aqua / Σ p over its training days with both known (`aggregate.py`, 1.4), with the
  1.4 chronological split and the unchanged 1.4 aggregate gate. Only platforms whose pairwise gate passes are eligible.
* Fuse: F_d = mean over eligible platforms known on day d of c_p · X_p,d (c_Aqua = 1). A calibrated AVERAGE, so a new
  satellite adds an estimate of the same quantity instead of adding detections: the level does not rise because another
  sensor starts. The contributing platforms are recorded for every day.
* Validate (`pyrosync-fusion-gate-1.0`): leave-reference-out. The fused estimate WITHOUT Aqua, with coefficients fitted
  only before the evaluation period, is compared with the observed Aqua totals: chronological hold-out, rolling-origin
  years, monthly and seasonal consistency, high-fire days, sensor-transition steps, regional cells and missing data.
  Thresholds are the 1.4 ones and are fixed here before any run.

MODIS Aqua is a reference observational scale, not ground truth. Agreement between sensors is not an independent
accuracy assessment of fire detection.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np

from . import aggregate as AG
from . import cache
from . import normalize as N
from . import query as Q
from .db import cursor, get_revision

FUSION_VERSION = "pyrosync-fusion-1.0"
GATE_VERSION = "pyrosync-fusion-gate-1.0"
REFERENCE = "Aqua"
PLATFORMS = ["Terra", "Aqua", "SNPP", "N20", "N21"]
COMPONENTS = ["Terra", "SNPP", "N20", "N21"]
LEVEL = AG.LEVEL
HARD = AG.HARD
MIN_HELD_OUT_DAYS = AG.MIN_HELD_OUT_DAYS
MIN_TRAIN_DAYS = AG.MIN_TRAIN_DAYS
MIN_YEAR_DAYS = AG.MIN_YEAR_DAYS
MIN_ROLL_YEARS = AG.MIN_ROLL_YEARS
STABLE_SHARE = AG.STABLE_SHARE
HIGH_PCT = AG.HIGH_PCT
MIN_HIGH_DAYS = AG.MIN_HIGH_DAYS
MIN_MONTH_DAYS = AG.MIN_MONTH_DAYS
TEST_FRACTION = 0.2
TRANSITION_DAYS = 365
MIN_TRANSITION_DAYS = 60
GAP_MIN_MEDIAN_ROWS = 20
NATIONAL_AOI = "region:indonesia"
SERIES_KEY = "FUSED"
LABEL = "Harmonized activity (MODIS-Aqua-equivalent detections/day)"
SHORT = "Harmonized (all sensors)"
UNIT = "MODIS-Aqua-equivalent detections per day"

REFERENCE_DOC = ("Reference scale: MODIS Aqua active-fire detections per UTC day in the AOI. Aqua is the longest single-platform MODIS record "
                 "with an afternoon overpass, the one the 1.4 day-level ratio was validated against. It is a reference observational scale, "
                 "not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target. "
                 "Aqua's overpass has drifted later since it left the A-Train in 2022; the year-by-year checks show whether that changes the ratios.")
COVERAGE_NOTE = ("Satellite observation coverage (swath, cloud, smoke) is not verified. A day is 'known' when the sensor's record and an "
                 "imported request interval cover it; a known day with no detection is a reported zero, not proof of a clear-sky observation.")


# ------------------------------------------------------------------ availability
def platform_records() -> dict[str, tuple[date, date]]:
    """First and last imported day of each platform (all rows, independent of filters)."""
    out: dict[str, tuple[date, date]] = {}
    for p in Q.inventory()["products"]:
        a, b = date.fromisoformat(p["first_date"]), date.fromisoformat(p["last_date"])
        if p["platform"] in out:
            a, b = min(a, out[p["platform"]][0]), max(b, out[p["platform"]][1])
        out[p["platform"]] = (a, b)
    return out


def platform_gap_days() -> dict[str, set[date]]:
    """Days inside a platform's record on which it has no row anywhere in the import although its typical day has many
    (median ≥ 20 rows over the record). Treated as unknown for that platform (likely acquisition/processing gap)."""
    rev = get_revision()

    def compute():
        with cursor() as cur:
            rows = cur.execute("SELECT platform, acq_date, count(*) FROM observations WHERE NOT superseded GROUP BY ALL").fetchall()
        per: dict[str, dict[date, int]] = {}
        for p, d, n in rows:
            per.setdefault(p, {})[d] = n
        out: dict[str, set[date]] = {}
        for p, counts in per.items():
            a, b = min(counts), max(counts)
            nd = (b - a).days + 1
            vals = sorted(list(counts.values()) + [0] * (nd - len(counts)))
            if vals[len(vals) // 2] < GAP_MIN_MEDIAN_ROWS:
                continue
            out[p] = {a + timedelta(days=i) for i in range(nd) if (a + timedelta(days=i)) not in counts}
        return out
    return cache.get_or_compute(cache.make_key("fusion_gaps", rev, {}), compute)


def _record_filters(f: Q.Filters) -> Q.Filters:
    """The AOI and quality filters over the whole imported record and all five platforms. The model does not depend on the
    display range, so changing the range never changes the coefficients."""
    rng = Q.inventory()["date_range"]
    if not rng:
        raise ValueError("no data imported")
    return f.model_copy(update={"start": date.fromisoformat(rng[0]), "end": date.fromisoformat(rng[1]),
                                "platforms": [p for p in Q.ALL_PLATFORMS]})


def model_key(f: Q.Filters) -> dict:
    k = f.key()
    for x in ("start", "end", "platforms", "grid"):
        k.pop(x, None)
    return k


def daily_platform_arrays(f: Q.Filters) -> dict:
    """Per-platform daily detection totals and known masks over the whole record for these filters and AOI."""
    rf = _record_filters(f)
    rev = get_revision()

    def compute():
        d = Q.daily_counts(rf)
        nd = len(d["dates"])
        dates = [rf.start + timedelta(days=i) for i in range(nd)]
        recs = platform_records()
        gaps = platform_gap_days()
        X: dict[str, np.ndarray] = {}
        K: dict[str, np.ndarray] = {}
        for p in PLATFORMS:
            ser = N.PLATFORM_SERIES[p]
            sts = d["status"].get(ser)
            if sts is None or p not in recs:
                X[p] = np.zeros(nd)
                K[p] = np.zeros(nd, bool)
                continue
            X[p] = np.array(d["platforms"][p], dtype=float)
            a, b = recs[p]
            g = gaps.get(p, set())
            K[p] = np.array([st in ("detections", "zero_reported") and a <= dd <= b and dd not in g
                             for st, dd in zip(sts, dates)])
            X[p][~K[p]] = 0.0
        return {"dates": dates, "X": X, "K": K, "filters": rf}
    return cache.get_or_compute(cache.make_key("fusion_arrays", rev, model_key(f)), compute)


# ------------------------------------------------------------------ pairwise calibration (1.4 rules, unchanged)
def _pair(arr: dict, p: str) -> dict:
    X, K, dates = arr["X"], arr["K"], arr["dates"]
    nd = len(dates)
    pa = {"dates": dates, "M": X[REFERENCE], "V": X[p], "Mc": np.zeros(nd), "Vc": np.zeros(nd),
          "known_m": K[REFERENCE], "known_v": K[p], "known": K[REFERENCE] & K[p]}
    split, rule = AG._split_day(SimpleNamespace(split_date=None, test_fraction=TEST_FRACTION), pa)
    ev = AG._evaluate(pa, "detections", split, None)
    ev["split_rule"] = rule
    ev["overlap_days"] = int(pa["known"].sum())
    ev["platform"] = p
    ev["platform_label"] = N.PLATFORM_LABEL[p]
    ev["eligible"] = ev.get("gate", {}).get("status") == "passes"
    # keep the response small: the year table and the gate are what the UI needs
    return ev


def _fit(M, V, mask) -> float | None:
    if mask.sum() < MIN_TRAIN_DAYS:
        return None
    return AG.fit_ratio(M, V, mask)


# ------------------------------------------------------------------ fused series
def fuse(arr: dict, coefs: dict[str, float], use_reference: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """F_d = mean over available calibrated platforms. Returns (values with NaN where no platform is known, n platforms)."""
    nd = len(arr["dates"])
    tot = np.zeros(nd)
    n = np.zeros(nd, int)
    plats = ([REFERENCE] if use_reference else []) + [p for p in coefs if p != REFERENCE]
    for p in plats:
        cp = 1.0 if p == REFERENCE else coefs[p]
        k = arr["K"][p]
        tot[k] += cp * arr["X"][p][k]
        n[k] += 1
    out = np.full(nd, np.nan)
    ok = n > 0
    out[ok] = tot[ok] / n[ok]
    return out, n


def _metrics(pred, obs) -> dict:
    return AG._metrics(np.asarray(pred, float), np.asarray(obs, float))


# ------------------------------------------------------------------ validation of the fused product
def _validate(arr: dict, eligible: list[str], pairs: dict) -> dict:
    dates = arr["dates"]
    X, K = arr["X"], arr["K"]
    A = X[REFERENCE]
    KA = K[REFERENCE]
    nd = len(dates)
    di = np.arange(nd)
    out: dict = {"reference": REFERENCE, "eligible_components": eligible,
                 "design": "Leave-reference-out: the fused estimate WITHOUT Aqua, with each ratio fitted only on days before the evaluation "
                           "period, is compared with the observed Aqua totals. Aqua is never an input to its own prediction."}
    if not eligible:
        out["status"] = "insufficient"
        out["reason"] = f"No platform passes its pairwise calibration gate against {REFERENCE}, so there is nothing to fuse and validate."
        out["gate"] = gate(out)
        return out
    # common chronological split over the reference record
    act = [dates[i] for i in range(nd) if KA[i] and (A[i] > 0 or any(K[p][i] and X[p][i] > 0 for p in eligible))]
    if len(act) < 10:
        out["status"] = "insufficient"
        out["reason"] = "Too few days with activity and a known Aqua state."
        out["gate"] = gate(out)
        return out
    from . import harmonize as H
    split = H.chronological_split(act, TEST_FRACTION, None)
    s = (split - dates[0]).days
    out["split"] = split.isoformat()
    out["split_rule"] = f"chronological hold-out: the last {TEST_FRACTION:.0%} of days with activity and a known Aqua state"
    train = di < s
    coefs_tr: dict[str, float] = {}
    out["train_coefficients"] = {}
    for p in eligible:
        c = _fit(A, X[p], KA & K[p] & train)
        out["train_coefficients"][p] = c
        if c is not None:
            coefs_tr[p] = c
    if not coefs_tr:
        out["status"] = "insufficient"
        out["reason"] = (f"No eligible platform has {MIN_TRAIN_DAYS} known overlap days with Aqua before the split ({split}), so the "
                         "fused estimate cannot be tested on later data.")
        out["gate"] = gate(out)
        return out
    F_lro, n_lro = fuse(arr, coefs_tr, use_reference=False)
    have = ~np.isnan(F_lro)
    te = KA & have & (di >= s)
    tr = KA & (di < s)
    out["held_out_days"] = int(te.sum())
    out["train_days"] = int(tr.sum())
    out["held_out_period"] = [dates[int(np.nonzero(te)[0][0])].isoformat(), dates[int(np.nonzero(te)[0][-1])].isoformat()] if te.any() else None
    if te.sum() == 0 or tr.sum() < MIN_TRAIN_DAYS:
        out["status"] = "insufficient"
        out["reason"] = f"Needs ≥ {MIN_TRAIN_DAYS} known Aqua training days and held-out days with a fused estimate; got {int(tr.sum())} and {int(te.sum())}."
        out["gate"] = gate(out)
        return out
    out["status"] = "ok"
    obs = A[te]
    const = float(A[tr].mean())
    raw_tot = np.zeros(nd)
    raw_n = np.zeros(nd, int)
    for p in coefs_tr:
        raw_tot[K[p]] += X[p][K[p]]
        raw_n[K[p]] += 1
    raw_mean = np.where(raw_n > 0, raw_tot / np.maximum(raw_n, 1), np.nan)
    methods = {"fusion_leave_reference_out": F_lro[te], "raw_unadjusted_mean": raw_mean[te],
               "constant_train_mean": np.full(int(te.sum()), const)}
    out["held_out"] = {k: _metrics(v, obs) for k, v in methods.items()}
    out["held_out"]["constant_train_mean"]["value"] = const
    # comparison with the 1.4 single-pair day-level ratio (S-NPP) and single-sensor ratios, on days where both exist
    comp = {}
    for p, c in coefs_tr.items():
        both = te & K[p]
        if both.sum() >= MIN_HELD_OUT_DAYS:
            comp[p] = {"days": int(both.sum()), "single_ratio": _metrics(c * X[p][both], A[both]), "fusion": _metrics(F_lro[both], A[both])}
    out["single_sensor_comparison"] = comp
    out["contributors_held_out"] = {p: int((te & K[p]).sum()) for p in coefs_tr}
    # high-fire days
    thr = float(np.percentile(A[tr], HIGH_PCT))
    hi = obs >= thr
    out["activity"] = {"threshold": thr, "rule": f"High-fire days: held-out days with Aqua total ≥ the training {HIGH_PCT}th percentile.",
                       "high": {k: _metrics(v[hi], obs[hi]) for k, v in methods.items()},
                       "low": {k: _metrics(v[~hi], obs[~hi]) for k, v in methods.items()}}
    # monthly consistency (held-out months with ≥ 20 evaluated days)
    groups: dict[tuple[int, int], list[int]] = {}
    for i in np.nonzero(te)[0]:
        groups.setdefault((dates[i].year, dates[i].month), []).append(int(i))
    full = {k: g for k, g in groups.items() if len(g) >= MIN_MONTH_DAYS}
    mrat = []
    for (y, m), g in sorted(full.items()):
        so = float(A[g].sum())
        mrat.append({"month": f"{y:04d}-{m:02d}", "days": len(g), "aqua": so, "fusion": float(F_lro[g].sum()),
                     "ratio": float(F_lro[g].sum() / so) if so > 0 else None})
    rr = [x["ratio"] for x in mrat if x["ratio"] is not None]
    out["monthly"] = {"months": mrat, "min_days": MIN_MONTH_DAYS,
                      "share_within_level": float(np.mean([LEVEL[0] <= r <= LEVEL[1] for r in rr])) if rr else None,
                      "totals": _metrics(np.array([x["fusion"] for x in mrat]), np.array([x["aqua"] for x in mrat])) if mrat else None}
    # rolling origin by calendar year (expanding window), out-of-sample prediction for every year
    roll = []
    oos = np.full(nd, np.nan)
    for y in range(dates[0].year + 1, dates[-1].year + 1):
        a_ = max(0, (date(y, 1, 1) - dates[0]).days)
        b_ = min((date(y + 1, 1, 1) - dates[0]).days, nd)
        before = di < a_
        cy = {}
        for p in eligible:
            c = _fit(A, X[p], KA & K[p] & before)
            if c is not None:
                cy[p] = c
        if not cy:
            continue
        Fy, ny = fuse(arr, cy, use_reference=False)
        yr = (di >= a_) & (di < b_)
        tst = yr & KA & ~np.isnan(Fy)
        if KA[before].sum() < MIN_TRAIN_DAYS or tst.sum() < MIN_YEAR_DAYS:
            continue
        oos[tst] = Fy[tst]
        m = _metrics(Fy[tst], A[tst])
        roll.append({"year": y, "coefficients": cy, "contributors": sorted({p for p in cy if (tst & K[p]).any()}, key=PLATFORMS.index),
                     "test_days": int(tst.sum()), "ratio": m["ratio"], "mae": m["mae"], "rmse": m["rmse"], "mbe": m["mbe"],
                     "sum_aqua": m["sum_obs"], "sum_estimate": m["sum_pred"],
                     "constant_mae": _metrics(np.full(int(tst.sum()), float(A[KA & before].mean())), A[tst])["mae"],
                     "within_level": m["ratio"] is not None and LEVEL[0] <= m["ratio"] <= LEVEL[1]})
    out["rolling_origin"] = {"years": roll, "rule": "Year Y is predicted without Aqua, from the other platforms with ratios fitted on all known "
                             f"days before 1 January Y; a year needs ≥ {MIN_TRAIN_DAYS} earlier Aqua days and ≥ {MIN_YEAR_DAYS} test days."}
    # seasonal consistency: out-of-sample (rolling-origin) predictions by calendar month over all years
    seas = []
    ok = ~np.isnan(oos)
    for m in range(1, 13):
        sel = ok & np.array([d.month == m for d in dates])
        so = float(A[sel].sum())
        seas.append({"month": m, "days": int(sel.sum()), "aqua": so, "fusion": float(oos[sel].sum()),
                     "ratio": float(oos[sel].sum() / so) if so > 0 else None})
    sr = [x["ratio"] for x in seas if x["ratio"] is not None and x["days"] >= MIN_MONTH_DAYS]
    out["seasonal"] = {"months": seas, "share_within_level": float(np.mean([LEVEL[0] <= r <= LEVEL[1] for r in sr])) if sr else None,
                       "rule": "Rolling-origin (out-of-sample) estimates summed by calendar month over every predicted year."}
    # sensor transitions: level of the fused estimate (without Aqua) relative to Aqua, the year before and after a platform joins
    trans = []
    coefs_prod = {p: pairs[p]["c"] for p in eligible}
    F_all_lro, _ = fuse(arr, coefs_prod, use_reference=False)
    F_all, _ = fuse(arr, coefs_prod, use_reference=True)
    for p in eligible:
        kidx = np.nonzero(K[p])[0]
        if not len(kidx):
            continue
        t0 = int(kidx[0])
        rec = {"platform": p, "joins": dates[t0].isoformat()}
        for name, F in (("leave_reference_out", F_all_lro), ("fused", F_all)):
            bsel = (di >= t0 - TRANSITION_DAYS) & (di < t0) & KA & ~np.isnan(F)
            asel = (di >= t0) & (di < t0 + TRANSITION_DAYS) & KA & ~np.isnan(F)
            if bsel.sum() < MIN_TRANSITION_DAYS or asel.sum() < MIN_TRANSITION_DAYS or A[bsel].sum() <= 0 or A[asel].sum() <= 0:
                rec[name] = None
                continue
            rb = float(F[bsel].sum() / A[bsel].sum())
            ra = float(F[asel].sum() / A[asel].sum())
            rec[name] = {"before": rb, "after": ra, "step": ra / rb if rb > 0 else None, "days_before": int(bsel.sum()), "days_after": int(asel.sum())}
        trans.append(rec)
    out["transitions"] = {"platforms": trans, "rule": f"Σ estimate / Σ Aqua over up to {TRANSITION_DAYS} known days before and after a platform's first "
                          f"known day (≥ {MIN_TRANSITION_DAYS} days each side). 'step' = after / before; a step of 1 means no jump. "
                          "Uses the production ratios, so it checks discontinuity, not accuracy."}
    # missing data
    any_known = np.zeros(nd, bool)
    for p in [REFERENCE] + eligible:
        any_known |= K[p]
    out["missing"] = {"days": nd, "no_known_platform": int((~any_known).sum()), "aqua_unknown": int((~KA).sum()),
                      "per_platform_known": {p: int(K[p].sum()) for p in PLATFORMS}}
    out["gate"] = gate(out)
    return out


def gate(ev: dict) -> dict:
    checks = []

    def add(cid, label, passed, value, rule):
        checks.append({"id": cid, "label": label, "passed": bool(passed), "value": value, "rule": rule})

    lo, hi = LEVEL
    if ev.get("status") != "ok":
        add("fitted", "Fusion can be tested", False, ev.get("reason", "not fitted"),
            f"At least one eligible platform with {MIN_TRAIN_DAYS} known overlap days before the split, and held-out days.")
        return {"version": GATE_VERSION, "status": "insufficient", "checks": checks, "label": "Insufficient validation data"}
    h = ev["held_out"]
    fu, raw, con = h["fusion_leave_reference_out"], h["raw_unadjusted_mean"], h["constant_train_mean"]
    add("days", "Enough held-out days", ev["held_out_days"] >= MIN_HELD_OUT_DAYS, f"{ev['held_out_days']:,} days",
        f"At least {MIN_HELD_OUT_DAYS} held-out days with a known Aqua state and a fused estimate.")
    add("level", "Total level close to Aqua", fu["ratio"] is not None and lo <= fu["ratio"] <= hi,
        "—" if fu["ratio"] is None else f"Σ fused / Σ Aqua = {fu['ratio']:.2f}", f"Held-out total between {lo:g}× and {hi:g}× the Aqua total.")
    add("beats_unadjusted", "Better than averaging raw counts", fu["mae"] < raw["mae"] and fu["rmse"] < raw["rmse"],
        f"MAE {fu['mae']:.1f} vs {raw['mae']:.1f}; RMSE {fu['rmse']:.1f} vs {raw['rmse']:.1f}",
        "Held-out daily MAE and RMSE below the uncalibrated mean of the same platforms' raw counts.")
    add("beats_constant", "Better than a constant", fu["mae"] < con["mae"] and fu["rmse"] < con["rmse"],
        f"MAE {fu['mae']:.1f} vs {con['mae']:.1f}; RMSE {fu['rmse']:.1f} vs {con['rmse']:.1f}",
        "Held-out daily MAE and RMSE below a constant equal to the training-period mean daily Aqua total.")
    yrs = [y for y in ev["rolling_origin"]["years"] if y["ratio"] is not None]
    share = (sum(1 for y in yrs if y["within_level"]) / len(yrs)) if yrs else 0.0
    worst = max(yrs, key=lambda y: abs(math.log(y["ratio"])) if y["ratio"] > 0 else math.inf) if yrs else None
    add("roll_years", "Enough rolling-origin years", len(yrs) >= MIN_ROLL_YEARS, f"{len(yrs)} years",
        f"At least {MIN_ROLL_YEARS} calendar years predicted from earlier years only.")
    add("roll_share", "Most years close to Aqua", share >= STABLE_SHARE,
        f"{sum(1 for y in yrs if y['within_level'])} of {len(yrs)} years within {lo:g}–{hi:g}×",
        f"At least {STABLE_SHARE:.0%} of rolling-origin years within {lo:g}–{hi:g}×.")
    add("roll_hard", "No year far off", bool(yrs) and all(HARD[0] <= y["ratio"] <= HARD[1] for y in yrs),
        "—" if worst is None else f"worst year {worst['year']}: {worst['ratio']:.2f}×", f"No rolling-origin year outside {HARD[0]:g}–{HARD[1]:g}×.")
    hd = ev["activity"]["high"]["fusion_leave_reference_out"]
    add("high_activity", "High-fire days close to Aqua", hd["n"] >= MIN_HIGH_DAYS and hd["ratio"] is not None and lo <= hd["ratio"] <= hi,
        f"{hd['n']} days" + ("" if hd["ratio"] is None else f", {hd['ratio']:.2f}×"),
        f"At least {MIN_HIGH_DAYS} held-out days at or above the training {HIGH_PCT}th percentile, total within {lo:g}–{hi:g}×.")
    steps = [(t["platform"], t["leave_reference_out"]["step"]) for t in ev["transitions"]["platforms"]
             if t.get("leave_reference_out") and t["leave_reference_out"]["step"] is not None]
    bad = [f"{p} {s_:.2f}×" for p, s_ in steps if not (lo <= s_ <= hi)]
    add("transitions", "No jump when a satellite joins", not bad,
        ("no testable transition" if not steps else ", ".join(f"{p} {s_:.2f}×" for p, s_ in steps)),
        f"For every platform joining the record, the before/after level step of the fused estimate (without Aqua) is within {lo:g}–{hi:g}×. "
        "A platform without a full year on both sides is not testable and does not fail the check.")
    passed = all(ch["passed"] for ch in checks)
    return {"version": GATE_VERSION, "status": "passes" if passed else "not_validated", "checks": checks,
            "label": "Passes the project's fusion validation rules (leave-reference-out, chronological and year-by-year)" if passed
            else "Experimental: the fused series does not pass the project's validation rules for this area",
            "note": "\"Passes\" means the documented PyroSync rules on held-out (later) data with Aqua as the reference scale; it is not an official "
                    "or NASA validation, and agreement between sensors is not an independent accuracy assessment."}


# ------------------------------------------------------------------ model (per AOI + filters, whole record)
def model(f: Q.Filters) -> dict:
    rev = get_revision()
    return cache.get_or_compute(cache.make_key("fusion_model", rev, model_key(f)), lambda: _model(f))


def _national_eligibility(f: Q.Filters) -> list[str] | None:
    """Platform eligibility is a property of the instrument pair, decided on the longest, largest record: the Indonesia-wide
    fit with the same filters. Smaller areas reuse it (their own pairwise tests have too few active days), but fit their own
    ratios and are validated on their own data. None for the national AOI itself, 'none', or when Indonesia is unavailable."""
    if f.aoi in ("none", NATIONAL_AOI):
        return None
    try:
        nat = model(f.model_copy(update={"aoi": NATIONAL_AOI}))
    except Exception:  # noqa: BLE001 - e.g. a test fixture without the Indonesia region
        return None
    return list(nat["eligible"]) if nat["reference_available"] else None


def _model(f: Q.Filters) -> dict:
    nat_elig = _national_eligibility(f)
    arr = daily_platform_arrays(f)
    recs = platform_records()
    pairs = {}
    for p in COMPONENTS:
        if not arr["K"][p].any() or not arr["K"][REFERENCE].any():
            pairs[p] = {"platform": p, "platform_label": N.PLATFORM_LABEL[p], "status": "insufficient", "c": None, "eligible": False,
                        "reason": "No known days of this platform or of Aqua for these filters.",
                        "gate": {"status": "insufficient", "checks": [], "label": "Not available"}}
            continue
        pairs[p] = _pair(arr, p)
    if nat_elig is None:
        eligible = [p for p in COMPONENTS if pairs[p].get("eligible")]
        elig_rule = "platforms whose pairwise day-level ratio against Aqua passes the 1.4 aggregate gate for this area"
    else:
        eligible = [p for p in COMPONENTS if p in nat_elig and pairs[p].get("c") is not None]
        elig_rule = ("platforms that pass the pairwise 1.4 gate against Aqua Indonesia-wide (instrument-level eligibility), with a ratio "
                     f"fitted on this area's own training days (≥ {MIN_TRAIN_DAYS} known overlap days)")
    for p in COMPONENTS:
        pairs[p]["used"] = p in eligible
    val = _validate(arr, eligible, pairs)
    coefs = {p: pairs[p]["c"] for p in eligible}
    dates = arr["dates"]
    any_ref = arr["K"][REFERENCE].any()
    return {"method_version": FUSION_VERSION, "gate_version": GATE_VERSION, "dataset_revision": get_revision(),
            "aoi": f.aoi, "effective_filters": {k: v for k, v in arr["filters"].key().items() if k not in ("grid",)},
            "record": [dates[0].isoformat(), dates[-1].isoformat()],
            "platform_records": {p: [a.isoformat(), b.isoformat()] for p, (a, b) in recs.items()},
            "reference": REFERENCE, "reference_available": bool(any_ref), "reference_doc": REFERENCE_DOC,
            "equation": "F_d = mean over eligible platforms p known on day d of c_p · X_p,d;  c_Aqua = 1,  c_p = Σ_train Aqua / Σ_train p "
                        "(1.4 day-level ratio, pairwise chronological split)",
            "coefficients": coefs, "eligible": eligible, "eligibility_rule": elig_rule, "national_eligibility": nat_elig,
            "pairs": {p: _compact_pair(pairs[p]) for p in COMPONENTS},
            "validation": val, "gate": val["gate"], "coverage": {"status": "not_verified", "note": COVERAGE_NOTE}}


def _compact_pair(ev: dict) -> dict:
    keep = ("platform", "platform_label", "status", "reason", "c", "bootstrap", "split", "split_rule", "train_days", "held_out_days",
            "train_period", "held_out_period", "overlap_days", "eligible", "used", "gate")
    out = {k: ev.get(k) for k in keep}
    h = ev.get("held_out")
    if h:
        out["held_out"] = {"day_ratio": h["day_ratio"], "raw": h["raw_viirs"], "constant": h["constant_train_mean"]}
    ro = ev.get("rolling_origin")
    if ro:
        out["rolling_years"] = [{k: y[k] for k in ("year", "c", "ratio", "within_level", "test_days")} for y in ro["years"]]
    return out


def effective(f: Q.Filters) -> dict:
    """The coefficients actually applied for this AOI, with the validation status shown to users.

    * the AOI's own fusion passes -> its own coefficients, 'passes';
    * its own fusion was tested and fails -> its own coefficients, 'not_validated' (experimental);
    * its own fusion cannot be tested (small area, few active days) -> the Indonesia-wide coefficients, 'insufficient'
      ("Insufficient validation data"): shown for orientation, never presented as validated for the area.
    """
    m = model(f)
    st = m["gate"]["status"]
    src = {"aoi": f.aoi, "label": "this area's own fit"}
    use = m
    if st == "insufficient" and f.aoi not in ("none", NATIONAL_AOI):
        try:
            nat = model(f.model_copy(update={"aoi": NATIONAL_AOI}))
        except Exception:  # noqa: BLE001 - region missing in a test fixture
            nat = None
        if nat is not None and nat["coefficients"]:
            use = nat
            src = {"aoi": NATIONAL_AOI, "label": "Indonesia-wide fit (not validated for this area)"}
    status = st
    label = {"passes": "Validated for this area's daily totals (project rules)",
             "not_validated": "Experimental: fails the project's validation rules for this area",
             "insufficient": "Insufficient validation data"}[st]
    return {"coefficients": use["coefficients"], "eligible": use["eligible"], "source": src, "status": status, "status_label": label,
            "local_gate": m["gate"], "national_gate": use["gate"] if use is not m else None}


# ------------------------------------------------------------------ outputs
def _fused_for(f: Q.Filters):
    arr = daily_platform_arrays(f)
    eff = effective(f)
    F, n = fuse(arr, eff["coefficients"], use_reference=True)
    return arr, eff, F, n


def series(f: Q.Filters, agg: str = "day") -> dict:
    if agg not in ("day", "month", "year"):
        raise ValueError("agg must be 'day', 'month' or 'year'")
    rev = get_revision()
    return cache.get_or_compute(cache.make_key("fusion_series", rev, {**f.key(), "agg": agg}), lambda: _series(f, agg))


def _series(f: Q.Filters, agg: str) -> dict:
    arr, eff, F, n = _fused_for(f)
    dates = arr["dates"]
    i0 = (f.start - dates[0]).days
    i1 = (f.end - dates[0]).days
    nd_all = len(dates)
    rng = [i for i in range(max(0, i0), min(nd_all - 1, i1) + 1)]
    plats = [REFERENCE] + list(eff["coefficients"])
    coefs = {REFERENCE: 1.0, **eff["coefficients"]}
    KA, A = arr["K"][REFERENCE], arr["X"][REFERENCE]

    def contrib(i):
        return [p for p in plats if arr["K"][p][i]]

    if agg == "day":
        rows = {"dates": [dates[i].isoformat() for i in rng],
                "fused": [None if np.isnan(F[i]) else round(float(F[i]), 3) for i in rng],
                "aqua_observed": [float(A[i]) if KA[i] else None for i in rng],
                "n_platforms": [int(n[i]) for i in rng],
                "contributors": [contrib(i) for i in rng],
                "calibrated": {p: [round(coefs[p] * float(arr["X"][p][i]), 3) if arr["K"][p][i] else None for i in rng] for p in plats},
                "observed": {p: [float(arr["X"][p][i]) if arr["K"][p][i] else None for i in rng] for p in PLATFORMS}}
    else:
        groups: dict[str, list[int]] = {}
        for i in rng:
            k = f"{dates[i].year:04d}-{dates[i].month:02d}" if agg == "month" else f"{dates[i].year:04d}"
            groups.setdefault(k, []).append(i)
        rows = {"dates": [], "fused": [], "aqua_observed": [], "known_days": [], "reference_days": [], "days": [], "contributors": [],
                "mean_platforms": []}
        for k, ix in groups.items():
            ok = [i for i in ix if not np.isnan(F[i])]
            ka = [i for i in ix if KA[i]]
            rows["dates"].append(k)
            rows["days"].append(len(ix))
            rows["known_days"].append(len(ok))
            rows["reference_days"].append(len(ka))
            rows["fused"].append(round(float(F[ok].sum()), 2) if ok else None)
            rows["aqua_observed"].append(float(A[ka].sum()) if ka else None)
            rows["contributors"].append(sorted({p for i in ok for p in contrib(i)}, key=PLATFORMS.index))
            rows["mean_platforms"].append(round(float(n[ok].mean()), 2) if ok else None)
    return {"agg": agg, "method_version": FUSION_VERSION, "label": LABEL, "unit": UNIT, "reference": REFERENCE,
            "coefficients": eff["coefficients"], "eligible": eff["eligible"], "coefficient_source": eff["source"],
            "validation_status": eff["status"], "validation_label": eff["status_label"], "gate": eff["local_gate"],
            "range": [f.start.isoformat(), f.end.isoformat()], **rows,
            "notes": ["Fused = mean of the calibrated estimates of every eligible platform known that day (Aqua itself counts with c = 1). "
                      "Raw detections from different satellites are never added.",
                      "Days with no known platform are empty, never zero. Monthly and yearly sums use only days with a fused value ('known_days').",
                      "Before 2002-07-04 only Terra can contribute (if eligible); before 2012-01-20 only MODIS.",
                      "Experimental unless the validation status says it passes. MODIS Aqua is a reference scale, not ground truth."]}


def daily_like(f: Q.Filters) -> dict:
    """The fused series in the shape of `query.daily` (series 'FUSED', metric 'detections' only), for calendar, elevated
    periods and Insights. Status: 'detections' (> 0), 'zero_reported' (0 with ≥ 1 known platform), 'unknown' (no known
    platform), 'outside_range'."""
    rev = get_revision()
    return cache.get_or_compute(cache.make_key("fusion_dailylike", rev, f.key()), lambda: _daily_like(f))


def _daily_like(f: Q.Filters) -> dict:
    arr, eff, F, n = _fused_for(f)
    dates0 = arr["dates"]
    nd = (f.end - f.start).days + 1
    dates = [f.start + timedelta(days=i) for i in range(nd)]
    vals: list = []
    sts: list = []
    npl: list = []
    for d in dates:
        i = (d - dates0[0]).days
        if i < 0 or i >= len(dates0):
            vals.append(None); sts.append("outside_range"); npl.append(0)
            continue
        if np.isnan(F[i]):
            vals.append(None); sts.append("unknown"); npl.append(0)
            continue
        v = round(float(F[i]), 3)
        vals.append(v); sts.append("detections" if v > 0 else "zero_reported"); npl.append(int(n[i]))
    ser = {"detections": vals, "status": sts, "status_origin": [None] * nd, "n_platforms": npl}
    for k in ("cells", "frp_sum", "frp_mean", "frp_max", "frp_median", "day", "night", "unfiltered", "frp_n"):
        ser[k] = [None] * nd
    return {"dates": [d.isoformat() for d in dates], "series": {SERIES_KEY: ser},
            "series_labels": {SERIES_KEY: LABEL}, "validation_status": eff["status"], "validation_label": eff["status_label"],
            "coefficient_source": eff["source"]}


def frame_cells(f: Q.Filters, day: date, mode: int, grid: float, bbox=None, limit: int = 30000) -> dict:
    key = cache.make_key("fusion_frame", get_revision(), {**f.key(), "day": day, "mode": mode, "g": grid, "bbox": bbox, "limit": limit})
    return cache.get_or_compute(key, lambda: _frame_cells(f, day, mode, grid, bbox, limit))


def _frame_cells(f: Q.Filters, day: date, mode: int, grid: float, bbox, limit: int) -> dict:
    """Harmonized activity per display-grid cell for a map window: Σ over days of Σ_p (c_p / n_d) · X_p,cell,d.
    The day weights are those of the AOI's fused daily total, so the cells of a day sum to that day's fused value."""
    a, b = Q.frame_window(day, mode)
    arr, eff, F, n = _fused_for(f)
    dates0 = arr["dates"]
    coefs = {REFERENCE: 1.0, **eff["coefficients"]}
    weights: dict[tuple[date, str], float] = {}
    days_known = 0
    for k in range((b - a).days + 1):
        d = a + timedelta(days=k)
        i = (d - dates0[0]).days
        if i < 0 or i >= len(dates0) or n[i] == 0:
            continue
        days_known += 1
        for p, c in coefs.items():
            if arr["K"][p][i]:
                weights[(d, p)] = c / n[i]
    ff = f.model_copy(update={"platforms": list(Q.ALL_PLATFORMS), "grid": grid})
    ew, ep = Q._bbox_where(bbox)
    sql, params = Q.filtered_sql(ff, a, b, extra_where=ew, extra_params=ep)
    ci, cj, _ = Q.cell_sql(grid)
    with cursor() as cur:
        rows = cur.execute(f"SELECT {ci}, {cj}, acq_date, platform, count(*) FROM ({sql}) o GROUP BY ALL", params).fetchall()
    cells: dict[tuple[int, int], dict] = {}
    for x, y, d, p, cnt in rows:
        c = cells.setdefault((x, y), {"ci": x, "cj": y, "value": 0.0, "observed": {}})
        c["observed"][p] = c["observed"].get(p, 0) + cnt
        c["value"] += cnt * weights.get((d, p), 0.0)
    out = [c | {"value": round(c["value"], 4)} for c in cells.values() if c["value"] > 0]
    out.sort(key=lambda c: (-c["value"], c["ci"], c["cj"]))
    total = len(out)
    out = out[:limit]
    i_a, i_b = (a - dates0[0]).days, (b - dates0[0]).days
    win = [i for i in range(max(0, i_a), min(len(dates0) - 1, i_b) + 1)]
    fused_total = float(np.nansum(F[win])) if win else 0.0
    contributing = sorted({p for (_d, p) in weights}, key=PLATFORMS.index)
    validated_cells = False
    return {"method_version": FUSION_VERSION, "frame": {"date": day.isoformat(), "mode_days": mode, "start": a.isoformat(), "end": b.isoformat()},
            "grid_size": grid, "cells": out, "cells_total": total, "truncated": total > len(out), "viewport": bbox,
            "fused_total": round(fused_total, 3), "days_known": days_known, "days": (b - a).days + 1,
            "contributors": contributing, "coefficients": eff["coefficients"], "coefficient_source": eff["source"],
            "reference": REFERENCE, "unit": f"{UNIT} summed over the window, per {grid}° cell",
            "validation_status": eff["status"], "validation_label": eff["status_label"], "cells_validated": validated_cells,
            "label": "Experimental Harmonized Activity Index",
            "notes": ["Each cell = Σ over the window's days of the calibrated, platform-averaged detections in the cell (the same weights as the "
                      "AOI's fused daily total, so the cells add up to it). Raw detections of different satellites are never added.",
                      "The fusion is validated, at most, for AOI daily totals. Individual cells are not validated at any grid size, so the layer is "
                      "labelled experimental. Cells are not burned area or fire boundaries."]}


def regional(f: Q.Filters, grid_deg: float = 1.0, min_days: int = 20) -> dict:
    rev = get_revision()
    return cache.get_or_compute(cache.make_key("fusion_regional", rev, {**model_key(f), "g": grid_deg, "m": min_days}),
                                lambda: _regional(f, grid_deg, min_days))


def _regional(f: Q.Filters, grid_deg: float, min_days: int) -> dict:
    """Held-out regional check: per grid_deg region cell, Σ fused-without-Aqua / Σ Aqua over the held-out days, with the
    training-period ratios of the AOI."""
    m = model(f)
    val = m["validation"]
    if val.get("status") != "ok":
        return {"available": False, "reason": val.get("reason"), "cells": [], "grid_deg": grid_deg}
    arr = daily_platform_arrays(f)
    dates0 = arr["dates"]
    split = date.fromisoformat(val["split"])
    coefs = {p: c for p, c in val["train_coefficients"].items() if c is not None}
    rf = _record_filters(f)
    r = int(round(grid_deg * 100000))
    sql, params = Q.filtered_sql(rf, split, rf.end)
    with cursor() as cur:
        rows = cur.execute(f"""SELECT (o.lon_e5::BIGINT + 18000000) // {r}, (o.lat_e5::BIGINT + 9000000) // {r}, acq_date, platform, count(*)
                               FROM ({sql}) o GROUP BY ALL""", params).fetchall()
    out: dict[tuple[int, int], dict] = {}
    KA = arr["K"][REFERENCE]
    nl = np.zeros(len(dates0), int)
    for p in coefs:
        nl += arr["K"][p].astype(int)
    for x, y, d, p, cnt in rows:
        i = (d - dates0[0]).days
        if i < 0 or i >= len(dates0) or not KA[i] or nl[i] == 0:
            continue
        c = out.setdefault((x, y), {"ci": int(x), "cj": int(y), "aqua": 0.0, "fusion": 0.0, "_days": set()})
        if p == REFERENCE:
            c["aqua"] += cnt
            c["_days"].add(i)
        elif p in coefs and arr["K"][p][i]:
            c["fusion"] += cnt * coefs[p] / nl[i]
            c["_days"].add(i)
    cells = []
    for c in out.values():
        nd_ = len(c.pop("_days"))
        ratio = c["fusion"] / c["aqua"] if c["aqua"] > 0 else None
        st = "too_few" if nd_ < min_days else ("within" if ratio is not None and LEVEL[0] <= ratio <= LEVEL[1] else "outside")
        cells.append(c | {"ratio": ratio, "active_days": nd_, "status": st,
                          "west": -180 + c["ci"] * grid_deg, "south": -90 + c["cj"] * grid_deg})
    cells.sort(key=lambda c: (c["cj"], c["ci"]))
    tested = [c for c in cells if c["status"] != "too_few"]
    return {"available": True, "grid_deg": grid_deg, "min_days": min_days, "split": val["split"], "cells": cells,
            "summary": {"within": sum(1 for c in tested if c["status"] == "within"), "outside": sum(1 for c in tested if c["status"] == "outside"),
                        "too_few": len(cells) - len(tested),
                        "share_within": (sum(1 for c in tested if c["status"] == "within") / len(tested)) if tested else None},
            "definition": "Per region cell, over held-out days with a known Aqua state: Σ fused estimate without Aqua (training ratios of the AOI) / "
                          "Σ Aqua detections. The AOI-level result does not make every region accurate; this shows where it holds."}


class reference_override:
    """Sensitivity analysis only (CLI `harmonize-fusion`): run the same fusion with another reference platform (e.g. Terra).
    Not used by the API. Clears the cache on entry and exit so results of different references never mix."""

    def __init__(self, platform: str):
        if platform not in PLATFORMS:
            raise ValueError(f"unknown platform {platform}")
        self.platform = platform

    def __enter__(self):
        global REFERENCE, COMPONENTS
        self._saved = (REFERENCE, COMPONENTS)
        REFERENCE = self.platform
        COMPONENTS = [p for p in PLATFORMS if p != self.platform]
        cache.invalidate()
        return self

    def __exit__(self, *exc):
        global REFERENCE, COMPONENTS
        REFERENCE, COMPONENTS = self._saved
        cache.invalidate()
        return False


def report(f: Q.Filters) -> dict:
    """Model + effective coefficients for the API and exports."""
    m = model(f)
    return m | {"effective": effective(f)}


def report_markdown(rep: dict, title: str, reg: dict | None = None) -> str:
    def x(v, nd=2):
        return "—" if v is None else f"{v:,.{nd}f}"

    v = rep["validation"]
    L = [f"# {title}", "", f"Method `{rep['method_version']}`, gate `{rep['gate_version']}`, dataset revision {rep['dataset_revision']}.",
         f"AOI `{rep['aoi']}`; record {rep['record'][0]} → {rep['record'][1]}; filters {rep['effective_filters']}.", "",
         rep["reference_doc"], "", f"Equation: {rep['equation']}.", "", f"## Pairwise calibration against {rep['reference']} (1.4 rules, unchanged)", "",
         "| Platform | c (95 % bootstrap) | overlap days | held-out ratio | rolling years within 0.8–1.25× | pair gate | eligible |",
         "|---|---|---|---|---|---|---|"]
    for p, pr in rep["pairs"].items():
        b = pr.get("bootstrap") or {}
        yrs = pr.get("rolling_years") or []
        ry = f"{sum(1 for y in yrs if y['within_level'])} of {len(yrs)}" + (f" ({min(y['ratio'] for y in yrs if y['ratio']):.2f}–{max(y['ratio'] for y in yrs if y['ratio']):.2f})" if yrs else "")
        hr = (pr.get("held_out") or {}).get("day_ratio", {}).get("ratio")
        L.append(f"| {pr['platform_label']} | {x(pr.get('c'), 4)} ({x(b.get('c_lo'), 4)}–{x(b.get('c_hi'), 4)}) | {pr.get('overlap_days') or 0:,} | "
                 f"{x(hr)} | {ry} | {pr['gate']['status']} | {'yes' if pr.get('eligible') else 'no'} |")
    L += ["", "## Fused series validation (leave-reference-out)", "", v["design"], ""]
    if v.get("status") != "ok":
        L += [f"Not tested: {v.get('reason')}", ""]
    else:
        L += [f"Split {v['split']} ({v['split_rule']}); {v['train_days']:,} Aqua training days; {v['held_out_days']:,} held-out days "
              f"{v['held_out_period']}. Training ratios: " + ", ".join(f"{p} {x(c, 4)}" for p, c in v["train_coefficients"].items()) + ".", "",
              "| Held-out daily totals | Σ est / Σ Aqua | MAE | RMSE | MBE |", "|---|---|---|---|---|"]
        for k, mm in v["held_out"].items():
            L.append(f"| {k} | {x(mm['ratio'])} | {x(mm['mae'], 1)} | {x(mm['rmse'], 1)} | {x(mm['mbe'], 1)} |")
        if v["single_sensor_comparison"]:
            L += ["", "| Same held-out days, single sensor vs fusion | days | single-ratio Σ/Σ | single MAE | fusion Σ/Σ | fusion MAE |", "|---|---|---|---|---|---|"]
            for p, cmp_ in v["single_sensor_comparison"].items():
                L.append(f"| {p} | {cmp_['days']} | {x(cmp_['single_ratio']['ratio'])} | {x(cmp_['single_ratio']['mae'], 1)} | "
                         f"{x(cmp_['fusion']['ratio'])} | {x(cmp_['fusion']['mae'], 1)} |")
        hi = v["activity"]["high"]["fusion_leave_reference_out"]
        L += ["", f"High-fire days (Aqua ≥ {v['activity']['threshold']:.0f}): {hi['n']} days, {x(hi['ratio'])}×.",
              f"Monthly consistency: {len(v['monthly']['months'])} held-out months; share within 0.8–1.25×: "
              f"{'—' if v['monthly']['share_within_level'] is None else format(v['monthly']['share_within_level'], '.0%')}.",
              f"Seasonal consistency (rolling-origin, by calendar month): share within 0.8–1.25×: "
              f"{'—' if v['seasonal']['share_within_level'] is None else format(v['seasonal']['share_within_level'], '.0%')} "
              f"({', '.join(x(s_['ratio']) for s_ in v['seasonal']['months'])}).", "",
              "| Year | contributors (no Aqua) | test days | Σ est / Σ Aqua | MAE | constant MAE |", "|---|---|---|---|---|---|"]
        for y in v["rolling_origin"]["years"]:
            L.append(f"| {y['year']} | {', '.join(y['contributors'])} | {y['test_days']} | {x(y['ratio'])} | {x(y['mae'], 1)} | {x(y['constant_mae'], 1)} |")
        L += ["", "| Platform joins | step without Aqua (before → after) | step with Aqua |", "|---|---|---|"]
        for t in v["transitions"]["platforms"]:
            lro, fu = t.get("leave_reference_out"), t.get("fused")
            L.append(f"| {t['platform']} {t['joins']} | " + (f"{x(lro['step'])}× ({x(lro['before'])} → {x(lro['after'])})" if lro else "not testable")
                     + " | " + (f"{x(fu['step'])}×" if fu else "—") + " |")
        mi = v["missing"]
        L += ["", f"Missing data: {mi['no_known_platform']:,} of {mi['days']:,} record days have no known platform; Aqua unknown on {mi['aqua_unknown']:,} days.", ""]
    g = rep["gate"]
    L += [f"**Fusion gate: {g['status']}** — {g['label']}", ""] + [f"- {'✔' if ch['passed'] else '✘'} {ch['label']}: {ch['value']} ({ch['rule']})" for ch in g["checks"]]
    if reg and reg.get("available"):
        s_ = reg["summary"]
        L += ["", f"## Regional check ({reg['grid_deg']}° cells, ≥ {reg['min_days']} active held-out days)", "",
              f"{s_['within']} cells within 0.8–1.25×, {s_['outside']} outside, {s_['too_few']} with too few days"
              + ("" if s_["share_within"] is None else f" (share within: {s_['share_within']:.0%})") + ".", "", reg["definition"]]
    L += ["", f"Coverage: {COVERAGE_NOTE}", ""]
    return "\n".join(L)
