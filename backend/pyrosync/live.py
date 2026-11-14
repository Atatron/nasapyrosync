"""Now vs. history (added in 1.3): the last days of FIRMS near-real-time (NRT) data for the AOI, scored against history.

NRT rows are fetched with the server-side MAP_KEY, filtered in memory and NEVER written to the database, so the
archive and the read-only demo stay unchanged. NRT data are provisional: FIRMS later replaces them with standard
(SP) processing, and counts can change.
"""
from __future__ import annotations

import csv
import io
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np
import shapely

from . import aoi as A
from . import climate
from . import firms
from . import normalize as N
from .config import get_settings
from .insights import ANOMALY_FLOOR, DISCLAIMER, INSIGHTS_VERSION, MIN_YEARS, _finish, _history, _year_table, robust_score
from .query import Filters

NRT_SOURCE = {"MODIS": ("MODIS_NRT", "MODIS"), "VIIRS_SNPP": ("VIIRS_SNPP_NRT", "VIIRS"),
              "VIIRS_N20": ("VIIRS_NOAA20_NRT", "VIIRS"), "VIIRS_N21": ("VIIRS_NOAA21_NRT", "VIIRS")}
NOW_DAYS = 10
CACHE_SECONDS = 1800
_cache: dict[tuple, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _fetch_rows(source: str, bbox, start: date, end: date, client: httpx.Client | None = None) -> list[dict]:
    key = get_settings().firms_map_key
    if not key:
        raise firms.FirmsError("No FIRMS MAP_KEY is configured on the server, so near-real-time data cannot be fetched.")
    ck = (source, tuple(round(x, 5) for x in bbox), start, end)
    with _lock:
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    own = client is None
    client = client or httpx.Client(follow_redirects=True)
    rows: list[dict] = []
    try:
        for d, n in firms.split_windows(start, end):
            body = firms.fetch_window(client, key, source, bbox, d, n)
            rows += list(csv.DictReader(io.StringIO(body)))
    finally:
        if own:
            client.close()
    with _lock:
        _cache[ck] = (time.time(), rows)
    return rows


def now_vs_history(f: Filters, series: str, days: int = NOW_DAYS, client: httpx.Client | None = None, today: date | None = None) -> dict:
    if series not in NRT_SOURCE:
        raise ValueError("unknown series")
    if not (3 <= days <= 10):
        raise ValueError("days must be 3–10")
    geom = A.get_geometry(f.aoi)
    if geom is None:
        raise ValueError("Choose an area of interest first; the near-real-time view needs an AOI.")
    source, instrument = NRT_SOURCE[series]
    end = today or _utc_today()
    start = end - timedelta(days=days - 1)
    w, s, e, n = geom.bounds
    bbox = firms.validate_bbox((max(-180, w), max(-90, s), min(180, e), min(90, n)))
    raw = _fetch_rows(source, bbox, start, end, client)
    plats = set(p for p in f.platforms if N.PLATFORM_SERIES[p] == series)
    counts = {start + timedelta(days=k): 0 for k in range(days)}
    rejected = outside = filtered = 0
    lats, lons, obs = [], [], []
    for r in raw:
        try:
            o = N.normalize_row(r, instrument, "NRT")
        except Exception:
            rejected += 1
            continue
        lats.append(o.lat); lons.append(o.lon); obs.append(o)
    inside = shapely.contains_xy(geom, np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)) if obs else []
    boundary = shapely.intersects_xy(geom.boundary, np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)) if obs else []
    for o, ins, onb in zip(obs, inside, boundary):
        if not (ins or onb):
            outside += 1
            continue
        if o.platform not in plats:
            filtered += 1
            continue
        if instrument == "MODIS" and (o.conf_num is None or o.conf_num < f.modis_min_conf):
            filtered += 1
            continue
        if instrument == "VIIRS" and o.conf_cat not in f.viirs_conf:
            filtered += 1
            continue
        if o.daynight is not None and o.daynight not in f.daynight:
            filtered += 1
            continue
        if o.type_code is not None and str(o.type_code) not in f.types:
            filtered += 1
            continue
        if o.acq_date in counts:
            counts[o.acq_date] += 1
    # history for scoring (archive, same AOI/filters/series)
    hf = f.model_copy(update={"end": min(f.end, end)})
    h, dates, vals = _history(hf, series, "detections")
    years = _year_table(dates, vals)
    elig = sorted(y for y, r in years.items() if r["eligible"])
    by = dict(zip(dates, vals))
    out_days = []
    for d, x in counts.items():
        refs, used = [], 0
        for y in elig:
            if y >= d.year:
                continue
            try:
                anchor = d.replace(year=y)
            except ValueError:
                anchor = date(y, 2, 28)
            win = [by.get(anchor + timedelta(days=k)) for k in range(-15, 16)]
            known = [v for v in win if v is not None]
            if len(known) >= 0.8 * len(win):
                used += 1
                refs.extend(known)
        rec = {"date": d.isoformat(), "nrt_detections": x, "reference_years": used}
        if used >= MIN_YEARS:
            rec.update(_finish(robust_score(x, refs), ANOMALY_FLOOR["day"], x, refs), state="scored")
        else:
            rec.update(state="insufficient history", z=None, band=None)
        out_days.append(rec)
    total = sum(counts.values())
    scored = [r for r in out_days if r.get("z") is not None]
    week_refs = []
    for y in elig:
        if y >= end.year:
            continue
        try:
            a = start.replace(year=y); b = end.replace(year=y)
        except ValueError:
            continue
        win = [by.get(a + timedelta(days=k)) for k in range((b - a).days + 1)]
        if all(v is not None for v in win):
            week_refs.append({"year": y, "total": float(sum(win))})
    window = None
    if len(week_refs) >= MIN_YEARS:
        refs = [r["total"] for r in week_refs]
        window = _finish(robust_score(total, refs), ANOMALY_FLOOR["week"], total, refs)
        window["higher_than_years"] = sum(1 for v in refs if v < total)
        window["n_years"] = len(refs)
        window["sentence"] = (f"{total} NRT detections in the last {days} days, more than in {window['higher_than_years']} of {len(refs)} "
                              f"past years for the same dates (median {np.median(refs):g}).")
    return {"available": True, "series": series, "series_label": N.SERIES_LABEL[series], "source": source, "aoi": A.describe(f.aoi)["name"],
            "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days}, "days": out_days, "total": total,
            "window_score": window, "reference_windows": week_refs, "climate_now": climate.latest(),
            "counts": {"rows_fetched": len(raw), "rejected_rows": rejected, "outside_aoi": outside, "filtered_out": filtered},
            "method_version": INSIGHTS_VERSION, "disclaimer": DISCLAIMER,
            "notes": ["Near-real-time (NRT) data are provisional and are replaced by standard data later; counts can change.",
                      "NRT rows are not stored. The history uses the archive with the same AOI, filters and sensor series.",
                      "The FIRMS area files used here may not carry the 'type' column; when it is missing, static sources cannot be "
                      "removed from NRT counts, while the archive history uses the type filter.",
                      "The most recent day is usually incomplete until all overpasses are processed."]}
