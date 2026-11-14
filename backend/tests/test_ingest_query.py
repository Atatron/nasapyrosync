"""Pipeline + query-layer tests. All rows are SYNTHETIC TEST FIXTURES in an isolated data dir."""
import zipfile
from datetime import date

import pytest

from pyrosync import cache, ingest, query as Q
from pyrosync.db import get_revision, cursor
from conftest import MODIS_HDR, VIIRS_HDR, do_import, modis_row, viirs_row, write_csv


def F(**kw):
    base = dict(start=date(2023, 9, 13), end=date(2023, 9, 17))
    base.update(kw)
    return Q.Filters(**base)


def idx(d, day):
    return d["dates"].index(day)


def test_time_padding_stored_as_utc(env):
    p = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row(time="402")])
    r = do_import([p])
    assert r["new_observations"] == 1
    pts = Q.points(F(), date(2023, 9, 15), date(2023, 9, 15))
    row = pts["records"][0]
    assert row["acq_hhmm"] == "0402"
    assert "04:02" in row["acq_time_utc"]


def test_rows_assigned_by_acq_date_not_filename(env):
    # file claims 2023-09-15 but the row says 2023-09-16
    p = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row(date="2023-09-16")])
    do_import([p])
    d = Q.daily(F())
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-16")] == 1
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-15")] == 0


def test_exact_duplicates_and_reimport_idempotent(env):
    rows = [modis_row(), modis_row(), modis_row(lat=-2.6)]
    p = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, rows)
    r1 = do_import([p])
    assert r1["new_observations"] == 2 and r1["duplicate_rows"] == 1
    rev = get_revision()
    r2 = do_import([p])
    assert r2["new_observations"] == 0 and r2["duplicates_of_existing"] == 3
    assert r2["revision_changed"] is False and get_revision() == rev
    d = Q.daily(F())
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-15")] == 2


def test_same_location_different_platforms_kept_distinct(env):
    rows = [modis_row(sat="Terra"), modis_row(sat="Aqua")]
    p1 = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, rows)
    p2 = write_csv(env / "in" / "VIIRS_NOAA20_SP" / "2023-09-15_1d.csv", VIIRS_HDR, [viirs_row()])
    r = do_import([p1, p2])
    assert r["new_observations"] == 3
    d = Q.daily(F())
    i = idx(d, "2023-09-15")
    m, v, u = d["series"]["MODIS"], d["series"]["VIIRS_N20"], d["series"]["UNION"]
    assert m["detections"][i] == 2 and m["terra"][i] == 1 and m["aqua"][i] == 1
    assert v["detections"][i] == 1
    assert m["cells"][i] == 1 and v["cells"][i] == 1
    assert u["cells"][i] == 1  # one shared cell counted once
    assert u["detections"][i] is None  # raw MODIS + VIIRS counts are never added


def test_nrt_superseded_by_sp(env):
    nrt = write_csv(env / "in" / "MODIS_NRT" / "nrt.csv", MODIS_HDR, [modis_row(version="6.1NRT", lat=-2.0), modis_row(version="6.1NRT", date="2023-09-16")])
    do_import([nrt])
    d = Q.daily(F())
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-15")] == 1
    sp = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row(lat=-2.1)])
    r = do_import([sp])
    assert r["superseded_nrt_rows"] == 1  # only the Terra 09-15 NRT row
    d = Q.daily(F())
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-15")] == 1  # SP row only, NRT excluded
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-16")] == 1  # NRT kept (no SP that day)
    with cursor() as cur:
        assert cur.execute("SELECT count(*) FROM observations WHERE superseded").fetchone()[0] == 1  # retained for audit


def test_type_and_confidence_filters(env):
    rows = [modis_row(typ="0"), modis_row(typ="2", lat=-2.0), modis_row(typ="1", lat=-1.0), modis_row(conf="10", lat=-3.0)]
    p = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, rows)
    do_import([p])
    d = Q.daily(F())
    i = idx(d, "2023-09-15")
    assert d["series"]["MODIS"]["detections"][i] == 1
    assert d["series"]["MODIS"]["unfiltered"][i] == 4
    d2 = Q.daily(F(types=["0", "2"], modis_min_conf=0))
    assert d2["series"]["MODIS"]["detections"][i] == 3


def test_viirs_confidence_filter(env):
    rows = [viirs_row(conf="l"), viirs_row(conf="n", lat=-2.0), viirs_row(conf="h", lat=-1.0)]
    do_import([write_csv(env / "in" / "VIIRS_NOAA20_SP" / "2023-09-15_1d.csv", VIIRS_HDR, rows)])
    i = 2
    assert Q.daily(F())["series"]["VIIRS_N20"]["detections"][i] == 2
    assert Q.daily(F(viirs_conf=["low", "nominal", "high"]))["series"]["VIIRS_N20"]["detections"][i] == 3


