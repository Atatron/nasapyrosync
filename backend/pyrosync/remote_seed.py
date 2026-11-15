"""Fetch the full read-only archive from Vercel Blob at cold start (added for the Vercel demo).

The Vercel function bundle cannot hold the full database (250 MB limit), so the Vercel build
uploads it to Vercel Blob as xz-compressed parts (deploy/blob/upload.mjs) and the function
downloads, decompresses and checksum-verifies it into /tmp the first time it opens the database.
If anything fails or takes too long, the caller falls back to the bundled slim demo database.

Configuration (environment):
  PYROSYNC_REMOTE_MANIFEST  path to deploy/blob/manifest.json (set by api/index.py)
  PYROSYNC_BLOB_BASE        optional base URL of the store; otherwise derived from the store id
                            inside BLOB_READ_WRITE_TOKEN (the token itself is never logged or sent)
  PYROSYNC_REMOTE_DEADLINE  seconds before giving up (default 40)
  PYROSYNC_ARCHIVE_BASE     optional mirror base URL (e.g. a GitHub release download URL); part names are
                            appended without the Blob prefix. The manifest's "base_url" is used the same way.
                            A mirror takes precedence over Blob (added after the Hobby Blob store was blocked
                            for exceeding its monthly data transfer).
"""
from __future__ import annotations

import hashlib
import json
import logging
import lzma
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger("pyrosync.remote_seed")


class RemoteSeedError(RuntimeError):
    pass


def blob_base() -> str | None:
    base = os.environ.get("PYROSYNC_BLOB_BASE")
    if base:
        return base.rstrip("/") + "/"
    token = os.environ.get("BLOB_READ_WRITE_TOKEN") or ""
    bits = token.split("_")
    if len(bits) < 5 or not bits[3]:
        return None
    return f"https://{bits[3].lower()}.public.blob.vercel-storage.com/"


def mirror_base(man: dict | None = None) -> str | None:
    base = os.environ.get("PYROSYNC_ARCHIVE_BASE")
    if not base and man is None:
        m = os.environ.get("PYROSYNC_REMOTE_MANIFEST")
        if m and Path(m).is_file():
            man = json.loads(Path(m).read_text(encoding="utf-8"))
    if not base and man:
        base = man.get("base_url")
    return base.rstrip("/") + "/" if base else None


def configured() -> bool:
    m = os.environ.get("PYROSYNC_REMOTE_MANIFEST")
    return bool(m and Path(m).is_file() and (mirror_base() or blob_base()))


def _get(url: str, expect: int, sha: str, deadline: float) -> bytes:
    buf = bytearray()
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "pyrosync-demo"})
    with urllib.request.urlopen(req, timeout=20) as r:
        while True:
            if time.monotonic() > deadline:
                raise RemoteSeedError("download deadline passed")
            b = r.read(1 << 20)
            if not b:
                break
            buf += b
            h.update(b)
    if len(buf) != expect or h.hexdigest() != sha:
        raise RemoteSeedError(f"{url.rsplit('/', 1)[-1]}: size or checksum mismatch")
    return bytes(buf)


def fetch(dest: str | Path) -> dict:
    """Download the parts in parallel, stream them through one xz decompressor into dest.part, verify, rename."""
    t0 = time.monotonic()
    deadline = t0 + float(os.environ.get("PYROSYNC_REMOTE_DEADLINE", "40"))
    man = json.loads(Path(os.environ["PYROSYNC_REMOTE_MANIFEST"]).read_text(encoding="utf-8"))
    mirror = mirror_base(man)
    base = mirror or blob_base()
    if not base:
        raise RemoteSeedError("no archive source configured")
    prefix = "" if mirror else man["prefix"]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(dest) + ".part")
    dec = lzma.LZMADecompressor()
    h = hashlib.sha256()
    n = 0
    with ThreadPoolExecutor(max_workers=len(man["parts"])) as pool:
        futs = [pool.submit(_get, base + prefix + p["name"], p["bytes"], p["sha256"], deadline) for p in man["parts"]]
        with open(tmp, "wb") as out:
            for f in futs:  # in order: part-00, part-01, ...
                data = f.result()
                for i in range(0, len(data), 8 << 20):
                    if time.monotonic() > deadline:
                        raise RemoteSeedError("decompression deadline passed")
                    o = dec.decompress(data[i:i + (8 << 20)])
                    out.write(o)
                    h.update(o)
                    n += len(o)
                del data
    if not dec.eof or n != man["db_bytes"] or h.hexdigest() != man["db_sha256"]:
        tmp.unlink(missing_ok=True)
        raise RemoteSeedError("decompressed database does not match manifest.json")
    tmp.replace(dest)
    info = {"source": "mirror" if mirror else "blob", "seconds": round(time.monotonic() - t0, 1), "bytes": n, "sha256": man["db_sha256"][:16]}
    log.warning("pyrosync: full archive fetched %s", info)
    return info
