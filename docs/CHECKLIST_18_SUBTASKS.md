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
| 14 | Calculate an eligible historical baseline | **Implemented with an identified verification limitation; blocked by missing data for the sample** | `analysis.compute_baseline` (≥5 prior years, ≥80 % coverage per ±15-day window, ≥100 reference days, P95/P5). The algorithm is verified by `test_baseline_eligible_and_zero_baseline_suppresses_low`, `test_baseline_missing_coverage_years_not_counted` and `test_insufficient_history_two_years`. **On the real 2023–2024 sample it is correctly ineligible ("Insufficient history for a robust multi-year baseline"). No scientifically established baseline exists until ≥5 prior years are imported.** |
| 15 | Flag supported above/below-baseline activity | **Implemented with an identified verification limitation; blocked by missing data for the sample** | Above/below flags only when eligible; low flags suppressed at P5 = 0; undefined ratio at median 0. Verified on synthetic multi-year fixtures only. No real-data flags are shown for the current sample. |

## Critical periods
| # | Subtask | Status | Evidence |
|---|---|---|---|
| 16 | Define an explainable threshold | **Implemented and verified** | Within-range percentile (default P90, ≥30 known days), user-defined threshold, or baseline (only when eligible). Rule and status text are shown in the UI and API. Test: `test_elevated_range_percentile_requires_30_known_days`. Kalimantan VIIRS cells: P90 = 190.4 cells/day. |
| 17 | Highlight qualifying periods | **Implemented and verified** | Red bands on the timeline histogram, flags on calendar days, Elevated lists (Explore/History), click-to-select. Browser flows 6 and 13 (12 periods for Kalimantan, VIIRS N20). |
| 18 | Explain every flag | **Implemented and verified** | Each period carries a `reason` (dates, days, threshold, minimum, peak) and coverage notes for adjacent unknown days. Test: `test_unknown_day_breaks_consecutive_period`. Labelled "Elevated observed activity", with a disclaimer that it is not a warning. |