def test_negative_coordinate_cells_in_db(env):
    rows = [modis_row(lat=-2.55, lon=113.55), modis_row(lat=-2.51, lon=113.59, sat="Aqua"), modis_row(lat=-2.45, lon=113.55, time="403")]
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, rows)])
    fr = Q.frame_cells(F(), date(2023, 9, 15), 1, None)
    cells = sorted((c["ci"], c["cj"], c["by_series"]["MODIS"]) for c in fr["cells"])
    assert len(cells) == 2
    south = [c for c in cells if c[2] == 2][0]
    assert south[1] * 0.1 - 90 == pytest.approx(-2.6)
    assert south[0] * 0.1 - 180 == pytest.approx(113.5)


def test_unknown_vs_zero_reported(env):
    # declared window 2023-09-14..2023-09-16 via filename; only 09-15 has rows.
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-14_3d.csv", MODIS_HDR, [modis_row()])])
    d = Q.daily(F(start=date(2023, 9, 13), end=date(2023, 9, 17)))
    st = d["series"]["MODIS"]["status"]
    # inventory range is 09-15..09-15 (data range); declared window extends coverage evidence
    assert st[idx(d, "2023-09-15")] == "detections"
    assert d["series"]["VIIRS_N20"]["status"][idx(d, "2023-09-15")] == "sensor_unavailable"


def test_zero_reported_inside_interval_unknown_outside(env):
    p1 = write_csv(env / "in" / "MODIS_SP" / "2023-09-13_1d.csv", MODIS_HDR, [modis_row(date="2023-09-13")])
    p2 = write_csv(env / "in" / "MODIS_SP" / "2023-09-14_2d.csv", MODIS_HDR, [])  # header-only, declared 14..15
    p3 = write_csv(env / "in" / "MODIS_SP" / "data_no_window.csv", MODIS_HDR, [modis_row(date="2023-09-17")])
    do_import([p1, p2, p3])
    d = Q.daily(F())
    st = d["series"]["MODIS"]["status"]
    assert st[idx(d, "2023-09-13")] == "detections"
    assert st[idx(d, "2023-09-14")] == "zero_reported"
    assert st[idx(d, "2023-09-15")] == "zero_reported"
    assert st[idx(d, "2023-09-16")] == "unknown"  # no interval covers it
    assert st[idx(d, "2023-09-17")] == "detections"
    d2 = Q.daily(F(end=date(2023, 9, 20)))
    assert d2["series"]["MODIS"]["status"][idx(d2, "2023-09-20")] == "outside_range"


def test_cli_declared_interval(env):
    p = write_csv(env / "in" / "plain.csv", MODIS_HDR, [modis_row(date="2023-09-13")])
    do_import([p], declared=[ingest.Declared(start=date(2023, 9, 13), end=date(2023, 9, 17), origin="cli-declared", series="MODIS", stream="SP")])
    d = Q.daily(F())
    assert d["series"]["MODIS"]["status"][idx(d, "2023-09-16")] == "zero_reported"


def test_late_data_invalidates_cache_and_extends_range(env):
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row()])])
    d = Q.daily(F())
    assert d["series"]["MODIS"]["detections"][idx(d, "2023-09-16")] == 0
    rev = d["dataset_revision"]
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-16_1d.csv", MODIS_HDR, [modis_row(date="2023-09-16")])])
    d2 = Q.daily(F())
    assert d2["dataset_revision"] == rev + 1
    assert d2["series"]["MODIS"]["detections"][idx(d2, "2023-09-16")] == 1
    assert Q.inventory()["date_range"] == ["2023-09-15", "2023-09-16"]


def test_cross_panel_consistency(env):
    rows = [modis_row(lat=-2.5 - k * 0.13, frp=str(5 + k)) for k in range(6)] + [modis_row(date="2023-09-16", lat=-1.0)]
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_2d.csv", MODIS_HDR, rows)])
    f = F()
    d = Q.daily(f)
    fr = Q.frame_cells(f, date(2023, 9, 15), 1, None)
    pts = Q.points(f, date(2023, 9, 15), date(2023, 9, 15))
    i = idx(d, "2023-09-15")
    assert d["series"]["MODIS"]["detections"][i] == fr["summary"]["MODIS"]["detections"] == 6
    assert d["series"]["MODIS"]["cells"][i] == fr["summary"]["MODIS"]["cells"] == len(fr["cells"])
    assert pts["total"] == 6 == len(pts["records"])
    h = Q.history(f)
    sep = [m for m in h["months"] if m["label"] == "2023-09"][0]["series"]["MODIS"]
    assert sep["detections"] == sum(d["series"]["MODIS"]["detections"])
    assert sep["sum_daily_cells"] == sum(d["series"]["MODIS"]["cells"])


