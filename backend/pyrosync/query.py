"""Shared filter model and the single query layer behind maps, charts, tables and exports."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import aoi as A
from . import cache
from . import normalize as N
from .config import PROCESSING_VERSION
from .db import cursor, get_revision

GRID_R = {0.1: 10000, 0.05: 5000, 0.01: 1000}  # cell size in 1e-5 degree units
TYPE_VALUES = ["0", "1", "2", "3", "unknown"]
ALL_PLATFORMS = ["Terra", "Aqua", "N20", "N21", "SNPP"]

GRID_DOC = {
    "crs": "WGS84 geographic longitude/latitude (EPSG:4326)",
    "origin": "(-180°, -90°): column 0 starts at longitude -180, row 0 starts at latitude -90",
    "cell_index": "col = floor((lon_e5 + 18,000,000) / R), row = floor((lat_e5 + 9,000,000) / R), "
                  "where lon_e5/lat_e5 are coordinates quantized to integer 1e-5 degrees and R = cell size × 100,000",
    "boundary": "Cells are half-open [west, east) × [south, north); a point exactly on a shared edge belongs to the cell to its east/north. "
                "Longitude 180 and latitude 90 are assigned to the last column/row.",
    "equal_area": False,
    "note": "Degree cells are not equal-area: a 0.1° cell is about 11.1 km tall everywhere but its width shrinks with cos(latitude).",
}
DAY_DOC = "Daily bins use UTC calendar days: observations with acquisition timestamps in [D 00:00 UTC, D+1 00:00 UTC)."


class Filters(BaseModel):
    start: date
    end: date
    platforms: list[str] = Field(default_factory=lambda: list(ALL_PLATFORMS))
    modis_min_conf: int = Field(30, ge=0, le=100)
    viirs_conf: list[Literal["low", "nominal", "high"]] = Field(default_factory=lambda: ["nominal", "high"])
    types: list[str] = Field(default_factory=lambda: ["0", "unknown"])  # 1.3: NRT rows have no type column; see METHODOLOGY §17
    daynight: list[Literal["D", "N"]] = Field(default_factory=lambda: ["D", "N"])
    aoi: str = "none"
    grid: float = 0.1

    @field_validator("platforms")
    @classmethod
    def _plats(cls, v: list[str]) -> list[str]:
        bad = [p for p in v if p not in ALL_PLATFORMS]
        if bad:
            raise ValueError(f"unknown platforms {bad}; expected {ALL_PLATFORMS}")
        return sorted(set(v), key=ALL_PLATFORMS.index)

    @field_validator("types")
    @classmethod
    def _types(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in TYPE_VALUES]
        if bad:
            raise ValueError(f"unknown type filter values {bad}; expected {TYPE_VALUES}")
        return sorted(set(v), key=TYPE_VALUES.index)

    @field_validator("grid")
    @classmethod
    def _grid(cls, v: float) -> float:
        for g in GRID_R:
            if abs(v - g) < 1e-9:
                return g
        raise ValueError("grid must be one of 0.1, 0.05, 0.01")

    @model_validator(mode="after")
    def _range(self) -> "Filters":
        if self.end < self.start:
            raise ValueError("end date is before start date")
        if (self.end - self.start).days > 366 * 40:
            raise ValueError("date range too long")
        return self

    def key(self) -> dict:
        return self.model_dump(mode="json")

    @property
    def series(self) -> list[str]:
        out = []
        for s in N.SERIES:
            if any(N.PLATFORM_SERIES[p] == s for p in self.platforms):
                out.append(s)
        return out


def cell_sql(grid: float, alias: str = "o") -> tuple[str, str, str]:
    r = GRID_R[grid]
    ncols = 36_000_000 // r
    nrows = 18_000_000 // r
    ci = f"least(({alias}.lon_e5::BIGINT + 18000000) // {r}, {ncols - 1})"
    cj = f"least(({alias}.lat_e5::BIGINT + 9000000) // {r}, {nrows - 1})"
    return ci, cj, f"(({cj}) * {ncols} + ({ci}))"


def filtered_sql(f: Filters, start: date | None = None, end: date | None = None, *, apply_quality: bool = True,
                 extra_where: str = "", extra_params: list | None = None) -> tuple[str, list]:
    """SQL for filtered observations (alias o). AOI filtering happens BEFORE any aggregation."""
    params: list = []
    joins = ""
    if f.aoi and f.aoi != "none":
        A.ensure_members(f.aoi)
        joins = " JOIN aoi_members m ON m.rid = o.rid AND m.aoi_id = ?"
        params.append(f.aoi)
    where = ["NOT o.superseded", "o.acq_date BETWEEN ? AND ?"]
    params += [start or f.start, end or f.end]
    if not f.platforms:
        where.append("FALSE")
    else:
        where.append("o.platform IN (" + ",".join("?" * len(f.platforms)) + ")")
        params += f.platforms
    if apply_quality:
        where.append("(o.instrument <> 'MODIS' OR o.conf_num >= ?)")
        params.append(f.modis_min_conf)
        if f.viirs_conf:
            where.append("(o.instrument <> 'VIIRS' OR o.conf_cat IN (" + ",".join("?" * len(f.viirs_conf)) + "))")
            params += list(f.viirs_conf)
        else:
            where.append("o.instrument <> 'VIIRS'")
        codes = [int(t) for t in f.types if t != "unknown"]
        tparts = []
        if codes:
            tparts.append("o.type_code IN (" + ",".join("?" * len(codes)) + ")")
            params += codes
        if "unknown" in f.types:
            tparts.append("(o.type_code IS NULL OR o.type_code NOT IN (0,1,2,3))")
        where.append("(" + (" OR ".join(tparts) if tparts else "FALSE") + ")")
        where.append("(o.daynight IS NULL OR o.daynight IN (" + ",".join("?" * len(f.daynight)) + "))" if f.daynight else "FALSE")
        params += list(f.daynight)
    if extra_where:
        where.append(extra_where)
        params += extra_params or []
    return f"SELECT o.* FROM observations o{joins} WHERE " + " AND ".join(where), params


def filter_disclosure(f: Filters) -> dict:
    type_names = {"0": "presumed vegetation fire", "1": "active volcano", "2": "other static land source", "3": "offshore", "unknown": "unknown/missing type"}
    excluded = [type_names[t] for t in TYPE_VALUES if t not in f.types]
    return {
        "aoi": A.describe(f.aoi)["name"],
        "range_utc": f"{f.start.isoformat()} 00:00 – {f.end.isoformat()} 23:59 UTC (inclusive days)",
        "platforms": [N.PLATFORM_LABEL[p] for p in f.platforms],
        "modis_quality": f"MODIS confidence ≥ {f.modis_min_conf} (numeric 0–100)",
        "viirs_quality": "VIIRS confidence in {" + ", ".join(f.viirs_conf) + "} (categorical)" if f.viirs_conf else "all VIIRS excluded",
        "types_included": [type_names[t] for t in f.types],
        "types_excluded": excluded,
        "daynight": f.daynight,
        "grid": f"{f.grid}° WGS84 cells",
        "note": "Quality filters are a project filter choice; they do not make MODIS and VIIRS detection performance equivalent.",
    }


def envelope(f: Filters, metric_definition: str | dict, warnings: list[str] | None = None, **extra) -> dict:
    return {"dataset_revision": get_revision(), "processing_version": PROCESSING_VERSION, "effective_filters": f.key(),
            "filter_disclosure": filter_disclosure(f), "metric_definition": metric_definition,
            "warnings": (warnings or []) + standing_warnings(f), **extra}


def standing_warnings(f: Filters) -> list[str]:
    w = []
    if any(p in f.platforms for p in ("N20", "N21", "SNPP")) and "0" in f.types:
        with cursor() as cur:
            old = cur.execute("SELECT count(*) FROM observations WHERE instrument = 'VIIRS' AND version IN ('1','2','1.0','2.0','2.0NRT','1.0NRT','2NRT') LIMIT 1").fetchone()[0]
        if old:
            w.append("VIIRS 375 m collection versions 1–2 contain a documented type-attribution issue (some 'other static land source' "
                     "detections labeled type 0, corrected in version 3). Static industrial sources may remain in the vegetation-fire class.")
    return w


# ------------------------------------------------------------------ inventory & coverage
def inventory() -> dict:
    with cursor() as cur:
        rev = get_revision(cur)

        def compute():
            q = cur.execute("""SELECT series, platform, source_product, stream, version, instrument, count(*) n,
                    count(*) FILTER (WHERE superseded) superseded_n, min(acq_date), max(acq_date)
                FROM observations GROUP BY ALL ORDER BY ALL""").fetchall()
            rng = cur.execute("""SELECT min(d), max(d) FROM (SELECT min(acq_date) d FROM observations UNION ALL SELECT max(acq_date) FROM observations
                UNION ALL SELECT min(start_date) FROM import_intervals UNION ALL SELECT max(end_date) FROM import_intervals)""").fetchone()
            ext = cur.execute("SELECT min(lon), min(lat), max(lon), max(lat), count(*), count(*) FILTER (WHERE superseded) FROM observations").fetchone()
            types = cur.execute("SELECT instrument, type_code, count(*) FROM observations GROUP BY ALL ORDER BY ALL").fetchall()
            conf = cur.execute("SELECT instrument, conf_cat, count(*) FROM observations GROUP BY ALL ORDER BY ALL").fetchall()
            ivs = cur.execute("SELECT series, origin, count(*), min(start_date), max(end_date) FROM import_intervals GROUP BY ALL ORDER BY ALL").fetchall()
            batches = cur.execute("SELECT count(*) FROM import_batches").fetchone()[0]
            return {
                "dataset_revision": rev, "processing_version": PROCESSING_VERSION,
                "observations_total": ext[4], "observations_superseded": ext[5],
                "date_range": [rng[0].isoformat(), rng[1].isoformat()] if rng[0] else None,
                "extent": {"west": ext[0], "south": ext[1], "east": ext[2], "north": ext[3]} if ext[4] else None,
                "products": [{"series": r[0], "series_label": N.SERIES_LABEL[r[0]], "platform": r[1], "platform_label": N.PLATFORM_LABEL[r[1]],
                              "source_product": r[2], "stream": r[3], "version": r[4], "instrument": r[5], "rows": r[6], "superseded": r[7],
                              "first_date": r[8].isoformat(), "last_date": r[9].isoformat()} for r in q],
                "type_counts": [{"instrument": r[0], "type_code": r[1], "label": N.TYPE_LABEL.get(r[1], "unknown") if r[1] is not None else "missing", "rows": r[2]} for r in types],
                "confidence_counts": [{"instrument": r[0], "category": r[1], "rows": r[2]} for r in conf],
                "intervals": [{"series": r[0], "origin": r[1], "count": r[2], "first": r[3].isoformat(), "last": r[4].isoformat()} for r in ivs],
                "available_platforms": sorted({r[1] for r in q}, key=ALL_PLATFORMS.index),
                "available_series": sorted({r[0] for r in q}, key=N.SERIES.index),
                "import_batches": batches,
                "grid": GRID_DOC, "day_definition": DAY_DOC,
            }
        return cache.get_or_compute(cache.make_key("inventory", rev, {}), compute)


def coverage_context(f: Filters) -> dict:
    """Interval evidence per series used to classify days without detections."""
    inv = inventory()
    with cursor() as cur:
        ivs = cur.execute("SELECT series, start_date, end_date, origin, west, south, east, north FROM import_intervals").fetchall()
        present = cur.execute("SELECT DISTINCT series FROM observations UNION SELECT DISTINCT series FROM import_intervals").fetchall()
    gaps = _global_gap_days()
    aoi_bbox = A.describe(f.aoi).get("bbox")
    by_series: dict[str, list] = {}
    for s, a, b, origin, w, so, e, n in ivs:
        if w is not None and aoi_bbox is not None:
            if not (w <= aoi_bbox[0] and so <= aoi_bbox[1] and e >= aoi_bbox[2] and n >= aoi_bbox[3]):
                continue  # request extent known and does not contain the AOI
        by_series.setdefault(s, []).append((a, b, origin, w is not None))
    rng = inv["date_range"]
    return {"intervals": by_series, "present": {r[0] for r in present}, "gaps": gaps,
            "range": (date.fromisoformat(rng[0]), date.fromisoformat(rng[1])) if rng else None}


GAP_MIN_MEDIAN_ROWS = 20


def _global_gap_days() -> dict[str, set]:
    """Days on which a series has NO records anywhere in the import although its typical day has many.

    "Typical" = median rows/day over the days declared by the same import batch (zeros included).

    Such whole-extent zeros are far more likely to be acquisition/processing gaps than an absence of
    fire, so they are classified as unknown coverage instead of 'zero reported'.
    """
    rev = get_revision()

    def compute():
        with cursor() as cur:
            # A spatial subset (the online demo) cannot see "no records anywhere"; its builder stores the gap days
            # computed on the full database, which are used instead (added in v1.1, absent in normal databases).
            ov = cur.execute("SELECT value FROM dataset_meta WHERE key = 'gap_days'").fetchone()
            if ov:
                import json
                return {s_: {date.fromisoformat(d) for d in ds} for s_, ds in json.loads(ov[0]).items()}
            rows = cur.execute("SELECT series, acq_date, count(*) FROM observations WHERE NOT superseded GROUP BY ALL").fetchall()
            ivs = cur.execute("SELECT DISTINCT batch_id, series, start_date, end_date FROM import_intervals").fetchall()
        per: dict[str, dict] = {}
        for s_, d, n in rows:
            per.setdefault(s_, {})[d] = n
        # Group declared days by the import batch that declared them: the "typical day" is judged
        # within the same delivery (a large regional download vs. a small AOI request), not globally.
        groups: dict[tuple, set] = {}
        for b, s_, a, e in ivs:
            g = groups.setdefault((b, s_), set())
            d = a
            while d <= e:
                g.add(d)
                d += timedelta(days=1)
        out: dict[str, set] = {}
        for (_b, s_), days in groups.items():
            counts = per.get(s_, {})
            vals = sorted(counts.get(d, 0) for d in days)
            if not vals or vals[len(vals) // 2] < GAP_MIN_MEDIAN_ROWS:
                continue
            for d in days:
                if d not in counts:
                    out.setdefault(s_, set()).add(d)
        return out
    return cache.get_or_compute(cache.make_key("gapdays", rev, {}), compute)


def day_status(ctx: dict, series: str, d: date, has_detections: bool) -> tuple[str, str | None]:
    if ctx["range"] is None or d < ctx["range"][0] or d > ctx["range"][1]:
        return "outside_range", None
    if series not in ctx["present"]:
        return "sensor_unavailable", None
    if has_detections:
        return "detections", None
    if d in ctx.get("gaps", {}).get(series, set()):
        return "unknown", "no records anywhere in the import for this sensor on this day (possible acquisition/processing gap)"
    origins = [o for (a, b, o, _bb) in ctx["intervals"].get(series, []) if a <= d <= b]
    if origins:
        return "zero_reported", sorted(set(origins))[0]
    return "unknown", None


STATUS_DOC = {
    "detections": "One or more detections pass the current filters.",
    "zero_reported": "No detections passed the filters, and the day lies inside an imported request/download interval for this sensor. "
                     "This means no records were returned or retained — not that every location was observed under clear conditions.",
    "unknown": "No detections, and either no import interval establishes that this day was requested for this sensor, or the sensor has no records "
               "anywhere in the import that day although it normally has many (a likely data gap). Treated as unknown, not zero.",
    "sensor_unavailable": "This sensor/platform is not present in the imported data.",
    "outside_range": "Outside the imported date range.",
}


# ------------------------------------------------------------------ daily series
def daily(f: Filters) -> dict:
    rev = get_revision()
    return cache.get_or_compute(cache.make_key("daily", rev, f.key()), lambda: _daily(f))


def _daily(f: Filters) -> dict:
    sql, params = filtered_sql(f)
    usql, uparams = filtered_sql(f, apply_quality=False)
    _, _, cell = cell_sql(f.grid)
    with cursor() as cur:
        rows = cur.execute(f"""WITH f AS ({sql}), g AS (SELECT acq_date, series, platform, {cell} AS cid, frp, daynight FROM f o)
            SELECT acq_date, series, count(*), count(DISTINCT cid), sum(frp), avg(frp), max(frp), median(frp),
                   count(*) FILTER (WHERE daynight = 'D'), count(*) FILTER (WHERE daynight = 'N'),
                   count(*) FILTER (WHERE platform = 'Terra'), count(*) FILTER (WHERE platform = 'Aqua'), count(frp)
            FROM g GROUP BY ALL
            UNION ALL
            SELECT acq_date, 'UNION', count(*), count(DISTINCT cid), sum(frp), avg(frp), max(frp), median(frp),
                   count(*) FILTER (WHERE daynight = 'D'), count(*) FILTER (WHERE daynight = 'N'), NULL, NULL, count(frp)
            FROM g GROUP BY ALL""", params).fetchall()
        urows = cur.execute(f"SELECT acq_date, series, count(*) FROM ({usql}) o GROUP BY ALL", uparams).fetchall()
    ndays = (f.end - f.start).days + 1
    dates = [f.start + timedelta(days=i) for i in range(ndays)]
    idx = {d: i for i, d in enumerate(dates)}
    series_keys = f.series + (["UNION"] if f.series else [])
    out = {s: {k: [0] * ndays for k in ("detections", "cells", "day", "night")} | {k: [None] * ndays for k in ("frp_sum", "frp_mean", "frp_max", "frp_median")}
           | {"unfiltered": [0] * ndays, "status": [None] * ndays, "status_origin": [None] * ndays, "frp_n": [0] * ndays} for s in series_keys}
    for s in series_keys:
        if s == "MODIS":
            out[s]["terra"] = [0] * ndays
            out[s]["aqua"] = [0] * ndays
    for d, s, n, c, fs, fm, fx, fmed, dn, nn, terra, aqua, frpn in rows:
        if s not in out:
            continue
        i = idx[d]
        o = out[s]
        o["detections"][i] = n; o["cells"][i] = c; o["day"][i] = dn; o["night"][i] = nn
        o["frp_sum"][i] = round(fs, 3) if fs is not None else None
        o["frp_mean"][i] = round(fm, 3) if fm is not None else None
        o["frp_max"][i] = fx
        o["frp_median"][i] = fmed
        o["frp_n"][i] = frpn
        if s == "MODIS":
            o["terra"][i] = terra; o["aqua"][i] = aqua
    for d, s, n in urows:
        if s in out:
            out[s]["unfiltered"][idx[d]] += n
            out["UNION"]["unfiltered"][idx[d]] += n
    ctx = coverage_context(f)
    for s in f.series:
        for i, d in enumerate(dates):
            st, origin = day_status(ctx, s, d, out[s]["detections"][i] > 0)
            out[s]["status"][i] = st
            out[s]["status_origin"][i] = origin
    if f.series:
        u = out["UNION"]
        for i in range(ndays):
            sts = [out[s]["status"][i] for s in f.series]
            if u["cells"][i] > 0:
                u["status"][i] = "detections"
            elif all(x == "outside_range" for x in sts):
                u["status"][i] = "outside_range"
            elif all(x in ("zero_reported", "sensor_unavailable") for x in sts) and any(x == "zero_reported" for x in sts):
                u["status"][i] = "zero_reported"
            else:
                u["status"][i] = "unknown"
    if "UNION" in out:
        # The union is defined only for occupied cells; raw MODIS + VIIRS counts and FRP are never combined.
        for k in ("detections", "day", "night", "frp_sum", "frp_mean", "frp_max", "frp_median", "frp_n", "unfiltered"):
            out["UNION"][k] = [None] * ndays
    return envelope(f, METRICS, dates=[d.isoformat() for d in dates], series=out,
                    series_labels={s: N.SERIES_LABEL[s] for s in series_keys}, status_doc=STATUS_DOC, grid_doc=GRID_DOC)


METRICS = {
    "detections": "Raw detection count: number of FIRMS active-fire records passing the filters (per sensor/platform). "
                  "A detection is not a separate fire event and not burned area.",
    "cells": "Occupied cells: number of distinct grid cells containing ≥1 detection on that UTC day, per sensor. "
             "Not burned area; cells are not equal-area.",
    "union_cells": "Cells with detections from any selected sensor: distinct cells occupied by at least one selected sensor that day. "
                   "A cell detected by both MODIS and VIIRS counts once. Its sensitivity changes when sensors are added or removed.",
    "frp_sum": "Sum of FRP (MW) over the day's detections. Repeated observations of the same fire add up, so this is a descriptive "
               "sum of per-pixel radiative power, not total energy or simultaneous regional fire power.",
    "frp_mean": "Mean FRP (MW) per detection.",
    "frp_max": "Maximum single-detection FRP (MW).",
}


# ------------------------------------------------------------------ frame (map)
def frame_window(day: date, mode: int) -> tuple[date, date]:
    if mode not in (1, 7, 30):
        raise ValueError("frame mode must be 1, 7 or 30 days")
    return day - timedelta(days=mode - 1), day


def frame_cells(f: Filters, day: date, mode: int, bbox: tuple[float, float, float, float] | None, limit: int = 30000) -> dict:
    key = cache.make_key("frame", get_revision(), {**f.key(), "day": day, "mode": mode, "bbox": bbox, "limit": limit})
    return cache.get_or_compute(key, lambda: _frame_cells(f, day, mode, bbox, limit))


def _bbox_where(bbox):
    if not bbox:
        return "", []
    w, s, e, n = bbox
    return "o.lon BETWEEN ? AND ? AND o.lat BETWEEN ? AND ?", [w, e, s, n]


def _frame_cells(f: Filters, day: date, mode: int, bbox, limit: int) -> dict:
    a, b = frame_window(day, mode)
    ew, ep = _bbox_where(bbox)
    sql, params = filtered_sql(f, a, b, extra_where=ew, extra_params=ep)
    ci, cj, _ = cell_sql(f.grid)
    series = f.series
    sel = ", ".join(f"count(*) FILTER (WHERE series = '{s}') AS \"{s}\"" for s in series) or "0 AS none"
    with cursor() as cur:
        total = cur.execute(f"SELECT count(DISTINCT ({cj}) * 100000000 + ({ci})) FROM ({sql}) o", params).fetchone()[0]
        rows = cur.execute(f"""SELECT {ci} AS ci, {cj} AS cj, count(*) AS n, {sel}, max(frp), sum(frp), count(DISTINCT acq_date), min(acq_date), max(acq_date)
            FROM ({sql}) o GROUP BY ALL ORDER BY n DESC, ci, cj LIMIT ?""", params + [limit]).fetchall()  # n: ordering only, not returned
        summ = cur.execute(f"""SELECT series, count(*), count(DISTINCT ({cj}) * 100000000 + ({ci})), sum(frp), max(frp),
                count(*) FILTER (WHERE daynight='D'), count(*) FILTER (WHERE daynight='N') FROM ({sql}) o GROUP BY 1""", params).fetchall()
        union = cur.execute(f"SELECT NULL, count(DISTINCT ({cj}) * 100000000 + ({ci})) FROM ({sql}) o", params).fetchone()
    nsel = len(series)
    cells = []
    for r in rows:
        by = {s: r[3 + k] for k, s in enumerate(series)}
        # Per-sensor counts only: raw MODIS and VIIRS detections are never added together.
        cells.append({"ci": r[0], "cj": r[1], "by_series": by, "sensors_detecting": sum(1 for v in by.values() if v),
                      "frp_max": r[3 + nsel], "frp_sum": round(r[4 + nsel], 2) if r[4 + nsel] is not None else None,
                      "days": r[5 + nsel], "first": r[6 + nsel].isoformat(), "last": r[7 + nsel].isoformat()})
    summary = {s: {"detections": 0, "cells": 0, "frp_sum": None, "frp_max": None, "day": 0, "night": 0} for s in series}
    for s, n, c, fs, fx, dn, nn in summ:
        summary[s] = {"detections": n, "cells": c, "frp_sum": round(fs, 2) if fs is not None else None, "frp_max": fx, "day": dn, "night": nn}
    return envelope(f, {"cells": "Cells occupied during the frame window. Cell counts in the window are distinct cells over the whole window, "
                                 "not sums of daily counts.", **METRICS},
                    frame={"date": day.isoformat(), "mode_days": mode, "start": a.isoformat(), "end": b.isoformat(),
                           "label": f"{a.isoformat()} 00:00 – {b.isoformat()} 23:59 UTC" if mode > 1 else f"{b.isoformat()} 00:00–24:00 UTC",
                           "utc_interval": [f"{a.isoformat()}T00:00:00Z", f"{(b + timedelta(days=1)).isoformat()}T00:00:00Z"]},
                    grid_size=f.grid, cells=cells, cells_total=total, truncated=total > len(cells), viewport=bbox,
                    summary=summary, union={"cells": union[1], "definition": METRICS["union_cells"]})


POINT_FIELDS = ["rid", "acq_date", "acq_hhmm", "lat", "lon", "instrument", "platform", "series", "source_product", "stream", "version",
                "conf_raw", "conf_cat", "frp", "daynight", "type_code", "scan", "track", "modis_brightness", "modis_bright_t31",
                "viirs_bright_ti4", "viirs_bright_ti5", "source_file", "source_row", "batch_id"]


def points(f: Filters, start: date, end: date, bbox=None, limit: int = 5000, offset: int = 0, include_filtered_out: bool = False) -> dict:
    ew, ep = _bbox_where(bbox)
    sql, params = filtered_sql(f, start, end, apply_quality=not include_filtered_out, extra_where=ew, extra_params=ep)
    cols = ", ".join(f"o.{c}" for c in POINT_FIELDS)
    with cursor() as cur:
        total = cur.execute(f"SELECT count(*) FROM ({sql}) o", params).fetchone()[0]
        rows = cur.execute(f"SELECT {cols} FROM ({sql}) o ORDER BY o.acq_ts, o.rid LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    recs = []
    for r in rows:
        d = dict(zip(POINT_FIELDS, r))
        d["acq_date"] = d["acq_date"].isoformat()
        d["acq_time_utc"] = f"{d['acq_hhmm'][:2]}:{d['acq_hhmm'][2:]} UTC"
        d["type_label"] = N.TYPE_LABEL.get(d["type_code"], "unknown") if d["type_code"] is not None else "missing"
        recs.append(d)
    return envelope(f, "Individual FIRMS detection records (pixel centres). Nominal pixel sizes (~1 km MODIS, ~375 m VIIRS at nadir) are not fire sizes.",
                    window={"start": start.isoformat(), "end": end.isoformat()}, total=total, offset=offset, limit=limit,
                    returned=len(recs), truncated=total > offset + len(recs), records=recs,
                    quality_filters_applied=not include_filtered_out)


# ------------------------------------------------------------------ history
def history(f: Filters) -> dict:
    return cache.get_or_compute(cache.make_key("history", get_revision(), f.key()), lambda: _history(f))


def _history(f: Filters) -> dict:
    sql, params = filtered_sql(f)
    _, _, cell = cell_sql(f.grid)
    with cursor() as cur:
        rows = cur.execute(f"""WITH g AS (SELECT year(acq_date) y, month(acq_date) m, series, {cell} cid, frp FROM ({sql}) o)
            SELECT y, m, series, count(*), count(DISTINCT cid), sum(frp), max(frp) FROM g GROUP BY ALL
            UNION ALL SELECT y, m, 'UNION', count(*), count(DISTINCT cid), sum(frp), max(frp) FROM g GROUP BY ALL""", params).fetchall()
        yrows = cur.execute(f"""WITH g AS (SELECT year(acq_date) y, series, {cell} cid FROM ({sql}) o)
            SELECT y, series, count(DISTINCT cid) FROM g GROUP BY ALL
            UNION ALL SELECT y, 'UNION', count(DISTINCT cid) FROM g GROUP BY ALL""", params).fetchall()
    d = daily(f)
    dates = [date.fromisoformat(x) for x in d["dates"]]
    series_keys = list(d["series"].keys())
    months: dict[tuple[int, int], dict] = {}
    for i, dt in enumerate(dates):
        mk = (dt.year, dt.month)
        m = months.setdefault(mk, {"days_in_range": 0, "series": {s: {"detections": 0, "sum_daily_cells": 0, "distinct_cells": 0, "frp_sum": 0.0,
                                                                        "frp_max": None, "days_detections": 0, "days_zero": 0, "days_unknown": 0}
                                                                    for s in series_keys}})
        m["days_in_range"] += 1
        for s in series_keys:
            ss = d["series"][s]
            ms = m["series"][s]
            ms["sum_daily_cells"] += ss["cells"][i]
            st = ss["status"][i]
            if st == "detections":
                ms["days_detections"] += 1
            elif st == "zero_reported":
                ms["days_zero"] += 1
            elif st in ("unknown", "sensor_unavailable"):
                ms["days_unknown"] += 1
    for y, mth, s, n, c, fs, fx in rows:
        if (y, mth) in months and s in months[(y, mth)]["series"]:
            ms = months[(y, mth)]["series"][s]
            ms.update({"detections": n, "distinct_cells": c, "frp_sum": round(fs or 0, 2), "frp_max": fx})
    month_list = []
    for (y, mth), v in sorted(months.items()):
        full_days = (date(y + (mth == 12), mth % 12 + 1, 1) - date(y, mth, 1)).days
        month_list.append({"year": y, "month": mth, "label": f"{y}-{mth:02d}", "days_in_range": v["days_in_range"], "days_in_month": full_days,
                           "partial": v["days_in_range"] < full_days, "series": v["series"]})
    years: dict[int, dict] = {}
    for m in month_list:
        yv = years.setdefault(m["year"], {"days_in_range": 0, "series": {s: {"detections": 0, "sum_daily_cells": 0, "distinct_cells": 0, "frp_sum": 0.0,
                                                                            "days_detections": 0, "days_zero": 0, "days_unknown": 0} for s in series_keys}})
        yv["days_in_range"] += m["days_in_range"]
        for s in series_keys:
            for k in ("detections", "sum_daily_cells", "frp_sum", "days_detections", "days_zero", "days_unknown"):
                yv["series"][s][k] += m["series"][s][k]
    for y, s, c in yrows:
        if y in years and s in years[y]["series"]:
            years[y]["series"][s]["distinct_cells"] = c
    year_list = []
    for y, v in sorted(years.items()):
        ndays = 366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365
        for s in series_keys:
            v["series"][s]["frp_sum"] = round(v["series"][s]["frp_sum"], 2)
        year_list.append({"year": y, "days_in_range": v["days_in_range"], "days_in_year": ndays, "partial": v["days_in_range"] < ndays,
                          "series": v["series"]})
    for block in month_list + year_list:
        u = block["series"].get("UNION")
        if u:
            for k in ("detections", "frp_sum", "frp_max"):
                u[k] = None
    return envelope(f, {"sum_daily_cells": "Sum over days of daily occupied-cell counts (a cell burning on 10 days counts 10 times).",
                        "distinct_cells": "Distinct cells with ≥1 detection at any time in the period (each cell counted once).",
                        **METRICS},
                    months=month_list, years=year_list, series_labels=d["series_labels"],
                    notes=["Two imported years are not enough to infer a sustained seasonal shift or trend.",
                           "Partial months/years are flagged; compare matched dates when coverage differs."])
