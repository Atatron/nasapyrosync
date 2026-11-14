"""Three-stage MODIS–VIIRS harmonization (added in PyroSync 1.1).

Stage 1 — Spatial standardization
    Detections that already passed the shared PyroSync filters (dates, AOI, quality, type, day/night)
    are indexed onto a regular WGS84 grid with the same integer rule as the rest of the app
    (col = floor((lon_e5 + 18e6) / R), row = floor((lat_e5 + 9e6) / R)). Each sensor keeps its own
    measurement; nothing is summed across sensors.

Stage 2 — Temporal matching
    Within each comparison cell, detections of one platform are grouped into *observation events*
    (a new event starts when consecutive acquisitions are more than EVENT_GAP_MIN apart; one event is
    normally one satellite overpass). A MODIS event and a VIIRS event in the same cell are a *candidate
    match* when their event times differ by at most the tolerance. Matching is one-to-one and
    deterministic: candidate pairs are taken in order of (|Δt|, MODIS time, VIIRS time, cell) and a
    pair is accepted only if neither event is already used.

    FIRMS active-fire files contain detections only, so a missing detection never proves that a sensor
    looked at the cell. Events without a partner are therefore split into "other sensor imaging nearby
    (proxy)" and "no evidence"; neither is verified coverage. Verified coverage would need swath
    geolocation and cloud/fire masks (e.g. MOD03/MOD14, VNP03/VNP14), which PyroSync does not import.

Stage 3 — Statistical calibration
    ln(1 + M_i) = α + β ln(1 + V_i) + ε_i fitted by ordinary least squares on the chronologically
    earlier units, then M̂_i = max(0, exp(α̂ + β̂ ln(1 + V_i)) − 1) is evaluated on the later, held-out
    units against the unadjusted VIIRS value (M̂ = V) with MAE, RMSE, MBE and percentage improvement.
    MODIS is the reference *scale* for continuity with the long MODIS record, not ground truth.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from . import cache
from . import normalize as N
from .config import PROCESSING_VERSION
from .db import cursor, get_revision
from .query import Filters, filter_disclosure, filtered_sql

METHOD_VERSION = "pyrosync-harmonize-1.0"
EVENT_GAP_MIN = 20          # minutes; MODIS/VIIRS orbits are ~100 min apart, granules 5–6 min
UNIT_GRIDS = (0.1, 0.25, 0.5, 1.0)
VIIRS_SERIES_PLATFORM = {"VIIRS_SNPP": "SNPP", "VIIRS_N20": "N20", "VIIRS_N21": "N21"}
MIN_TRAIN_UNITS = 30
MIN_TEST_UNITS = 10
SCATTER_MAX = 2500
Z95 = 1.959964

CLASS_DOC = {
    "matched": "Candidate match: a MODIS event and a VIIRS event in the same cell within the time tolerance. Both sensors reported "
               "at least one detection. This is a positive-detection match, not verified joint coverage.",
    "viirs_only_proxy": "VIIRS event without a MODIS partner, while MODIS reported a detection within the evidence radius and time "
                        "tolerance (the instrument was imaging nearby). Proxy only: the cell may have been outside the swath or under cloud.",
    "viirs_only_no_evidence": "VIIRS event without a MODIS partner and with no MODIS detection nearby in time. Whether MODIS observed the "
                              "cell is unknown; such units are never used as MODIS zeros.",
    "modis_only_proxy": "MODIS event without a VIIRS partner, while VIIRS reported a detection within the evidence radius and time "
                        "tolerance. Proxy only, as above.",
    "modis_only_no_evidence": "MODIS event without a VIIRS partner and no VIIRS detection nearby in time. Coverage unknown.",
}
COVERAGE_NOTE = ("Verified satellite coverage is NOT established. FIRMS active-fire records list detections only; they do not say which "
                 "cells each overpass imaged, nor which were cloud-free. Verifying coverage would require swath geolocation and "
                 "fire/cloud masks (MOD03/MOD14 for MODIS, VNP03/VNP14 or VJ103/VJ114 for VIIRS), which PyroSync does not import. "
                 "'Proxy' classes only show that the other instrument reported a detection nearby at about the same time.")


class HarmonizeConfig(BaseModel):
    modis_platforms: list[Literal["Aqua", "Terra"]] = Field(default_factory=lambda: ["Aqua"])
    viirs_series: Literal["VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"] = "VIIRS_SNPP"
    unit_grid: float = 0.1
    tolerance_min: int = Field(30, ge=1, le=180)
    metric: Literal["detections", "frp_sum"] = "detections"
    unit_set: Literal["matched", "matched_plus_proxy"] = "matched"
    evidence_radius_deg: float = Field(5.0, gt=0, le=20)
    test_fraction: float = Field(0.2, ge=0.05, le=0.5)
    split_date: date | None = None

    @field_validator("modis_platforms")
    @classmethod
    def _mp(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("choose at least one MODIS platform (Aqua and/or Terra)")
        return sorted(set(v), key=["Aqua", "Terra"].index)

    @field_validator("unit_grid")
    @classmethod
    def _grid(cls, v: float) -> float:
        for g in UNIT_GRIDS:
            if abs(v - g) < 1e-9:
                return g
        raise ValueError(f"unit_grid must be one of {', '.join(map(str, UNIT_GRIDS))}")

    @model_validator(mode="after")
    def _ok(self) -> "HarmonizeConfig":
        return self

    def key(self) -> dict:
        return self.model_dump(mode="json")


# ------------------------------------------------------------------ stage 1 + 2 (SQL)
def _cell_expr(g: float) -> tuple[str, str, int]:
    r = int(round(g * 100000))
    ncols = 36_000_000 // r
    nrows = 18_000_000 // r
    ci = f"least((o.lon_e5::BIGINT + 18000000) // {r}, {ncols - 1})"
    cj = f"least((o.lat_e5::BIGINT + 9000000) // {r}, {nrows - 1})"
    return ci, cj, ncols


def _sensor_filters(f: Filters, cfg: HarmonizeConfig) -> Filters:
    plats = list(cfg.modis_platforms) + [VIIRS_SERIES_PLATFORM[cfg.viirs_series]]
    return f.model_copy(update={"platforms": plats})


def _build_events(cur, f: Filters, cfg: HarmonizeConfig, tag: str) -> None:
    """Temp table ev_<tag>: one row per observation event (sensor, platform, cell, event number)."""
    ff = _sensor_filters(f, cfg)
    sql, params = filtered_sql(ff)
    ci, cj, ncols = _cell_expr(cfg.unit_grid)
    g = cfg.unit_grid
    cur.execute(f"""CREATE TEMP TABLE ev_{tag} AS
        WITH p AS (
            SELECT CASE WHEN o.instrument = 'MODIS' THEN 'M' ELSE 'V' END AS sensor, o.platform, {ci} AS ci, {cj} AS cj,
                   o.rid, o.acq_ts, coalesce(o.frp, 0) AS frp, o.frp IS NULL AS frp_missing
            FROM ({sql}) o),
        q AS (
            SELECT *, CASE WHEN lag(acq_ts) OVER w IS NULL
                            OR acq_ts - lag(acq_ts) OVER w > INTERVAL {EVENT_GAP_MIN} MINUTE THEN 1 ELSE 0 END AS newev
            FROM p WINDOW w AS (PARTITION BY sensor, platform, ci, cj ORDER BY acq_ts, rid)),
        r AS (
            SELECT *, sum(newev) OVER (PARTITION BY sensor, platform, ci, cj ORDER BY acq_ts, rid ROWS UNBOUNDED PRECEDING) AS evn FROM q)
        SELECT sensor, platform, ci, cj, ci + cj * {ncols} AS cid, evn,
               min(acq_ts) AS t0, max(acq_ts) AS t1, count(*) AS n, sum(frp) AS frp_sum, count(*) FILTER (WHERE frp_missing) AS frp_missing_n,
               -180 + (ci + 0.5) * {g} AS clon, -90 + (cj + 0.5) * {g} AS clat
        FROM r GROUP BY sensor, platform, ci, cj, evn""", params)
    cur.execute(f"""CREATE TEMP TABLE evn_{tag} AS
        SELECT row_number() OVER (ORDER BY sensor, t0, cid, platform) AS id, * FROM ev_{tag}""")
    cur.execute(f"DROP TABLE ev_{tag}")


def _candidate_pairs(cur, cfg: HarmonizeConfig, tag: str) -> list[tuple]:
    tol = cfg.tolerance_min
    return cur.execute(f"""
        SELECT m.id, v.id, abs(epoch(v.t0) - epoch(m.t0)) AS dt, m.t0, v.t0, m.cid
        FROM evn_{tag} m JOIN evn_{tag} v
          ON m.cid = v.cid AND m.sensor = 'M' AND v.sensor = 'V'
         AND v.t0 BETWEEN m.t0 - INTERVAL {tol} MINUTE AND m.t0 + INTERVAL {tol} MINUTE
        ORDER BY dt, m.t0, v.t0, m.cid, m.id, v.id""").fetchall()


def greedy_match(pairs: list[tuple]) -> list[tuple]:
    """One-to-one deterministic matching. `pairs` must already be sorted by priority; first come, first served."""
    used_m: set = set()
    used_v: set = set()
    out = []
    for p in pairs:
        mid, vid = p[0], p[1]
        if mid in used_m or vid in used_v:
            continue
        used_m.add(mid)
        used_v.add(vid)
        out.append(p)
    return out


def _proxy_flags(cur, f: Filters, cfg: HarmonizeConfig, tag: str) -> None:
    """For every event, does the OTHER instrument report any detection nearby in time and space?

    Uses all non-superseded detections of the selected platforms (any quality, any type, no AOI clip),
    because a swath is far larger than any AOI. Spatial test: |Δlat| and |Δlon| ≤ radius (degrees)."""
    tol = cfg.tolerance_min
    rad = cfg.evidence_radius_deg
    plats = list(cfg.modis_platforms) + [VIIRS_SERIES_PLATFORM[cfg.viirs_series]]
    ph = ",".join("?" * len(plats))
    cur.execute(f"""CREATE TEMP TABLE pp_{tag} AS
        SELECT CASE WHEN instrument = 'MODIS' THEN 'M' ELSE 'V' END AS sensor, acq_ts AS t,
               floor(lat * 2) / 2 + 0.25 AS la, floor(lon * 2) / 2 + 0.25 AS lo
        FROM observations
        WHERE NOT superseded AND platform IN ({ph}) AND acq_date BETWEEN ? AND ?
        GROUP BY ALL""", plats + [f.start - timedelta(days=1), f.end + timedelta(days=1)])
    # Set-based search: time buckets of width = tolerance, so a partner within ±tol is always in bucket b-1, b or b+1.
    w = tol * 60
    cur.execute(f"""CREATE TEMP TABLE px_{tag} AS
        WITH e AS (SELECT id, sensor, t0, clat, clon, CAST(floor(epoch(t0) / {w}) AS BIGINT) AS b FROM evn_{tag}),
             ek AS (SELECT e.*, e.b + k.o AS bb, CASE WHEN e.sensor = 'M' THEN 'V' ELSE 'M' END AS other
                    FROM e CROSS JOIN (VALUES (-1), (0), (1)) k(o)),
             p AS (SELECT sensor, t, la, lo, CAST(floor(epoch(t) / {w}) AS BIGINT) AS b FROM pp_{tag})
        SELECT DISTINCT ek.id FROM ek JOIN p ON p.sensor = ek.other AND p.b = ek.bb
        WHERE abs(epoch(p.t) - epoch(ek.t0)) <= {w}
          AND abs(p.la - ek.clat) <= {rad + 0.25} AND abs(p.lo - ek.clon) <= {rad + 0.25}""")


# ------------------------------------------------------------------ stage 3 (numerics)
def fit_loglog(v: np.ndarray, m: np.ndarray) -> dict:
    """OLS of ln(1+M) on ln(1+V). Returns coefficients, classical SEs and 95 % normal-approximation CIs."""
    x = np.log1p(v.astype(float))
    y = np.log1p(m.astype(float))
    n = len(x)
    if n < 3:
        raise ValueError("at least 3 units are needed to fit the model")
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    if sxx <= 0:
        raise ValueError("all training units have the same VIIRS value; the slope is not identifiable")
    beta = float(((x - xm) * (y - ym)).sum() / sxx)
    alpha = float(ym - beta * xm)
    resid = y - (alpha + beta * x)
    ssr = float((resid ** 2).sum())
    sst = float(((y - ym) ** 2).sum())
    s2 = ssr / (n - 2)
    se_b = math.sqrt(s2 / sxx)
    se_a = math.sqrt(s2 * (1.0 / n + xm * xm / sxx))
    return {"alpha": alpha, "beta": beta, "se_alpha": se_a, "se_beta": se_b,
            "ci95_alpha": [alpha - Z95 * se_a, alpha + Z95 * se_a], "ci95_beta": [beta - Z95 * se_b, beta + Z95 * se_b],
            "r2_log": (1 - ssr / sst) if sst > 0 else None, "residual_sd_log": math.sqrt(s2), "n": n,
            "duan_smearing_factor": float(np.mean(np.exp(resid)))}


def predict(alpha: float, beta: float, v: np.ndarray) -> np.ndarray:
    """M̂ = max(0, exp(α + β ln(1+V)) − 1)."""
    return np.maximum(0.0, np.exp(alpha + beta * np.log1p(v.astype(float))) - 1.0)


def error_metrics(pred: np.ndarray, obs: np.ndarray) -> dict:
    e = pred.astype(float) - obs.astype(float)
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(math.sqrt(np.mean(e ** 2))), "mbe": float(np.mean(e)), "n": int(len(e))}


def improvement(unadj: dict, cal: dict) -> dict:
    def pct(a: float, b: float) -> float | None:
        return None if a == 0 else 100.0 * (a - b) / a
    return {"mae_pct": pct(unadj["mae"], cal["mae"]), "rmse_pct": pct(unadj["rmse"], cal["rmse"]),
            "abs_mbe_pct": pct(abs(unadj["mbe"]), abs(cal["mbe"])),
            "definition": "100 × (unadjusted − calibrated) / unadjusted. Positive = calibrated error is smaller. For MBE the absolute bias is compared."}


VALID_MIN_TEST_UNITS = 100
VALIDITY_RULES_VERSION = "pyrosync-validity-1.0"


def assess_validity(stage3: dict, cfg: HarmonizeConfig) -> dict:
    """Project rule (added in v1.2) deciding whether a fitted calibration may be APPLIED to maps and time series.

    Every check uses only the held-out (later) period. Passing means "the calibrated estimate beat the simple alternatives
    on later data for this exact configuration"; it is not an independent scientific validation."""
    checks: list[dict] = []

    def add(cid: str, label: str, passed: bool, value: str, rule: str) -> None:
        checks.append({"id": cid, "label": label, "passed": bool(passed), "value": value, "rule": rule})

    ok = stage3.get("status") == "ok"
    add("fitted", "Model fitted", ok, "fitted" if ok else (stage3.get("reason") or "not fitted"),
        f"At least {MIN_TRAIN_UNITS} training and {MIN_TEST_UNITS} held-out units, and a non-constant VIIRS value.")
    add("measurement", "Measurement eligible for application", cfg.metric == "detections",
        "detection counts" if cfg.metric == "detections" else "FRP sum",
        "Only detection counts may be applied. FRP sums are evaluated but never applied: on the full Indonesia archive the "
        "log-log model did not reduce held-out FRP errors (docs/HARMONIZATION_VALIDATION.md, run E).")
    if ok:
        ho = stage3["evaluation"]["held_out"]
        u, c = ho["unadjusted"], ho["calibrated"]
        mref, dref = ho["training_mean_reference"], ho["training_median_reference"]
        n_test = stage3["split"]["n_test"]
        lo = stage3["fit"]["ci95_beta"][0]
        add("held_out_size", "Enough held-out units", n_test >= VALID_MIN_TEST_UNITS, f"{n_test:,} units",
            f"At least {VALID_MIN_TEST_UNITS} held-out units.")
        add("beats_unadjusted", "Better than unadjusted VIIRS", c["mae"] < u["mae"] and c["rmse"] < u["rmse"] and abs(c["mbe"]) < abs(u["mbe"]),
            f"MAE {c['mae']:.3f} vs {u['mae']:.3f}; RMSE {c['rmse']:.3f} vs {u['rmse']:.3f}; |MBE| {abs(c['mbe']):.3f} vs {abs(u['mbe']):.3f}",
            "Held-out MAE, RMSE and |MBE| all lower than using the raw VIIRS value (M̂ = V).")
        best_mae, best_rmse = min(mref["mae"], dref["mae"]), min(mref["rmse"], dref["rmse"])
        add("beats_constant", "Better than a constant model", c["mae"] < best_mae and c["rmse"] < best_rmse,
            f"MAE {c['mae']:.3f} vs best constant {best_mae:.3f}; RMSE {c['rmse']:.3f} vs best constant {best_rmse:.3f}",
            "Held-out MAE and RMSE both lower than the better of two constants fitted on the training period (MODIS mean, MODIS median), "
            "i.e. the VIIRS value adds information beyond the overall level.")
        add("slope", "VIIRS slope clearly positive", lo > 0, f"β 95 % CI lower bound {lo:.4f}",
            "Lower bound of the 95 % interval of β above 0 (intervals are optimistic because units are correlated).")
    passed = bool(checks) and all(ch["passed"] for ch in checks) and len(checks) == 6
    return {
        "status": "passes" if passed else "not_validated",
        "label": ("Passes PyroSync's validation rules for this configuration" if passed
                  else "Not validated for application with this configuration"),
        "rules_version": VALIDITY_RULES_VERSION,
        "checks": checks,
        "scope": "Valid only for the AOI, dates, filters, sensor pair, grid, tolerance and unit set of this run. Calibrated values before the "
                 "held-out period are in-sample. Satellite coverage is not verified, and MODIS is a reference scale, not ground truth.",
        "applies_to": "Map estimates and time series in the Harmonization tab. The calendar, history, Explore map and Sensor Workbench "
                      "always show original observations.",
    }


