# Harmonization audit (generated)

Generated 2026-11-14 18:34 UTC by `python -m pyrosync.cli harmonize-audit` (pyrosync-harmonize-1.0, pyrosync-validity-1.0, pyrosync-calibration-apply-1.0). Every number is computed from the imported data by `backend/pyrosync/audit.py`.

## Run A: Indonesia, Aqua–S-NPP, ±30 min, 0.1°, detections

Dates 2012-01-20 to 2026-11-14, AOI `none`, config `{"modis_platforms": ["Aqua"], "viirs_series": "VIIRS_SNPP", "unit_grid": 0.1, "tolerance_min": 30, "metric": "detections", "unit_set": "matched", "evidence_radius_deg": 5.0, "test_fraction": 0.2, "split_date": null}`.

### 1. Temporal matching

- Matched pairs 113,567 out of 113,567 candidate pairs (ambiguous candidates resolved by the one-to-one rule: 0).
- Every event used at most once: **yes**; all |Δt| within the tolerance: **yes**.
- |Δt| percentiles (min): p10 2, p25 6, p50 13, p75 23, p90 27, p99 30. Share of matches with |Δt| ≥ ⅔ of the tolerance: 32.1 %.

### 2. Coverage limits

- 8.0 % of VIIRS events and 37.1 % of MODIS events have a partner. Of all VIIRS events, 38.9 % are unmatched with only proxy evidence and 53.2 % are unmatched with no MODIS evidence nearby. Coverage status: `not_verified`.

### 3. Data leakage

- Training units strictly before held-out units: **yes** (split 2019-09-22); days on both sides: 0.
- Refit after deleting every record from the split date on: α 0.613138 vs 0.613138, β 0.238849 vs 0.238849 (max difference 0.00e+00; 90,772 vs 90,772 training units).
- Constants are fitted on training units only; the Duan smearing factor is reported but not applied.
- Embargo (drop held-out units in the first N days after the split): 0 d: n 22,795, MAE 3.562 → 0.842; 30 d: n 20,156, MAE 3.232 → 0.824; 90 d: n 18,186, MAE 3.120 → 0.811; 365 d: n 16,137, MAE 3.116 → 0.810.

### 4. Metrics recomputed independently

- Maximum absolute difference between the report and a plain-Python recomputation of MAE/RMSE/MBE: 2.78e-17.

### 5. Held-out errors of simple alternatives

| Estimate | MAE | RMSE | MBE |
|---|---|---|---|
| Calibrated (log-log) | 0.842 | 1.423 | -0.228 |
| Unadjusted VIIRS (M̂ = V) | 3.562 | 7.539 | 3.262 |
| Constant: training mean | 1.006 | 1.595 | 0.076 |
| Constant: training median | 0.894 | 1.827 | -0.894 |
| Ratio model M̂ = c·V (c = ΣM/ΣV, training) | 1.232 | 2.037 | -0.289 |

### 6. Application

- Unit-level validity: **passes**. Model fitted: yes (fitted); Measurement eligible for application: yes (detection counts); Enough held-out units: yes (22,795 units); Better than unadjusted VIIRS: yes (MAE 0.842 vs 3.562; RMSE 1.423 vs 7.539; |MBE| 0.228 vs 3.262); Better than a constant model: yes (MAE 0.842 vs best constant 0.894; RMSE 1.423 vs best constant 1.595); VIIRS slope clearly positive: yes (β 95 % CI lower bound 0.2360).
- Error map (0.5° regions, n ≥ 20): 305 validated regions holding 83.5 % of 22,795 held-out units; 589 with too few units; 408 with VIIRS activity but no held-out unit; validated regions where calibrated is worse than unadjusted: 3.
- Held-out daily totals, model-domain events: Σ calibrated / Σ MODIS = 0.24 (raw VIIRS 6.30); daily MAE 345.4 → 46.9; constant 118.2. Totals validity: **not_validated**.
- Held-out daily totals, all VIIRS events: Σ calibrated / Σ MODIS = 3.79 (raw VIIRS 6.30); daily MAE 345.4 → 190.1; constant 118.2. Totals validity: **not_validated**.

## Run B: as A, matched + proxy one-sided units

Dates 2012-01-20 to 2026-11-14, AOI `none`, config `{"modis_platforms": ["Aqua"], "viirs_series": "VIIRS_SNPP", "unit_grid": 0.1, "tolerance_min": 30, "metric": "detections", "unit_set": "matched_plus_proxy", "evidence_radius_deg": 5.0, "test_fraction": 0.2, "split_date": null}`.

### 1. Temporal matching

