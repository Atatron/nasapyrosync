# Run F: Indonesia, Terra–S-NPP (different overpass time; control)

Method `pyrosync-aggregate-1.0`, gate `pyrosync-aggregate-gate-1.0`, dataset revision 1.
Config `{'modis_platforms': ['Terra'], 'viirs_series': 'VIIRS_SNPP', 'unit_grid': 0.1, 'tolerance_min': 30, 'metric': 'detections', 'unit_set': 'matched', 'evidence_radius_deg': 5.0, 'test_fraction': 0.2, 'split_date': None}`; AOI `none`; types `0,unknown`.

Equation: M̂_d = c · V_d,  c = Σ_train M_d / Σ_train V_d (training days with known coverage of both sensors). Split: 2023-10-27 (chronological hold-out: the last 20% of days with activity and known coverage of both sensors). Valid period: ['2012-01-20', '2026-11-02'].

MODIS is the reference scale for continuity with the long MODIS record. It is not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target.

## Detections

FIRMS detections per UTC day in the AOI, each sensor its own count (MODIS 1 km, VIIRS 375 m pixels).

c = 0.0630 (95 % month-block bootstrap 0.0595–0.0669); 4,268 training days ['2012-01-20', '2023-10-26'], 1,066 held-out days ['2023-10-27', '2026-11-02']; 1.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 0.919.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 13.80 | 806.1 | 2,024.1 | 806.1 |
| constant_train_mean | 0.83 | 83.0 | 199.7 | -10.6 |
| day_ratio | 0.87 | 31.1 | 116.2 | -8.2 |

High-activity days (MODIS ≥ 124): 92 days, day ratio 0.70× (raw VIIRS 11.13×); low-activity days: 974 days, 1.53×.
Monthly totals (36 months with ≥ 20 known days): ratio 0.87×, MAE 613; share of months within 0.8–1.25×: 42%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2013 | 0.0622 | 364 | 1.03 | 16.63 | 22.5 | 58.5 |
| 2014 | 0.0613 | 365 | 0.96 | 15.67 | 41.5 | 89.7 |
| 2015 | 0.0625 | 365 | 0.98 | 15.60 | 50.5 | 148.4 |
| 2016 | 0.0632 | 366 | 1.12 | 17.75 | 12.7 | 72.0 |
| 2017 | 0.0627 | 364 | 1.19 | 19.01 | 7.2 | 63.0 |
| 2018 | 0.0623 | 365 | 1.04 | 16.71 | 13.1 | 54.0 |
| 2019 | 0.0621 | 365 | 0.81 | 13.10 | 30.7 | 89.7 |
| 2020 | 0.0642 | 366 | 1.20 | 18.65 | 8.9 | 51.7 |
| 2021 | 0.0638 | 362 | 1.08 | 16.95 | 7.3 | 48.4 |
| 2022 | 0.0637 | 346 | 1.46 | 22.99 | 6.9 | 49.0 |
| 2023 | 0.0633 | 361 | 1.07 | 16.88 | 15.3 | 52.4 |
| 2024 | 0.0630 | 345 | 1.40 | 22.25 | 10.1 | 38.1 |
| 2025 | 0.0624 | 364 | 1.84 | 29.40 | 10.4 | 41.8 |
| 2026 | 0.0617 | 291 | 0.74 | 11.94 | 86.3 | 192.1 |

**Gate: not_validated** — Not validated under the project's aggregate rules: the calibrated line is not drawn

- ✔ Enough held-out days: 1,066 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 0.87 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 31.1 vs 806.1; RMSE 116.2 vs 2024.1 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 31.1 vs 83.0; RMSE 116.2 vs 199.7 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to MODIS: 10 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✘ No year far off: worst year 2025: 1.84× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to MODIS: 92 days, 0.70× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Cells

Occupied comparison cells per UTC day: grid cells of the run's comparison grid with at least one detection of that sensor.

c = 0.1074 (95 % month-block bootstrap 0.0983–0.1169); 4,268 training days ['2012-01-20', '2023-10-26'], 1,066 held-out days ['2023-10-27', '2026-11-02']; 1.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 0.991.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 8.76 | 233.5 | 415.5 | 233.5 |
| constant_train_mean | 0.96 | 38.0 | 76.1 | -1.1 |
| day_ratio | 0.94 | 16.3 | 43.5 | -1.8 |

High-activity days (MODIS ≥ 72): 91 days, day ratio 0.62× (raw VIIRS 5.79×); low-activity days: 975 days, 1.69×.
Monthly totals (36 months with ≥ 20 known days): ratio 0.94×, MAE 401; share of months within 0.8–1.25×: 17%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2013 | 0.1005 | 364 | 1.08 | 10.79 | 11.8 | 28.2 |
| 2014 | 0.0972 | 365 | 0.82 | 8.47 | 19.5 | 42.9 |
| 2015 | 0.1062 | 365 | 0.78 | 7.35 | 28.2 | 72.5 |
| 2016 | 0.1171 | 366 | 1.32 | 11.31 | 9.1 | 34.6 |
| 2017 | 0.1143 | 364 | 1.43 | 12.51 | 6.6 | 31.3 |
| 2018 | 0.1118 | 365 | 1.23 | 11.01 | 9.0 | 27.2 |
| 2019 | 0.1095 | 365 | 0.84 | 7.66 | 13.9 | 39.7 |
| 2020 | 0.1124 | 366 | 1.36 | 12.14 | 6.9 | 25.2 |
| 2021 | 0.1108 | 362 | 1.30 | 11.70 | 5.3 | 24.2 |
| 2022 | 0.1098 | 346 | 1.69 | 15.38 | 5.9 | 25.1 |
| 2023 | 0.1084 | 361 | 1.14 | 10.53 | 9.4 | 28.2 |
| 2024 | 0.1073 | 345 | 1.61 | 14.99 | 8.6 | 19.3 |
| 2025 | 0.1054 | 364 | 2.05 | 19.46 | 7.9 | 21.9 |
| 2026 | 0.1034 | 291 | 0.69 | 6.65 | 38.0 | 81.5 |

**Gate: not_validated** — Not validated under the project's aggregate rules: the calibrated line is not drawn

- ✔ Enough held-out days: 1,066 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 0.94 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 16.3 vs 233.5; RMSE 43.5 vs 415.5 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 16.3 vs 38.0; RMSE 43.5 vs 76.1 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to MODIS: 5 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✘ No year far off: worst year 2025: 2.05× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to MODIS: 91 days, 0.62× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Limitations

- Day totals are calibrated, not single fires: the ratio says nothing about the MODIS count of one cell and overpass.
- The ratio assumes a stable MODIS/VIIRS relation; it is tested only where both sensors exist (S-NPP from 2012-01, NOAA-20 from 2018-04, NOAA-21 from 2023-03). Applying it outside the valid period is extrapolation and is not done by PyroSync.
- Aqua left the A-Train in January 2022 and its overpass time drifts later; the year-by-year results after 2022 show whether that changes the ratio.
- Satellite coverage (swath, cloud, smoke) is not verified: unknown days are excluded, but cloudy known days still count.
- The same rules apply to every AOI; small AOIs have few active days and often fail the gate.

Coverage: Verified satellite coverage is NOT established. FIRMS active-fire records list detections only; they do not say which cells each overpass imaged, nor which were cloud-free. Verifying coverage would require swath geolocation and fire/cloud masks (MOD03/MOD14 for MODIS, VNP03/VNP14 or VJ103/VJ114 for VIIRS), which PyroSync does not import. 'Proxy' classes only show that the other instrument reported a detection nearby at about the same time.
