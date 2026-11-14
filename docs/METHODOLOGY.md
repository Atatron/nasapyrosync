# PyroSync: methodology, definitions and limitations

> Independent hackathon prototype using NASA FIRMS data and, where enabled, NASA GIBS imagery. Not an official NASA application.

PyroSync is a **descriptive** tool. It does not forecast fires, issue warnings, estimate burned area, or calibrate one sensor against another. Every number on screen is traceable to source records, filters and the dataset revision shown on each result. The same text is in the app under **Data & Methods → Methods**.

## 1. What FIRMS detections represent
- Each record is a satellite pixel flagged as containing one or more thermal anomalies: active fires, and also other hot sources such as volcanoes or industrial sites. Coordinates are the pixel centre.
- A **detection is not a fire event**. One fire can produce many detections across pixels and overpasses. Detection counts and occupied grid cells are **not burned area**, and grid cells are not burned-area polygons.
- FIRMS active-fire files list only positive detections. The MODIS Collection 6 user guide notes that fire-pixel files contain no information on cloud cover or missing data. A day without rows is therefore **not proof** that a place was observed and found fire-free.
- **FRP** (fire radiative power, MW) is the pixel-integrated radiative power at observation time. Summed FRP is a descriptive sum of per-pixel values. It is not total energy, emissions, or simultaneous regional fire power.
- Active-fire CSVs contain no satellite photographs. Imagery on the map comes separately from NASA GIBS.

## 2. MODIS vs VIIRS (kept distinct)
| | MODIS (Terra, Aqua) | VIIRS 375 m (NOAA-20, NOAA-21, Suomi NPP) |
|---|---|---|
| Nominal pixel at nadir | ~1 km | ~375 m |
| Pixel size away from nadir | grows (see `scan`/`track`) | grows (see `scan`/`track`) |
| Confidence | numeric 0–100. Classes per C6 guide: low 0 ≤ C < 30, nominal 30 ≤ C < 80, high ≥ 80 | categorical `l`/`n`/`h` |
| Thermal fields | `brightness` (21/22), `bright_t31` | `bright_ti4`, `bright_ti5` |

VIIRS generally detects more small and cooler fires, so raw counts are **not interchangeable**, and adding satellites raises counts even when activity is unchanged. Confidence classes are not equivalent probabilities. `daynight` describes the overpass. It does not identify agricultural clearing, peat burning, crown fire or cause.

## 3. What PyroSync standardizes ("sensor-aware spatial and daily standardization")
This is **partial harmonization**: it puts the sensors on common units of organization, but no bias correction, regression calibration or probability surface is applied.

- **Time.** `acq_date` + `acq_time` (HHMM, UTC, zero-padded: `402` → 04:02, `5` → 00:05). A UTC day D is [D 00:00, D+1 00:00). Browser time zones are never applied.
- **Grid.** WGS84 lon/lat, origin (−180°, −90°). Coordinates are quantized to integer 1e-5 degrees (`lon_e5`, `lat_e5`, round-half-even). Cell index: `col = floor((lon_e5 + 18,000,000) / R)`, `row = floor((lat_e5 + 9,000,000) / R)`, where R = cell size × 100,000 (0.1° → 10,000). Cells are half-open [west, east) × [south, north), so a point on a shared edge belongs to the cell to its east or north. Longitude 180 and latitude 90 go to the last column and row. Because integer floor division is used, negative coordinates index correctly (−2.55° lies in the row starting at −2.6°). Cells are not equal-area.
- **Per sensor.** Each cell and day keeps counts per sensor: MODIS (Terra+Aqua, with a Terra/Aqua split) and each VIIRS platform. It also keeps occupied-cell indicators, FRP summaries and day/night counts.
- **Union.** "Cells with detections from any selected sensor" counts a cell once even if several sensors detected it. Its sensitivity changes with sensor availability. **The union exists only for occupied cells.** Raw MODIS and VIIRS detection counts and FRP are never added together anywhere: not in the API, the map colouring, the tables or the exports. The map colours each cell by the primary sensor's own count. Cells detected only by another selected sensor are drawn as grey outlines.

## 4. Quality and type filters
- The default preset is MODIS confidence ≥ 30 and VIIRS nominal/high. This is a *filter choice*, not equivalent detection performance. All valid records are stored, and every result discloses the active filters and the number of rows they removed.
- Type codes, from the MODIS C6 and VIIRS 375 m user guides: 0 presumed vegetation fire, 1 active volcano, 2 other static land source, 3 offshore. The default includes type 0 only. Records without a type, such as some NRT files, are "unknown".
- The VIIRS 375 m user guide v1.2 documents a type-attribution issue in collection versions 1–2: some type-2 static sources are labelled type 0. Version 3 corrects it. The supplied VIIRS sample is version 2, so a standing warning is shown on VIIRS results.