- Matched pairs 113,567 out of 113,567 candidate pairs (ambiguous candidates resolved by the one-to-one rule: 0).
- Every event used at most once: **yes**; all |Δt| within the tolerance: **yes**.
- |Δt| percentiles (min): p10 2, p25 6, p50 13, p75 23, p90 27, p99 30. Share of matches with |Δt| ≥ ⅔ of the tolerance: 32.1 %.

### 2. Coverage limits

- 8.0 % of VIIRS events and 37.1 % of MODIS events have a partner. Of all VIIRS events, 38.9 % are unmatched with only proxy evidence and 53.2 % are unmatched with no MODIS evidence nearby. Coverage status: `not_verified`.

### 3. Data leakage

- Training units strictly before held-out units: **yes** (split 2019-11-07); days on both sides: 0.
- Refit after deleting every record from the split date on: α 0.081959 vs 0.081959, β 0.132073 vs 0.132073 (max difference 0.00e+00; 578,557 vs 578,557 training units).
- Constants are fitted on training units only; the Duan smearing factor is reported but not applied.
- Embargo (drop held-out units in the first N days after the split): 0 d: n 145,243, MAE 1.979 → 0.531; 30 d: n 138,539, MAE 1.971 → 0.534; 90 d: n 136,036, MAE 1.978 → 0.536; 365 d: n 115,731, MAE 1.998 → 0.547.

### 4. Metrics recomputed independently

- Maximum absolute difference between the report and a plain-Python recomputation of MAE/RMSE/MBE: 2.78e-17.

### 5. Held-out errors of simple alternatives

| Estimate | MAE | RMSE | MBE |
|---|---|---|---|
| Calibrated (log-log) | 0.531 | 0.976 | -0.187 |
| Unadjusted VIIRS (M̂ = V) | 1.979 | 3.492 | 1.605 |
| Constant: training mean | 0.619 | 0.965 | 0.007 |
| Constant: training median | 0.411 | 1.049 | -0.411 |
| Ratio model M̂ = c·V (c = ΣM/ΣV, training) | 0.544 | 0.939 | -0.113 |

### 6. Application

- Unit-level validity: **not_validated**. Model fitted: yes (fitted); Measurement eligible for application: yes (detection counts); Enough held-out units: yes (145,243 units); Better than unadjusted VIIRS: yes (MAE 0.531 vs 1.979; RMSE 0.976 vs 3.492; |MBE| 0.187 vs 1.605); Better than a constant model: no (MAE 0.531 vs best constant 0.411; RMSE 0.976 vs best constant 0.965); VIIRS slope clearly positive: yes (β 95 % CI lower bound 0.1304).
- Error map (0.5° regions, n ≥ 20): 834 validated regions holding 98.4 % of 145,243 held-out units; 329 with too few units; 139 with VIIRS activity but no held-out unit; validated regions where calibrated is worse than unadjusted: 0.

## Run C: Indonesia, Aqua–NOAA-20, ±60 min

Dates 2018-04-01 to 2026-11-14, AOI `none`, config `{"modis_platforms": ["Aqua"], "viirs_series": "VIIRS_N20", "unit_grid": 0.1, "tolerance_min": 60, "metric": "detections", "unit_set": "matched", "evidence_radius_deg": 5.0, "test_fraction": 0.2, "split_date": null}`.

### 1. Temporal matching

- Matched pairs 59,563 out of 60,204 candidate pairs (ambiguous candidates resolved by the one-to-one rule: 641).
- Every event used at most once: **yes**; all |Δt| within the tolerance: **yes**.
- |Δt| percentiles (min): p10 3, p25 11, p50 23, p75 37, p90 49, p99 59. Share of matches with |Δt| ≥ ⅔ of the tolerance: 18.8 %.

### 2. Coverage limits

- 9.2 % of VIIRS events and 44.7 % of MODIS events have a partner. Of all VIIRS events, 53.0 % are unmatched with only proxy evidence and 37.8 % are unmatched with no MODIS evidence nearby. Coverage status: `not_verified`.

### 3. Data leakage

- Training units strictly before held-out units: **yes** (split 2023-09-21); days on both sides: 0.
- Refit after deleting every record from the split date on: α 0.603647 vs 0.603647, β 0.260248 vs 0.260248 (max difference 0.00e+00; 47,592 vs 47,592 training units).
- Constants are fitted on training units only; the Duan smearing factor is reported but not applied.
- Embargo (drop held-out units in the first N days after the split): 0 d: n 11,971, MAE 3.113 → 0.888; 30 d: n 8,175, MAE 2.758 → 0.872; 90 d: n 6,086, MAE 2.511 → 0.868; 365 d: n 2,754, MAE 2.495 → 0.793.

