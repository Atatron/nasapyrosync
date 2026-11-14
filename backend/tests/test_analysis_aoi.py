"""Analysis and AOI tests on SYNTHETIC TEST FIXTURES (isolated data dir)."""
from datetime import date, timedelta

import pytest

from pyrosync import aoi as A, analysis as AN, ingest, query as Q
from conftest import MODIS_HDR, do_import, modis_row, write_csv


# ---------------------------------------------------------------- ISO weeks / leap day
def test_iso_week_year_boundaries(env):
    rows = [modis_row(date=d) for d in ("2020-12-31", "2021-01-01", "2021-01-03", "2021-01-04", "2024-12-30")]
    do_import([write_csv(env / "in" / "MODIS_SP" / "x.csv", MODIS_HDR, rows)],
              declared=[ingest.Declared(date(2020, 12, 28), date(2025, 1, 5), "cli-declared", "MODIS", "SP")])
    f = Q.Filters(start=date(2020, 12, 28), end=date(2025, 1, 5), platforms=["Terra", "Aqua"])
    w = AN.iso_weeks(f, "MODIS", "detections")
    weeks = {(x["iso_year"], x["iso_week"]): x for x in w["weeks"]}
    # 2020-12-31 and 2021-01-01..03 belong to ISO 2020-W53
    assert weeks[(2020, 53)]["value"] == 3
    assert weeks[(2021, 1)]["value"] == 1
    # 2024-12-30 belongs to ISO 2025-W01
    assert weeks[(2025, 1)]["value"] == 1
    assert weeks[(2020, 53)]["n_weeks_in_iso_year"] == 53 and weeks[(2021, 1)]["n_weeks_in_iso_year"] == 52


def test_leap_day_counted_and_compare_excludes_feb29(env):
    rows = [modis_row(date="2024-02-29"), modis_row(date="2024-02-28"), modis_row(date="2023-02-28")]
    do_import([write_csv(env / "in" / "MODIS_SP" / "x.csv", MODIS_HDR, rows)],
              declared=[ingest.Declared(date(2023, 1, 1), date(2024, 12, 31), "cli-declared", "MODIS", "SP")])
    f = Q.Filters(start=date(2023, 1, 1), end=date(2024, 12, 31), platforms=["Terra", "Aqua"])
    d = Q.daily(f)
    assert d["series"]["MODIS"]["detections"][d["dates"].index("2024-02-29")] == 1
    c = AN.year_compare(f, "MODIS", "detections", 2024, 2023)
    assert any("29" in n for n in c.get("notes", [])) or c.get("excluded_feb29") is not None


# ---------------------------------------------------------------- baseline
def test_insufficient_history_two_years(env):
    rows = [modis_row(date="2023-09-15"), modis_row(date="2024-09-15")]
    do_import([write_csv(env / "in" / "MODIS_SP" / "x.csv", MODIS_HDR, rows)],
              declared=[ingest.Declared(date(2023, 1, 1), date(2024, 12, 31), "cli-declared", "MODIS", "SP")])
    f = Q.Filters(start=date(2024, 9, 1), end=date(2024, 9, 30), platforms=["Terra", "Aqua"])
    b = AN.baseline(f, "MODIS", "detections")
    assert b["eligibility"]["eligible"] is False
    assert b["eligibility"]["reason"].startswith("Insufficient history for a robust multi-year baseline")
    assert b["flags"] == []
    e = AN.elevated(f, "MODIS", "detections", mode="baseline")
    assert e["unavailable"] and e["periods"] == []


def test_baseline_eligible_and_zero_baseline_suppresses_low(env):
    # six years, declared coverage everywhere; a single detection in 2023-09-15 only
    rows = [modis_row(date="2023-09-15")]
    do_import([write_csv(env / "in" / "MODIS_SP" / "x.csv", MODIS_HDR, rows)],
              declared=[ingest.Declared(date(2017, 1, 1), date(2023, 12, 31), "cli-declared", "MODIS", "SP")])
    f = Q.Filters(start=date(2023, 9, 10), end=date(2023, 9, 20), platforms=["Terra", "Aqua"])
    b = AN.baseline(f, "MODIS", "detections")
    assert b["eligibility"]["eligible"] is True
    day = {x["date"]: x for x in b["days"]}
    assert day["2023-09-15"]["flag"] == "above"
    assert day["2023-09-15"]["ratio_to_median"] is None  # median 0 -> no ratio
    assert all(x["flag"] != "below" for x in b["days"])  # P5 == 0 -> no low flags


def test_baseline_missing_coverage_years_not_counted():
    vals = {}
    for y in range(2015, 2024):
        for k in range(-20, 21):
            d = date(y, 6, 15) + timedelta(days=k)
            vals[d] = None if y in (2016, 2018, 2020, 2022) else float(k % 3)
    b = AN.compute_baseline(vals, [date(2023, 6, 15)])
    rec = b["days"][0]
    assert 2016 not in rec["eligible_years"] and 2018 not in rec["eligible_years"]
    assert rec["eligible_years"] == [2015, 2017, 2019, 2021]
    assert rec["eligible"] is False  # only 4 usable prior years < 5


