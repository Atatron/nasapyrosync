"""Descriptive analysis: ISO weeks, rankings, year comparison, baseline eligibility, elevated periods.

Nothing here is a statistical significance test, forecast, or risk probability.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta

import numpy as np

from . import cache
from . import normalize as N
from .db import cursor, get_revision
from .query import Filters, cell_sql, daily, envelope, filtered_sql, inventory

KNOWN = {"detections", "zero_reported"}


def _daily_for(f: Filters, series: str) -> dict:
    """Per-sensor daily series, or (1.5) the harmonized multi-sensor series 'FUSED' in the same shape."""
    if series == "FUSED":
        from . import fusion
        return fusion.daily_like(f)
    return daily(f)
METRIC_LABEL = {
    "cells": ("Occupied cells", "cells/day"),
    "detections": ("Detections", "detections/day"),
    "frp_sum": ("Summed FRP", "MW (sum of per-detection FRP)"),
    "frp_max": ("Maximum FRP", "MW"),
    "frp_mean": ("Mean FRP", "MW"),
}

# Project settings (documented; NOT NASA-validated thresholds)
BASELINE_DEFAULTS = {"window_days": 15, "min_years": 5, "min_reference_days": 100, "min_year_coverage": 0.8,
                     "upper_percentile": 95, "lower_percentile": 5}
ELEVATED_DEFAULTS = {"min_consecutive_days": 3, "min_activity": 1, "mode": "range_percentile", "percentile": 90, "fixed_threshold": None}


def series_values(d: dict, series: str, metric: str) -> tuple[list[date], list[float | None], list[str]]:
    if series == "FUSED" and metric != "detections":
        raise ValueError("The harmonized series is defined for detections only (MODIS-Aqua-equivalent detections per day); "
                         "choose Detections / day as the metric.")
    if series not in d["series"]:
        raise ValueError(f"series '{series}' is not selected by the current platform filter")
    s = d["series"][series]
    if series == "UNION" and metric != "cells":
        raise ValueError("The union series is defined only for occupied cells (cells with detections from any selected sensor); "
                         "raw MODIS and VIIRS counts are not combined.")
    if metric not in ("cells", "detections", "frp_sum", "frp_max", "frp_mean"):
        raise ValueError("unknown metric")
    dates = [date.fromisoformat(x) for x in d["dates"]]
    vals: list[float | None] = []
    for i, st in enumerate(s["status"]):
        if st not in KNOWN:
            vals.append(None)
        else:
            v = s[metric][i]
            vals.append(0.0 if v is None else float(v))
    return dates, vals, list(s["status"])


# ------------------------------------------------------------------ ISO weeks
def iso_weeks(f: Filters, series: str, metric: str) -> dict:
    key = cache.make_key("isoweeks", get_revision(), {**f.key(), "series": series, "metric": metric})
    return cache.get_or_compute(key, lambda: _iso_weeks(f, series, metric))


def _iso_weeks(f: Filters, series: str, metric: str) -> dict:
    d = _daily_for(f, series)
    dates, vals, sts = series_values(d, series, metric)
    weeks: "OrderedDict[tuple[int, int], dict]" = OrderedDict()
    for dt, v, st in zip(dates, vals, sts):
        iy, iw, _ = dt.isocalendar()
        w = weeks.setdefault((iy, iw), {"iso_year": iy, "iso_week": iw, "start": (dt - timedelta(days=dt.isoweekday() - 1)).isoformat(),
                                         "days_in_range": 0, "days_known": 0, "value": 0.0, "max_day": None})
        w["days_in_range"] += 1
        if v is not None:
            w["days_known"] += 1
            if metric == "frp_max":
                w["value"] = max(w["value"], v)
            else:
                w["value"] += v
    if metric == "frp_mean":
        # weekly mean FRP = sum FRP / detections (not the mean of daily means)
        _, s_sum, _ = series_values(d, series, "frp_sum")
        _, s_det, _ = series_values(d, series, "detections")
        acc: dict = {}
        for dt, a, b in zip(dates, s_sum, s_det):
            k = dt.isocalendar()[:2]
            x = acc.setdefault(k, [0.0, 0.0])
            x[0] += a or 0; x[1] += b or 0
        for k, w in weeks.items():
            w["value"] = round(acc[k][0] / acc[k][1], 3) if acc[k][1] else 0.0
    distinct = {}
    if metric == "cells":
        sql, params = filtered_sql(f)
        _, _, cell = cell_sql(f.grid)
        cond = "" if series == "UNION" else "WHERE series = ?"
        p2 = params + ([] if series == "UNION" else [series])
        with cursor() as cur:
            for iy, iw, c in cur.execute(f"SELECT isoyear(acq_date), week(acq_date), count(DISTINCT {cell}) FROM ({sql}) o {cond} GROUP BY ALL", p2).fetchall():
                distinct[(iy, iw)] = c
    out = []
    for k, w in weeks.items():
        w["partial"] = w["days_in_range"] < 7
        w["coverage_complete"] = w["days_known"] == w["days_in_range"]
        w["value"] = round(w["value"], 3)
        if metric == "cells":
            w["sum_daily_cells"] = w["value"]
            w["distinct_cells"] = distinct.get(k, 0)
        w["n_weeks_in_iso_year"] = date(w["iso_year"], 12, 28).isocalendar()[1]
        out.append(w)
    label, unit = METRIC_LABEL[metric]
    return envelope(f, {"metric": metric, "label": label, "unit": unit,
                        "weekly_value": "Sum of daily values over the ISO week (max for maximum FRP; summed FRP ÷ detections for mean FRP). "
                                        "For occupied cells, the weekly value is the SUM of daily occupied cells; distinct cells per week are reported separately."},
                    series=series, series_label=N.SERIES_LABEL[series], weeks=out,
                    iso_note="ISO 8601 weeks start on Monday; week 1 contains the year's first Thursday. ISO years have 52 or 53 weeks, and "
                             "early-January/late-December days can belong to the neighbouring ISO year (e.g. 2024-12-30 is 2025-W01).")


# ------------------------------------------------------------------ rankings & year comparison
def rankings(f: Filters, series: str, metric: str, top: int = 10) -> dict:
    d = _daily_for(f, series)
    dates, vals, _ = series_values(d, series, metric)
    days = sorted([(v, dt) for dt, v in zip(dates, vals) if v is not None and v > 0], key=lambda x: (-x[0], x[1]))[:top]
    wk = iso_weeks(f, series, metric)
    weeks = sorted([w for w in wk["weeks"] if w["value"] > 0], key=lambda w: (-w["value"], w["start"]))[:top]
    label, unit = METRIC_LABEL[metric]
    return envelope(f, {"metric": metric, "label": label, "unit": unit}, series=series, series_label=N.SERIES_LABEL[series],
                    top_days=[{"date": dt.isoformat(), "value": v, "rank": i + 1} for i, (v, dt) in enumerate(days)],
                    top_weeks=[{**w, "rank": i + 1} for i, w in enumerate(weeks)],
                    note="Descriptive rankings of the most active observed days and ISO weeks in the selected range. "
                         "They are not statistically significant anomalies.")


def _md(dt: date) -> tuple[int, int]:
    return dt.month, dt.day


def year_compare(f: Filters, series: str, metric: str, year: int, reference_year: int) -> dict:
    if year == reference_year:
        raise ValueError("choose two different years")
    full = f.model_copy(update={"start": date(min(year, reference_year), 1, 1), "end": date(max(year, reference_year), 12, 31)})
    d = _daily_for(full, series)
    dates, vals, _ = series_values(d, series, metric)
    by = {dt: v for dt, v in zip(dates, vals)}
    pairs = []
    leap_excluded = False
    dt = date(year, 1, 1)
    while dt.year == year:
        try:
            ref = date(reference_year, dt.month, dt.day)
        except ValueError:
            ref = None
        if ref is None:
            leap_excluded = True
        else:
            a, b = by.get(dt), by.get(ref)
            pairs.append({"month_day": f"{dt.month:02d}-{dt.day:02d}", "date": dt.isoformat(), "ref_date": ref.isoformat(), "value": a, "ref_value": b,
                          "matched": a is not None and b is not None})
        dt += timedelta(days=1)
    if date(reference_year, 12, 31).timetuple().tm_yday == 366 and date(year, 12, 31).timetuple().tm_yday == 365:
        leap_excluded = True
    months = []
    for m in range(1, 13):
        ps = [p for p in pairs if int(p["month_day"][:2]) == m and p["matched"]]
        if metric == "frp_max":
            a = max((p["value"] for p in ps), default=0.0); b = max((p["ref_value"] for p in ps), default=0.0)
        else:
            a = sum(p["value"] for p in ps); b = sum(p["ref_value"] for p in ps)
        months.append({"month": m, "matched_days": len(ps), "value": round(a, 3), "ref_value": round(b, 3), "difference": round(a - b, 3),
                       "ratio": round(a / b, 3) if b > 0 else None,
                       "ratio_note": None if b > 0 else "reference value is zero; ratio undefined"})
    matched = [p for p in pairs if p["matched"]]
    tot_a = sum(p["value"] for p in matched); tot_b = sum(p["ref_value"] for p in matched)
    label, unit = METRIC_LABEL[metric]
    notes = ["Descriptive comparison against one clearly labeled reference year; not a baseline and not evidence of a trend or seasonal shift.",
             "Only month-days with known coverage in both years are compared (matched dates)."]
    if leap_excluded:
        notes.append("February 29 has no counterpart in the non-leap year and is excluded from matched totals.")
    if metric != "frp_max":
        notes.append("Summed occupied cells count a cell once per day it is occupied." if metric == "cells" else "")
    return envelope(f, {"metric": metric, "label": label, "unit": unit}, series=series, series_label=N.SERIES_LABEL[series],
                    year=year, reference_year=reference_year, months=months, daily=pairs,
                    totals={"value": round(tot_a, 3), "ref_value": round(tot_b, 3), "matched_days": len(matched),
                            "ratio": round(tot_a / tot_b, 3) if tot_b > 0 else None},
                    notes=[n for n in notes if n])


# ------------------------------------------------------------------ baseline
def _shift(dt: date, year: int) -> date:
    try:
        return dt.replace(year=year)
    except ValueError:  # Feb 29 -> Feb 28 in non-leap reference years
        return date(year, 2, 28)


def compute_baseline(values: dict[date, float | None], eval_dates: list[date], cfg: dict | None = None) -> dict:
    """Seasonal-window empirical baseline per evaluation day.

    For day D in year Y: reference = values on dates within ±window days of D's month-day
    in each prior year y < Y, restricted to known-coverage days and excluding any date in Y.
    """
    c = {**BASELINE_DEFAULTS, **(cfg or {})}
    w = c["window_days"]
    if not values:
        return {"eligible": False, "reason": "No data.", "config": c, "days": []}
    years = sorted({dt.year for dt in values})
    out_days = []
    any_eligible = False
    year_reports: dict[int, dict] = {}
    for d in eval_dates:
        Y = d.year
        prior = [y for y in years if y < Y]
        refs: list[float] = []
        elig_years = []
        for y in prior:
            anchor = _shift(d, y)
            win = [anchor + timedelta(days=k) for k in range(-w, w + 1)]
            win = [x for x in win if x.year != Y]
            known = [values[x] for x in win if values.get(x) is not None]
            if win and len(known) / len(win) >= c["min_year_coverage"]:
                elig_years.append(y)
                refs.extend(known)
        n = len(refs)
        ok = len(elig_years) >= c["min_years"] and n >= c["min_reference_days"]
        rec = {"date": d.isoformat(), "eligible_years": elig_years, "n": n, "eligible": ok}
        if ok:
            arr = np.asarray(refs, dtype=float)
            rec.update({"median": float(np.median(arr)), "p_low": float(np.percentile(arr, c["lower_percentile"])),
                        "p_high": float(np.percentile(arr, c["upper_percentile"]))})
            any_eligible = True
        out_days.append(rec)
        yr = year_reports.setdefault(Y, {"year": Y, "prior_years_available": prior, "max_eligible_years": 0})
        yr["max_eligible_years"] = max(yr["max_eligible_years"], len(elig_years))
    if any_eligible:
        reason = None
    else:
        best = max((r["max_eligible_years"] for r in year_reports.values()), default=0)
        avail = sorted({y for r in year_reports.values() for y in r["prior_years_available"]})
        reason = (f"Insufficient history for a robust multi-year baseline: at most {best} comparable prior year(s) "
                  f"({', '.join(map(str, avail)) or 'none'}) available for the evaluated dates; the project rule requires at least "
                  f"{c['min_years']} prior years with ≥{int(c['min_year_coverage'] * 100)}% known coverage in each ±{w}-day seasonal window "
                  f"and ≥{c['min_reference_days']} reference days.")
    return {"eligible": any_eligible, "reason": reason, "config": c, "days": out_days, "years": list(year_reports.values())}


def baseline(f: Filters, series: str, metric: str, cfg: dict | None = None) -> dict:
    key = cache.make_key("baseline", get_revision(), {**f.key(), "series": series, "metric": metric, "cfg": cfg or {}})
    return cache.get_or_compute(key, lambda: _baseline(f, series, metric, cfg))


def _baseline(f: Filters, series: str, metric: str, cfg: dict | None) -> dict:
    inv = inventory()
    if not inv["date_range"]:
        raise ValueError("no data imported")
    lo = min(date.fromisoformat(inv["date_range"][0]), f.start)
    full = f.model_copy(update={"start": lo, "end": f.end})
    d = _daily_for(full, series)
    dates, vals, sts = series_values(d, series, metric)
    values = dict(zip(dates, vals))
    eval_dates = [dt for dt in dates if f.start <= dt <= f.end]
    b = compute_baseline(values, eval_dates, cfg)
    flags = []
    for rec in b["days"]:
        dt = date.fromisoformat(rec["date"])
        v = values.get(dt)
        rec["value"] = v
        rec["status"] = sts[dates.index(dt)]
        rec["flag"] = None
        if not rec["eligible"] or v is None:
            continue
        if v > rec["p_high"]:
            rec["flag"] = "above"
        elif rec["p_low"] > 0 and v < rec["p_low"]:
            rec["flag"] = "below"
        rec["ratio_to_median"] = round(v / rec["median"], 3) if rec["median"] > 0 else None
        if rec["flag"]:
            flags.append(rec)
    label, unit = METRIC_LABEL[metric]
    return envelope(f, {"metric": metric, "label": label, "unit": unit,
                        "threshold": f"Empirical {b['config']['upper_percentile']}th/{b['config']['lower_percentile']}th percentiles of reference days "
                                     "(descriptive threshold exceedances; not significance tests or risk probabilities)."},
                    series=series, series_label=N.SERIES_LABEL[series], eligibility={"eligible": b["eligible"], "reason": b["reason"],
                    "config": b["config"], "years": b.get("years", []),
                    "rule_note": "Project eligibility rule (conservative project choice, not an official NASA standard)."},
                    days=b["days"], flags=flags,
                    notes=["Low-activity flags are suppressed when the lower threshold is zero or coverage is unknown.",
                           "Reference years exclude the evaluation year; Feb 29 maps to Feb 28 in non-leap reference years."])


# ------------------------------------------------------------------ elevated periods
def find_periods(dates: list[date], values: list[float | None], thresholds: list[float | None], min_days: int, min_activity: float) -> list[dict]:
    periods = []
    run: list[int] = []

    def close(end_idx_exclusive: int):
        if len(run) >= min_days:
            a, b = run[0], run[-1]
            before = dates[a] - timedelta(days=1)
            after = dates[b] + timedelta(days=1)
            bi = a - 1
            ai = b + 1
            notes = []
            if bi >= 0 and values[bi] is None:
                notes.append(f"Preceded by a day with unknown coverage ({before.isoformat()}); the period may have started earlier.")
            if bi < 0:
                notes.append("Starts at the beginning of the analysis range; it may have started earlier.")
            if ai < len(dates) and values[ai] is None:
                notes.append(f"Followed by a day with unknown coverage ({after.isoformat()}); the period may have continued.")
            if ai >= len(dates):
                notes.append("Ends at the end of the analysis range; it may have continued.")
            periods.append({"start": dates[a].isoformat(), "end": dates[b].isoformat(), "duration_days": len(run),
                            "values": [values[i] for i in run], "thresholds": [thresholds[i] for i in run],
                            "peak": max(values[i] for i in run), "peak_date": dates[max(run, key=lambda i: values[i])].isoformat(),
                            "total": round(sum(values[i] for i in run), 3), "coverage_notes": notes})

    for i, (v, t) in enumerate(zip(values, thresholds)):
        q = v is not None and t is not None and v > t and v >= min_activity
        if q:
            run.append(i)
        else:
            close(i)
            run = []
    close(len(dates))
    return periods


def elevated(f: Filters, series: str, metric: str, mode: str = "range_percentile", percentile: float = 90, fixed_threshold: float | None = None,
             min_days: int = 3, min_activity: float = 1, baseline_cfg: dict | None = None) -> dict:
    key = cache.make_key("elevated", get_revision(), {**f.key(), "series": series, "metric": metric, "mode": mode, "p": percentile,
                                                      "fixed": fixed_threshold, "min_days": min_days, "min_activity": min_activity, "bcfg": baseline_cfg})
    return cache.get_or_compute(key, lambda: _elevated(f, series, metric, mode, percentile, fixed_threshold, min_days, min_activity, baseline_cfg))


def _elevated(f, series, metric, mode, percentile, fixed_threshold, min_days, min_activity, baseline_cfg) -> dict:
    if min_days < 1 or min_days > 60:
        raise ValueError("min_days must be 1–60")
    d = _daily_for(f, series)
    dates, vals, sts = series_values(d, series, metric)
    label, unit = METRIC_LABEL[metric]
    known = [v for v in vals if v is not None]
    unavailable = None
    threshold_info: dict = {"mode": mode}
    if mode == "fixed":
        if fixed_threshold is None:
            unavailable = "Enter a threshold value to use the user-defined activity threshold mode."
            thr = [None] * len(dates)
        else:
            thr = [float(fixed_threshold)] * len(dates)
            threshold_info.update({"label": "User-defined activity threshold", "value": float(fixed_threshold),
                                   "description": f"Day value must exceed {fixed_threshold:g} {unit} (value entered by the user)."})
    elif mode == "range_percentile":
        if not (50 <= percentile <= 99.9):
            raise ValueError("percentile must be between 50 and 99.9")
        if len(known) < 30:
            unavailable = f"Only {len(known)} days with known coverage in the range; at least 30 are needed for a within-range percentile."
            thr = [None] * len(dates)
        else:
            t = float(np.percentile(np.asarray(known), percentile))
            thr = [t] * len(dates)
            threshold_info.update({"label": "Within-range percentile threshold (descriptive)", "value": round(t, 3), "percentile": percentile,
                                   "reference": f"All {len(known)} known-coverage days in {f.start.isoformat()} – {f.end.isoformat()} (same AOI, filters, sensor, grid)",
                                   "description": f"Day value must exceed the {percentile:g}th percentile ({t:.3g} {unit}) of daily values in the analysis range. "
                                                  "This is a relative, within-range cut, not a historical baseline."})
    elif mode == "baseline":
        b = baseline(f, series, metric, baseline_cfg)
        if not b["eligibility"]["eligible"]:
            unavailable = b["eligibility"]["reason"]
            thr = [None] * len(dates)
        else:
            m = {x["date"]: x for x in b["days"]}
            thr = [m[dt.isoformat()].get("p_high") if m.get(dt.isoformat(), {}).get("eligible") else None for dt in dates]
            threshold_info.update({"label": "Historical seasonal baseline (descriptive threshold exceedance)",
                                   "description": f"Day value must exceed its seasonal {b['eligibility']['config']['upper_percentile']}th-percentile reference.",
                                   "config": b["eligibility"]["config"]})
    else:
        raise ValueError("mode must be fixed, range_percentile, or baseline")
    periods = [] if unavailable else find_periods(dates, vals, thr, min_days, min_activity)
    disc = None
    for p in periods:
        p["series"] = series
        p["series_label"] = N.SERIES_LABEL[series]
        p["metric"] = metric
        p["unit"] = unit
        p["threshold_label"] = threshold_info.get("label")
        p["reason"] = (f"{p['duration_days']} consecutive UTC days ({p['start']} to {p['end']}) on which {label.lower()} from {N.SERIES_LABEL[series]} "
                       f"exceeded the threshold ({_fmt_thr(p['thresholds'])} {unit}) and was ≥ {min_activity:g}; the rule requires ≥ {min_days} days. "
                       f"Peak {p['peak']:g} on {p['peak_date']}.")
        p["label"] = "Elevated observed activity"
    unknown_days = sum(1 for s in sts if s in ("unknown", "sensor_unavailable"))
    return envelope(f, {"metric": metric, "label": label, "unit": unit}, series=series, series_label=N.SERIES_LABEL[series],
                    rule={"min_consecutive_days": min_days, "min_activity": min_activity, "threshold": threshold_info,
                          "missing_days": "Days with unknown coverage break a run; they are never bridged. Adjacent unknown days are disclosed per period.",
                          "status": "Project setting, not a NASA-validated danger threshold."},
                    unavailable=unavailable, periods=periods, unknown_coverage_days=unknown_days,
                    disclaimer="Descriptive decision-support indicator based on satellite detections; not a fire forecast or an official emergency warning.")


def _fmt_thr(ts: list) -> str:
    vals = sorted({round(t, 3) for t in ts if t is not None})
    if len(vals) == 1:
        return f"{vals[0]:g}"
    return f"{vals[0]:g}–{vals[-1]:g}"
