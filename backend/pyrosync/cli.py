"""Command-line interface.

    python -m pyrosync.cli import PATH [PATH ...] [--dry-run] [--declare START END] [--bbox W S E N] [--stream SP|NRT]
    python -m pyrosync.cli status
    python -m pyrosync.cli history
    python -m pyrosync.cli serve
    python -m pyrosync.cli harmonize --start 2012-01-20 --end 2026-11-10 [--aoi region:kalimantan] [--viirs VIIRS_SNPP] --out DIR
    python -m pyrosync.cli harmonize-audit --out DIR [--runs A,B,C,D,E]
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
    hz = sub.add_parser("harmonize", help="Run the three-stage MODIS-VIIRS harmonization and write a validation package")
    hz.add_argument("--start", required=True)
    hz.add_argument("--end", required=True)
    hz.add_argument("--aoi", default="none")
    hz.add_argument("--viirs", default="VIIRS_SNPP", choices=["VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"])
    hz.add_argument("--modis", default="Aqua", help="Comma-separated MODIS platforms (Aqua, Terra)")
    hz.add_argument("--tolerance", type=int, default=30, help="Time tolerance in minutes")
    hz.add_argument("--grid", type=float, default=0.1, help="Comparison grid in degrees (0.1, 0.25, 0.5, 1.0)")
    hz.add_argument("--metric", default="detections", choices=["detections", "frp_sum"])
    hz.add_argument("--unit-set", default="matched", choices=["matched", "matched_plus_proxy"])
    hz.add_argument("--test-fraction", type=float, default=0.2)
    hz.add_argument("--split-date", default=None)
    hz.add_argument("--title", default="Harmonization validation report")
    hz.add_argument("--out", type=Path, required=True, help="Output folder for report.md, report.json and units.csv")
    hz.add_argument("--no-units", action="store_true", help="Do not write units.csv (it can be large)")
    au = sub.add_parser("harmonize-audit", help="Audit matching, leakage, metrics, alternatives and application on the imported archive")
    au.add_argument("--out", type=Path, required=True, help="Output folder for AUDIT.md and audit.json")
    au.add_argument("--runs", default=None, help="Comma-separated subset of runs (A,B,C,D,E)")
    ag = sub.add_parser("harmonize-aggregate", help="Day-level ratio calibration reports (1.4) for the standard runs A, C, D and the Terra control F")
    ag.add_argument("--out", type=Path, required=True, help="Output folder (one sub-folder per run, plus AGGREGATE.md)")
    ag.add_argument("--runs", default=None, help="Comma-separated subset of runs (A,C,D,F)")
    ag.add_argument("--with-events", action="store_true", help="Also build the event-level run to compare its daily sums (slower)")
    ins = sub.add_parser("insights", help="Write the AOI Insights package (regime, critical periods, years, recurrence) for one AOI and sensor")
    ins.add_argument("--aoi", required=True, help="AOI id, e.g. region:kalimantan")
    ins.add_argument("--series", default="MODIS", choices=["MODIS", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21"])
    ins.add_argument("--metric", default="detections", choices=["detections", "cells"])
    ins.add_argument("--as-of", required=True, help="Last day of the history (YYYY-MM-DD); its year is the focus year")
    ins.add_argument("--out", type=Path, required=True, help="Output folder")
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
    if a.cmd == "harmonize":
        from . import harmonize as H
        f = query.Filters(start=date.fromisoformat(a.start), end=date.fromisoformat(a.end), aoi=a.aoi)
        cfg = H.HarmonizeConfig(viirs_series=a.viirs, modis_platforms=[x.strip() for x in a.modis.split(",") if x.strip()],
                                tolerance_min=a.tolerance, unit_grid=a.grid, metric=a.metric, unit_set=a.unit_set,
                                test_fraction=a.test_fraction, split_date=date.fromisoformat(a.split_date) if a.split_date else None)
        t0 = time.time()
        res = H.harmonize(f, cfg, include_units=True)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "report.md").write_text(H.report_markdown(res, a.title), encoding="utf-8")
        (a.out / "report.json").write_text(json.dumps({k: v for k, v in res.items() if k != "units"}, indent=2, default=str), encoding="utf-8")
        if not a.no_units:
            (a.out / "units.csv").write_text(H.units_csv(res), encoding="utf-8")
        s3 = res["stage3"]
        print(f"Done in {time.time() - t0:.1f} s. Matched units: {res['stage2']['class_counts']['matched']:,}. Stage 3: {s3['status']}.")
        if s3["status"] == "ok":
            ho = s3["evaluation"]["held_out"]
            print(f"alpha={s3['fit']['alpha']:.4f} beta={s3['fit']['beta']:.4f}  held-out MAE {ho['unadjusted']['mae']:.3f} -> {ho['calibrated']['mae']:.3f}")
        print(f"Wrote {a.out}/report.md, report.json" + ("" if a.no_units else ", units.csv"))
        return 0
    if a.cmd == "insights":
        from . import exports
        import io, zipfile
        end = date.fromisoformat(a.as_of)
        f = query.Filters(start=date(end.year, 1, 1), end=end, aoi=a.aoi)
        a.out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(exports.insights_zip(f, a.series, a.metric))) as z:
            z.extractall(a.out)
        print(f"Wrote the AOI Insights package to {a.out}")
        return 0
    if a.cmd == "harmonize-aggregate":
        from . import aggregate as A
        from . import calibration as C
        from . import harmonize as H
        runs = [("A", "Indonesia, Aqua–S-NPP", dict(start="2012-01-20"), dict()),
                ("C", "Indonesia, Aqua–NOAA-20", dict(start="2018-04-01"), dict(viirs_series="VIIRS_N20", tolerance_min=60)),
                ("D", "Kalimantan, Aqua–S-NPP", dict(start="2012-01-20", aoi="region:kalimantan"), dict()),
                ("F", "Indonesia, Terra–S-NPP (different overpass time; control)", dict(start="2012-01-20"), dict(modis_platforms=["Terra"]))]
        only = [x.strip() for x in a.runs.split(",")] if a.runs else None
        summary = []
        for rid, label, fk, ck in runs:
            if only and rid not in only:
                continue
            t0 = time.time()
            f = query.Filters(start=date.fromisoformat(fk["start"]), end=date(2026, 11, 14), aoi=fk.get("aoi", "none"))
            cfg = H.HarmonizeConfig(**ck)
            core = C.core(f, cfg) if a.with_events else None
            rep = A.report(f, cfg, core)
            d = a.out / rid
            d.mkdir(parents=True, exist_ok=True)
            (d / "report.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
            (d / "report.md").write_text(A.report_markdown(rep, f"Run {rid}: {label}"), encoding="utf-8")
            summary.append((rid, label, rep))
            C.clear()
            print(f"aggregate {rid} done in {time.time() - t0:.1f} s", flush=True)
        (a.out / "AGGREGATE.md").write_text(A.summary_markdown(summary), encoding="utf-8")
        print(f"Wrote {a.out}/AGGREGATE.md")
        return 0
    if a.cmd == "harmonize-audit":
        from . import audit
        audit.run_audit(a.out, [x.strip() for x in a.runs.split(",")] if a.runs else None)
        print(f"Wrote {a.out}/AUDIT.md, audit.json")
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
