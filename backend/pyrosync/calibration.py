"""Applying a fitted MODIS–VIIRS harmonization (added in PyroSync 1.2).

The three stages live in `harmonize.py`. This module takes ONE run of those stages (the "core") and derives,
from exactly the same events, matches and coefficients:

* map windows: per grid cell, the original MODIS and VIIRS detections, the matched pairs (stage 2) and, only when the
  run passes the validity rules, an experimental MODIS-scale estimate computed from the VIIRS observation events;
* a calibration-error map: held-out errors aggregated per region cell, with a minimum sample size;
* time series: original MODIS, original VIIRS and (only when valid) calibrated VIIRS, with a daily-total check on the
  held-out period.

Calibrated values are estimates on the comparison grid. They are never written back to the observations table and never
replace the original data used by the calendar, history, Explore map or Sensor Workbench.
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from . import cache
from . import harmonize as H
from . import query as Q
from .db import get_revision
from .query import Filters

APPLY_VERSION = "pyrosync-calibration-apply-1.0"
EPOCH = date(1970, 1, 1)
CORE_MAX = 3            # cores keep per-event arrays; only a few configurations are held in memory
MAX_PAIRS = 4000        # matched pairs listed per map window
MAX_CELLS = 30000
ERROR_GRIDS = (0.1, 0.25, 0.5, 1.0, 2.0)
MIN_N_CHOICES = (5, 10, 20, 30, 50)

CLS_MATCHED, CLS_PROXY, CLS_NONE = 0, 1, 2

ESTIMATE_DOC = ("Experimental MODIS-scale estimate: for every VIIRS observation event in the cell, M̂ = max(0, exp(α + β ln(1 + V)) − 1) "
                "with the coefficients of this run, summed over the events in the display window. It is an estimate on the comparison grid, "
                "not a hotspot and not a MODIS observation.")
DOMAIN_DOC = {
    "matched": "The model was fitted only on events that BOTH sensors detected (candidate matches). For VIIRS events without a MODIS "
               "partner it predicts what MODIS would have counted had it detected the fire, so summing over all VIIRS events tends to "
               "overstate MODIS-scale totals. Use 'In model domain only' to restrict the estimate to matched events.",
    "matched_plus_proxy": "The model was fitted on candidate matches plus one-sided events with nearby evidence (proxy, unverified). "
                          "VIIRS events without any nearby MODIS evidence are outside that domain.",
}


def _day_index(d: date) -> int:
    return (d - EPOCH).days


def _day(i: int) -> date:
    return EPOCH + timedelta(days=int(i))


@dataclass
class Core:
    report: dict
    cfg: H.HarmonizeConfig
    f: Filters
    valid: bool
    alpha: float | None
    beta: float | None
    split_day: int | None
    train_v_max: float | None
    # per observation event (index = event id - 1)
    sensor: np.ndarray = field(repr=False)      # 0 = MODIS, 1 = VIIRS
    platform: np.ndarray = field(repr=False)
    ci: np.ndarray = field(repr=False)
    cj: np.ndarray = field(repr=False)
    t0: np.ndarray = field(repr=False)          # epoch seconds (UTC) of the first acquisition
    day: np.ndarray = field(repr=False)         # UTC day index of t0
    n: np.ndarray = field(repr=False)           # detections of that platform in the cell during the event
    val: np.ndarray = field(repr=False)         # measurement used by the model (detections or FRP sum)
    cls: np.ndarray = field(repr=False)         # 0 matched, 1 proxy, 2 no evidence
    partner: np.ndarray = field(repr=False)     # index of the matched event of the other sensor, or -1
    dt_min: np.ndarray = field(repr=False)      # |Δt| of the match in minutes, NaN if unmatched
    in_domain: np.ndarray = field(repr=False)   # event class is inside the unit set the model was fitted on
    mhat: np.ndarray | None = field(repr=False)  # calibrated estimate per VIIRS event (NaN for MODIS), None if not applicable
    # model units (for the error map)
    u_ci: np.ndarray = field(repr=False)
    u_cj: np.ndarray = field(repr=False)
    u_M: np.ndarray = field(repr=False)
    u_V: np.ndarray = field(repr=False)
    u_test: np.ndarray = field(repr=False)


_lock = threading.Lock()
_cores: "OrderedDict[str, Core]" = OrderedDict()


def core(f: Filters, cfg: H.HarmonizeConfig) -> Core:
    rev = get_revision()
    key = cache.make_key("hcore", rev, {"f": f.key(), "c": cfg.key()})
    with _lock:
        if key in _cores:
            _cores.move_to_end(key)
            return _cores[key]
    c = _build(f, cfg)
    with _lock:
        _cores[key] = c
        while len(_cores) > CORE_MAX:
            _cores.popitem(last=False)
    return c


def clear() -> None:
    with _lock:
        _cores.clear()


cache._listeners.append(clear)


def _epoch_s(t: datetime) -> float:
    return (t - datetime(1970, 1, 1)).total_seconds() if t.tzinfo is None else t.timestamp()


def _build(f: Filters, cfg: H.HarmonizeConfig) -> Core:
    report, ex = H._run(f, cfg)
    events = ex["events"]
    ne = len(events)
    for i, r in enumerate(events):
        if r[0] != i + 1:  # event ids are row_number() 1..N, ordered by id
            raise RuntimeError("unexpected event numbering")
    sensor = np.fromiter((1 if r[1] == "V" else 0 for r in events), dtype=np.int8, count=ne)
    platform = np.array([r[2] for r in events], dtype=object)
    ci = np.fromiter((r[4] for r in events), dtype=np.int64, count=ne)
    cj = np.fromiter((r[5] for r in events), dtype=np.int64, count=ne)
    t0 = np.fromiter((_epoch_s(r[6]) for r in events), dtype=np.float64, count=ne)
    day = np.floor(t0 / 86400.0).astype(np.int64)
    n = np.fromiter((r[7] for r in events), dtype=np.int64, count=ne)
    frp = np.fromiter((float(r[8] or 0.0) for r in events), dtype=np.float64, count=ne)
    val = n.astype(np.float64) if cfg.metric == "detections" else frp
    proxy = np.fromiter((bool(r[12]) for r in events), dtype=bool, count=ne)
    partner = np.full(ne, -1, dtype=np.int64)
    dt_min = np.full(ne, np.nan)
    for mid, vid, dt, _mt, _vt, _cid in ex["matched"]:
        partner[mid - 1] = vid - 1
        partner[vid - 1] = mid - 1
        dt_min[mid - 1] = dt_min[vid - 1] = dt / 60.0
    cls = np.where(partner >= 0, CLS_MATCHED, np.where(proxy, CLS_PROXY, CLS_NONE)).astype(np.int8)
    in_domain = cls == CLS_MATCHED if cfg.unit_set == "matched" else cls <= CLS_PROXY

    s3 = report["stage3"]
    valid = report["validity"]["status"] == "passes"
    alpha = beta = None
    split_day = None
    train_v_max = None
    if s3["status"] == "ok":
        alpha, beta = s3["fit"]["alpha"], s3["fit"]["beta"]
        split_day = _day_index(date.fromisoformat(s3["split"]["test_starts"]))
    mu = ex["model_units"]
    u_ci = np.fromiter((u["ci"] for u in mu), dtype=np.int64, count=len(mu))
    u_cj = np.fromiter((u["cj"] for u in mu), dtype=np.int64, count=len(mu))
    u_M = np.fromiter((u["M"] for u in mu), dtype=np.float64, count=len(mu))
    u_V = np.fromiter((u["V"] for u in mu), dtype=np.float64, count=len(mu))
    u_test = np.fromiter((u.get("set") == "test" for u in mu), dtype=bool, count=len(mu))
    if s3["status"] == "ok":
        u_train = np.fromiter((u.get("set") == "train" for u in mu), dtype=bool, count=len(mu))
        train_v_max = float(u_V[u_train].max()) if u_train.any() else None
    mhat = None
    if valid:
        mhat = np.full(ne, np.nan)
        vs = sensor == 1
        mhat[vs] = H.predict(alpha, beta, val[vs])
    return Core(report=report, cfg=cfg, f=f, valid=valid, alpha=alpha, beta=beta, split_day=split_day, train_v_max=train_v_max,
                sensor=sensor, platform=platform, ci=ci, cj=cj, t0=t0, day=day, n=n, val=val, cls=cls, partner=partner,
                dt_min=dt_min, in_domain=in_domain, mhat=mhat, u_ci=u_ci, u_cj=u_cj, u_M=u_M, u_V=u_V, u_test=u_test)


# ------------------------------------------------------------------ shared descriptors
def _model_summary(c: Core) -> dict:
    s3 = c.report["stage3"]
    out = {"method_version": c.report["method_version"], "apply_version": APPLY_VERSION, "config": c.cfg.key(),
           "validity": c.report["validity"], "calibrated_available": c.valid, "fit_status": s3["status"],
           "unit_set": c.cfg.unit_set, "domain_doc": DOMAIN_DOC[c.cfg.unit_set], "estimate_doc": ESTIMATE_DOC,
           "grid_deg": c.cfg.unit_grid, "dataset_revision": c.report["dataset_revision"]}
    if s3["status"] == "ok":
        out.update(alpha=c.alpha, beta=c.beta, test_starts=s3["split"]["test_starts"], train_period=s3["split"]["train_period"],
                   test_period=s3["split"]["test_period"], train_v_max=c.train_v_max)
    if not c.valid:
        out["calibrated_unavailable_reason"] = "; ".join(ch["label"] + ": " + ch["value"] for ch in c.report["validity"]["checks"] if not ch["passed"]) \
            or "The model was not fitted."
    return out


def error_grids_for(unit_grid: float) -> list[float]:
    """Region cells for the error map: integer multiples of the comparison grid, so every comparison cell lies in exactly one."""
    out = []
    for g in ERROR_GRIDS:
        k = g / unit_grid
        if g >= unit_grid - 1e-9 and abs(k - round(k)) < 1e-9:
            out.append(g)
    return out


def _agg_factor(c: Core, err_grid: float) -> int:
    grids = error_grids_for(c.cfg.unit_grid)
    for g in grids:
        if abs(g - err_grid) < 1e-9:
            return int(round(g / c.cfg.unit_grid))
    raise ValueError(f"error grid must be one of {', '.join(map(str, grids))} for a {c.cfg.unit_grid}° comparison grid")


# ------------------------------------------------------------------ error map (held-out units only)
def error_cells(c: Core, err_grid: float, min_n: int) -> dict:
    if min_n not in MIN_N_CHOICES:
        raise ValueError(f"min_n must be one of {MIN_N_CHOICES}")
    k = _agg_factor(c, err_grid)
    s3 = c.report["stage3"]
    base = {"error_grid_deg": err_grid, "comparison_grid_deg": c.cfg.unit_grid, "min_n": min_n, "metric": c.cfg.metric,
            "unit": "detections" if c.cfg.metric == "detections" else "MW",
            "definition": "Per region cell: errors of the held-out (later) comparison units whose comparison cell lies in the region cell. "
                          "MAE = mean |prediction − MODIS|. 'validated' = at least min_n held-out units; otherwise the cell is marked "
                          "'too few held-out units'. Cells with VIIRS events but no held-out unit are marked 'no held-out units'. "
                          "Per-cell values from few units are noisy; the threshold is a display rule, not a significance test.",
            "error_grids": error_grids_for(c.cfg.unit_grid), "min_n_choices": list(MIN_N_CHOICES), "model": _model_summary(c)}
    if s3["status"] != "ok":
        return base | {"cells": [], "summary": None}
    a, b = c.alpha, c.beta
    ai, aj = c.u_ci // k, c.u_cj // k
    pred = H.predict(a, b, c.u_V)
    groups: dict[tuple[int, int], list[int]] = {}
    for idx in np.nonzero(c.u_test)[0]:
        groups.setdefault((int(ai[idx]), int(aj[idx])), []).append(int(idx))
    ntrain: dict[tuple[int, int], int] = {}
    for idx in np.nonzero(~c.u_test)[0]:
        key = (int(ai[idx]), int(aj[idx]))
        ntrain[key] = ntrain.get(key, 0) + 1
    cells = []
    for (x, y), ids in groups.items():
        sel = np.array(ids)
        m, v, p = c.u_M[sel], c.u_V[sel], pred[sel]
        e_cal, e_un = p - m, v - m
        mae_c, mae_u = float(np.mean(np.abs(e_cal))), float(np.mean(np.abs(e_un)))
        cells.append({"ci": x, "cj": y, "n_test": len(ids), "n_train": ntrain.get((x, y), 0),
                      "mae_cal": mae_c, "mae_unadj": mae_u, "rmse_cal": float(math.sqrt(np.mean(e_cal ** 2))), "mbe_cal": float(np.mean(e_cal)),
                      "improvement_pct": (100.0 * (mae_u - mae_c) / mae_u) if mae_u > 0 else None,
                      "status": "validated" if len(ids) >= min_n else "too_few"})
    seen = set(groups)
    vsel = c.sensor == 1
    act = set(zip((c.ci[vsel] // k).tolist(), (c.cj[vsel] // k).tolist()))
    for x, y in sorted(act - seen):
        cells.append({"ci": x, "cj": y, "n_test": 0, "n_train": ntrain.get((x, y), 0), "mae_cal": None, "mae_unadj": None, "rmse_cal": None,
                      "mbe_cal": None, "improvement_pct": None, "status": "no_held_out"})
    cells.sort(key=lambda r: (r["cj"], r["ci"]))
    val_cells = [r for r in cells if r["status"] == "validated"]
    n_test_total = int(c.u_test.sum())
    n_in_val = sum(r["n_test"] for r in val_cells)
    summary = {"cells_validated": len(val_cells), "cells_too_few": sum(1 for r in cells if r["status"] == "too_few"),
               "cells_no_held_out": sum(1 for r in cells if r["status"] == "no_held_out"),
               "held_out_units": n_test_total, "held_out_units_in_validated_cells": n_in_val,
               "share_in_validated_cells": (n_in_val / n_test_total) if n_test_total else None,
               "overall_mae_cal": s3["evaluation"]["held_out"]["calibrated"]["mae"],
               "overall_mae_unadj": s3["evaluation"]["held_out"]["unadjusted"]["mae"],
               "validated_cells_mae_cal_range": [min(r["mae_cal"] for r in val_cells), max(r["mae_cal"] for r in val_cells)] if val_cells else None,
               "validated_cells_worse_than_unadjusted": sum(1 for r in val_cells if r["mae_cal"] > r["mae_unadj"])}
    return base | {"cells": cells, "summary": summary}


def _validation_lookup(c: Core, err_grid: float, min_n: int) -> tuple[int, dict]:
    k = _agg_factor(c, err_grid)
    res = error_cells(c, err_grid, min_n)
    return k, {(r["ci"], r["cj"]): r for r in res["cells"]}


# ------------------------------------------------------------------ map window
def map_window(c: Core, day: date, mode: int, scope: str, err_grid: float, min_n: int) -> dict:
    d0, d1 = Q.frame_window(day, mode)
    if scope not in ("all", "domain"):
        raise ValueError("scope must be 'all' or 'domain'")
    i0, i1 = _day_index(d0), _day_index(d1)
    sel = np.nonzero((c.day >= i0) & (c.day <= i1))[0]
    k, vlook = _validation_lookup(c, err_grid, min_n)
    cells: dict[tuple[int, int], dict] = {}
    for idx in sel.tolist():
        key = (int(c.ci[idx]), int(c.cj[idx]))
        r = cells.get(key)
        if r is None:
            r = cells[key] = {"ci": key[0], "cj": key[1], "modis": 0, "viirs": 0, "modis_events": 0, "viirs_events": 0, "pairs": 0,
                              "viirs_events_in_domain": 0, "cal": 0.0 if c.valid else None, "cal_domain": 0.0 if c.valid else None,
                              "extrapolated_events": 0, "_dt": []}
        if c.sensor[idx] == 0:
            r["modis"] += int(c.n[idx]); r["modis_events"] += 1
            if c.partner[idx] >= 0:
                r["pairs"] += 1
                r["_dt"].append(float(c.dt_min[idx]))
        else:
            r["viirs"] += int(c.n[idx]); r["viirs_events"] += 1
            dom = bool(c.in_domain[idx])
            r["viirs_events_in_domain"] += int(dom)
            if c.valid:
                mh = float(c.mhat[idx])
                r["cal"] += mh
                if dom:
                    r["cal_domain"] += mh
                if c.train_v_max is not None and c.val[idx] > c.train_v_max:
                    r["extrapolated_events"] += 1
    out_cells = []
    for r in cells.values():
        dts = r.pop("_dt")
        r["dt_median"] = float(np.median(dts)) if dts else None
        r["value_cal"] = (r["cal"] if scope == "all" else r["cal_domain"]) if c.valid else None
        v = vlook.get((r["ci"] // k, r["cj"] // k))
        r["validation"] = v["status"] if v else "no_held_out"
        r["region_mae"] = v["mae_cal"] if v else None
        r["region_n_test"] = v["n_test"] if v else 0
        out_cells.append(r)
    out_cells.sort(key=lambda r: (r["cj"], r["ci"]))
    truncated = len(out_cells) > MAX_CELLS
    # matched pairs whose MODIS event falls in the window (the unit date of a match is the MODIS event day)
    msel = sel[(c.sensor[sel] == 0) & (c.partner[sel] >= 0)]
    pairs = []
    for idx in msel[np.argsort(c.t0[msel], kind="stable")].tolist()[:MAX_PAIRS]:
        p = int(c.partner[idx])
        pairs.append({"ci": int(c.ci[idx]), "cj": int(c.cj[idx]), "modis_platform": str(c.platform[idx]),
                      "t_modis": _iso(c.t0[idx]), "t_viirs": _iso(c.t0[p]), "dt_min": float(c.dt_min[idx]),
                      "M": float(c.val[idx]), "V": float(c.val[p]),
                      "M_hat": float(H.predict(c.alpha, c.beta, np.array([c.val[p]]))[0]) if c.alpha is not None else None,
                      "set": None if c.split_day is None else ("test" if int(c.day[idx]) >= c.split_day else "train")})
    role = None
    if c.split_day is not None:
        role = "held_out" if i0 >= c.split_day else ("training" if i1 < c.split_day else "mixed")
    vs = [r for r in out_cells if r["viirs_events"] > 0]
    totals = {"modis": sum(r["modis"] for r in out_cells), "viirs": sum(r["viirs"] for r in out_cells),
              "modis_events": sum(r["modis_events"] for r in out_cells), "viirs_events": sum(r["viirs_events"] for r in out_cells),
              "pairs": int(len(msel)), "cells": len(out_cells),
              "cal": sum(r["cal"] for r in vs) if c.valid else None, "cal_domain": sum(r["cal_domain"] for r in vs) if c.valid else None,
              "cells_viirs": len(vs), "cells_viirs_validated": sum(1 for r in vs if r["validation"] == "validated")}
    return {"window": {"date": day.isoformat(), "mode_days": mode, "start": d0.isoformat(), "end": d1.isoformat(),
                       "utc_interval": [f"{d0.isoformat()}T00:00Z", f"{(d1 + timedelta(days=1)).isoformat()}T00:00Z"],
                       "period_role": role,
                       "period_role_doc": {"held_out": "Whole window in the held-out period: the model never saw these units.",
                                           "training": "Window in the training period: calibrated values here are in-sample.",
                                           "mixed": "Window spans the split date (part in-sample, part held out)."}.get(role or "", None)},
            "scope": scope, "error_grid_deg": err_grid, "min_n": min_n, "cells": out_cells[:MAX_CELLS], "truncated": truncated,
            "pairs": pairs, "pairs_truncated": len(msel) > MAX_PAIRS, "totals": totals, "model": _model_summary(c),
            "event_day_rule": "Each observation event is assigned to the UTC day of its first acquisition; a match is shown on its MODIS event day.",
            "modis_label": "MODIS " + " + ".join(c.cfg.modis_platforms), "viirs_label": H.N.SERIES_LABEL.get(c.cfg.viirs_series, c.cfg.viirs_series)}


def _iso(ts: float) -> str:
    return (datetime(1970, 1, 1) + timedelta(seconds=float(ts))).strftime("%Y-%m-%dT%H:%MZ")


def suggested_days(c: Core, top: int = 6) -> dict:
    """Days with the most matched pairs, separately for the training and the held-out period (navigation aid)."""
    m = (c.sensor == 0) & (c.partner >= 0)
    days = c.day[m]
    out: dict = {"training": [], "held_out": []}
    if not len(days):
        return out
    u, cnt = np.unique(days, return_counts=True)
    order = np.lexsort((u, -cnt))
    for i in order.tolist():
        role = "held_out" if c.split_day is not None and u[i] >= c.split_day else "training"
        if len(out[role]) < top:
            out[role].append({"date": _day(u[i]).isoformat(), "pairs": int(cnt[i])})
    return out


# ------------------------------------------------------------------ time series
def series(c: Core, agg: str, scope: str) -> dict:
    if agg not in ("day", "month"):
        raise ValueError("agg must be 'day' or 'month'")
    if scope not in ("all", "domain"):
        raise ValueError("scope must be 'all' or 'domain'")
    f = c.f
    ff = H._sensor_filters(f, c.cfg)
    daily = Q.daily(ff)  # same filters and platforms; supplies the coverage state of every day
    vs = c.cfg.viirs_series
    st_m = daily["series"]["MODIS"]["status"] if "MODIS" in daily["series"] else None
    st_v = daily["series"][vs]["status"] if vs in daily["series"] else None
    nd = (f.end - f.start).days + 1
    i0 = _day_index(f.start)
    off = c.day - i0
    ok = (off >= 0) & (off < nd)
    msk_m, msk_v = ok & (c.sensor == 0), ok & (c.sensor == 1)
    mod = np.bincount(off[msk_m], weights=c.n[msk_m].astype(float), minlength=nd)
    vir = np.bincount(off[msk_v], weights=c.n[msk_v].astype(float), minlength=nd)
    cal = None
    if c.valid:
        msk_c = msk_v & (c.in_domain if scope == "domain" else True)
        cal = np.bincount(off[msk_c], weights=c.mhat[msk_c], minlength=nd)
    known_m = np.array([s in ("detections", "zero_reported") for s in st_m]) if st_m else np.zeros(nd, bool)
    known_v = np.array([s in ("detections", "zero_reported") for s in st_v]) if st_v else np.zeros(nd, bool)
    # consistency guard: the event sums must equal the per-sensor daily detections of the same filters
    if st_m is not None and "MODIS" in daily["series"]:
        dm = np.array(daily["series"]["MODIS"]["detections"], dtype=float)
        if not np.array_equal(dm, mod):
            raise RuntimeError("calibration series: MODIS event sums differ from daily detections")
    if st_v is not None:
        dv = np.array(daily["series"][vs]["detections"], dtype=float)
        if not np.array_equal(dv, vir):
            raise RuntimeError("calibration series: VIIRS event sums differ from daily detections")
    dates = [f.start + timedelta(days=i) for i in range(nd)]
    split = None if c.split_day is None else _day(c.split_day)
    check = _daily_total_check(dates, mod, vir, cal, known_m & known_v, split) if c.valid else None
    tv = totals_validity(c, check, scope)
    if not tv["status"] == "passes":
        cal = None  # calibrated totals are only shown when they passed the held-out daily-total rules
    if agg == "day":
        rows = {"dates": [d.isoformat() for d in dates],
                "modis": [float(mod[i]) if known_m[i] else None for i in range(nd)],
                "viirs": [float(vir[i]) if known_v[i] else None for i in range(nd)],
                "calibrated": [float(cal[i]) if known_v[i] else None for i in range(nd)] if cal is not None else None,
                "known_days": None}
    else:
        both = known_m & known_v
        keys: dict[tuple[int, int], list[int]] = {}
        for i, d in enumerate(dates):
            keys.setdefault((d.year, d.month), []).append(i)
        rows = {"dates": [], "modis": [], "viirs": [], "calibrated": [] if cal is not None else None, "known_days": [], "days": []}
        for (y, m), idxs in keys.items():
            ix = [i for i in idxs if both[i]]
            rows["dates"].append(f"{y:04d}-{m:02d}")
            rows["known_days"].append(len(ix))
            rows["days"].append(len(idxs))
            rows["modis"].append(float(mod[ix].sum()) if ix else None)
            rows["viirs"].append(float(vir[ix].sum()) if ix else None)
            if cal is not None:
                rows["calibrated"].append(float(cal[ix].sum()) if ix else None)
    return {"agg": agg, "scope": scope, "model": _model_summary(c), "check": check, "totals_validity": tv, **rows,
            "modis_label": "MODIS " + " + ".join(c.cfg.modis_platforms) + " (observed)",
            "viirs_label": H.N.SERIES_LABEL.get(vs, vs) + " (original)",
            "calibrated_label": H.N.SERIES_LABEL.get(vs, vs) + " calibrated to MODIS scale (experimental)",
            "notes": [
                "Original values are the detections of the selected platforms after the shared filters; they equal the per-sensor daily series of the app.",
                "Days whose coverage state is unknown are left empty (not zero). Monthly sums use only days on which both sensors have a known state; "
                "'known_days' gives their number.",
                "Calibrated values are estimates computed from VIIRS events with this run's coefficients. Before the held-out period they are in-sample. "
                "They are drawn only when the run passes both the unit-level rules and the held-out daily-total rules.",
                "The calendar, history and Explore pages keep using original observations.",
            ]}


TOTALS_MIN_DAYS = 30
TOTALS_RATIO_RANGE = (0.8, 1.25)


def totals_validity(c: Core, check: dict | None, scope: str) -> dict:
    """Second gate (v1.2) for time series: unit-level validity does not imply that SUMS of estimates reproduce MODIS-scale totals."""
    checks = [{"id": "unit_level", "label": "Unit-level validation passed", "passed": c.valid,
               "value": c.report["validity"]["status"], "rule": "The run passes the unit-level validity rules (see validation status)."}]
    h = (check or {}).get("held_out")
    if c.valid and h:
        t = h.get("constant_reference")
        lo, hi = TOTALS_RATIO_RANGE
        r = h["ratio_calibrated_to_modis"]
        checks += [
            {"id": "days", "label": "Enough held-out days", "passed": h["days"] >= TOTALS_MIN_DAYS, "value": f"{h['days']:,} days",
             "rule": f"At least {TOTALS_MIN_DAYS} held-out days on which both sensors have a known coverage state."},
            {"id": "level", "label": "Total level close to MODIS", "passed": r is not None and lo <= r <= hi,
             "value": "—" if r is None else f"Σ calibrated / Σ MODIS = {r:.2f}",
             "rule": f"Over the held-out days the summed estimate is between {lo:g}× and {hi:g}× the summed MODIS detections."},
            {"id": "beats_unadjusted", "label": "Daily totals better than unadjusted VIIRS",
             "passed": h["calibrated"]["mae"] < h["unadjusted"]["mae"] and h["calibrated"]["rmse"] < h["unadjusted"]["rmse"],
             "value": f"MAE {h['calibrated']['mae']:.1f} vs {h['unadjusted']['mae']:.1f}", "rule": "Held-out daily-total MAE and RMSE below the raw VIIRS totals."},
            {"id": "beats_constant", "label": "Daily totals better than a constant",
             "passed": t is not None and h["calibrated"]["mae"] < t["mae"] and h["calibrated"]["rmse"] < t["rmse"],
             "value": "—" if t is None else f"MAE {h['calibrated']['mae']:.1f} vs {t['mae']:.1f}",
             "rule": "Held-out daily-total MAE and RMSE below a constant equal to the training-period mean daily MODIS total."},
        ]
    passed = len(checks) == 5 and all(ch["passed"] for ch in checks)
    return {"status": "passes" if passed else "not_validated", "scope": scope, "checks": checks,
            "label": "Calibrated totals pass the held-out daily-total rules" if passed
            else "Calibrated totals are not validated for this configuration: the calibrated line is not drawn",
            "note": "Unit-level results describe matched comparison units; a time series sums estimates over all events in the AOI, "
                    "including events the model was not fitted on, so it needs its own check."}


def _daily_total_check(dates, mod, vir, cal, both, split) -> dict:
    """Compares DAILY AOI TOTALS (all events, not only matched units) on days where both sensors have a known state."""
    out = {}
    for name, sel in (("held_out", [i for i, d in enumerate(dates) if both[i] and split is not None and d >= split]),
                      ("training", [i for i, d in enumerate(dates) if both[i] and split is not None and d < split])):
        if not sel:
            out[name] = None
            continue
        ix = np.array(sel)
        m, v, cc = mod[ix], vir[ix], cal[ix]
        um, cm = H.error_metrics(v, m), H.error_metrics(cc, m)
        out[name] = {"days": len(sel), "first": dates[sel[0]].isoformat(), "last": dates[sel[-1]].isoformat(),
                     "sum_modis": float(m.sum()), "sum_viirs": float(v.sum()), "sum_calibrated": float(cc.sum()),
                     "ratio_viirs_to_modis": float(v.sum() / m.sum()) if m.sum() > 0 else None,
                     "ratio_calibrated_to_modis": float(cc.sum() / m.sum()) if m.sum() > 0 else None,
                     "unadjusted": um, "calibrated": cm, "improvement_vs_unadjusted": H.improvement(um, cm)}
    tr, ho = out.get("training"), out.get("held_out")
    if tr and ho:
        ix = np.array([i for i, d in enumerate(dates) if both[i] and d >= split])
        const = tr["sum_modis"] / tr["days"]
        ho["constant_reference"] = H.error_metrics(np.full(len(ix), const), mod[ix]) | {"value": const}
    out["definition"] = ("Daily totals over the AOI on days where both sensors have a known coverage state. Unlike the unit-level evaluation, "
                         "these totals include VIIRS-only and MODIS-only events, so they show whether the estimate reproduces MODIS-scale "
                         "activity levels, not only matched pairs.")
    return out
