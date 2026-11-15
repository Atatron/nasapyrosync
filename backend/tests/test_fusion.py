"""Tests for the 1.5 multi-sensor historical fusion, the circle (Analyze Location) AOI and the 0.25° grid.

All observations are SYNTHETIC TEST FIXTURES written to an isolated temporary data directory. They check software behaviour
(availability, no raw summation, no leakage, missing ≠ zero, API contracts); they make no scientific performance claim.
"""
from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import MODIS_HDR, VIIRS_HDR, do_import, modis_row, viirs_row, write_csv
from pyrosync import aoi as AOI
from pyrosync.ingest import Declared
from pyrosync import cache
from pyrosync import fusion as FU
from pyrosync import query as Q
from pyrosync.analysis import series_values
from pyrosync.query import Filters

START = date(2019, 1, 1)
N_DAYS = 5 * 365
END = START + timedelta(days=N_DAYS - 1)
N20_FROM = date(2019, 7, 1)  # NOAA-20 joins half a year after the others (availability + transition)
TERRA_TO = date(2020, 12, 31)  # Terra's record ends early: too few years for its pairwise gate
DRIFT_FROM = date(2023, 6, 1)  # inside the held-out period (last 20 % of active days)
EXTRA = 10  # days after the last import: unknown, never zero
C_SNPP, C_N20 = 0.5, 1 / 3  # SYNTHETIC truth: S-NPP = 2 × Aqua, NOAA-20 = 3 × Aqua


def F(**kw):
    base = {"start": START, "end": END + timedelta(days=EXTRA), "platforms": list(Q.ALL_PLATFORMS)}
    base.update(kw)
    return Filters(**base)


def _aqua(k: int) -> int:
    if k % 37 == 0 and k > 0:
        return 0  # a reported zero day for every platform
    return 1 + (k * 7) % 5 + (8 if k % 61 == 0 else 0)


