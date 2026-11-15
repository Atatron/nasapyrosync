"""Day-level (aggregate) calibration of MODIS–VIIRS activity totals (added in PyroSync 1.4).

Why this module exists
----------------------
The event-level model of `harmonize.py` (ln(1 + M) = α + β ln(1 + V)) is fitted on comparison units that BOTH sensors
detected. Summed over matched events it leaves out every MODIS-only detection (run A: about 0.24× the MODIS total);
summed over all VIIRS events it assigns a MODIS count to VIIRS-only fires that MODIS mostly does not record (about
3.8×). An event model conditional on a match is therefore not a model of daily totals (METHODOLOGY §18).

This module calibrates at the level where the historical question is asked: the AOI total of one UTC day. The model is

    M̂_d = c · V_d,   c = Σ_train M_d / Σ_train V_d

over training days on which both sensors have a known coverage state. It is the least-squares-free ratio estimator of a
proportional relation; the day-level log-log slope is close to 1 on the Indonesian archive, so the proportional model is
the simplest one consistent with the data. The same rule is applied to occupied comparison cells per day
(cells with ≥ 1 detection of that sensor), a second quantity with its own coefficient and its own gate.

Everything is computed from the same events as the core of `calibration.py` (same filters, AOI, platforms, grid), so
the daily totals equal the app's per-sensor daily series. Original observations are never modified.

Validation (all of it chronological; nothing is tuned on held-out days)
----------------------------------------------------------------------
* single split: the unit-level split day of the run (or a chronological 80/20 split of active known days);
* rolling origin by calendar year: year Y is predicted with c fitted on every known day before 1 January Y;
* month-block bootstrap of c on the training days (resampling whole calendar months keeps within-month correlation);
* high-activity days: held-out days at or above the training 90th percentile of the MODIS total.

Gate (`pyrosync-aggregate-gate-1.0`): the existing daily-total rules of 1.2 (≥ 30 held-out days, total within
0.8–1.25× MODIS, MAE and RMSE below raw VIIRS and below a training constant) PLUS a stability rule: at least 3
rolling-origin years, at least 80 % of them within 0.8–1.25×, none outside 0.67–1.5×, and held-out high-activity days
(≥ 10) within 0.8–1.25×. Thresholds are fixed here, before any run.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from . import cache
from . import harmonize as H
from . import query as Q
from .db import get_revision

AGG_VERSION = "pyrosync-aggregate-1.0"
GATE_VERSION = "pyrosync-aggregate-gate-1.0"
QUANTITIES = ("detections", "cells")
LEVEL = (0.8, 1.25)
HARD = (0.67, 1.5)
MIN_HELD_OUT_DAYS = 30
MIN_TRAIN_DAYS = 180
MIN_YEAR_DAYS = 30
MIN_ROLL_YEARS = 3
STABLE_SHARE = 0.8
HIGH_PCT = 90
MIN_HIGH_DAYS = 10
BOOT_N = 500
BOOT_SEED = 20261115
MIN_MONTH_DAYS = 20
REGION_MIN_DAYS = (5, 10, 20, 30, 50)

QUANTITY_DOC = {
    "detections": "FIRMS detections per UTC day in the AOI, each sensor its own count (MODIS 1 km, VIIRS 375 m pixels).",
    "cells": "Occupied comparison cells per UTC day: grid cells of the run's comparison grid with at least one detection of that sensor.",
}
REFERENCE_DOC = ("MODIS is the reference scale for continuity with the long MODIS record. It is not ground truth: MODIS misses small fires "
                 "and fires under cloud or smoke, and its own errors stay in the target.")


# ------------------------------------------------------------------ daily arrays
def _filters(f, cfg):
    """The run's filters with the sensor pair's platforms and the comparison grid (cells are counted on that grid)."""
    return H._sensor_filters(f, cfg).model_copy(update={"grid": cfg.unit_grid})


def daily_arrays(f, cfg, c=None) -> dict:
    """Per-day totals of both sensors from the app's daily series (same filters, AOI, platforms and grid) and the
    known-coverage mask of both sensors. With a harmonization core `c`, the event sums are checked against them."""
    ff = _filters(f, cfg)
    daily = Q.daily(ff)
    vser = cfg.viirs_series
    nd = (f.end - f.start).days + 1

    def col(series, key):
        s = daily["series"].get(series)
        return np.array(s[key], dtype=float) if s else np.zeros(nd)

    def known(series):
        st = daily["series"].get(series, {}).get("status")
        return np.array([x in ("detections", "zero_reported") for x in st]) if st else np.zeros(nd, bool)

    M, V, Mc, Vc = col("MODIS", "detections"), col(vser, "detections"), col("MODIS", "cells"), col(vser, "cells")
    if c is not None:
        i0 = (f.start - date(1970, 1, 1)).days
        off = c.day - i0
        ok = (off >= 0) & (off < nd)
        for sens, arr, name in ((0, M, "MODIS"), (1, V, "VIIRS")):
            sel = ok & (c.sensor == sens)
            if not np.array_equal(np.bincount(off[sel], weights=c.n[sel].astype(float), minlength=nd), arr):
                raise RuntimeError(f"aggregate: {name} event sums differ from the daily series")
    km, kv = known("MODIS"), known(vser)
    dates = [f.start + timedelta(days=i) for i in range(nd)]
    return {"dates": dates, "M": M, "V": V, "Mc": Mc, "Vc": Vc, "known_m": km, "known_v": kv, "known": km & kv}


def _metrics(pred: np.ndarray, obs: np.ndarray) -> dict:
    e = pred - obs
    n = len(obs)
    if n == 0:
        return {"n": 0, "mae": None, "rmse": None, "mbe": None, "ratio": None, "sum_pred": 0.0, "sum_obs": 0.0}
    so = float(obs.sum())
    return {"n": n, "mae": float(np.mean(np.abs(e))), "rmse": float(math.sqrt(np.mean(e ** 2))), "mbe": float(np.mean(e)),
            "ratio": float(pred.sum() / so) if so > 0 else None, "sum_pred": float(pred.sum()), "sum_obs": so}


def fit_ratio(M: np.ndarray, V: np.ndarray, mask: np.ndarray) -> float | None:
    sv = float(V[mask].sum())
    return float(M[mask].sum()) / sv if sv > 0 else None


def bootstrap_ratio(M, V, mask, dates, n_boot: int = BOOT_N, seed: int = BOOT_SEED) -> dict | None:
    """Month-block bootstrap of c over the training days: resample whole calendar months with replacement."""
    idx = np.nonzero(mask)[0]
    if len(idx) == 0:
        return None
    months: dict[tuple[int, int], list[int]] = {}
    for i in idx:
        months.setdefault((dates[i].year, dates[i].month), []).append(int(i))
    sums = np.array([[M[ix].sum(), V[ix].sum()] for ix in months.values()])
    if len(sums) < 2 or sums[:, 1].sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sums), size=(n_boot, len(sums)))
    sm, sv = sums[draws, 0].sum(axis=1), sums[draws, 1].sum(axis=1)
    cs = sm[sv > 0] / sv[sv > 0]
    lo, hi = np.percentile(cs, [2.5, 97.5])
    return {"n_boot": n_boot, "seed": seed, "blocks": len(sums), "c_lo": float(lo), "c_hi": float(hi),
            "rule": "Month-block bootstrap: whole calendar months of training days resampled with replacement; 2.5th and 97.5th percentiles."}


def _split_day(cfg, arr) -> tuple[date | None, str]:
    """One split rule whether or not a unit-level run exists, so the Harmonization tab and the history pages agree."""
    if cfg.split_date is not None:
        return cfg.split_date, "configured split date"
    act = [d for i, d in enumerate(arr["dates"]) if arr["known"][i] and (arr["M"][i] > 0 or arr["V"][i] > 0)]
    if len(act) < 10:
        return None, "too few active days"
    return (H.chronological_split(act, cfg.test_fraction, None),
            f"chronological hold-out: the last {cfg.test_fraction:.0%} of days with activity and known coverage of both sensors")


# ------------------------------------------------------------------ evaluation of one quantity
def _evaluate(arr: dict, q: str, split: date | None, event_pred: dict | None) -> dict:
    dates, known = arr["dates"], arr["known"]
    M, V = (arr["M"], arr["V"]) if q == "detections" else (arr["Mc"], arr["Vc"])
    nd = len(dates)
    di = np.arange(nd)
    s = None if split is None else (split - dates[0]).days
    tr = known & (di < s) if s is not None else np.zeros(nd, bool)
    te = known & (di >= s) if s is not None else np.zeros(nd, bool)
    out: dict = {"quantity": q, "definition": QUANTITY_DOC[q], "split": split.isoformat() if split else None,
                 "train_days": int(tr.sum()), "held_out_days": int(te.sum()),
                 "train_period": [dates[int(np.nonzero(tr)[0][0])].isoformat(), dates[int(np.nonzero(tr)[0][-1])].isoformat()] if tr.any() else None,
                 "held_out_period": [dates[int(np.nonzero(te)[0][0])].isoformat(), dates[int(np.nonzero(te)[0][-1])].isoformat()] if te.any() else None,
                 "known_days": int(known.sum()), "days": nd,
                 "unknown_share": float(1 - known.sum() / nd) if nd else None}
    cval = fit_ratio(M, V, tr) if tr.sum() >= MIN_TRAIN_DAYS else None
    out["c"] = cval
    out["status"] = "ok" if cval is not None and te.sum() > 0 else "insufficient"
    if out["status"] != "ok":
        if tr.sum() >= MIN_TRAIN_DAYS and te.sum() > 0 and float(V[tr].sum()) <= 0:
            out["reason"] = "No VIIRS detections on the training days for these filters, so the ratio cannot be fitted."
        else:
            out["reason"] = (f"Needs at least {MIN_TRAIN_DAYS} training days with known coverage of both sensors and VIIRS activity, "
                             f"and held-out days; got {int(tr.sum())} training and {int(te.sum())} held-out days.")
        out["gate"] = gate(out)
        return out
    out["bootstrap"] = bootstrap_ratio(M, V, tr, dates)
    o = M[te]
    const = float(M[tr].mean())
    methods = {"raw_viirs": V[te], "constant_train_mean": np.full(int(te.sum()), const), "day_ratio": cval * V[te]}
    if q == "detections" and event_pred:
        for k, p in event_pred.items():
            methods[k] = p[te]
    out["held_out"] = {k: _metrics(p, o) for k, p in methods.items()}
    out["held_out"]["constant_train_mean"]["value"] = const
    out["training"] = {"day_ratio": _metrics(cval * V[tr], M[tr]), "raw_viirs": _metrics(V[tr], M[tr])}
    # day-level log-log slope on training days (diagnostic: a slope near 1 supports the proportional model)
    x, y = np.log1p(V[tr]), np.log1p(M[tr])
    if np.ptp(x) > 0:
        b, a = np.polyfit(x, y, 1)
        out["loglog_slope_diagnostic"] = {"alpha": float(a), "beta": float(b),
                                          "note": "OLS of ln(1 + M_d) on ln(1 + V_d) over training days; diagnostic only, not used for prediction."}
    # high / low activity
    thr = float(np.percentile(M[tr], HIGH_PCT))
    hi = o >= thr
    out["activity"] = {"threshold": thr, "rule": f"High-activity days: held-out days with MODIS total ≥ the training {HIGH_PCT}th percentile.",
                       "high": {k: _metrics(p[hi], o[hi]) for k, p in methods.items()},
                       "low": {k: _metrics(p[~hi], o[~hi]) for k, p in methods.items()}}
    # monthly totals over known held-out days
    groups: dict[tuple[int, int], list[int]] = {}
    for i in np.nonzero(te)[0]:
        groups.setdefault((dates[i].year, dates[i].month), []).append(int(i))
    full = {k: g for k, g in groups.items() if len(g) >= MIN_MONTH_DAYS}
    mo = np.array([M[g].sum() for g in full.values()])
    out["monthly"] = {"months": len(full), "min_known_days": MIN_MONTH_DAYS,
                      "raw_viirs": _metrics(np.array([V[g].sum() for g in full.values()]), mo),
                      "day_ratio": _metrics(np.array([cval * V[g].sum() for g in full.values()]), mo)}
    if len(full):
        r = np.array([cval * V[g].sum() / M[g].sum() if M[g].sum() > 0 else np.nan for g in full.values()])
        r = r[~np.isnan(r)]
        out["monthly"]["share_within_level"] = float(np.mean((r >= LEVEL[0]) & (r <= LEVEL[1]))) if len(r) else None
    # rolling origin by calendar year
    roll = []
    for y in range(dates[0].year + 1, dates[-1].year + 1):
        a_ = (date(y, 1, 1) - dates[0]).days
        b_ = min((date(y + 1, 1, 1) - dates[0]).days, nd)
        trn = known & (di < a_)
        tst = known & (di >= a_) & (di < b_)
        if trn.sum() < MIN_TRAIN_DAYS or tst.sum() < MIN_YEAR_DAYS:
            continue
        cy = fit_ratio(M, V, trn)
        if cy is None:
            continue
        m = _metrics(cy * V[tst], M[tst])
        roll.append({"year": y, "c": cy, "train_days": int(trn.sum()), "test_days": int(tst.sum()), "ratio": m["ratio"],
                     "mae": m["mae"], "rmse": m["rmse"], "mbe": m["mbe"], "sum_modis": m["sum_obs"], "sum_estimate": m["sum_pred"],
                     "raw_ratio": _metrics(V[tst], M[tst])["ratio"],
                     "constant_mae": _metrics(np.full(int(tst.sum()), float(M[trn].mean())), M[tst])["mae"],
                     "within_level": m["ratio"] is not None and LEVEL[0] <= m["ratio"] <= LEVEL[1]})
    out["rolling_origin"] = {"years": roll, "rule": "Year Y is predicted with c fitted on all known days before 1 January Y (expanding window); "
                             f"a year needs ≥ {MIN_TRAIN_DAYS} training days and ≥ {MIN_YEAR_DAYS} test days."}
    out["gate"] = gate(out)
    return out


def gate(ev: dict) -> dict:
    checks = []

    def add(cid, label, passed, value, rule):
        checks.append({"id": cid, "label": label, "passed": bool(passed), "value": value, "rule": rule})

    if ev.get("status") != "ok":
        add("fitted", "Ratio fitted", False, ev.get("reason", "not fitted"), f"At least {MIN_TRAIN_DAYS} training days with known coverage.")
        return {"version": GATE_VERSION, "status": "insufficient", "checks": checks,
                "label": "Not enough data to fit or test the day-level ratio"}
    h = ev["held_out"]
    cal, raw, con = h["day_ratio"], h["raw_viirs"], h["constant_train_mean"]
    lo, hi = LEVEL
    add("days", "Enough held-out days", ev["held_out_days"] >= MIN_HELD_OUT_DAYS, f"{ev['held_out_days']:,} days",
        f"At least {MIN_HELD_OUT_DAYS} held-out days with a known coverage state for both sensors.")
    add("level", "Total level close to MODIS", cal["ratio"] is not None and lo <= cal["ratio"] <= hi,
        "—" if cal["ratio"] is None else f"Σ estimate / Σ MODIS = {cal['ratio']:.2f}", f"Held-out total between {lo:g}× and {hi:g}× the MODIS total.")
    add("beats_unadjusted", "Daily totals better than raw VIIRS", cal["mae"] < raw["mae"] and cal["rmse"] < raw["rmse"],
        f"MAE {cal['mae']:.1f} vs {raw['mae']:.1f}; RMSE {cal['rmse']:.1f} vs {raw['rmse']:.1f}", "Held-out daily MAE and RMSE below raw VIIRS.")
    add("beats_constant", "Daily totals better than a constant", cal["mae"] < con["mae"] and cal["rmse"] < con["rmse"],
        f"MAE {cal['mae']:.1f} vs {con['mae']:.1f}; RMSE {cal['rmse']:.1f} vs {con['rmse']:.1f}",
        "Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.")
    yrs = [y for y in ev["rolling_origin"]["years"] if y["ratio"] is not None]
    share = (sum(1 for y in yrs if y["within_level"]) / len(yrs)) if yrs else 0.0
    worst = max(yrs, key=lambda y: abs(math.log(y["ratio"])) if y["ratio"] > 0 else math.inf) if yrs else None
    add("roll_years", "Enough rolling-origin years", len(yrs) >= MIN_ROLL_YEARS, f"{len(yrs)} years",
        f"At least {MIN_ROLL_YEARS} calendar years predicted from earlier years only.")
    add("roll_share", "Most years close to MODIS", share >= STABLE_SHARE,
        f"{sum(1 for y in yrs if y['within_level'])} of {len(yrs)} years within {lo:g}–{hi:g}×",
        f"At least {STABLE_SHARE:.0%} of rolling-origin years within {lo:g}–{hi:g}×.")
    add("roll_hard", "No year far off", bool(yrs) and all(HARD[0] <= y["ratio"] <= HARD[1] for y in yrs),
        "—" if worst is None else f"worst year {worst['year']}: {worst['ratio']:.2f}×", f"No rolling-origin year outside {HARD[0]:g}–{HARD[1]:g}×.")
    hd = ev["activity"]["high"]["day_ratio"]
    add("high_activity", "High-fire days close to MODIS", hd["n"] >= MIN_HIGH_DAYS and hd["ratio"] is not None and lo <= hd["ratio"] <= hi,
        f"{hd['n']} days" + ("" if hd["ratio"] is None else f", {hd['ratio']:.2f}×"),
        f"At least {MIN_HIGH_DAYS} held-out days at or above the training {HIGH_PCT}th percentile, total within {lo:g}–{hi:g}×.")
    passed = all(ch["passed"] for ch in checks)
    return {"version": GATE_VERSION, "status": "passes" if passed else "not_validated", "checks": checks,
            "label": "Passes the project's aggregate validation rules (chronological hold-out and year-by-year stability)" if passed
            else "Not validated under the project's aggregate rules: the calibrated line is not drawn",
            "note": "\"Passes\" means the documented PyroSync rules on held-out (later) data; it is not an official or NASA validation."}


# ------------------------------------------------------------------ report
def report(f, cfg, c=None) -> dict:
    """Aggregate report for one AOI, period, filter set and sensor pair. With a harmonization core `c`, the event-level
    model's daily sums are added as comparison lines (the ratio itself never uses the core)."""
    rev = get_revision()
    key = cache.make_key("aggregate", rev, {"f": f.key(), "c": cfg.key(), "events": c is not None and c.alpha is not None})
    return cache.get_or_compute(key, lambda: _report(f, cfg, c))


