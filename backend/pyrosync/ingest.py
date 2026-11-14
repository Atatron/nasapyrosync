"""Repeatable import pipeline: inspect -> validate -> normalize -> deduplicate/reconcile -> commit.

The same pipeline is used by browser uploads, the CLI, and the optional FIRMS
API connector.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import threading
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

try:
    import pyarrow as pa
except ImportError:  # read-only deployment
    pa = None

from . import normalize as N
from .config import PROCESSING_VERSION, get_settings
from .db import cursor, get_revision, write_lock

OBS_COLUMNS = [
    "record_key", "acq_date", "acq_ts", "acq_hhmm", "lat", "lon", "lat_e5", "lon_e5", "instrument", "platform",
    "satellite_raw", "series", "source_product", "stream", "version", "conf_raw", "conf_num", "conf_cat", "frp",
    "daynight", "type_code", "scan", "track", "modis_brightness", "modis_bright_t31", "viirs_bright_ti4",
    "viirs_bright_ti5",
]
if pa is not None:  # pyarrow is needed only for imports (absent in the read-only web demo)
    ARROW_SCHEMA = pa.schema([
        ("record_key", pa.string()), ("acq_date", pa.date32()), ("acq_ts", pa.timestamp("us")), ("acq_hhmm", pa.string()),
        ("lat", pa.float64()), ("lon", pa.float64()), ("lat_e5", pa.int32()), ("lon_e5", pa.int32()),
        ("instrument", pa.string()), ("platform", pa.string()), ("satellite_raw", pa.string()), ("series", pa.string()),
        ("source_product", pa.string()), ("stream", pa.string()), ("version", pa.string()), ("conf_raw", pa.string()),
        ("conf_num", pa.int16()), ("conf_cat", pa.string()), ("frp", pa.float64()), ("daynight", pa.string()),
        ("type_code", pa.int16()), ("scan", pa.float64()), ("track", pa.float64()), ("modis_brightness", pa.float64()),
        ("modis_bright_t31", pa.float64()), ("viirs_bright_ti4", pa.float64()), ("viirs_bright_ti5", pa.float64()),
        ("source_file", pa.string()), ("source_row", pa.int32()), ("file_seq", pa.int32()),
    ])
MAX_STORED_REJECTIONS = 200_000
PREVIEW_ROWS = 5


class ImportError_(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class SourceFile:
    name: str                      # display / provenance name (zip member path or file name)
    open: Callable[[], io.BufferedIOBase]
    size: int | None = None
    path_hint: str = ""            # used for SP/NRT and platform detection


@dataclass
class Declared:
    start: date
    end: date
    origin: str                    # 'cli-declared' | 'api-request'
    series: str | None = None
    stream: str | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class ImportOptions:
    origin: str = "upload"         # upload | cli | firms-api
    label: str = ""
    dry_run: bool = False
    stream_override: str | None = None
    declared: list[Declared] = field(default_factory=list)
    use_filename_windows: bool = True
    raw_paths: list[Path] = field(default_factory=list)  # original inputs to preserve
    keep_raw: bool | None = None
    progress: Callable[[dict], None] | None = None
    cancel: threading.Event | None = None


# ------------------------------------------------------------------ ZIP safety
def safe_zip_members(zpath: Path) -> tuple[list[SourceFile], list[str]]:
    s = get_settings()
    warnings: list[str] = []
    files: list[SourceFile] = []
    try:
        zf = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        raise ImportError_(f"{zpath.name}: not a valid ZIP archive") from None
    infos = zf.infolist()
    if len(infos) > s.max_zip_entries:
        raise ImportError_(f"{zpath.name}: {len(infos)} entries exceeds limit {s.max_zip_entries}")
    total = 0
    for info in infos:
        name = info.filename
        p = PurePosixPath(name.replace("\\", "/"))
        if name.startswith("/") or p.is_absolute() or ".." in p.parts or (len(name) > 1 and name[1] == ":"):
            raise ImportError_(f"{zpath.name}: unsafe path '{name}' rejected")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ImportError_(f"{zpath.name}: symbolic link '{name}' rejected")
        total += info.file_size
        if total > s.max_zip_expanded_bytes:
            raise ImportError_(f"{zpath.name}: expanded size exceeds {s.max_zip_expanded_bytes // (1024*1024)} MB limit")
        if info.compress_size > 0 and info.file_size / info.compress_size > s.max_zip_ratio and info.file_size > 10 * 1024 * 1024:
            raise ImportError_(f"{zpath.name}: '{name}' has a suspicious compression ratio")
        if info.is_dir():
            continue
        if any(part.startswith("__MACOSX") for part in p.parts) or p.name.startswith("._"):
            continue
        if p.suffix.lower() == ".zip":
            warnings.append(f"Nested archive '{name}' ignored; extract it and import separately.")
            continue
        if p.suffix.lower() != ".csv":
            warnings.append(f"Non-CSV file '{name}' ignored.")
            continue
        files.append(SourceFile(name=f"{zpath.name}:{name}", open=(lambda zp=zpath, n=name: zipfile.ZipFile(zp).open(n)),
                                size=info.file_size, path_hint=name))
    return sorted(files, key=lambda f: f.name), warnings


def collect_sources(paths: Iterable[Path]) -> tuple[list[SourceFile], list[str]]:
    """Expand a mix of CSV files, ZIP archives and directories."""
    out: list[SourceFile] = []
    warnings: list[str] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file() and sub.suffix.lower() in {".csv", ".zip"}:
                    f, w = collect_sources([sub])
                    # keep path relative to the directory for provenance
                    for sf in f:
                        if not sf.path_hint or sf.path_hint in (sub.name, f"{sub.parent.name}/{sub.name}"):
                            sf.path_hint = str(sub.relative_to(p))
                            sf.name = str(sub.relative_to(p))
                    out += f
                    warnings += w
        elif p.suffix.lower() == ".zip":
            f, w = safe_zip_members(p)
            out += f
            warnings += w
        elif p.suffix.lower() == ".csv":
            out.append(SourceFile(name=p.name, open=(lambda pp=p: open(pp, "rb")), size=p.stat().st_size,
                                  path_hint=f"{p.parent.name}/{p.name}" if p.parent.name else p.name))
        else:
            warnings.append(f"Unsupported file '{p.name}' ignored (expected .csv or .zip).")
    return out, warnings


# ------------------------------------------------------------------ pipeline
class _Builder:
    def __init__(self) -> None:
        self.cols: dict[str, list] = {c.name: [] for c in ARROW_SCHEMA}

    def add(self, o: N.Obs, source_file: str, row: int, seq: int) -> None:
        c = self.cols
        for k in OBS_COLUMNS:
            c[k].append(getattr(o, k))
        c["source_file"].append(source_file)
        c["source_row"].append(row)
        c["file_seq"].append(seq)

    def __len__(self) -> int:
        return len(self.cols["record_key"])

    def table(self):
        return pa.table(self.cols, schema=ARROW_SCHEMA)


def _emit(opts: ImportOptions, **kw) -> None:
    if opts.progress:
        opts.progress(kw)


def run_import(sources: list[SourceFile], opts: ImportOptions, pre_warnings: list[str] | None = None) -> dict:
    """Run the full pipeline. Returns the import report (also persisted)."""
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started = datetime.now(timezone.utc)
    warnings = list(pre_warnings or [])
    files_report: list[dict] = []
    rejections: list[tuple[str, int, str]] = []
    reason_counts: Counter = Counter()
    intervals: list[dict] = []
    staging_name = f"staging_{batch_id.replace('-', '_')}"
    rows_read = 0
    accepted_rows = 0
    platforms: Counter = Counter()
    products: Counter = Counter()
    versions: Counter = Counter()
    dmin = dmax = None
    lat_min = lon_min = float("inf")
    lat_max = lon_max = float("-inf")

    with cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE {staging_name} AS SELECT * FROM (SELECT NULL::VARCHAR AS x) WHERE false")
        cur.execute(f"DROP TABLE {staging_name}")
        first_chunk = True
        for seq, sf in enumerate(sources):
            if opts.cancel is not None and opts.cancel.is_set():
                raise Cancelled()
            _emit(opts, stage="reading", file=sf.name, index=seq, total=len(sources), rows_read=rows_read)
            fr: dict = {"file": sf.name, "rows_read": 0, "accepted": 0, "rejected": 0, "instrument": None,
                        "platforms": [], "stream": None, "versions": [], "declared_window": None,
                        "columns": [], "missing_required": [], "preview": [], "status": "ok", "warnings": []}
            files_report.append(fr)
            try:
                raw = sf.open()
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                reader = csv.reader(text)
                try:
                    header = next(reader)
                except StopIteration:
                    fr["status"] = "empty-no-header"
                    fr["warnings"].append("File is empty (no header); skipped.")
                    warnings.append(f"{sf.name}: empty file without header skipped")
                    continue
                header = [h.strip().lower() for h in header]
                fr["columns"] = header
                instrument, missing = N.detect_schema(header)
                fr["instrument"] = instrument
                fr["missing_required"] = missing
                if instrument is None or missing:
                    fr["status"] = "rejected-schema"
                    msg = "unrecognized schema (not FIRMS MODIS or VIIRS)" if instrument is None else f"missing required columns: {', '.join(missing)}"
                    fr["warnings"].append(msg)
                    warnings.append(f"{sf.name}: {msg}")
                    continue
                hint = sf.path_hint or sf.name
                stream_hint = opts.stream_override or N.stream_from_path(hint)
                fr["stream_hint"] = stream_hint
                window = N.declared_window(PurePosixPath(hint).name) if opts.use_filename_windows else None
                if window:
                    fr["declared_window"] = [window[0].isoformat(), window[1].isoformat()]
                b = _Builder()
                fplat: Counter = Counter()
                fver: Counter = Counter()
                fstreams: Counter = Counter()
                outside_window = 0
                for i, rowvals in enumerate(reader, start=2):  # row 1 is the header
                    if not rowvals or all(not v.strip() for v in rowvals):
                        continue
                    fr["rows_read"] += 1
                    if len(rowvals) != len(header):
                        reason = f"expected {len(header)} fields, found {len(rowvals)}"
                        fr["rejected"] += 1
                        reason_counts[reason.split(",")[0]] += 1
                        if len(rejections) < MAX_STORED_REJECTIONS:
                            rejections.append((sf.name, i, reason))
                        continue
                    row = dict(zip(header, rowvals))
                    if len(fr["preview"]) < PREVIEW_ROWS:
                        fr["preview"].append(row)
                    try:
                        o = N.normalize_row(row, instrument, stream_hint)
                    except N.RowError as e:
                        fr["rejected"] += 1
                        reason = str(e)
                        key = reason.split("'")[0].strip() if "'" in reason else reason
                        reason_counts[key] += 1
                        if len(rejections) < MAX_STORED_REJECTIONS:
                            rejections.append((sf.name, i, reason))
                        continue
                    b.add(o, sf.name, i, seq)
                    fplat[o.platform] += 1
                    fver[o.version or "(none)"] += 1
                    fstreams[o.stream] += 1
                    products[o.source_product] += 1
                    if window and not (window[0] <= o.acq_date <= window[1]):
                        outside_window += 1
                    if dmin is None or o.acq_date < dmin:
                        dmin = o.acq_date
                    if dmax is None or o.acq_date > dmax:
                        dmax = o.acq_date
                    lat_min = min(lat_min, o.lat); lat_max = max(lat_max, o.lat)
                    lon_min = min(lon_min, o.lon); lon_max = max(lon_max, o.lon)
                rows_read += fr["rows_read"]
                fr["accepted"] = len(b)
                accepted_rows += len(b)
                fr["platforms"] = sorted(fplat)
                fr["versions"] = sorted(fver)
                fr["stream"] = ", ".join(sorted(fstreams)) if fstreams else (stream_hint or "unknown")
                platforms.update(fplat)
                versions.update(fver)
                if outside_window:
                    fr["warnings"].append(f"{outside_window} rows fall outside the file-name window; each row is assigned by its own acq_date.")
                if fr["rows_read"] == 0:
                    fr["status"] = "empty-valid"
                # declared interval(s) for coverage bookkeeping
                if window:
                    series_set = {N.PLATFORM_SERIES[p] for p in fplat}
                    if not series_set:
                        if instrument == "MODIS":
                            series_set = {"MODIS"}
                        else:
                            p = N.platform_from_path(hint)
                            if p:
                                series_set = {N.PLATFORM_SERIES[p]}
                    if not series_set:
                        fr["warnings"].append("Empty VIIRS file without a recognizable platform in its name; its window was not recorded as coverage.")
                    for s_ in sorted(series_set):
                        intervals.append({"series": s_, "stream": (fstreams.most_common(1)[0][0] if fstreams else (stream_hint or "unknown")),
                                          "start": window[0], "end": window[1], "origin": "filename-declared", "bbox": None, "file": sf.name})
                if len(b):
                    tbl = b.table()
                    cur.register("chunk_tbl", tbl)
                    if first_chunk:
                        cur.execute(f"CREATE TEMP TABLE {staging_name} AS SELECT * FROM chunk_tbl")
                        first_chunk = False
                    else:
                        cur.execute(f"INSERT INTO {staging_name} SELECT * FROM chunk_tbl")
                    cur.unregister("chunk_tbl")
            except UnicodeDecodeError:
                fr["status"] = "rejected-encoding"
                fr["warnings"].append("File is not UTF-8 text.")
                warnings.append(f"{sf.name}: not UTF-8 text; skipped")
            except csv.Error as e:
                fr["status"] = "rejected-csv"
                fr["warnings"].append(f"CSV parse error: {e}")
                warnings.append(f"{sf.name}: CSV parse error")
        for d in opts.declared:
            series_list = [d.series] if d.series else sorted({N.PLATFORM_SERIES[p] for p in platforms})
            for s_ in series_list:
                intervals.append({"series": s_, "stream": d.stream or opts.stream_override or "unknown", "start": d.start, "end": d.end,
                                  "origin": d.origin, "bbox": d.bbox, "file": None})

        report = {
            "batch_id": batch_id, "origin": opts.origin, "label": opts.label, "dry_run": opts.dry_run,
            "processing_version": PROCESSING_VERSION,
            "started_at": started.isoformat(), "files_processed": len(sources),
            "files": files_report, "rows_read": rows_read, "accepted_rows": accepted_rows,
            "rejected_rows": sum(f["rejected"] for f in files_report),
            "rejection_reasons": dict(reason_counts.most_common()),
            "date_range": [dmin.isoformat(), dmax.isoformat()] if dmin else None,
            "platforms": dict(platforms), "source_products": dict(products), "versions": dict(versions),
            "geographic_extent": {"west": lon_min, "south": lat_min, "east": lon_max, "north": lat_max} if dmin else None,
            "declared_intervals": len(intervals), "warnings": warnings,
        }
        _emit(opts, stage="committing", rows_read=rows_read)
        if first_chunk:  # nothing staged
            cur.execute(f"CREATE TEMP TABLE {staging_name} AS SELECT * FROM (SELECT * FROM range(0)) WHERE false")
            staged = 0
        else:
            staged = cur.execute(f"SELECT count(*) FROM {staging_name}").fetchone()[0]
        try:
            if opts.dry_run:
                if staged:
                    dup_existing = cur.execute(
                        f"SELECT count(*) FROM {staging_name} s WHERE EXISTS (SELECT 1 FROM observations o WHERE o.record_key = s.record_key)").fetchone()[0]
                    distinct_new = cur.execute(
                        f"SELECT count(DISTINCT record_key) FROM {staging_name} s WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.record_key = s.record_key)").fetchone()[0]
                else:
                    dup_existing = distinct_new = 0
                report.update({"new_observations": distinct_new, "duplicate_rows": staged - distinct_new,
                               "duplicates_of_existing": dup_existing, "superseded_nrt_rows": None,
                               "dataset_revision": get_revision(cur), "revision_changed": False, "status": "inspected"})
                return report
            with write_lock:
                report.update(_commit(cur, staging_name, staged, batch_id, intervals, report, opts))
        finally:
            cur.execute(f"DROP TABLE IF EXISTS {staging_name}")

    _persist_report(report, rejections)
    _preserve_raw(batch_id, opts)
    return report


def _commit(cur, staging: str, staged: int, batch_id: str, intervals: list[dict], report: dict, opts: ImportOptions) -> dict:
    rev_before = get_revision(cur)
    cur.execute("BEGIN TRANSACTION")
    try:
        if staged:
            cur.execute(f"""CREATE TEMP TABLE ranked AS
                SELECT *, row_number() OVER (PARTITION BY record_key ORDER BY file_seq, source_row) AS rn,
                       EXISTS (SELECT 1 FROM observations o WHERE o.record_key = s.record_key) AS existed
                FROM {staging} s""")
            new_n = cur.execute("SELECT count(*) FROM ranked WHERE rn = 1 AND NOT existed").fetchone()[0]
            dup_existing = cur.execute("SELECT count(*) FROM ranked WHERE existed").fetchone()[0]
            max_rid = cur.execute("SELECT coalesce(max(rid), 0) FROM observations").fetchone()[0]
            cols = ", ".join(OBS_COLUMNS)
            cur.execute(f"""INSERT INTO observations (rid, {cols}, batch_id, source_file, source_row)
                SELECT ? + row_number() OVER (ORDER BY acq_date, acq_ts, record_key), {cols}, ?, source_file, source_row
                FROM ranked WHERE rn = 1 AND NOT existed""", [max_rid, batch_id])
            cur.execute("""INSERT INTO provenance SELECT record_key, ?, source_file, source_row,
                CASE WHEN rn = 1 AND NOT existed THEN 'first' ELSE 'duplicate' END FROM ranked""", [batch_id])
            cur.execute("DROP TABLE ranked")
        else:
            new_n = dup_existing = 0
        for iv in intervals:
            bb = iv["bbox"] or (None, None, None, None)
            cur.execute("INSERT INTO import_intervals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [batch_id, iv["series"], iv["stream"], iv["start"], iv["end"], iv["origin"], *bb, iv["file"]])
        superseded = _reconcile_streams(cur, batch_id)
        changed = new_n > 0 or superseded > 0 or len(intervals) > 0
        # interval rows that exactly repeat existing ones do not count as a change
        if new_n == 0 and superseded == 0 and intervals:
            dup_iv = cur.execute("""SELECT count(*) FROM import_intervals a WHERE a.batch_id = ? AND EXISTS (
                SELECT 1 FROM import_intervals b WHERE b.batch_id <> a.batch_id AND b.series = a.series AND b.stream = a.stream
                AND b.start_date = a.start_date AND b.end_date = a.end_date AND b.origin = a.origin
                AND b.west IS NOT DISTINCT FROM a.west AND b.south IS NOT DISTINCT FROM a.south
                AND b.east IS NOT DISTINCT FROM a.east AND b.north IS NOT DISTINCT FROM a.north)""", [batch_id]).fetchone()[0]
            changed = dup_iv < len(intervals)
        rev_after = rev_before + 1 if changed else rev_before
        if changed:
            cur.execute("UPDATE dataset_meta SET value = ? WHERE key = 'revision'", [str(rev_after)])
            cur.execute("DELETE FROM aoi_members")
            cur.execute("DELETE FROM aoi_cache_state")
        result = {"new_observations": new_n, "duplicate_rows": staged - new_n, "duplicates_of_existing": dup_existing,
                  "superseded_nrt_rows": superseded, "dataset_revision": rev_after, "revision_changed": changed,
                  "status": "committed", "finished_at": datetime.now(timezone.utc).isoformat()}
        full = {**report, **result}
        cur.execute("INSERT INTO import_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [batch_id, opts.origin, opts.label, report["started_at"], result["finished_at"], "committed", rev_after,
                     json.dumps(full, default=str)])
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    from . import cache
    cache.invalidate()
    return result


def _reconcile_streams(cur, batch_id: str) -> int:
    """SP (standard processing) supersedes NRT/RT/URT for the same platform and UTC day.

    Record-level matching between NRT and SP is not attempted because positions
    and attributes can change between processing streams. Superseded rows are
    retained (superseded = TRUE) for audit and excluded from every analysis.
    """
    cur.execute("""CREATE TEMP TABLE sp_days AS
        SELECT DISTINCT platform, acq_date FROM observations WHERE stream = 'SP'
        UNION
        SELECT DISTINCT p.platform, CAST(d.generate_series AS DATE) AS acq_date
        FROM import_intervals i
        JOIN (VALUES ('MODIS','Terra'), ('MODIS','Aqua'), ('VIIRS_N20','N20'), ('VIIRS_N21','N21'), ('VIIRS_SNPP','SNPP')) p(series, platform)
          ON p.series = i.series
        CROSS JOIN generate_series(i.start_date, i.end_date, INTERVAL 1 DAY) d
        WHERE i.stream = 'SP'""")
    n = cur.execute("""SELECT count(*) FROM observations o JOIN sp_days s USING (platform, acq_date)
        WHERE o.stream IN ('NRT', 'RT', 'URT') AND NOT o.superseded""").fetchone()[0]
    if n:
        cur.execute("""UPDATE observations SET superseded = TRUE, superseded_by = ?
            WHERE stream IN ('NRT', 'RT', 'URT') AND NOT superseded
            AND (platform, acq_date) IN (SELECT platform, acq_date FROM sp_days)""", [f"SP coverage (batch {batch_id})"])
    cur.execute("DROP TABLE sp_days")
    return n


def _persist_report(report: dict, rejections: list[tuple[str, int, str]]) -> None:
    s = get_settings()
    rp = s.reports_dir / f"{report['batch_id']}.json"
    rp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    with open(s.reports_dir / f"{report['batch_id']}_rejections.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source_file", "row_number", "reason"])
        w.writerows(rejections)
        if len(rejections) >= MAX_STORED_REJECTIONS:
            w.writerow(["(truncated)", "", f"only the first {MAX_STORED_REJECTIONS} rejections are listed"])


def _preserve_raw(batch_id: str, opts: ImportOptions) -> None:
    keep = get_settings().keep_raw_uploads if opts.keep_raw is None else opts.keep_raw
    if not keep or not opts.raw_paths:
        return
    dest = get_settings().raw_dir / batch_id
    dest.mkdir(parents=True, exist_ok=True)
    for p in opts.raw_paths:
        p = Path(p)
        if p.is_dir():
            shutil.copytree(p, dest / p.name, dirs_exist_ok=True)
        elif p.is_file():
            shutil.copy2(p, dest / p.name)


def import_paths(paths: list[Path], opts: ImportOptions) -> dict:
    sources, warnings = collect_sources(paths)
    if not opts.raw_paths:
        opts.raw_paths = list(paths)
    return run_import(sources, opts, warnings)


def list_batches() -> list[dict]:
    with cursor() as cur:
        rows = cur.execute("SELECT report_json FROM import_batches ORDER BY started_at DESC").fetchall()
    out = []
    for (rj,) in rows:
        r = json.loads(rj)
        r.pop("files", None)
        out.append(r)
    return out


def get_batch(batch_id: str) -> dict | None:
    with cursor() as cur:
        row = cur.execute("SELECT report_json FROM import_batches WHERE batch_id = ?", [batch_id]).fetchone()
    return json.loads(row[0]) if row else None


def group_counts(xs: Iterable[str]) -> dict:
    d: dict = defaultdict(int)
    for x in xs:
        d[x] += 1
    return dict(d)