def chronological_split(dates: list[date], test_fraction: float, split_date: date | None) -> date:
    """First UTC day of the held-out (test) period. All units of one day fall on the same side."""
    if split_date is not None:
        return split_date
    ds = sorted(dates)
    target = int(math.ceil(len(ds) * (1 - test_fraction)))
    target = min(max(target, 1), len(ds) - 1)
    return ds[target]


# ------------------------------------------------------------------ orchestration
def harmonize(f: Filters, cfg: HarmonizeConfig, include_units: bool = False) -> dict:
    if not include_units:
        # v1.2: the report is taken from the shared calibration core, so the report, the map, the error map and the
        # time series of one configuration always come from the same single run (identical numbers, computed once).
        from . import calibration
        return calibration.core(f, cfg).report
    rev = get_revision()
    key = cache.make_key("harmonize", rev, {"f": f.key(), "c": cfg.key(), "u": include_units})
    return cache.get_or_compute(key, lambda: _harmonize(f, cfg, include_units))


def _harmonize(f: Filters, cfg: HarmonizeConfig, include_units: bool) -> dict:
    out, ex = _run(f, cfg)
    if include_units:
        out["units"] = ex["model_units"]
    return out


def _run(f: Filters, cfg: HarmonizeConfig) -> tuple[dict, dict]:
    """One complete three-stage run. Returns (report, extras); extras holds the events, matches and units for applications."""
    tag = uuid.uuid4().hex[:10]
    rev = get_revision()
    vplat = VIIRS_SERIES_PLATFORM[cfg.viirs_series]
    with cursor() as cur:
        try:
            _build_events(cur, f, cfg, tag)
            pairs = _candidate_pairs(cur, cfg, tag)
            matched = greedy_match(pairs)
            _proxy_flags(cur, f, cfg, tag)
            events = cur.execute(f"""SELECT e.id, e.sensor, e.platform, e.cid, e.ci, e.cj, e.t0, e.n, e.frp_sum, e.frp_missing_n, e.clon, e.clat,
                       x.id IS NOT NULL AS proxy
                FROM evn_{tag} e LEFT JOIN px_{tag} x ON x.id = e.id ORDER BY e.id""").fetchall()
            present = cur.execute("SELECT DISTINCT platform FROM observations WHERE NOT superseded").fetchall()
        finally:
            for t in ("ev", "evn", "pp", "px"):
                cur.execute(f"DROP TABLE IF EXISTS {t}_{tag}")
    present_plats = {r[0] for r in present}
    ev = {r[0]: r for r in events}
    n_events = {"modis": sum(1 for r in events if r[1] == "M"), "viirs": sum(1 for r in events if r[1] == "V")}
    used_m = {p[0] for p in matched}
    used_v = {p[1] for p in matched}
    val = (lambda r: float(r[7])) if cfg.metric == "detections" else (lambda r: float(r[8] or 0.0))

    units: list[dict] = []
    for mid, vid, dt, mt, vt, cid in matched:
        m, v = ev[mid], ev[vid]
        units.append({"class": "matched", "cid": cid, "ci": m[4], "cj": m[5], "lon": m[10], "lat": m[11], "modis_platform": m[2],
                      "t_modis": mt, "t_viirs": vt, "dt_min": dt / 60.0, "M": val(m), "V": val(v), "M_n": m[7], "V_n": v[7]})
    counts = {k: 0 for k in CLASS_DOC}
    counts["matched"] = len(matched)
    for r in events:
        if r[1] == "M" and r[0] not in used_m:
            cls = "modis_only_proxy" if r[12] else "modis_only_no_evidence"
            counts[cls] += 1
            if cls == "modis_only_proxy":
                units.append({"class": cls, "cid": r[3], "ci": r[4], "cj": r[5], "lon": r[10], "lat": r[11], "modis_platform": r[2],
                              "t_modis": r[6], "t_viirs": None, "dt_min": None, "M": val(r), "V": 0.0, "M_n": r[7], "V_n": 0})
        elif r[1] == "V" and r[0] not in used_v:
            cls = "viirs_only_proxy" if r[12] else "viirs_only_no_evidence"
            counts[cls] += 1
            if cls == "viirs_only_proxy":
                units.append({"class": cls, "cid": r[3], "ci": r[4], "cj": r[5], "lon": r[10], "lat": r[11], "modis_platform": None,
                              "t_modis": None, "t_viirs": r[6], "dt_min": None, "M": 0.0, "V": val(r), "M_n": 0, "V_n": r[7]})
    for u in units:
        t = u["t_modis"] if u["t_modis"] is not None else u["t_viirs"]
        u["t"] = t
        u["date"] = t.date()
    units.sort(key=lambda u: (u["t"], u["cid"], u["class"]))

    use_classes = {"matched"} if cfg.unit_set == "matched" else {"matched", "viirs_only_proxy", "modis_only_proxy"}
    model_units = [u for u in units if u["class"] in use_classes]

    dts = [u["dt_min"] for u in units if u["class"] == "matched"]
    dt_hist = _histogram(dts, cfg.tolerance_min)

    stage1 = {
        "unit": f"Observation event of one platform in one {cfg.unit_grid}° WGS84 grid cell",
        "grid_deg": cfg.unit_grid,
        "grid_rule": "col = floor((lon_e5 + 18,000,000) / R), row = floor((lat_e5 + 9,000,000) / R), R = grid × 100,000 (same rule as the map grid)",
        "measurement": {"detections": "Number of FIRMS detections of that platform in the cell during the event (each sensor its own count).",
                        "frp_sum": "Sum of FRP (MW) of that platform's detections in the cell during the event; missing FRP counts as 0."}[cfg.metric],
        "filters_applied": "Shared PyroSync filters: dates, AOI (exact polygon, before aggregation), MODIS confidence, VIIRS confidence, fire type, day/night.",
        "sensor_note": "MODIS (~1 km at nadir) and VIIRS I-band (375 m) pixels differ in size and sensitivity; values are kept per sensor and never added.",
    }
    stage2 = {
        "modis_platforms": cfg.modis_platforms, "viirs_series": cfg.viirs_series, "viirs_platform": vplat,
        "tolerance_min": cfg.tolerance_min, "event_gap_min": EVENT_GAP_MIN, "evidence_radius_deg": cfg.evidence_radius_deg,
        "events": n_events, "candidate_pairs": len(pairs), "class_counts": counts, "class_doc": CLASS_DOC,
        "dt_minutes": {"histogram": dt_hist, "median": _median(dts), "max": max(dts) if dts else None},
        "matching_rule": f"Events: consecutive acquisitions of one platform in one cell ≤ {EVENT_GAP_MIN} min apart. Candidate pair: MODIS and VIIRS "
                         f"events in the same cell with |Δt| ≤ {cfg.tolerance_min} min (event time = first acquisition). One-to-one greedy "
                         "matching by (|Δt|, MODIS time, VIIRS time, cell): deterministic and independent of input order.",
        "coverage_verification": {"status": "not_verified", "note": COVERAGE_NOTE},
        "platforms_missing": [p for p in cfg.modis_platforms + [vplat] if p not in present_plats],
    }
    if cfg.modis_platforms == ["Terra"]:
        stage2["warning"] = ("Terra crosses the equator at about 10:30/22:30 local time and VIIRS at about 13:30/01:30, so few or no Terra–VIIRS "
                             "events fall within a short tolerance. Aqua is the near-simultaneous partner for VIIRS.")

    stage3 = _calibrate(model_units, cfg)
    validity = assess_validity(stage3, cfg)

    out = {
        "dataset_revision": rev, "processing_version": PROCESSING_VERSION, "method_version": METHOD_VERSION,
        "effective_filters": _sensor_filters(f, cfg).key(), "filter_disclosure": filter_disclosure(_sensor_filters(f, cfg)),
        "config": cfg.key(), "stage1": stage1, "stage2": stage2, "stage3": stage3,
        "interpretation": [
            "MODIS is used as the reference scale for continuity with the long MODIS record; it is not ground truth. Its own omission and "
            "commission errors remain in the target.",
            "The calibration maps a VIIRS measurement to an expected MODIS-scale measurement for the same cell and overpass. It does not "
            "make the sensors equivalent and does not recover fires that neither sensor detected.",
            "With unit_set = 'matched', the model is conditional on both sensors reporting a detection; it does not describe cells where only "
            "one sensor detected fire.",
            "Coefficients are empirical for this AOI, period, filters and sensor pair. Re-fit before applying them elsewhere.",
            "Standard errors assume independent units; neighbouring cells and successive days are correlated, so the intervals are optimistic.",
        ],
    }
    out["validity"] = validity
    return out, {"events": events, "matched": matched, "units": units, "model_units": model_units}


