"""FastAPI application: typed JSON API + static frontend."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import aoi as A
from . import analysis as AN
from . import cache, exports, firms, gibs, harmonize, ingest
from . import insights as INS
from . import live as LIVE
from . import query as Q
from .config import APP_VERSION, PROCESSING_VERSION, PROJECT_ROOT, get_settings
from .db import get_revision

app = FastAPI(title="PyroSync API", version=APP_VERSION,
              description="Local API for PyroSync — fire history, in context. Independent prototype; not an official NASA application.")
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(A.AOIError)
async def _aoi_err(_: Request, e: A.AOIError):
    return JSONResponse(status_code=422, content={"detail": str(e), "kind": "aoi"})


@app.exception_handler(ValueError)
async def _val_err(_: Request, e: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(e)})


def _csv(v: str | None) -> list[str] | None:
    if v is None:
        return None
    return [x for x in (s.strip() for s in v.split(",")) if x]


def filters(start: date, end: date, platforms: str | None = None, modis_min_conf: int = 30, viirs_conf: str | None = None,
            types: str | None = None, daynight: str | None = None, aoi: str = "none", grid: float = 0.1) -> Q.Filters:
    kw: dict = {"start": start, "end": end, "modis_min_conf": modis_min_conf, "aoi": aoi, "grid": grid}
    for name, v in (("platforms", platforms), ("viirs_conf", viirs_conf), ("types", types), ("daynight", daynight)):
        lst = _csv(v)
        if lst is not None:
            kw[name] = lst
    try:
        return Q.Filters(**kw)
    except ValidationError as e:
        raise HTTPException(422, detail="; ".join(f"{'.'.join(map(str, er['loc']))}: {er['msg']}" for er in e.errors())) from None


def F(request: Request) -> Q.Filters:
    p = request.query_params
    if "start" not in p or "end" not in p:
        raise HTTPException(422, detail="start and end (YYYY-MM-DD) are required")
    try:
        return filters(date.fromisoformat(p["start"]), date.fromisoformat(p["end"]), p.get("platforms"), int(p.get("modis_min_conf", 30)),
                       p.get("viirs_conf"), p.get("types"), p.get("daynight"), p.get("aoi", "none"), float(p.get("grid", 0.1)))
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None


def _bbox(p: str | None):
    if not p:
        return None
    try:
        w, s, e, n = (float(x) for x in p.split(","))
    except ValueError:
        raise HTTPException(422, detail="bbox must be west,south,east,north") from None
    return (max(-180, w), max(-90, s), min(180, e), min(90, n))


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    s = get_settings()
    return {"ok": True, "version": APP_VERSION, "processing_version": PROCESSING_VERSION, "dataset_revision": get_revision(),
            "firms_key_configured": bool(s.firms_map_key), "offline_mode": s.offline, "readonly": s.readonly, "cache": cache.stats,
            "demo_note": _demo_note() if s.readonly else None}


def _demo_note() -> str:
    """Describe what the read-only demo database contains (built from its own metadata, never hard-coded)."""
    from .db import cursor
    inv = Q.inventory()
    with cursor() as cur:
        row = cur.execute("SELECT value FROM dataset_meta WHERE key = 'demo_subset'").fetchone()
    sub = json.loads(row[0]) if row else {}
    rng = inv.get("date_range") or ["?", "?"]
    plats = ", ".join(sub.get("platforms") or inv.get("available_platforms") or [])
    where = f" for {sub['aoi']} only" if sub.get("aoi") else ""
    slim = " Per-record brightness, scan/track and source-file details are omitted to fit the hosting limit." if sub.get("slim") else ""
    return f"FIRMS data {rng[0]} to {rng[1]}{where} ({plats}).{slim}"


READONLY_MSG = ("This is a read-only online demo of PyroSync. Importing data and FIRMS refresh "
                "are available in the local version (run it on your own computer).")


def _guard_readonly() -> None:
    if get_settings().readonly:
        raise HTTPException(403, READONLY_MSG)


@app.get("/api/inventory")
def inventory():
    return Q.inventory()


@app.get("/api/regions")
def regions():
    return {"regions": A.list_regions()}


@app.get("/api/regions/{rid}.geojson")
def region_geojson(rid: str):
    return A.geojson_feature(f"region:{rid}")


class AOIIn(BaseModel):
    geojson: dict
    name: str | None = None


@app.post("/api/aoi")
def aoi_register(body: AOIIn):
    info = A.register_custom(body.geojson, (body.name or "Custom AOI")[:80])
    return {**info, "feature": A.geojson_feature(info["id"])}


@app.get("/api/aoi/{aoi_id}")
def aoi_get(aoi_id: str):
    return A.geojson_feature(aoi_id)


# ------------------------------------------------------------------ analysis
@app.get("/api/daily")
def daily(request: Request, fused: bool = False):
    """Per-sensor daily series. fused=true (1.5) adds the harmonized multi-sensor series 'FUSED' (detections only)."""
    f = F(request)
    out = Q.daily(f)
    if fused:
        from . import fusion
        fl = fusion.daily_like(f)
        out = {**out, "series": {**out["series"], **fl["series"]}, "series_labels": {**out["series_labels"], **fl["series_labels"]},
               "fused_validation": {"status": fl["validation_status"], "label": fl["validation_label"], "source": fl["coefficient_source"]}}
    return out


@app.get("/api/frame")
def frame(request: Request, date_: date = Query(alias="date"), mode: int = 1, bbox: str | None = None, limit: int = 30000):
    if mode not in (1, 7, 30):
        raise HTTPException(422, "mode must be 1, 7 or 30")
    return Q.frame_cells(F(request), date_, mode, _bbox(bbox), min(max(limit, 1), 100000))


@app.get("/api/observations")
def observations(request: Request, window_start: date, window_end: date, bbox: str | None = None, limit: int = 500, offset: int = 0,
                 include_filtered_out: bool = False):
    if (window_end - window_start).days > 400:
        raise HTTPException(422, "observation table windows are limited to 400 days; use the CSV export for more")
    return Q.points(F(request), window_start, window_end, _bbox(bbox), min(max(limit, 1), 10000), max(offset, 0), include_filtered_out)


@app.get("/api/history")
def history(request: Request):
    return Q.history(F(request))


Metric = Literal["cells", "detections", "frp_sum", "frp_max", "frp_mean"]


@app.get("/api/weeks")
def weeks(request: Request, series: str = "VIIRS_N20", metric: Metric = "cells"):
    return AN.iso_weeks(F(request), series, metric)


@app.get("/api/rankings")
def rankings(request: Request, series: str = "VIIRS_N20", metric: Metric = "cells", top: int = 10):
    return AN.rankings(F(request), series, metric, min(max(top, 1), 50))


@app.get("/api/compare")
def compare(request: Request, year: int, reference_year: int, series: str = "VIIRS_N20", metric: Metric = "cells"):
    return AN.year_compare(F(request), series, metric, year, reference_year)


@app.get("/api/baseline")
def baseline(request: Request, series: str = "VIIRS_N20", metric: Metric = "cells", window_days: int = 15, min_years: int = 5,
             min_reference_days: int = 100):
    cfg = {"window_days": window_days, "min_years": max(1, min_years), "min_reference_days": max(1, min_reference_days)}
    return AN.baseline(F(request), series, metric, cfg)


@app.get("/api/elevated")
def elevated(request: Request, series: str = "VIIRS_N20", metric: Metric = "cells", mode: Literal["fixed", "range_percentile", "baseline"] = "range_percentile",
             percentile: float = 90, threshold: float | None = None, min_days: int = 3, min_activity: float = 1):
    return AN.elevated(F(request), series, metric, mode, percentile, threshold, min_days, min_activity)


# ------------------------------------------------------------------ harmonization (v1.1, additive)
def _hcfg(request: Request) -> harmonize.HarmonizeConfig:
    p = request.query_params
    kw: dict = {}
    if p.get("modis_platforms"):
        kw["modis_platforms"] = _csv(p["modis_platforms"])
    for name in ("viirs_series", "metric", "unit_set"):
        if p.get(name):
            kw[name] = p[name]
    try:
        for name, typ in (("unit_grid", float), ("tolerance_min", int), ("evidence_radius_deg", float), ("test_fraction", float)):
            if p.get(name):
                kw[name] = typ(p[name])
        if p.get("split_date"):
            kw["split_date"] = date.fromisoformat(p["split_date"])
        return harmonize.HarmonizeConfig(**kw)
    except ValidationError as e:
        raise HTTPException(422, detail="; ".join(f"{'.'.join(map(str, er['loc']))}: {er['msg']}" for er in e.errors())) from None
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None


@app.get("/api/harmonization")
def harmonization(request: Request):
    return harmonize.harmonize(F(request), _hcfg(request))


# ------------------------------------------------------------------ calibration application (v1.2, additive, read-only)
def _ccore(request: Request):
    from . import calibration
    return calibration, calibration.core(F(request), _hcfg(request))


def _num(request: Request, name: str, typ, default):
    v = request.query_params.get(name)
    if v in (None, ""):
        return default
    try:
        return typ(v)
    except ValueError:
        raise HTTPException(422, detail=f"{name}: invalid value {v!r}") from None


@app.get("/api/harmonization/map")
def harmonization_map(request: Request, date_: date = Query(..., alias="date"), mode: int = 1):
    C, c = _ccore(request)
    try:
        out = C.map_window(c, date_, mode, request.query_params.get("scope", "domain"),
                           _num(request, "err_grid", float, max(0.5, c.cfg.unit_grid)), _num(request, "min_n", int, 20))
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None
    out["suggested_days"] = C.suggested_days(c)
    from . import aggregate
    return aggregate.augment_map(out, c.f, c.cfg)


@app.get("/api/harmonization/errors")
def harmonization_errors(request: Request):
    C, c = _ccore(request)
    try:
        return C.error_cells(c, _num(request, "err_grid", float, max(0.5, c.cfg.unit_grid)), _num(request, "min_n", int, 20))
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None


@app.get("/api/harmonization/series")
def harmonization_series(request: Request, agg: Literal["day", "month"] = "month", scope: Literal["all", "domain"] = "domain"):
    C, c = _ccore(request)
    return C.series(c, agg, scope)


# ------------------------------------------------------------------ day-level (aggregate) calibration (1.4, additive, read-only)
@app.get("/api/harmonization/aggregate")
def harmonization_aggregate(request: Request, events: bool = False):
    """Day-level ratio calibration with chronological, rolling-origin and bootstrap evaluation and the aggregate gate.
    events=true also builds the harmonization run to compare the event-level model's daily sums (slower)."""
    from . import aggregate
    f, cfg = F(request), _hcfg(request)
    c = _ccore(request)[1] if events else None
    return aggregate.report(f, cfg, c)


