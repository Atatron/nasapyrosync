"""Schema detection and record-level normalization for FIRMS active-fire CSVs.

Every rule here is deliberately explicit so the Data & Methods page and the
data dictionary can describe it exactly.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

# ---------------------------------------------------------------- schemas
MODIS_REQUIRED = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "brightness"}
VIIRS_REQUIRED = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "bright_ti4"}
OPTIONAL = {"scan", "track", "instrument", "version", "frp", "daynight", "type", "bright_t31", "bright_ti5"}

# Series = the unit kept separate in every analysis.
SERIES = ["MODIS", "VIIRS_N20", "VIIRS_N21", "VIIRS_SNPP"]
SERIES_LABEL = {
    "MODIS": "MODIS (Terra + Aqua)",
    "VIIRS_N20": "VIIRS NOAA-20",
    "VIIRS_N21": "VIIRS NOAA-21",
    "VIIRS_SNPP": "VIIRS Suomi NPP",
    "UNION": "Cells with detections from any selected sensor",
}
PLATFORM_SERIES = {"Terra": "MODIS", "Aqua": "MODIS", "N20": "VIIRS_N20", "N21": "VIIRS_N21", "SNPP": "VIIRS_SNPP"}
PLATFORM_LABEL = {"Terra": "Terra (MODIS)", "Aqua": "Aqua (MODIS)", "N20": "NOAA-20 (VIIRS)", "N21": "NOAA-21 (VIIRS)", "SNPP": "Suomi NPP (VIIRS)"}

_MODIS_SAT = {"terra": "Terra", "t": "Terra", "aqua": "Aqua", "a": "Aqua"}
# JPSS-1 == NOAA-20, JPSS-2 == NOAA-21 (satellite designations, not guesses).
_VIIRS_SAT = {
    "n20": "N20", "noaa-20": "N20", "noaa20": "N20", "j1": "N20", "jpss-1": "N20", "1": "N20",
    "n21": "N21", "noaa-21": "N21", "noaa21": "N21", "j2": "N21", "jpss-2": "N21",
    "n": "SNPP", "npp": "SNPP", "snpp": "SNPP", "suomi npp": "SNPP", "suomi-npp": "SNPP",
}
_VIIRS_CONF = {"l": "low", "low": "low", "n": "nominal", "nominal": "nominal", "h": "high", "high": "high"}

# Documented FIRMS type codes (see docs/METHODOLOGY.md for the source note).
TYPE_LABEL = {0: "Presumed vegetation fire", 1: "Active volcano", 2: "Other static land source", 3: "Offshore detection"}

# MODIS confidence classes used for the *normalized category only*.
MODIS_CONF_BINS = ((0, 29, "low"), (30, 79, "nominal"), (80, 100, "high"))

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{1,4}$")
_TIME_COLON_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


class RowError(ValueError):
    """Raised for a row that must be rejected; message is the user-facing reason."""


def detect_schema(columns: list[str]) -> tuple[str | None, list[str]]:
    """Return (instrument, missing_required) from a CSV header."""
    cols = {c.strip().lower() for c in columns}
    if "brightness" in cols or "bright_t31" in cols:
        missing = sorted(MODIS_REQUIRED - cols)
        return "MODIS", missing
    if "bright_ti4" in cols or "bright_ti5" in cols:
        missing = sorted(VIIRS_REQUIRED - cols)
        return "VIIRS", missing
    return None, sorted((MODIS_REQUIRED & VIIRS_REQUIRED) - cols)


def parse_acq_date(raw: str) -> date:
    s = (raw or "").strip()
    if not _DATE_RE.match(s):
        raise RowError(f"acq_date '{raw}' is not YYYY-MM-DD")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise RowError(f"acq_date '{raw}' is not a valid calendar date") from None


def parse_acq_time(raw: str) -> tuple[int, int]:
    """FIRMS acq_time is HHMM in UTC, sometimes without leading zeros.

    '402' -> (4, 2); '137' -> (1, 37); '5' -> (0, 5); '04:02' -> (4, 2).
    """
    s = (raw or "").strip()
    m = _TIME_COLON_RE.match(s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    elif _TIME_RE.match(s):
        s4 = s.zfill(4)
        hh, mm = int(s4[:2]), int(s4[2:])
    else:
        raise RowError(f"acq_time '{raw}' is not HHMM")
    if hh > 23 or mm > 59:
        raise RowError(f"acq_time '{raw}' has invalid hour/minute")
    return hh, mm


def format_hhmm(hh: int, mm: int) -> str:
    return f"{hh:02d}{mm:02d}"


def quantize_e5(raw: str, lo: float, hi: float, name: str) -> tuple[float, int]:
    """Parse a coordinate exactly and quantize to integer 1e-5 degrees."""
    s = (raw or "").strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise RowError(f"{name} '{raw}' is not numeric") from None
    if not d.is_finite():
        raise RowError(f"{name} '{raw}' is not finite")
    v = float(d)
    if v < lo or v > hi:
        raise RowError(f"{name} {raw} outside [{lo}, {hi}]")
    e5 = int((d * 100000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    return v, e5


def opt_float(raw: str | None, name: str, allow_negative: bool = True) -> float | None:
    if raw is None:
        return None
    s = raw.strip()
    if s == "" or s.lower() in {"nan", "null", "none"}:
        return None
    try:
        v = float(s)
    except ValueError:
        raise RowError(f"{name} '{raw}' is not numeric") from None
    if not math.isfinite(v):
        return None
    if not allow_negative and v < 0:
        raise RowError(f"{name} {raw} is negative")
    return v


def modis_conf(raw: str) -> tuple[int, str]:
    s = (raw or "").strip()
    try:
        v = float(s)
    except ValueError:
        raise RowError(f"MODIS confidence '{raw}' is not numeric 0-100") from None
    if not v.is_integer() or v < 0 or v > 100:
        raise RowError(f"MODIS confidence '{raw}' is not an integer 0-100")
    n = int(v)
    for lo, hi, cat in MODIS_CONF_BINS:
        if lo <= n <= hi:
            return n, cat
    raise RowError(f"MODIS confidence '{raw}' out of range")  # pragma: no cover


def viirs_conf(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s not in _VIIRS_CONF:
        raise RowError(f"VIIRS confidence '{raw}' is not one of l/n/h")
    return _VIIRS_CONF[s]


def platform_for(instrument: str, raw_sat: str) -> str:
    s = (raw_sat or "").strip().lower()
    table = _MODIS_SAT if instrument == "MODIS" else _VIIRS_SAT
    if s not in table:
        raise RowError(f"unrecognized {instrument} satellite value '{raw_sat}'")
    return table[s]


def stream_from_version(version: str | None) -> str | None:
    v = (version or "").strip().upper()
    if v.endswith("URT"):
        return "URT"
    if v.endswith("RT") and not v.endswith("NRT"):
        return "RT"
    if v.endswith("NRT"):
        return "NRT"
    return None


_SP_TOKENS = re.compile(r"(^|[^A-Z])(SP|ARCHIVE|FIRE_ARCHIVE)([^A-Z]|$)")
_NRT_TOKENS = re.compile(r"(^|[^A-Z])(NRT|FIRE_NRT)([^A-Z]|$)")


def stream_from_path(path_hint: str) -> str | None:
    """Detect SP/NRT from a FIRMS-style path or file name; None if unclear."""
    p = path_hint.upper().replace("-", "_")
    has_sp = bool(_SP_TOKENS.search(p))
    has_nrt = bool(_NRT_TOKENS.search(p))
    if has_sp and not has_nrt:
        return "SP"
    if has_nrt and not has_sp:
        return "NRT"
    return None


def platform_from_path(path_hint: str) -> str | None:
    p = path_hint.upper()
    if "NOAA20" in p or "NOAA_20" in p or "J1V" in p:
        return "N20"
    if "NOAA21" in p or "NOAA_21" in p or "J2V" in p:
        return "N21"
    if "SNPP" in p or "SUOMI" in p or re.search(r"(^|[^A-Z])SV[-_]C", p):
        return "SNPP"
    return None


def source_product(instrument: str, platform: str, stream: str) -> str:
    if instrument == "MODIS":
        base = "MODIS"
    else:
        base = {"N20": "VIIRS_NOAA20", "N21": "VIIRS_NOAA21", "SNPP": "VIIRS_SNPP"}.get(platform, "VIIRS_UNKNOWN")
    return f"{base}_{stream}" if stream != "unknown" else f"{base}_unknown-stream"


_WINDOW_RE = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{1,3})d", re.IGNORECASE)


def declared_window(filename: str) -> tuple[date, date] | None:
    """Download window declared by a file name such as '2024-06-19_5d.csv'.

    The window is *declared* metadata about the original request; each row is
    still assigned by its own acq_date/acq_time.
    """
    m = _WINDOW_RE.search(filename)
    if not m:
        return None
    try:
        start = date.fromisoformat(m.group(1))
    except ValueError:
        return None
    n = int(m.group(2))
    if n < 1:
        return None
    return start, start + timedelta(days=n - 1)


@dataclass
class Obs:
    record_key: str
    acq_date: date
    acq_ts: datetime
    acq_hhmm: str
    lat: float
    lon: float
    lat_e5: int
    lon_e5: int
    instrument: str
    platform: str
    satellite_raw: str
    series: str
    source_product: str
    stream: str
    version: str | None
    conf_raw: str
    conf_num: int | None
    conf_cat: str
    frp: float | None
    daynight: str | None
    type_code: int | None
    scan: float | None
    track: float | None
    modis_brightness: float | None
    modis_bright_t31: float | None
    viirs_bright_ti4: float | None
    viirs_bright_ti5: float | None


def normalize_row(row: dict[str, str], instrument: str, stream_hint: str | None) -> Obs:
    g = row.get
    lat, lat_e5 = quantize_e5(g("latitude", ""), -90.0, 90.0, "latitude")
    lon, lon_e5 = quantize_e5(g("longitude", ""), -180.0, 180.0, "longitude")
    d = parse_acq_date(g("acq_date", ""))
    hh, mm = parse_acq_time(g("acq_time", ""))
    inst_col = (g("instrument") or "").strip().upper()
    if inst_col and inst_col != instrument:
        raise RowError(f"instrument column '{inst_col}' disagrees with {instrument} schema")
    sat_raw = (g("satellite") or "").strip()
    platform = platform_for(instrument, sat_raw)
    version = (g("version") or "").strip() or None
    stream = stream_from_version(version) or stream_hint or "unknown"
    if instrument == "MODIS":
        conf_num, conf_cat = modis_conf(g("confidence", ""))
        b1 = opt_float(g("brightness"), "brightness")
        b2 = opt_float(g("bright_t31"), "bright_t31")
        if b1 is None:
            raise RowError("brightness is missing")
        vb1 = vb2 = None
    else:
        conf_num, conf_cat = None, viirs_conf(g("confidence", ""))
        vb1 = opt_float(g("bright_ti4"), "bright_ti4")
        vb2 = opt_float(g("bright_ti5"), "bright_ti5")
        if vb1 is None:
            raise RowError("bright_ti4 is missing")
        b1 = b2 = None
    frp = opt_float(g("frp"), "frp", allow_negative=False)
    dn = (g("daynight") or "").strip().upper() or None
    if dn is not None and dn not in {"D", "N"}:
        raise RowError(f"daynight '{dn}' is not D or N")
    traw = (g("type") or "").strip()
    if traw == "":
        tcode = None
    else:
        try:
            tf = float(traw)
        except ValueError:
            raise RowError(f"type '{traw}' is not an integer code") from None
        if not tf.is_integer():
            raise RowError(f"type '{traw}' is not an integer code")
        tcode = int(tf)
    scan = opt_float(g("scan"), "scan", allow_negative=False)
    track = opt_float(g("track"), "track", allow_negative=False)
    hhmm = format_hhmm(hh, mm)
    ts = datetime(d.year, d.month, d.day, hh, mm)
    conf_raw = (g("confidence") or "").strip()
    key_src = "|".join(
        str(x)
        for x in (instrument, platform, stream, version, d.isoformat(), hhmm, lat_e5, lon_e5, b1, b2, vb1, vb2, frp, scan, track, conf_raw.lower(), dn, tcode)
    )
    rk = hashlib.sha1(key_src.encode()).hexdigest()
    return Obs(
        record_key=rk, acq_date=d, acq_ts=ts, acq_hhmm=hhmm, lat=lat, lon=lon, lat_e5=lat_e5, lon_e5=lon_e5,
        instrument=instrument, platform=platform, satellite_raw=sat_raw, series=PLATFORM_SERIES[platform],
        source_product=source_product(instrument, platform, stream), stream=stream, version=version,
        conf_raw=conf_raw, conf_num=conf_num, conf_cat=conf_cat, frp=frp, daynight=dn, type_code=tcode,
        scan=scan, track=track, modis_brightness=b1, modis_bright_t31=b2, viirs_bright_ti4=vb1, viirs_bright_ti5=vb2,
    )