def test_rejections_reported(env):
    rows = [modis_row(), modis_row(time="2500", lat=-1), modis_row(sat="Landsat", lat=-1.5), modis_row(conf="abc", lat=-1.7)]
    r = do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, rows)])
    assert r["accepted_rows"] == 1 and r["rejected_rows"] == 3
    assert len(r["rejection_reasons"]) >= 2


def test_dry_run_commits_nothing(env):
    r = do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row()])], dry_run=True)
    assert r["status"] == "inspected" and r["new_observations"] == 1
    assert get_revision() == 0
    assert Q.inventory()["date_range"] is None


def test_single_csv_stream_from_parent_folder(env):
    p = write_csv(env / "in" / "MODIS_SP" / "2023-09-15_1d.csv", MODIS_HDR, [modis_row()])
    r = do_import([p])
    assert r["source_products"] == {"MODIS_SP": 1}


def test_schema_rejected_file(env):
    p = env / "in" / "bad.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("a,b,c\n1,2,3\n")
    r = do_import([p])
    assert r["new_observations"] == 0
    assert r["files"][0]["status"] == "rejected-schema"


# ---------------------------------------------------------------- ZIP safety
def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_zip_traversal_rejected(env):
    zp = _zip(env / "evil.zip", {"../escape.csv": "x"})
    with pytest.raises(ingest.ImportError_):
        ingest.safe_zip_members(zp)
    zp2 = _zip(env / "evil2.zip", {"/abs.csv": "x"})
    with pytest.raises(ingest.ImportError_):
        ingest.safe_zip_members(zp2)


def test_zip_symlink_rejected(env):
    zp = env / "link.zip"
    with zipfile.ZipFile(zp, "w") as z:
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = (0o120777 << 16)
        z.writestr(info, "target")
    with pytest.raises(ingest.ImportError_):
        ingest.safe_zip_members(zp)


def test_zip_ignores_macosx_nested_and_noncsv(env):
    from conftest import csv_bytes
    zp = _zip(env / "ok.zip", {"MODIS_SP/2023-09-15_1d.csv": csv_bytes(MODIS_HDR, [modis_row()]), "__MACOSX/._x.csv": "junk",
                               "inner.zip": "PK", "readme.txt": "hi"})
    files, warns = ingest.safe_zip_members(zp)
    assert [f.path_hint for f in files] == ["MODIS_SP/2023-09-15_1d.csv"]
    assert any("Nested" in w for w in warns) and any("Non-CSV" in w for w in warns)
    r = do_import([zp])
    assert r["new_observations"] == 1


def test_zip_expanded_size_limit(env):
    from pyrosync.config import get_settings
    get_settings().max_zip_expanded_bytes = 1000
    zp = _zip(env / "big.zip", {"a.csv": "x" * 2000})
    with pytest.raises(ingest.ImportError_):
        ingest.safe_zip_members(zp)


def test_not_a_zip(env):
    p = env / "fake.zip"
    p.write_bytes(b"not a zip")
    with pytest.raises(ingest.ImportError_):
        ingest.safe_zip_members(p)


def test_gap_rule_is_relative_to_the_importing_batch(env):
    # Large delivery: ~30 rows/day for 5 declared days, one day with no rows at all -> likely gap -> unknown
    big = [modis_row(date=f"2023-09-{d}", lat=-2.0 - k * 0.01, time=str(400 + k)) for d in (13, 14, 16, 17) for k in range(30)]
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-09-13_5d.csv", MODIS_HDR, big)])
    d = Q.daily(F())
    assert d["series"]["MODIS"]["status"][idx(d, "2023-09-15")] == "unknown"
    assert "gap" in d["series"]["MODIS"]["status_origin"][idx(d, "2023-09-15")]
    # Small later delivery (one row in 3 declared days): its empty days are genuine zero-reported days
    do_import([write_csv(env / "in" / "MODIS_SP" / "2023-10-01_3d.csv", MODIS_HDR, [modis_row(date="2023-10-02")])])
    d2 = Q.daily(F(start=date(2023, 10, 1), end=date(2023, 10, 3)))
    assert d2["series"]["MODIS"]["status"] == ["zero_reported", "detections", "zero_reported"]