def _build(root, drift: bool = False):
    """SYNTHETIC: Aqua a_k, Terra a_k until TERRA_TO, S-NPP 2·a_k (4·a_k from DRIFT_FROM when drift), NOAA-20 3·a_k from N20_FROM.
    Points alternate between two 0.1° cells so the map has more than one cell."""
    m, s, n = [], [], []
    for k in range(N_DAYS):
        dd = START + timedelta(days=k)
        d = dd.isoformat()
        a = _aqua(k)

        def pt(j, step):
            return round(-2.55 + step * j, 5), (112.05 if j % 2 == 0 else 112.35)
        for j in range(a):
            la, lo = pt(j, 0.002)
            m.append(modis_row(lat=la, lon=lo, date=d, time="0600", sat="Aqua"))
            if dd <= TERRA_TO:
                m.append(modis_row(lat=la, lon=lo, date=d, time="0300", sat="Terra"))
        for j in range(a * (4 if drift and dd >= DRIFT_FROM else 2)):
            la, lo = pt(j, 0.001)
            s.append(viirs_row(lat=la, lon=lo, date=d, time="0610", sat="N"))
        if dd >= N20_FROM:
            for j in range(3 * a):
                la, lo = pt(j, 0.001)
                n.append(viirs_row(lat=la, lon=lo, date=d, time="0520", sat="N20"))
    write_csv(root / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_modis.csv", MODIS_HDR, m)
    write_csv(root / "in" / "VIIRS_SNPP_SP" / "SYNTHETIC_TEST_FIXTURE_snpp.csv", VIIRS_HDR, s)
    write_csv(root / "in" / "VIIRS_NOAA20_SP" / "SYNTHETIC_TEST_FIXTURE_n20.csv", VIIRS_HDR, n)
    # declared request intervals (as a FIRMS area request records them): a day inside one without rows is a reported zero
    decl = [Declared(start=START, end=END, origin="cli-declared", series="MODIS"),
            Declared(start=START, end=END, origin="cli-declared", series="VIIRS_SNPP"),
            Declared(start=N20_FROM, end=END, origin="cli-declared", series="VIIRS_N20")]
    do_import([root / "in"], declared=decl)


def _fresh_store(tmp_path, name):
    from pyrosync import db
    from pyrosync.config import Settings, set_settings
    db.close_conn()
    s2 = Settings(data_dir=tmp_path / name)
    s2.keep_raw_uploads = False
    s2.offline = True
    s2.firms_map_key = ""
    set_settings(s2)
    cache.invalidate()


@pytest.fixture()
def built(env):
    _build(env)
    return env


# ------------------------------------------------------------------ model, availability, no raw summation
def test_coefficients_eligibility_and_gate(built):
    m = FU.model(F())
    assert m["reference"] == "Aqua" and m["reference_available"]
    assert m["coefficients"]["SNPP"] == pytest.approx(C_SNPP)
    assert m["coefficients"]["N20"] == pytest.approx(C_N20)
    assert "N21" not in m["eligible"]  # no NOAA-21 data: never used, never zero-filled
    assert m["pairs"]["N21"]["status"] == "insufficient"
    # Terra has two years only: its pairwise 1.4 gate cannot pass, so it is not fused
    assert "Terra" not in m["eligible"] and m["pairs"]["Terra"]["used"] is False
    assert m["gate"]["status"] == "passes", [c for c in m["gate"]["checks"] if not c["passed"]]
    v = m["validation"]
    ho = v["held_out"]
    assert ho["fusion_leave_reference_out"]["ratio"] == pytest.approx(1.0)
    assert ho["fusion_leave_reference_out"]["mae"] < ho["raw_unadjusted_mean"]["mae"]
    assert ho["fusion_leave_reference_out"]["mae"] < ho["constant_train_mean"]["mae"]
    assert len(v["rolling_origin"]["years"]) >= 3
    assert {t["platform"] for t in v["transitions"]["platforms"]} == {"SNPP", "N20"}
    assert m["coverage"]["status"] == "not_verified"


def test_fused_is_calibrated_mean_never_raw_sum(built):
    d = FU.series(F(), "day")
    i = (date(2021, 3, 3) - START).days
    aqua = d["observed"]["Aqua"][i]
    assert aqua and aqua > 0
    raw_sum = sum(d["observed"][p][i] for p in ("Aqua", "SNPP", "N20"))
    assert d["fused"][i] == pytest.approx(aqua)  # mean(a, 0.5·2a, ⅓·3a) = a
    assert d["fused"][i] != pytest.approx(raw_sum)
    assert d["n_platforms"][i] == 3 and set(d["contributors"][i]) == {"Aqua", "SNPP", "N20"}
    vals = [d["calibrated"][p][i] for p in d["contributors"][i]]
    assert d["fused"][i] == pytest.approx(sum(vals) / len(vals))


def test_platform_availability_is_respected(built):
    d = FU.series(F(), "day")
    before = (N20_FROM - START).days - 3
    assert "N20" not in d["contributors"][before]
    assert d["observed"]["N20"][before] is None  # outside NOAA-20's record: unknown, not zero
    assert d["observed"]["N21"][before] is None
    after = (N20_FROM - START).days + 3
    assert "N20" in d["contributors"][after]
    late = (TERRA_TO - START).days + 10
    assert d["observed"]["Terra"][late] is None
    recs = FU.platform_records()
    assert recs["Terra"][1] == TERRA_TO and recs["N20"][0] == N20_FROM


def test_missing_is_not_zero(built):
    dl = FU.daily_like(F())
    s = dl["series"]["FUSED"]
    zero_k = 37 * 10
    assert s["status"][zero_k] == "zero_reported" and s["detections"][zero_k] == 0
    # after the last imported day: the same status the per-sensor daily view uses, and no value
    assert all(st == "outside_range" for st in s["status"][-EXTRA:])
    assert Q.daily(F())["series"]["MODIS"]["status"][-EXTRA:] == s["status"][-EXTRA:]
    assert all(v is None for v in s["detections"][-EXTRA:])
    mon = FU.series(F(), "month")
    assert sum(mon["known_days"]) == N_DAYS
    # series_values feeds calendar/elevated/Insights; FUSED is detections only
    dates, vals, sts = series_values(dl, "FUSED", "detections")
    assert len(vals) == N_DAYS + EXTRA
    with pytest.raises(ValueError):
        series_values(dl, "FUSED", "cells")


def test_model_independent_of_display_range(built):
    a = FU.model(F())
    b = FU.model(F(start=date(2022, 1, 1), end=date(2022, 3, 31)))
    assert a["coefficients"] == b["coefficients"] and a["validation"]["split"] == b["validation"]["split"]
    s = FU.series(F(start=date(2022, 1, 1), end=date(2022, 3, 31)), "day")
    assert s["dates"][0] == "2022-01-01" and len(s["dates"]) == 90


def test_held_out_data_never_used_in_fit(built, tmp_path):
    base = FU.model(F())
    _fresh_store(tmp_path, "data2")
    _build(tmp_path / "drift", drift=True)
    d = FU.model(F())
    assert d["validation"]["split"] == base["validation"]["split"]
    assert DRIFT_FROM.isoformat() >= d["validation"]["split"]
    # the S-NPP pair fit uses only days before its split: identical with and without the held-out drift
    assert d["pairs"]["SNPP"]["c"] == pytest.approx(base["pairs"]["SNPP"]["c"])
    assert d["validation"]["train_coefficients"]["N20"] == pytest.approx(base["validation"]["train_coefficients"]["N20"])
    # and the drift is caught: S-NPP fails its pairwise gate, so it is no longer fused
    assert d["pairs"]["SNPP"]["gate"]["status"] == "not_validated"
    assert "SNPP" not in d["eligible"]


def test_frame_cells_add_up_to_fused_total(built):
    f = F()
    for mode in (1, 30):
        fr = FU.frame_cells(f, date(2021, 3, 3), mode, 0.1)
        assert fr["label"] == "Experimental Harmonized Activity Index" and fr["cells_validated"] is False
        assert len(fr["cells"]) == 2
        assert sum(c["value"] for c in fr["cells"]) == pytest.approx(fr["fused_total"], rel=1e-3)
    fr25 = FU.frame_cells(f, date(2021, 3, 3), 1, 0.25)
    assert fr25["grid_size"] == 0.25 and len(fr25["cells"]) == 2  # 112.05 and 112.35 lie in different 0.25° cells


def test_platform_gap_days_are_unknown(env):
    """A day on which one platform (Terra) has no row anywhere while its typical day has many is unknown for that platform,
    even though the MODIS series as a whole (Aqua) has detections that day."""
    rows = []
    gap = date(2022, 1, 20)
    for k in range(40):
        d = date(2022, 1, 1) + timedelta(days=k)
        rows += [modis_row(lat=round(-2.5 + 0.001 * j, 4), lon=112.05, date=d.isoformat(), sat="Aqua") for j in range(25)]
        if d != gap:
            rows += [modis_row(lat=round(-2.5 + 0.001 * j, 4), lon=112.05, date=d.isoformat(), sat="Terra", time="0300") for j in range(25)]
    do_import([write_csv(env / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_gap.csv", MODIS_HDR, rows)],
              declared=[Declared(start=date(2022, 1, 1), end=date(2022, 2, 9), origin="cli-declared", series="MODIS")])
    assert FU.platform_gap_days()["Terra"] == {gap}
    assert FU.platform_gap_days().get("Aqua", set()) == set()
    f = Filters(start=date(2022, 1, 1), end=date(2022, 2, 9), platforms=["Terra", "Aqua"])
    arr = FU.daily_platform_arrays(f)
    i = (gap - arr["dates"][0]).days
    assert not arr["K"]["Terra"][i] and arr["K"]["Terra"][i - 1] and arr["K"]["Aqua"][i]
    assert Q.daily(f)["series"]["MODIS"]["status"][i] == "detections"


# ------------------------------------------------------------------ circle AOI (Analyze Location)
def _gc_km(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    dl = math.radians(lo2 - lo1)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * AOI.EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def test_circle_geometry_is_geodesic():
    for lat in (-2.2, 45.0, 80.0):
        poly = AOI.circle_polygon(lat, 113.9, 50)
        xs, ys = poly.exterior.coords.xy
        dist = [_gc_km(lat, 113.9, y, x) for x, y in zip(xs, ys)]
        assert max(abs(x - 50) for x in dist) < 1e-6
        assert len(xs) == AOI.CIRCLE_VERTICES + 1
    assert AOI.parse_circle("circle:-2.2,113.9,50") == (-2.2, 113.9, 50.0)
    assert AOI.circle_id(-2.123456, 113.987654, 12.3456) == "circle:-2.1235,113.9877,12.3"
    for bad in ("circle:95,10,5", "circle:0,0,0", "circle:0,0,5000", "circle:a,b,c", "circle:1,2"):
        with pytest.raises(AOI.AOIError):
            AOI.parse_circle(bad)


def test_circle_aoi_filters_points_and_fuses(env):
    rows = [modis_row(lat=-2.2, lon=113.9, sat="Aqua"),  # centre
            modis_row(lat=-2.2, lon=113.9 + 0.4, sat="Aqua"),  # ~44 km east: inside 50 km
            modis_row(lat=-2.2, lon=113.9 + 0.6, sat="Aqua")]  # ~67 km east: outside
    do_import([write_csv(env / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_circle.csv", MODIS_HDR, rows)])
    f = Filters(start=date(2023, 9, 15), end=date(2023, 9, 15), platforms=["Aqua"], aoi="circle:-2.2,113.9,50")
    d = Q.daily(f)
    assert d["series"]["MODIS"]["detections"] == [2]
    desc = AOI.describe("circle:-2.2,113.9,50")
    assert desc["kind"] == "circle" and desc["radius_km"] == 50


def test_grid_025_is_accepted(env):
    do_import([write_csv(env / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_g.csv", MODIS_HDR,
                         [modis_row(lat=-2.51, lon=113.51), modis_row(lat=-2.6, lon=113.7)])])
    f = Filters(start=date(2023, 9, 15), end=date(2023, 9, 15), platforms=["Terra"], grid=0.25)
    assert Q.daily(f)["series"]["MODIS"]["cells"] == [1]
    assert Q.daily(f.model_copy(update={"grid": 0.1}))["series"]["MODIS"]["cells"] == [2]
    with pytest.raises(Exception):
        Filters(start=date(2023, 9, 15), end=date(2023, 9, 15), grid=0.3)


# ------------------------------------------------------------------ API
QS = f"start=2021-01-01&end=2021-12-31&platforms={','.join(Q.ALL_PLATFORMS)}"


def test_fusion_api(built):
    c = TestClient(app_())
    r = c.get(f"/api/fusion?{QS}").json()
    assert r["gate"]["status"] == "passes" and r["effective"]["status"] == "passes"
    s = c.get(f"/api/fusion/series?{QS}&agg=month").json()
    assert s["dates"][0] == "2021-01" and len(s["dates"]) == 12 and s["validation_status"] == "passes"
    assert c.get(f"/api/fusion/series?{QS}&agg=week").status_code == 422
    mp = c.get(f"/api/fusion/map?{QS}&date=2021-03-03&mode=1").json()
    assert mp["label"] == "Experimental Harmonized Activity Index" and mp["cells"]
    assert c.get(f"/api/fusion/map?{QS}&date=2021-03-03&mode=5").status_code == 422
    rg = c.get(f"/api/fusion/regions?{QS}&grid_deg=1&min_days=5")
    assert rg.status_code == 200
    assert c.get(f"/api/fusion/regions?{QS}&grid_deg=3").status_code == 422
    d = c.get(f"/api/daily?{QS}&fused=true").json()
    assert "FUSED" in d["series"] and "MODIS" in d["series"]
    assert len(d["series"]["FUSED"]["detections"]) == 365
    assert "FUSED" not in c.get(f"/api/daily?{QS}").json()["series"]
    # FUSED through the analysis and Insights endpoints (detections only)
    for u in ("weeks", "rankings", "elevated", "baseline"):
        assert c.get(f"/api/{u}?{QS}&series=FUSED&metric=detections").status_code == 200, u
        assert c.get(f"/api/{u}?{QS}&series=FUSED&metric=cells").status_code == 422, u
    for u in ("regime", "anomaly", "recurrence", "critical", "years"):
        assert c.get(f"/api/insights/{u}?{QS}&series=FUSED").status_code == 200, u
    assert c.get(f"/api/insights/now?{QS}&series=FUSED").status_code == 422
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/export/fusion.zip?{QS}").content))
    names = set(z.namelist())
    assert {"fusion_report.json", "FUSION_REPORT.md", "fused_daily.csv", "manifest.json"} <= names
    man = json.loads(z.read("manifest.json"))
    assert man  # a non-empty manifest describing the export
    rep = json.loads(z.read("fusion_report.json"))
    assert rep["method_version"] == FU.FUSION_VERSION and rep["coefficients"]["SNPP"] == pytest.approx(C_SNPP)
    csv_lines = z.read("fused_daily.csv").decode().splitlines()
    assert len(csv_lines) == 366


def test_circle_api_errors(env):
    c = TestClient(app_())
    assert c.get("/api/aoi/circle:-2.2,113.9,50").json()["properties"]["kind"] == "circle"
    for bad in ("circle:95,10,50", "circle:0,0,0", "circle:x,y,z"):
        assert c.get(f"/api/aoi/{bad}").status_code == 422, bad


def app_():
    from pyrosync.api import app
    return app




def test_unexpected_error_is_json_and_redacted(env, monkeypatch, caplog):
    """An unexpected server error returns a generic JSON 500; the log line never contains the FIRMS key."""
    from pyrosync import api as API
    from pyrosync.config import get_settings
    get_settings().firms_map_key = "SYNTHETICKEY0123456789"

    def boom(*a, **k):
        raise RuntimeError("failed with key SYNTHETICKEY0123456789")
    monkeypatch.setattr(FU, "report", boom)
    c = TestClient(app_(), raise_server_exceptions=False)
    with caplog.at_level("ERROR", logger="pyrosync"):
        r = c.get("/api/fusion?start=2023-01-01&end=2023-01-02")
    assert r.status_code == 500 and r.json()["ref"]
    assert "SYNTHETICKEY" not in r.text
    line = " ".join(rec.getMessage() for rec in caplog.records if "pyrosync 500" in rec.getMessage())
    assert "RuntimeError" in line and "[redacted]" in line and "SYNTHETICKEY" not in line
    assert API._redact("x SYNTHETICKEY0123456789 y") == "x [redacted] y"
