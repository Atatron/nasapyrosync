# Test results

Every result below was produced by actually running the tests on **2026-11-14** (version 1.3.0, after adding the AOI Insights tab); the 1.4 rows and the section "Day-level ratio (1.4)" were run on **2026-11-15** (version 1.4.0), and the 1.5 rows and the section "Multi-sensor fusion and map (1.5)" on **2026-11-15** (version 1.5.0), in the development container: Linux 6.18, 4 vCPU Intel Xeon @ 2.30 GHz, 15 GB RAM, Python 3.13.18, Node 22.23.4, Chromium via Playwright 1.63. Nothing is reported as passed unless it was executed.

## Summary
| Suite | Command | Result |
|---|---|---|
| Backend unit/integration (pytest), 1.5 | `cd backend && ../.venv/bin/python -m pytest -q` | **135 passed, 0 failed** (35 s): the tests of 1.4 unchanged, plus 13 tests in `test_fusion.py` (SYNTHETIC TEST FIXTURES) covering coefficients, eligibility and gate; calibrated mean, never a raw sum; platform availability; missing is not zero; model independent of the display range; held-out data never used in the fit, and drift caught; map cells adding up to the fused total; per-platform gap days; geodesic circle geometry and invalid circles; circle AOI filtering; the 0.25° grid; and the fusion, FUSED-series and circle API contracts |
| Browser-level checks, 1.5 | `cd frontend && npm run build && npm run e2e` | **20 of 20 passed**, 0 uncaught page errors. Flows 1–18 are unchanged, except that flow 3 now clicks "Harmonized Calendar". Flow 19 covers navigation, the adaptive grid with unchanged region statistics, the harmonized layer status, Analyze Location, a shared circle and the hotspot popup; flow 20 covers the Harmonized Calendar and Insights with the fused series |
| TypeScript type check and build, 1.5 | `npx tsc --noEmit -p . && npm run build` | **passed** |
| HTTP 5xx sweep, 1.5 (full archive) | 2,320 GET requests over 8 AOIs (regions, circles, an unknown region and an unknown custom id) × 5 date ranges (including an inverted range and the Terra-only period) × daily, frame, history, fusion, observations, analysis and Insights endpoints, with all 7 series values | **0 responses ≥ 500**. Bad input returns 422 with a message |
| Fusion validation runs, 1.5 | `python -m pyrosync.cli harmonize-fusion --out ../docs/harmonization/FUSION` | **completed** on the full archive in 2–6 s per run: [FUSION.md](harmonization/FUSION/FUSION.md) |
| Backend unit/integration (pytest), 1.4 | `cd backend && ../.venv/bin/python -m pytest -q` | **121 passed, 0 failed** (24 s): the 115 tests of 1.3 with Blob (one assertion in `test_api_and_export` extended to the two added ZIP files) plus 6 day-level ratio tests (`test_aggregate.py`) |
| Browser-level checks, 1.4 | `cd frontend && npm run build && npm run e2e` | **18 of 18 passed** (flows 1–17, flow 15 now selects the 1.0 event model before reading its series, plus flow 18), 0 uncaught page errors |
| Backend unit/integration (pytest), 1.3 | `cd backend && ../.venv/bin/python -m pytest -v` | **112 passed, 0 failed** (18 s): the 98 tests of 1.2 (one assertion updated for the new default type filter), plus 14 AOI Insights tests (`test_insights.py`: regime and tracker, insufficient history, recurrence, critical periods and readiness with a hand-computed threshold, anomaly score with a hand-computed z, guard rail against count noise, cell anomaly, years and NOAA phases, analog groups exclude the focus year, climate file checksums, API/compare/exports, NRT rows without a type, demo refuses areas outside its data, near-real-time view with a mocked FIRMS: nothing stored, key not leaked) |
| TypeScript type check | `cd frontend && npx tsc -b --noEmit` | **passed** (no errors) |
| Production build | `cd frontend && npm run build` | **passed** |
| Browser-level checks (Playwright), 1.3 | `cd frontend && npm run e2e` | **17 of 17 passed** in 1 min 36 s (flows 1–16 with unchanged results, plus flow 17 for AOI Insights: role presets, honest "not enough history" on the short sample, no FIRMS request until asked, English and Indonesian briefing with the disclaimer, method drawer, hotspot and package exports), 0 uncaught page errors |
| Fresh-copy start (macOS/Linux script) | `./scripts/start.sh` in a clean copy without `.venv` or `data` | **passed**: created .venv, installed the locked packages, served `/api/health` |
| CLI import of the sample | `./scripts/import.sh sample_data/indonesia.zip`, twice | **passed**: 566,644 new rows, 0 rejected, revision 1. The second run gave 0 new, 566,644 duplicates, revision unchanged. |
| CLI import of the full-history archive | `./scripts/import.sh indonesia_full_history.zip` | **passed**: 3,886 files, 10,917,537 rows, 0 rejected, 2000-11-01 → 2026-11-14, 526 s |
| Harmonization validation runs | `python -m pyrosync.cli harmonize …` (11 configurations) | **completed** and regenerated for 1.2: every 1.1 number reproduced exactly (0 differences, only the validity section and the median-constant row added). Results in [HARMONIZATION_VALIDATION.md](HARMONIZATION_VALIDATION.md) |
| Harmonization audit | `python -m pyrosync.cli harmonize-audit --out ../docs/harmonization/AUDIT` | **completed** on the full archive (runs A–E, 18–53 s each): [AUDIT.md](harmonization/AUDIT/AUDIT.md) |
| Windows scripts (`start.bat`, `start.ps1`, `import.ps1`) | — | **Not executed**: no Windows machine was available. Written for Windows and reviewed, but unverified. |
| Live FIRMS API with a real MAP_KEY | `GET /api/firms/availability` on the Vercel deployment (key stored as a sensitive server-side variable) | **Authenticated availability check passed** on 2026-11-14: FIRMS returned the date ranges of 12 products (e.g. MODIS_SP 2000-11-01 → 2026-08-31, VIIRS_SNPP_SP 2012-01-20 → 2026-07-31); the key did not appear in the response. A full Area-API download was not run, because downloads are disabled in the read-only demo and the development container cannot reach NASA. |
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
PASS  1. App launches and shows an honest empty state — backend 1.2.0 on http://127.0.0.1:8765; no data shown before import
PASS  2. Sample import through the browser (upload → inspect → commit) — 566,644 observations, 2023-01-01 → 2024-12-31, revision 1
PASS  3. Changing the AOI changes the results — VIIRS N20 detections 2023-09-15: Kalimantan 384, Sumatra 646, drawn rectangle 84; calendar re-queried for the new AOI
PASS  4. Moving one day changes the fire query and labels — frame request date=2023-09-16 issued; label "Daily frame 2023-09-16 UTC"
PASS  5. Clicking a calendar day selects that date everywhere — calendar click → shared date 2023-09-20; map label and timeline date input follow; next-month and year navigation work
PASS  6. Changing the sensor updates dependent panels — elevated-period request and summary card switched to MODIS
PASS  7. Imagery tile requests include the selected date — 36 tile requests, all with /default/YYYY-MM-DD/; followed 09-15 → 09-16
PASS  8. Unavailable imagery is not replaced by another day — unavailable notice shown, 0 tiles requested, label keeps 2023-09-15 (nearest-date only on explicit click)
PASS  9. Rapid scrubbing never leaves stale results — settled on 2024-06-05; card 7 = API 7
PASS  10. Re-importing the same sample leaves counts unchanged — total 566,644 and revision 1 unchanged
PASS  11. An additional file extends coverage with no code changes (SYNTHETIC TEST FIXTURE) — range now 2023-01-01 → 2025-01-03; 2025-01-01..03 statuses zero_reported/detections/zero_reported; revision 2
PASS  12. CSV and GeoJSON downloads contain the filtered data — observations CSV 3180 rows (= API, window 09-09..09-15, type 0 only); grid 683 cells (= frame); AOI MultiPolygon
PASS  13. Analysis works without external imagery or network — history/baseline/elevated rendered offline (12 elevated periods); explore shows 384 detections with imagery blocked
PASS  14. Harmonization runs the three stages and matches the API — 5907 matched Aqua–N20 units; beta 0.196; held-out MAE 1.99 → 1.10
PASS  15. Harmonization tab: stages, validation, map layers and error map match the API — 5907 matches; validity not_validated; map day 2024-09-15 MODIS 4 / VIIRS 651 (= daily series); 13 validated 0.5° regions; series totals not_validated
PASS  16. Original-data pages are unchanged by the Harmonization tab — daily series and 12 elevated periods identical after harmonization requests; calendar, workbench panel and explore (384 N20 detections) still render

