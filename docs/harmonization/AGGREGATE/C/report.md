# Run C: Indonesia, Aqua–NOAA-20

Method `pyrosync-aggregate-1.0`, gate `pyrosync-aggregate-gate-1.0`, dataset revision 1.
Config `{'modis_platforms': ['Aqua'], 'viirs_series': 'VIIRS_N20', 'unit_grid': 0.1, 'tolerance_min': 60, 'metric': 'detections', 'unit_set': 'matched', 'evidence_radius_deg': 5.0, 'test_fraction': 0.2, 'split_date': None}`; AOI `none`; types `0,unknown`.

Equation: M̂_d = c · V_d,  c = Σ_train M_d / Σ_train V_d (training days with known coverage of both sensors). Split: 2025-02-27 (chronological hold-out: the last 20% of days with activity and known coverage of both sensors). Valid period: ['2018-04-01', '2026-11-14'].

MODIS is the reference scale for continuity with the long MODIS record. It is not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target.

## Detections

FIRMS detections per UTC day in the AOI, each sensor its own count (MODIS 1 km, VIIRS 375 m pixels).

c = 0.1349 (95 % month-block bootstrap 0.1285–0.1418); 2,507 training days ['2018-04-01', '2025-02-26'], 626 held-out days ['2025-02-27', '2026-11-14']; 0.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 0.974.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 7.89 | 1,149.9 | 2,569.8 | 1,149.9 |
| constant_train_mean | 0.43 | 162.1 | 362.8 | -95.1 |
| day_ratio | 1.07 | 79.5 | 202.4 | 10.9 |
| event_loglog_all_viirs | 3.75 | 458.9 | 847.9 | 458.9 |
| event_loglog_model_domain | 0.03 | 161.1 | 383.2 | -161.1 |

High-activity days (MODIS ≥ 174): 133 days, day ratio 1.05× (raw VIIRS 7.76×); low-activity days: 493 days, 1.15×.
Monthly totals (20 months with ≥ 20 known days): ratio 1.07×, MAE 798; share of months within 0.8–1.25×: 90%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2019 | 0.1420 | 365 | 1.11 | 7.81 | 47.7 | 148.7 |
| 2020 | 0.1324 | 366 | 1.21 | 9.12 | 21.1 | 107.2 |
| 2021 | 0.1291 | 362 | 0.98 | 7.62 | 12.7 | 73.8 |
| 2022 | 0.1293 | 361 | 1.01 | 7.82 | 12.0 | 64.0 |
| 2023 | 0.1292 | 358 | 0.88 | 6.82 | 37.1 | 103.8 |
| 2024 | 0.1330 | 363 | 0.87 | 6.55 | 25.4 | 61.5 |
| 2025 | 0.1349 | 365 | 0.93 | 6.90 | 18.5 | 61.9 |
| 2026 | 0.1356 | 318 | 1.09 | 8.05 | 136.1 | 261.1 |

**Gate: passes** — Passes the project's aggregate validation rules (chronological hold-out and year-by-year stability)

- ✔ Enough held-out days: 626 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 1.07 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 79.5 vs 1149.9; RMSE 202.4 vs 2569.8 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 79.5 vs 162.1; RMSE 202.4 vs 362.8 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 8 years (At least 3 calendar years predicted from earlier years only.)
- ✔ Most years close to MODIS: 8 of 8 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2020: 1.21× (No rolling-origin year outside 0.67–1.5×.)
- ✔ High-fire days close to MODIS: 133 days, 1.05× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Cells

Occupied comparison cells per UTC day: grid cells of the run's comparison grid with at least one detection of that sensor.

c = 0.1969 (95 % month-block bootstrap 0.1821–0.2107); 2,507 training days ['2018-04-01', '2025-02-26'], 626 held-out days ['2025-02-27', '2026-11-14']; 0.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 1.048.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 4.32 | 283.9 | 481.0 | 283.9 |
| constant_train_mean | 0.48 | 79.4 | 157.9 | -44.9 |
| day_ratio | 0.85 | 32.9 | 76.1 | -12.8 |

High-activity days (MODIS ≥ 103): 130 days, day ratio 0.75× (raw VIIRS 3.81×); low-activity days: 496 days, 1.20×.
Monthly totals (20 months with ≥ 20 known days): ratio 0.85×, MAE 527; share of months within 0.8–1.25×: 65%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2019 | 0.2043 | 365 | 0.94 | 4.59 | 22.7 | 70.3 |
| 2020 | 0.2125 | 366 | 1.41 | 6.63 | 14.5 | 53.2 |
| 2021 | 0.2003 | 362 | 1.14 | 5.68 | 8.4 | 37.3 |
| 2022 | 0.1970 | 361 | 1.17 | 5.96 | 9.0 | 33.2 |
| 2023 | 0.1939 | 358 | 0.91 | 4.69 | 19.6 | 55.9 |
| 2024 | 0.1983 | 363 | 1.05 | 5.31 | 14.2 | 33.2 |
| 2025 | 0.1971 | 365 | 1.04 | 5.29 | 11.3 | 34.3 |
| 2026 | 0.1964 | 318 | 0.81 | 4.13 | 52.3 | 124.2 |

**Gate: not_validated** — Not validated under the project's aggregate rules: the calibrated line is not drawn

- ✔ Enough held-out days: 626 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 0.85 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 32.9 vs 283.9; RMSE 76.1 vs 481.0 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 32.9 vs 79.4; RMSE 76.1 vs 157.9 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 8 years (At least 3 calendar years predicted from earlier years only.)
- ✔ Most years close to MODIS: 7 of 8 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2020: 1.41× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to MODIS: 130 days, 0.75× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Limitations

- Day totals are calibrated, not single fires: the ratio says nothing about the MODIS count of one cell and overpass.
- The ratio assumes a stable MODIS/VIIRS relation; it is tested only where both sensors exist (S-NPP from 2012-01, NOAA-20 from 2018-04, NOAA-21 from 2023-03). Applying it outside the valid period is extrapolation and is not done by PyroSync.
- Aqua left the A-Train in January 2022 and its overpass time drifts later; the year-by-year results after 2022 show whether that changes the ratio.
- Satellite coverage (swath, cloud, smoke) is not verified: unknown days are excluded, but cloudy known days still count.
- The same rules apply to every AOI; small AOIs have few active days and often fail the gate.

Coverage: Verified satellite coverage is NOT established. FIRMS active-fire records list detections only; they do not say which cells each overpass imaged, nor which were cloud-free. Verifying coverage would require swath geolocation and fire/cloud masks (MOD03/MOD14 for MODIS, VNP03/VNP14 or VJ103/VJ114 for VIIRS), which PyroSync does not import. 'Proxy' classes only show that the other instrument reported a detection nearby at about the same time.