@app.get("/api/harmonization/aggregate/series")
def harmonization_aggregate_series(request: Request, agg: Literal["day", "month"] = "month",
                                   quantity: Literal["detections", "cells"] = "detections"):
    from . import aggregate
    return aggregate.series(F(request), _hcfg(request), agg, quantity)


@app.get("/api/harmonization/aggregate/regions")
def harmonization_aggregate_regions(request: Request):
    """Held-out regional check of the AOI's day-level ratio: Σ c·V / Σ MODIS per region cell (needs the run's events)."""
    from . import aggregate
    C, c = _ccore(request)
    err_grid = _num(request, "err_grid", float, max(0.5, c.cfg.unit_grid))
    min_days = _num(request, "min_days", int, 20)
    if min_days not in aggregate.REGION_MIN_DAYS:
        raise HTTPException(422, detail=f"min_days must be one of {aggregate.REGION_MIN_DAYS}")
    try:
        k = C._agg_factor(c, err_grid)
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None
    rep = aggregate.report(c.f, c.cfg)
    rows = aggregate.regional_ratio(c, k, min_days)
    return {"error_grid_deg": err_grid, "min_days": min_days, "min_days_choices": list(aggregate.REGION_MIN_DAYS),
            "error_grids": C.error_grids_for(c.cfg.unit_grid), "c": rep["quantities"]["detections"].get("c"), "split": rep["split"],
            "gate_status": rep["quantities"]["detections"].get("gate", {}).get("status"), "level": list(aggregate.LEVEL), "cells": rows,
            "summary": {"within": sum(1 for r in rows if r["status"] == "within"), "outside": sum(1 for r in rows if r["status"] == "outside"),
                        "too_few": sum(1 for r in rows if r["status"] == "too_few")},
            "definition": "Per region cell, over held-out days with a known coverage state for both sensors: the AOI's c times the region's VIIRS "
                          "detections, divided by its MODIS detections. 'within' = 0.8–1.25×; 'too few' = fewer active held-out days than the "
                          "minimum. The AOI-level gate does not make every region accurate; this view shows where it holds."}


