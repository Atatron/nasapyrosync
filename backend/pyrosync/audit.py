"""Reproducible audit of the harmonization method and its application (added in PyroSync 1.2).

    python -m pyrosync.cli harmonize-audit --out ../docs/harmonization/AUDIT

For each configuration the audit re-runs the three stages and checks, with code that is independent of the
functions under test where possible:

1. temporal matching: one-to-one use of events, |Δt| within tolerance, ambiguity (candidate pairs vs matches),
   distribution of |Δt|;
2. coverage limits: share of events without a partner and how many of those have only proxy evidence;
3. data leakage: training dates strictly before held-out dates, no day on both sides, coefficients unchanged when
   all data after the split are removed, sensitivity to an embargo after the split date;
4. metrics: MAE / RMSE / MBE recomputed with plain Python from the units and compared with the report;
5. simple alternatives: training mean, training median and a ratio model (Σ M / Σ V) on the held-out units;
6. application: validity status, error-map summary and the held-out daily-total check.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import calibration as C
from . import harmonize as H
from .query import Filters

RUNS = [
    ("A", "Indonesia, Aqua–S-NPP, ±30 min, 0.1°, detections", dict(start="2012-01-20", end="2026-11-14"), dict()),
    ("B", "as A, matched + proxy one-sided units", dict(start="2012-01-20", end="2026-11-14"), dict(unit_set="matched_plus_proxy")),
    ("C", "Indonesia, Aqua–NOAA-20, ±60 min", dict(start="2018-04-01", end="2026-11-14"), dict(viirs_series="VIIRS_N20", tolerance_min=60)),
    ("D", "Kalimantan, Aqua–S-NPP (the online demo region)", dict(start="2012-01-20", end="2026-11-14", aoi="region:kalimantan"), dict()),
    ("E", "as A, FRP sum (MW)", dict(start="2012-01-20", end="2026-11-14"), dict(metric="frp_sum")),
]


def _plain_metrics(pred: list[float], obs: list[float]) -> dict:
    n = len(obs)
    e = [p - o for p, o in zip(pred, obs)]
    return {"mae": sum(abs(x) for x in e) / n, "rmse": math.sqrt(sum(x * x for x in e) / n), "mbe": sum(e) / n}


def audit_run(f: Filters, cfg: H.HarmonizeConfig) -> dict:
    t0 = time.time()
    rep, ex = H._run(f, cfg)
    out: dict = {"config": cfg.key(), "filters": f.key(), "seconds": None}
    s2, s3 = rep["stage2"], rep["stage3"]
    matched = ex["matched"]
    # ---- 1. temporal matching
    mids = [m[0] for m in matched]
    vids = [m[1] for m in matched]
    dts = np.array([m[2] / 60.0 for m in matched]) if matched else np.array([])
    out["matching"] = {
        "matched": len(matched), "candidate_pairs": s2["candidate_pairs"],
        "ambiguous_candidates": s2["candidate_pairs"] - len(matched),
        "one_to_one": len(set(mids)) == len(mids) and len(set(vids)) == len(vids),
        "max_dt_within_tolerance": bool(len(dts) == 0 or dts.max() <= cfg.tolerance_min + 1e-9),
        "dt_percentiles_min": {str(q): float(np.percentile(dts, q)) for q in (10, 25, 50, 75, 90, 99)} if len(dts) else None,
        "share_dt_at_least_two_thirds_tolerance": float((dts >= 2 * cfg.tolerance_min / 3).mean()) if len(dts) else None,
    }
    # ---- 2. coverage limits
    cc = s2["class_counts"]
    nv = s2["events"]["viirs"]
    nm = s2["events"]["modis"]
    out["coverage"] = {
        "viirs_events": nv, "modis_events": nm,
        "viirs_matched_share": cc["matched"] / nv if nv else None, "modis_matched_share": cc["matched"] / nm if nm else None,
        "viirs_unmatched_proxy_share": cc["viirs_only_proxy"] / nv if nv else None,
        "viirs_unmatched_no_evidence_share": cc["viirs_only_no_evidence"] / nv if nv else None,
        "status": s2["coverage_verification"]["status"],
    }
    out["validity"] = rep["validity"]
    if s3["status"] != "ok":
        out["stage3_status"] = s3["status"]
        out["seconds"] = round(time.time() - t0, 1)
        return out
    units = ex["model_units"]
    split = date.fromisoformat(s3["split"]["test_starts"])
    train = [u for u in units if u["set"] == "train"]
    test = [u for u in units if u["set"] == "test"]
    # ---- 3. leakage
    tr_days = {u["date"] for u in train}
    te_days = {u["date"] for u in test}
    fit = s3["fit"]
    f_trunc = f.model_copy(update={"end": split - timedelta(days=1)})
    rep2, ex2 = H._run(f_trunc, cfg.model_copy(update={"split_date": None}))
    tr2 = ex2["model_units"]
    fit2 = H.fit_loglog(np.array([u["V"] for u in tr2]), np.array([u["M"] for u in tr2])) if len(tr2) >= 3 else None
    a, b = fit["alpha"], fit["beta"]
    emb = {}
    for days in (0, 30, 90, 365):
        sel = [u for u in test if u["date"] >= split + timedelta(days=days)]
        if sel:
            p = H.predict(a, b, np.array([u["V"] for u in sel])).tolist()
            o = [u["M"] for u in sel]
            emb[str(days)] = {"n": len(sel), "calibrated": _plain_metrics(p, o), "unadjusted": _plain_metrics([u["V"] for u in sel], o)}
    out["leakage"] = {
        "train_before_test": max(tr_days) < min(te_days) if tr_days and te_days else None,
        "days_on_both_sides": len(tr_days & te_days),
        "split": split.isoformat(),
        "refit_without_later_data": None if fit2 is None else {
            "n_units": fit2["n"], "n_train_in_full_run": len(train), "alpha": fit2["alpha"], "beta": fit2["beta"],
            "alpha_full": a, "beta_full": b, "max_abs_coefficient_difference": max(abs(fit2["alpha"] - a), abs(fit2["beta"] - b))},
        "embargo_after_split": emb,
        "constants_fitted_on": "training units only (see harmonize._calibrate)",
        "smearing_applied": False,
    }
    # ---- 4. metrics recomputed independently
    obs = [u["M"] for u in test]
    pred = H.predict(a, b, np.array([u["V"] for u in test])).tolist()
    ho = s3["evaluation"]["held_out"]
    plain = {"calibrated": _plain_metrics(pred, obs), "unadjusted": _plain_metrics([u["V"] for u in test], obs)}
    out["metrics"] = {"report": {"calibrated": ho["calibrated"], "unadjusted": ho["unadjusted"]}, "recomputed": plain,
                      "max_abs_difference": max(abs(plain[k][m] - ho[k][m]) for k in plain for m in ("mae", "rmse", "mbe"))}
    # ---- 5. simple alternatives on the held-out units
    mtr = [u["M"] for u in train]
    vtr = [u["V"] for u in train]
    ratio = sum(mtr) / sum(vtr) if sum(vtr) > 0 else None
    alts = {"calibrated": plain["calibrated"], "unadjusted": plain["unadjusted"],
            "training_mean": _plain_metrics([sum(mtr) / len(mtr)] * len(obs), obs),
            "training_median": _plain_metrics([float(np.median(mtr))] * len(obs), obs)}
    if ratio is not None:
        alts["ratio_model"] = _plain_metrics([ratio * u["V"] for u in test], obs) | {"ratio": ratio}
    out["alternatives"] = alts
    # ---- 6. application
    core = C.core(f, cfg)
    e = C.error_cells(core, max(0.5, cfg.unit_grid), 20)
    out["error_map_0.5deg_n20"] = e["summary"]
    if core.valid:
        out["daily_totals"] = {sc: {"check": (srs := C.series(core, "day", sc))["check"], "totals_validity": srs["totals_validity"]} for sc in ("domain", "all")}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def run_audit(out_dir: Path, only: list[str] | None = None) -> dict:
    res = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "method_version": H.METHOD_VERSION,
           "validity_rules": H.VALIDITY_RULES_VERSION, "apply_version": C.APPLY_VERSION, "runs": {}}
    for rid, label, fk, ck in RUNS:
        if only and rid not in only:
            continue
        f = Filters(start=date.fromisoformat(fk["start"]), end=date.fromisoformat(fk["end"]), aoi=fk.get("aoi", "none"))
        cfg = H.HarmonizeConfig(**ck)
        r = audit_run(f, cfg)
        r["label"] = label
        res["runs"][rid] = r
        C.clear()
        print(f"audit {rid} done in {r['seconds']} s", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    (out_dir / "AUDIT.md").write_text(audit_markdown(res), encoding="utf-8")
    return res


def _f(x, nd=3):
    return "—" if x is None else f"{x:,.{nd}f}"


def _p(x):
    return "—" if x is None else f"{100 * x:.1f} %"


def audit_markdown(res: dict) -> str:
    L = ["# Harmonization audit (generated)", "",
         f"Generated {res['generated_utc']} UTC by `python -m pyrosync.cli harmonize-audit` ({res['method_version']}, {res['validity_rules']}, "
         f"{res['apply_version']}). Every number is computed from the imported data by `backend/pyrosync/audit.py`.", ""]
    for rid, r in res["runs"].items():
        m, cv = r["matching"], r["coverage"]
        L += [f"## Run {rid}: {r['label']}", "",
              f"Dates {r['filters']['start']} to {r['filters']['end']}, AOI `{r['filters']['aoi']}`, config `{json.dumps(r['config'])}`.", "",
              "### 1. Temporal matching", "",
              f"- Matched pairs {m['matched']:,} out of {m['candidate_pairs']:,} candidate pairs (ambiguous candidates resolved by the one-to-one rule: {m['ambiguous_candidates']:,}).",
              f"- Every event used at most once: **{'yes' if m['one_to_one'] else 'NO'}**; all |Δt| within the tolerance: **{'yes' if m['max_dt_within_tolerance'] else 'NO'}**.",
              (f"- |Δt| percentiles (min): " + ", ".join(f"p{k} {v:.0f}" for k, v in m["dt_percentiles_min"].items())
               + f". Share of matches with |Δt| ≥ ⅔ of the tolerance: {_p(m['share_dt_at_least_two_thirds_tolerance'])}.") if m["dt_percentiles_min"] else "- No matches.",
              "", "### 2. Coverage limits", "",
              f"- {_p(cv['viirs_matched_share'])} of VIIRS events and {_p(cv['modis_matched_share'])} of MODIS events have a partner. "
              f"Of all VIIRS events, {_p(cv['viirs_unmatched_proxy_share'])} are unmatched with only proxy evidence and "
              f"{_p(cv['viirs_unmatched_no_evidence_share'])} are unmatched with no MODIS evidence nearby. Coverage status: `{cv['status']}`.", ""]
        if "leakage" not in r:
            L += [f"Stage 3 not fitted ({r.get('stage3_status')}).", "", f"Validity: **{r['validity']['status']}**.", ""]
            continue
        lk, mt, al = r["leakage"], r["metrics"], r["alternatives"]
        rf = lk["refit_without_later_data"]
        L += ["### 3. Data leakage", "",
              f"- Training units strictly before held-out units: **{'yes' if lk['train_before_test'] else 'NO'}** (split {lk['split']}); days on both sides: {lk['days_on_both_sides']}.",
              (f"- Refit after deleting every record from the split date on: α {rf['alpha']:.6f} vs {rf['alpha_full']:.6f}, β {rf['beta']:.6f} vs {rf['beta_full']:.6f} "
               f"(max difference {rf['max_abs_coefficient_difference']:.2e}; {rf['n_units']:,} vs {rf['n_train_in_full_run']:,} training units)." if rf else "- Refit not possible."),
              "- Constants are fitted on training units only; the Duan smearing factor is reported but not applied.",
              "- Embargo (drop held-out units in the first N days after the split): " + "; ".join(
                  f"{k} d: n {v['n']:,}, MAE {v['unadjusted']['mae']:.3f} → {v['calibrated']['mae']:.3f}" for k, v in lk["embargo_after_split"].items()) + ".", "",
              "### 4. Metrics recomputed independently", "",
              f"- Maximum absolute difference between the report and a plain-Python recomputation of MAE/RMSE/MBE: {mt['max_abs_difference']:.2e}.", "",
              "### 5. Held-out errors of simple alternatives", "",
              "| Estimate | MAE | RMSE | MBE |", "|---|---|---|---|"]
        names = {"calibrated": "Calibrated (log-log)", "unadjusted": "Unadjusted VIIRS (M̂ = V)", "training_mean": "Constant: training mean",
                 "training_median": "Constant: training median", "ratio_model": "Ratio model M̂ = c·V (c = ΣM/ΣV, training)"}
        for k, v in al.items():
            L.append(f"| {names[k]} | {_f(v['mae'])} | {_f(v['rmse'])} | {_f(v['mbe'])} |")
        L += ["", "### 6. Application", "", f"- Unit-level validity: **{r['validity']['status']}**. "
              + "; ".join(f"{c['label']}: {'yes' if c['passed'] else 'no'} ({c['value']})" for c in r["validity"]["checks"]) + "."]
        em = r.get("error_map_0.5deg_n20")
        if em:
            L.append(f"- Error map (0.5° regions, n ≥ 20): {em['cells_validated']} validated regions holding {_p(em['share_in_validated_cells'])} of "
                     f"{em['held_out_units']:,} held-out units; {em['cells_too_few']} with too few units; {em['cells_no_held_out']} with VIIRS activity but no held-out unit; "
                     f"validated regions where calibrated is worse than unadjusted: {em['validated_cells_worse_than_unadjusted']}.")
        for sc, v in (r.get("daily_totals") or {}).items():
            h = v["check"]["held_out"] if v["check"] else None
            if h:
                L.append(f"- Held-out daily totals, {'model-domain events' if sc == 'domain' else 'all VIIRS events'}: Σ calibrated / Σ MODIS = {h['ratio_calibrated_to_modis']:.2f} "
                         f"(raw VIIRS {h['ratio_viirs_to_modis']:.2f}); daily MAE {h['unadjusted']['mae']:.1f} → {h['calibrated']['mae']:.1f}; "
                         f"constant {h['constant_reference']['mae']:.1f}. Totals validity: **{v['totals_validity']['status']}**.")
        L.append("")
    return "\n".join(L)
