"""Tests for the three-stage MODIS–VIIRS harmonization. All observations are SYNTHETIC TEST FIXTURES."""
from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import date, timedelta

import numpy as np
import pytest

from conftest import MODIS_HDR, VIIRS_HDR, do_import, modis_row, viirs_row, write_csv
from pyrosync import harmonize as H
from pyrosync.query import Filters


def F(**kw):
    base = {"start": date(2023, 8, 1), "end": date(2023, 10, 31)}
    base.update(kw)
    return Filters(**base)


def C(**kw):
    return H.HarmonizeConfig(**kw)


# ---------------------------------------------------------------- unit-level numerics
def test_fit_recovers_known_coefficients_exactly():
    v = np.array([0, 1, 2, 3, 5, 8, 13, 21, 34], dtype=float)
    a, b = -0.4, 0.8
    m = np.exp(a + b * np.log1p(v)) - 1
    fit = H.fit_loglog(v, m)
    assert fit["alpha"] == pytest.approx(a, abs=1e-12)
    assert fit["beta"] == pytest.approx(b, abs=1e-12)
    assert fit["r2_log"] == pytest.approx(1.0)


def test_prediction_formula_and_nonnegative_clamp():
    v = np.array([0.0, 4.0])
    # exp(α) − 1 < 0 when α < 0, so V = 0 must clamp to 0
    p = H.predict(-1.0, 1.0, v)
    assert p[0] == 0.0
    assert p[1] == pytest.approx(max(0.0, math.exp(-1.0 + math.log(5.0)) - 1))


def test_error_metrics_and_improvement():
    obs = np.array([1.0, 2.0, 3.0])
    unadj = H.error_metrics(np.array([2.0, 4.0, 6.0]), obs)   # errors 1,2,3
    cal = H.error_metrics(np.array([1.0, 2.5, 2.5]), obs)     # errors 0,0.5,-0.5
    assert unadj["mae"] == pytest.approx(2.0)
    assert unadj["rmse"] == pytest.approx(math.sqrt(14 / 3))
    assert unadj["mbe"] == pytest.approx(2.0)
    assert cal["mbe"] == pytest.approx(0.0)
    imp = H.improvement(unadj, cal)
    assert imp["mae_pct"] == pytest.approx(100 * (2.0 - 1 / 3) / 2.0)
    assert imp["abs_mbe_pct"] == pytest.approx(100.0)


def test_slope_not_identifiable_is_reported():
    with pytest.raises(ValueError):
        H.fit_loglog(np.array([2.0, 2.0, 2.0, 2.0]), np.array([1.0, 2.0, 3.0, 4.0]))


def test_greedy_matching_is_one_to_one_and_ordered():
    # (mid, vid, dt, ...) already sorted by priority
    pairs = [(1, 10, 60), (2, 10, 120), (1, 11, 300), (2, 11, 600)]
    out = H.greedy_match(pairs)
    assert [(p[0], p[1]) for p in out] == [(1, 10), (2, 11)]


def test_chronological_split_never_splits_a_day():
    ds = [date(2023, 1, 1)] * 5 + [date(2023, 1, 2)] * 5 + [date(2023, 1, 3)] * 5
    s = H.chronological_split(ds, 0.2, None)
    train = [d for d in ds if d < s]
    test = [d for d in ds if d >= s]
    assert max(train) < min(test)
    assert s == date(2023, 1, 3)
    assert H.chronological_split(ds, 0.2, date(2023, 1, 2)) == date(2023, 1, 2)


def test_config_validation():
    with pytest.raises(ValueError):
        C(unit_grid=0.3)
    with pytest.raises(ValueError):
        C(modis_platforms=[])
    with pytest.raises(ValueError):
        C(tolerance_min=0)


# ---------------------------------------------------------------- synthetic integration fixture
N_DAYS = 60
START = date(2023, 8, 1)


def _v_count(k: int) -> int:
    return 1 + (k % 12)


def _m_count(k: int) -> int:
    return max(1, round(0.5 * _v_count(k)))


