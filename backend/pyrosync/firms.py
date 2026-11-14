"""Optional NASA FIRMS Area API connector (server-side; the MAP_KEY never reaches the browser).

Documented interface (https://firms.modaps.eosdis.nasa.gov/api/area/, read 2026-11-14):
  /api/area/csv/[MAP_KEY]/[SOURCE]/[AREA_COORDINATES]/[DAY_RANGE]/[DATE]
  AREA_COORDINATES = west,south,east,north ; DAY_RANGE = 1..5 ;
  DATE = YYYY-MM-DD, returns data for [DATE .. DATE + DAY_RANGE - 1]
  Key limit: 5000 transactions / 10-minute interval (multi-day requests may count as several).
"""
from __future__ import annotations

import hashlib
import io
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import ingest
from .config import get_settings

SOURCES = {
    "MODIS_NRT": ("MODIS", "NRT"), "MODIS_SP": ("MODIS", "SP"),
    "VIIRS_NOAA20_NRT": ("VIIRS_N20", "NRT"), "VIIRS_NOAA20_SP": ("VIIRS_N20", "SP"),
    "VIIRS_NOAA21_NRT": ("VIIRS_N21", "NRT"), "VIIRS_NOAA21_SP": ("VIIRS_N21", "SP"),
    "VIIRS_SNPP_NRT": ("VIIRS_SNPP", "NRT"), "VIIRS_SNPP_SP": ("VIIRS_SNPP", "SP"),
}
MAX_DAY_RANGE = 5
MAX_RETRIES = 3


class FirmsError(Exception):
    pass


def redact(text: str, key: str) -> str:
    if key:
        text = text.replace(key, "***")
    return re.sub(r"(/api/[a-z_]+/csv/)[^/\s]+", r"\1***", text)


def split_windows(start: date, end: date, max_days: int = MAX_DAY_RANGE) -> list[tuple[date, int]]:
    out = []
    d = start
    while d <= end:
        n = min(max_days, (end - d).days + 1)
        out.append((d, n))
        d += timedelta(days=n)
    return out


