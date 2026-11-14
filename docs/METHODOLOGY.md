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
This is **partial harmonization**: it puts the sensors on common units of organization, but no bias correction, regression calibration or probability surface is applied to the map, calendar, history, elevated-period or export series. Since version 1.1 a separate, optional empirical MODIS–VIIRS calibration is available in the Sensor Workbench (§15). Its output is shown only in that panel and its validation package; it never replaces or alters the per-sensor series described here.

- **Time.** `acq_date` + `acq_time` (HHMM, UTC, zero-padded: `402` → 04:02, `5` → 00:05). A UTC day D is [D 00:00, D+1 00:00). Browser time zones are never applied.
- **Grid.** WGS84 lon/lat, origin (−180°, −90°). Coordinates are quantized to integer 1e-5 degrees (`lon_e5`, `lat_e5`, round-half-even). Cell index: `col = floor((lon_e5 + 18,000,000) / R)`, `row = floor((lat_e5 + 9,000,000) / R)`, where R = cell size × 100,000 (0.1° → 10,000). Cells are half-open [west, east) × [south, north), so a point on a shared edge belongs to the cell to its east or north. Longitude 180 and latitude 90 go to the last column and row. Because integer floor division is used, negative coordinates index correctly (−2.55° lies in the row starting at −2.6°). Cells are not equal-area.
- **Per sensor.** Each cell and day keeps counts per sensor: MODIS (Terra+Aqua, with a Terra/Aqua split) and each VIIRS platform. It also keeps occupied-cell indicators, FRP summaries and day/night counts.
- **Union.** "Cells with detections from any selected sensor" counts a cell once even if several sensors detected it. Its sensitivity changes with sensor availability. **The union exists only for occupied cells.** Raw MODIS and VIIRS detection counts and FRP are never added together anywhere: not in the API, the map colouring, the tables or the exports. The map colours each cell by the primary sensor's own count. Cells detected only by another selected sensor are drawn as grey outlines.

## 4. Quality and type filters
- The default preset is MODIS confidence ≥ 30 and VIIRS nominal/high. This is a *filter choice*, not equivalent detection performance. All valid records are stored, and every result discloses the active filters and the number of rows they removed.
- Type codes, from the MODIS C6 and VIIRS 375 m user guides: 0 presumed vegetation fire, 1 active volcano, 2 other static land source, 3 offshore. The default includes type 0 and records without a type ("unknown/missing type"; FIRMS NRT area files have no type column). Until 1.2 the default was type 0 only, which dropped every NRT row; see §17.
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
- **With the 2023–2024 sample the baseline is ineligible.** The app says so ("Insufficient history for a robust multi-year baseline …") and offers descriptive comparisons and rankings instead.
- **With the full-history archive (2000–2026) the rule is met without any code change.** For Kalimantan in 2023 (occupied cells), MODIS and VIIRS S-NPP are eligible on all 365 days; VIIRS NOAA-20 (data from April 2018) is eligible on 266 days, once five prior years exist for that month-day. The thresholds remain descriptive empirical percentiles, not validated danger levels.

## 9. Elevated observed activity (explainable periods)
- **Rule:** ≥ N consecutive UTC days (default 3) on which the selected metric for the selected sensor exceeds the threshold and is ≥ a minimum activity (default 1). Unknown-coverage days **break** a run. They are never bridged, and adjacent unknown days are disclosed with each period.
- **Threshold modes:** within-range percentile (default P90 of known days in the analysis range; needs ≥ 30 known days; relative, not historical), a user-defined activity threshold, or the historical seasonal baseline (only when eligible).
- Every period carries a plain-language reason (dates, duration, threshold, peak). These are project settings, not NASA-validated danger thresholds, and the label is always "Elevated observed activity", never a warning.

