# PyroSync 1.1: change record (three-stage harmonization)

Version 1.0.0 is preserved unchanged on the GitHub branch `legacy-v1`. Version 1.1 extends it; no file was deleted except the old hashed build assets that every frontend build replaces.

## Added
| File | Purpose |
|---|---|
| `backend/pyrosync/harmonize.py` | Stages 1–3: comparison units, event matching, proxy/no-evidence classes, OLS calibration, chronological hold-out, MAE/RMSE/MBE, Markdown/CSV report writers |
| `backend/tests/test_harmonize.py` | 19 tests (exact coefficient recovery, clamp, metrics, deterministic one-to-one matching, tolerance, Terra negative control, proxy classes, AOI before matching, FRP metric, hold-out, explicit split, API and export, existing daily series unchanged) |
| `frontend/src/components/Harmonization.tsx` | Sensor Workbench panel: settings, Run button, stage cards, coefficient and error tables, log-log scatter with fitted curve, held-out daily sums, validation-package download |
| `docs/HARMONIZATION_VALIDATION.md` | Summary of 11 runs on the full archive, interpretation and limits |
| `docs/harmonization/*/report.md`, `report.json` | Generated per-run reports (reproducible with the CLI) |
| `docs/CHANGES_1.1.md` | This file |

## Modified (and why)
| File | Change | Why it was necessary |
|---|---|---|
| `backend/pyrosync/normalize.py` | `declared_window` also accepts `YYYY-MM-DD_YYYY-MM-DD.csv` | The full-history archive names files this way. Without it, every day of the archive would have no declared coverage and show as "unknown". The `_Nd` form is unchanged. |
| `backend/pyrosync/api.py` | `GET /api/harmonization`, `GET /api/export/harmonization.zip`; `demo_note` in `/api/health`; read-only message no longer names the 2023–2024 sample | New endpoints; the online demo now holds different data, so its description is read from the database instead of being hard-coded. |
| `backend/pyrosync/exports.py` | `harmonization_zip()` appended | Validation package with the existing manifest builder. Existing exports untouched. |
| `backend/pyrosync/cli.py` | `harmonize` sub-command | Reproducible validation reports from the command line. |
| `backend/pyrosync/query.py` | `_global_gap_days` uses a stored `gap_days` list when the database has one | Only the online demo database (a Kalimantan subset) carries it, so coverage states online match the full local archive. Normal databases are unaffected (tested). |
| `backend/pyrosync/config.py` | `APP_VERSION = "1.1.0"` | Version bump. `PROCESSING_VERSION` is unchanged: stored rows are processed exactly as before. |
| `backend/tests/test_normalize.py`, `test_api_exports.py` | 1 + 2 tests added | Cover the new file-name form, the demo note and the gap-day override. No existing test was changed. |
| `frontend/src/pages/Workbench.tsx` | Renders `<Harmonization />` after the per-sensor series | Placement of the new panel. |
| `frontend/src/components/ui.tsx` | Registers the ECharts `ScatterChart` | Needed for the calibration scatter plot. |
| `frontend/src/App.tsx`, `pages/DataMethods.tsx` | Demo banner and notice show `demo_note` from the server | The demo data changed; the text must describe what is really online. |
| `frontend/e2e/run.mjs` | Flow 14 (harmonization UI = API, chronological split, coverage not claimed) | Browser-level check of the new feature. Flows 1–13 unchanged and passing with the same values. |
| `frontend/package.json`, `package-lock.json`, `frontend/dist/*`, `tsconfig.tsbuildinfo` | Version and rebuilt assets | Build output. |
| `deploy/build_demo_db.py` | `--from-db`, `--aoi`, `--platforms`; blanks `record_key`; stores `demo_subset` and `gap_days` | The full archive does not fit Vercel; the demo is built as a documented subset. File-based builds still work. |
| `deploy/pyrosync-demo.duckdb` | Kalimantan, Terra + Aqua + S-NPP, 2000–2026 (72 MB) | New online demo data. |
| `README.md`, `docs/METHODOLOGY.md` (§3 note, §8, §13, §14, new §15), `docs/DATA_DICTIONARY.md` (§9), `docs/TEST_RESULTS.md`, `docs/CHECKLIST_18_SUBTASKS.md` | Documentation | Describe the method, results, tests and the new data honestly. |

## Not changed
Map, timeline, calendar, history, comparison, rankings, baseline and elevated-period calculations, sensor filters, grid rules, existing exports, ingestion of existing file names, start and import scripts, `requirements*.txt`, `vercel.json`, `api/index.py`. The NASA proposal documents were not touched.