16/16 browser checks passed.
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
9. (1.2) Calibration runs were kept after an import, so a later request could use a run fitted on older data. They are now cleared on every cache invalidation (caught by the tests in `test_calibration.py`).
10. (1.2) The daily-total test fixture had only 12 held-out days, below the 30-day minimum of the totals rule; the test now uses a 50 % hold-out so the rule can actually be exercised.
11. (1.2) The map's layer label overlapped the zoom control and the totals table overflowed on narrow screens. Both fixed (checked in screenshots).

## Harmonization performance (full archive: 10,917,537 rows; same container, cold cache)
In 1.2 the map, error-map and series requests reuse the run that produced the report. On the read-only demo database locally: Kalimantan run 7.5 s (36,893 matches), then map 0.1 s and series 0.7 s.

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


## AOI Insights (added in 1.3), checked on the full archive
Run locally on the full-history database (2000-11-01 → 2026-11-14), read-only, Kalimantan, MODIS (Terra + Aqua), as of 2026-11-14:
- Timings (first request, no cache): regime 1.6 s, anomaly (180 days) 0.2 s, recurrence 0.4 s, critical periods 0.4 s, years 0.1 s after the regime, compare Kalimantan + Sumatra 1.4–9.2 s. All are well inside the 60 s limit of the online demo.
- Season tracker: 70,762 detections by 14 Nov 2026, higher than 25 of 25 reference years (median 13,866): "among the highest on record". The 2026 dry season was an El Niño season (mean ONI of JAS and ASO 2.31 °C, NOAA CPC).
- **Defect found and fixed (affected 1.2 too):** FIRMS near-real-time area files have no `type` column, and the 1.2 default filter (type 0 only) dropped every NRT row, so every tab showed Kalimantan as having zero fire from 1 Sep 2026 (MODIS) and from 1 Aug 2026 (VIIRS); before the fix the tracker read "within the usual range". The default now includes "unknown/missing type" (Methodology §4, §17); `/api/daily` for 1–10 Sep 2026 now shows 3,084, 295, 1,631 … MODIS detections instead of zeros. Test: `test_nrt_rows_without_type_are_not_read_as_zero`.
- Usual season (median of complete years): start 08 Jul, peak 05 Sep, end 10 Oct; busiest week 24–30 Sep. Readiness: 24–30 Sep held a critical day in 13 of 26 complete years.
- Example notebook `docs/notebooks/aoi_insights_api.ipynb`: its code cells were executed as a script against this server and completed (tracker, anomaly, critical periods, analog years, recurrence, ZIP download). The notebook file itself is stored without outputs.
- CLI `python -m pyrosync.cli insights --aoi region:kalimantan --series MODIS --as-of 2026-11-14` wrote the 9-file package.
- **Not executed:** the "Status now" request against the real FIRMS API (the container cannot reach NASA); it is covered by a test with a mocked FIRMS response.