## 10. Imagery and dates
- Dated imagery comes from NASA GIBS WMTS corrected-reflectance true colour (VIIRS NOAA-20, MODIS Terra, MODIS Aqua) in EPSG:3857, tile matrix set `GoogleMapsCompatible_Level9`, maximum native zoom 8. Every tile URL contains the selected date explicitly (`…/default/YYYY-MM-DD/…`). The service default date is never used.
- Availability comes from the GIBS DescribeDomains endpoint (cached 24 h), with a bundled snapshot verified on 2026-11-14 as fallback. Terra and NOAA-20 were verified for 2023–2024 only.
- For dates outside a layer's domain the map shows **"Imagery unavailable for this date"**. A nearest-date image appears only after an explicit click and is labelled **SUBSTITUTED**.
- A daily image is assembled from that day's overpasses and is not captured at the instant of each hotspot. With 7- or 30-day fire windows, the fire window and the imagery date are labelled separately. Clouds, smoke or blank imagery do not prove that no fire was present.
- Static basemaps (Esri Canvas, keyless) are labelled "not historical conditions". Imagery and basemaps need internet access, and analysis does not.

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

No journal articles are cited. The only cross-sensor relationship PyroSync reports is the empirical calibration of §15, fitted on the imported data and published with its held-out errors; it is not a general conversion factor.

## 14. Known limitations
1. The bundled sample (2023–2024) cannot support baselines, trends or seasonal-shift claims. The full-history archive can support baselines; trend or seasonal-shift statements would still need a dedicated statistical analysis, which PyroSync does not perform.
2. Authenticated live FIRMS retrieval is unverified in this build.
3. File-name windows are *declared*, not verified, coverage. The original bounding box of archive files is unknown unless supplied with `--bbox`.
4. Static-source contamination (the VIIRS v1–2 type issue), cloud and smoke obscuration, and overpass timing affect all counts.
5. The likely-gap rule is a heuristic (median ≥ 20 rows/day per import batch). It is disclosed on each affected day.
6. Imagery availability for dates outside 2023–2024 relies on the live DescribeDomains check. The behaviour of GIBS for out-of-range dates was not independently verified, so the app never requests such tiles.
7. The Windows start scripts (`start.bat`/`start.ps1`) were written for Windows but could only be executed on Linux during development (see TEST_RESULTS.md).
8. The MODIS–VIIRS calibration (§15) relies on detections only; satellite coverage is not verified. See [HARMONIZATION_VALIDATION.md](HARMONIZATION_VALIDATION.md) for its measured performance and limits.

## 15. MODIS–VIIRS harmonization (three stages, added in 1.1)
Implementation: `backend/pyrosync/harmonize.py`. API: `/api/harmonization` and `/api/export/harmonization.zip`. CLI: `python -m pyrosync.cli harmonize`. UI: Sensor Workbench → MODIS–VIIRS harmonization, and the Harmonization tab (§16).

**Stage 1 — Spatial standardization.** The same filtered observations as every other panel (dates, exact AOI before aggregation, MODIS confidence, VIIRS confidence, type, day/night) are indexed with the grid rule of §3 at a comparison grid of 0.1° (default), 0.25°, 0.5° or 1°. One MODIS platform set (Aqua by default, Terra or both) and one VIIRS platform (S-NPP by default, NOAA-20 or NOAA-21) are compared. Each sensor keeps its own measurement: the number of its detections in the cell during one observation event (default), or the sum of their FRP (MW).

**Stage 2 — Temporal matching.** Per cell and platform, acquisitions closer than 20 minutes form one *observation event* (normally one overpass; FIRMS times are granule start times). A MODIS event and a VIIRS event in the same cell form a *candidate pair* when their event times (first acquisition) differ by at most the tolerance (default ±30 min; Aqua and S-NPP cross the equator within minutes of each other, NOAA-20 about 50 minutes apart). Pairs are accepted one-to-one in the order (|Δt|, MODIS time, VIIRS time, cell, ids): the result is deterministic and independent of file order.

Positive-detection matching is kept apart from coverage. Events without a partner are classified as *proxy* when the other instrument reported any detection (any quality, any type, inside or outside the AOI) within the evidence radius (default 5°) and the time tolerance, and *no evidence* otherwise. A proxy only shows that the other instrument was imaging the region; it does not show that the cell was inside its swath or cloud-free. **Verified coverage is not established**: that would need swath geolocation and fire/cloud masks (MOD03/MOD14, VNP03/VNP14, VJ103/VJ114), which FIRMS active-fire CSVs do not contain. One-sided units enter the model only when the user selects "+ proxy one-sided" (they then count as 0 for the missing sensor); "no evidence" units never do.

