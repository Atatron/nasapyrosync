"""NASA GIBS date-enabled imagery metadata.

Tile URLs follow the documented GIBS REST WMTS pattern
  {base}/wmts/epsg3857/best/{Layer}/default/{Time}/{TileMatrixSet}/{z}/{y}/{x}.{ext}
and ALWAYS include an explicit date (never the service default).
Temporal availability is read from the WMTS DescribeDomains REST endpoint
  {base}/wmts/epsg3857/best/1.0.0/{Layer}/default/{TileMatrixSet}/all/all.xml
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta

import httpx

from .config import get_settings

TMS = "GoogleMapsCompatible_Level9"
LAYERS = [
    {"id": "VIIRS_NOAA20_CorrectedReflectance_TrueColor", "label": "VIIRS NOAA-20 Corrected Reflectance (True Color)",
     "platform": "NOAA-20 / VIIRS", "format": "jpg", "tile_matrix_set": TMS, "max_native_zoom": 8},
    {"id": "MODIS_Terra_CorrectedReflectance_TrueColor", "label": "MODIS Terra Corrected Reflectance (True Color)",
     "platform": "Terra / MODIS", "format": "jpg", "tile_matrix_set": TMS, "max_native_zoom": 8},
    {"id": "MODIS_Aqua_CorrectedReflectance_TrueColor", "label": "MODIS Aqua Corrected Reflectance (True Color)",
     "platform": "Aqua / MODIS", "format": "jpg", "tile_matrix_set": TMS, "max_native_zoom": 8},
]
# Snapshot of DescribeDomains responses read during development on 2026-11-14.
# Terra and NOAA-20 were queried for 2023-01-01--2024-12-31 only (the imported range),
# so the snapshot asserts availability only for that window.
SNAPSHOT = {
    "verified_on": "2026-11-14",
    "domains": {
        "VIIRS_NOAA20_CorrectedReflectance_TrueColor": "2023-01-01/2024-12-31/P1D",
        "MODIS_Terra_CorrectedReflectance_TrueColor": "2023-01-01/2024-12-31/P1D",
        "MODIS_Aqua_CorrectedReflectance_TrueColor": "2002-07-03/2002-07-30/P1D,2002-08-07/2002-09-12/P1D,2002-09-14/2022-03-31/P1D,2022-04-17/2026-10-11/P1D",
    },
    "scope_note": "Terra and NOAA-20 domains were verified only for the 2023–2024 window; dates outside it are treated as unverified.",
}
ACK = ("We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse Services (GIBS), "
       "part of NASA's Earth Science Data and Information System (ESDIS).")
_CACHE_TTL = 24 * 3600
_DOMAIN_RE = re.compile(r"<Domain>(.*?)</Domain>", re.S)


def parse_domain(text: str) -> list[tuple[date, date]]:
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split("/")
        a = date.fromisoformat(bits[0][:10])
        b = date.fromisoformat(bits[1][:10]) if len(bits) > 1 else a
        out.append((a, b))
    return out


def _fetch_domain(layer: dict, client: httpx.Client) -> str:
    s = get_settings()
    url = f"{s.gibs_base_url}/wmts/epsg3857/best/1.0.0/{layer['id']}/default/{layer['tile_matrix_set']}/all/all.xml"
    r = client.get(url, timeout=20)
    r.raise_for_status()
    m = _DOMAIN_RE.search(r.text)
    if not m:
        raise ValueError("DescribeDomains response has no <Domain>")
    return m.group(1).strip()


def layer_info(client: httpx.Client | None = None, force: bool = False) -> dict:
    s = get_settings()
    cache_path = s.cache_dir / "gibs_domains.json"
    if not force and cache_path.is_file():
        try:
            c = json.loads(cache_path.read_text())
            if time.time() - c["fetched_at"] < _CACHE_TTL:
                return _assemble(c["domains"], "live", c["fetched_at_iso"])
        except Exception:  # noqa: BLE001
            pass
    if not s.offline:
        try:
            own = client is None
            client = client or httpx.Client(follow_redirects=True)
            try:
                domains = {l["id"]: _fetch_domain(l, client) for l in LAYERS}
            finally:
                if own:
                    client.close()
            now = time.time()
            iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
            cache_path.write_text(json.dumps({"fetched_at": now, "fetched_at_iso": iso, "domains": domains}))
            return _assemble(domains, "live", iso)
        except Exception as e:  # noqa: BLE001
            info = _assemble(SNAPSHOT["domains"], "snapshot", SNAPSHOT["verified_on"])
            info["warning"] = f"Live GIBS DescribeDomains request failed ({type(e).__name__}); using the development snapshot. " + SNAPSHOT["scope_note"]
            return info
    info = _assemble(SNAPSHOT["domains"], "snapshot", SNAPSHOT["verified_on"])
    info["warning"] = "Offline mode; using the development snapshot. " + SNAPSHOT["scope_note"]
    return info


def _assemble(domains: dict, source: str, when: str) -> dict:
    s = get_settings()
    layers = []
    for l in LAYERS:
        dom = domains.get(l["id"], "")
        layers.append({**l, "domain": dom, "ranges": [[a.isoformat(), b.isoformat()] for a, b in parse_domain(dom)] if dom else [],
                       "url_template": f"{s.gibs_base_url}/wmts/epsg3857/best/{l['id']}/default/{{date}}/{l['tile_matrix_set']}/{{z}}/{{y}}/{{x}}.{l['format']}"})
    return {"layers": layers, "domain_source": source, "domain_checked": when, "acknowledgement": ACK,
            "notes": ["Daily corrected-reflectance imagery is assembled from the satellite's overpasses for that day; it is not captured at the instant of each hotspot.",
                      "Clouds, smoke, swath gaps, or blank imagery do not prove the absence of fire.",
                      "Imagery tiles are requested directly from NASA GIBS and require internet access."]}


def available(ranges: list[list[str]], d: date) -> bool:
    return any(date.fromisoformat(a) <= d <= date.fromisoformat(b) for a, b in ranges)


def nearest(ranges: list[list[str]], d: date) -> date | None:
    best = None
    for a, b in ranges:
        a_, b_ = date.fromisoformat(a), date.fromisoformat(b)
        cand = d if a_ <= d <= b_ else (a_ if d < a_ else b_)
        if best is None or abs((cand - d).days) < abs((best - d).days):
            best = cand
    return best


def tile_url(layer_id: str, d: date, z: int, y: int, x: int) -> str:
    l = next(l for l in LAYERS if l["id"] == layer_id)
    s = get_settings()
    return f"{s.gibs_base_url}/wmts/epsg3857/best/{l['id']}/default/{d.isoformat()}/{l['tile_matrix_set']}/{z}/{y}/{x}.{l['format']}"


def _unused(d: date) -> date:  # pragma: no cover
    return d + timedelta(days=0)
