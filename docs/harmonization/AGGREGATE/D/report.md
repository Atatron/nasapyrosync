# Run D: Kalimantan, Aqua–S-NPP

Method `pyrosync-aggregate-1.0`, gate `pyrosync-aggregate-gate-1.0`, dataset revision 1.
Config `{'modis_platforms': ['Aqua'], 'viirs_series': 'VIIRS_SNPP', 'unit_grid': 0.1, 'tolerance_min': 30, 'metric': 'detections', 'unit_set': 'matched', 'evidence_radius_deg': 5.0, 'test_fraction': 0.2, 'split_date': None}`; AOI `region:kalimantan`; types `0,unknown`.

Equation: M̂_d = c · V_d,  c = Σ_train M_d / Σ_train V_d (training days with known coverage of both sensors). Split: 2023-10-23 (chronological hold-out: the last 20% of days with activity and known coverage of both sensors). Valid period: ['2012-01-20', '2026-11-02'].

MODIS is the reference scale for continuity with the long MODIS record. It is not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target.

## Detections

FIRMS detections per UTC day in the AOI, each sensor its own count (MODIS 1 km, VIIRS 375 m pixels).

c = 0.1477 (95 % month-block bootstrap 0.1328–0.1644); 4,264 training days ['2012-01-20', '2023-10-22'], 1,070 held-out days ['2023-10-23', '2026-11-02']; 1.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 0.733.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 7.21 | 300.6 | 1,012.0 | 300.0 |
| constant_train_mean | 0.78 | 66.7 | 179.7 | -10.5 |
| day_ratio | 1.06 | 36.6 | 119.8 | 3.1 |
| event_loglog_all_viirs | 2.95 | 96.8 | 252.3 | 94.4 |
| event_loglog_model_domain | 0.04 | 46.3 | 183.7 | -46.3 |

High-activity days (MODIS ≥ 76): 104 days, day ratio 0.89× (raw VIIRS 6.06×); low-activity days: 966 days, 2.06×.
Monthly totals (36 months with ≥ 20 known days): ratio 1.07×, MAE 292; share of months within 0.8–1.25×: 67%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2013 | 0.1788 | 364 | 0.92 | 5.12 | 25.1 | 62.6 |
| 2014 | 0.1850 | 365 | 1.25 | 6.77 | 56.4 | 80.7 |
| 2015 | 0.1651 | 365 | 1.34 | 8.10 | 77.1 | 130.1 |
| 2016 | 0.1441 | 366 | 0.83 | 5.76 | 13.0 | 64.5 |
| 2017 | 0.1455 | 364 | 0.82 | 5.61 | 7.4 | 55.5 |
| 2018 | 0.1463 | 365 | 0.90 | 6.16 | 16.9 | 56.5 |
| 2019 | 0.1475 | 365 | 1.09 | 7.40 | 38.5 | 79.1 |
| 2020 | 0.1454 | 366 | 1.02 | 7.04 | 7.8 | 47.6 |
| 2021 | 0.1453 | 362 | 0.78 | 5.37 | 7.3 | 42.2 |
| 2022 | 0.1460 | 346 | 0.98 | 6.75 | 4.5 | 37.2 |
| 2023 | 0.1460 | 361 | 0.87 | 5.94 | 28.3 | 53.4 |
| 2024 | 0.1477 | 345 | 0.66 | 4.47 | 17.1 | 41.9 |
| 2025 | 0.1497 | 364 | 0.89 | 5.94 | 12.8 | 38.3 |
| 2026 | 0.1502 | 291 | 1.18 | 7.86 | 96.3 | 136.1 |

**Gate: not_validated** — Not validated under the project's aggregate rules: the calibrated line is not drawn

- ✔ Enough held-out days: 1,070 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 1.06 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 36.6 vs 300.6; RMSE 119.8 vs 1012.0 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 36.6 vs 66.7; RMSE 119.8 vs 179.7 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to MODIS: 10 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✘ No year far off: worst year 2024: 0.66× (No rolling-origin year outside 0.67–1.5×.)
- ✔ High-fire days close to MODIS: 104 days, 0.89× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Cells