# ---------------------------------------------------------------- periods
def test_unknown_day_breaks_consecutive_period():
    ds = [date(2023, 9, 1) + timedelta(days=i) for i in range(8)]
    vals = [5, 5, 5, None, 5, 5, 5, 0]
    thr = [1] * 8
    ps = AN.find_periods(ds, vals, thr, 3, 1)
    assert [(p["start"], p["end"]) for p in ps] == [("2023-09-01", "2023-09-03"), ("2023-09-05", "2023-09-07")]
    assert any("unknown coverage" in n for n in ps[0]["coverage_notes"])
    assert any("unknown coverage" in n for n in ps[1]["coverage_notes"])
    assert AN.find_periods(ds, vals, thr, 4, 1) == []


def test_elevated_range_percentile_requires_30_known_days(env):
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row()])])
    f = Q.Filters(start=date(2023, 9, 1), end=date(2023, 9, 30))
    e = AN.elevated(f, "MODIS", "cells")
    assert e["unavailable"] and "30" in e["unavailable"]


def test_union_only_for_cells(env):
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row()])])
    f = Q.Filters(start=date(2023, 9, 15), end=date(2023, 9, 15))
    with pytest.raises(ValueError):
        AN.series_values(Q.daily(f), "UNION", "detections")


# ---------------------------------------------------------------- AOI
SQUARE = {"type": "Polygon", "coordinates": [[[113.0, -3.0], [114.0, -3.0], [114.0, -2.0], [113.0, -2.0], [113.0, -3.0]]]}
TRIANGLE = {"type": "Polygon", "coordinates": [[[113.0, -3.0], [114.0, -3.0], [113.0, -2.0], [113.0, -3.0]]]}


def test_aoi_boundary_points_included_and_exact_polygon(env):
    rows = [modis_row(lat=-2.0, lon=113.5),            # on square's north edge
            modis_row(lat=-2.5, lon=114.0, time="403"), # on east edge
            modis_row(lat=-2.2, lon=113.8, time="404"), # inside square, outside triangle (bbox-inside)
            modis_row(lat=-2.9, lon=113.1, time="405"), # inside both
            modis_row(lat=-1.0, lon=113.5, time="406")] # outside
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, rows)])
    sq = A.register_custom(SQUARE, "sq")["id"]
    tri = A.register_custom(TRIANGLE, "tri")["id"]
    day = date(2023, 9, 15)
    n = lambda aid: Q.daily(Q.Filters(start=day, end=day, aoi=aid))["series"]["MODIS"]["detections"][0]
    assert n("none") == 5
    assert n(sq) == 4
    assert n(tri) == 1  # (113.8,-2.2) is inside the triangle's bbox but outside the polygon: exact test drops it
    # hypotenuse point (113.5,-2.5) lies exactly on the triangle boundary
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_b.csv", MODIS_HDR, [modis_row(lat=-2.5, lon=113.5, time="410")])])
    assert n(tri) == 2


def test_aoi_validation_errors(env):
    with pytest.raises(A.AOIError):
        A.parse_geojson({"type": "Point", "coordinates": [0, 0]})
    with pytest.raises(A.AOIError):  # self-intersecting bow-tie
        A.parse_geojson({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]})
    with pytest.raises(A.AOIError):  # antimeridian-spanning
        A.parse_geojson({"type": "Polygon", "coordinates": [[[170, 0], [-170, 0], [-170, 1], [170, 1], [170, 0]]]})
    with pytest.raises(A.AOIError):  # out of bounds
        A.parse_geojson({"type": "Polygon", "coordinates": [[[0, 0], [200, 0], [200, 1], [0, 1], [0, 0]]]})
    with pytest.raises(A.AOIError):  # unsupported CRS
        A.parse_geojson({"type": "Feature", "crs": {"type": "name", "properties": {"name": "EPSG:32750"}}, "geometry": SQUARE, "properties": {}})
    with pytest.raises(A.AOIError):
        A.get_geometry("custom:../../etc")


def test_aoi_3857_transformed(env):
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    ring = [list(t.transform(x, y)) for x, y in SQUARE["coordinates"][0]]
    g, notes = A.parse_geojson({"type": "Feature", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}},
                                "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})
    assert g.bounds == pytest.approx((113.0, -3.0, 114.0, -2.0), abs=1e-6)
    assert notes


def test_named_regions_have_source_and_license(env):
    regs = A.list_regions()
    ids = {r["id"] for r in regs}
    assert {"region:sumatra", "region:kalimantan", "region:indonesia"} <= ids
    for r in regs:
        assert r.get("source") and r.get("license")
