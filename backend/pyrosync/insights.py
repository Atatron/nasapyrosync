"""AOI Insights (added in 1.3): fire regime, season tracker, recurrence, critical periods and readiness calendar.

Everything here describes OBSERVED satellite detections and their history for one sensor series at a time.
Nothing here is a forecast, a fire-danger rating, a probability of fire or an official warning.

Shared definitions
- History = every day from the first imported day up to the "as of" day (the end of the selected range), for the
  selected AOI, filters and ONE sensor series. Series are never added together.
- Known day = coverage state "detections" or "zero_reported". Unknown days are never treated as zero in percentiles.
- Eligible year = a calendar year in which at least YEAR_MIN_KNOWN of its days are known.
- Week bin = (day of year - 1) // 7, capped at 51, so bin 52 does not exist and bin 51 holds 8-9 days.
  A week value is the MEAN per known day, so bins of different length and partial coverage stay comparable;
  it needs at least WEEK_MIN_KNOWN known days, otherwise it is unknown.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import cache
from . import normalize as N
from .analysis import METRIC_LABEL, find_periods, series_values
from .db import cursor, get_revision
from .query import GRID_R, Filters, cell_sql, daily, envelope, filtered_sql, inventory

INSIGHTS_VERSION = "pyrosync-insights-1.0"
YEAR_MIN_KNOWN = 0.8
WEEK_MIN_KNOWN = 5
MIN_YEARS = 5
N_WEEKS = 52
SEASON_FRACTIONS = (0.10, 0.50, 0.90)
SEASON_MIN_TOTAL = 10  # a year with fewer detections (or cells) has no meaningful onset/peak/end
CRITICAL_DEFAULTS = {"percentile": 90, "min_days": 3, "min_activity": 1, "min_other_years": MIN_YEARS}
DISCLAIMER = ("Historical description of satellite fire detections. Not a forecast, not a fire-danger rating and not an official warning. "
              "Clouds, smoke and overpass timing hide some fires, so few detections do not prove few fires.")


# ------------------------------------------------------------------ helpers
def week_bin(d: date) -> int:
    return min((d.timetuple().tm_yday - 1) // 7, N_WEEKS - 1)


def week_label(w: int) -> str:
    a = date(2001, 1, 1) + timedelta(days=7 * w)
    b = date(2001, 12, 31) if w == N_WEEKS - 1 else a + timedelta(days=6)
    return f"{a.strftime('%d %b')} – {b.strftime('%d %b')}"


def _doy365(d: date) -> int:
    """Day of year on a 365-day calendar: Feb 29 shares Feb 28's index, later days shift back by one in leap years."""
    y = d.timetuple().tm_yday
    leap = (d.year % 4 == 0 and d.year % 100 != 0) or d.year % 400 == 0
    if leap and (d.month > 2 or (d.month == 2 and d.day == 29)):
        y -= 1
    return y  # 1..365


def _md(doy: float | None) -> str | None:
    if doy is None:
        return None
    return (date(2001, 1, 1) + timedelta(days=int(round(doy)) - 1)).strftime("%d %b")


def _history_filters(f: Filters, series: str) -> Filters:
    inv = inventory()
    if not inv["date_range"]:
        raise ValueError("no data imported")
    lo = date.fromisoformat(inv["date_range"][0])
    plats = [p for p in f.platforms if N.PLATFORM_SERIES[p] == series]
    if not plats:
        raise ValueError(f"series '{series}' is not selected by the current platform filter")
    return f.model_copy(update={"start": min(lo, f.end), "end": f.end, "platforms": plats})


def _history(f: Filters, series: str, metric: str):
    h = _history_filters(f, series)
    dates, vals, sts = series_values(daily(h), series, metric)
    return h, dates, vals


def _year_table(dates: list[date], vals: list[float | None]) -> dict[int, dict]:
    years: dict[int, dict] = {}
    for d, v in zip(dates, vals):
        y = years.setdefault(d.year, {"days": {}, "known": 0})
        y["days"][d] = v
        if v is not None:
            y["known"] += 1
    for yr, y in years.items():
        n_days = (date(yr, 12, 31) - date(yr, 1, 1)).days + 1
        y["n_days"] = n_days
        y["known_share"] = y["known"] / n_days
        y["eligible"] = y["known_share"] >= YEAR_MIN_KNOWN
        y["total"] = float(sum(v for v in y["days"].values() if v is not None))
    return years


def _weekly(ydays: dict[date, float | None]) -> list[float | None]:
    acc: list[list[float]] = [[] for _ in range(N_WEEKS)]
    for d, v in ydays.items():
        if v is not None:
            acc[week_bin(d)].append(v)
    return [float(np.mean(a)) if len(a) >= WEEK_MIN_KNOWN else None for a in acc]


