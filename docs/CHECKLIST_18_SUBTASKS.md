# 18-subtask checklist: implementation evidence

Status values: **Implemented and verified** · **Implemented with an identified verification limitation** · **Blocked by missing data or credentials** · **Not implemented**.
"Verified" means an automated test or browser check listed in [TEST_RESULTS.md](TEST_RESULTS.md) exercised it successfully. A working algorithm is kept distinct from adequate historical evidence.

## Harmonization
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 1 | Connect to NASA FIRMS API | **Implemented with an identified verification limitation** | `backend/pyrosync/firms.py` (Area API, ≤5-day windows, disk cache, back-off, cancel, key redaction). UI: Data & Methods → FIRMS API. Tests: `test_firms_gibs.py` (11 cases with simulated responses). **Authenticated live retrieval is unverified: no MAP_KEY was available.** |
| 2 | Normalize MODIS and VIIRS records | **Implemented and verified** | `normalize.py` (schemas, strict dates, HHMM padding, per-sensor confidence, satellite codes, stream detection, separate thermal fields). Tests: `test_normalize.py`, `test_rejections_reported`. Sample: 566,644 rows, 0 rejected. |
| 3 | Aggregate into common spatial/daily units | **Implemented and verified** | `query.py` (`cell_sql`, `_daily`, `_frame_cells`): integer 0.1/0.05/0.01° grid, UTC days. Tests: `test_negative_coordinate_*`, `test_cross_panel_consistency`. Browser flows 3, 4, 9. |
| 4 | Retain sensor-specific results and limitations | **Implemented and verified** | Per-sensor series everywhere; union is cells only and never sums counts; standing VIIRS v2 type warning; Sensor Workbench. Tests: `test_same_location_different_platforms_kept_distinct`, `test_union_only_for_cells`, `test_grid_geojson_matches_frame`. |

## Calendar
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 5 | Calculate daily summaries | **Implemented and verified** | `/api/daily`, with five coverage states per day. Tests: `test_unknown_vs_zero_reported`, `test_zero_reported_inside_interval_unknown_outside`, `test_daily_export_matches_query`. |
| 6 | Create the heatmap | **Implemented and verified** | `CalendarPage.tsx` month grid (stable or per-month scale with disclosure; hatched unknown days), year overview, ISO-week heatmap. Browser flow 5 clicks a heatmap day. |
| 7 | Add month/year navigation | **Implemented and verified** | Previous/next month, month and year selectors, keyboard arrows/PageUp/PageDown. Browser flow 5 (next month → Oct 2023, year → 2024). |

## AOI
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 8 | Add map-based region selection | **Implemented and verified** | Leaflet-Geoman rectangle/polygon drawing, named regions (Natural Earth, with source and licence), GeoJSON upload, clear, export. Browser flow 3 draws a rectangle (→ 84 VIIRS detections). Tests: `test_aoi_post_and_export`, `test_aoi_validation_errors`, `test_aoi_3857_transformed`. |
| 9 | Filter by the selected region | **Implemented and verified** | Exact point-in-polygon with boundary points included, materialized per revision. Test: `test_aoi_boundary_points_included_and_exact_polygon`. Browser flow 3 (Kalimantan 384 vs Sumatra 646 on 2023-09-15). |
| 10 | Update the calendar from the AOI | **Implemented and verified** | Calendar uses the shared AOI filter. Browser flow 3 checks that changing the AOI on the calendar page re-queries `/api/daily` with the new AOI. |

## History
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 11 | Generate monthly/annual summaries | **Implemented and verified** | `/api/history`: per sensor, sum-of-daily vs distinct cells, partial flags, coverage days. Test: `test_cross_panel_consistency` (history = daily). Browser flow 13 renders it offline. |
| 12 | Build seasonal charts | **Implemented and verified** | HistoryPage monthly-by-sensor chart and seasonal profile (ECharts). Rendered in browser flow 13. Values come from the tested history endpoint. |
| 13 | Compare years | **Implemented and verified** | `/api/compare` (matched month-days, Feb 29 excluded, ratio undefined for a zero reference), rankings. Test: `test_leap_day_counted_and_compare_excludes_feb29`. Descriptive only, with no significance or seasonal-shift claims. |