## Day-level ratio (added in 1.4)
Browser check 18, final run on 2026-11-15 (sample data, so the gate correctly reports "not validated": two years cannot give three rolling-origin years):
```
PASS  15. Harmonization tab: stages, validation, map layers and error map match the API — 5907 matches; validity not_validated; map day 2024-09-15 MODIS 4 / VIIRS 651 (= daily series); 13 validated 0.5° regions; series totals not_validated
PASS  18. Day-level ratio (1.4): gate badge, series, map views and the off-by-default History/Insights comparison follow the API — sample Kalimantan Aqua–N20: aggregate gate not_validated (UI = API); series line withheld; map ratio layer withheld; 22 regions within 0.8–1.25×; history gate not_validated; insights gate not_validated; nothing requested before the toggle

18/18 browser checks passed.
```
Full archive, through the API (`TestClient`, same container): `/api/harmonization/aggregate/series` for Indonesia, Aqua–S-NPP, 2012-01-20 → 2026-11-14 returns `passes` with a calibrated line (0.9 s warm). 2024-01-01 → 2026-11-14 returns `not_validated` (enough rolling-origin years fails). Kalimantan with Aqua–NOAA-20 from 2018-04-01 returns `not_validated` (most years close to MODIS fails). The generated reports and every gate check are in [`harmonization/AGGREGATE/`](harmonization/AGGREGATE/AGGREGATE.md). The live preview and production checks are reported with the deployment, not here.

## Multi-sensor fusion and map (added in 1.5)
Browser checks 19 and 20, final run 2026-11-15T08:28Z, version 1.5.0, on the sample data. The sample spans only two years, so the fusion correctly reports "insufficient": no pair can pass three rolling-origin years.
```
PASS  19. 1.5 map: 4 destinations, adaptive grid with fixed region statistics, harmonized layer status, Analyze Location, shared circle, hotspot popup — nav 4+advanced; grid 0.25→0.1→0.05 with zoom, region N20 384 unchanged; harmonized status insufficient (= API); circle 35.6 → 17.8 km on zoom (= 2 N20 detections, = API); shared link restored 17.8 km; popup + Analyze around → circle at -0.8681, 117.0530
PASS  20. Harmonized Calendar and Insights show the fused series with the API validation status — sample: fusion status insufficient (Insufficient validation data); eligible none; calendar and Insights banners = API (4 Insights requests for FUSED); fusion.zip OK

20/20 browser checks passed.
```
Full archive, through the API (`TestClient`, same container, cold cache):

- `/api/fusion` for Kalimantan takes 4.4 s, which includes the Indonesia-wide eligibility model. It returns `not_validated`.
- `/api/fusion` for a 50 km circle at -2.2°, 113.9° takes 1.6 s. It returns `not_validated`, with the circle's own coefficients.
- Once the model is cached, `/api/fusion/series` and `/api/fusion/map` take 0.0–0.1 s. The first harmonized map frame takes 3.9 s.
- Every FUSED path of `/api/weeks`, `/rankings`, `/elevated`, `/baseline`, `/compare`, `/insights/*` and `/history` returns 200 for detections. With the cells metric they return 422, as does `/api/insights/now?series=FUSED`.

Defects found by the 1.5 tests and fixed:

- The inventory check reset `series=FUSED` to a single sensor if the user pressed Harmonized Calendar, or opened a shared FUSED link, before the inventory had loaded. FUSED is now kept whenever MODIS is present.
- Leaving Explore could raise `Cannot read properties of undefined (reading '_leaflet_pos')`, because `map.stop()` fired a final `moveend` after the debounce timer was cleared. The handlers are now removed first, and a late call is ignored.
- A shared Analyze Location link recomputed the circle for the recipient's screen size on load. The radius in the link is now kept; only a later zoom changes it.