### 4. Metrics recomputed independently

- Maximum absolute difference between the report and a plain-Python recomputation of MAE/RMSE/MBE: 2.22e-16.

### 5. Held-out errors of simple alternatives

| Estimate | MAE | RMSE | MBE |
|---|---|---|---|
| Calibrated (log-log) | 0.888 | 1.466 | -0.254 |
| Unadjusted VIIRS (M̂ = V) | 3.113 | 6.253 | 2.670 |
| Constant: training mean | 1.022 | 1.594 | 0.069 |
| Constant: training median | 0.944 | 1.851 | -0.944 |
| Ratio model M̂ = c·V (c = ΣM/ΣV, training) | 1.285 | 2.050 | -0.344 |

### 6. Application

- Unit-level validity: **passes**. Model fitted: yes (fitted); Measurement eligible for application: yes (detection counts); Enough held-out units: yes (11,971 units); Better than unadjusted VIIRS: yes (MAE 0.888 vs 3.113; RMSE 1.466 vs 6.253; |MBE| 0.254 vs 2.670); Better than a constant model: yes (MAE 0.888 vs best constant 0.944; RMSE 1.466 vs best constant 1.594); VIIRS slope clearly positive: yes (β 95 % CI lower bound 0.2562).
- Error map (0.5° regions, n ≥ 20): 188 validated regions holding 73.3 % of 11,971 held-out units; 568 with too few units; 505 with VIIRS activity but no held-out unit; validated regions where calibrated is worse than unadjusted: 2.
- Held-out daily totals, model-domain events: Σ calibrated / Σ MODIS = 0.23 (raw VIIRS 5.13); daily MAE 352.1 → 58.1; constant 84.3. Totals validity: **not_validated**.
- Held-out daily totals, all VIIRS events: Σ calibrated / Σ MODIS = 3.32 (raw VIIRS 5.13); daily MAE 352.1 → 215.2; constant 84.3. Totals validity: **not_validated**.

## Run D: Kalimantan, Aqua–S-NPP (the online demo region)

Dates 2012-01-20 to 2026-11-14, AOI `region:kalimantan`, config `{"modis_platforms": ["Aqua"], "viirs_series": "VIIRS_SNPP", "unit_grid": 0.1, "tolerance_min": 30, "metric": "detections", "unit_set": "matched", "evidence_radius_deg": 5.0, "test_fraction": 0.2, "split_date": null}`.

### 1. Temporal matching

- Matched pairs 36,893 out of 36,893 candidate pairs (ambiguous candidates resolved by the one-to-one rule: 0).
- Every event used at most once: **yes**; all |Δt| within the tolerance: **yes**.
- |Δt| percentiles (min): p10 2, p25 7, p50 13, p75 23, p90 27, p99 30. Share of matches with |Δt| ≥ ⅔ of the tolerance: 33.3 %.

### 2. Coverage limits

- 9.9 % of VIIRS events and 35.9 % of MODIS events have a partner. Of all VIIRS events, 40.3 % are unmatched with only proxy evidence and 49.8 % are unmatched with no MODIS evidence nearby. Coverage status: `not_verified`.

### 3. Data leakage

- Training units strictly before held-out units: **yes** (split 2019-09-12); days on both sides: 0.
- Refit after deleting every record from the split date on: α 0.686670 vs 0.686670, β 0.205203 vs 0.205203 (max difference 0.00e+00; 29,275 vs 29,275 training units).
- Constants are fitted on training units only; the Duan smearing factor is reported but not applied.
- Embargo (drop held-out units in the first N days after the split): 0 d: n 7,618, MAE 4.169 → 0.975; 30 d: n 5,792, MAE 2.957 → 0.858; 90 d: n 5,359, MAE 2.779 → 0.862; 365 d: n 5,170, MAE 2.739 → 0.865.

### 4. Metrics recomputed independently

- Maximum absolute difference between the report and a plain-Python recomputation of MAE/RMSE/MBE: 1.11e-16.

### 5. Held-out errors of simple alternatives

| Estimate | MAE | RMSE | MBE |
|---|---|---|---|
| Calibrated (log-log) | 0.975 | 1.654 | -0.300 |
| Unadjusted VIIRS (M̂ = V) | 4.169 | 9.215 | 3.752 |
| Constant: training mean | 1.098 | 1.783 | -0.009 |
| Constant: training median | 1.054 | 2.072 | -1.054 |
| Ratio model M̂ = c·V (c = ΣM/ΣV, training) | 1.491 | 2.640 | -0.188 |