## Unusual conditions
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 14 | Calculate an eligible historical baseline | **Implemented and verified** (real-data eligibility observed with the full-history archive; still ineligible with the 2023–2024 sample) | `analysis.compute_baseline` (≥5 prior years, ≥80 % coverage per ±15-day window, ≥100 reference days, P95/P5). The algorithm is verified by `test_baseline_eligible_and_zero_baseline_suppresses_low`, `test_baseline_missing_coverage_years_not_counted` and `test_insufficient_history_two_years`. **On the real 2023–2024 sample it is correctly ineligible ("Insufficient history for a robust multi-year baseline").** With the full-history archive (2000–2026) imported locally it becomes eligible without code changes: Kalimantan 2023, occupied cells: MODIS and VIIRS S-NPP 365/365 days, VIIRS NOAA-20 266/365 days. The thresholds are empirical percentiles, not validated danger levels. |
| 15 | Flag supported above/below-baseline activity | **Implemented and verified** (on synthetic fixtures; real-data flags observed with the full archive) | Above/below flags only when eligible; low flags suppressed at P5 = 0; undefined ratio at median 0. Verified on synthetic multi-year fixtures. With the full archive, Kalimantan 2023 shows 9 MODIS, 11 VIIRS S-NPP and 56 VIIRS NOAA-20 flagged days (occupied cells, default filters). No real-data flags exist for the 2023–2024 sample. |

## Critical periods
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 16 | Define an explainable threshold | **Implemented and verified** | Within-range percentile (default P90, ≥30 known days), user-defined threshold, or baseline (only when eligible). Rule and status text are shown in the UI and API. Test: `test_elevated_range_percentile_requires_30_known_days`. Kalimantan VIIRS cells: P90 = 190.4 cells/day. |
| 17 | Highlight qualifying periods | **Implemented and verified** | Red bands on the timeline histogram, flags on calendar days, Elevated lists (Explore/History), click-to-select. Browser flows 6 and 13 (12 periods for Kalimantan, VIIRS N20). |
| 18 | Explain every flag | **Implemented and verified** | Each period carries a `reason` (dates, days, threshold, minimum, peak) and coverage notes for adjacent unknown days. Test: `test_unknown_day_breaks_consecutive_period`. Labelled "Elevated observed activity", with a disclaimer that it is not a warning. |

## Three-stage MODIS–VIIRS harmonization (added in 1.1)
| # | Stage | Status | Evidence |
|---|---|---|---|
| H1 | Spatial standardization | **Implemented and verified** | `harmonize._build_events` reuses the shared filters (`query.filtered_sql`, exact AOI before aggregation) and the integer grid rule at 0.1/0.25/0.5/1°. Per-sensor values only. Tests: `test_stage1_keeps_sensor_values_separate`, `test_aoi_filter_applies_before_matching`, `test_frp_metric`. |
| H2 | Temporal matching | **Implemented and verified; coverage not verifiable from FIRMS data** | Event clustering (20 min), candidate pairs within a configurable tolerance, deterministic one-to-one matching, proxy vs no-evidence classes, `coverage_verification = not_verified`. Tests: `test_stage2_matches_every_synthetic_pair`, `test_stage2_tolerance_excludes_pairs`, `test_terra_is_not_matched_to_aqua_pairs`, `test_proxy_evidence_is_distinguished_from_matches`, `test_greedy_matching_is_one_to_one_and_ordered`, `test_deterministic_results`. Real data: 113,567 Aqua–S-NPP matches, median \|Δt\| 13 min; Terra negative control 0 matches. Browser flow 14. |
| H3 | Statistical calibration | **Implemented and verified (method); performance measured, not independently validated** | OLS on ln(1+M) vs ln(1+V), chronological hold-out, MAE/RMSE/MBE and % improvement vs unadjusted, training-mean context. Tests: `test_fit_recovers_known_coefficients_exactly`, `test_prediction_formula_and_nonnegative_clamp`, `test_error_metrics_and_improvement`, `test_chronological_split_never_splits_a_day`, `test_stage3_chronological_holdout_and_improvement`, `test_explicit_split_date`. Real-data results in [HARMONIZATION_VALIDATION.md](HARMONIZATION_VALIDATION.md): detections MAE −76 %, RMSE −81 % vs unadjusted (run A); FRP not improved (run E). |

