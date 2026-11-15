# Multi-sensor historical fusion (added in 1.5)

Method `pyrosync-fusion-1.0`, gate `pyrosync-fusion-gate-1.0`. Implementation: `backend/pyrosync/fusion.py`.
Generated validation reports (real FIRMS archive, no synthetic data): [`docs/harmonization/FUSION/`](harmonization/FUSION/FUSION.md),
reproduced with `python -m pyrosync.cli harmonize-fusion --out docs/harmonization/FUSION`.

The fused series is an **experimental, project-defined index**. It is not a NASA product and has no NASA validation. In this
document, "validated" means only "passes the PyroSync rules below on later, held-out data, with MODIS Aqua as the reference scale".

## 1. What it answers

How active was fire in an area on each day from 2000 to now, on **one consistent scale**, while the set of satellites changes:
Terra (from 2000-11), Aqua (2002-07), Suomi NPP (2012-01), NOAA-20 (2018-04) and NOAA-21 (2023-03).

Raw detection counts cannot be compared across that period. A VIIRS 375 m pixel is about 20 times smaller in area than a MODIS
1 km pixel, so one fire gives many more VIIRS detections. On the full Indonesia archive, the plain mean of the raw counts is
7.3 times the Aqua total on held-out days. Adding the satellites' counts would be worse still, and would double-count fires that
two satellites see. **PyroSync never adds raw detections from different satellites.**

## 2. Reference scale

**MODIS Aqua detections per UTC day in the AOI** (unit: "MODIS-Aqua-equivalent detections per day").

Why Aqua:

- It is the longest single-platform record with an afternoon overpass. It runs from 2002-07-04 to today, in overlap with every VIIRS satellite.
- The 1.4 day-level ratio was validated against Aqua.
- Terra was tested as the reference (run T, below) and fails. Every one of its four pairs fails the 1.4 gate, with year-by-year
  ratios from 0.53× to 1.92×. Terra's morning overpass sees a different part of the diurnal fire cycle, and its orbit has been
  drifting since 2020.
- A composite reference (for example the Terra + Aqua mean) is not used. It cannot be defined the same way before 2002-07, when
  only Terra exists, and it would inherit Terra's drift.

The reference is an **observational scale, not ground truth**. MODIS misses small and short fires and fires under cloud or
smoke, and its own errors stay in the target. Aqua's overpass has drifted later since it left the A-Train in 2022. The
year-by-year checks show whether that has changed the ratios (2023–2025: 0.87–0.94×).

## 3. Estimator

For platform p on day d with detections X_p,d:

    c_p = Σ_train Aqua_d / Σ_train X_p,d          (the 1.4 day-level ratio, pairwise chronological split, unchanged)
    F_d = mean over eligible platforms p that are KNOWN on day d of c_p · X_p,d      (c_Aqua = 1)

- **Calibrated average, not a sum.** Each satellite is first converted to the Aqua scale, and then the available estimates are
  averaged. When Aqua is known, it takes part with c = 1.
- **Eligibility.** A platform is used only if its pair with Aqua passes the unchanged 1.4 aggregate gate on the Indonesia-wide
  record with the same filters. Eligibility is a property of the instrument pair, decided on the largest record. Smaller AOIs
  (regions, drawn polygons, circles) inherit it, but **fit their own ratios on their own training days** (at least 180 known
  overlap days). On the full archive, S-NPP, NOAA-20 and NOAA-21 are eligible. **Terra is not.** Its pair fails, with 13 of
  23 years inside 0.8–1.25× and a range of 0.53–1.64×.
- **Known day.** A platform is known on day d only when all three hold:
  - its series status is `detections` or `zero_reported` (inside an imported request interval);
  - d lies inside the platform's own record (first to last imported day);
  - d is not a platform gap day, meaning no row anywhere in the import while that platform's median day has 20 or more rows.
