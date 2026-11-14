"""Tests for AOI Insights (v1.3): regime, tracker, recurrence, critical periods, readiness, anomaly score, years/climate,
AOI comparison, exports and the near-real-time view. All observations are SYNTHETIC TEST FIXTURES."""
from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import numpy as np
import pytest

from conftest import MODIS_HDR, do_import, modis_row, write_csv
from pyrosync import climate, ingest
from pyrosync import insights as I
from pyrosync import live
from pyrosync import query as Q
from pyrosync.config import get_settings

YEARS = list(range(2015, 2023))       # 8 complete years
BIG = {2015, 2019, 2022}              # synthetic "big" seasons
A_LON, B_LON, LAT = 113.05, 113.55, -2.55


def _n_a(d: date) -> int:
    """Detections per day in cell A (every year)."""
    if d.year in BIG and d.month == 9 and d.day <= 20:
        return 20
    if 8 <= d.month <= 10:
        return 2
    return 1 if d.day == 10 else 0


def _n_b(d: date) -> int:
    """Cell B burns only in the big years."""
    return 3 if d.year in BIG and d.month == 9 and d.day <= 20 else 0


def _load(tmp_path, years=YEARS):
    rows = []
    d = date(years[0], 1, 1)
    while d <= date(years[-1], 12, 31):
        for j in range(_n_a(d)):
            rows.append(modis_row(lat=round(LAT + 0.001 * j, 5), lon=A_LON, date=d.isoformat(), time="0300", sat="Terra"))
        for j in range(_n_b(d)):
            rows.append(modis_row(lat=round(LAT + 0.001 * j, 5), lon=B_LON, date=d.isoformat(), time="0300", sat="Terra"))
        d += timedelta(days=1)
    write_csv(tmp_path / "in" / "MODIS_SP" / "SYNTHETIC_TEST_FIXTURE_insights.csv", MODIS_HDR, rows)
    do_import([tmp_path / "in"], declared=[ingest.Declared(date(years[0], 1, 1), date(years[-1], 12, 31), "cli-declared", "MODIS", "SP")])


def F(end=date(2022, 12, 31), start=None, **kw):
    return Q.Filters(start=start or date(end.year, 1, 1), end=end, platforms=["Terra", "Aqua"], aoi="region:kalimantan", **kw)


def test_regime_and_tracker(env):
    _load(env)
    r = I.regime(F(), "MODIS")
    assert r["available"], r.get("reason")
    assert r["reference_years"] == list(range(2015, 2022))          # focus year 2022 excluded
    w36 = r["weeks"][36]                                             # 3–9 Sep
    vals = sorted(I._weekly(I._year_table(*I._history(F(), "MODIS", "detections")[1:])[y]["days"])[36] for y in r["reference_years"])
    assert w36["median"] == pytest.approx(float(np.median(vals)))
    assert w36["n_years"] == 7
    assert r["peak_week"]["week"] in range(30, 44)
    for k in ("onset", "peak", "end"):
        assert r["season"][k] is not None
    assert r["variability"]["max_year"] in BIG
    t = r["tracker"]["status"]
    assert t["as_of"] == "2022-12-31" and t["n_reference_years"] == 7
    totals = [sum(_n_a(date(y, 1, 1) + timedelta(days=i)) + _n_b(date(y, 1, 1) + timedelta(days=i))
                  for i in range((date(y, 12, 31) - date(y, 1, 1)).days + 1)) for y in YEARS]
    assert t["cumulative"] == totals[-1]
    assert t["years_below"] == sum(1 for x in totals[:-1] if x < totals[-1])
    assert len(r["tracker"]["envelope"]["median"]) == 365


def test_regime_insufficient_history(env):
    _load(env, years=[2020, 2021, 2022])
    r = I.regime(F(), "MODIS")
    assert r["available"] is False and "Insufficient history" in r["reason"]


def test_recurrence(env):
    _load(env)
    r = I.recurrence(F(), "MODIS", chronic_share=0.4)
    assert r["n_eligible_years"] == 8
    cells = {round(c["lon"], 2): c for c in r["cells"]}
    a, b = cells[A_LON], cells[B_LON]
    assert a["fire_years"] == 8 and a["longest_run"] == 8 and a["chronic"]
    assert b["fire_years"] == 3 and b["longest_run"] == 1 and not b["chronic"]       # 3/8 < 0.4
    assert (b["first_year"], b["last_year"]) == (2015, 2022)
    assert r["cells"][0]["lon"] == A_LON                              # sorted by fire years
    assert sum(h["cells"] for h in r["histogram"]) == r["cells_total"] == 2


def test_critical_periods_and_readiness(env):
    _load(env)
    c = I.critical(F(), "MODIS", percentile=90, min_days=3)
    assert c["available"]
    top = c["periods"][:3]
    assert {p["year"] for p in top} == BIG
    assert all(p["start"][5:7] == "09" for p in top)
    # the threshold of a year never uses that year: recompute for 2015 by hand
    _, dates, vals = I._history(F(), "MODIS", "detections")
    others = [v for d, v in zip(dates, vals) if v is not None and d.year != 2015]
    thr = next(t for t in c["thresholds_by_year"] if t["year"] == 2015)["threshold"]
    assert thr == pytest.approx(float(np.percentile(others, 90)))
    wk = c["readiness"]["weeks"][36]
    assert wk["years_known"] == 8 and wk["years_critical"] == 3 and wk["share"] == pytest.approx(0.375)
    assert c["readiness"]["weeks"][5]["years_critical"] == 0


