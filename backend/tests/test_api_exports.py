"""HTTP API and export tests (FastAPI TestClient, SYNTHETIC TEST FIXTURES)."""
import csv
import io
import json
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from pyrosync import query as Q
from pyrosync.api import app
from pyrosync.config import get_settings
from conftest import MODIS_HDR, VIIRS_HDR, csv_bytes, do_import, modis_row, viirs_row, write_csv

QS = "start=2023-09-14&end=2023-09-16"


@pytest.fixture()
def api(env):
    rows = [modis_row(lat=-2.5 - 0.13 * k) for k in range(4)] + [modis_row(typ="2", lat=-1.0)]
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-14_3d.csv", MODIS_HDR, rows),
               write_csv(env / "in" / "VIIRS_NOAA20_SP" / "2023-09-14_3d.csv", VIIRS_HDR, [viirs_row(), viirs_row(date="2023-09-16", lat=-1.2)])])
    return TestClient(app)


def unzip(content):
    z = zipfile.ZipFile(io.BytesIO(content))
    return {n: z.read(n).decode() for n in z.namelist()}


def test_health_and_inventory(api):
    assert api.get("/api/health").status_code == 200
    inv = api.get("/api/inventory").json()
    assert inv["date_range"] == ["2023-09-14", "2023-09-16"]


def test_daily_export_matches_query(api):
    d = api.get(f"/api/daily?{QS}").json()
    files = unzip(api.get(f"/api/export/daily.zip?{QS}").content)
    rows = list(csv.DictReader(io.StringIO(files["daily_summary.csv"])))
    assert [r["date_utc"] for r in rows] == d["dates"]
    for i, r in enumerate(rows):
        assert int(r["MODIS_detections"]) == d["series"]["MODIS"]["detections"][i]
        assert int(r["VIIRS_N20_cells"]) == d["series"]["VIIRS_N20"]["cells"][i]
        assert r["MODIS_status"] == d["series"]["MODIS"]["status"][i]
    assert not any("union_detections" in c for c in rows[0].keys())
    m = json.loads(files["manifest.json"])
    assert m["dataset_revision"] == d["dataset_revision"]
    assert m["filters"]["types"] == ["0"]
    assert "Not an official NASA application" in m["attribution"]


def test_observations_export_matches_points_and_filters(api):
    files = unzip(api.get(f"/api/export/observations.zip?{QS}&window_start=2023-09-15&window_end=2023-09-15").content)
    rows = list(csv.DictReader(io.StringIO(files["observations.csv"])))
    pts = api.get(f"/api/observations?{QS}&window_start=2023-09-15&window_end=2023-09-15").json()
    assert len(rows) == pts["total"] == 5  # 4 MODIS type-0 + 1 VIIRS; type-2 row excluded
    assert all(r["type_code"] == "0" for r in rows)
    assert all(len(r["acq_hhmm"]) == 4 for r in rows)
    assert json.loads(files["manifest.json"])["row_count"] == 5


def test_grid_geojson_matches_frame(api):
    fr = api.get(f"/api/frame?{QS}&date=2023-09-15&mode=1").json()
    gj = api.get(f"/api/export/grid.geojson?{QS}&date=2023-09-15&mode=1").json()
    assert len(gj["features"]) == len(fr["cells"])
    for k in ("MODIS", "VIIRS_N20"):
        assert sum(f["properties"][f"{k}_detections"] for f in gj["features"]) == fr["summary"][k]["detections"]
    assert all("detections_total" not in f["properties"] for f in gj["features"])  # sensors never summed
    assert "detections" not in fr["union"]
    ring = gj["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5
    assert "not a burned-area polygon" in gj["pyrosync_metadata"]["geometry_note"]


def test_aoi_post_and_export(api):
    poly = {"type": "Polygon", "coordinates": [[[113.0, -3.0], [114.0, -3.0], [114.0, -2.0], [113.0, -2.0], [113.0, -3.0]]]}
    r = api.post("/api/aoi", json={"geojson": poly, "name": "test"})
    assert r.status_code == 200
    aid = r.json()["id"]
    gj = api.get(f"/api/export/aoi.geojson?aoi={aid}").json()
    assert gj["features"][0]["geometry"]["type"] == "Polygon"
    a = api.get(f"/api/daily?{QS}&aoi={aid}").json()
    n = api.get(f"/api/daily?{QS}").json()
    assert sum(a["series"]["MODIS"]["detections"]) <= sum(n["series"]["MODIS"]["detections"])
    bad = api.post("/api/aoi", json={"geojson": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}})
    assert bad.status_code == 422


