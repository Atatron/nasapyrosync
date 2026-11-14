"""DuckDB storage: schema, connection handling, dataset revision."""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager

import duckdb
from pathlib import Path

from .config import PROCESSING_VERSION, get_settings

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS observations (
        rid BIGINT PRIMARY KEY,
        record_key VARCHAR NOT NULL UNIQUE,
        acq_date DATE NOT NULL,
        acq_ts TIMESTAMP NOT NULL,          -- UTC, stored without zone
        acq_hhmm VARCHAR NOT NULL,          -- zero-padded HHMM, UTC
        lat DOUBLE NOT NULL, lon DOUBLE NOT NULL,
        lat_e5 INTEGER NOT NULL, lon_e5 INTEGER NOT NULL,  -- coordinates quantized to 1e-5 degree
        instrument VARCHAR NOT NULL, platform VARCHAR NOT NULL, satellite_raw VARCHAR,
        series VARCHAR NOT NULL, source_product VARCHAR NOT NULL, stream VARCHAR NOT NULL, version VARCHAR,
        conf_raw VARCHAR, conf_num SMALLINT, conf_cat VARCHAR NOT NULL,
        frp DOUBLE, daynight VARCHAR, type_code SMALLINT,
        scan DOUBLE, track DOUBLE,
        modis_brightness DOUBLE, modis_bright_t31 DOUBLE, viirs_bright_ti4 DOUBLE, viirs_bright_ti5 DOUBLE,
        batch_id VARCHAR NOT NULL, source_file VARCHAR NOT NULL, source_row INTEGER NOT NULL,
        superseded BOOLEAN NOT NULL DEFAULT FALSE, superseded_by VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS provenance (
        record_key VARCHAR NOT NULL, batch_id VARCHAR NOT NULL, source_file VARCHAR NOT NULL,
        source_row INTEGER NOT NULL, role VARCHAR NOT NULL   -- 'first' | 'duplicate'
    )""",
    """CREATE TABLE IF NOT EXISTS import_batches (
        batch_id VARCHAR PRIMARY KEY, origin VARCHAR, label VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP,
        status VARCHAR, revision_after INTEGER, report_json VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS import_intervals (
        batch_id VARCHAR NOT NULL, series VARCHAR NOT NULL, stream VARCHAR NOT NULL,
        start_date DATE NOT NULL, end_date DATE NOT NULL,
        origin VARCHAR NOT NULL,   -- 'filename-declared' | 'cli-declared' | 'api-request'
        west DOUBLE, south DOUBLE, east DOUBLE, north DOUBLE, source_file VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS dataset_meta (key VARCHAR PRIMARY KEY, value VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS aoi_members (aoi_id VARCHAR NOT NULL, revision INTEGER NOT NULL, rid BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS aoi_cache_state (aoi_id VARCHAR PRIMARY KEY, revision INTEGER NOT NULL, n BIGINT)""",
]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_obs_date ON observations(acq_date)",
    "CREATE INDEX IF NOT EXISTS idx_prov_key ON provenance(record_key)",
    "CREATE INDEX IF NOT EXISTS idx_aoi_members ON aoi_members(aoi_id, rid)",
]

_lock = threading.RLock()
_conn: duckdb.DuckDBPyConnection | None = None
_conn_path: str | None = None


def _init(conn: duckdb.DuckDBPyConnection) -> None:
    for stmt in SCHEMA:
        conn.execute(stmt)
    for stmt in INDEXES:
        conn.execute(stmt)
    conn.execute("INSERT INTO dataset_meta VALUES ('revision', '0') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO dataset_meta VALUES ('processing_version', ?) ON CONFLICT DO UPDATE SET value = excluded.value", [PROCESSING_VERSION])


def get_conn() -> duckdb.DuckDBPyConnection:
    """One process-wide connection; callers use cursor() for thread safety."""
    global _conn, _conn_path
    with _lock:
        st = get_settings()
        path = str(st.db_path)
        if _conn is None or _conn_path != path:
            if not Path(path).exists():
                from . import remote_seed
                if remote_seed.configured():  # Vercel demo: full archive from Vercel Blob
                    try:
                        remote_seed.fetch(path)
                    except Exception as e:  # fall back to the bundled slim database below
                        Path(path + ".part").unlink(missing_ok=True)
                        logging.getLogger(__name__).warning("pyrosync: Blob archive unavailable (%s); using the bundled demo database", type(e).__name__ + ": " + str(e)[:200])
            if st.seed_db and not Path(path).exists():
                import shutil
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(st.seed_db, path + ".part")
                Path(path + ".part").replace(path)
            if _conn is not None:
                _conn.close()
            _conn = duckdb.connect(path)
            _conn.execute("SET TimeZone = 'UTC'")
            # Serverless instances have little memory (and /tmp may count against it): cap DuckDB there.
            if os.environ.get("PYROSYNC_DUCKDB_MEMORY"):
                _conn.execute(f"SET memory_limit = '{os.environ['PYROSYNC_DUCKDB_MEMORY']}'")
                _conn.execute("SET preserve_insertion_order = false")
                _conn.execute(f"SET temp_directory = '{Path(path).parent / 'duckdb_tmp'}'")  # spill instead of failing
            if os.environ.get("PYROSYNC_DUCKDB_THREADS"):
                _conn.execute(f"SET threads = {int(os.environ['PYROSYNC_DUCKDB_THREADS'])}")
            _init(_conn)
            _conn_path = path
        return _conn


def close_conn() -> None:
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _conn_path = None


@contextmanager
def cursor():
    cur = get_conn().cursor()
    try:
        cur.execute("SET TimeZone = 'UTC'")
        yield cur
    finally:
        cur.close()


write_lock = threading.Lock()


def get_revision(cur=None) -> int:
    if cur is None:
        with cursor() as c:
            return get_revision(c)
    row = cur.execute("SELECT value FROM dataset_meta WHERE key = 'revision'").fetchone()
    return int(row[0]) if row else 0
