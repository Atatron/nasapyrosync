# Run K: Kalimantan (reference: MODIS Aqua)

Method `pyrosync-fusion-1.0`, gate `pyrosync-fusion-gate-1.0`, dataset revision 1.
AOI `region:kalimantan`; record 2000-11-01 → 2026-11-14; filters {'start': '2000-11-01', 'end': '2026-11-14', 'platforms': ['Terra', 'Aqua', 'N20', 'N21', 'SNPP'], 'modis_min_conf': 30, 'viirs_conf': ['nominal', 'high'], 'types': ['0', 'unknown'], 'daynight': ['D', 'N'], 'aoi': 'region:kalimantan'}.

Reference scale: MODIS Aqua active-fire detections per UTC day in the AOI. Aqua is the longest single-platform MODIS record with an afternoon overpass, the one the 1.4 day-level ratio was validated against. It is a reference observational scale, not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target. Aqua's overpass has drifted later since it left the A-Train in 2022; the year-by-year checks show whether that changes the ratios.

Equation: F_d = mean over eligible platforms p known on day d of c_p · X_p,d;  c_Aqua = 1,  c_p = Σ_train Aqua / Σ_train p (1.4 day-level ratio, pairwise chronological split).

## Pairwise calibration against Aqua (1.4 rules, unchanged)

| Platform | c (95 % bootstrap) | overlap days | held-out ratio | rolling years within 0.8–1.25× | pair gate | eligible |
|---|---|---|---|---|---|---|
| Terra (MODIS) | 2.6206 (2.3077–3.0388) | 8,702 | 1.35 | 5 of 23 (0.22–2.07) | not_validated | no |
| Suomi NPP (VIIRS) | 0.1483 (0.1334–0.1654) | 5,270 | 1.07 | 10 of 14 (0.66–1.34) | not_validated | no |
| NOAA-20 (VIIRS) | 0.1617 (0.1488–0.1848) | 3,081 | 1.22 | 6 of 8 (0.70–1.28) | not_validated | no |
| NOAA-21 (VIIRS) | 0.1917 (0.1674–0.2225) | 1,341 | 1.47 | 1 of 3 (0.80–1.46) | not_validated | no |

## Fused series validation (leave-reference-out)

Leave-reference-out: the fused estimate WITHOUT Aqua, with each ratio fitted only on days before the evaluation period, is compared with the observed Aqua totals. Aqua is never an input to its own prediction.

Split 2022-07-24 (chronological hold-out: the last 20% of days with activity and a known Aqua state); 7,240 Aqua training days; 1,556 held-out days ['2022-07-24', '2026-11-14']. Training ratios: SNPP 0.1466, N20 0.1500, N21 —.

| Held-out daily totals | Σ est / Σ Aqua | MAE | RMSE | MBE |
|---|---|---|---|---|
| fusion_leave_reference_out | 1.01 | 33.7 | 108.2 | 0.6 |
| raw_unadjusted_mean | 6.84 | 258.9 | 855.6 | 258.8 |
| constant_train_mean | 1.15 | 71.3 | 158.1 | 6.8 |

| Same held-out days, single sensor vs fusion | days | single-ratio Σ/Σ | single MAE | fusion Σ/Σ | fusion MAE |
|---|---|---|---|---|---|
| SNPP | 1492 | 1.02 | 33.2 | 1.03 | 33.8 |
| N20 | 1550 | 1.02 | 35.2 | 1.01 | 33.8 |

High-fire days (Aqua ≥ 112): 132 days, 0.78×.
Monthly consistency: 51 held-out months; share within 0.8–1.25×: 61%.
Seasonal consistency (rolling-origin, by calendar month): share within 0.8–1.25×: 83% (1.19, 1.24, 1.29, 0.96, 0.99, 1.06, 0.89, 0.95, 1.12, 1.50, 1.21, 1.12).

| Year | contributors (no Aqua) | test days | Σ est / Σ Aqua | MAE | constant MAE |
|---|---|---|---|---|---|
| 2013 | SNPP | 362 | 0.92 | 25.2 | 72.7 |
| 2014 | SNPP | 363 | 1.25 | 56.7 | 90.3 |
| 2015 | SNPP | 364 | 1.34 | 77.3 | 134.5 |
| 2016 | SNPP | 366 | 0.83 | 13.0 | 61.8 |
| 2017 | SNPP | 362 | 0.82 | 7.4 | 59.5 |
| 2018 | SNPP | 364 | 0.90 | 16.9 | 63.3 |
| 2019 | SNPP, N20 | 363 | 1.16 | 38.4 | 85.8 |
| 2020 | SNPP, N20 | 349 | 0.83 | 6.3 | 55.9 |
| 2021 | SNPP, N20 | 358 | 0.81 | 7.2 | 52.3 |
| 2022 | SNPP, N20 | 344 | 0.95 | 5.0 | 48.9 |
| 2023 | SNPP, N20 | 361 | 0.86 | 28.6 | 63.0 |
| 2024 | SNPP, N20, N21 | 362 | 0.72 | 17.8 | 52.1 |
| 2025 | SNPP, N20, N21 | 359 | 0.93 | 12.7 | 48.8 |
| 2026 | SNPP, N20, N21 | 316 | 1.31 | 98.2 | 134.2 |

| Platform joins | step without Aqua (before → after) | step with Aqua |
|---|---|---|
| SNPP 2012-01-20 | not testable | 0.92× |
| N20 2018-04-01 | 1.09× (0.86 → 0.94) | 1.03× |
| N21 2023-03-01 | 0.94× (1.01 → 0.95) | 0.96× |

Missing data: 636 of 9,510 record days have no known platform; Aqua unknown on 714 days.

**Fusion gate: not_validated** — Experimental: the fused series does not pass the project's validation rules for this area

- ✔ Enough held-out days: 1,556 days (At least 30 held-out days with a known Aqua state and a fused estimate.)
- ✔ Total level close to Aqua: Σ fused / Σ Aqua = 1.01 (Held-out total between 0.8× and 1.25× the Aqua total.)
- ✔ Better than averaging raw counts: MAE 33.7 vs 258.9; RMSE 108.2 vs 855.6 (Held-out daily MAE and RMSE below the uncalibrated mean of the same platforms' raw counts.)
- ✔ Better than a constant: MAE 33.7 vs 71.3; RMSE 108.2 vs 158.1 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily Aqua total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to Aqua: 10 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2024: 0.72× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to Aqua: 132 days, 0.78× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)
- ✔ No jump when a satellite joins: N20 1.09×, N21 0.94× (For every platform joining the record, the before/after level step of the fused estimate (without Aqua) is within 0.8–1.25×. A platform without a full year on both sides is not testable and does not fail the check.)

## Regional check (1.0° cells, ≥ 20 active held-out days)

29 cells within 0.8–1.25×, 34 outside, 6 with too few days (share within: 46%).

Per region cell, over held-out days with a known Aqua state: Σ fused estimate without Aqua (training ratios of the AOI) / Σ Aqua detections. The AOI-level result does not make every region accurate; this shows where it holds.

Coverage: Satellite observation coverage (swath, cloud, smoke) is not verified. A day is 'known' when the sensor's record and an imported request interval cover it; a known day with no detection is a reported zero, not proof of a clear-sky observation.