def test_frame_query_changes_with_date(api):
    a = api.get(f"/api/frame?{QS}&date=2023-09-15&mode=1").json()
    b = api.get(f"/api/frame?{QS}&date=2023-09-16&mode=1").json()
    assert a["frame"]["date"] == "2023-09-15" and b["frame"]["date"] == "2023-09-16"
    assert a["summary"]["MODIS"]["detections"] == 4 and b["summary"]["MODIS"]["detections"] == 0


def test_validation_errors(api):
    assert api.get("/api/daily?start=2023-09-16&end=2023-09-14").status_code == 422
    assert api.get(f"/api/daily?{QS}&platforms=Landsat").status_code == 422
    assert api.get(f"/api/daily?{QS}&grid=0.2").status_code == 422
    assert api.get(f"/api/elevated?{QS}&series=UNION&metric=detections").status_code == 422


def test_upload_and_import_flow(api, env):
    up = api.post("/api/uploads", files={"files": ("2023-09-17_1d.csv", csv_bytes(MODIS_HDR, [modis_row(date="2023-09-17")]), "text/csv")})
    assert up.status_code == 200, up.text
    uid = up.json()["upload_id"]
    import time
    def run(dry):
        jid = api.post("/api/imports", json={"upload_id": uid, "dry_run": dry}).json()["job_id"]
        for _ in range(100):
            j = api.get(f"/api/imports/jobs/{jid}").json()
            if j["status"] in ("done", "error"):
                return j
            time.sleep(0.05)
        raise AssertionError("import job did not finish")
    j = run(True)
    assert j["status"] == "done" and j["report"]["status"] == "inspected"
    j = run(False)
    assert j["status"] == "done" and j["report"]["new_observations"] == 1
    assert api.get("/api/inventory").json()["date_range"][1] == "2023-09-17"
    bid = j["report"]["batch_id"]
    assert api.get(f"/api/imports/{bid}/report.json").status_code == 200
    assert api.get(f"/api/imports/{bid}/rejections.csv").status_code == 200


def test_key_never_exposed(api):
    get_settings().firms_map_key = "SECRETKEY123456"
    for path in ("/api/firms/status", "/api/health", "/api/inventory", f"/api/export/daily.zip?{QS}"):
        r = api.get(path)
        assert b"SECRETKEY123456" not in r.content


def test_imagery_check_explicit_date(api):
    r = api.get("/api/imagery/check?layer=VIIRS_NOAA20_CorrectedReflectance_TrueColor&date=2023-09-15").json()
    assert r["date"] == "2023-09-15" and r["available"] is True
    r = api.get("/api/imagery/check?layer=VIIRS_NOAA20_CorrectedReflectance_TrueColor&date=2030-01-01").json()
    assert r["available"] is False and r["nearest_available"] != "2030-01-01"


def test_readonly_demo_blocks_writes_but_serves_analysis(api):
    get_settings().readonly = True
    try:
        assert api.get("/api/health").json()["readonly"] is True
        assert api.post("/api/imports", json={"upload_id": "x", "dry_run": True}).status_code == 403
        assert api.post("/api/uploads", files={"files": ("a.csv", b"x", "text/csv")}).status_code == 403
        assert api.get(f"/api/daily?{QS}").status_code == 200
    finally:
        get_settings().readonly = False