def test_anomaly_score(env):
    _load(env)
    a = I.anomaly(F(start=date(2022, 9, 1), end=date(2022, 9, 30)), "MODIS")
    big = next(x for x in a["days"] if x["date"] == "2022-09-10")
    assert big["state"] == "scored" and big["band"] == "exceptional"
    # hand computation of the score
    _, dates, vals = I._history(F(end=date(2022, 9, 30)), "MODIS", "detections")
    by = dict(zip(dates, vals))
    refs = [by[date(y, 9, 10) + timedelta(days=k)] for y in range(2015, 2022) for k in range(-15, 16)]
    lr = np.log1p(refs)
    med = np.median(lr)
    scale = max(1.4826 * np.median(np.abs(lr - med)), I.ANOMALY_FLOOR["day"])
    assert big["z"] == pytest.approx(round((np.log1p(23) - med) / scale, 3))
    normal = I.anomaly(F(start=date(2021, 10, 10), end=date(2021, 10, 10)), "MODIS")["days"][0]
    assert normal["state"] == "scored" and normal["band"] == "normal"
    early = I.anomaly(F(start=date(2016, 9, 10), end=date(2016, 9, 10)), "MODIS")["days"][0]
    assert early["state"] == "insufficient history" and early["z"] is None


def test_cell_anomaly(env):
    _load(env)
    m = I.cell_anomaly(F(start=date(2022, 9, 1), end=date(2022, 9, 20)), "MODIS")
    assert m["available"] and m["reference_years"] == list(range(2015, 2022))
    a = next(c for c in m["cells"] if c["lon"] == A_LON)
    assert a["value"] == 400 and a["n_reference"] == 7 and a["band"] != "normal"
    b = next(c for c in m["cells"] if c["lon"] == B_LON)
    assert b["value"] == 60 and b["years_with_fire"] == 2
    with pytest.raises(ValueError):
        I.cell_anomaly(F(start=date(2022, 1, 1), end=date(2022, 12, 31)), "MODIS")


def test_years_report_uses_noaa_phases(env):
    _load(env)
    y = I.years_report(F(), "MODIS")
    rows = {r["year"]: r for r in y["years"]}
    assert rows[2015]["enso"] == "El Niño" and rows[2015]["oni"] == climate.season_phase(2015)["oni"]
    assert rows[2019]["iod"] == "positive"
    assert {rows[y]["rank"] for y in BIG} == {1, 2, 3}
    en = next(g for g in y["groups"]["enso"] if g["phase"] == "El Niño")
    assert 2015 in en["years"]


def test_climate_tables_are_the_verified_noaa_rows():
    import hashlib
    for name, digest in (("oni.txt", "994b2e6bc5324910f2966b302f2cbca98fce56da63e08ce65f4a2f86f1dd2414"),
                         ("dmi.txt", "ccc1bdb3a361e3d4a3f270bdd7ca0d876570034e0463eb5d64968eb3dddd67d4")):
        text = (climate.RES / name).read_text()
        rows = "".join(l + "\n" for l in text.splitlines() if not l.startswith("#"))
        assert hashlib.sha256(rows.encode()).hexdigest() == digest
    p = climate.season_phase(2015)
    assert p["oni"] == pytest.approx((1.73 + 2.02) / 2) and p["enso"] == "El Niño"
    assert climate.season_phase(2010)["enso"] == "La Niña"


def test_compare_and_exports(env):
    _load(env)
    from fastapi.testclient import TestClient
    from pyrosync.api import app
    cl = TestClient(app)
    q = "start=2022-01-01&end=2022-12-31&platforms=Terra,Aqua&aoi=region:kalimantan"
    for path in ("regime", "recurrence", "critical", "years"):
        assert cl.get(f"/api/insights/{path}?{q}&series=MODIS").status_code == 200
    assert cl.get(f"/api/insights/anomaly?start=2022-09-01&end=2022-09-30&platforms=Terra,Aqua&aoi=region:kalimantan").status_code == 200
    assert cl.get(f"/api/insights/regime?{q}&series=NOPE").status_code == 422
    cmp = cl.get(f"/api/insights/compare?{q}&aois=region:kalimantan,region:sumatra&series=MODIS").json()
    k = next(r for r in cmp["rows"] if r["aoi"] == "region:kalimantan")
    assert k["area_km2"] > 400000 and k["mean_annual_per_1000km2"] == pytest.approx(k["mean_annual"] / k["area_km2"] * 1000)
    csv_t = cl.get(f"/api/export/hotspots.csv?{q}&series=MODIS").text
    assert csv_t.startswith("# PyroSync") and "rank,lat,lon,fire_years" in csv_t and len(csv_t.strip().splitlines()) == 4
    gj = cl.get(f"/api/export/hotspots.geojson?{q}&series=MODIS").json()
    assert gj["features"][0]["geometry"]["coordinates"] == [A_LON, -2.55]
    kml = cl.get(f"/api/export/hotspots.kml?{q}&series=MODIS").text
    assert kml.startswith("<?xml") and kml.count("<Placemark>") == kml.count("</Placemark>") == 2
    z = cl.get(f"/api/export/insights.zip?{q}&series=MODIS")
    assert z.status_code == 200 and z.content[:2] == b"PK"