def _event_predictions(c, nd: int) -> dict | None:
    if c is None or c.alpha is None or c.cfg.metric != "detections":
        return None
    i0 = (c.f.start - date(1970, 1, 1)).days
    off = c.day - i0
    vs = (c.sensor == 1) & (off >= 0) & (off < nd)
    dom = vs & c.in_domain
    return {"event_loglog_all_viirs": np.bincount(off[vs], weights=H.predict(c.alpha, c.beta, c.val[vs].astype(float)), minlength=nd),
            "event_loglog_model_domain": np.bincount(off[dom], weights=H.predict(c.alpha, c.beta, c.val[dom].astype(float)), minlength=nd)}


def _report(f, cfg, c) -> dict:
    arr = daily_arrays(f, cfg, c)
    split, split_rule = _split_day(cfg, arr)
    event_pred = _event_predictions(c, len(arr["dates"]))
    qs = {q: _evaluate(arr, q, split, event_pred) for q in QUANTITIES}
    vlabel = H.N.SERIES_LABEL.get(cfg.viirs_series, cfg.viirs_series)
    mlabel = "MODIS " + " + ".join(cfg.modis_platforms)
    return {"method_version": AGG_VERSION, "gate_version": GATE_VERSION, "dataset_revision": get_revision(),
            "config": cfg.key(), "effective_filters": _filters(f, cfg).key(),
            "split": split.isoformat() if split else None, "split_rule": split_rule,
            "equation": "M̂_d = c · V_d,  c = Σ_train M_d / Σ_train V_d (training days with known coverage of both sensors)",
            "modis_label": mlabel, "viirs_label": vlabel,
            "estimate_label": {"detections": f"{mlabel} detections per day, estimated from {vlabel} (experimental)",
                               "cells": f"{mlabel} occupied {cfg.unit_grid}° cells per day, estimated from {vlabel} (experimental)"},
            "valid_period": [arr["dates"][int(np.nonzero(arr["known"])[0][0])].isoformat(),
                             arr["dates"][int(np.nonzero(arr["known"])[0][-1])].isoformat()] if arr["known"].any() else None,
            "event_model_compared": event_pred is not None,
            "quantities": qs, "reference_doc": REFERENCE_DOC,
            "coverage": {"status": "not_verified", "note": H.COVERAGE_NOTE},
            "limitations": [
                "Day totals are calibrated, not single fires: the ratio says nothing about the MODIS count of one cell and overpass.",
                "The ratio assumes a stable MODIS/VIIRS relation; it is tested only where both sensors exist (S-NPP from 2012-01, NOAA-20 from "
                "2018-04, NOAA-21 from 2023-03). Applying it outside the valid period is extrapolation and is not done by PyroSync.",
                "Aqua left the A-Train in January 2022 and its overpass time drifts later; the year-by-year results after 2022 show whether that "
                "changes the ratio.",
                "Satellite coverage (swath, cloud, smoke) is not verified: unknown days are excluded, but cloudy known days still count.",
                "The same rules apply to every AOI; small AOIs have few active days and often fail the gate.",
            ]}


