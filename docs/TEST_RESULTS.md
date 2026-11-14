# Test results

Every result below was produced by actually running the tests on **2026-11-14** (version 1.1.0, after the harmonization upgrade) in the development container: Linux 6.18, 4 vCPU Intel Xeon @ 2.30 GHz, 15 GB RAM, Python 3.13.18, Node 22.23.4, Chromium via Playwright 1.63. Nothing is reported as passed unless it was executed.

## Summary
| Suite | Command | Result |
|---|---|---|
| Backend unit/integration (pytest) | `cd backend && ../.venv/bin/python -m pytest -v` | **90 passed, 0 failed** (8.6 s): the 68 earlier tests unchanged, plus 19 harmonization tests (`test_harmonize.py`), 1 file-name window test and 2 demo tests |
| TypeScript type check | `cd frontend && npx tsc -b --noEmit` | **passed** (no errors) |
| Production build | `cd frontend && npm run build` | **passed** |
| Browser-level checks (Playwright) | `cd frontend && npm run e2e` | **14 of 14 passed** (the 13 original flows with unchanged results, plus flow 14 for harmonization), 0 uncaught page errors |
| Fresh-copy start (macOS/Linux script) | `./scripts/start.sh` in a clean copy without `.venv` or `data` | **passed**: created .venv, installed the locked packages, served `/api/health` |
| CLI import of the sample | `./scripts/import.sh sample_data/indonesia.zip`, twice | **passed**: 566,644 new rows, 0 rejected, revision 1. The second run gave 0 new, 566,644 duplicates, revision unchanged. |
| CLI import of the full-history archive | `./scripts/import.sh indonesia_full_history.zip` | **passed**: 3,886 files, 10,917,537 rows, 0 rejected, 2000-11-01 → 2026-11-14, 526 s |
| Harmonization validation runs | `python -m pyrosync.cli harmonize …` (11 configurations) | **completed**: results in [HARMONIZATION_VALIDATION.md](HARMONIZATION_VALIDATION.md) |
| Windows scripts (`start.bat`, `start.ps1`, `import.ps1`) | — | **Not executed**: no Windows machine was available. Written for Windows and reviewed, but unverified. |
| Live FIRMS API with a real MAP_KEY | — | **Not executed**: a key was provided and stored in the local `.env`, but the development container's network blocks NASA hosts (`CONNECT tunnel failed, 403`). The connector is tested with simulated HTTP responses only. |
| Live NASA GIBS tiles | — | **Not executed against NASA**: the container's network blocks NASA hosts. Tile URLs and date handling are verified by intercepting the requests. The DescribeDomains values were read from NASA during development via a separate fetch. |

All test fixtures are synthetic, labelled as such, and created in temporary directories. The browser checks run their own server on port 8765 with a temporary data directory. The only synthetic CSV, used in flow 11, is named `SYNTHETIC_TEST_FIXTURE_…` and never touches the real database.

## Backend tests → required cases
| Required case | Test(s) |
|---|---|
| MODIS numeric vs VIIRS categorical confidence | `test_modis_confidence_numeric_bins`, `test_viirs_confidence_categorical`, `test_type_and_confidence_filters`, `test_viirs_confidence_filter` |
| Time padding (402 → 04:02 UTC) | `test_acq_time_padding`, `test_time_padding_stored_as_utc` |
| Leap day and ISO week-year boundaries | `test_acq_date_strict_and_leap_day`, `test_declared_window_from_filename`, `test_iso_week_year_boundaries` (2020-W53, 2025-W01), `test_leap_day_counted_and_compare_excludes_feb29` |
| Negative-coordinate grid indexing | `test_negative_coordinate_grid_indexing`, `test_negative_coordinate_cells_in_db` |
| Exact duplicates and repeated imports | `test_exact_duplicates_and_reimport_idempotent` |
| Different platforms at the same location | `test_same_location_different_platforms_kept_distinct` |
| NRT/SP reconciliation | `test_nrt_superseded_by_sp` |
| Type filtering | `test_type_and_confidence_filters`, `test_observations_export_matches_points_and_filters` |
| AOI boundary points and exact polygon filtering | `test_aoi_boundary_points_included_and_exact_polygon` |
| Unknown coverage vs reported zero | `test_unknown_vs_zero_reported`, `test_zero_reported_inside_interval_unknown_outside`, `test_cli_declared_interval`, `test_gap_rule_is_relative_to_the_importing_batch`, `test_empty_result_imports_zero_reported` |
| Missing days in baseline and consecutive periods | `test_baseline_missing_coverage_years_not_counted`, `test_unknown_day_breaks_consecutive_period` |
| Insufficient history (initial sample) | `test_insufficient_history_two_years` |
| Zero baselines | `test_baseline_eligible_and_zero_baseline_suppresses_low` |
| Late data and cache invalidation | `test_late_data_invalidates_cache_and_extends_range` |
| Cross-panel consistency | `test_cross_panel_consistency` (daily = frame = points = history) |
| Exports match source queries | `test_daily_export_matches_query`, `test_observations_export_matches_points_and_filters`, `test_grid_geojson_matches_frame`, `test_aoi_post_and_export` |
| Additional | ZIP safety (`test_zip_*`, `test_not_a_zip`), AOI validation and EPSG:3857, FIRMS connector (invalid key, rate limit, empty result, cancel, network error, cache reuse, key redaction, window splitting), GIBS explicit-date URLs, upload → inspect → commit API flow, key never exposed in API/exports, union never sums sensors |

