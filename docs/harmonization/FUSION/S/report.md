# Run S: Sumatra (reference: MODIS Aqua)

Method `pyrosync-fusion-1.0`, gate `pyrosync-fusion-gate-1.0`, dataset revision 1.
AOI `region:sumatra`; record 2000-11-01 → 2026-11-14; filters {'start': '2000-11-01', 'end': '2026-11-14', 'platforms': ['Terra', 'Aqua', 'N20', 'N21', 'SNPP'], 'modis_min_conf': 30, 'viirs_conf': ['nominal', 'high'], 'types': ['0', 'unknown'], 'daynight': ['D', 'N'], 'aoi': 'region:sumatra'}.

Reference scale: MODIS Aqua active-fire detections per UTC day in the AOI. Aqua is the longest single-platform MODIS record with an afternoon overpass, the one the 1.4 day-level ratio was validated against. It is a reference observational scale, not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target. Aqua's overpass has drifted later since it left the A-Train in 2022; the year-by-year checks show whether that changes the ratios.

Equation: F_d = mean over eligible platforms p known on day d of c_p · X_p,d;  c_Aqua = 1,  c_p = Σ_train Aqua / Σ_train p (1.4 day-level ratio, pairwise chronological split).

## Pairwise calibration against Aqua (1.4 rules, unchanged)

| Platform | c (95 % bootstrap) | overlap days | held-out ratio | rolling years within 0.8–1.25× | pair gate | eligible |
|---|---|---|---|---|---|---|
| Terra (MODIS) | 2.0375 (1.8820–2.2154) | 8,702 | 1.27 | 10 of 23 (0.71–1.59) | not_validated | no |
| Suomi NPP (VIIRS) | 0.1219 (0.1088–0.1374) | 5,270 | 0.82 | 8 of 14 (0.68–1.41) | not_validated | no |
| NOAA-20 (VIIRS) | 0.1379 (0.1316–0.1491) | 3,081 | 0.95 | 7 of 8 (0.79–1.06) | not_validated | no |
| NOAA-21 (VIIRS) | 0.1558 (0.1451–0.1733) | 1,341 | 1.09 | 3 of 3 (0.86–1.10) | passes | yes |

## Fused series validation (leave-reference-out)

Leave-reference-out: the fused estimate WITHOUT Aqua, with each ratio fitted only on days before the evaluation period, is compared with the observed Aqua totals. Aqua is never an input to its own prediction.

Split 2022-06-18 (chronological hold-out: the last 20% of days with activity and a known Aqua state); 7,204 Aqua training days; 1,592 held-out days ['2022-06-18', '2026-11-14']. Training ratios: SNPP 0.1212, N20 0.1336, N21 —.

| Held-out daily totals | Σ est / Σ Aqua | MAE | RMSE | MBE |
|---|---|---|---|---|
| fusion_leave_reference_out | 0.87 | 12.0 | 30.7 | -2.0 |
| raw_unadjusted_mean | 6.79 | 87.7 | 232.5 | 87.6 |
| constant_train_mean | 2.71 | 40.0 | 50.9 | 25.9 |

| Same held-out days, single sensor vs fusion | days | single-ratio Σ/Σ | single MAE | fusion Σ/Σ | fusion MAE |
|---|---|---|---|---|---|
| SNPP | 1528 | 0.82 | 12.0 | 0.87 | 12.0 |
| N20 | 1586 | 0.91 | 12.3 | 0.86 | 12.0 |

High-fire days (Aqua ≥ 111): 52 days, 0.53×.
Monthly consistency: 52 held-out months; share within 0.8–1.25×: 42%.
Seasonal consistency (rolling-origin, by calendar month): share within 0.8–1.25×: 67% (1.02, 1.29, 1.34, 0.81, 0.74, 1.15, 0.92, 0.97, 1.11, 1.36, 1.06, 0.84).

| Year | contributors (no Aqua) | test days | Σ est / Σ Aqua | MAE | constant MAE |
|---|---|---|---|---|---|
| 2013 | SNPP | 362 | 1.19 | 31.3 | 65.6 |
| 2014 | SNPP | 363 | 1.25 | 48.1 | 72.3 |
| 2015 | SNPP | 364 | 1.41 | 53.4 | 75.8 |
| 2016 | SNPP | 366 | 0.85 | 9.6 | 45.2 |
| 2017 | SNPP | 362 | 0.77 | 5.3 | 45.1 |
| 2018 | SNPP | 364 | 0.92 | 7.9 | 42.7 |
| 2019 | SNPP, N20 | 363 | 1.00 | 25.2 | 56.8 |
| 2020 | SNPP, N20 | 349 | 0.81 | 3.9 | 41.5 |
| 2021 | SNPP, N20 | 358 | 0.73 | 4.1 | 39.0 |
| 2022 | SNPP, N20 | 344 | 0.87 | 3.7 | 38.5 |
| 2023 | SNPP, N20 | 361 | 0.91 | 12.2 | 38.2 |
| 2024 | SNPP, N20, N21 | 362 | 0.82 | 7.0 | 34.7 |
| 2025 | SNPP, N20, N21 | 359 | 0.79 | 8.1 | 34.3 |
| 2026 | SNPP, N20, N21 | 316 | 0.99 | 28.3 | 46.8 |

| Platform joins | step without Aqua (before → after) | step with Aqua |
|---|---|---|
| SNPP 2012-01-20 | not testable | 0.89× |
| N20 2018-04-01 | 1.16× (0.85 → 0.99) | 1.07× |
| N21 2023-03-01 | 1.10× (0.88 → 0.97) | 1.06× |

Missing data: 636 of 9,510 record days have no known platform; Aqua unknown on 714 days.

**Fusion gate: not_validated** — Experimental: the fused series does not pass the project's validation rules for this area

- ✔ Enough held-out days: 1,592 days (At least 30 held-out days with a known Aqua state and a fused estimate.)
- ✔ Total level close to Aqua: Σ fused / Σ Aqua = 0.87 (Held-out total between 0.8× and 1.25× the Aqua total.)
- ✔ Better than averaging raw counts: MAE 12.0 vs 87.7; RMSE 30.7 vs 232.5 (Held-out daily MAE and RMSE below the uncalibrated mean of the same platforms' raw counts.)
- ✔ Better than a constant: MAE 12.0 vs 40.0; RMSE 30.7 vs 50.9 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily Aqua total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to Aqua: 10 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2015: 1.41× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to Aqua: 52 days, 0.53× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)
- ✔ No jump when a satellite joins: N20 1.16×, N21 1.10× (For every platform joining the record, the before/after level step of the fused estimate (without Aqua) is within 0.8–1.25×. A platform without a full year on both sides is not testable and does not fail the check.)

## Regional check (1.0° cells, ≥ 20 active held-out days)

28 cells within 0.8–1.25×, 29 outside, 10 with too few days (share within: 49%).

Per region cell, over held-out days with a known Aqua state: Σ fused estimate without Aqua (training ratios of the AOI) / Σ Aqua detections. The AOI-level result does not make every region accurate; this shows where it holds.

Coverage: Satellite observation coverage (swath, cloud, smoke) is not verified. A day is 'known' when the sensor's record and an imported request interval cover it; a known day with no detection is a reported zero, not proof of a clear-sky observation.