def _calibrate(units: list[dict], cfg: HarmonizeConfig) -> dict:
    res: dict = {"equation": "ln(1 + M_i) = α + β ln(1 + V_i) + ε_i",
                 "prediction": "M̂_i = max(0, exp(α̂ + β̂ ln(1 + V_i)) − 1)",
                 "estimator": "Ordinary least squares on the training (earlier) period only",
                 "unit_set": cfg.unit_set, "n_units": len(units), "status": "ok", "reason": None}
    if len(units) < MIN_TRAIN_UNITS + MIN_TEST_UNITS:
        res.update(status="insufficient", reason=f"Only {len(units)} comparison units; at least {MIN_TRAIN_UNITS + MIN_TEST_UNITS} are needed "
                   f"({MIN_TRAIN_UNITS} training + {MIN_TEST_UNITS} held-out). Widen the dates or AOI, or increase the tolerance.")
        return res
    dates = [u["date"] for u in units]
    split = chronological_split(dates, cfg.test_fraction, cfg.split_date)
    train = [u for u in units if u["date"] < split]
    test = [u for u in units if u["date"] >= split]
    for u in units:
        u["set"] = "train" if u["date"] < split else "test"
    res["split"] = {"test_starts": split.isoformat(), "rule": "Chronological hold-out: units on or after this UTC day are held out; "
                    "no random shuffling, and no unit of one day appears on both sides.",
                    "train_period": [train[0]["date"].isoformat(), train[-1]["date"].isoformat()] if train else None,
                    "test_period": [test[0]["date"].isoformat(), test[-1]["date"].isoformat()] if test else None,
                    "n_train": len(train), "n_test": len(test), "requested_test_fraction": cfg.test_fraction if cfg.split_date is None else None}
    if len(train) < MIN_TRAIN_UNITS or len(test) < MIN_TEST_UNITS:
        res.update(status="insufficient", reason=f"Split gives {len(train)} training and {len(test)} held-out units; at least "
                   f"{MIN_TRAIN_UNITS} and {MIN_TEST_UNITS} are needed.")
        return res
    vtr = np.array([u["V"] for u in train]); mtr = np.array([u["M"] for u in train])
    vte = np.array([u["V"] for u in test]); mte = np.array([u["M"] for u in test])
    try:
        fit = fit_loglog(vtr, mtr)
    except ValueError as e:
        res.update(status="insufficient", reason=str(e))
        return res
    res["fit"] = fit
    a, b = fit["alpha"], fit["beta"]
    pte = predict(a, b, vte)
    ptr = predict(a, b, vtr)
    unadj = error_metrics(vte, mte)
    cal = error_metrics(pte, mte)
    mean_baseline = error_metrics(np.full(len(mte), float(mtr.mean())), mte)
    median_baseline = error_metrics(np.full(len(mte), float(np.median(mtr))), mte)
    res["evaluation"] = {
        "held_out": {"unadjusted": unadj, "calibrated": cal, "training_mean_reference": mean_baseline,
                     "training_median_reference": median_baseline,
                     "improvement_vs_unadjusted": improvement(unadj, cal)},
        "training": {"unadjusted": error_metrics(vtr, mtr), "calibrated": error_metrics(ptr, mtr)},
        "definitions": {"mae": "mean |prediction − MODIS|", "rmse": "sqrt(mean (prediction − MODIS)²)",
                        "mbe": "mean (prediction − MODIS); positive = overestimates the MODIS-scale value",
                        "unadjusted": "the raw VIIRS value used directly as the MODIS-scale estimate (M̂ = V)",
                        "training_mean_reference": "a constant equal to the training-period MODIS mean; context only",
                        "training_median_reference": "a constant equal to the training-period MODIS median (the best constant for MAE); context only"},
        "observed_means": {"train_M": float(mtr.mean()), "train_V": float(vtr.mean()), "test_M": float(mte.mean()), "test_V": float(vte.mean())},
        "retransformation_note": "Back-transforming a log-scale fit estimates a conditional median rather than a mean, which typically biases "
                                 f"M̂ low. The Duan smearing factor on the training residuals is {fit['duan_smearing_factor']:.3f}; it is reported "
                                 "for transparency and NOT applied, so the prediction follows the stated equation exactly.",
    }
    res["bins"] = _bins(test, a, b)
    res["daily_test"] = _daily_test(test, a, b)
    res["scatter"] = _scatter(units, a, b)
    res["curve"] = [{"V": float(v), "M_hat": float(predict(a, b, np.array([v]))[0])} for v in _curve_points(units)]
    return res


