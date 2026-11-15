# Run A: Indonesia, Aqua–S-NPP

Method `pyrosync-aggregate-1.0`, gate `pyrosync-aggregate-gate-1.0`, dataset revision 1.
Config `{'modis_platforms': ['Aqua'], 'viirs_series': 'VIIRS_SNPP', 'unit_grid': 0.1, 'tolerance_min': 30, 'metric': 'detections', 'unit_set': 'matched', 'evidence_radius_deg': 5.0, 'test_fraction': 0.2, 'split_date': None}`; AOI `none`; types `0,unknown`.

Equation: M̂_d = c · V_d,  c = Σ_train M_d / Σ_train V_d (training days with known coverage of both sensors). Split: 2023-10-27 (chronological hold-out: the last 20% of days with activity and known coverage of both sensors). Valid period: ['2012-01-20', '2026-11-02'].

MODIS is the reference scale for continuity with the long MODIS record. It is not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target.

## Detections

FIRMS detections per UTC day in the AOI, each sensor its own count (MODIS 1 km, VIIRS 375 m pixels).

c = 0.1309 (95 % month-block bootstrap 0.1226–0.1394); 4,268 training days ['2012-01-20', '2023-10-26'], 1,066 held-out days ['2023-10-27', '2026-11-02']; 1.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 0.991.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 7.55 | 754.1 | 1,942.7 | 754.0 |
| constant_train_mean | 0.94 | 138.2 | 280.1 | -6.3 |
| day_ratio | 0.99 | 51.6 | 152.6 | -1.3 |
| event_loglog_all_viirs | 3.67 | 307.1 | 615.3 | 306.8 |
| event_loglog_model_domain | 0.05 | 109.9 | 299.9 | -109.8 |

High-activity days (MODIS ≥ 289): 101 days, day ratio 0.98× (raw VIIRS 7.45×); low-activity days: 965 days, 1.01×.
Monthly totals (36 months with ≥ 20 known days): ratio 0.99×, MAE 405; share of months within 0.8–1.25×: 83%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2013 | 0.1556 | 364 | 1.07 | 6.85 | 47.9 | 147.7 |
| 2014 | 0.1513 | 365 | 1.18 | 7.80 | 81.7 | 180.9 |
| 2015 | 0.1400 | 365 | 1.22 | 8.70 | 100.8 | 270.5 |
| 2016 | 0.1293 | 366 | 0.94 | 7.27 | 24.5 | 144.5 |
| 2017 | 0.1299 | 364 | 0.94 | 7.24 | 16.6 | 128.4 |
| 2018 | 0.1303 | 365 | 0.94 | 7.19 | 27.1 | 117.0 |
| 2019 | 0.1310 | 365 | 1.03 | 7.89 | 46.1 | 158.7 |
| 2020 | 0.1304 | 366 | 1.17 | 8.96 | 21.0 | 108.1 |
| 2021 | 0.1297 | 362 | 0.95 | 7.31 | 13.2 | 97.3 |
| 2022 | 0.1299 | 346 | 1.02 | 7.84 | 11.9 | 95.0 |
| 2023 | 0.1299 | 361 | 0.90 | 6.93 | 34.9 | 114.9 |
| 2024 | 0.1310 | 345 | 0.83 | 6.37 | 24.4 | 83.5 |
| 2025 | 0.1318 | 364 | 0.92 | 7.01 | 19.5 | 85.2 |
| 2026 | 0.1320 | 291 | 1.04 | 7.89 | 130.6 | 275.7 |

**Gate: passes** — Passes the project's aggregate validation rules (chronological hold-out and year-by-year stability)

- ✔ Enough held-out days: 1,066 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 0.99 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 51.6 vs 754.1; RMSE 152.6 vs 1942.7 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 51.6 vs 138.2; RMSE 152.6 vs 280.1 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✔ Most years close to MODIS: 14 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2015: 1.22× (No rolling-origin year outside 0.67–1.5×.)
- ✔ High-fire days close to MODIS: 101 days, 0.98× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Cells

Occupied comparison cells per UTC day: grid cells of the run's comparison grid with at least one detection of that sensor.

c = 0.2204 (95 % month-block bootstrap 0.2092–0.2300); 4,268 training days ['2012-01-20', '2023-10-26'], 1,066 held-out days ['2023-10-27', '2026-11-02']; 1.5% of days have an unknown coverage state for at least one sensor.

Diagnostic day-level log-log slope β = 1.095.