- **Missing is not zero.** A day with no known platform has no fused value. It is `unknown`, or `outside_range` beyond the
  import, and is drawn as a gap. A day with known platforms and no detections is a reported zero (0). Monthly and yearly sums
  use only days that have a fused value, and they report how many days that is (`known_days`).
- **Independent of the display range.** The model is always fitted on the whole imported record for the AOI and quality
  filters. Changing the date range or the platform checkboxes never changes the coefficients.

Consequence on the real archive: **2000-11-01 to 2002-07-03 has no fused value**, because only Terra exists then and Terra is
not eligible. The per-sensor MODIS series is unchanged and still covers that period.

## 4. Validation design (all on real data)

- **Leave-reference-out.** The fused estimate **without Aqua**, with each ratio fitted only on days before the evaluation
  period, is compared with the observed Aqua totals. Aqua is never an input to its own prediction.
- **Chronological hold-out.** A common split for the fused series: the last 20 % of days with activity and a known Aqua state.
  The ratios used for the test are fitted before the split.
- **Baselines on the same days:**
  - the uncalibrated mean of the same platforms' raw counts;
  - a constant equal to the training-period mean Aqua total;
  - each single sensor with its own ratio.
- **Rolling origin by calendar year.** Every year Y is predicted from ratios fitted on all known days before 1 January Y.
- **Additional checks:**
  - **high-fire days:** held-out days with Aqua at or above the training 90th percentile;
  - **monthly** consistency over held-out months with at least 20 days;
  - **seasonal** consistency: the rolling-origin estimates summed by calendar month;
  - **transitions:** the level, 365 days either side of the day a platform joins (at least 60 days each side);
  - **missing-data** counts;
  - **regional** cells of 0.5°, 1° and 2°.

### Gate (project rules, not a NASA standard)

| Check | Rule |
|---|---|
| days | ≥ 30 held-out days with a known Aqua state and a fused estimate |
| level | held-out Σ fused / Σ Aqua within 0.8–1.25× |
| beats_unadjusted | held-out daily MAE **and** RMSE below the raw-count mean |
| beats_constant | held-out daily MAE **and** RMSE below the training-mean constant |
| roll_years | ≥ 3 rolling-origin years |
| roll_share | ≥ 80 % of those years within 0.8–1.25× |
| roll_hard | no year outside 0.67–1.5× |
| high_activity | ≥ 10 high-fire held-out days, total within 0.8–1.25× |
| transitions | every testable join step (after / before, without Aqua) within 0.8–1.25× |

Status shown to users:

- **passes**: the AOI's own fusion passes every check. Its own coefficients are used.
- **not_validated**: tested and failed. Its own coefficients are used, labelled "Experimental: fails the project's validation
  rules for this area".
- **insufficient**: cannot be tested, for example a small area with few active days or no eligible platform. The Indonesia-wide
  coefficients are used, labelled "Insufficient validation data". This is never presented as validated for that area.

## 5. Results on the full archive (types 0 + unknown, default confidence filters)

| Run | AOI | Eligible (c) | Held-out Σ/Σ | MAE fused / raw mean / constant | Rolling years in band | Gate | Regional 0.5° / 1° / 2° within |
|---|---|---|---|---|---|---|---|
| N | Indonesia | S-NPP 0.1322, NOAA-20 0.1385, NOAA-21 0.1555 | 0.963 | 35.7 / 515.8 / 132.4 | 14 of 14 | **passes** | 285/853 / 114/319 / 47/119 |
| K | Kalimantan | S-NPP 0.1483, NOAA-20 0.1617, NOAA-21 0.1917 | 1.014 | 33.7 / 258.9 / 71.3 | 10 of 14 | not validated | 74/194 / 29/63 / 14/21 |
| S | Sumatra | S-NPP 0.1219, NOAA-20 0.1379, NOAA-21 0.1558 | 0.866 | 12.0 / 87.7 / 40.0 | 10 of 14 | not validated | 64/178 / 28/57 / 11/19 |
| T | Indonesia, **Terra** as reference (sensitivity only) | none | — | — | — | insufficient (no pair passes against Terra) | — |

