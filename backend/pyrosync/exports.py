"""Genuine exports with reproducibility manifests. Uses the same query layer as the UI."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime, timezone

from shapely.geometry import mapping

from . import aoi as A
from . import normalize as N
from .config import APP_VERSION, PROCESSING_VERSION
from .db import cursor, get_revision
from .query import GRID_DOC, DAY_DOC, METRICS, POINT_FIELDS, Filters, daily, filter_disclosure, filtered_sql, frame_cells, inventory

ATTRIBUTION = "Independent hackathon prototype using NASA FIRMS data and, where enabled, NASA GIBS imagery. Not an official NASA application."


def manifest(f: Filters, kind: str, extra: dict | None = None) -> dict:
    inv = inventory()
    aoi_geom = None
    if f.aoi != "none":
        aoi_geom = mapping(A.get_geometry(f.aoi))
    return {
        "generator": f"PyroSync {APP_VERSION}", "attribution": ATTRIBUTION, "export_kind": kind,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_revision": get_revision(), "processing_version": PROCESSING_VERSION,
        "aoi": {**A.describe(f.aoi), "geometry": aoi_geom, "boundary_rule": "Points on the AOI boundary are included."},
        "time": {"start": f.start.isoformat(), "end": f.end.isoformat(), "timezone": "UTC", "day_definition": DAY_DOC},
        "filters": f.key(), "filter_disclosure": filter_disclosure(f),
        "grid": {"size_deg": f.grid, **GRID_DOC},
        "metric_definitions": METRICS,
        "source_products": [p for p in inv["products"] if p["platform"] in f.platforms],
        **(extra or {}),
    }


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def daily_csv(f: Filters) -> str:
    d = daily(f)
    keys = list(d["series"].keys())
    cols = ["date_utc"]
    for s in keys:
        if s == "UNION":
            cols += ["union_cells_any_selected_sensor", "union_status"]
        else:
            cols += [f"{s}_detections", f"{s}_cells", f"{s}_frp_sum_mw", f"{s}_frp_mean_mw", f"{s}_frp_max_mw", f"{s}_day", f"{s}_night",
                     f"{s}_status"]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    for i, dt in enumerate(d["dates"]):
        row = [dt]
        for s in keys:
            x = d["series"][s]
            if s == "UNION":
                row += [x["cells"][i], x["status"][i]]
            else:
                row += [x["detections"][i], x["cells"][i], x["frp_sum"][i], x["frp_mean"][i], x["frp_max"][i], x["day"][i], x["night"][i], x["status"][i]]
        w.writerow(row)
    return out.getvalue()


def daily_zip(f: Filters, analysis: dict | None = None) -> bytes:
    csv_text = daily_csv(f)
    m = manifest(f, "daily-summary", {"analysis_settings": analysis or {}, "columns_note":
             "*_cells = distinct grid cells with ≥1 detection that UTC day for that sensor; union_cells_any_selected_sensor counts a cell once "
             "even if several sensors detected it. *_status: detections | zero_reported | unknown | sensor_unavailable | outside_range."})
    return _zip({"daily_summary.csv": csv_text, "manifest.json": json.dumps(m, indent=2, default=str)})


def observations_csv(f: Filters, start: date, end: date) -> tuple[str, int]:
    sql, params = filtered_sql(f, start, end)
    cols = POINT_FIELDS + ["acq_ts"]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([c if c != "acq_ts" else "acq_timestamp_utc" for c in cols])
    n = 0
    with cursor() as cur:
        res = cur.execute(f"SELECT {', '.join('o.' + c for c in cols)} FROM ({sql}) o ORDER BY o.acq_ts, o.rid", params)
        while True:
            chunk = res.fetchmany(50000)
            if not chunk:
                break
            for r in chunk:
                r = list(r)
                r[-1] = r[-1].strftime("%Y-%m-%dT%H:%M:00Z")
                w.writerow(r)
                n += 1
    return out.getvalue(), n


def observations_zip(f: Filters, start: date, end: date) -> bytes:
    text, n = observations_csv(f, start, end)
    m = manifest(f, "filtered-observations", {"window": {"start": start.isoformat(), "end": end.isoformat()}, "row_count": n,
                 "columns_note": "acq_hhmm is zero-padded UTC HHMM. modis_* and viirs_* thermal fields are sensor-specific and not interchangeable. "
                                 "conf_raw is the original confidence (MODIS 0–100 numeric; VIIRS l/n/h)."})
    return _zip({"observations.csv": text, "manifest.json": json.dumps(m, indent=2, default=str)})


def aoi_geojson(aoi_id: str) -> dict:
    feat = A.geojson_feature(aoi_id)
    return {"type": "FeatureCollection", "features": [feat],
            "pyrosync_metadata": {"exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "crs": "WGS84 lon/lat (RFC 7946)",
                                  "attribution": ATTRIBUTION}}


def grid_geojson(f: Filters, day: date, mode: int) -> dict:
    fr = frame_cells(f, day, mode, None, limit=10_000_000)
    g = f.grid
    feats = []
    for c in fr["cells"]:
        w = round(c["ci"] * g - 180, 6); s = round(c["cj"] * g - 90, 6)
        e = round(w + g, 6); n = round(s + g, 6)
        props = {"cell_col": c["ci"], "cell_row": c["cj"], "west": w, "south": s, "sensors_detecting": c["sensors_detecting"],
                 **{f"{k}_detections": v for k, v in c["by_series"].items()}, "frp_max_mw": c["frp_max"], "frp_sum_mw": c["frp_sum"],
                 "days_with_detections": c["days"], "first_date": c["first"], "last_date": c["last"]}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}})
    m = manifest(f, "aggregated-grid", {"frame": fr["frame"], "cells_total": fr["cells_total"],
                 "geometry_note": "Each feature is a grid cell polygon (cell extent), not a burned-area polygon.",
                 "properties_note": "<SERIES>_detections are raw detection counts per sensor in the frame window; they are deliberately not summed across "
                                    "MODIS and VIIRS. sensors_detecting = number of selected sensors with ≥1 detection in the cell."})
    m["aoi"].pop("geometry", None)
    return {"type": "FeatureCollection", "features": feats, "pyrosync_metadata": m}