def _cumulative(ydays: dict[date, float | None]) -> list[float]:
    """Cumulative total of known days by 365-day index (unknown days add nothing; disclosed)."""
    daily_v = [0.0] * 366
    for d, v in ydays.items():
        if v is not None:
            daily_v[_doy365(d)] += v
    return list(np.cumsum(daily_v[1:]))  # index 0 = 1 Jan ... 364 = 31 Dec


def _season_dates(cum: list[float]) -> dict | None:
    total = cum[-1]
    if total < SEASON_MIN_TOTAL:
        return None
    out = {}
    for frac, name in zip(SEASON_FRACTIONS, ("onset", "peak", "end")):
        i = int(np.searchsorted(np.asarray(cum), frac * total, side="left"))
        out[name] = i + 1  # 1-based day of a 365-day year
    return out


def _pct(arr, q):
    return float(np.percentile(np.asarray(arr, dtype=float), q)) if len(arr) else None


# ------------------------------------------------------------------ A1 + B4: fire regime and season tracker
def regime(f: Filters, series: str, metric: str = "detections") -> dict:
    key = cache.make_key("ins_regime", get_revision(), {**f.key(), "series": series, "metric": metric})
    return cache.get_or_compute(key, lambda: _regime(f, series, metric))


def _regime(f: Filters, series: str, metric: str) -> dict:
    if metric not in ("detections", "cells"):
        raise ValueError("the fire regime uses detections or occupied cells")
    h, dates, vals = _history(f, series, metric)
    years = _year_table(dates, vals)
    focus = f.end.year
    ref_years = sorted(y for y, r in years.items() if r["eligible"] and y != focus)
    label, unit = METRIC_LABEL[metric]
    year_rows = [{"year": y, "known_share": round(r["known_share"], 4), "eligible": r["eligible"], "total": r["total"],
                  "is_focus": y == focus} for y, r in sorted(years.items())]
    base = dict(series=series, series_label=N.SERIES_LABEL[series], focus_year=focus, as_of=f.end.isoformat(),
                history={"start": h.start.isoformat(), "end": h.end.isoformat()}, years=year_rows,
                reference_years=ref_years, method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER,
                rules={"year_min_known": YEAR_MIN_KNOWN, "week_min_known_days": WEEK_MIN_KNOWN, "min_years": MIN_YEARS,
                       "season_fractions": list(SEASON_FRACTIONS), "season_min_total": SEASON_MIN_TOTAL,
                       "week_bins": "Week k covers days 7k+1 … 7k+7 of the year; the last bin (k = 51) runs to 31 Dec.",
                       "reference": "Eligible calendar years other than the focus year (at least 80 % of days with known coverage)."})
    mdef = {"metric": metric, "label": label, "unit": unit}
    if len(ref_years) < MIN_YEARS:
        return envelope(h, mdef, available=False,
                        reason=f"Insufficient history: {len(ref_years)} eligible reference year(s) for {N.SERIES_LABEL[series]} in this AOI; "
                               f"at least {MIN_YEARS} complete years (≥ {int(YEAR_MIN_KNOWN * 100)} % known days) are needed.", **base)
    # weekly climatology (mean per known day in each week bin)
    wk = {y: _weekly(years[y]["days"]) for y in ref_years}
    weeks = []
    for w in range(N_WEEKS):
        xs = [wk[y][w] for y in ref_years if wk[y][w] is not None]
        enough = len(xs) >= MIN_YEARS
        weeks.append({"week": w, "label": week_label(w), "n_years": len(xs),
                      "median": _pct(xs, 50) if enough else None, "p10": _pct(xs, 10) if enough else None,
                      "p90": _pct(xs, 90) if enough else None})
    focus_week = _weekly(years[focus]["days"]) if focus in years else [None] * N_WEEKS
    peak_w = max((w for w in weeks if w["median"] is not None), key=lambda w: w["median"], default=None)
    # season dates per reference year
    per_year = []
    for y in ref_years:
        sd = _season_dates(_cumulative(years[y]["days"]))
        per_year.append({"year": y, "total": years[y]["total"], **({k: v for k, v in sd.items()} if sd else {"onset": None, "peak": None, "end": None}),
                         **({f"{k}_date": _md(v) for k, v in sd.items()} if sd else {})})
    season = {}
    for k in ("onset", "peak", "end"):
        xs = [r[k] for r in per_year if r.get(k) is not None]
        season[k] = {"median_doy": _pct(xs, 50), "p10_doy": _pct(xs, 10), "p90_doy": _pct(xs, 90), "n_years": len(xs),
                     "median": _md(_pct(xs, 50)), "early": _md(_pct(xs, 10)), "late": _md(_pct(xs, 90))} if len(xs) >= MIN_YEARS else None
    totals = [years[y]["total"] for y in ref_years]
    mean_t = float(np.mean(totals))
    variability = {"mean_annual": mean_t, "median_annual": _pct(totals, 50), "min": min(totals), "max": max(totals),
                   "cv": float(np.std(totals, ddof=1) / mean_t) if mean_t > 0 and len(totals) > 1 else None,
                   "max_year": ref_years[int(np.argmax(totals))], "min_year": ref_years[int(np.argmin(totals))]}
    # B4: cumulative season tracker
    cums = np.asarray([_cumulative(years[y]["days"]) for y in ref_years])
    env = {"p10": [float(x) for x in np.percentile(cums, 10, axis=0)], "median": [float(x) for x in np.percentile(cums, 50, axis=0)],
           "p90": [float(x) for x in np.percentile(cums, 90, axis=0)]}
    tracker = {"days": 365, "envelope": env, "focus": None, "status": None,
               "note": "Cumulative total of known days since 1 Jan. Unknown days add nothing, so years with gaps run low; "
                       "reference years need ≥ 80 % known days."}
    if focus in years:
        fy = years[focus]
        last_known = max((d for d, v in fy["days"].items() if v is not None), default=None)
        if last_known is not None:
            fc = _cumulative(fy["days"])
            idx = _doy365(last_known) - 1
            cur = fc[idx]
            ref_at = cums[:, idx]
            rank_pct = float(100.0 * (np.sum(ref_at < cur) + 0.5 * np.sum(ref_at == cur)) / len(ref_at))
            known_to_date = sum(1 for d, v in fy["days"].items() if v is not None and d <= last_known)
            days_to_date = (last_known - date(focus, 1, 1)).days + 1
            tracker["focus"] = [float(x) for x in fc[: idx + 1]]
            tracker["status"] = {"as_of": last_known.isoformat(), "cumulative": float(cur), "reference_median": float(np.median(ref_at)),
                                 "percentile_among_reference_years": round(rank_pct, 1),
                                 "years_below": int(np.sum(ref_at < cur)), "n_reference_years": int(len(ref_at)),
                                 "known_days": known_to_date, "days": days_to_date,
                                 "band": _tracker_band(rank_pct),
                                 "sentence": (f"By {last_known.strftime('%d %b %Y')}, {focus} had {cur:,.0f} {unit.split('/')[0]} — higher than "
                                              f"{int(np.sum(ref_at < cur))} of {len(ref_at)} reference years at the same date "
                                              f"(median {float(np.median(ref_at)):,.0f}). {known_to_date} of {days_to_date} days have known coverage.")}
    return envelope(h, mdef, available=True, reason=None, weeks=weeks, focus_weeks=focus_week,
                    peak_week=peak_w and {"week": peak_w["week"], "label": peak_w["label"], "median": peak_w["median"]},
                    season=season, season_by_year=per_year, variability=variability, tracker=tracker, **base)