Indonesia (run N): split 2022-01-08, with 7,059 training days and 1,737 held-out days.

- **Error and level.** MAE 35.7 and RMSE 110.6 detections per day, against 515.8 / 1,411.9 for the raw mean and
  132.4 / 218.6 for the constant.
- **High-fire days.** 112 days at 0.91×.
- **Years.** All 14 rolling-origin years fall within 0.8–1.25×. The worst is 2015 at 1.24×.
- **Transitions.** The NOAA-20 join step is 1.00× and the NOAA-21 step 0.95×. The S-NPP join (2012-01-20) is not testable
  without Aqua, because no other eligible platform exists before it.
- **Monthly and seasonal.** 75 % of held-out months and 9 of 12 calendar months are within 0.8–1.25×. February, March and
  October are high, at 1.28–1.37×.

Kalimantan and Sumatra fail two checks each. Only 10 of 14 years fall in the band. On high-fire days the fusion underestimates,
at 0.78× in Kalimantan and 0.53× in Sumatra. Both are therefore shown as experimental.

**What the fusion does and does not improve.** On the same held-out days, the fused series has about the same error as the best
single-sensor ratio. For Indonesia: S-NPP alone 35.4 MAE against 35.5 for fusion, and NOAA-20 alone 37.0 against 35.7. The
benefit is **continuity**. One series spans 2002 to now without a jump when a satellite joins or leaves, and it keeps a value on
days when one satellite is missing. The fusion is **not** more accurate than the best single sensor on days when that sensor exists.

**Regional agreement is low.** At 1°, only 36 % of tested Indonesian cells are within 0.8–1.25× (114 of 319). The AOI-level
result does not make every region accurate, so the map cells are labelled experimental at every grid size.

## 6. Where it appears in the app

- **Harmonized Calendar** (main navigation): opens on the fused series. A banner shows the status, the sensors and their
  coefficients, plus a whole-record chart.
- **Explore → Harmonized layer:** the "Experimental Harmonized Activity Index" per display-grid cell. A cell is the sum over the
  window's days of Σ_p (c_p / n_d) · X_p,cell,d, using the same weights as the AOI's fused daily total, so the cells add up to that
  total. Single cells are not validated at any grid size. The original detections stay available as "Detections" (points with a
  FIRMS-style attribute popup) and as per-sensor cells.
- **Historical Patterns, elevated periods, weekly patterns, rankings and AOI Insights:** "Harmonized (all sensors)" is one more
  series, for detections only. Cell-level parts of Insights (recurrence, cell anomaly) use the Aqua reference sensor, so raw
  counts of different satellites are never mixed there either. The live "now vs history" view needs one sensor's NRT feed and
  refuses the fused series (HTTP 422).
- **Harmonization diagnostics → Multi-sensor fusion:** the pair table, held-out tables, rolling-origin chart, transitions, gate
  checks, regional check and the export `fusion.zip`.

API:

- `/api/fusion` (model and validation);
- `/api/fusion/series?agg=day|month|year`;
- `/api/fusion/map?date&mode=1|7|30&bbox`;
- `/api/fusion/regions?grid_deg=0.5|1|2&min_days=5|10|20|30|50`;
- `/api/daily?fused=true`;
- `/api/export/fusion.zip`.

## 7. Limitations

- **Coverage is not verified.** Swath, cloud and smoke are not modelled. A reported zero is not proof of a clear-sky observation.
- **The reference has its own errors**, including the Aqua overpass drift since 2022.
- **2000-11 to 2002-07 has no fused value** (Terra-only period, Terra not eligible).
- The ratios are fitted per AOI on daily totals. They are not a pixel-level or per-fire correction, and FRP is not fused.
- Burned area is not estimated. FIRMS points are never converted into burned-area polygons.
- The gate bands (0.8–1.25×, 0.67–1.5×, 80 %, 90th percentile, 20 % hold-out) are project decisions, not taken from the literature.
