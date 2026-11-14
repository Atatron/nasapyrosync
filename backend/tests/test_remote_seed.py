"""Vercel Blob cold-start fetch (remote_seed): a small local HTTP server stands in for the Blob store.

The database used here is a tiny synthetic test fixture (one table), not FIRMS data.
"""
import functools
import hashlib
import http.server
import json
import lzma
import threading

import duckdb
import pytest

from pyrosync import remote_seed


def _serve(root):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def store(tmp_path, monkeypatch):
    db = tmp_path / "src.duckdb"
    c = duckdb.connect(str(db)); c.execute("CREATE TABLE fixture AS SELECT range AS i FROM range(50000)"); c.close()
    raw = db.read_bytes()
    xz = lzma.compress(raw)
    prefix = "pyrosync-full/test/"
    (tmp_path / "blob" / prefix).mkdir(parents=True)
    parts = []
    for k, i in enumerate(range(0, len(xz), len(xz) // 3 + 1)):
        chunk = xz[i:i + len(xz) // 3 + 1]
        name = f"x.part-{k:02d}"
        (tmp_path / "blob" / prefix / name).write_bytes(chunk)
        parts.append({"name": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
    man = {"prefix": prefix, "db_sha256": hashlib.sha256(raw).hexdigest(), "db_bytes": len(raw), "parts": parts}
    (tmp_path / "manifest.json").write_text(json.dumps(man))
    srv = _serve(tmp_path / "blob")
    monkeypatch.setenv("PYROSYNC_REMOTE_MANIFEST", str(tmp_path / "manifest.json"))
    monkeypatch.setenv("PYROSYNC_BLOB_BASE", f"http://127.0.0.1:{srv.server_address[1]}/")
    yield tmp_path, man
    srv.shutdown()


def test_fetch_rebuilds_and_verifies(store):
    tmp, man = store
    assert len(man["parts"]) == 3 and remote_seed.configured()
    info = remote_seed.fetch(tmp / "out.duckdb")
    assert info["bytes"] == man["db_bytes"]
    c = duckdb.connect(str(tmp / "out.duckdb"), read_only=True)
    assert c.execute("SELECT count(*) FROM fixture").fetchone()[0] == 50000


def test_corrupt_part_is_rejected(store):
    tmp, man = store
    p = tmp / "blob" / man["prefix"] / man["parts"][1]["name"]
    b = bytearray(p.read_bytes()); b[10] ^= 0xFF; p.write_bytes(bytes(b))
    with pytest.raises(remote_seed.RemoteSeedError):
        remote_seed.fetch(tmp / "out.duckdb")
    assert not (tmp / "out.duckdb").exists()


def test_store_id_from_token_without_exposing_it(monkeypatch):
    monkeypatch.delenv("PYROSYNC_BLOB_BASE", raising=False)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_AbC123_secretpart")
    assert remote_seed.blob_base() == "https://abc123.public.blob.vercel-storage.com/"
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN")
    assert remote_seed.blob_base() is None
