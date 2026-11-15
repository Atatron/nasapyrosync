"""Area of Interest validation, registry, and exact point-in-polygon membership.

Boundary convention: a detection whose coordinates lie exactly on the AOI
boundary is INCLUDED (closed-set / "covers" semantics, shapely.intersects_xy).
Bounding boxes are used only to pre-filter candidates; every candidate is then
tested against the exact geometry.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import mapping, shape
from shapely.validation import explain_validity

from .config import get_settings
from .db import cursor, get_revision

RESOURCES = Path(__file__).parent / "resources"
MAX_VERTICES = 200_000
_member_lock = threading.Lock()


class AOIError(ValueError):
    pass


@lru_cache(maxsize=1)
def regions() -> dict[str, dict]:
    fc = json.loads((RESOURCES / "regions.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in fc["features"]:
        p = f["properties"]
        g = shape(f["geometry"])
        out[p["id"]] = {"id": f"region:{p['id']}", "properties": p, "geometry": g}
    return out


def list_regions() -> list[dict]:
    res = []
    for r in regions().values():
        g = r["geometry"]
        p = r["properties"]
        res.append({"id": r["id"], "name": p["name"], "kind": p["kind"], "source": p["source"], "license": p["license"],
                    "note": p["note"], "simplification_tolerance_deg": p.get("simplification_tolerance_deg"),
                    "bbox": list(g.bounds), "is_bounding_box": False})
    return res


def _crs_name(obj: dict) -> str | None:
    crs = obj.get("crs")
    if not crs:
        return None
    try:
        return str(crs["properties"]["name"])
    except (KeyError, TypeError):
        raise AOIError("Unrecognized 'crs' member; supply WGS84 longitude/latitude (RFC 7946) coordinates.") from None


_WGS84_NAMES = {"urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:OGC::CRS84", "EPSG:4326", "urn:ogc:def:crs:EPSG::4326", "CRS84"}
_MERC_NAMES = {"EPSG:3857", "urn:ogc:def:crs:EPSG::3857", "EPSG:900913"}


def parse_geojson(obj: dict) -> tuple[shapely.Geometry, list[str]]:
    """Validate a GeoJSON Polygon/MultiPolygon (or Feature/FeatureCollection of them)."""
    notes: list[str] = []
    if not isinstance(obj, dict) or "type" not in obj:
        raise AOIError("Not a GeoJSON object (missing 'type').")
    crs = _crs_name(obj)
    t = obj["type"]
    geoms = []
    if t == "FeatureCollection":
        feats = obj.get("features") or []
        if not feats:
            raise AOIError("FeatureCollection contains no features.")
        for f in feats:
            if not f.get("geometry"):
                raise AOIError("A feature has no geometry.")
            geoms.append(f["geometry"])
    elif t == "Feature":
        if not obj.get("geometry"):
            raise AOIError("Feature has no geometry.")
        geoms.append(obj["geometry"])
    else:
        geoms.append(obj)
    shp = []
    for gj in geoms:
        gt = gj.get("type")
        if gt not in ("Polygon", "MultiPolygon"):
            raise AOIError(f"Unsupported geometry type '{gt}'. Only Polygon and MultiPolygon are accepted.")
        try:
            shp.append(shape(gj))
        except Exception as e:  # noqa: BLE001
            raise AOIError(f"Malformed {gt} coordinates: {e}") from None
    g = shapely.union_all(shp) if len(shp) > 1 else shp[0]
    if crs and crs not in _WGS84_NAMES:
        if crs in _MERC_NAMES:
            from pyproj import Transformer
            tr = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
            g = shapely.transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
            notes.append("Geometry was explicitly transformed from EPSG:3857 (Web Mercator) to WGS84 longitude/latitude.")
        else:
            raise AOIError(f"Unsupported coordinate reference system '{crs}'. Reproject to WGS84 (EPSG:4326) longitude/latitude first.")
    return _check(g), notes


def _check(g: shapely.Geometry) -> shapely.Geometry:
    if g.is_empty:
        raise AOIError("Geometry is empty.")
    if shapely.get_num_coordinates(g) > MAX_VERTICES:
        raise AOIError(f"Geometry has more than {MAX_VERTICES} vertices; simplify it first.")
    minx, miny, maxx, maxy = g.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise AOIError("Coordinates fall outside longitude [-180, 180] / latitude [-90, 90]. "
                       "The file may be in a projected CRS, or use latitude/longitude order; GeoJSON requires [longitude, latitude].")
    if maxx - minx > 180:
        raise AOIError("Geometry spans more than 180° of longitude, which usually means it crosses the antimeridian. "
                       "Antimeridian-crossing AOIs are not supported; split the polygon at ±180°.")
    if not g.is_valid:
        raise AOIError(f"Invalid geometry: {explain_validity(g)}. Fix self-intersections or ring errors and try again.")
    if g.area == 0:
        raise AOIError("Geometry has zero area.")
    return g


def aoi_id_for(g: shapely.Geometry) -> str:
    wkb = shapely.to_wkb(shapely.set_precision(g, 1e-7), hex=True)
    return "custom:" + hashlib.sha1(wkb.encode()).hexdigest()[:16]


def register_custom(obj: dict, name: str | None = None) -> dict:
    g, notes = parse_geojson(obj)
    aid = aoi_id_for(g)
    path = get_settings().aoi_dir / f"{aid.split(':')[1]}.geojson"
    feat = {"type": "Feature", "properties": {"id": aid, "name": name or "Custom AOI"}, "geometry": mapping(g)}
    path.write_text(json.dumps(feat), encoding="utf-8")
    return describe(aid) | {"notes": notes}


# ------------------------------------------------------------------ Click-to-Analyze circles (1.5)
EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius; the same sphere Leaflet uses for distances (6371 km)
CIRCLE_MIN_KM, CIRCLE_MAX_KM = 0.1, 2000.0
CIRCLE_VERTICES = 96


def parse_circle(aoi_id: str) -> tuple[float, float, float]:
    """'circle:<lat>,<lon>,<radius_km>' -> (lat, lon, radius_km), validated."""
    try:
        lat, lon, r = (float(x) for x in aoi_id.split(":", 1)[1].split(","))
    except ValueError:
        raise AOIError("Malformed circle AOI id; expected circle:<lat>,<lon>,<radius_km>.") from None
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        raise AOIError("Circle centre must lie within latitude ±85° and longitude ±180°.")
    if not (CIRCLE_MIN_KM <= r <= CIRCLE_MAX_KM) or not math.isfinite(r):
        raise AOIError(f"Circle radius must be between {CIRCLE_MIN_KM} and {CIRCLE_MAX_KM:g} km.")
    return lat, lon, r


def circle_id(lat: float, lon: float, radius_km: float) -> str:
    """Canonical id: centre to 4 decimals (about 11 m), radius to 3 significant digits, so equal circles share caches."""
    r = float(f"{radius_km:.3g}")
    return f"circle:{lat:.4f},{lon:.4f},{r:g}"


def circle_polygon(lat: float, lon: float, radius_km: float, n: int = CIRCLE_VERTICES) -> shapely.Geometry:
    """Geodesic circle on the sphere: n points at great-circle distance radius_km from the centre (destination-point formula).
    On the WGS84 ellipsoid the true distance differs by less than 0.5 %."""
    d = radius_km / EARTH_RADIUS_KM
    p1, l1 = math.radians(lat), math.radians(lon)
    pts = []
    for k in range(n):
        b = 2 * math.pi * k / n
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
        l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
        pts.append((math.degrees(l2), math.degrees(p2)))
    pts.append(pts[0])
    g = shapely.Polygon(pts)
    if not g.is_valid:
        g = g.buffer(0)
    return _check(g)


def get_geometry(aoi_id: str | None) -> shapely.Geometry | None:
    if not aoi_id or aoi_id == "none":
        return None
    if aoi_id.startswith("circle:"):
        return circle_polygon(*parse_circle(aoi_id))
    if aoi_id.startswith("region:"):
        r = regions().get(aoi_id.split(":", 1)[1])
        if not r:
            raise AOIError(f"Unknown region '{aoi_id}'.")
        return r["geometry"]
    if aoi_id.startswith("custom:"):
        key = aoi_id.split(":", 1)[1]
        if not key.isalnum():
            raise AOIError("Malformed AOI id.")
        p = get_settings().aoi_dir / f"{key}.geojson"
        if not p.is_file():
            raise AOIError(f"AOI '{aoi_id}' is not registered on this server. Re-draw or re-upload it.")
        return shape(json.loads(p.read_text(encoding="utf-8"))["geometry"])
    raise AOIError(f"Unknown AOI id '{aoi_id}'.")


def describe(aoi_id: str | None) -> dict:
    if not aoi_id or aoi_id == "none":
        return {"id": "none", "name": "All imported observations (no AOI)", "kind": "none", "bbox": None,
                "note": "No spatial filter. The imported extent is a download bounding box and is broader than Indonesia's land boundary."}
    g = get_geometry(aoi_id)
    if aoi_id.startswith("circle:"):
        lat, lon, r = parse_circle(aoi_id)
        return {"id": aoi_id, "name": f"Circle {r:g} km around {lat:.3f}°, {lon:.3f}°", "kind": "circle", "bbox": list(g.bounds),
                "center": [lat, lon], "radius_km": r,
                "note": "Click-to-Analyze area: a geodesic circle on the sphere. Its radius follows the map zoom when it was created."}
    if aoi_id.startswith("region:"):
        p = regions()[aoi_id.split(":", 1)[1]]["properties"]
        return {"id": aoi_id, "name": p["name"], "kind": p["kind"], "bbox": list(g.bounds), "source": p["source"],
                "license": p["license"], "note": p["note"]}
    p = get_settings().aoi_dir / f"{aoi_id.split(':', 1)[1]}.geojson"
    name = json.loads(p.read_text(encoding="utf-8"))["properties"].get("name", "Custom AOI")
    return {"id": aoi_id, "name": name, "kind": "custom", "bbox": list(g.bounds), "area_note": "Geographic (degree) geometry; not an equal-area measure.",
            "vertices": int(shapely.get_num_coordinates(g))}


def geojson_feature(aoi_id: str) -> dict:
    g = get_geometry(aoi_id)
    if g is None:
        raise AOIError("No AOI selected.")
    return {"type": "Feature", "properties": describe(aoi_id), "geometry": mapping(g)}


def ensure_members(aoi_id: str) -> int:
    """Materialize exact AOI membership for the current dataset revision."""
    g = get_geometry(aoi_id)
    with _member_lock:
        with cursor() as cur:
            rev = get_revision(cur)
            st = cur.execute("SELECT revision, n FROM aoi_cache_state WHERE aoi_id = ?", [aoi_id]).fetchone()
            if st and st[0] == rev:
                return st[1]
            minx, miny, maxx, maxy = g.bounds
            shapely.prepare(g)
            cur.execute("BEGIN TRANSACTION")
            cur.execute("DELETE FROM aoi_members WHERE aoi_id = ?", [aoi_id])
            # Work in longitude strips so memory stays bounded for country-sized AOIs (the online demo
            # runs on small serverless instances). Strips are half-open, the last one closed.
            n_strips = 16
            edges = np.linspace(minx, maxx, n_strips + 1)
            total = 0
            for i in range(n_strips):
                hi_op = "<=" if i == n_strips - 1 else "<"
                cand = cur.execute(f"SELECT rid, lon, lat FROM observations WHERE lon >= ? AND lon {hi_op} ? AND lat BETWEEN ? AND ?",
                                   [float(edges[i]), float(edges[i + 1]), miny, maxy]).fetchnumpy()
                if not len(cand["rid"]):
                    continue
                inside = shapely.intersects_xy(g, np.asarray(cand["lon"]), np.asarray(cand["lat"]))
                sel = np.asarray(cand["rid"])[inside].astype(np.int64)
                del cand, inside
                for j in range(0, len(sel), 200_000):
                    cur.execute("INSERT INTO aoi_members SELECT ?, ?, unnest(?::BIGINT[])", [aoi_id, rev, sel[j:j + 200_000].tolist()])
                total += len(sel)
            cur.execute("INSERT OR REPLACE INTO aoi_cache_state VALUES (?, ?, ?)", [aoi_id, rev, total])
            cur.execute("COMMIT")
            return int(total)