@app.get("/api/export/harmonization.zip")
def export_harmonization(request: Request):
    f = F(request)
    cfg = _hcfg(request)
    return _dl(exports.harmonization_zip(f, cfg), f"pyrosync_harmonization_{f.start}_{f.end}.zip", "application/zip")


# ------------------------------------------------------------------ multi-sensor historical fusion (1.5, additive, read-only)
@app.get("/api/fusion")
def fusion_report(request: Request):
    """Fusion model for the AOI and filters over the whole record: pairwise ratios, eligibility, leave-reference-out validation and gate."""
    from . import fusion
    return fusion.report(F(request))


@app.get("/api/fusion/series")
def fusion_series(request: Request, agg: Literal["day", "month", "year"] = "month"):
    from . import fusion
    return fusion.series(F(request), agg)


@app.get("/api/fusion/map")
def fusion_map(request: Request, date_: date = Query(alias="date"), mode: int = 1, bbox: str | None = None, limit: int = 30000):
    from . import fusion
    if mode not in (1, 7, 30):
        raise HTTPException(422, "mode must be 1, 7 or 30")
    f = F(request)
    return fusion.frame_cells(f, date_, mode, f.grid, _bbox(bbox), min(max(limit, 1), 100000))


@app.get("/api/fusion/regions")
def fusion_regions(request: Request, grid_deg: float = 1.0, min_days: int = 20):
    from . import fusion
    if grid_deg not in (0.5, 1.0, 2.0):
        raise HTTPException(422, "grid_deg must be 0.5, 1 or 2")
    if min_days not in (5, 10, 20, 30, 50):
        raise HTTPException(422, "min_days must be one of 5, 10, 20, 30, 50")
    return fusion.regional(F(request), grid_deg, min_days)


