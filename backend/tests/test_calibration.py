"""Tests for applying a fitted harmonization (v1.2): validity rules, map windows, error map, series and API.
All observations are SYNTHETIC TEST FIXTURES."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from conftest import MODIS_HDR, VIIRS_HDR, do_import, modis_row, viirs_row, write_csv
from pyrosync import cache
from pyrosync import calibration as CAL
from pyrosync import harmonize as H
from pyrosync import query as Q
from pyrosync.query import Filters

START = date(2023, 8, 1)
N_DAYS = 60
N_CELLS = 10


def F(**kw):
    base = {"start": START, "end": START + timedelta(days=N_DAYS - 1), "platforms": ["Aqua", "SNPP"]}
    base.update(kw)
    return Filters(**base)


def _v(k: int, i: int) -> int:
    return 1 + ((7 * k + 3 * i) % 12)


def _m(k: int, i: int) -> int:
    return max(1, round(0.5 * _v(k, i)))


def _big(tmp_path, extra_viirs=()):
    """SYNTHETIC: N_CELLS matched cells per day (Aqua 06:00, S-NPP 06:10), MODIS ≈ half of VIIRS."""
    mrows, vrows = [], []
    for k in range(N_DAYS):
        d = (START + timedelta(days=k)).isoformat()
        for i in range(N_CELLS):
            lon = round(112.05 + 0.1 * i, 5)
            for j in range(_v(k, i)):
                vrows.append(viirs_row(lat=round(-2.55 + 0.001 * j, 5), lon=lon, date=d, time="0610", sat="N"))
            for j in range(_m(k, i)):
                mrows.append(modis_row(lat=round(-2.55 + 0.002 * j, 5), lon=lon, date=d, time="0600", sat="Aqua"))
    vrows += list(extra_viirs)
    write_csv(tmp_path / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_modis.csv", MODIS_HDR, mrows)
    write_csv(tmp_path / "in" / "VIIRS_SNPP_SP" / "SYNTHETIC_TEST_FIXTURE_viirs.csv", VIIRS_HDR, vrows)
    do_import([tmp_path / "in"])


# SYNTHETIC VIIRS-only event far from any MODIS detection in time (no evidence), on day 50
LONE = viirs_row(lat=-2.55, lon=114.05, date=(START + timedelta(days=50)).isoformat(), time="1500", sat="N")


def test_validity_passes_on_consistent_synthetic_data(env):
    _big(env)
    r = H.harmonize(F(), H.HarmonizeConfig())
    v = r["validity"]
    assert v["status"] == "passes", v
    assert [c["id"] for c in v["checks"]] == ["fitted", "measurement", "held_out_size", "beats_unadjusted", "beats_constant", "slope"]
    assert all(c["passed"] for c in v["checks"])
    ho = r["stage3"]["evaluation"]["held_out"]
    assert ho["training_median_reference"]["n"] == r["stage3"]["split"]["n_test"]


def test_validity_fails_for_frp_and_small_samples(env):
    _big(env)
    frp = H.harmonize(F(), H.HarmonizeConfig(metric="frp_sum"))
    assert frp["validity"]["status"] == "not_validated"
    assert not next(c for c in frp["validity"]["checks"] if c["id"] == "measurement")["passed"]
    small = H.harmonize(F(end=START + timedelta(days=9)), H.HarmonizeConfig())  # 100 units -> 20 held out
    assert small["validity"]["status"] == "not_validated"
    assert not next(c for c in small["validity"]["checks"] if c["id"] == "held_out_size")["passed"]
    c = CAL.core(F(), H.HarmonizeConfig(metric="frp_sum"))
    m = CAL.map_window(c, START + timedelta(days=55), 1, "all", 0.5, 20)
    assert m["model"]["calibrated_available"] is False
    assert all(x["cal"] is None and x["value_cal"] is None for x in m["cells"])
    assert m["totals"]["cal"] is None


def test_report_is_identical_through_core_and_units_path(env):
    _big(env)
    cfg = H.HarmonizeConfig()
    a = H.harmonize(F(), cfg)
    b = H.harmonize(F(), cfg, include_units=True)
    assert a is CAL.core(F(), cfg).report
    assert a["stage3"]["fit"] == b["stage3"]["fit"]
    assert a["stage3"]["evaluation"] == b["stage3"]["evaluation"]
    assert a["validity"] == b["validity"]


def test_map_window_values(env):
    _big(env, extra_viirs=[LONE])
    cfg = H.HarmonizeConfig()
    c = CAL.core(F(), cfg)
    k = 50
    day = START + timedelta(days=k)
    m = CAL.map_window(c, day, 1, "all", 0.5, 5)
    a, b = c.alpha, c.beta
    exp_cal = sum(float(H.predict(a, b, np.array([_v(k, i)]))[0]) for i in range(N_CELLS)) + float(H.predict(a, b, np.array([1.0]))[0])
    t = m["totals"]
    assert t["modis"] == sum(_m(k, i) for i in range(N_CELLS))
    assert t["viirs"] == sum(_v(k, i) for i in range(N_CELLS)) + 1
    assert t["pairs"] == N_CELLS and len(m["pairs"]) == N_CELLS
    assert t["cal"] == pytest.approx(exp_cal)
    # the lone VIIRS event is outside the 'matched' model domain
    assert t["cal_domain"] == pytest.approx(exp_cal - float(H.predict(a, b, np.array([1.0]))[0]))
    lone = next(x for x in m["cells"] if x["modis_events"] == 0)
    assert lone["viirs_events_in_domain"] == 0 and lone["pairs"] == 0
    # the same totals as the app's per-sensor daily detections (original data)
    d = Q.daily(H._sensor_filters(F(), cfg))
    i = d["dates"].index(day.isoformat())
    assert t["modis"] == d["series"]["MODIS"]["detections"][i]
    assert t["viirs"] == d["series"]["VIIRS_SNPP"]["detections"][i]
    for p in m["pairs"]:
        assert p["dt_min"] == pytest.approx(10.0)
        assert p["set"] == "test"
    assert m["window"]["period_role"] == "held_out"
    assert CAL.map_window(c, START + timedelta(days=3), 1, "all", 0.5, 5)["window"]["period_role"] == "training"
    seven = CAL.map_window(c, day, 7, "all", 0.5, 5)
    assert seven["totals"]["viirs"] == sum(_v(kk, i) for kk in range(k - 6, k + 1) for i in range(N_CELLS)) + 1


def test_error_cells(env):
    _big(env, extra_viirs=[LONE])
    c = CAL.core(F(), H.HarmonizeConfig())
    with pytest.raises(ValueError):
        CAL.error_cells(c, 0.25, 20)  # 0.25 is not a multiple of the 0.1° comparison grid
    with pytest.raises(ValueError):
        CAL.error_cells(c, 0.5, 7)
    e = CAL.error_cells(c, 0.1, 10)
    n_test = c.report["stage3"]["split"]["n_test"]
    assert sum(x["n_test"] for x in e["cells"]) == n_test
    tested = [x for x in e["cells"] if x["n_test"] > 0]
    assert len(tested) == N_CELLS
    for x in tested:
        assert x["status"] == ("validated" if x["n_test"] >= 10 else "too_few")
    # the lone VIIRS-only cell has activity but no held-out unit
    assert any(x["status"] == "no_held_out" for x in e["cells"])
    # per-cell MAE recomputed by hand for one cell
    x = tested[0]
    sel = (c.u_ci == x["ci"]) & (c.u_cj == x["cj"]) & c.u_test
    p = H.predict(c.alpha, c.beta, c.u_V[sel])
    assert x["mae_cal"] == pytest.approx(float(np.mean(np.abs(p - c.u_M[sel]))))
    # coarser regions hold the same held-out units
    e1 = CAL.error_cells(c, 1.0, 10)
    assert sum(x["n_test"] for x in e1["cells"]) == n_test
    assert e1["summary"]["held_out_units"] == n_test


def test_series_matches_daily_and_gates_totals(env):
    _big(env, extra_viirs=[LONE])
    cfg = H.HarmonizeConfig(test_fraction=0.5)  # 30 held-out days, the minimum for the daily-total rules
    c = CAL.core(F(), cfg)
    s = CAL.series(c, "day", "domain")
    d = Q.daily(H._sensor_filters(F(), cfg))
    assert s["modis"] == [float(x) for x in d["series"]["MODIS"]["detections"]]
    assert s["viirs"] == [float(x) for x in d["series"]["VIIRS_SNPP"]["detections"]]
    tv = s["totals_validity"]
    # every MODIS event has a partner and M ≈ M̂, so the model-domain totals reproduce the MODIS level
    assert tv["status"] == "passes", tv
    assert s["calibrated"] is not None and len(s["calibrated"]) == N_DAYS
    h = s["check"]["held_out"]
    assert 0.8 <= h["ratio_calibrated_to_modis"] <= 1.25
    mo = CAL.series(c, "month", "domain")
    assert mo["dates"] == ["2023-08", "2023-09"]
    assert sum(mo["known_days"]) == N_DAYS
    assert sum(mo["modis"]) == pytest.approx(sum(s["modis"]))


def test_series_hides_calibrated_when_totals_fail(env):
    # SYNTHETIC: many VIIRS-only events (no MODIS anywhere near) inflate the all-events totals far above MODIS
    extra = [viirs_row(lat=-2.55, lon=round(115.05 + 0.1 * j, 5), date=(START + timedelta(days=k)).isoformat(), time="1500", sat="N")
             for k in range(N_DAYS) for j in range(30)]
    _big(env, extra_viirs=extra)
    c = CAL.core(F(), H.HarmonizeConfig())
    assert c.valid
    s = CAL.series(c, "day", "all")
    assert s["totals_validity"]["status"] == "not_validated"
    assert not next(x for x in s["totals_validity"]["checks"] if x["id"] == "level")["passed"]
    assert s["calibrated"] is None
    assert s["check"]["held_out"]["ratio_calibrated_to_modis"] > 1.25


def test_api_endpoints_and_original_data_unchanged(env):
    _big(env)
    from fastapi.testclient import TestClient
    from pyrosync.api import app
    cl = TestClient(app)
    q = "start=2023-08-01&end=2023-09-29&modis_platforms=Aqua&viirs_series=VIIRS_SNPP"
    before = Q.daily(F())
    r = cl.get(f"/api/harmonization/map?{q}&date=2023-09-20&mode=1&scope=all&err_grid=0.5&min_n=20")
    assert r.status_code == 200
    j = r.json()
    assert j["totals"]["pairs"] == N_CELLS and j["model"]["calibrated_available"] is True
    assert set(j["suggested_days"]) == {"training", "held_out"}
    assert cl.get(f"/api/harmonization/errors?{q}&err_grid=0.5&min_n=20").status_code == 200
    assert cl.get(f"/api/harmonization/errors?{q}&err_grid=0.3").status_code == 422
    assert cl.get(f"/api/harmonization/map?{q}&date=2023-09-20&scope=bad").status_code == 422
    s = cl.get(f"/api/harmonization/series?{q}&agg=month&scope=domain")
    assert s.status_code == 200 and s.json()["agg"] == "month"
    assert cl.get(f"/api/harmonization?{q}").json()["validity"]["status"] == "passes"
    cache.invalidate()
    assert Q.daily(F())["series"] == before["series"]
