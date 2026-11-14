"""Test fixtures. All observations created here are SYNTHETIC TEST FIXTURES and live in
an isolated temporary data directory; they never touch the real-data database."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from pyrosync import cache, db
from pyrosync.config import Settings, set_settings

MODIS_HDR = ["latitude", "longitude", "brightness", "scan", "track", "acq_date", "acq_time", "satellite", "instrument", "confidence",
             "version", "bright_t31", "frp", "daynight", "type"]
VIIRS_HDR = ["latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time", "satellite", "instrument", "confidence",
             "version", "bright_ti5", "frp", "daynight", "type"]


def modis_row(lat=-2.5, lon=113.5, date="2023-09-15", time="402", sat="Terra", conf="50", version="61.03", frp="10.0", dn="D", typ="0", bright="320.1"):
    return [str(lat), str(lon), bright, "1.0", "1.0", date, time, sat, "MODIS", conf, version, "295.0", frp, dn, typ]


def viirs_row(lat=-2.5, lon=113.5, date="2023-09-15", time="545", sat="N20", conf="n", version="2", frp="3.0", dn="D", typ="0", bright="330.0"):
    return [str(lat), str(lon), bright, "0.4", "0.5", date, time, sat, "VIIRS", conf, version, "290.0", frp, dn, typ]


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


@pytest.fixture()
def env(tmp_path):
    db.close_conn()
    s = Settings(data_dir=tmp_path / "data")
    s.keep_raw_uploads = False
    s.offline = True
    s.firms_map_key = ""
    set_settings(s)
    cache.invalidate()
    from pyrosync import aoi
    aoi.regions.cache_clear()
    yield tmp_path
    db.close_conn()
    cache.invalidate()


def csv_bytes(header, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode()


def do_import(paths, **kw):
    """Import fixture files through the real pipeline (CLI origin, no raw copy)."""
    from pyrosync import ingest
    opts = ingest.ImportOptions(origin="cli", keep_raw=False, **kw)
    return ingest.import_paths([Path(p) for p in paths], opts)
