"""Exploratory comparison of daily-total calibration options (planning prototype, not project code).

Run from backend/: PYROSYNC_DATA_DIR=/home/user/fulldata ../.venv/bin/python proto.py OUT.json
"""
import json
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, "/home/user/pyrosync/backend")
from pyrosync import harmonize as H  # noqa: E402
from pyrosync import query as Q  # noqa: E402

out_path = sys.argv[1]
types = sys.argv[2].split(",") if len(sys.argv) > 2 else ["0"]
aoi = sys.argv[3] if len(sys.argv) > 3 else "none"
viirs = sys.argv[4] if len(sys.argv) > 4 else "VIIRS_SNPP"
start = date(2012, 1, 20) if viirs == "VIIRS_SNPP" else date(2018, 4, 1)
tol = 30 if viirs == "VIIRS_SNPP" else 60
f = Q.Filters(start=start, end=date(2026, 11, 14), aoi=aoi, types=types)
cfg = H.HarmonizeConfig(viirs_series=viirs, modis_platforms=["Aqua"], tolerance_min=tol)
rep, ex = H._run(f, cfg)
ev = ex["events"]
ne = len(ev)
sensor = np.array([1 if r[1] == "V" else 0 for r in ev])
cid = np.array([r[3] for r in ev])
day0 = start.toordinal()
day = np.array([r[6].date().toordinal() - day0 for r in ev])
n = np.array([r[7] for r in ev], dtype=float)
proxy = np.array([bool(r[12]) for r in ev])
hour = np.array([r[6].hour for r in ev])
partner = np.full(ne, -1)
for mid, vid, *_ in ex["matched"]:
    partner[mid - 1] = vid - 1
    partner[vid - 1] = mid - 1
nd = (f.end - f.start).days + 1
dates = [f.start + timedelta(days=i) for i in range(nd)]

# daily known-coverage mask from the app's own daily series
ff = H._sensor_filters(f, cfg)
dl = Q.daily(ff)
km = np.array([s in ("detections", "zero_reported") for s in dl["series"]["MODIS"]["status"]])
kv = np.array([s in ("detections", "zero_reported") for s in dl["series"][viirs]["status"]])
known = km & kv

M = np.bincount(day[sensor == 0], weights=n[sensor == 0], minlength=nd)
V = np.bincount(day[sensor == 1], weights=n[sensor == 1], minlength=nd)
# occupied cells per day (0.1 deg)
def cells(sel):
    d = day[sel]; c = cid[sel]
    k = np.unique(d * 10**9 + c)
    return np.bincount(k // 10**9, minlength=nd).astype(float)
Mc, Vc = cells(sensor == 0), cells(sensor == 1)
vmask = sensor == 1
matched_v = vmask & (partner >= 0)
Mm = np.zeros(nd);
mm_idx = partner[matched_v]
np.add.at(Mm, day[matched_v], n[mm_idx])


def metrics(p, o):
    e = p - o
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e**2))), "mbe": float(np.mean(e)),
            "ratio": float(p.sum() / o.sum()) if o.sum() > 0 else None, "days": int(len(o))}


def loglog(x, y):
    X = np.log1p(x); Y = np.log1p(y)
    b, a = np.polyfit(X, Y, 1)
    res = Y - (a + b * X)
    return a, b, float(np.mean(np.exp(res)))