def _tracker_band(p: float) -> str:
    if p >= 90:
        return "among the highest on record"
    if p >= 75:
        return "above the usual range"
    if p > 25:
        return "within the usual range"
    if p > 10:
        return "below the usual range"
    return "among the lowest on record"


# ------------------------------------------------------------------ A2: recurrence map
def recurrence(f: Filters, series: str, chronic_share: float = 0.4, limit: int = 60000) -> dict:
    key = cache.make_key("ins_recur", get_revision(), {**f.key(), "series": series, "chronic": chronic_share, "limit": limit})
    return cache.get_or_compute(key, lambda: _recurrence(f, series, chronic_share, limit))


def _recurrence(f: Filters, series: str, chronic_share: float, limit: int) -> dict:
    if not (0.1 <= chronic_share <= 1.0):
        raise ValueError("chronic_share must be between 0.1 and 1")
    h, dates, vals = _history(f, series, "detections")
    years = _year_table(dates, vals)
    elig = sorted(y for y, r in years.items() if r["eligible"])
    if not elig:
        return envelope(h, {"metric": "fire_years"}, available=False, reason="No calendar year with ≥ 80 % known coverage in the history.",
                        series=series, series_label=N.SERIES_LABEL[series], cells=[], method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER)
    sql, params = filtered_sql(h)
    ci, cj, _ = cell_sql(h.grid)
    with cursor() as cur:
        rows = cur.execute(f"""SELECT {ci} AS ci, {cj} AS cj, year(acq_date) AS y, count(*) AS n
            FROM ({sql}) o GROUP BY ALL""", params).fetchall()
    eset = set(elig)
    cells: dict[tuple[int, int], dict] = {}
    for a, b, y, n in rows:
        c = cells.setdefault((a, b), {"years": set(), "detections": 0})
        if y in eset:
            c["years"].add(y)
            c["detections"] += n
    r = GRID_R[h.grid]
    out = []
    pos = {y: i for i, y in enumerate(elig)}
    for (a, b), c in cells.items():
        ys = sorted(c["years"])
        if not ys:
            continue
        run = best = 1
        for p, q in zip(ys, ys[1:]):
            run = run + 1 if pos[q] == pos[p] + 1 else 1
            best = max(best, run)
        out.append({"ci": a, "cj": b, "lon": round((a + 0.5) * r / 1e5 - 180, 5), "lat": round((b + 0.5) * r / 1e5 - 90, 5),
                    "fire_years": len(ys), "share": round(len(ys) / len(elig), 4), "longest_run": best,
                    "first_year": ys[0], "last_year": ys[-1], "detections": c["detections"],
                    "chronic": len(ys) / len(elig) >= chronic_share})
    out.sort(key=lambda x: (-x["fire_years"], -x["detections"], x["ci"], x["cj"]))
    total = len(out)
    hist = {}
    for x in out:
        hist[x["fire_years"]] = hist.get(x["fire_years"], 0) + 1
    return envelope(h, {"metric": "fire_years", "label": "Years with fire",
                        "definition": "Number of eligible calendar years in which the cell had at least one detection from this sensor series "
                                      "(after the filters). A cell is 'chronic' when that share is at least the chosen share."},
                    available=True, reason=None, series=series, series_label=N.SERIES_LABEL[series], eligible_years=elig,
                    n_eligible_years=len(elig), chronic_share=chronic_share, grid_size=h.grid, cells=out[:limit], cells_total=total,
                    truncated=total > limit, chronic_cells=sum(1 for x in out if x["chronic"]),
                    histogram=[{"fire_years": k, "cells": v} for k, v in sorted(hist.items())],
                    method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER,
                    notes=["Detections in years with less than 80 % known coverage are not counted, so recurrence is not inflated "
                           "or deflated by partial years.",
                           "A cell is a grid square (0.1° ≈ 11 km), not an exact fire location.",
                           "Static industrial sources may remain in the vegetation-fire class (see warnings)."])


