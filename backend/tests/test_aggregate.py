"""Tests for the day-level (aggregate) calibration of 1.4: ratio fit, chronological hold-out, stability gate, series, map and API.
All observations are SYNTHETIC TEST FIXTURES written to an isolated temporary data directory."""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

import numpy as np
import pytest

from conftest import MODIS_HDR, VIIRS_HDR, do_import, modis_row, viirs_row, write_csv
from pyrosync import aggregate as A
from pyrosync import cache
from pyrosync import harmonize as H
from pyrosync import query as Q
from pyrosync.query import Filters

START = date(2019, 1, 1)
N_DAYS = 5 * 365  # five synthetic years: enough for three rolling-origin test years
DRIFT_FROM = date(2023, 3, 1)  # after the chronological split (last 20 % of active days starts 2022-12-31)
EXTRA = 10  # days after the last observation, inside the filters but outside every import: unknown coverage


def F(**kw):
    base = {"start": START, "end": START + timedelta(days=N_DAYS - 1 + EXTRA), "platforms": ["Aqua", "SNPP"]}
    base.update(kw)
    return Filters(**base)


def _nv(k: int) -> int:
    return 2 * (1 + (k * 7) % 5) + (8 if k % 61 == 0 else 0)  # occasional high-activity days


def _build(tmp_path, drift: bool = False):
    """SYNTHETIC: one cell per day; MODIS (Aqua) = exactly half of S-NPP, or (drift=True) equal to S-NPP from DRIFT_FROM on."""
    mrows, vrows = [], []
    for k in range(N_DAYS):
        dd = START + timedelta(days=k)
        d = dd.isoformat()
        nv = _nv(k)
        nm = nv if (drift and dd >= DRIFT_FROM) else nv // 2
        for j in range(nv):
            vrows.append(viirs_row(lat=round(-2.55 + 0.001 * j, 5), lon=112.05, date=d, time="0610", sat="N"))
        for j in range(nm):
            mrows.append(modis_row(lat=round(-2.55 + 0.002 * j, 5), lon=112.05, date=d, time="0600", sat="Aqua"))
    write_csv(tmp_path / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_modis.csv", MODIS_HDR, mrows)
    write_csv(tmp_path / "in" / "VIIRS_SNPP_SP" / "SYNTHETIC_TEST_FIXTURE_viirs.csv", VIIRS_HDR, vrows)
    do_import([tmp_path / "in"])


CFG = H.HarmonizeConfig(viirs_series="VIIRS_SNPP", modis_platforms=["Aqua"])


def test_ratio_fit_holdout_and_gate_pass(env):
    _build(env)
    rep = A.report(F(), CFG)
    ev = rep["quantities"]["detections"]
    arr = A.daily_arrays(F(), CFG)
    s = (date.fromisoformat(rep["split"]) - START).days
    tr = arr["known"] & (np.arange(len(arr["dates"])) < s)
    # c is Σ MODIS / Σ VIIRS over known training days only
    assert ev["c"] == pytest.approx(arr["M"][tr].sum() / arr["V"][tr].sum())
    assert ev["c"] == pytest.approx(0.5)
    assert ev["train_period"][1] < rep["split"] <= ev["held_out_period"][0]
    assert ev["gate"]["status"] == "passes", ev["gate"]
    assert all(c["passed"] for c in ev["gate"]["checks"])
    assert len(ev["rolling_origin"]["years"]) >= A.MIN_ROLL_YEARS
    ho = ev["held_out"]
    assert ho["day_ratio"]["ratio"] == pytest.approx(1.0)
    assert ho["day_ratio"]["mae"] < ho["raw_viirs"]["mae"] and ho["day_ratio"]["mae"] < ho["constant_train_mean"]["mae"]
    assert rep["coverage"]["status"] == "not_verified"


def test_held_out_days_never_used_in_fit_and_drift_fails_gate(env, tmp_path):
    _build(env)
    base = A.report(F(), CFG)
    # same history with MODIS doubled in the held-out period only: c must be identical, and the gate must fail
    from pyrosync import db
    from pyrosync.config import Settings, set_settings
    db.close_conn()
    s2 = Settings(data_dir=tmp_path / "data2")
    s2.keep_raw_uploads = False
    s2.offline = True
    s2.firms_map_key = ""
    set_settings(s2)
    cache.invalidate()
    _build(tmp_path / "drift", drift=True)
    assert base["split"] <= DRIFT_FROM.isoformat()  # the drift lies entirely in the held-out period
    d = A.report(F(), CFG)
    assert d["split"] == base["split"]
    assert d["quantities"]["detections"]["c"] == pytest.approx(base["quantities"]["detections"]["c"])
    g = d["quantities"]["detections"]["gate"]
    assert g["status"] == "not_validated"
    failed = {c["id"] for c in g["checks"] if not c["passed"]}
    assert "level" in failed
    ser = A.series(F(), CFG, "day", "detections")
    assert ser["calibrated"] is None and ser["band"] is None  # never drawn when the gate fails


def test_series_unknown_days_and_month_totals(env):
    _build(env)
    d = A.series(F(), CFG, "day", "detections")
    assert len(d["dates"]) == N_DAYS + EXTRA
    assert d["calibrated"] is not None
    # days after the last import have no known coverage: empty, never zero
    assert all(x is None for x in d["modis"][-EXTRA:]) and all(x is None for x in d["viirs"][-EXTRA:])
    assert all(x is None for x in d["calibrated"][-EXTRA:])
    daily = Q.daily(H._sensor_filters(F(), CFG))
    assert d["modis"][:N_DAYS] == [float(x) for x in daily["series"]["MODIS"]["detections"][:N_DAYS]]
    c = d["evaluation"]["c"]
    assert d["calibrated"][5] == pytest.approx(c * d["viirs"][5])
    lo, hi = d["band"][5]
    assert lo <= d["calibrated"][5] <= hi
    m = A.series(F(), CFG, "month", "detections")
    assert m["dates"][0] == "2019-01" and sum(m["known_days"]) == N_DAYS
    assert sum(x for x in m["modis"] if x is not None) == pytest.approx(sum(x for x in d["modis"] if x is not None))
    with pytest.raises(ValueError):
        A.series(F(), CFG, "week", "detections")


def test_insufficient_history_is_not_validated(env):
    _build(env)
    short = F(start=date(2022, 6, 1))
    g = A.report(short, CFG)["quantities"]["detections"]["gate"]
    assert g["status"] != "passes"
    assert not next(c for c in g["checks"] if c["id"] == "roll_years")["passed"]


def test_api_endpoints_zip_and_original_data_unchanged(env):
    _build(env)
    from fastapi.testclient import TestClient
    from pyrosync.api import app
    cl = TestClient(app)
    end = (START + timedelta(days=N_DAYS - 1 + EXTRA)).isoformat()
    q = f"start={START}&end={end}&modis_platforms=Aqua&viirs_series=VIIRS_SNPP&tolerance_min=30"
    before = Q.daily(F())
    r = cl.get(f"/api/harmonization/aggregate?{q}")
    assert r.status_code == 200 and r.json()["method_version"] == A.AGG_VERSION
    assert r.json()["quantities"]["detections"]["gate"]["status"] == "passes"
    s = cl.get(f"/api/harmonization/aggregate/series?{q}&agg=month&quantity=detections")
    assert s.status_code == 200 and s.json()["calibrated"] is not None
    assert cl.get(f"/api/harmonization/aggregate/series?{q}&agg=week").status_code == 422
    assert cl.get(f"/api/harmonization/aggregate/regions?{q}&err_grid=0.5&min_days=20").status_code == 200
    assert cl.get(f"/api/harmonization/aggregate/regions?{q}&min_days=7").status_code == 422
    mp = cl.get(f"/api/harmonization/map?{q}&date=2023-09-20&mode=1&scope=all&err_grid=0.5&min_n=20").json()
    assert mp["ratio_model"]["available"] is True and mp["ratio_model"]["c"] == pytest.approx(0.5)
    assert any("value_ratio" in x for x in mp["cells"]) if mp.get("cells") else True
    z = cl.get(f"/api/export/harmonization.zip?{q}")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.endswith("aggregate_report.json") for n in names) and any(n.endswith("AGGREGATE_REPORT.md") for n in names)
    cache.invalidate()
    assert Q.daily(F())["series"] == before["series"]