### 6. Application

- Unit-level validity: **passes**. Model fitted: yes (fitted); Measurement eligible for application: yes (detection counts); Enough held-out units: yes (7,618 units); Better than unadjusted VIIRS: yes (MAE 0.975 vs 4.169; RMSE 1.654 vs 9.215; |MBE| 0.300 vs 3.752); Better than a constant model: yes (MAE 0.975 vs best constant 1.054; RMSE 1.654 vs best constant 1.783); VIIRS slope clearly positive: yes (β 95 % CI lower bound 0.1999).
- Error map (0.5° regions, n ≥ 20): 114 validated regions holding 91.2 % of 7,618 held-out units; 80 with too few units; 20 with VIIRS activity but no held-out unit; validated regions where calibrated is worse than unadjusted: 1.
- Held-out daily totals, model-domain events: Σ calibrated / Σ MODIS = 0.22 (raw VIIRS 4.93); daily MAE 104.0 → 18.6; constant 53.9. Totals validity: **not_validated**.
- Held-out daily totals, all VIIRS events: Σ calibrated / Σ MODIS = 2.69 (raw VIIRS 4.93); daily MAE 104.0 → 51.7; constant 53.9. Totals validity: **not_validated**.

## Run E: as A, FRP sum (MW)

Dates 2012-01-20 to 2026-11-14, AOI `none`, config `{"modis_platforms": ["Aqua"], "viirs_series": "VIIRS_SNPP", "unit_grid": 0.1, "tolerance_min": 30, "metric": "frp_sum", "unit_set": "matched", "evidence_radius_deg": 5.0, "test_fraction": 0.2, "split_date": null}`.

### 1. Temporal matching

- Matched pairs 113,567 out of 113,567 candidate pairs (ambiguous candidates resolved by the one-to-one rule: 0).
- Every event used at most once: **yes**; all |Δt| within the tolerance: **yes**.
- |Δt| percentiles (min): p10 2, p25 6, p50 13, p75 23, p90 27, p99 30. Share of matches with |Δt| ≥ ⅔ of the tolerance: 32.1 %.

### 2. Coverage limits

- 8.0 % of VIIRS events and 37.1 % of MODIS events have a partner. Of all VIIRS events, 38.9 % are unmatched with only proxy evidence and 53.2 % are unmatched with no MODIS evidence nearby. Coverage status: `not_verified`.

### 3. Data leakage

- Training units strictly before held-out units: **yes** (split 2019-09-22); days on both sides: 0.
- Refit after deleting every record from the split date on: α 1.504726 vs 1.504726, β 0.603046 vs 0.603046 (max difference 0.00e+00; 90,772 vs 90,772 training units).
- Constants are fitted on training units only; the Duan smearing factor is reported but not applied.
- Embargo (drop held-out units in the first N days after the split): 0 d: n 22,795, MAE 40.759 → 40.713; 30 d: n 20,156, MAE 38.482 → 38.485; 90 d: n 18,186, MAE 38.204 → 37.874; 365 d: n 16,137, MAE 38.062 → 37.640.

### 4. Metrics recomputed independently

- Maximum absolute difference between the report and a plain-Python recomputation of MAE/RMSE/MBE: 7.11e-15.

### 5. Held-out errors of simple alternatives

| Estimate | MAE | RMSE | MBE |
|---|---|---|---|
| Calibrated (log-log) | 40.713 | 137.841 | -24.098 |
| Unadjusted VIIRS (M̂ = V) | 40.759 | 113.686 | -8.532 |
| Constant: training mean | 70.912 | 158.539 | 11.954 |
| Constant: training median | 51.380 | 162.286 | -36.674 |
| Ratio model M̂ = c·V (c = ΣM/ΣV, training) | 42.982 | 116.197 | -1.409 |

### 6. Application

- Unit-level validity: **not_validated**. Model fitted: yes (fitted); Measurement eligible for application: no (FRP sum); Enough held-out units: yes (22,795 units); Better than unadjusted VIIRS: no (MAE 40.713 vs 40.759; RMSE 137.841 vs 113.686; |MBE| 24.098 vs 8.532); Better than a constant model: yes (MAE 40.713 vs best constant 51.380; RMSE 137.841 vs best constant 158.539); VIIRS slope clearly positive: yes (β 95 % CI lower bound 0.5986).
- Error map (0.5° regions, n ≥ 20): 305 validated regions holding 83.5 % of 22,795 held-out units; 589 with too few units; 408 with VIIRS activity but no held-out unit; validated regions where calibrated is worse than unadjusted: 97.