# ------------------------------------------------------------------ C1 + C2: critical periods and readiness calendar
def critical(f: Filters, series: str, metric: str = "detections", percentile: float = 90, min_days: int = 3,
             min_activity: float = 1, top: int = 20) -> dict:
    key = cache.make_key("ins_crit", get_revision(), {**f.key(), "series": series, "metric": metric, "p": percentile,
                                                      "min_days": min_days, "min_activity": min_activity, "top": top})
    return cache.get_or_compute(key, lambda: _critical(f, series, metric, percentile, min_days, min_activity, top))


def leave_one_year_out_thresholds(dates: list[date], vals: list[float | None], eligible: set[int], percentile: float,
                                  min_years: int) -> list[float | None]:
    """Per day: the percentile of ALL known daily values of every OTHER complete year (no seasonal window).

    Critical periods mark absolutely high activity (the weeks that keep responders busy). "Unusual for the season"
    is the separate anomaly score. Using all other years (not only earlier ones) gives every year, including the
    first ones, the same kind of reference; the evaluated year never contributes to its own threshold."""
    by_year: dict[int, list[float]] = {y: [] for y in eligible}
    for d, v in zip(dates, vals):
        if d.year in by_year and v is not None:
            by_year[d.year].append(v)
    thr_year: dict[int, float | None] = {}
    out: list[float | None] = []
    for d in dates:
        if d.year not in thr_year:
            others = [y for y in by_year if y != d.year]
            thr_year[d.year] = (float(np.percentile(np.concatenate([np.asarray(by_year[y]) for y in others]), percentile))
                                if len(others) >= min_years else None)
        out.append(thr_year[d.year])
    return out