def _bins(test: list[dict], a: float, b: float) -> list[dict]:
    edges = [(0, 0), (1, 1), (2, 3), (4, 7), (8, 15), (16, 31), (32, math.inf)]
    out = []
    for lo, hi in edges:
        sel = [u for u in test if lo <= u["V"] <= hi] if hi != math.inf else [u for u in test if u["V"] >= lo]
        if not sel:
            continue
        v = np.array([u["V"] for u in sel]); m = np.array([u["M"] for u in sel])
        p = predict(a, b, v)
        out.append({"V_range": f"{lo}" if lo == hi else (f"{lo}–{hi}" if hi != math.inf else f"≥{lo}"), "n": len(sel),
                    "mean_V": float(v.mean()), "mean_M": float(m.mean()), "mean_M_hat": float(p.mean())})
    return out


def _daily_test(test: list[dict], a: float, b: float) -> list[dict]:
    agg: dict = {}
    for u in test:
        d = agg.setdefault(u["date"], [0.0, 0.0, 0.0, 0])
        d[0] += u["M"]; d[1] += u["V"]; d[2] += float(predict(a, b, np.array([u["V"]]))[0]); d[3] += 1
    return [{"date": k.isoformat(), "M": v[0], "V": v[1], "M_hat": v[2], "units": v[3]} for k, v in sorted(agg.items())]


