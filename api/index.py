"""Vercel entry point for the read-only online demo of PyroSync.

Vercel serves frontend/dist as static files and routes /api/* here (see vercel.json).
The bundled demo database is copied to /tmp on first use; imports and FIRMS refresh are disabled.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("PYROSYNC_READONLY", "1")
os.environ.setdefault("PYROSYNC_DATA_DIR", "/tmp/pyrosync")
os.environ.setdefault("PYROSYNC_SEED_DB", os.path.join(ROOT, "deploy", "pyrosync-demo.duckdb"))

from pyrosync.api import app  # noqa: E402,F401
