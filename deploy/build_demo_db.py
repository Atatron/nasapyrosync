"""Build the compact database used by the read-only online demo (Vercel).

Usage (from the project root, server stopped):
    .venv/bin/python deploy/build_demo_db.py sample_data/indonesia.zip [more files/folders...]
    .venv/bin/python deploy/build_demo_db.py --from-db data/pyrosync.duckdb [--aoi region:kalimantan] [--platforms Terra,Aqua,SNPP]

With files: imports them into a temporary data directory with the normal pipeline first.
With --from-db: copies from an existing PyroSync database (for example your local full-history import),
optionally keeping only the observations inside a named AOI and/or on some platforms. The subset is
recorded in dataset_meta ('demo_subset') and shown by the online demo.

The output (deploy/pyrosync-demo.duckdb) contains the analysis tables without per-occurrence provenance and
with record_key blanked (it is only used to de-duplicate imports, which the demo disables). Keep it under
about 75 MB so the Vercel function stays under the 250 MB limit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

ap = argparse.ArgumentParser()
ap.add_argument("paths", nargs="*")
ap.add_argument("--from-db", type=Path, default=None)
ap.add_argument("--aoi", default=None, help="Keep only observations inside this AOI id (e.g. region:kalimantan)")
ap.add_argument("--platforms", default=None, help="Comma-separated platforms to keep (Terra,Aqua,N20,N21,SNPP)")
ap.add_argument("--out", type=Path, default=ROOT / "deploy" / "pyrosync-demo.duckdb")
a = ap.parse_args()

if a.from_db:
    src_db = a.from_db.resolve()
    os.environ["PYROSYNC_DATA_DIR"] = str(src_db.parent)
else:
    tmp = Path(tempfile.mkdtemp(prefix="pyrosync-demo-"))
    os.environ["PYROSYNC_DATA_DIR"] = str(tmp)
    src_db = tmp / "pyrosync.duckdb"
os.environ["PYROSYNC_KEEP_RAW_UPLOADS"] = "0"

import duckdb  # noqa: E402

from pyrosync import aoi as A  # noqa: E402
from pyrosync import db, ingest  # noqa: E402

if not a.from_db:
    paths = [Path(p).resolve() for p in a.paths] or [ROOT / "sample_data" / "indonesia.zip"]
    rep = ingest.import_paths(paths, ingest.ImportOptions(origin="cli", label="online demo build", keep_raw=False))
    print(f"imported {rep['new_observations']:,} observations, revision {rep['dataset_revision']}")

subset = {}
if a.aoi:
    A.ensure_members(a.aoi)  # exact polygon membership, materialized in the source database
    subset["aoi"] = A.describe(a.aoi)["name"]
    subset["aoi_id"] = a.aoi
plats = [p.strip() for p in a.platforms.split(",")] if a.platforms else None
if plats:
    subset["platforms"] = plats
gap_days = None
if subset:
    # Whole-extent data gaps must be judged on the full database, not on the subset.
    from pyrosync import query as Q  # noqa: E402
    gap_days = {s_: sorted(d.isoformat() for d in ds) for s_, ds in Q._global_gap_days().items()}
db.close_conn()

out = a.out
out.unlink(missing_ok=True)
c = duckdb.connect(str(out))
c.execute(f"ATTACH '{src_db}' AS s (READ_ONLY)")
where = ["TRUE"]
params: list = []
if a.aoi:
    where.append("rid IN (SELECT rid FROM s.aoi_members WHERE aoi_id = ? AND revision = (SELECT max(revision) FROM s.aoi_members WHERE aoi_id = ?))")
    params += [a.aoi, a.aoi]
if plats:
    where.append("platform IN (" + ",".join("?" * len(plats)) + ")")
    params += plats
# Large tables are copied without the record_key uniqueness index (only needed for imports, which the
# demo disables); this keeps the file small. Remaining tables, keys and indexes come from the normal schema.
c.execute(f"CREATE TABLE observations AS SELECT * REPLACE ('' AS record_key) FROM s.observations WHERE {' AND '.join(where)} ORDER BY acq_date, platform, rid", params)
c.execute("CREATE TABLE import_batches AS SELECT * FROM s.import_batches")
c.execute("CREATE TABLE import_intervals AS SELECT * FROM s.import_intervals")
c.execute("CREATE TABLE provenance AS SELECT * FROM s.provenance WHERE false")
db._init(c)
c.execute("DELETE FROM dataset_meta")
c.execute("INSERT INTO dataset_meta SELECT * FROM s.dataset_meta")
if subset:
    c.execute("INSERT INTO dataset_meta VALUES ('demo_subset', ?)", [json.dumps(subset)])
    c.execute("INSERT INTO dataset_meta VALUES ('gap_days', ?)", [json.dumps(gap_days)])
c.execute("CHECKPOINT")
n = c.execute("SELECT count(*) FROM observations").fetchone()[0]
c.close()
print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {n:,} observations{', subset ' + json.dumps(subset) if subset else ''})")