def _critical(f: Filters, series: str, metric: str, percentile: float, min_days: int, min_activity: float, top: int) -> dict:
    if metric not in ("detections", "cells"):
        raise ValueError("critical periods use detections or occupied cells")
    if not (50 <= percentile <= 99):
        raise ValueError("percentile must be between 50 and 99")
    if not (1 <= min_days <= 30):
        raise ValueError("min_days must be 1–30")
    c = {**CRITICAL_DEFAULTS, "percentile": percentile, "min_days": min_days, "min_activity": min_activity}
    h, dates, vals = _history(f, series, metric)
    years = _year_table(dates, vals)
    elig = {y for y, r in years.items() if r["eligible"]}
    label, unit = METRIC_LABEL[metric]
    mdef = {"metric": metric, "label": label, "unit": unit}
    base = dict(series=series, series_label=N.SERIES_LABEL[series], rule=c, method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER,
                rule_text=(f"A critical period is at least {min_days} consecutive UTC days on which {label.lower()} exceeded the "
                           f"{percentile:g}th percentile of all days in all OTHER complete years, and was ≥ {min_activity:g}. "
                           "It marks absolutely high activity; activity that is unusual for the time of year is the separate anomaly score. "
                           "Days with unknown coverage break a period; they are never bridged. Project setting, not a NASA-validated danger threshold."))
    if len(elig) < MIN_YEARS + 1:
        return envelope(h, mdef, available=False, reason=f"Insufficient history: {len(elig)} complete year(s); at least {MIN_YEARS + 1} are needed "
                        f"so that every year has {MIN_YEARS} other years as its reference.", periods=[], readiness=None, **base)
    thr = leave_one_year_out_thresholds(dates, vals, elig, percentile, c["min_other_years"])
    thr_by_year = {d.year: t for d, t in zip(dates, thr)}
    periods = find_periods(dates, vals, thr, min_days, min_activity)
    for p in periods:
        p["excess"] = round(sum(v - t for v, t in zip(p["values"], p["thresholds"])), 3)
        p["year"] = int(p["start"][:4])
        p["in_complete_year"] = p["year"] in elig
        p["label"] = "Critical period (historical)"
        p["reason"] = (f"{p['duration_days']} consecutive days ({p['start']} to {p['end']}) above "
                       f"{p['thresholds'][0]:g} {unit.split('/')[0]}/day (the {percentile:g}th percentile of all days in other complete years); peak {p['peak']:g} {unit.split('/')[0]} on {p['peak_date']}; "
                       f"{p['excess']:g} above the threshold in total.")
        del p["values"], p["thresholds"]
    ranked = sorted(periods, key=lambda p: -p["excess"])
    for i, p in enumerate(ranked):
        p["rank"] = i + 1
    # C2 readiness calendar over complete years
    crit_days = set()
    for p in periods:
        a, b = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        crit_days.update(a + timedelta(days=k) for k in range((b - a).days + 1))
    ey = sorted(elig)
    weeks = []
    for w in range(N_WEEKS):
        n_known = n_crit = 0
        for y in ey:
            days_w = [d for d in years[y]["days"] if week_bin(d) == w]
            known = [d for d in days_w if years[y]["days"][d] is not None]
            if len(known) >= WEEK_MIN_KNOWN:
                n_known += 1
                if any(d in crit_days for d in days_w):
                    n_crit += 1
        weeks.append({"week": w, "label": week_label(w), "years_known": n_known, "years_critical": n_crit,
                      "share": round(n_crit / n_known, 4) if n_known else None})
    by_year = [{"year": y, "critical_days": sum(1 for d in crit_days if d.year == y),
                "periods": sum(1 for p in periods if p["year"] == y)} for y in ey]
    readiness = {"weeks": weeks, "years": ey, "by_year": by_year,
                 "definition": "For each week of the year: in how many complete years at least one day of that week was inside a critical period. "
                               "A summary of the past, not a prediction for the coming year."}
    return envelope(h, mdef, available=True, reason=None, periods=ranked[:top], periods_total=len(periods), readiness=readiness,
                    thresholds_by_year=[{"year": y, "threshold": t} for y, t in sorted(thr_by_year.items())], **base)


# ------------------------------------------------------------------ B2: robust anomaly score
ANOMALY_FLOOR = {"day": 0.25, "week": 0.25, "cell": 0.5}  # minimum robust scale in log(1 + x) units (documented project setting)
ANOMALY_BANDS = [(3.0, "exceptional"), (2.0, "well above normal"), (1.0, "above normal"), (-1.0, "normal")]


def robust_score(x: float, refs) -> dict:
    """z = (log1p(x) - median(log1p(refs))) / max(1.4826 * MAD, floor). Returns the parts so it can be checked by hand."""
    lr = np.log1p(np.asarray(refs, dtype=float))
    med = float(np.median(lr))
    mad = float(np.median(np.abs(lr - med)))
    return {"log_value": float(np.log1p(x)), "log_median": med, "mad": mad, "scale_raw": 1.4826 * mad}


def _finish(parts: dict, floor: float, x: float, refs) -> dict:
    scale = max(parts["scale_raw"], floor)
    z = (parts["log_value"] - parts["log_median"]) / scale
    band = "below normal" if z <= -1.0 and np.median(refs) > 0 else next((b for t, b in ANOMALY_BANDS if z >= t), "normal")
    return {"value": x, "z": round(float(z), 3), "band": band, "reference_median": float(np.median(refs)), "n_reference": len(refs),
            "scale": scale, "floor_applied": parts["scale_raw"] < floor}


def anomaly(f: Filters, series: str, metric: str = "detections") -> dict:
    key = cache.make_key("ins_anom", get_revision(), {**f.key(), "series": series, "metric": metric})
    return cache.get_or_compute(key, lambda: _anomaly(f, series, metric))