| Held-out daily totals | Σ est / Σ MODIS | MAE | RMSE | MBE |
|---|---|---|---|---|
| raw_viirs | 4.33 | 202.9 | 364.8 | 202.7 |
| constant_train_mean | 0.98 | 68.1 | 122.1 | -1.4 |
| day_ratio | 0.95 | 24.1 | 57.3 | -2.8 |

High-activity days (MODIS ≥ 160): 106 days, day ratio 0.78× (raw VIIRS 3.54×); low-activity days: 960 days, 1.23×.
Monthly totals (36 months with ≥ 20 known days): ratio 0.95×, MAE 305; share of months within 0.8–1.25×: 53%.

| Year | c (earlier years) | test days | Σ est / Σ MODIS | raw VIIRS ratio | MAE | constant MAE |
|---|---|---|---|---|---|---|
| 2013 | 0.2450 | 364 | 1.05 | 4.28 | 23.9 | 74.9 |
| 2014 | 0.2402 | 365 | 1.02 | 4.24 | 31.7 | 87.7 |
| 2015 | 0.2382 | 365 | 0.99 | 4.18 | 37.5 | 130.3 |
| 2016 | 0.2387 | 366 | 1.21 | 5.09 | 16.4 | 70.9 |
| 2017 | 0.2346 | 364 | 1.27 | 5.39 | 12.4 | 65.1 |
| 2018 | 0.2310 | 365 | 1.15 | 4.97 | 17.6 | 60.7 |
| 2019 | 0.2278 | 365 | 1.02 | 4.50 | 22.2 | 74.1 |
| 2020 | 0.2270 | 366 | 1.46 | 6.44 | 15.5 | 55.1 |
| 2021 | 0.2232 | 362 | 1.19 | 5.35 | 8.8 | 49.9 |
| 2022 | 0.2218 | 346 | 1.31 | 5.89 | 9.4 | 49.0 |
| 2023 | 0.2202 | 361 | 1.01 | 4.57 | 19.1 | 60.9 |
| 2024 | 0.2200 | 345 | 1.11 | 5.04 | 14.5 | 43.0 |
| 2025 | 0.2191 | 364 | 1.12 | 5.13 | 12.2 | 45.2 |
| 2026 | 0.2182 | 291 | 0.85 | 3.91 | 52.5 | 129.5 |

**Gate: not_validated** — Not validated under the project's aggregate rules: the calibrated line is not drawn

- ✔ Enough held-out days: 1,066 days (At least 30 held-out days with a known coverage state for both sensors.)
- ✔ Total level close to MODIS: Σ estimate / Σ MODIS = 0.95 (Held-out total between 0.8× and 1.25× the MODIS total.)
- ✔ Daily totals better than raw VIIRS: MAE 24.1 vs 202.9; RMSE 57.3 vs 364.8 (Held-out daily MAE and RMSE below raw VIIRS.)
- ✔ Daily totals better than a constant: MAE 24.1 vs 68.1; RMSE 57.3 vs 122.1 (Held-out daily MAE and RMSE below a constant equal to the training-period mean daily MODIS total.)
- ✔ Enough rolling-origin years: 14 years (At least 3 calendar years predicted from earlier years only.)
- ✘ Most years close to MODIS: 11 of 14 years within 0.8–1.25× (At least 80% of rolling-origin years within 0.8–1.25×.)
- ✔ No year far off: worst year 2020: 1.46× (No rolling-origin year outside 0.67–1.5×.)
- ✘ High-fire days close to MODIS: 106 days, 0.78× (At least 10 held-out days at or above the training 90th percentile, total within 0.8–1.25×.)

## Limitations

- Day totals are calibrated, not single fires: the ratio says nothing about the MODIS count of one cell and overpass.
- The ratio assumes a stable MODIS/VIIRS relation; it is tested only where both sensors exist (S-NPP from 2012-01, NOAA-20 from 2018-04, NOAA-21 from 2023-03). Applying it outside the valid period is extrapolation and is not done by PyroSync.
- Aqua left the A-Train in January 2022 and its overpass time drifts later; the year-by-year results after 2022 show whether that changes the ratio.
- Satellite coverage (swath, cloud, smoke) is not verified: unknown days are excluded, but cloudy known days still count.
- The same rules apply to every AOI; small AOIs have few active days and often fail the gate.

Coverage: Verified satellite coverage is NOT established. FIRMS active-fire records list detections only; they do not say which cells each overpass imaged, nor which were cloud-free. Verifying coverage would require swath geolocation and fire/cloud masks (MOD03/MOD14 for MODIS, VNP03/VNP14 or VJ103/VJ114 for VIIRS), which PyroSync does not import. 'Proxy' classes only show that the other instrument reported a detection nearby at about the same time.