def validate_bbox(b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    w, s, e, n = b
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise FirmsError("Bounding box must satisfy -180 ≤ west < east ≤ 180 and -90 ≤ south < north ≤ 90 (antimeridian-crossing boxes are not supported).")
    return w, s, e, n


@dataclass
class FirmsJob:
    id: str
    source: str
    bbox: tuple[float, float, float, float]
    start: date
    end: date
    status: str = "queued"
    windows_total: int = 0
    windows_done: int = 0
    cached_hits: int = 0
    rows_downloaded: int = 0
    message: str = ""
    error: str | None = None
    report: dict | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {"id": self.id, "source": self.source, "bbox": self.bbox, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "status": self.status, "windows_total": self.windows_total, "windows_done": self.windows_done, "cached_hits": self.cached_hits,
                "rows_downloaded": self.rows_downloaded, "message": self.message, "error": self.error,
                "report": {k: v for k, v in (self.report or {}).items() if k != "files"} if self.report else None}


JOBS: dict[str, FirmsJob] = {}


def _cache_path(source: str, bbox, d: date, n: int) -> Path:
    h = hashlib.sha1(f"{source}|{','.join(f'{x:.5f}' for x in bbox)}|{d.isoformat()}|{n}".encode()).hexdigest()[:20]
    return get_settings().cache_dir / "firms" / f"{source}_{d.isoformat()}_{n}d_{h}.csv"


def fetch_window(client: httpx.Client, key: str, source: str, bbox, d: date, n: int, cancel: threading.Event | None = None,
                 sleep=time.sleep) -> str:
    s = get_settings()
    area = ",".join(f"{x:g}" for x in bbox)
    url = f"{s.firms_base_url}/api/area/csv/{key}/{source}/{area}/{n}/{d.isoformat()}"
    delay = 2.0
    last = ""
    for attempt in range(MAX_RETRIES + 1):
        if cancel is not None and cancel.is_set():
            raise FirmsError("cancelled")
        try:
            r = client.get(url, timeout=60)
        except httpx.HTTPError as e:
            last = f"network error: {type(e).__name__}"
            if attempt < MAX_RETRIES:
                sleep(delay); delay *= 2
                continue
            raise FirmsError(f"Network failure contacting FIRMS after {MAX_RETRIES + 1} attempts ({last}). Check your internet connection.") from None
        body = r.text
        low = body[:300].lower()
        if "invalid map_key" in low or "invalid api call" in low and "key" in low or r.status_code in (401, 403):
            raise FirmsError("FIRMS rejected the MAP_KEY (invalid or inactive). Check FIRMS_MAP_KEY in your .env file.")
        if r.status_code == 429 or "exceeding allowed transaction limit" in low or "transaction limit" in low:
            last = "rate limit"
            if attempt < MAX_RETRIES:
                sleep(max(delay, 30)); delay *= 2
                continue
            raise FirmsError("FIRMS transaction limit reached (5000 transactions per 10 minutes per key). Wait and retry; cached windows will be reused.")
        if r.status_code >= 500:
            last = f"HTTP {r.status_code}"
            if attempt < MAX_RETRIES:
                sleep(delay); delay *= 2
                continue
            raise FirmsError(f"FIRMS server error ({last}).")
        if r.status_code != 200:
            raise FirmsError(redact(f"FIRMS returned HTTP {r.status_code}: {body[:200]}", key))
        first = body.lstrip().split("\n", 1)[0].lower()
        if "latitude" not in first or "longitude" not in first:
            raise FirmsError(redact(f"Unexpected FIRMS response for {source} {d.isoformat()}: {body[:200].strip()}", key))
        return body
    raise FirmsError(last)  # pragma: no cover


def run_job(job: FirmsJob, client: httpx.Client | None = None, sleep=time.sleep) -> None:
    s = get_settings()
    key = s.firms_map_key
    own = client is None
    try:
        if not key:
            raise FirmsError("No FIRMS_MAP_KEY configured. Add it to .env (server-side) to enable API refresh; local imports work without it.")
        if job.source not in SOURCES:
            raise FirmsError(f"Unknown FIRMS source '{job.source}'.")
        series, stream = SOURCES[job.source]
        validate_bbox(job.bbox)
        windows = split_windows(job.start, job.end)
        job.windows_total = len(windows)
        job.status = "downloading"
        client = client or httpx.Client(follow_redirects=True)
        paths: list[Path] = []
        for d, n in windows:
            if job.cancel.is_set():
                job.status = "cancelled"; job.message = "Cancelled by user; nothing was committed."
                return
            cp = _cache_path(job.source, job.bbox, d, n)
            if cp.is_file():
                job.cached_hits += 1
            else:
                body = fetch_window(client, key, job.source, job.bbox, d, n, job.cancel, sleep=sleep)
                tmp = cp.with_suffix(".part")
                tmp.write_text(body, encoding="utf-8")
                tmp.replace(cp)
            paths.append(cp)
            job.rows_downloaded += max(0, sum(1 for line in cp.read_text(encoding="utf-8").splitlines()[1:] if line.strip()))
            job.windows_done += 1
            job.message = f"Window {job.windows_done}/{job.windows_total} ({d.isoformat()} + {n - 1} days)"
        job.status = "importing"
        sources = []
        for p in paths:
            sources.append(ingest.SourceFile(name=f"firms-api:{p.name}", open=(lambda pp=p: open(pp, "rb")), path_hint=f"{job.source}/{p.name}"))
        declared = [ingest.Declared(start=d, end=d + timedelta(days=n - 1), origin="api-request", series=series, stream=stream, bbox=job.bbox)
                    for d, n in windows]
        opts = ingest.ImportOptions(origin="firms-api", label=f"FIRMS {job.source} {job.start}–{job.end}", stream_override=stream,
                                    declared=declared, use_filename_windows=False, keep_raw=False, cancel=job.cancel)
        job.report = ingest.run_import(sources, opts)
        job.status = "done"
        job.message = f"Imported {job.report['new_observations']:,} new observations (revision {job.report['dataset_revision']})."
    except ingest.Cancelled:
        job.status = "cancelled"; job.message = "Cancelled by user; nothing was committed."
    except FirmsError as e:
        job.status = "cancelled" if str(e) == "cancelled" else "error"
        job.error = redact(str(e), key)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = redact(f"{type(e).__name__}: {e}", key)
    finally:
        if own and client is not None:
            client.close()


def start_job(source: str, bbox, start: date, end: date) -> FirmsJob:
    if end < start:
        raise FirmsError("End date is before start date.")
    if (end - start).days > 3660:
        raise FirmsError("Requested range longer than 10 years; split it, or use archive downloads from https://firms.modaps.eosdis.nasa.gov/download/.")
    job = FirmsJob(id=uuid.uuid4().hex[:12], source=source, bbox=tuple(bbox), start=start, end=end)
    JOBS[job.id] = job
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return job


def availability(client: httpx.Client | None = None) -> dict:
    s = get_settings()
    key = s.firms_map_key
    if not key:
        return {"configured": False, "message": "No FIRMS_MAP_KEY configured."}
    own = client is None
    client = client or httpx.Client(follow_redirects=True)
    try:
        r = client.get(f"{s.firms_base_url}/api/data_availability/csv/{key}/ALL", timeout=30)
        text = r.text
        if r.status_code != 200 or "invalid" in text[:200].lower():
            return {"configured": True, "ok": False, "message": redact(f"FIRMS availability check failed (HTTP {r.status_code}): {text[:160]}", key)}
        import csv
        rows = list(csv.DictReader(io.StringIO(text)))
        return {"configured": True, "ok": True, "rows": rows}
    except httpx.HTTPError as e:
        return {"configured": True, "ok": False, "message": f"Network failure ({type(e).__name__}); FIRMS refresh needs internet access."}
    finally:
        if own:
            client.close()