def _anomaly(f: Filters, series: str, metric: str) -> dict:
    if metric not in ("detections", "cells"):
        raise ValueError("the anomaly score uses detections or occupied cells")
    if (f.end - f.start).days > 400:
        raise ValueError("choose a range of at most 400 days to score")
    h, dates, vals = _history(f, series, metric)
    years = _year_table(dates, vals)
    elig = sorted(y for y, r in years.items() if r["eligible"])
    label, unit = METRIC_LABEL[metric]
    by = {d: v for d, v in zip(dates, vals)}
    w = 15  # same ±15-day seasonal window as the existing baseline rule
    days = []
    for d in (f.start + timedelta(days=k) for k in range((f.end - f.start).days + 1)):
        v = by.get(d)
        rec = {"date": d.isoformat(), "value": v, "z": None, "band": None}
        if v is None:
            rec["state"] = "unknown coverage"
        else:
            prior = [y for y in elig if y < d.year]
            refs = []
            used = 0
            for y in prior:
                try:
                    anchor = d.replace(year=y)
                except ValueError:
                    anchor = date(y, 2, 28)
                win = [by.get(anchor + timedelta(days=k)) for k in range(-w, w + 1)]
                known = [x for x in win if x is not None]
                if len(known) >= 0.8 * len(win):
                    used += 1
                    refs.extend(known)
            if used < MIN_YEARS:
                rec["state"] = "insufficient history"
                rec["reference_years"] = used
            else:
                r = _finish(robust_score(v, refs), ANOMALY_FLOOR["day"], v, refs)
                rec.update(r, state="scored", reference_years=used)
        days.append(rec)
    # weekly scores (mean per known day in the week bin vs the same bin in prior complete years)
    wk_cache = {y: _weekly(years[y]["days"]) for y in elig}
    weeks = []
    seen = set()
    for d in (f.start + timedelta(days=k) for k in range((f.end - f.start).days + 1)):
        key = (d.year, week_bin(d))
        if key in seen:
            continue
        seen.add(key)
        y, wb = key
        cur = _weekly(years[y]["days"])[wb] if y in years else None
        rec = {"year": y, "week": wb, "label": week_label(wb), "value": cur, "z": None, "band": None}
        refs = [wk_cache[p][wb] for p in elig if p < y and wk_cache[p][wb] is not None]
        if cur is None:
            rec["state"] = "unknown coverage"
        elif len(refs) < MIN_YEARS:
            rec["state"] = "insufficient history"
        else:
            rec.update(_finish(robust_score(cur, refs), ANOMALY_FLOOR["week"], cur, refs), state="scored")
        weeks.append(rec)
    scored = [x for x in days if x.get("z") is not None]
    summary = {"days": len(days), "scored": len(scored), "unknown": sum(1 for x in days if x["state"] == "unknown coverage"),
               "insufficient": sum(1 for x in days if x["state"] == "insufficient history"),
               "by_band": {b: sum(1 for x in scored if x["band"] == b) for b in ("exceptional", "well above normal", "above normal", "normal", "below normal")},
               "max": max(scored, key=lambda x: x["z"]) if scored else None}
    return envelope(f, {"metric": metric, "label": label, "unit": unit}, series=series, series_label=N.SERIES_LABEL[series],
                    days=days, weeks=weeks, summary=summary, method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER,
                    method={"score": "z = (log(1 + x) − median of log(1 + reference)) / max(1.4826 × MAD, floor)",
                            "reference": f"Daily: known days within ±{w} days of the same date in every EARLIER complete year (≥ 80 % known days in that window); "
                                         f"at least {MIN_YEARS} such years. Weekly: the same week bin in earlier complete years.",
                            "floor": ANOMALY_FLOOR, "bands": "below 1 normal · 1–2 above normal · 2–3 well above normal · 3 or more exceptional · "
                                                             "−1 or less below normal (only when the reference median is above 0)",
                            "why": "Median and MAD are not pulled up by a few extreme years; the log scale keeps quiet and busy seasons comparable. "
                                   "The floor stops near-constant quiet seasons from turning one detection into an extreme score."})


def cell_anomaly(f: Filters, series: str, limit: int = 30000) -> dict:
    key = cache.make_key("ins_cellanom", get_revision(), {**f.key(), "series": series, "limit": limit})
    return cache.get_or_compute(key, lambda: _cell_anomaly(f, series, limit))