**Stage 3 — Statistical calibration.** For each comparison unit i (default: candidate matches only),

ln(1 + M_i) = α + β ln(1 + V_i) + ε_i,  M̂_i = max(0, exp(α̂ + β̂ ln(1 + V_i)) − 1),

where M is the MODIS and V the VIIRS measurement. α and β are estimated by ordinary least squares on the training period only. Units are ordered by time and the last 20 % (default; 10 % or 30 % selectable, or an explicit `--split-date`) form the held-out test period; all units of one UTC day fall on the same side. On the test period the calibrated estimate is compared with the unadjusted VIIRS value (M̂ = V) using MAE, RMSE and MBE (mean of prediction − MODIS), and the percentage improvement 100 × (unadjusted − calibrated) / unadjusted (absolute values for MBE). A constant equal to the training-period MODIS mean is reported for context. Coefficients come with classical standard errors and 95 % normal-approximation intervals, which assume independent units and are therefore optimistic. The log-model back-transformation estimates a conditional median; the Duan smearing factor is reported but not applied. At least 30 training and 10 test units are required; otherwise the panel says the model was not fitted and why.

**Interpretation.** MODIS is the reference *scale*, chosen for continuity with its longer record; it is not ground truth. A calibrated value is the expected MODIS-scale measurement for a cell and overpass given the VIIRS measurement; it does not make the sensors equivalent and does not add fires that neither sensor detected. Coefficients depend on AOI, period, filters, grid and sensor pair and must be re-fitted, not transferred.


## 16. Applying the calibration: the Harmonization tab (added in 1.2)
Implementation: `backend/pyrosync/calibration.py` (application) and `harmonize.assess_validity` (rules). API: `/api/harmonization/map`, `/api/harmonization/errors`, `/api/harmonization/series`. UI: the **Harmonization** tab in the main navigation. Audit: `python -m pyrosync.cli harmonize-audit` → [harmonization/AUDIT/AUDIT.md](harmonization/AUDIT/AUDIT.md).

**One run, many views.** The tab computes one run of §15 for the chosen region, period, filters and sensor pair. The report, the map, the error map and the time series are all derived from the same events, matches and coefficients (`calibration.core`), so their numbers agree. Nothing is written to the database: original observations stay unchanged and keep feeding the calendar, history, Explore map and Sensor Workbench.

**Unit-level validity rules (`pyrosync-validity-1.0`, a project rule, not a NASA standard).** A run may be *applied* (calibrated values shown) only when all of these hold, each measured on the held-out period: (1) the model was fitted; (2) the measurement is detection counts (FRP sums are evaluated but never applied, because the log-log model did not reduce held-out FRP errors on the full archive); (3) at least 100 held-out units; (4) held-out MAE, RMSE and |MBE| below unadjusted VIIRS; (5) held-out MAE and RMSE below the better of two constants fitted on the training period (MODIS mean and MODIS median), i.e. the VIIRS value adds information beyond the overall level; (6) the lower bound of the 95 % interval of β above 0. Passing means "beat the simple alternatives on later data for this configuration", not an independent validation.

**Map.** For the selected UTC day or trailing 7/30-day window, each comparison cell shows the original MODIS detections (selected MODIS platforms), the original VIIRS detections, the stage-2 matches (|Δt| per pair) and, for a run that passes the rules, an *experimental MODIS-scale estimate*: Σ over the VIIRS observation events in the cell of M̂ = max(0, exp(α̂ + β̂ ln(1 + V)) − 1). It is drawn with its own purple ramp and labelled as an estimate on the grid; no hotspot points are created. Each observation event is assigned to the UTC day of its first acquisition; a match is shown on its MODIS event day. The estimate can be limited to events *in the model domain* (default: VIIRS events of the kind the model was fitted on, i.e. matched events for "Matched only") or extended to all VIIRS events. Outside the domain the matched-only model predicts what MODIS would have counted had it detected the fire, which overstates MODIS-scale totals. Windows are labelled *training (in-sample)*, *held-out* or *mixed* relative to the split date. VIIRS values larger than the largest training value are counted as extrapolation.

