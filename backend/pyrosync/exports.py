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


def harmonization_zip(f: Filters, cfg) -> bytes:
    """Harmonization validation package: report (JSON + Markdown), per-unit CSV and manifest (added in v1.1)."""
    from . import harmonize as H
    res = H.harmonize(f, cfg, include_units=True)
    body = {k: v for k, v in res.items() if k != "units"}
    ff = H._sensor_filters(f, cfg)
    man = manifest(ff, "harmonization", {"harmonization_config": cfg.key(), "method_version": res["method_version"],
                                         "row_count": len(res.get("units", [])),
                                         "columns_note": "units.csv lists every comparison unit used by the model; set = train/test (chronological). "
                                                         "M = MODIS-scale measurement, V = VIIRS measurement, M_hat = calibrated prediction."})
    return _zip({"manifest.json": json.dumps(man, indent=2, default=str),
                 "harmonization_report.json": json.dumps(body, indent=2, default=str),
                 "HARMONIZATION_REPORT.md": H.report_markdown(res),
                 "units.csv": H.units_csv(res)})


# ------------------------------------------------------------------ AOI Insights exports (1.3)
HOTSPOT_FIELDS = ["rank", "lat", "lon", "fire_years", "years_in_record", "share", "longest_run", "first_year", "last_year", "detections", "chronic"]


def hotspots(rows: list[dict], fmt: str, f: Filters, series: str) -> tuple[str, str]:
    """Recurrent cells (cell centres) as CSV, GeoJSON or KML. A cell is a grid square, not an exact fire location."""
    from xml.sax.saxutils import escape
    note = (f"PyroSync {APP_VERSION} recurrent fire cells, {N.SERIES_LABEL[series]}, history to {f.end.isoformat()}, grid {f.grid} deg. "
            "Points are grid-cell centres, not exact fire locations. Historical description, not a forecast or warning.")
    if fmt == "csv":
        buf = io.StringIO()
        buf.write(f"# {note}\n")
        w = csv.DictWriter(buf, fieldnames=HOTSPOT_FIELDS)
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue(), "text/csv"
    if fmt == "geojson":
        fc = {"type": "FeatureCollection", "properties": {"note": note, "series": series, "grid_deg": f.grid, "attribution": ATTRIBUTION},
              "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                            "properties": {k: r[k] for k in HOTSPOT_FIELDS if k not in ("lat", "lon")}} for r in rows]}
        return json.dumps(fc), "application/geo+json"
    if fmt == "kml":
        pm = []
        for r in rows:
            desc = (f"Fire in {r['fire_years']} of {r['years_in_record']} complete years; last {r['last_year']}; "
                    f"longest run {r['longest_run']} years; {r['detections']} detections.")
            pm.append(f"<Placemark><name>#{r['rank']}</name><description>{escape(desc)}</description>"
                      f"<Point><coordinates>{r['lon']},{r['lat']},0</coordinates></Point></Placemark>")
        kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
               f"<name>PyroSync recurrent fire cells</name><description>{escape(note)}</description>{''.join(pm)}</Document></kml>")
        return kml, "application/vnd.google-earth.kml+xml"
    raise ValueError("format must be csv, geojson or kml")


def insights_zip(f: Filters, series: str, metric: str) -> bytes:
    from . import insights as INS
    reg = INS.regime(f, series, metric)
    cri = INS.critical(f, series, metric, top=100)
    yrs = INS.years_report(f, series, metric)
    rec = INS.recurrence(f, series)
    files: dict[str, str | bytes] = {}
    files["manifest.json"] = json.dumps(manifest(f, "aoi_insights", {"series": series, "metric": metric,
                                                                      "method_version": INS.INSIGHTS_VERSION,
                                                                      "reproduce": f"python -m pyrosync.cli insights --aoi {f.aoi} --series {series} "
                                                                                   f"--metric {metric} --as-of {f.end.isoformat()} --out DIR"}), indent=2)
    for name, obj in (("regime.json", reg), ("critical_periods.json", cri), ("years.json", yrs), ("recurrence.json", rec)):
        files[name] = json.dumps(obj, indent=1, default=str)
    if reg.get("available"):
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["week", "label", "n_years", "median", "p10", "p90", "focus_year_value"])
        for x, fv in zip(reg["weeks"], reg["focus_weeks"]):
            w.writerow([x["week"], x["label"], x["n_years"], x["median"], x["p10"], x["p90"], fv])
        files["weekly_climatology.csv"] = buf.getvalue()
    buf = io.StringIO(); w = csv.writer(buf)
    cols = ["year", "eligible", "known_share", "total", "rank", "vs_median_of_other_years", "peak_season_total", "critical_days", "enso", "oni", "iod", "dmi"]
    w.writerow(cols)
    for r in yrs["years"]:
        w.writerow([r.get(c) for c in cols])
    files["years.csv"] = buf.getvalue()
    if cri.get("available"):
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["rank", "start", "end", "duration_days", "peak", "peak_date", "total", "excess"])
        for p in cri["periods"]:
            w.writerow([p["rank"], p["start"], p["end"], p["duration_days"], p["peak"], p["peak_date"], p["total"], p["excess"]])
        files["critical_periods.csv"] = buf.getvalue()
    files["README.txt"] = ("PyroSync AOI Insights package. Historical description of satellite fire detections; not a forecast, "
                           "not a fire-danger rating and not an official warning. Definitions are in each JSON file and in docs/METHODOLOGY.md §17.\n")
    return _zip(files)
