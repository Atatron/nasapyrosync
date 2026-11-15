# PyroSync 1.5: change record (multi-sensor historical fusion and the adaptive map)

**Backup.** Version 1.4 is unchanged on the GitHub branch `legacy-v1.4-harmonization`. That is the state of `main` and of
production before this work: commit `7336a9f`, with the full archive from the public GitHub mirror. The earlier branches
`legacy-v1.3-blob`, `legacy-v1.2`, `legacy-v1.1`, `legacy-v1` and `backup-main-2026-11-15` are unchanged too. No stored data is
modified, and `PROCESSING_VERSION` is unchanged.

1.5 adds a **multi-sensor harmonized history**: Terra, Aqua, S-NPP, NOAA-20 and NOAA-21 calibrated to the MODIS Aqua scale and
averaged, never summed, with its own validation gate. It also adds an **adaptive map grid**, **Analyze Location** circles, a
FIRMS-style **detection popup** and a simpler **navigation**. Nothing that existed before is removed. The original detections,
every per-sensor series, the 1.0 event model, the 1.2 rules and the 1.4 day-level ratio are unchanged.
Method: [MULTISENSOR_FUSION.md](MULTISENSOR_FUSION.md).

## Added
| File | Purpose |
|---|---|
| `backend/pyrosync/fusion.py` | Platform records and gap days, the per-platform daily arrays, pairwise 1.4 ratios against Aqua, the fused series, the leave-reference-out validation (hold-out, rolling origin, high-fire, monthly, seasonal, transitions, missing data), the gate, effective coefficients and status, series, `daily_like`, map cells, regional check, reports, and the reference override used only by the CLI sensitivity run |
| `backend/tests/test_fusion.py` | 13 tests on SYNTHETIC TEST FIXTURES (software behaviour only, no scientific claim) |
| `frontend/src/fusion.ts`, `frontend/src/components/FusionParts.tsx` | Fusion types, the status pill, banner, history chart and diagnostics panel |
| `docs/MULTISENSOR_FUSION.md`, `docs/SCIENTIFIC_REFERENCES.md`, `docs/CHANGES_1.5.md` | Documentation |
| `docs/harmonization/FUSION/` | Generated real-data reports: runs N (Indonesia), K (Kalimantan), S (Sumatra) and T (Terra as reference, sensitivity), each with 0.5°, 1° and 2° regional checks |

## Changed
| File | Change |
|---|---|
| `backend/pyrosync/api.py` | New: `/api/fusion`, `/api/fusion/series`, `/api/fusion/map`, `/api/fusion/regions`, `/api/export/fusion.zip`, `/api/daily?fused=true`. The series parameter accepts `FUSED`, and `/api/insights/now` refuses it with 422 |
| `backend/pyrosync/aoi.py` | `circle:<lat>,<lon>,<radius_km>` AOIs: parsing, validation, canonical id and geodesic polygon |
| `backend/pyrosync/query.py` | 0.25° grid |
| `backend/pyrosync/analysis.py`, `insights.py`, `normalize.py` | `FUSED` as a detections-only series for weeks, rankings, comparison, baseline, elevated periods and AOI Insights. Insights cell maps use the Aqua reference |
| `backend/pyrosync/exports.py` | `fusion_zip`: report JSON and Markdown, fused daily CSV, manifest |
| `backend/pyrosync/cli.py` | `harmonize-fusion` command |
| `backend/pyrosync/config.py`, `frontend/package.json`, `frontend/package-lock.json` | Version 1.5.0 |
| `frontend/src/state.ts` | `gridMode` (Auto by default; an old `grid=` link opens as manual), `analyzeMode`, `clickAt`, `circleFrac`, `lastRegionAoi` and `view`, all in shared links |
| `frontend/src/components/MapView.tsx` | Display grid by zoom; Region AOI or Analyze Location; zoom-adaptive circle; Harmonized layer; detection popup with "Analyze around this detection"; restorable view; clean teardown |
| `frontend/src/pages/Explore.tsx` | Cards use the analysis grid and the map uses the display grid, so statistics never change with zoom; circle AOI card |
| `frontend/src/App.tsx` | Four main destinations plus a collapsible Advanced group. Harmonized Calendar opens on the fused series. FUSED survives the inventory check |
| `frontend/src/components/TopBar.tsx` | Harmonized series option; Auto grid; circle in the AOI selector |
| `frontend/src/pages/CalendarPage.tsx`, `HistoryPage.tsx`, `InsightsPage.tsx`, `HarmonizationPage.tsx`, `components/InsightsBriefing.tsx`, `insights.ts`, `hooks.ts`, `util.ts`, `index.css` | Fused series wiring, banners and the diagnostics panel |
| `frontend/e2e/run.mjs` | Flow 3 now clicks the renamed nav item; new flows 19 and 20 |
| `README.md`, `docs/METHODOLOGY.md` (§19–20), `docs/HARMONIZATION_VALIDATION.md`, `docs/TEST_RESULTS.md`, `docs/DEMO_SCRIPT.md` | Documentation |
| `frontend/dist/` | Rebuilt |

