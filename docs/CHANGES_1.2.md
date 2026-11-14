# PyroSync 1.2: change record (Harmonization tab)

Backups: version 1.0.0 is unchanged on the GitHub branch `legacy-v1`, and version 1.1.0 (the state of `main` before this work, commit `afdcf75`) is unchanged on the new branch `legacy-v1.1`. No file was deleted except the old hashed build assets that every frontend build replaces.

The three harmonization stages of 1.1 were **not rebuilt**. They are reused exactly. Every number in the 1.1 validation reports is reproduced by 1.2 (the reports were regenerated with the same commands; only the validity section and the training-median row were added). 1.2 adds the application of a run (map, error map, series), explicit validity rules and an audit.

## Added
| File | Purpose |
|---|---|
| `backend/pyrosync/calibration.py` | Applies ONE harmonization run: per-cell map windows (original MODIS, original VIIRS, matches, experimental MODIS-scale estimates), per-region held-out error map with a minimum sample size, original vs calibrated time series with a held-out daily-total gate. Never writes to the database. |
| `backend/pyrosync/audit.py` | Reproducible audit (`harmonize-audit`): matching, coverage, leakage (including a refit with all later data deleted), metrics recomputed independently, simple alternatives (mean, median, ratio model), application results |
| `backend/tests/test_calibration.py` | 8 tests: validity passes and fails (FRP, small samples), report identical through both code paths, map-window values against hand computation and the daily series, error cells (grid multiples, thresholds, per-cell MAE), series equal to the daily series, totals gate (passes and hides the line), API endpoints, original data unchanged |
| `frontend/src/pages/HarmonizationPage.tsx` | The new **Harmonization** tab: workflow (region → compare → harmonize → evaluate → map → history), settings, three-stage pipeline cards, validation status |
| `frontend/src/components/HarmonizationMap.tsx` | Map with five layers (Original MODIS, Original VIIRS, Experimental calibrated, Matching, Calibration error), date and window controls, legends, cell details with matched pairs |
| `frontend/src/components/HarmonizationSeries.tsx` | Original vs calibrated series (monthly/daily), totals rules and daily-total check |
| `frontend/src/components/HarmonizationParts.tsx` | Validity checks table, status badge, pipeline cards, matching process (funnel, Δt histogram, classes), error comparison with constants |
| `frontend/src/harmonization.ts` | Types of the new endpoints, tab state, colour ramps for estimates and errors |
| `docs/harmonization/AUDIT/AUDIT.md`, `audit.json` | Generated audit of runs A–E on the full archive |
| `docs/CHANGES_1.2.md` | This file |

## Modified (and why)
| File | Change | Why it was necessary |
|---|---|---|
| `backend/pyrosync/harmonize.py` | `_harmonize` split into `_run` (returns the report plus the events, matches and units) and a thin wrapper; `harmonize()` without units now reads the report from the calibration core; `assess_validity()` and the `validity` key; `training_median_reference`; validity section in the Markdown report | The map, error map and series must come from the same run as the report. The median constant is the best constant for MAE and is needed for an honest "better than a constant" check. Numbers of 1.1 are unchanged (checked field by field against the 1.1 report of run A). |
| `backend/pyrosync/api.py` | `GET /api/harmonization/map`, `/errors`, `/series` | New read-only endpoints (also allowed in the online demo) |
| `backend/pyrosync/cache.py` | Invalidation listeners | The calibration cores live in their own small cache and must be cleared on every import |
| `backend/pyrosync/cli.py` | `harmonize-audit` sub-command | Reproducible audit |
| `backend/pyrosync/config.py` | `APP_VERSION = "1.2.0"` | Version. `PROCESSING_VERSION` unchanged: stored rows are processed exactly as before. |
| `frontend/src/App.tsx`, `state.ts` | Navigation entry and page id `harmonization` | The new tab. No existing page was changed or removed. |
| `frontend/src/components/Harmonization.tsx` | `export` added to its existing types, `CLASS_LABEL` and `Stage3` | Reused by the new tab. The Sensor Workbench panel itself is unchanged. |
| `frontend/src/components/ui.tsx` | `harmonize` icon | Navigation icon |
| `frontend/e2e/run.mjs` | Flows 15 (tab = API: stages, validity, map totals = daily series, calibrated availability follows validity, error map, series gate) and 16 (original-data pages unchanged) | Browser-level checks. Flows 1–14 unchanged and passing with the same values. |
| `frontend/package.json`, `package-lock.json`, `frontend/dist/*` | Version and rebuilt assets | Build output |
| `docs/harmonization/*/report.md`, `report.json` | Regenerated with the same commands | Adds the validity section and the median constant; all 1.1 numbers unchanged |
| `README.md`, `docs/METHODOLOGY.md` (§15 note, new §16), `docs/DATA_DICTIONARY.md` (§10), `docs/HARMONIZATION_VALIDATION.md` (median constant, Application, Audit), `docs/TEST_RESULTS.md`, `docs/CHECKLIST_18_SUBTASKS.md` (H4–H10) | Documentation | Describe the tab, the rules, the real results and their limits |

## Not changed
Explore map, timeline, calendar, history, comparison, rankings, baseline and elevated-period calculations, Sensor Workbench (including its harmonization panel), sensor filters, grid rules, ingestion, existing exports, start and import scripts, `requirements*.txt`, `vercel.json`, `api/index.py`, the online demo database. The NASA proposal documents were not touched. Calibrated values are never stored and never replace original observations anywhere outside the Harmonization tab.