## 5. Coverage states
Every day, for every sensor, has exactly one state:
| State | Meaning |
|---|---|
| `detections` | ≥1 detection passed the filters |
| `zero_reported` | No detections passed, and the day lies inside an imported request/download interval for that sensor. This means no records were returned or retained, *not* that every location was seen under clear skies. |
| `unknown` | No detections, and either no interval covers the day, or the sensor has no records anywhere in the import that day although that delivery normally has many (rule below) |
| `sensor_unavailable` | The sensor/platform is absent from the imported data |
| `outside_range` | Outside the imported date range |

Intervals come from three sources, stored separately from observations: verified API request windows (with bounding box), CLI-declared windows (`--declare`), and windows declared by FIRMS-style file names such as `2024-06-19_5d.csv`. Rows are still assigned by their own timestamps, never by file name.

**Likely-gap rule.** Within one import batch, if the median number of rows per declared day (zeros included) is at least 20, a declared day on which the sensor has **no rows at all, anywhere** is treated as `unknown` (a likely acquisition or processing gap), not `zero_reported`. Small AOI downloads therefore keep genuine zero days, while whole-extent blanks in large regional downloads are not mistaken for "no fire". In the sample this affects, for example, VIIRS NOAA-20 on 2023-07-19 to 2023-07-22.

## 6. Import pipeline
inspect → validate → normalize → deduplicate/reconcile → commit (one transaction).
- **Validation** checks the schema, strict dates, time ranges, coordinate ranges, confidence formats, known satellite codes and numeric fields. Rejected rows are counted by reason and downloadable as CSV.
- **Deduplication.** A record key is a SHA-1 of all normalized fields. Exact duplicates from repeat imports or overlapping windows are stored once, and every occurrence is kept in `provenance`. Records are never merged because their coordinates match. Different platforms or times stay distinct.
- **NRT/SP reconciliation.** Standard processing (SP/archive) supersedes NRT/RT/URT for the same platform and UTC day. Superseded rows are kept with a flag, excluded from all analysis, and counted in the inventory. Record-level matching across streams is not attempted, because positions and attributes can change between processing streams.
- **ZIP safety.** Absolute paths, `..`, drive letters and symlinks are rejected. Entry-count, expanded-size and compression-ratio limits apply. `__MACOSX`, nested ZIPs and non-CSV entries are skipped with warnings.
- **Revision.** The dataset revision increments only when data or coverage change, and every cache key includes it. Re-importing identical data leaves the revision and counts unchanged.

## 7. Patterns, comparison, rankings
- Monthly and annual summaries report detections and FRP per sensor, plus two distinct cell measures: **sum of daily occupied cells** (a cell active on 10 days counts 10 times) and **distinct cells** (counted once per period). Partial months and years are flagged.
- ISO weeks start on Monday, and week 1 contains the first Thursday. ISO years have 52 or 53 weeks, and dates near New Year can belong to the neighbouring ISO year (2024-12-30 is 2025-W01).
- **Year comparison** (e.g. 2024 vs 2023) matches month-days. Feb 29 is excluded and disclosed. A ratio is undefined when the reference is 0. These are descriptive comparisons, not significance tests, and two years cannot show a seasonal shift.

## 8. Baseline eligibility and unusual conditions
This is a conservative **project rule**, not an official NASA standard:
- At least **5 prior comparable years**, each with **≥80 % known coverage** in a **±15-day seasonal window** around the same month-day, and **≥100 reference days** in total. The evaluation year is excluded. Feb 29 maps to Feb 28 in non-leap years. Windows crossing New Year use actual dates.
- When eligible, empirical **P95/P5** thresholds flag descriptive above/below exceedances. Low flags are suppressed when P5 = 0 or coverage is unknown. Ratios to a zero median are undefined, never infinite.
- **With the 2023–2024 sample the baseline is ineligible.** The app says so ("Insufficient history for a robust multi-year baseline …") and offers descriptive comparisons and rankings instead. The algorithm works and is unit-tested, but adequate historical evidence does not yet exist.

## 9. Elevated observed activity (explainable periods)
- **Rule:** ≥ N consecutive UTC days (default 3) on which the selected metric for the selected sensor exceeds the threshold and is ≥ a minimum activity (default 1). Unknown-coverage days **break** a run. They are never bridged, and adjacent unknown days are disclosed with each period.
- **Threshold modes:** within-range percentile (default P90 of known days in the analysis range; needs ≥ 30 known days; relative, not historical), a user-defined activity threshold, or the historical seasonal baseline (only when eligible).
- Every period carries a plain-language reason (dates, duration, threshold, peak). These are project settings, not NASA-validated danger thresholds, and the label is always "Elevated observed activity", never a warning.