**Calibration error map.** The held-out units are grouped into region cells that are integer multiples of the comparison grid (0.1°, 0.5°, 1° or 2° for a 0.1° grid; 0.25° is not allowed there because 0.1° cells would straddle its edges). For each region: number of held-out and training units, calibrated and unadjusted MAE, RMSE, MBE and the MAE improvement. A region is *validated* when it has at least the chosen minimum of held-out units (5, 10, 20 default, 30 or 50); otherwise it is marked *too few held-out units*. Regions with VIIRS activity but no held-out unit are marked *no held-out units*. On the calibrated map layer, cells in regions that are not validated are drawn faded with a dashed edge. The minimum is a display rule, not a significance test.

**Original vs calibrated time series and the daily-total gate.** The tab plots the original daily (or monthly) MODIS and VIIRS detections of the selected platforms (identical to the app's per-sensor daily series; days with unknown coverage are left empty, and monthly sums use only days on which both sensors have a known state). Unit-level validity does **not** imply that *sums* of estimates reproduce MODIS-scale activity, because a series adds up estimates over all events, including events the model was not fitted on. The calibrated line is therefore drawn only when a second set of rules also holds on the held-out days: at least 30 days with both sensors known; Σ calibrated / Σ MODIS between 0.8 and 1.25; daily-total MAE and RMSE below unadjusted VIIRS; and below a constant equal to the training-period mean daily MODIS total. The check table is always shown. On the full archive no configuration tested passes this gate (see [HARMONIZATION_VALIDATION.md](HARMONIZATION_VALIDATION.md), "Application"), so the existing calendar and history pages correctly continue to use original data.

## 17. AOI Insights (added in 1.3)
Implementation: `backend/pyrosync/insights.py`, `climate.py`, `live.py`. API: `/api/insights/*`, `/api/export/hotspots.{csv|geojson|kml}`, `/api/export/insights.zip`. UI: the **AOI Insights** tab. CLI: `python -m pyrosync.cli insights --aoi … --series … --as-of … --out …`. Method version `pyrosync-insights-1.0`.

**What it is and is not.** A description of OBSERVED satellite detections for one area of interest and one sensor series (MODIS Terra + Aqua, or one VIIRS satellite; series are never added together). It is not a forecast, not a fire-danger rating, not a probability of fire and not an official warning. Clouds, smoke and overpass timing hide some fires, so few detections do not prove few fires. Every response carries this disclaimer.

**Shared definitions.**
- *History*: every day from the first imported day to the *as of* day, for the AOI, filters and one series. The year of the as-of day is the *focus year*.
- *Known day*: coverage state `detections` or `zero_reported` (§5). Unknown days are never counted as zero.
- *Complete (eligible) year*: at least 80 % of its days known. *Reference years*: complete years other than the focus year. Every statistic needs at least 5 of them, otherwise the section says "not enough history" and nothing is estimated.
- *Week bin*: (day of year − 1) // 7, capped at 51 (the last bin holds 8–9 days). A week value is the mean per known day and needs at least 5 known days.
- *Rows without a fire type* (changed in 1.3 for every tab): FIRMS near-real-time (NRT) area files carry no `type` column. The default type filter is now presumed vegetation fire **plus** "unknown/missing type"; with the 1.2 default (type 0 only) every NRT row was dropped and recent weeks read as zero fire (for example Kalimantan, September–November 2026). Static sources and volcanoes cannot be removed from rows without a type. Users can still untick "unknown/missing type" in Filters; rows that have a type are filtered exactly as selected.

**A1 Fire regime.** Per week bin: median and 10th–90th percentile over reference years, with the focus year. Season start, peak and end of a year are the days on which its cumulative total reaches 10 %, 50 % and 90 % (years with fewer than 10 detections have none); the regime reports their median and 10th–90th percentiles. Variability: mean, median, min, max and coefficient of variation of annual totals.

**B4 Season tracker.** Cumulative total of known days since 1 January on a 365-day index (29 February shares 28 February's index), for the focus year and every reference year; the envelope is the 10th, 50th and 90th percentile per day. Status: the focus year's cumulative total at the as-of day compared with the reference years at the same index ("higher than k of n"), banded at the 10th, 25th, 75th and 90th percentile ("among the lowest", "below", "within", "above the usual range", "among the highest on record").

**B2 Unusual conditions (robust score).** z = (ln(1 + x) − median ln(1 + r)) / max(1.4826 · MAD, floor), where r are the reference values and MAD is the median absolute deviation of ln(1 + r). Daily references: known days within ±15 days of the same date in every EARLIER complete year whose window is at least 80 % known (at least 5 years). Weekly: the same week bin in earlier complete years. Cells (map): detections in a window of up to 93 days compared with the same window in every earlier year whose window is at least 80 % known. Floors (log units): day 0.25, week 0.25, cell 0.5. Bands: z ≥ 3 exceptional, ≥ 2 well above normal, ≥ 1 above normal, otherwise normal; ≤ −1 below normal. Guard rails: a positive band also needs the value above the reference 75th percentile and at least 3 above the reference median (so one or two detections in a usually empty season stay normal); a negative band needs a reference median above 0 and the value below the reference 25th percentile. Each score also reports the share of reference values below the value (`higher_than_pct`). Median and MAD are not pulled up by a few extreme years; because reference windows contain earlier extreme seasons, a very large day in a month that often burns may score only "above normal" while being among the largest on record: the percentile share and the critical periods (C1) show that side.

**C1 Critical periods.** At least 3 consecutive days with activity at or above max(threshold, 1), where the threshold for a year is the chosen percentile (85, 90 default, 95) of ALL known days in all OTHER complete years (leave one year out, so no year sets its own threshold; at least 5 other years). Unknown days break a period. Periods are ranked by detections above the threshold. "Critical" means absolutely high activity for this area; "unusual" (B2) means unusual for the time of year.

**C2 Readiness calendar.** For each week bin: in how many complete years at least one day of that week was inside a critical period. A summary of the past, not a prediction.

**A2 Recurrence.** For each grid cell: the number of complete years with at least one detection (detections in incomplete years are not counted), the share of years, the longest run of consecutive fire years, first and last fire year. A cell is *chronic* when the share is at least the chosen value (25 %, 40 % default, 60 %). The hotspot exports (CSV, GeoJSON, KML) list the top cells by years with fire; a cell is a grid square, not a fire location.

**D2/F2 Years and climate background.** Per complete year: detections, July–October detections, critical days and periods, rank. Climate phases from NOAA data bundled in `backend/pyrosync/resources/climate/` (SHA-256 checksums tested): ENSO El Niño if the mean ONI of JAS and ASO is ≥ +0.5 °C, La Niña if ≤ −0.5 °C (NOAA CPC Oceanic Niño Index); IOD positive if the mean DMI of August–October is ≥ +0.4 °C, negative if ≤ −0.4 °C (NOAA PSL Dipole Mode Index, HadISST1.1, marked preliminary by NOAA). These are project thresholds describing the dry-season background, not NOAA's official episode definitions. Grouping years by phase shows *analog years*: what happened in a handful of past seasons with a similar background; not a forecast.

**F1 Compare areas.** The same measures for 2–6 AOIs, each with its own history and thresholds; detections per 1,000 km² use an approximate area (cosine-latitude scaling of the AOI polygon). Critical days compare how often an area exceeds its own high-activity level.

**D1 Status now.** On request only, the server fetches the last 3–10 days of FIRMS NRT detections for the AOI's bounding box (the key stays on the server; responses are cached in memory for 30 minutes and never stored), keeps rows inside the AOI polygon and passing the filters (rows without a type pass only when "unknown/missing type" is selected, the default), and scores each day and the window total with B2 against the archive. NRT data are provisional and the latest day is usually incomplete.

**E1 Briefing.** A printable one-page summary in English or Indonesian built only from the numbers above, with the disclaimer at the top. **G1 Package.** `insights.zip` holds JSON and CSV for the regime, critical periods, years and recurrence, a manifest with every setting and a README; the CLI writes the same package.