def _cell_anomaly(f: Filters, series: str, limit: int) -> dict:
    """Per cell: detections in the selected window vs the same calendar window in every earlier complete year."""
    if (f.end - f.start).days > 92:
        raise ValueError("choose a window of at most 93 days for the anomaly map")
    if f.start.month == 2 and f.start.day == 29 or f.end.month == 2 and f.end.day == 29:
        raise ValueError("choose a window that does not start or end on 29 February")
    h, dates, vals = _history(f, series, "detections")
    years = _year_table(dates, vals)
    span = f.end.year - f.start.year
    ref_years = []
    for y in sorted(years):
        a, b = f.start.replace(year=y - span), f.end.replace(year=y)
        if b >= f.start:
            continue
        ws = [years.get(x.year, {}).get("days", {}).get(x) for x in (a + timedelta(days=k) for k in range((b - a).days + 1))]
        if sum(v is not None for v in ws) >= 0.8 * len(ws) and years.get(y, {}).get("eligible"):
            ref_years.append(y)
    cur_known = [v for d, v in zip(dates, vals) if f.start <= d <= f.end]
    base = dict(series=series, series_label=N.SERIES_LABEL[series], window={"start": f.start.isoformat(), "end": f.end.isoformat()},
                reference_years=ref_years, method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER, grid_size=f.grid)
    if len(ref_years) < MIN_YEARS:
        return envelope(f, {"metric": "detections"}, available=False, cells=[],
                        reason=f"Insufficient history: {len(ref_years)} earlier year(s) with ≥ 80 % known days in this window; {MIN_YEARS} are needed.", **base)
    plats = [p for p in f.platforms if N.PLATFORM_SERIES[p] == series]
    hs = f.model_copy(update={"platforms": plats})
    ci, cj, _ = cell_sql(f.grid)
    parts, params = [], []
    for y in ref_years + [f.end.year]:
        a, b = f.start.replace(year=y - span), f.end.replace(year=y)
        s, p = filtered_sql(hs, a, b)
        parts.append(f"SELECT {ci} AS ci, {cj} AS cj, {y} AS y, count(*) AS n FROM ({s}) o GROUP BY ALL")
        params += p
    with cursor() as cur:
        rows = cur.execute(" UNION ALL ".join(parts), params).fetchall()
    cnt: dict[tuple[int, int], dict[int, int]] = {}
    for a, b, y, n in rows:
        cnt.setdefault((a, b), {})[y] = n
    r = GRID_R[f.grid]
    out = []
    for (a, b), m in cnt.items():
        x = m.get(f.end.year, 0)
        refs = [m.get(y, 0) for y in ref_years]
        res = _finish(robust_score(x, refs), ANOMALY_FLOOR["cell"], x, refs)
        out.append({"ci": a, "cj": b, "lon": round((a + 0.5) * r / 1e5 - 180, 5), "lat": round((b + 0.5) * r / 1e5 - 90, 5),
                    "years_with_fire": sum(1 for v in refs if v > 0), **res})
    out.sort(key=lambda c: (-c["z"], -c["value"]))
    return envelope(f, {"metric": "detections", "label": "Detections in the window", "unit": "detections"}, available=True, reason=None,
                    cells=out[:limit], cells_total=len(out), truncated=len(out) > limit,
                    window_known_days=sum(v is not None for v in cur_known), window_days=(f.end - f.start).days + 1,
                    notes=["Cells with no detections in the window or any reference year are not listed (score undefined, nothing observed).",
                           f"Scale floor {ANOMALY_FLOOR['cell']} in log units for cells, so a cell that never burned needs several detections to score as exceptional.",
                           "Unknown-coverage days in the window lower its counts; their number is reported."], **base)


# ------------------------------------------------------------------ D2 + F2: year report card with climate phases (analog years)
PEAK_MONTHS = (7, 8, 9, 10)


def years_report(f: Filters, series: str, metric: str = "detections") -> dict:
    key = cache.make_key("ins_years", get_revision(), {**f.key(), "series": series, "metric": metric})
    return cache.get_or_compute(key, lambda: _years_report(f, series, metric))


def _years_report(f: Filters, series: str, metric: str) -> dict:
    from . import climate
    if metric not in ("detections", "cells"):
        raise ValueError("the year report uses detections or occupied cells")
    h, dates, vals = _history(f, series, metric)
    years = _year_table(dates, vals)
    crit = critical(f, series, metric)
    crit_by = {r["year"]: r for r in (crit.get("readiness") or {}).get("by_year", [])}
    label, unit = METRIC_LABEL[metric]
    elig = sorted(y for y, r in years.items() if r["eligible"])
    rows = []
    for y in sorted(years):
        r = years[y]
        peak = [v for d, v in r["days"].items() if d.month in PEAK_MONTHS]
        peak_known = sum(1 for v in peak if v is not None)
        ph = climate.season_phase(y)
        rows.append({"year": y, "eligible": r["eligible"], "known_share": round(r["known_share"], 4), "total": r["total"],
                     "peak_season_total": float(sum(v for v in peak if v is not None)), "peak_season_known_days": peak_known,
                     "critical_days": crit_by.get(y, {}).get("critical_days"), "critical_periods": crit_by.get(y, {}).get("periods"),
                     "enso": ph["enso"], "oni": ph["oni"], "iod": ph["iod"], "dmi": ph["dmi"], "is_focus": y == f.end.year})
    er = [r for r in rows if r["eligible"]]
    order = sorted(er, key=lambda r: -r["total"])
    for i, r in enumerate(order):
        r["rank"] = i + 1
        others = [x["total"] for x in er if x["year"] != r["year"]]
        med = float(np.median(others)) if others else None
        r["vs_median_of_other_years"] = round(r["total"] / med, 3) if med else None
    groups = {}
    for dim, keyname in (("enso", ("El Niño", "neutral", "La Niña")), ("iod", ("positive", "neutral", "negative"))):
        g = []
        for k in keyname:
            xs = [r for r in er if r[dim] == k]
            g.append({"phase": k, "n_years": len(xs), "years": [r["year"] for r in xs],
                      "median_total": float(np.median([r["total"] for r in xs])) if xs else None,
                      "median_peak_season": float(np.median([r["peak_season_total"] for r in xs])) if xs else None,
                      "median_critical_days": float(np.median([r["critical_days"] for r in xs if r["critical_days"] is not None])) if any(r["critical_days"] is not None for r in xs) else None,
                      "enough": len(xs) >= 3})
        groups[dim] = g
    focus_phase = climate.season_phase(f.end.year)
    return envelope(h, {"metric": metric, "label": label, "unit": unit}, series=series, series_label=N.SERIES_LABEL[series],
                    years=rows, groups=groups, focus_year=f.end.year, focus_phase=focus_phase, climate_latest=climate.latest(),
                    phase_rules=climate.PHASE_RULES, climate_sources=climate.SOURCES, peak_months=list(PEAK_MONTHS),
                    method_version=INSIGHTS_VERSION, disclaimer=DISCLAIMER,
                    notes=["Analog years show what happened in past seasons with a similar climate background. They are a pattern, "
                           "not a forecast: only a handful of seasons exist per phase, and fire use, land cover and policy also changed.",
                           "Ranks and the comparison with other years use complete years only (≥ 80 % known days).",
                           "Fewer detections can also mean more cloud or smoke, not fewer fires."])