def _scatter(units: list[dict], a: float, b: float) -> list[dict]:
    step = max(1, math.ceil(len(units) / SCATTER_MAX))
    return [{"V": u["V"], "M": u["M"], "set": u.get("set"), "class": u["class"], "date": u["date"].isoformat()} for u in units[::step]]


def _curve_points(units: list[dict]) -> list[float]:
    vmax = max((u["V"] for u in units), default=1.0)
    pts = sorted({0.0, *[float(x) for x in np.unique(np.round(np.geomspace(1, max(vmax, 1.0), 40)))]})
    return pts


def _histogram(xs: list[float], tol: int) -> list[dict]:
    if tol <= 0:
        return []
    width = 5 if tol <= 60 else 10
    bins = [{"from_min": i, "to_min": min(i + width, tol), "n": 0} for i in range(0, tol, width)]
    for x in xs:
        k = min(int(x // width), len(bins) - 1)
        bins[k]["n"] += 1
    return bins


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ------------------------------------------------------------------ report / export
UNIT_COLUMNS = ["set", "class", "date_utc", "t_modis_utc", "t_viirs_utc", "dt_min", "cell_col", "cell_row", "cell_center_lon", "cell_center_lat",
                "modis_platform", "M", "V", "M_hat", "modis_detections", "viirs_detections"]


def units_csv(res: dict) -> str:
    import csv
    import io
    s3 = res["stage3"]
    fit = s3.get("fit")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(UNIT_COLUMNS)
    for u in res.get("units", []):
        mh = float(predict(fit["alpha"], fit["beta"], np.array([u["V"]]))[0]) if fit else None
        w.writerow([u.get("set"), u["class"], u["date"].isoformat(),
                    u["t_modis"].strftime("%Y-%m-%dT%H:%MZ") if u["t_modis"] else "", u["t_viirs"].strftime("%Y-%m-%dT%H:%MZ") if u["t_viirs"] else "",
                    f"{u['dt_min']:.1f}" if u["dt_min"] is not None else "", u["ci"], u["cj"], f"{u['lon']:.4f}", f"{u['lat']:.4f}",
                    u["modis_platform"] or "", _g(u["M"]), _g(u["V"]), _g(mh) if mh is not None else "", u["M_n"], u["V_n"]])
    return buf.getvalue()


def _g(x: float) -> str:
    return f"{x:.6g}"


def _f(x, nd=3) -> str:
    if x is None:
        return "—"
    return f"{x:,.{nd}f}"


def report_markdown(res: dict, title: str = "Harmonization validation report") -> str:
    c = res["config"]
    s2 = res["stage2"]
    s3 = res["stage3"]
    fd = res["filter_disclosure"]
    L = [f"# {title}", "",
         f"Generated by PyroSync ({res['method_version']}, {res['processing_version']}), dataset revision {res['dataset_revision']}, "
         f"at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. Every number below was computed from the imported FIRMS records by the "
         "code in `backend/pyrosync/harmonize.py`; rerun the same command on the same data to reproduce it.", "",
         "## Configuration", "",
         "| Setting | Value |", "|---|---|",
         f"| AOI | {fd['aoi']} |",
         f"| Dates (UTC) | {res['effective_filters']['start']} to {res['effective_filters']['end']} |",
         f"| MODIS platform(s) | {', '.join(c['modis_platforms'])} |",
         f"| VIIRS series | {N.SERIES_LABEL.get(c['viirs_series'], c['viirs_series'])} |",
         f"| Quality filters | {fd['modis_quality']}; {fd['viirs_quality']}; types {', '.join(fd['types_included'])}; day/night {', '.join(fd['daynight'])} |",
         f"| Comparison grid | {c['unit_grid']}° |",
         f"| Measurement | {c['metric']} |",
         f"| Time tolerance | ±{c['tolerance_min']} min (event gap {s2['event_gap_min']} min) |",
         f"| Units used for the model | {c['unit_set']} |",
         f"| Proxy evidence radius | {c['evidence_radius_deg']}° |",
         f"| Hold-out | {'from ' + c['split_date'] if c['split_date'] else 'last ' + str(int(c['test_fraction'] * 100)) + ' % of units by time'} |",
         "", "## Stage 1: Spatial standardization", "", res["stage1"]["unit"] + ". " + res["stage1"]["measurement"], "",
         "## Stage 2: Temporal matching", "", s2["matching_rule"], "",
         f"Events: {s2['events']['modis']:,} MODIS and {s2['events']['viirs']:,} VIIRS. Candidate pairs within tolerance: {s2['candidate_pairs']:,}.", "",
         "| Class | Units | Meaning |", "|---|---|---|"]
    for k, v in s2["class_counts"].items():
        L.append(f"| {k} | {v:,} | {CLASS_DOC[k]} |")
    L += ["", f"Median |Δt| of matched pairs: {_f(s2['dt_minutes']['median'], 1)} min.", "", f"**Coverage:** {COVERAGE_NOTE}", ""]
    if s2.get("warning"):
        L += [f"> {s2['warning']}", ""]
    L += ["## Stage 3: Statistical calibration", "", f"Model: {s3['equation']}; prediction {s3['prediction']}. {s3['estimator']}.", ""]
    if s3["status"] != "ok":
        L += [f"**Not fitted:** {s3['reason']}", ""]
    else:
        fit = s3["fit"]
        sp = s3["split"]
        ev = s3["evaluation"]["held_out"]
        L += [f"Training: {sp['n_train']:,} units, {sp['train_period'][0]} to {sp['train_period'][1]}. "
              f"Held out: {sp['n_test']:,} units, {sp['test_period'][0]} to {sp['test_period'][1]}.", "",
              "| Coefficient | Estimate | SE | 95 % CI |", "|---|---|---|---|",
              f"| α | {fit['alpha']:.4f} | {fit['se_alpha']:.4f} | {fit['ci95_alpha'][0]:.4f} to {fit['ci95_alpha'][1]:.4f} |",
              f"| β | {fit['beta']:.4f} | {fit['se_beta']:.4f} | {fit['ci95_beta'][0]:.4f} to {fit['ci95_beta'][1]:.4f} |", "",
              f"Training R² (log scale): {_f(fit['r2_log'])}. Residual SD (log scale): {_f(fit['residual_sd_log'])}.", "",
              "### Held-out evaluation (original measurement scale)", "",
              "| Estimate | MAE | RMSE | MBE |", "|---|---|---|---|",
              f"| Unadjusted VIIRS (M̂ = V) | {_f(ev['unadjusted']['mae'])} | {_f(ev['unadjusted']['rmse'])} | {_f(ev['unadjusted']['mbe'])} |",
              f"| Calibrated | {_f(ev['calibrated']['mae'])} | {_f(ev['calibrated']['rmse'])} | {_f(ev['calibrated']['mbe'])} |",
              f"| Training-mean constant (context) | {_f(ev['training_mean_reference']['mae'])} | {_f(ev['training_mean_reference']['rmse'])} | {_f(ev['training_mean_reference']['mbe'])} |",
              f"| Training-median constant (context) | {_f(ev['training_median_reference']['mae'])} | {_f(ev['training_median_reference']['rmse'])} | {_f(ev['training_median_reference']['mbe'])} |", "",
              f"Improvement over unadjusted: MAE {_f(ev['improvement_vs_unadjusted']['mae_pct'], 1)} %, RMSE {_f(ev['improvement_vs_unadjusted']['rmse_pct'], 1)} %, "
              f"|MBE| {_f(ev['improvement_vs_unadjusted']['abs_mbe_pct'], 1)} %.", "",
              s3["evaluation"]["retransformation_note"], "",
              "### Held-out units by VIIRS value", "", "| V | Units | Mean V | Mean MODIS | Mean M̂ |", "|---|---|---|---|---|"]
        for bn in s3["bins"]:
            L.append(f"| {bn['V_range']} | {bn['n']:,} | {_f(bn['mean_V'], 2)} | {_f(bn['mean_M'], 2)} | {_f(bn['mean_M_hat'], 2)} |")
        L.append("")
    va = res.get("validity")
    if va:
        L += ["## Validity for application (project rule)", "", f"**{va['label']}** (`{va['status']}`, {va['rules_version']}).", "",
              "| Check | Passed | Value | Rule |", "|---|---|---|---|"]
        for ch in va["checks"]:
            L.append(f"| {ch['label']} | {'yes' if ch['passed'] else 'no'} | {ch['value']} | {ch['rule']} |")
        L += ["", va["scope"], ""]
    L += ["## Interpretation and limits", ""] + [f"- {x}" for x in res["interpretation"]] + [
        "- These are results of an implemented method on the imported data. They are not an independent scientific validation; "
        "that would need comparison with coverage-aware reference data and peer review.", ""]
    return "\n".join(L)