def series(f, cfg, agg: str, quantity: str) -> dict:
    """Original MODIS and VIIRS daily/monthly totals and, only when that quantity passes the gate, the calibrated line with its
    bootstrap band. Unknown days stay empty (None), never zero."""
    if agg not in ("day", "month"):
        raise ValueError("agg must be 'day' or 'month'")
    if quantity not in QUANTITIES:
        raise ValueError("quantity must be 'detections' or 'cells'")
    rep = report(f, cfg)
    arr = daily_arrays(f, cfg)
    ev = rep["quantities"][quantity]
    M, V = (arr["M"], arr["V"]) if quantity == "detections" else (arr["Mc"], arr["Vc"])
    km, kv, both = arr["known_m"], arr["known_v"], arr["known"]
    ok = ev.get("gate", {}).get("status") == "passes"
    b = ev.get("bootstrap") if ok else None
    cal = ev["c"] * V if ok else None
    lo = b["c_lo"] * V if b else None
    hi = b["c_hi"] * V if b else None
    dates = arr["dates"]
    nd = len(dates)
    if agg == "day":
        rows = {"dates": [d.isoformat() for d in dates],
                "modis": [float(M[i]) if km[i] else None for i in range(nd)],
                "viirs": [float(V[i]) if kv[i] else None for i in range(nd)],
                "calibrated": [float(cal[i]) if kv[i] else None for i in range(nd)] if cal is not None else None,
                "band": [[float(lo[i]), float(hi[i])] if kv[i] else None for i in range(nd)] if lo is not None else None,
                "known_days": None, "days": None}
    else:
        keys: dict[tuple[int, int], list[int]] = {}
        for i, d in enumerate(dates):
            keys.setdefault((d.year, d.month), []).append(i)
        rows = {"dates": [], "modis": [], "viirs": [], "calibrated": [] if cal is not None else None,
                "band": [] if lo is not None else None, "known_days": [], "days": []}
        for (y, m), idxs in keys.items():
            ix = [i for i in idxs if both[i]]
            rows["dates"].append(f"{y:04d}-{m:02d}")
            rows["known_days"].append(len(ix))
            rows["days"].append(len(idxs))
            rows["modis"].append(float(M[ix].sum()) if ix else None)
            rows["viirs"].append(float(V[ix].sum()) if ix else None)
            if cal is not None:
                rows["calibrated"].append(float(cal[ix].sum()) if ix else None)
            if lo is not None:
                rows["band"].append([float(lo[ix].sum()), float(hi[ix].sum())] if ix else None)
    compact = {k: ev.get(k) for k in ("quantity", "definition", "status", "reason", "c", "bootstrap", "split", "train_days", "held_out_days",
                                       "train_period", "held_out_period", "unknown_share")}
    return {"agg": agg, "quantity": quantity, "method_version": AGG_VERSION, "gate": ev.get("gate"), "evaluation": compact,
            "split": rep["split"], "valid_period": rep["valid_period"], **rows,
            "modis_label": rep["modis_label"] + " (observed)", "viirs_label": rep["viirs_label"] + " (original)",
            "calibrated_label": rep["estimate_label"][quantity],
            "notes": [
                "Original values are the app's per-sensor daily series for these filters; they are never changed.",
                "Days whose coverage state is unknown for a sensor are empty (not zero). Monthly sums use only days on which both sensors have "
                "a known state; 'known_days' gives their number.",
                "The calibrated line is c × VIIRS (day-level ratio). Before the split date it is in-sample. It is drawn only when this quantity "
                "passes the aggregate gate (chronological hold-out and year-by-year stability). The band is the 95 % month-block bootstrap of c.",
                "Estimates exist only where VIIRS exists; no value is extrapolated to years before the VIIRS record.",
            ]}