# ------------------------------------------------------------------ F1: AOI comparison
def _area_km2(g) -> float:
    """Approximate area: each polygon scaled by the cosine of its own centroid latitude (good to about 1 % for AOIs of a few degrees)."""
    import shapely
    from shapely.affinity import scale
    total = 0.0
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    for p in parts:
        lat = p.centroid.y
        total += scale(p, xfact=111.320 * np.cos(np.radians(lat)), yfact=110.574, origin=(0, 0)).area
    return float(total)


def compare_aois(f: Filters, aois: list[str], series: str, metric: str = "detections") -> dict:
    from . import aoi as A
    if not (2 <= len(aois) <= 6):
        raise ValueError("compare 2 to 6 areas")
    out = []
    for a in aois:
        g = A.get_geometry(a)
        if g is None:
            raise ValueError("every compared area must be a region or a drawn/uploaded AOI")
        fa = f.model_copy(update={"aoi": a})
        area = _area_km2(g)
        reg = regime(fa, series, metric)
        rec = recurrence(fa, series)
        cri = critical(fa, series, metric)
        row = {"aoi": a, "name": A.describe(a)["name"], "area_km2": round(area, 1), "small_area": area < 1000,
               "regime_available": reg["available"], "reason": reg.get("reason")}
        if reg["available"]:
            v = reg["variability"]
            row.update({"mean_annual": v["mean_annual"], "mean_annual_per_1000km2": v["mean_annual"] / area * 1000 if area else None,
                        "cv": v["cv"], "peak_week": reg["peak_week"]["label"] if reg["peak_week"] else None,
                        "season_peak": (reg["season"].get("peak") or {}).get("median"),
                        "tracker": reg["tracker"]["status"]})
        if rec["available"]:
            row.update({"cells_with_fire": rec["cells_total"], "chronic_cells": rec["chronic_cells"],
                        "chronic_share_of_fire_cells": rec["chronic_cells"] / rec["cells_total"] if rec["cells_total"] else None})
        if cri["available"]:
            by = cri["readiness"]["by_year"]
            row.update({"median_critical_days": float(np.median([x["critical_days"] for x in by])),
                        "critical_threshold_note": "Each area uses its own threshold (its own history), so critical days compare how often an "
                                                   "area exceeds its own high-activity level, not absolute activity."})
        out.append(row)
    return {"series": series, "series_label": N.SERIES_LABEL[series], "metric": metric, "rows": out, "as_of": f.end.isoformat(),
            "method_version": INSIGHTS_VERSION, "disclaimer": DISCLAIMER,
            "notes": ["Detections per 1,000 km² use an approximate area (cosine-latitude scaling).",
                      "Areas under 1,000 km² give noisy numbers and are flagged.",
                      "All areas use the same filters, sensor series and grid."]}


# ------------------------------------------------------------------ E2: hotspot list exports
def hotspot_rows(f: Filters, series: str, top: int = 200) -> list[dict]:
    r = recurrence(f, series)
    rows = []
    for c in r.get("cells", [])[:top]:
        rows.append({"rank": len(rows) + 1, "lat": c["lat"], "lon": c["lon"], "fire_years": c["fire_years"],
                     "years_in_record": r["n_eligible_years"], "share": c["share"], "longest_run": c["longest_run"],
                     "first_year": c["first_year"], "last_year": c["last_year"], "detections": c["detections"], "chronic": c["chronic"]})
    return rows