## Harmonization tab (added in 1.2)
| # | Task (priority) | Status | Evidence |
|---|---|---|---|
| H4 | Harmonization tab (P1) | **Implemented and verified** | New main-navigation tab `pages/HarmonizationPage.tsx`: workflow steps, sensor settings, three-stage cards, validation status. No existing page changed. Browser flow 15. |
| H5 | Calibrated results on the map (P1) | **Implemented and verified** | Layers Original MODIS / Original VIIRS / Experimental calibrated; estimates are per-cell sums on the comparison grid (purple ramp, labelled), no points created; only for runs passing the validity rules. Tests: `test_map_window_values`, `test_validity_fails_for_frp_and_small_samples`; flow 15 (map totals = daily series; calibrated availability follows validity). |
| H6 | Visualize the process (P1) | **Implemented and verified** | Matching layer (pairs, median \|Δt\|, one-sided cells), cell details with each pair's times, \|Δt\|, M, V, M̂; funnel events → candidates → matches; Δt histogram; regression scatter with fitted curve. |
| H7 | Calibration error map (P2) | **Implemented and verified** | Held-out MAE per region (0.1–2°), minimum held-out units (5–50), regions with too few or no held-out units marked. Test: `test_error_cells`; flow 15. Full archive: [AUDIT.md](harmonization/AUDIT/AUDIT.md). |
| H8 | Link to historical analysis (P2) | **Implemented; calibrated line correctly withheld on the real data** | Original vs calibrated series with a second, daily-total gate. On the full archive no configuration passes (Σ calibrated / Σ MODIS 0.22–0.24 or 2.7–3.8), so only original series are drawn; calendar and history unchanged. Tests: `test_series_matches_daily_and_gates_totals`, `test_series_hides_calibrated_when_totals_fail`; flows 15–16. |
| H9 | Audit of method and regression (P1) | **Done** | `harmonize-audit`: one-to-one matching, \|Δt\| within tolerance, coverage shares, no leakage (refit after deleting later data reproduces α, β exactly), metrics recomputed, alternatives (mean, median, ratio), FRP not claimed. [AUDIT.md](harmonization/AUDIT/AUDIT.md). |
| H10 | Testing and documentation (P1) | **Done** | 98 backend tests, 16/16 browser flows (map, calendar, timeline, AOI, Workbench unchanged), live deployment check; [CHANGES_1.2.md](CHANGES_1.2.md), Methodology §16, validation report "Application". |

## AOI Insights (added in 1.3)
| ID | Item | Status | Evidence |
|---|---|---|---|
| I1 | AOI Insights tab with role presets (Early warning, Emergency responder, Land manager, Scientist, All) | **Implemented and verified** | `pages/InsightsPage.tsx`; browser flow 17 |
| I2 | Fire regime and season tracker (A1, B4) | **Implemented and verified** | `insights.regime`; `test_regime_and_tracker`; full-archive check in TEST_RESULTS |
| I3 | Unusual conditions: robust score, daily, weekly and per cell (B2) | **Implemented and verified** | `insights.anomaly`, `cell_anomaly`; hand-computed z test; guard-rail test |
| I4 | Critical periods and readiness calendar (C1, C2) | **Implemented and verified** | `insights.critical`; hand-computed leave-one-year-out threshold test |
| I5 | Recurrence map and hotspot exports (A2, E2) | **Implemented and verified** | `insights.recurrence`, `/api/export/hotspots.*`; tests and flow 17 |
| I6 | Years, ENSO and IOD phases, analog years (D2, F2) | **Implemented and verified** | `climate.py` with checksummed NOAA files; `test_years_report_uses_noaa_phases`, `test_analog_groups_exclude_the_focus_year` |
| I7 | Compare areas (F1) | **Implemented and verified** | `insights.compare_aois`; API test |
| I8 | Status now from FIRMS NRT, on request only (D1) | **Implemented; verified with a mocked FIRMS** | `live.py`; NRT never stored, key never in responses; real FIRMS call not run from the container |
| I9 | Printable bilingual briefing EN/ID (E1) | **Implemented and verified** | `components/InsightsBriefing.tsx`; flow 17 checks both languages and the disclaimer |
| I10 | Method drawer, insights package, CLI, example notebook (G1, G4) | **Done** | `/api/export/insights.zip`, `cli insights`, `docs/notebooks/aoi_insights_api.ipynb` |
| I11 | NRT rows without a type no longer read as zero (all tabs) | **Fixed** | Default type filter `0,unknown`; test and TEST_RESULTS |