def augment_map(out: dict, f, cfg) -> dict:
    """Adds the day-ratio estimate (c × VIIRS detections per cell) to a map window, only when the detections quantity passes the gate."""
    rep = report(f, cfg)
    ev = rep["quantities"]["detections"]
    ok = ev.get("gate", {}).get("status") == "passes"
    for r in out.get("cells", []):
        r["value_ratio"] = ev["c"] * r["viirs"] if ok else None
    t = out.get("totals")
    if t is not None:
        t["ratio_estimate"] = ev["c"] * t["viirs"] if ok else None
    out["ratio_model"] = {"available": ok, "c": ev.get("c"), "gate_status": ev.get("gate", {}).get("status"), "split": rep["split"],
                          "label": "MODIS-equivalent index per cell = c × VIIRS detections (day-level ratio; validated for AOI daily totals, "
                                   "not for single cells)"}
    return out


# ------------------------------------------------------------------ regional ratio check (error map view)
def regional_ratio(c, err_grid_factor: int, min_days: int) -> list[dict]:
    """Per region cell: held-out Σ c·V / Σ M (detections) with the AOI's c, on known held-out days (needs the run's events)."""
    rep = report(c.f, c.cfg)
    ev = rep["quantities"]["detections"]
    if ev.get("status") != "ok" or rep["split"] is None:
        return []
    arr = daily_arrays(c.f, c.cfg)
    dates = arr["dates"]
    i0 = (dates[0] - date(1970, 1, 1)).days
    off = c.day - i0
    nd = len(dates)
    s = (date.fromisoformat(rep["split"]) - dates[0]).days
    ok = (off >= 0) & (off < nd)
    held = np.zeros(len(c.day), bool)
    held[ok] = arr["known"][off[ok]] & (off[ok] >= s)
    k = err_grid_factor
    rx, ry = c.ci // k, c.cj // k
    out: dict[tuple[int, int], dict] = {}
    for idx in np.nonzero(held)[0]:
        key = (int(rx[idx]), int(ry[idx]))
        r = out.setdefault(key, {"ci": key[0], "cj": key[1], "M": 0.0, "V": 0.0, "_days": set()})
        if c.sensor[idx] == 0:
            r["M"] += float(c.n[idx])
        else:
            r["V"] += float(c.n[idx])
        r["_days"].add(int(off[idx]))
    rows = []
    cv = ev["c"]
    for r in out.values():
        nd_ = len(r.pop("_days"))
        est = cv * r["V"]
        ratio = est / r["M"] if r["M"] > 0 else None
        status = "too_few" if nd_ < min_days else ("within" if ratio is not None and LEVEL[0] <= ratio <= LEVEL[1] else "outside")
        rows.append(r | {"estimate": est, "ratio": ratio, "active_days": nd_, "status": status})
    rows.sort(key=lambda r: (r["cj"], r["ci"]))
    return rows


