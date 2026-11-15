# Run N: Indonesia (reference: MODIS Aqua)

Method `pyrosync-fusion-1.0`, gate `pyrosync-fusion-gate-1.0`, dataset revision 1.
AOI `region:indonesia`; record 2000-11-01 → 2026-11-14; filters {'start': '2000-11-01', 'end': '2026-11-14', 'platforms': ['Terra', 'Aqua', 'N20', 'N21', 'SNPP'], 'modis_min_conf': 30, 'viirs_conf': ['nominal', 'high'], 'types': ['0', 'unknown'], 'daynight': ['D', 'N'], 'aoi': 'region:indonesia'}.

Reference scale: MODIS Aqua active-fire detections per UTC day in the AOI. Aqua is the longest single-platform MODIS record with an afternoon overpass, the one the 1.4 day-level ratio was validated against. It is a reference observational scale, not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target. Aqua's overpass has drifted later since it left the A-Train in 2022; the year-by-year checks show whether that changes the ratios.

Equation: F_d = mean over eligible platforms p known on day d of c_p · X_p,d;  c_Aqua = 1,  c_p = Σ_train Aqua / Σ_train p (1.4 day-level ratio, pairwise chronological split).

## Pairwise calibration against Aqua (1.4 rules, unchanged)

| Platform | c (95 % bootstrap) | overlap days | held-out ratio | rolling years within 0.8–1.25× | pair gate | eligible |
|---|---|---|---|---|---|---|
| Terra (MODIS) | 2.3472 (2.1510–2.5673) | 8,702 | 1.23 | 13 of 23 (0.53–1.64) | not_validated | no |
| Suomi NPP (VIIRS) | 0.1322 (0.1227–0.1421) | 5,270 | 0.99 | 14 of 14 (0.81–1.24) | passes | yes |
| NOAA-20 (VIIRS) | 0.1385 (0.1328–0.1478) | 3,081 | 1.06 | 8 of 8 (0.86–1.11) | passes | yes |
| NOAA-21 (VIIRS) | 0.1555 (0.1443–0.1705) | 1,341 | 1.20 | 3 of 3 (0.94–1.20) | passes | yes |

## Fused series validation (leave-reference-out)

Leave-reference-out: the fused estimate WITHOUT Aqua, with each ratio fitted only on days before the evaluation period, is compared with the observed Aqua totals. Aqua is never an input to its own prediction.

Split 2022-01-08 (chronological hold-out: the last 20% of days with activity and a known Aqua state); 7,059 Aqua training days; 1,737 held-out days ['2022-01-08', '2026-11-14']. Training ratios: SNPP 0.1311, N20 0.1328, N21 —.

| Held-out daily totals | Σ est / Σ Aqua | MAE | RMSE | MBE |
|---|---|---|---|---|
| fusion_leave_reference_out | 0.96 | 35.7 | 110.6 | -3.0 |
| raw_unadjusted_mean | 7.30 | 515.8 | 1,411.9 | 515.8 |
| constant_train_mean | 1.47 | 132.4 | 218.6 | 38.2 |

| Same held-out days, single sensor vs fusion | days | single-ratio Σ/Σ | single MAE | fusion Σ/Σ | fusion MAE |
|---|---|---|---|---|---|
| SNPP | 1673 | 0.96 | 35.4 | 0.97 | 35.5 |
| N20 | 1731 | 0.97 | 37.0 | 0.96 | 35.7 |

High-fire days (Aqua ≥ 351): 112 days, 0.91×.
Monthly consistency: 57 held-out months; share within 0.8–1.25×: 75%.
Seasonal consistency (rolling-origin, by calendar month): share within 0.8–1.25×: 75% (1.06, 1.28, 1.37, 0.99, 0.95, 1.16, 0.91, 0.92, 1.05, 1.28, 1.10, 1.01).

| Year | contributors (no Aqua) | test days | Σ est / Σ Aqua | MAE | constant MAE |
|---|---|---|---|---|---|
| 2013 | SNPP | 362 | 1.07 | 44.0 | 140.3 |
| 2014 | SNPP | 363 | 1.19 | 75.8 | 168.7 |
| 2015 | SNPP | 364 | 1.24 | 95.6 | 253.9 |
| 2016 | SNPP | 366 | 0.90 | 19.0 | 120.7 |
| 2017 | SNPP | 362 | 0.94 | 13.0 | 118.4 |
| 2018 | SNPP | 364 | 0.94 | 21.9 | 115.1 |
| 2019 | SNPP, N20 | 363 | 1.07 | 40.1 | 158.1 |
| 2020 | SNPP, N20 | 349 | 0.98 | 11.9 | 111.7 |
| 2021 | SNPP, N20 | 358 | 0.94 | 10.3 | 107.7 |
| 2022 | SNPP, N20 | 344 | 0.97 | 8.8 | 104.4 |
| 2023 | SNPP, N20 | 361 | 0.90 | 31.7 | 116.2 |
| 2024 | SNPP, N20, N21 | 362 | 0.87 | 20.8 | 96.0 |
| 2025 | SNPP, N20, N21 | 359 | 0.94 | 16.2 | 94.8 |
| 2026 | SNPP, N20, N21 | 316 | 1.11 | 111.5 | 244.3 |

| Platform joins | step without Aqua (before → after) | step with Aqua |
|---|---|---|
| SNPP 2012-01-20 | not testable | 0.92× |
| N20 2018-04-01 | 1.00× (0.97 → 0.96) | 0.99× |
| N21 2023-03-01 | 0.95× (1.00 → 0.95) | 0.96× |

Missing data: 636 of 9,510 record days have no known platform; Aqua unknown on 714 days.

**Fusion gate: passes** — Passes the project's fusion validation rules (leave-reference-out, chronological and year-by-year)

- ✔ Enough held-out days: 1,737 days (At least 30 held-out days with a known Aqua state and a fused estimate.)
- ✔ Total level close to Aqua: Σ fused / Σ Aqua = 0.96 (Held-out total between 0.8× and 1.25× the Aqua total.)
- ✔ Better than averaging raw counts: MAE 35.7 vs 515.8; RMSE 110.6 vs 1411.9 (Held-out daily MAE and RMSE below the uncalibrated mean of the same platforms' raw counts.)
- ✔ Better than a constant: MAE 35.7 vs 132.4; RMSE 110.6 vs 218.6 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily Aqua total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✔ Most years close to Aqua: 14 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2015: 1.24× (No rolling-origin year outside 0.67–1.5×.)
- ✔ High-fire days close to Aqua: 112 days, 0.91× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)
- ✔ No jump when a satellite joins: N20 1.00×, N21 0.95× (For every platform joining the record, the before/after level step of the fused estimate (without Aqua) is within 0.8–1.25×. A platform without a full year on both sides is not testable and does not fail the check.)

## Regional check (1.0° cells, ≥ 20 active held-out days)

114 cells within 0.8–1.25×, 205 outside, 49 with too few days (share within: 36%).

Per region cell, over held-out days with a known Aqua state: Σ fused estimate without Aqua (training ratios of the AOI) / Σ Aqua detections. The AOI-level result does not make every region accurate; this shows where it holds.

Coverage: Satellite observation coverage (swath, cloud, smoke) is not verified. A day is 'known' when the sensor's record and an imported request interval cover it; a known day with no detection is a reported zero, not proof of a clear-sky observation.
