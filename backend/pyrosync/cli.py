"""Command-line interface.

    python -m pyrosync.cli import PATH [PATH ...] [--dry-run] [--declare START END] [--bbox W S E N] [--stream SP|NRT]
    python -m pyrosync.cli status
    python -m pyrosync.cli history
    python -m pyrosync.cli serve
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from . import ingest, query
from .config import get_settings


def _progress(ev: dict) -> None:
    if ev.get("stage") == "reading":
        i, t = ev.get("index", 0) + 1, ev.get("total", 0)
        if i == 1 or i % 25 == 0 or i == t:
            print(f"  [{i}/{t}] {ev.get('file')}  rows read so far: {ev.get('rows_read', 0):,}", file=sys.stderr)
    elif ev.get("stage") == "committing":
        print("  committing (deduplicate, reconcile, update revision)...", file=sys.stderr)


def _print_report(r: dict) -> None:
    keys = ["batch_id", "status", "files_processed", "rows_read", "accepted_rows", "rejected_rows", "new_observations", "duplicate_rows",
            "superseded_nrt_rows", "date_range", "platforms", "source_products", "versions", "geographic_extent", "dataset_revision", "revision_changed"]
    for k in keys:
        if k in r:
            print(f"{k:>22}: {r[k]}")
    if r.get("rejection_reasons"):
        print("     rejection_reasons:")
        for k, v in r["rejection_reasons"].items():
            print(f"        {v:>8,}  {k}")
    for w in r.get("warnings", [])[:20]:
        print(f"  warning: {w}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyrosync", description="PyroSync local data tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    im = sub.add_parser("import", help="Import FIRMS CSV files, ZIP archives, or directories")
    im.add_argument("paths", nargs="+", type=Path)
    im.add_argument("--dry-run", action="store_true", help="Inspect and validate without committing")
    im.add_argument("--declare", nargs=2, metavar=("START", "END"), help="Declare the requested date interval (YYYY-MM-DD, inclusive)")
    im.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"), help="Bounding box of the original request")
    im.add_argument("--stream", choices=["SP", "NRT", "URT", "RT"], help="Override processing-stream detection")
    im.add_argument("--no-filename-windows", action="store_true", help="Do not treat '<date>_<N>d' file names as declared windows")
    im.add_argument("--no-copy-raw", action="store_true", help="Do not copy original inputs into data/raw")
    im.add_argument("--label", default="")
    im.add_argument("--json", action="store_true", help="Print the full JSON report")
    sub.add_parser("status", help="Show dataset inventory")
    sub.add_parser("history", help="List import batches")
    sv = sub.add_parser("serve", help="Run the web application")
    sv.add_argument("--host", default=None)
    sv.add_argument("--port", type=int, default=None)
    a = ap.parse_args(argv)
    s = get_settings()

    if a.cmd == "import":
        for p in a.paths:
            if not p.exists():
                print(f"error: {p} does not exist", file=sys.stderr)
                return 2
        declared = []
        if a.declare:
            declared.append(ingest.Declared(date.fromisoformat(a.declare[0]), date.fromisoformat(a.declare[1]), "cli-declared",
                                            stream=a.stream, bbox=tuple(a.bbox) if a.bbox else None))
        opts = ingest.ImportOptions(origin="cli", label=a.label, dry_run=a.dry_run, stream_override=a.stream, declared=declared,
                                    use_filename_windows=not a.no_filename_windows, keep_raw=not a.no_copy_raw, progress=_progress)
        t0 = time.time()
        print(f"Importing into {s.db_path}", file=sys.stderr)
        r = ingest.import_paths(list(a.paths), opts)
        print(f"Done in {time.time() - t0:.1f} s", file=sys.stderr)
        print(json.dumps(r, indent=2, default=str) if a.json else "", end="")
        if not a.json:
            _print_report(r)
            if not a.dry_run:
                print(f"\nValidation report: {s.reports_dir / (r['batch_id'] + '.json')}")
        return 0
    if a.cmd == "status":
        print(json.dumps(query.inventory(), indent=2, default=str))
        return 0
    if a.cmd == "history":
        for b in ingest.list_batches():
            print(f"{b['batch_id']}  {b.get('origin'):>9}  rows={b.get('rows_read'):>9,}  new={b.get('new_observations'):>9,}  "
                  f"dup={b.get('duplicate_rows'):>9,}  rev={b.get('dataset_revision')}")
        return 0
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("pyrosync.api:app", host=a.host or s.host, port=a.port or s.port, log_level="info")
        return 0
    return 1


def _entry() -> int:
    import duckdb
    try:
        return main()
    except duckdb.IOException as e:
        if "lock" in str(e).lower():
            print("The PyroSync database is in use by another process (most likely the running web server).\n"
                  "Stop the server (Ctrl+C in its window) and run this command again, or import through the browser:\n"
                  "Data & Methods -> Import.", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(_entry())
