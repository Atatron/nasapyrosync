"""Vercel entry point for the read-only online demo of PyroSync.

Vercel serves frontend/dist as static files and routes /api/* here (see vercel.json).
On first use the full archive (all five satellites) is downloaded from Vercel Blob into /tmp
(see backend/pyrosync/remote_seed.py and deploy/blob/). If no Blob store is connected or the
download fails, the bundled slim demo database is used instead. Imports and FIRMS refresh are disabled.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("PYROSYNC_READONLY", "1")
os.environ.setdefault("PYROSYNC_DATA_DIR", "/tmp/pyrosync")
os.environ.setdefault("PYROSYNC_REMOTE_MANIFEST", os.path.join(ROOT, "deploy", "blob", "manifest.json"))
os.environ.setdefault("PYROSYNC_DUCKDB_MEMORY", "512MB")  # DuckDB would otherwise size itself from the host, not the instance; /tmp also counts
os.environ.setdefault("PYROSYNC_DUCKDB_THREADS", "2")
os.environ.setdefault("PYROSYNC_SEED_DB", os.path.join(ROOT, "deploy", "pyrosync-demo.duckdb"))

from pyrosync.api import app  # noqa: E402,F401