@app.get("/api/export/fusion.zip")
def export_fusion(request: Request):
    f = F(request)
    return _dl(exports.fusion_zip(f), f"pyrosync_fusion_{f.start}_{f.end}.zip", "application/zip")


# ------------------------------------------------------------------ AOI Insights (1.3)
Series = Literal["MODIS", "VIIRS_SNPP", "VIIRS_N20", "VIIRS_N21", "FUSED"]
InsMetric = Literal["detections", "cells"]


@app.get("/api/insights/regime")
def insights_regime(request: Request, series: Series = "MODIS", metric: InsMetric = "detections"):
    return INS.regime(F(request), series, metric)


@app.get("/api/insights/anomaly")
def insights_anomaly(request: Request, series: Series = "MODIS", metric: InsMetric = "detections"):
    return INS.anomaly(F(request), series, metric)


@app.get("/api/insights/anomaly_cells")
def insights_anomaly_cells(request: Request, series: Series = "MODIS"):
    return INS.cell_anomaly(F(request), series)


@app.get("/api/insights/recurrence")
def insights_recurrence(request: Request, series: Series = "MODIS", chronic_share: float = 0.4):
    return INS.recurrence(F(request), series, chronic_share)


@app.get("/api/insights/critical")
def insights_critical(request: Request, series: Series = "MODIS", metric: InsMetric = "detections", percentile: float = 90,
                      min_days: int = 3, min_activity: float = 1, top: int = 20):
    return INS.critical(F(request), series, metric, percentile, min_days, min_activity, max(1, min(top, 100)))


@app.get("/api/insights/years")
def insights_years(request: Request, series: Series = "MODIS", metric: InsMetric = "detections"):
    return INS.years_report(F(request), series, metric)


@app.get("/api/insights/compare")
def insights_compare(request: Request, aois: str, series: Series = "MODIS", metric: InsMetric = "detections"):
    return INS.compare_aois(F(request), _csv(aois) or [], series, metric)


@app.get("/api/insights/now")
def insights_now(request: Request, series: Series = "VIIRS_SNPP", days: int = 10):
    if series == "FUSED":
        raise HTTPException(422, "The live 'now vs history' view needs one sensor's near-real-time feed; "
                                 "the harmonized series is historical only. Pick a single sensor series.")
    try:
        return LIVE.now_vs_history(F(request), series, days)
    except firms.FirmsError as e:
        return JSONResponse(status_code=503, content={"available": False, "detail": str(e)})