def fold(train_days, test_days):
    """train_days/test_days: boolean masks over days (already & known)."""
    tr_ev = np.isin(day, np.where(train_days)[0])
    o = M[test_days]
    out = {}
    out["raw_viirs"] = metrics(V[test_days], o)
    out["constant_train_mean"] = metrics(np.full(test_days.sum(), M[train_days].mean()), o)
    # existing event model refitted on matched training units
    tv = matched_v & tr_ev
    a, b, smear = loglog(n[tv], n[partner[tv]])
    mh = np.maximum(0, np.exp(a + b * np.log1p(n)) - 1)
    cal_all = np.bincount(day[vmask], weights=mh[vmask], minlength=nd)
    cal_dom = np.bincount(day[matched_v], weights=mh[matched_v], minlength=nd)
    out["event_loglog_all_viirs"] = metrics(cal_all[test_days], o)
    out["event_loglog_matched_only"] = metrics(cal_dom[test_days], o)
    out["_event_coef"] = {"alpha": a, "beta": b, "smear": smear}
    # day-level ratio
    c = M[train_days].sum() / V[train_days].sum()
    out["day_ratio"] = metrics(c * V[test_days], o) | {"c": float(c)}
    # day-level ratio by month of year (seasonal)
    mon = np.array([d.month for d in dates])
    cm = {m_: M[train_days & (mon == m_)].sum() / max(V[train_days & (mon == m_)].sum(), 1) for m_ in range(1, 13)}
    out["day_ratio_by_month"] = metrics(np.array([cm[m_] for m_ in mon[test_days]]) * V[test_days], o)
    # day-level log-log with smearing
    a2, b2, s2 = loglog(V[train_days], M[train_days])
    p2 = np.maximum(0, s2 * np.exp(a2 + b2 * np.log1p(V[test_days])) - 1)
    out["day_loglog_smeared"] = metrics(p2, o) | {"alpha": a2, "beta": b2, "smear": s2}
    # day-level power law fitted on totals by least squares in log space without smearing
    p2b = np.maximum(0, np.exp(a2 + b2 * np.log1p(V[test_days])) - 1)
    out["day_loglog_unsmeared"] = metrics(p2b, o)
    # two-part: P(matched | VIIRS event) by bins of event size x proxy flag, times E[M | matched] (smeared event model),
    # plus MODIS-only detections modelled as a training share of the matched MODIS total.
    sz = np.minimum(np.log2(n).astype(int), 6)
    key = sz * 2 + proxy.astype(int)
    vtr = vmask & tr_ev
    pm = {}
    for k in np.unique(key[vmask]):
        s = vtr & (key == k)
        pm[k] = (partner[s] >= 0).mean() if s.sum() > 0 else 0.0
    pv = np.array([pm.get(k, 0.0) for k in key])
    e2 = pv * smear * np.exp(a + b * np.log1p(n)) - pv * 1.0  # E[M|matched] ~ smear*exp(..)-1
    e2 = np.maximum(e2, 0)
    tp = np.bincount(day[vmask], weights=e2[vmask], minlength=nd)
    mo = (sensor == 0) & (partner < 0)
    Mo = np.bincount(day[mo], weights=n[mo], minlength=nd)
    share = Mo[train_days].sum() / max(Mm[train_days].sum(), 1)
    out["two_part_plus_modis_only_share"] = metrics(tp[test_days] * (1 + share), o) | {"modis_only_share": float(share)}
    out["two_part_matched_component_only"] = metrics(tp[test_days], o)
    # occupied cells (a different metric: compare MODIS cells)
    oc = Mc[test_days]
    out["cells_raw_viirs_vs_modis_cells"] = metrics(Vc[test_days], oc)
    cc = Mc[train_days].sum() / Vc[train_days].sum()
    out["cells_ratio"] = metrics(cc * Vc[test_days], oc) | {"c": float(cc)}
    out["cells_constant"] = metrics(np.full(test_days.sum(), Mc[train_days].mean()), oc)
    a3, b3, s3 = loglog(Vc[train_days], Mc[train_days])
    out["cells_loglog_smeared"] = metrics(np.maximum(0, s3 * np.exp(a3 + b3 * np.log1p(Vc[test_days])) - 1), oc)
    # monthly totals for main methods
    def monthly(p_all, obs_all):
        keys = {}
        for i in np.where(test_days)[0]:
            keys.setdefault((dates[i].year, dates[i].month), []).append(i)
        pp = np.array([p_all[ix].sum() for ix in keys.values()]); oo = np.array([obs_all[ix].sum() for ix in keys.values()])
        return metrics(pp, oo) | {"months": len(keys)}
    full_ratio = c * V
    full_ll = np.maximum(0, s2 * np.exp(a2 + b2 * np.log1p(V)) - 1)
    out["monthly"] = {"raw_viirs": monthly(V, M), "event_loglog_all_viirs": monthly(cal_all, M), "day_ratio": monthly(full_ratio, M),
                      "day_loglog_smeared": monthly(full_ll, M), "two_part_plus_share": monthly(tp * (1 + share), M),
                      "cells_ratio": monthly(cc * Vc, Mc)}
    # high / low activity split of test days by observed MODIS (median of training)
    thr = np.percentile(M[train_days], 90)
    hi = M[test_days] >= thr
    out["high_activity_days"] = {"threshold": float(thr), "days": int(hi.sum()),
                                 "day_ratio": metrics((c * V[test_days])[hi], o[hi]) if hi.any() else None,
                                 "day_loglog_smeared": metrics(p2[hi], o[hi]) if hi.any() else None,
                                 "event_loglog_all_viirs": metrics(cal_all[test_days][hi], o[hi]) if hi.any() else None,
                                 "raw_viirs": metrics(V[test_days][hi], o[hi]) if hi.any() else None}
    out["low_activity_days"] = {"days": int((~hi).sum()),
                                "day_ratio": metrics((c * V[test_days])[~hi], o[~hi]),
                                "day_loglog_smeared": metrics(p2[~hi], o[~hi]),
                                "event_loglog_all_viirs": metrics(cal_all[test_days][~hi], o[~hi])}
    return out


res = {"config": {"types": types, "aoi": aoi, "viirs": viirs, "start": str(start)}, "class_counts": rep["stage2"]["class_counts"],
       "known_days": int(known.sum()), "days": nd}
didx = np.arange(nd)
split = date(2019, 9, 22) if viirs == "VIIRS_SNPP" else date(2023, 9, 21)
s = (split - f.start).days
res["single_split"] = {"split": str(split)} | fold(known & (didx < s), known & (didx >= s))
# rolling origin by calendar year
roll = {}
first_test = 2015 if viirs == "VIIRS_SNPP" else 2020
for y in range(first_test, 2027):
    a_ = (date(y, 1, 1) - f.start).days
    b_ = (date(y + 1, 1, 1) - f.start).days
    tr = known & (didx < a_); te = known & (didx >= a_) & (didx < b_)
    if te.sum() < 30:
        continue
    r = fold(tr, te)
    roll[y] = {k: (v if k.startswith("_") else {kk: vv for kk, vv in v.items() if kk in ("mae", "rmse", "mbe", "ratio", "days")})
               for k, v in r.items() if k not in ("monthly", "high_activity_days", "low_activity_days")}
res["rolling_origin"] = roll
# coverage fraction of VIIRS detections that are in matched / proxy / none events
res["viirs_detection_share"] = {"matched": float(n[matched_v].sum() / n[vmask].sum()),
                                "proxy_unmatched": float(n[vmask & (partner < 0) & proxy].sum() / n[vmask].sum()),
                                "no_evidence": float(n[vmask & (partner < 0) & ~proxy].sum() / n[vmask].sum())}
res["modis_detection_share"] = {"matched": float(n[(sensor == 0) & (partner >= 0)].sum() / n[sensor == 0].sum())}
json.dump(res, open(out_path, "w"), indent=1, default=float)
print("ok", out_path)