def report_markdown(rep: dict, title: str) -> str:
    def f(x, nd=2):
        return "—" if x is None else f"{x:,.{nd}f}"

    L = [f"# {title}", "", f"Method `{rep['method_version']}`, gate `{rep['gate_version']}`, dataset revision {rep['dataset_revision']}.",
         f"Config `{rep['config']}`; AOI `{rep['effective_filters']['aoi']}`; types `{','.join(rep['effective_filters']['types'])}`.", "",
         f"Equation: {rep['equation']}. Split: {rep['split']} ({rep['split_rule']}). Valid period: {rep['valid_period']}.", "",
         REFERENCE_DOC, ""]
    for q, ev in rep["quantities"].items():
        L += [f"## {q.capitalize()}", "", ev["definition"], ""]
        if ev["status"] != "ok":
            L += [f"Not fitted: {ev.get('reason')}", ""]
            continue
        b = ev.get("bootstrap") or {}
        L += [f"c = {ev['c']:.4f} (95 % month-block bootstrap {f(b.get('c_lo'), 4)}–{f(b.get('c_hi'), 4)}); "
              f"{ev['train_days']:,} training days {ev['train_period']}, {ev['held_out_days']:,} held-out days {ev['held_out_period']}; "
              f"{ev['unknown_share']:.1%} of days have an unknown coverage state for at least one sensor.", ""]
        if "loglog_slope_diagnostic" in ev:
            L += [f"Diagnostic day-level log-log slope β = {ev['loglog_slope_diagnostic']['beta']:.3f}.", ""]
        L += ["| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |", "|---|---|---|---|---|"]
        for k, m in ev["held_out"].items():
            L.append(f"| {k} | {f(m['ratio'])} | {f(m['mae'], 1)} | {f(m['rmse'], 1)} | {f(m['mbe'], 1)} |")
        hi, lo = ev["activity"]["high"], ev["activity"]["low"]
        L += ["", f"High-activity days (MODIS ≥ {ev['activity']['threshold']:.0f}): {hi['day_ratio']['n']} days, day ratio {f(hi['day_ratio']['ratio'])}× "
              f"(raw VIIRS {f(hi['raw_viirs']['ratio'])}×); low-activity days: {lo['day_ratio']['n']} days, {f(lo['day_ratio']['ratio'])}×.",
              f"Monthly totals ({ev['monthly']['months']} months with ≥ {MIN_MONTH_DAYS} known days): ratio {f(ev['monthly']['day_ratio']['ratio'])}×, "
              f"MAE {f(ev['monthly']['day_ratio']['mae'], 0)}; share of months within {LEVEL[0]}–{LEVEL[1]}×: "
              f"{'—' if ev['monthly'].get('share_within_level') is None else format(ev['monthly']['share_within_level'], '.0%')}.", "",
              "| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |", "|---|---|---|---|---|---|---|"]
        for y in ev["rolling_origin"]["years"]:
            L.append(f"| {y['year']} | {y['c']:.4f} | {y['test_days']} | {f(y['ratio'])} | {f(y['raw_ratio'])} | {f(y['mae'], 1)} | {f(y['constant_mae'], 1)} |")
        g = ev["gate"]
        L += ["", f"**Gate: {g['status']}** — {g['label']}", ""]
        for ch in g["checks"]:
            L.append(f"- {'✔' if ch['passed'] else '✘'} {ch['label']}: {ch['value']} ({ch['rule']})")
        L.append("")
    L += ["## Limitations", ""] + [f"- {x}" for x in rep["limitations"]] + ["", f"Coverage: {rep['coverage']['note']}", ""]
    return "\n".join(L)