@app.get("/api/insights/climate")
def insights_climate():
    from . import climate
    return {"latest": climate.latest(), "phase_rules": climate.PHASE_RULES, "sources": climate.SOURCES,
            "years": [climate.season_phase(y) for y in range(2000, climate.latest()["oni"]["year"] + 1)]}


@app.get("/api/export/hotspots.{fmt}")
def export_hotspots(request: Request, fmt: Literal["csv", "geojson", "kml"], series: Series = "MODIS", top: int = 200):
    f = F(request)
    rows = INS.hotspot_rows(f, series, max(1, min(top, 2000)))
    name = f"pyrosync_hotspots_{series}_{f.end}"
    content, media = exports.hotspots(rows, fmt, f, series)
    return _dl(content, f"{name}.{fmt}", media)


@app.get("/api/export/insights.zip")
def export_insights(request: Request, series: Series = "MODIS", metric: InsMetric = "detections"):
    f = F(request)
    return _dl(exports.insights_zip(f, series, metric), f"pyrosync_insights_{series}_{f.end}.zip", "application/zip")


# ------------------------------------------------------------------ exports
def _dl(content: bytes | str, filename: str, media: str) -> Response:
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/daily.zip")
def export_daily(request: Request, series: str | None = None, metric: str | None = None):
    f = F(request)
    return _dl(exports.daily_zip(f, {"primary_series": series, "metric": metric}), f"pyrosync_daily_{f.start}_{f.end}.zip", "application/zip")


@app.get("/api/export/observations.zip")
def export_obs(request: Request, window_start: date, window_end: date):
    f = F(request)
    return _dl(exports.observations_zip(f, window_start, window_end), f"pyrosync_observations_{window_start}_{window_end}.zip", "application/zip")


@app.get("/api/export/aoi.geojson")
def export_aoi(aoi: str):
    return _dl(json.dumps(exports.aoi_geojson(aoi)), "pyrosync_aoi.geojson", "application/geo+json")


@app.get("/api/export/grid.geojson")
def export_grid(request: Request, date_: date = Query(alias="date"), mode: int = 1):
    f = F(request)
    return _dl(json.dumps(exports.grid_geojson(f, date_, mode)), f"pyrosync_grid_{f.grid}deg_{date_}_{mode}d.geojson", "application/geo+json")


# ------------------------------------------------------------------ imagery
@app.get("/api/imagery/layers")
def imagery_layers(refresh: bool = False):
    return gibs.layer_info(force=refresh)


@app.get("/api/imagery/check")
def imagery_check(layer: str, date_: date = Query(alias="date")):
    info = gibs.layer_info()
    l = next((x for x in info["layers"] if x["id"] == layer), None)
    if not l:
        raise HTTPException(404, "unknown imagery layer")
    ok = gibs.available(l["ranges"], date_)
    near = None if ok else gibs.nearest(l["ranges"], date_)
    return {"layer": layer, "date": date_.isoformat(), "available": ok, "nearest_available": near.isoformat() if near else None,
            "domain_source": info["domain_source"], "domain_checked": info["domain_checked"]}


# ------------------------------------------------------------------ imports
UPLOADS: dict[str, dict] = {}
JOBS: dict[str, dict] = {}
_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


@app.post("/api/uploads")
async def upload(files: list[UploadFile] = File(...)):
    _guard_readonly()
    s = get_settings()
    uid = uuid.uuid4().hex[:12]
    dest = s.data_dir / "uploads" / uid
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    total = 0
    try:
        for uf in files:
            name = _SAFE.sub("_", Path(uf.filename or "upload").name)[:120] or "upload"
            if not name.lower().endswith((".csv", ".zip")):
                raise HTTPException(422, f"'{name}': only .csv and .zip files are accepted")
            p = dest / name
            with open(p, "wb") as out:
                while chunk := await uf.read(1024 * 1024):
                    total += len(chunk)
                    if total > s.max_upload_bytes:
                        raise HTTPException(413, f"Upload exceeds {s.max_upload_bytes // (1024 * 1024)} MB; use the CLI import for large datasets")
                    out.write(chunk)
            saved.append({"name": name, "bytes": p.stat().st_size})
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    UPLOADS[uid] = {"dir": dest, "files": saved, "created": time.time()}
    return {"upload_id": uid, "files": saved}