## Browser checks (actual output, final run)
```
PASS  1. App launches and shows an honest empty state — backend 1.0.0 on http://127.0.0.1:8765; no data shown before import
PASS  2. Sample import through the browser (upload → inspect → commit) — 566,644 observations, 2023-01-01 → 2024-12-31, revision 1
PASS  3. Changing the AOI changes the results — VIIRS N20 detections 2023-09-15: Kalimantan 384, Sumatra 646, drawn rectangle 84; calendar re-queried for the new AOI
PASS  4. Moving one day changes the fire query and labels — frame request date=2023-09-16 issued; label "Daily frame 2023-09-16 UTC"
PASS  5. Clicking a calendar day selects that date everywhere — calendar click → shared date 2023-09-20; map label and timeline date input follow; next-month and year navigation work
PASS  6. Changing the sensor updates dependent panels — elevated-period request and summary card switched to MODIS
PASS  7. Imagery tile requests include the selected date — 24 tile requests, all with /default/YYYY-MM-DD/; followed 09-15 → 09-16
PASS  8. Unavailable imagery is not replaced by another day — unavailable notice shown, 0 tiles requested, label keeps 2023-09-15 (nearest-date only on explicit click)
PASS  9. Rapid scrubbing never leaves stale results — settled on 2024-06-05; card 7 = API 7
PASS  10. Re-importing the same sample leaves counts unchanged — total 566,644 and revision 1 unchanged
PASS  11. An additional file extends coverage with no code changes (SYNTHETIC TEST FIXTURE) — range now 2023-01-01 → 2025-01-03; 2025-01-01..03 statuses zero_reported/detections/zero_reported; revision 2
PASS  12. CSV and GeoJSON downloads contain the filtered data — observations CSV 3180 rows (= API, window 09-09..09-15, type 0 only); grid 683 cells (= frame); AOI MultiPolygon
PASS  13. Analysis works without external imagery or network — history/baseline/elevated rendered offline (12 elevated periods); explore shows 384 detections with imagery blocked
PASS  14. Harmonization runs the three stages and matches the API — 5907 matched Aqua–N20 units; beta 0.196; held-out MAE 1.99 → 1.10

14/14 browser checks passed.
```
During this whole run every non-localhost request is aborted, so the app is exercised offline. GIBS tiles in flows 7–8 are intercepted and answered locally.

## Defects found by testing and fixed
1. A single CSV imported from a folder such as `MODIS_SP/` lost its SP stream, because only the file name was used as a hint. The parent folder name is now included (`test_single_csv_stream_from_parent_folder`).
2. The likely-gap rule used a global median, so a small later delivery's genuine zero days would have been shown as unknown. It is now evaluated per import batch (`test_gap_rule_is_relative_to_the_importing_batch`, browser flow 11).
3. The map's cell colour, the grid GeoJSON and the frame "union" summed MODIS and VIIRS detections. Cells are now coloured by the primary sensor's own count, the export has per-sensor counts only, and union detections and FRP are null everywhere.
4. The export menu stayed open after a download (browser flow 12), and a Leaflet animation error could fire when leaving the map mid-zoom. Both are fixed.
5. Empty values in `.env` overrode the defaults. They now fall back to the defaults.

6. (1.1) Event numbering in harmonization used a window ordered only by time, so detections with identical timestamps could be assigned to the previous event. Ordering now includes the row id (`test_stage1_keeps_sensor_values_separate` caught it).
7. (1.1) The scatter chart type was not registered with ECharts, which blanked the harmonization panel (browser flow 14 caught it).
8. (1.1) The proxy-evidence search was a correlated subquery (52 s for Kalimantan on the full archive). It is now a time-bucketed join (1 s) with identical class counts.

## Harmonization performance (full archive: 10,917,537 rows; same container, cold cache)
| Run | Time |
|---|---|
| Kalimantan, Aqua–NOAA-20, 2023–2024 | 1.0 s |
| Indonesia, Aqua–S-NPP, 2023–2024 | 1.8 s |
| Indonesia, Aqua–S-NPP, 2012–2026 (113,567 matches) | 12.5 s |

## Performance (sample: 566,644 rows; same container)
| Operation | Cold | Warm (cached) |
|---|---|---|
| Import `indonesia.zip` (294 CSVs) | 18.1 s | re-import 15.4 s (0 new) |
| `/api/inventory` | 0.077 s | 0.002 s |
| `/api/daily` Kalimantan, 731 days, all sensors | 0.27 s | 0.021 s |
| `/api/daily` whole extent | 0.12 s | 0.022 s |
| `/api/frame` Kalimantan, 1-day window | 0.039 s | 0.006 s |
| `/api/frame` Kalimantan, 30-day window | 0.105 s | 0.039 s |
| `/api/history` Kalimantan | 0.145 s | 0.005 s |
| `/api/elevated` / `/api/baseline` | 0.017 s / 0.030 s | 0.004 s / 0.011 s |
| `/api/export/daily.zip` | 0.019 s | 0.013 s |

Timings are wall-clock from `curl` against the local server. Laptop results will differ.
