# PyroSync 1.4: change record (day-level ratio for daily totals)

Backup: version 1.3 (the state of `main` before this work, commit `5077b98`, with the Vercel Blob full archive) is unchanged on the GitHub branch `legacy-v1.3-blob`. The earlier branches `legacy-v1.2`, `legacy-v1.1`, `legacy-v1` and `backup-main-2026-11-15` are unchanged too. No stored data is modified, and `PROCESSING_VERSION` is unchanged.

1.4 adds a second calibration method, next to the 1.0 event model: the **day-level ratio** (`pyrosync-aggregate-1.0`). It applies to AOI daily totals and has its own stability gate (`pyrosync-aggregate-gate-1.0`). The calibrated line and the map index are drawn only where the gate passes for the exact filters, AOI and sensor pair. History and AOI Insights get an optional comparison that is off by default. Nothing that existed before is removed. The event model, its validity rules and the 1.2 daily-total rules are unchanged. Why and how: [HARMONIZATION_UPDATE_REPORT.md](HARMONIZATION_UPDATE_REPORT.md). Task audit: [HARMONIZATION_TASK_STATUS.md](HARMONIZATION_TASK_STATUS.md).

## Added
| File | Purpose |
|---|---|
| `backend/pyrosync/aggregate.py` | Daily arrays (checked against `/api/daily`), ratio fit, month-block bootstrap, split rule, held-out and rolling-origin evaluation, gate, report, series, map augmentation, regional ratio, Markdown reports |
| `backend/tests/test_aggregate.py` | 5 tests on SYNTHETIC TEST FIXTURES: fit and gate, no leakage plus drift detection, unknown days and monthly sums, short history, API, ZIP and unchanged originals |
| `frontend/src/components/HarmonizationAggregate.tsx` | Validation panel, ratio series, gate badge and the History/Insights comparison (`ModisEquivalentComparison`) |
| `docs/harmonization/AGGREGATE/` | Generated reports for runs A, C, D and F (`harmonize-aggregate --with-events`), the Aqua drift diagnostic, and the planning prototype with its results |
| `docs/HARMONIZATION_UPDATE_REPORT.md`, `docs/HARMONIZATION_TASK_STATUS.md`, `docs/CHANGES_1.4.md` | Documentation |

## Modified (and why)
| File | Change | Why |
|---|---|---|
| `backend/pyrosync/api.py` | `/api/harmonization/aggregate`, `/aggregate/series`, `/aggregate/regions`. `/api/harmonization/map` also returns `value_ratio` per cell and `ratio_model` | New read-only endpoints |
| `backend/pyrosync/exports.py` | The harmonization ZIP also contains `aggregate_report.json` and `AGGREGATE_REPORT.md` | Validation package |
| `backend/pyrosync/cli.py` | `harmonize-aggregate --out DIR [--runs A,C,D,F] [--with-events]` | Reproducible reports |
| `backend/pyrosync/config.py`, `frontend/package.json` | Version 1.4.0 | Version |
| `frontend/src/pages/HarmonizationPage.tsx` | New section 5, "Validate daily totals". Map and history are renumbered 6 and 7. The history panel has a "Calibration method" switch (day-level ratio by default, with the 1.0 event model kept) | Tab integration |
| `frontend/src/components/HarmonizationMap.tsx` | "Estimate" switch on the calibrated layer (event model, or ratio index). "Error view" switch on the error layer (unit MAE, or regional daily totals). A ratio legend, and a ratio summary in the side panel | Map integration |
| `frontend/src/pages/HistoryPage.tsx`, `InsightsPage.tsx` | One panel each with the comparison, off by default | Historical integration (gated) |
| `frontend/src/harmonization.ts` | Types and state for the above | — |
| `frontend/e2e/run.mjs` | Flow 15 clicks "Event model (1.0 baseline)" before reading the 1.0 series. New flow 18 | The panel's default changed; browser check of the new views |
| `backend/tests/test_harmonize.py` | `test_api_and_export` expects the two added ZIP files, and the four original files are still required | The package gained files; no result changed |
| `README.md`, `docs/METHODOLOGY.md` (new §18), `docs/HARMONIZATION_VALIDATION.md` (type-filter note, 1.4 section), `docs/TEST_RESULTS.md` | Documentation | — |

## Not changed
Ingestion, stored rows, grid rules, the 1.0 event model and its rules, the Explore map, the calendar, the statistics of the history and Insights pages (they still use original observations), the Sensor Workbench, existing exports, Vercel and Blob deployment files, and `requirements*.txt`. The NASA proposal documents were not touched.

## Deployment
The work goes on the branch `feature/1.4-harmonization`, then a Vercel preview, then `main` and production only after the team approves the preview. The deployment state is recorded in the final report of this work and is not claimed here.
