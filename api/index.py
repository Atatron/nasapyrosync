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
os.environ.setdefault("PYROSYNC_DUCKDB_MEMORY", "1GB")  # DuckDB would otherwise size itself from the host, not the instance; /tmp also counts
os.environ.setdefault("PYROSYNC_DUCKDB_THREADS", "2")
os.environ.setdefault("PYROSYNC_SEED_DB", os.path.join(ROOT, "deploy", "pyrosync-demo.duckdb"))

from pyrosync.api import app  # noqa: E402,F401


# ---- CDN caching for the read-only demo (deployment layer only; no data logic) ----
# The demo database never changes within a deployment, so identical GET requests return identical JSON.
# Successful answers are cached at Vercel's edge for a day (a new deployment purges the cache). Live or
# per-instance endpoints are never cached: health, FIRMS near-real-time, import and job status.
_NO_CDN = ("/api/health", "/api/firms", "/api/insights/now", "/api/imports", "/api/uploads", "/api/imagery", "/api/aoi")
_CDN_VALUE = b"public, max-age=0, s-maxage=86400, stale-while-revalidate=604800"


class _CdnCache:
    """Pure ASGI middleware: adds an edge Cache-Control header to successful, cacheable GET answers."""

    def __init__(self, asgi):
        self.asgi = asgi

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        cacheable = (scope.get("method") == "GET" and path.startswith("/api/") and not path.startswith(_NO_CDN)
                     and os.environ.get("PYROSYNC_READONLY") == "1")
        if not cacheable:
            return await self.asgi(scope, receive, send)

        async def send_with_cache(msg):
            if msg["type"] == "http.response.start" and msg.get("status") == 200:
                headers = [(k, v) for k, v in msg.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", _CDN_VALUE))
                msg = {**msg, "headers": headers}
            await send(msg)
        return await self.asgi(scope, receive, send_with_cache)


app.add_middleware(_CdnCache)