def summary_markdown(runs: list[tuple[str, str, dict]]) -> str:
    """Overview of several runs (CLI `harmonize-aggregate`)."""
    def f(x, nd=2):
        return "—" if x is None else f"{x:,.{nd}f}"

    L = ["# Day-level (aggregate) calibration: generated summary", "",
         f"Method `{AGG_VERSION}`, gate `{GATE_VERSION}`. Generated by `python -m pyrosync.cli harmonize-aggregate`. Every number is "
         "computed from the imported archive; thresholds are fixed in `backend/pyrosync/aggregate.py` before the runs.", "",
         "| Run | Quantity | c (95 % bootstrap) | Split | Held-out days | Σ est / Σ MODIS | Daily MAE: ratio / raw VIIRS / constant | "
         "High-fire days | Rolling years within 0.8–1.25× (range) | Gate |", "|---|---|---|---|---|---|---|---|---|---|"]
    for rid, label, rep in runs:
        for q, ev in rep["quantities"].items():
            if ev["status"] != "ok":
                L.append(f"| {rid} {label} | {q} | — | {rep['split']} | {ev['held_out_days']} | — | — | — | — | {ev['gate']['status']} |")
                continue
            h = ev["held_out"]
            b = ev.get("bootstrap") or {}
            yrs = [y for y in ev["rolling_origin"]["years"] if y["ratio"] is not None]
            rr = f"{sum(1 for y in yrs if y['within_level'])} of {len(yrs)} ({min(y['ratio'] for y in yrs):.2f}–{max(y['ratio'] for y in yrs):.2f})" if yrs else "—"
            hi = ev["activity"]["high"]["day_ratio"]
            L.append(f"| {rid} {label} | {q} | {ev['c']:.4f} ({f(b.get('c_lo'), 4)}–{f(b.get('c_hi'), 4)}) | {rep['split']} | {ev['held_out_days']:,} | "
                     f"{f(h['day_ratio']['ratio'])} | {f(h['day_ratio']['mae'], 1)} / {f(h['raw_viirs']['mae'], 1)} / {f(h['constant_train_mean']['mae'], 1)} | "
                     f"{hi['n']} days, {f(hi['ratio'])}× | {rr} | **{ev['gate']['status']}** |")
    L += ["", "\"passes\" = the documented PyroSync aggregate rules on later (held-out) data; it is not an official or NASA validation. "
          "Per-run details, including every gate check and the year-by-year table, are in each run's `report.md`.", ""]
    return "\n".join(L)