## Requirements from the 1.5 brief: status
| Item | Status |
|---|---|
| P0 multi-sensor fusion with reference scale, calibrated average, availability, missing ≠ zero, no leakage | Done: tested with fixtures and on real data |
| P0 validation with real data (leave-reference-out, hold-out, rolling origin, MAE/RMSE/bias, monthly, seasonal, years, high-fire, transitions, regional, missing) | Done: Indonesia passes; Kalimantan and Sumatra fail two checks each and are shown as experimental |
| P0 calendar and timeline integration | Done: Harmonized Calendar, History, elevated periods, Insights |
| P0 harmonized heatmap in Explore, labelled "Experimental Harmonized Activity Index" | Done |
| P0 original hotspots preserved, labelled "Observed Active-Fire Detections" | Done |
| P0 adaptive zoom grid, manual override, old bookmarks, region statistics fixed under zoom | Done: checked in browser flow 19 |
| P0 Analyze Location (geodesic circle, 22 % of the shortest map side, radius in km, recalculated on zoom) | Done |
| P0 Region AOI, drawn polygons, GeoJSON upload, shared links preserved | Done: flows 3 and 19 |
| P0 FIRMS-style popup with "Analyze around this detection"; missing fields shown as unavailable | Done |
| P0 shareable URL state | Done: circle and view restored in a fresh page (flow 19) |
| P0 regression tests | Done: backend 135/135, browser 20/20 |
| P1 four main destinations, advanced tools kept | Done |
| P1 performance (debounce, caching, stale requests) | Done: 300 ms debounced map moves, server cache keyed by revision, aborted stale map requests, a viewport bbox for fine grids |
| P1 reproducible HTTP 500s | None found: a sweep of 2,320 requests on the full archive returned no 5xx |
| P1 validation indicators | Done: status pills and banners, each linked to the diagnostics |
| P1 docs | Done |
| P2 MCD64A1 burned-area overlay | **Not done** (optional). The product is documented in SCIENTIFIC_REFERENCES.md |

## Known limitations
- 2000-11 to 2002-07 has no fused value, because only Terra exists then and Terra is not eligible.
- Kalimantan, Sumatra and most smaller areas are **experimental**: they fail the rules, mainly by underestimating on high-fire
  days. Only 36 % of 1° cells nationwide agree within 0.8–1.25×.
- The fusion is no more accurate than the best single-sensor ratio. Its gain is continuity.
- Coverage (swath, cloud, smoke) is not verified. Aqua is a reference scale, not ground truth, and has drifted since 2022.
- The read-only online demo holds whatever archive its deployment carries. The sample data (2023–2024) is too short to test the
  fusion, so it reports "Insufficient validation data".