def test_now_vs_history_uses_nrt_without_storing(env, monkeypatch):
    _load(env)
    monkeypatch.setattr(get_settings(), "firms_map_key", "SYNTHETICKEY")
    today = date(2022, 9, 10)
    hdr = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight"
    lines = [hdr]
    for k in range(10):
        d = (today - timedelta(days=k)).isoformat()
        for j in range(5):
            lines.append(f"{LAT + 0.001 * j},{A_LON},320.1,1.0,1.0,{d},0300,T,MODIS,50,6.1NRT,295.0,10.0,D")
    lines.append(f"{LAT},{A_LON},320.1,1.0,1.0,{today.isoformat()},0300,T,MODIS,10,6.1NRT,295.0,10.0,D")   # low confidence: filtered
    lines.append(f"5.0,100.0,320.1,1.0,1.0,{today.isoformat()},0300,T,MODIS,50,6.1NRT,295.0,10.0,D")    # outside the AOI
    body = "\n".join(lines) + "\n"

    def handler(req: httpx.Request):
        parts = req.url.path.split("/")
        start, n = date.fromisoformat(parts[-1]), int(parts[-2])
        keep = [lines[0]] + [l for l in lines[1:] if start <= date.fromisoformat(l.split(",")[5]) < start + timedelta(days=n)]
        return httpx.Response(200, text="\n".join(keep) + "\n")

    live._cache.clear()
    from pyrosync.db import cursor, get_revision
    with cursor() as cur:
        n_before = cur.execute("SELECT count(*) FROM observations").fetchone()[0]
    rev = get_revision()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = live.now_vs_history(F(end=today, start=date(2022, 1, 1)), "MODIS", days=10, client=client, today=today)
    assert out["total"] == 50 and out["source"] == "MODIS_NRT"
    assert out["counts"]["outside_aoi"] == 1 and out["counts"]["filtered_out"] == 1
    assert all(d["nrt_detections"] == 5 for d in out["days"])
    assert out["window_score"]["n_years"] == 7
    assert "SYNTHETICKEY" not in json.dumps(out)
    assert body  # fixture used
    with cursor() as cur:
        assert cur.execute("SELECT count(*) FROM observations").fetchone()[0] == n_before
    assert get_revision() == rev


def test_anomaly_guard_rail_against_count_noise():
    # A usually empty season (median 0, MAD 0): the floor alone would turn 1-2 detections into a high z.
    refs = [0] * 200 + [1] * 20 + [2] * 5
    one = I._finish(I.robust_score(1, refs), I.ANOMALY_FLOOR["day"], 1, refs)
    assert one["z"] > 2 and one["band"] == "normal"
    many = I._finish(I.robust_score(17, refs), I.ANOMALY_FLOOR["day"], 17, refs)
    assert many["band"] == "exceptional"
    # below normal needs a positive reference median and a value under the 25th percentile
    busy = [40, 50, 60, 55, 45, 52, 48]
    low = I._finish(I.robust_score(5, busy), I.ANOMALY_FLOOR["week"], 5, busy)
    assert low["band"] == "below normal"


def test_insight_types_keep_rows_without_type():
    assert I.insight_types(["0"]) == ["0", "unknown"]
    assert I.insight_types(["0", "unknown"]) == ["0", "unknown"]
    assert I.insight_types(["1"]) == ["1"]


def test_nrt_rows_without_type_are_not_read_as_zero(env):
    """FIRMS NRT area files have no 'type' column. With the default vegetation-fire filter they must still count in Insights."""
    _load(env)
    rows = [modis_row(lat=round(LAT + 0.001 * j, 5), lon=A_LON, date=f"2023-01-{d:02d}", time="0300", sat="Aqua", version="6.1NRT")[:-1] for d in range(1, 11) for j in range(4)]
    write_csv(env / "nrt" / "MODIS_NRT" / "SYNTHETIC_TEST_FIXTURE_nrt_no_type.csv", MODIS_HDR[:-1], rows)
    do_import([env / "nrt"], declared=[ingest.Declared(date(2023, 1, 1), date(2023, 1, 10), "cli-declared", "MODIS", "NRT")])
    r = I.regime(F(end=date(2023, 1, 10)), "MODIS")
    assert r["tracker"]["status"]["cumulative"] == 40
    assert "unknown/missing type" in r["filter_disclosure"]["types_included"][-1] or any("missing" in x for x in r["filter_disclosure"]["types_included"])
    assert "no fire-type column" in r["rules"]["missing_type"]