Occupied comparison cells per UTC day: grid cells of the run's comparison grid with at least one detection of that sensor.

c = 0.2789 (95 % month-block bootstrap 0.2617–0.2917); 4,264 training days ['2012-01-20', '2023-10-22'], 1,070 held-out days ['2023-10-23', '2026-11-02']; 1.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 0.780.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 3.38 | 55.0 | 127.0 | 54.5 |
| constant_train_mean | 0.85 | 30.9 | 69.7 | -3.5 |
| day_ratio | 0.94 | 16.6 | 44.9 | -1.3 |

High-activity days (MODIS ≥ 46): 107 days, day ratio 0.65× (raw VIIRS 2.32×); low-activity days: 963 days, 2.09×.
Monthly totals (36 months with ≥ 20 known days): ratio 0.94×, MAE 119; share of months within 0.8–1.25×: 53%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2013 | 0.2959 | 364 | 1.06 | 3.58 | 13.4 | 32.2 |
| 2014 | 0.2891 | 365 | 1.02 | 3.52 | 24.1 | 39.4 |
| 2015 | 0.2869 | 365 | 0.96 | 3.36 | 29.0 | 59.2 |
| 2016 | 0.2912 | 366 | 1.20 | 4.13 | 8.3 | 30.9 |
| 2017 | 0.2874 | 364 | 1.27 | 4.42 | 5.1 | 27.4 |
| 2018 | 0.2846 | 365 | 1.08 | 3.80 | 9.7 | 28.3 |
| 2019 | 0.2825 | 365 | 0.96 | 3.39 | 17.2 | 35.7 |
| 2020 | 0.2843 | 366 | 1.50 | 5.28 | 5.8 | 23.4 |
| 2021 | 0.2808 | 362 | 1.15 | 4.08 | 4.5 | 20.7 |
| 2022 | 0.2798 | 346 | 1.35 | 4.81 | 3.6 | 18.6 |
| 2023 | 0.2781 | 361 | 0.99 | 3.55 | 15.3 | 27.3 |
| 2024 | 0.2784 | 345 | 1.00 | 3.58 | 10.0 | 21.0 |
| 2025 | 0.2785 | 364 | 1.10 | 3.95 | 7.8 | 19.9 |
| 2026 | 0.2775 | 291 | 0.88 | 3.18 | 37.9 | 58.2 |

**Gate: not_validated** — Not validated under the project's aggregate rules: the calibrated line is not drawn

- ✔ Enough held-out days: 1,070 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 0.94 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 16.6 vs 55.0; RMSE 44.9 vs 127.0 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 16.6 vs 30.9; RMSE 44.9 vs 69.7 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to MODIS: 11 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✘ No year far off: worst year 2020: 1.50× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to MODIS: 107 days, 0.65× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Limitations

- Day totals are calibrated, not single fires: the ratio says nothing about the MODIS count of one cell and overpass.
- The ratio assumes a stable MODIS/VIIRS relation; it is tested only where both sensors exist (S-NPP from 2012-01, NOAA-20 from 2018-04, NOAA-21 from 2023-03). Applying it outside the valid period is extrapolation and is not done by PyroSync.
- Aqua left the A-Train in January 2022 and its overpass time drifts later; the year-by-year results after 2022 show whether that changes the ratio.
- Satellite coverage (swath, cloud, smoke) is not verified: unknown days are excluded, but cloudy known days still count.
- The same rules apply to every AOI; small AOIs have few active days and often fail the gate.

Coverage: Verified satellite coverage is NOT established. FIRMS active-fire records list detections only; they do not say which cells each overpass imaged, nor which were cloud-free. Verifying coverage would require swath geolocation and fire/cloud masks (MOD03/MOD14 for MODIS, VNP03/VNP14 or VJ103/VJ114 for VIIRS), which PyroSync does not import. 'Proxy' classes only show that the other instrument reported a detection nearby at about the same time.