def _build(tmp_path, *, modis_time="0600", viirs_time="0610", extra_modis=(), extra_viirs=()):
    """SYNTHETIC: each day k has one matched cell (Aqua at modis_time, SNPP at viirs_time)."""
    mrows, vrows = [], []
    for k in range(N_DAYS):
        d = (START + timedelta(days=k)).isoformat()
        lon0 = 113.05 + (k % 5) * 0.1   # cell centre, 0.1° cells
        for i in range(_v_count(k)):
            vrows.append(viirs_row(lat=round(-2.55 + 0.001 * i, 5), lon=round(lon0, 5), date=d, time=viirs_time, sat="N"))
        for i in range(_m_count(k)):
            mrows.append(modis_row(lat=round(-2.55 + 0.002 * i, 5), lon=round(lon0, 5), date=d, time=modis_time, sat="Aqua"))
    mrows += list(extra_modis)
    vrows += list(extra_viirs)
    write_csv(tmp_path / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_modis.csv", MODIS_HDR, mrows)
    write_csv(tmp_path / "in" / "VIIRS_SNPP_SP" / "SYNTHETIC_TEST_FIXTURE_viirs.csv", VIIRS_HDR, vrows)
    do_import([tmp_path / "in"])


def test_stage2_matches_every_synthetic_pair(env):
    _build(env)
    r = H.harmonize(F(), C())
    s2 = r["stage2"]
    assert s2["class_counts"]["matched"] == N_DAYS
    assert s2["events"] == {"modis": N_DAYS, "viirs": N_DAYS}
    assert s2["dt_minutes"]["median"] == pytest.approx(10.0)
    assert s2["coverage_verification"]["status"] == "not_verified"


def test_stage2_tolerance_excludes_pairs(env):
    _build(env)
    r = H.harmonize(F(), C(tolerance_min=5))
    assert r["stage2"]["class_counts"]["matched"] == 0
    # with the partner instrument reporting nearby within ±5 min? No: 10 min apart, so no proxy evidence either
    assert r["stage2"]["class_counts"]["viirs_only_no_evidence"] == N_DAYS
    assert r["stage3"]["status"] == "insufficient"


def test_terra_is_not_matched_to_aqua_pairs(env):
    _build(env)
    r = H.harmonize(F(), C(modis_platforms=["Terra"]))
    assert r["stage2"]["events"]["modis"] == 0
    assert r["stage2"]["class_counts"]["matched"] == 0
    assert "warning" in r["stage2"]


def test_proxy_evidence_is_distinguished_from_matches(env):
    d = "2023-08-03"
    # SYNTHETIC: VIIRS-only cell 1° away from day-2's matched cell, same overpass time -> proxy
    near = viirs_row(lat=-3.55, lon=113.35, date=d, time="0610", sat="N")
    # VIIRS-only event at 0900: no MODIS detection anywhere within ±30 min -> no evidence
    far_t = viirs_row(lat=-3.55, lon=114.35, date=d, time="0900", sat="N")
    _build(env, extra_viirs=[near, far_t])
    r = H.harmonize(F(), C())
    cc = r["stage2"]["class_counts"]
    assert cc["matched"] == N_DAYS
    assert cc["viirs_only_proxy"] == 1
    assert cc["viirs_only_no_evidence"] == 1
    # 'matched' unit set ignores proxy units; 'matched_plus_proxy' adds exactly the one proxy unit as M = 0
    assert r["stage3"]["n_units"] == N_DAYS
    r2 = H.harmonize(F(), C(unit_set="matched_plus_proxy"))
    assert r2["stage3"]["n_units"] == N_DAYS + 1


def test_stage1_keeps_sensor_values_separate(env):
    _build(env)
    r = H.harmonize(F(), C(), include_units=True)
    by_day = {u["date"]: u for u in r["units"]}
    for k in range(N_DAYS):
        u = by_day[START + timedelta(days=k)]
        assert u["V"] == _v_count(k)
        assert u["M"] == _m_count(k)


def test_stage3_chronological_holdout_and_improvement(env):
    _build(env)
    r = H.harmonize(F(), C())
    s3 = r["stage3"]
    assert s3["status"] == "ok"
    sp = s3["split"]
    assert sp["n_train"] + sp["n_test"] == N_DAYS
    assert sp["train_period"][1] < sp["test_period"][0]
    ev = s3["evaluation"]["held_out"]
    # synthetic MODIS ≈ half of VIIRS: the raw VIIRS value overestimates, calibration must reduce every error measure
    assert ev["unadjusted"]["mbe"] > 0
    assert ev["calibrated"]["mae"] < ev["unadjusted"]["mae"]
    assert ev["calibrated"]["rmse"] < ev["unadjusted"]["rmse"]
    assert abs(ev["calibrated"]["mbe"]) < abs(ev["unadjusted"]["mbe"])
    assert 0 < s3["fit"]["beta"] < 1.2


def test_explicit_split_date(env):
    _build(env)
    r = H.harmonize(F(), C(split_date=date(2023, 9, 10)))
    sp = r["stage3"]["split"]
    assert sp["test_starts"] == "2023-09-10"
    assert sp["n_train"] == 40 and sp["n_test"] == 20


def test_deterministic_results(env):
    _build(env)
    from pyrosync import cache
    a = H.harmonize(F(), C(), include_units=True)
    cache.invalidate()
    b = H.harmonize(F(), C(), include_units=True)
    assert a["stage3"]["fit"] == b["stage3"]["fit"]
    assert [(u["cid"], u["t"], u["M"], u["V"]) for u in a["units"]] == [(u["cid"], u["t"], u["M"], u["V"]) for u in b["units"]]


def test_aoi_filter_applies_before_matching(env):
    _build(env)
    from fastapi.testclient import TestClient
    from pyrosync.api import app
    c = TestClient(app)
    # SYNTHETIC rectangle covering only the first column of cells (lon 113.0–113.1)
    geo = {"type": "Feature", "properties": {"name": "SYNTHETIC test box"},
           "geometry": {"type": "Polygon", "coordinates": [[[113.0, -3.0], [113.099, -3.0], [113.099, -2.0], [113.0, -2.0], [113.0, -3.0]]]}}
    aid = c.post("/api/aoi", json={"geojson": geo}).json()["id"]
    r = H.harmonize(F(aoi=aid), C())
    assert r["stage2"]["class_counts"]["matched"] == N_DAYS // 5


def test_frp_metric(env):
    _build(env)
    r = H.harmonize(F(), C(metric="frp_sum"), include_units=True)
    u = r["units"][0]
    k = (u["date"] - START).days
    assert u["V"] == pytest.approx(3.0 * _v_count(k))
    assert u["M"] == pytest.approx(10.0 * _m_count(k))


def test_api_and_export(env):
    _build(env)
    from fastapi.testclient import TestClient
    from pyrosync.api import app
    c = TestClient(app)
    q = "start=2023-08-01&end=2023-10-31&modis_platforms=Aqua&viirs_series=VIIRS_SNPP&tolerance_min=30"
    r = c.get(f"/api/harmonization?{q}")
    assert r.status_code == 200
    assert r.json()["stage2"]["class_counts"]["matched"] == N_DAYS
    assert c.get(f"/api/harmonization?{q}&unit_grid=0.3").status_code == 422
    z = c.get(f"/api/export/harmonization.zip?{q}")
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert set(zf.namelist()) == {"manifest.json", "harmonization_report.json", "HARMONIZATION_REPORT.md", "units.csv",
                                 "aggregate_report.json", "AGGREGATE_REPORT.md"}  # 1.4 adds the day-level ratio report
    lines = zf.read("units.csv").decode().strip().splitlines()
    assert len(lines) == N_DAYS + 1
    man = json.loads(zf.read("manifest.json"))
    assert man["export_kind"] == "harmonization"
    assert "MAP_KEY" not in zf.read("manifest.json").decode().upper()
    assert "Stage 3" in zf.read("HARMONIZATION_REPORT.md").decode()


def test_existing_daily_unchanged_by_harmonization(env):
    _build(env)
    from pyrosync import query as Q
    before = Q.daily(F())
    H.harmonize(F(), C())
    from pyrosync import cache
    cache.invalidate()
    after = Q.daily(F())
    assert before["series"] == after["series"]
