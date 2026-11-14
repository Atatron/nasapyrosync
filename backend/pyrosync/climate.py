"""Climate indices used as CONTEXT for fire seasons (added in 1.3): ONI (ENSO) and DMI (Indian Ocean Dipole).

The tables are copies of NOAA files, stored in resources/climate with their source URL, retrieval date and a checksum.
Phases are a project classification for the Indonesian dry season (see PHASE_RULES); they describe the climate
background of past seasons and are not used to predict fire.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

RES = Path(__file__).parent / "resources" / "climate"
SEASON_CENTER = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6, "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}
ONI_SEASONS = ("JAS", "ASO")      # 3-month means centred on August and September
DMI_MONTHS = (8, 9, 10)           # August-October
ONI_THRESHOLD = 0.5               # °C; NOAA's ENSO threshold (NOAA's official episodes also need 5 consecutive overlapping seasons)
DMI_THRESHOLD = 0.4               # °C; a common IOD threshold (project choice for this HadISST-based index)
PHASE_RULES = {
    "enso": f"El Niño if the mean ONI of {' and '.join(ONI_SEASONS)} is ≥ +{ONI_THRESHOLD} °C, La Niña if ≤ −{ONI_THRESHOLD} °C, otherwise neutral. "
            "This marks the climate background of the dry season; it is not NOAA's official episode list.",
    "iod": f"Positive IOD if the mean DMI of Aug–Oct is ≥ +{DMI_THRESHOLD} °C, negative if ≤ −{DMI_THRESHOLD} °C, otherwise neutral (project threshold).",
}
SOURCES = [
    {"name": "Oceanic Niño Index (ONI), NOAA Climate Prediction Center", "url": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
     "retrieved": "2026-11-14"},
    {"name": "Dipole Mode Index (DMI), HadISST1.1, NOAA Physical Sciences Laboratory (marked preliminary by NOAA)",
     "url": "https://psl.noaa.gov/data/timeseries/month/data/dmi.had.long.data", "retrieved": "2026-11-14"},
]


def _rows(name: str):
    for line in (RES / name).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            yield line.split()


@lru_cache(maxsize=1)
def oni() -> dict[tuple[int, int], float]:
    """(year, centre month) -> ONI anomaly °C."""
    return {(int(y), SEASON_CENTER[s]): float(a) for s, y, a in _rows("oni.txt")}


@lru_cache(maxsize=1)
def dmi() -> dict[tuple[int, int], float]:
    out = {}
    for r in _rows("dmi.txt"):
        y = int(r[0])
        for m, v in enumerate(r[1:13], start=1):
            if float(v) > -999:
                out[(y, m)] = float(v)
    return out


def season_phase(year: int) -> dict:
    o = [oni().get((year, SEASON_CENTER[s])) for s in ONI_SEASONS]
    d = [dmi().get((year, m)) for m in DMI_MONTHS]
    rec: dict = {"year": year, "oni": None, "enso": None, "dmi": None, "iod": None,
                 "oni_complete": all(x is not None for x in o), "dmi_complete": all(x is not None for x in d)}
    if rec["oni_complete"]:
        v = float(np.mean(o))
        rec["oni"] = round(v, 3)
        rec["enso"] = "El Niño" if v >= ONI_THRESHOLD else "La Niña" if v <= -ONI_THRESHOLD else "neutral"
    if rec["dmi_complete"]:
        v = float(np.mean(d))
        rec["dmi"] = round(v, 3)
        rec["iod"] = "positive" if v >= DMI_THRESHOLD else "negative" if v <= -DMI_THRESHOLD else "neutral"
    elif any(x is not None for x in d):
        rec["dmi_partial"] = round(float(np.mean([x for x in d if x is not None])), 3)
        rec["dmi_months"] = sum(1 for x in d if x is not None)
    return rec


def latest() -> dict:
    o = max(oni())
    d = max(dmi())
    inv = {v: k for k, v in SEASON_CENTER.items()}
    return {"oni": {"season": inv[o[1]], "year": o[0], "value": oni()[o]}, "dmi": {"year": d[0], "month": d[1], "value": dmi()[d]}}