## 10. Imagery and dates
- Dated imagery comes from NASA GIBS WMTS corrected-reflectance true colour (VIIRS NOAA-20, MODIS Terra, MODIS Aqua) in EPSG:3857, tile matrix set `GoogleMapsCompatible_Level9`, maximum native zoom 8. Every tile URL contains the selected date explicitly (`…/default/YYYY-MM-DD/…`). The service default date is never used.
- Availability comes from the GIBS DescribeDomains endpoint (cached 24 h), with a bundled snapshot verified on 2026-11-14 as fallback. Terra and NOAA-20 were verified for 2023–2024 only.
- For dates outside a layer's domain the map shows **"Imagery unavailable for this date"**. A nearest-date image appears only after an explicit click and is labelled **SUBSTITUTED**.
- A daily image is assembled from that day's overpasses and is not captured at the instant of each hotspot. With 7- or 30-day fire windows, the fire window and the imagery date are labelled separately. Clouds, smoke or blank imagery do not prove that no fire was present.
- Static basemaps (CARTO / OpenStreetMap) are labelled "not historical conditions". Imagery and basemaps need internet access, and analysis does not.

## 11. AOIs and boundaries
- Named regions use Natural Earth 1:10m admin-0/admin-1 boundaries (public domain), simplified at 0.002°. Sumatra is 8 provinces (Aceh, North Sumatra, West Sumatra, Riau, Jambi, South Sumatra, Bengkulu, Lampung). Kalimantan is the Indonesian Borneo provinces as delineated by Natural Earth, whose East Kalimantan polygon includes North Kalimantan. Riau Islands and Bangka-Belitung are not part of the "Sumatra" region.
- Filtering is an exact point-in-polygon test (Shapely), and **points on the boundary are included**. Custom AOIs can be drawn (rectangle or polygon) or uploaded as GeoJSON Polygon/MultiPolygon. WGS84 is assumed per RFC 7946, and EPSG:3857 is transformed explicitly. Other CRSs, invalid or self-intersecting geometries, antimeridian-crossing shapes and out-of-range coordinates are rejected with a message.
- "All imported observations" is the download bounding box (≈ lon 94.27–142.0, lat −12.0–7.0), which is broader than Indonesia.

## 12. FIRMS API (optional)
Area API: `/api/area/csv/[MAP_KEY]/[SOURCE]/[west,south,east,north]/[DAY_RANGE 1..5]/[DATE]`, where DATE is the first day of the window. Long ranges are split into ≤5-day windows and cached on disk. The documented key limit is 5000 transactions per 10 minutes, and rate-limit responses back off and retry. The key is read only on the server and redacted from every message. **Authenticated live retrieval has not been verified** (no key was available). Behaviour is tested with simulated responses.

## 13. Sources (verified 2026-11-14)
- NASA FIRMS Area API: https://firms.modaps.eosdis.nasa.gov/api/area/ · archive download: https://firms.modaps.eosdis.nasa.gov/download/ · FAQ: https://www.earthdata.nasa.gov/data/tools/firms/faq
- MODIS Collection 6 Active Fire Product User's Guide, Revision B: https://www.earthdata.nasa.gov/sites/default/files/imported/MODIS_C6_Fire_User_Guide_B.pdf
- VIIRS 375 m Active Fire Product User Guide v1.2: https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf
- NASA GIBS API documentation: https://nasa-gibs.github.io/gibs-api-docs/
- Natural Earth (public domain): https://www.naturalearthdata.com/

No journal articles are cited, and no cross-sensor calibration factor is claimed.

## 14. Known limitations
1. Two years of data (2023–2024) cannot support baselines, trends or seasonal-shift claims.
2. Authenticated live FIRMS retrieval is unverified in this build.
3. File-name windows are *declared*, not verified, coverage. The original bounding box of archive files is unknown unless supplied with `--bbox`.
4. Static-source contamination (the VIIRS v1–2 type issue), cloud and smoke obscuration, and overpass timing affect all counts.
5. The likely-gap rule is a heuristic (median ≥ 20 rows/day per import batch). It is disclosed on each affected day.
6. Imagery availability for dates outside 2023–2024 relies on the live DescribeDomains check. The behaviour of GIBS for out-of-range dates was not independently verified, so the app never requests such tiles.
7. The Windows start scripts (`start.bat`/`start.ps1`) were written for Windows but could only be executed on Linux during development (see TEST_RESULTS.md).