class ImportIn(BaseModel):
    upload_id: str
    dry_run: bool = True
    stream_override: Literal["SP", "NRT", "URT", "RT"] | None = None


@app.post("/api/imports")
def start_import(body: ImportIn):
    _guard_readonly()
    up = UPLOADS.get(body.upload_id)
    if not up:
        raise HTTPException(404, "upload not found (it may already have been committed); upload the files again")
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "status": "running", "dry_run": body.dry_run, "progress": {}, "report": None, "error": None}
    JOBS[jid] = job

    def work():
        try:
            paths = sorted(up["dir"].iterdir())
            opts = ingest.ImportOptions(origin="upload", label=", ".join(f["name"] for f in up["files"])[:200], dry_run=body.dry_run,
                                        stream_override=body.stream_override, raw_paths=paths, progress=lambda ev: job.__setitem__("progress", ev))
            job["report"] = ingest.import_paths(paths, opts)
            job["status"] = "done"
            if not body.dry_run:
                shutil.rmtree(up["dir"], ignore_errors=True)
                UPLOADS.pop(body.upload_id, None)
        except ingest.ImportError_ as e:
            job["status"] = "error"; job["error"] = str(e)
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"; job["error"] = f"Import failed and was rolled back; previous data are unchanged. ({type(e).__name__}: {e})"

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": jid}


@app.get("/api/imports/jobs/{jid}")
def import_job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.get("/api/imports")
def import_history():
    return {"batches": ingest.list_batches(), "dataset_revision": get_revision()}


@app.get("/api/imports/{batch_id}/report.json")
def import_report(batch_id: str):
    if not re.fullmatch(r"[0-9TZ]+-[0-9a-f]{8}", batch_id):
        raise HTTPException(404)
    p = get_settings().reports_dir / f"{batch_id}.json"
    if not p.is_file():
        raise HTTPException(404, "report not found")
    return FileResponse(p, media_type="application/json", filename=f"pyrosync_import_{batch_id}.json")


@app.get("/api/imports/{batch_id}/rejections.csv")
def import_rejections(batch_id: str):
    if not re.fullmatch(r"[0-9TZ]+-[0-9a-f]{8}", batch_id):
        raise HTTPException(404)
    p = get_settings().reports_dir / f"{batch_id}_rejections.csv"
    if not p.is_file():
        raise HTTPException(404, "report not found")
    return FileResponse(p, media_type="text/csv", filename=f"pyrosync_rejections_{batch_id}.csv")


# ------------------------------------------------------------------ FIRMS
class FirmsIn(BaseModel):
    source: str
    west: float
    south: float
    east: float
    north: float
    start: date
    end: date


@app.get("/api/firms/status")
def firms_status():
    s = get_settings()
    return {"key_configured": bool(s.firms_map_key), "sources": list(firms.SOURCES), "max_day_range": firms.MAX_DAY_RANGE,
            "verified_live": False,
            "note": "Live retrieval has not been verified with credentials in this build. Requests use the documented Area API "
                    "(west,south,east,north; DAY_RANGE 1–5)."}


@app.get("/api/firms/availability")
def firms_availability():
    return firms.availability()


@app.post("/api/firms/jobs")
def firms_start(body: FirmsIn):
    _guard_readonly()
    try:
        firms.validate_bbox((body.west, body.south, body.east, body.north))
        job = firms.start_job(body.source, (body.west, body.south, body.east, body.north), body.start, body.end)
    except firms.FirmsError as e:
        raise HTTPException(422, str(e)) from None
    return job.public()


@app.get("/api/firms/jobs/{jid}")
def firms_job(jid: str):
    j = firms.JOBS.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j.public()


@app.post("/api/firms/jobs/{jid}/cancel")
def firms_cancel(jid: str):
    j = firms.JOBS.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    j.cancel.set()
    return j.public()


# ------------------------------------------------------------------ static frontend
DIST = PROJECT_ROOT / "frontend" / "dist"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST.resolve() in target.parents:
        return FileResponse(target)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Frontend not built. Run the start script (it builds the frontend) or `npm run build` in frontend/."}, status_code=503)
