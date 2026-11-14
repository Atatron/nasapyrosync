"""Build the compact database used by the read-only online demo (Vercel).

Usage (from the project root, server stopped):
    .venv/bin/python deploy/build_demo_db.py sample_data/indonesia.zip [more files/folders...]

Imports the given FIRMS files into a temporary data directory with the normal pipeline, then copies
the analysis tables (without per-occurrence provenance) into deploy/pyrosync-demo.duckdb.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
tmp = Path(tempfile.mkdtemp(prefix="pyrosync-demo-"))
os.environ["PYROSYNC_DATA_DIR"] = str(tmp)
os.environ["PYROSYNC_KEEP_RAW_UPLOADS"] = "0"

import duckdb  # noqa: E402

from pyrosync import db, ingest  # noqa: E402

paths = [Path(p).resolve() for p in sys.argv[1:]] or [ROOT / "sample_data" / "indonesia.zip"]
rep = ingest.import_paths(paths, ingest.ImportOptions(origin="cli", label="online demo build", keep_raw=False))
print(f"imported {rep['new_observations']:,} observations, revision {rep['dataset_revision']}")
db.close_conn()

out = ROOT / "deploy" / "pyrosync-demo.duckdb"
out.unlink(missing_ok=True)
c = duckdb.connect(str(out))
c.execute(f"ATTACH '{tmp / 'pyrosync.duckdb'}' AS s (READ_ONLY)")
# Large tables are copied without the record_key uniqueness index (only needed for imports, which the
# demo disables); this keeps the file small. Remaining tables, keys and indexes come from the normal schema.
for t in ("observations", "import_batches", "import_intervals"):
    c.execute(f"CREATE TABLE {t} AS SELECT * FROM s.{t}")
c.execute("CREATE TABLE provenance AS SELECT * FROM s.provenance WHERE false")
db._init(c)
c.execute("DELETE FROM dataset_meta")
c.execute("INSERT INTO dataset_meta SELECT * FROM s.dataset_meta")
c.execute("CHECKPOINT")
c.close()
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
