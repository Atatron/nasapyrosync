# PyroSync — Fire history, in context

A local web application for exploring historical NASA FIRMS active-fire detections (MODIS and VIIRS) over Indonesia, with a day-by-day timeline, a burning calendar, area-of-interest (AOI) selection, seasonal and annual patterns, a baseline-eligibility check, explainable "elevated observed activity" periods, and (since 1.1) a three-stage MODIS–VIIRS harmonization with a chronological hold-out validation.

> Independent hackathon prototype using NASA FIRMS data and, where enabled, NASA GIBS imagery. Not an official NASA application.

Everything runs on your own computer at **http://127.0.0.1:8000**. Nothing is published to the internet. The only outside requests are optional ones: NASA GIBS satellite-imagery tiles and the Esri basemap, which your browser fetches when you pick them, and the FIRMS API, which runs only if you add a key.

---

## 1. Quick start

### Requirements
- **Python 3.11 or newer** (tested with 3.13). On Windows, tick "Add python.exe to PATH" in the installer.
- Node.js is **not** needed. The built web interface (`frontend/dist`) is included. You only need Node.js 20.19+ or 22.12+ if you change the frontend code.
- About 1 GB of free disk space for the Python packages and the database.

### Start
| System | Command |
|---|---|
| Windows | Double-click `scripts\start.bat` |
| macOS / Linux | `./scripts/start.sh` in a terminal, from the project folder |

The first run creates a private Python environment (`.venv`) and installs the tested package versions listed in `backend/requirements.lock.txt`, which takes a few minutes. Later runs start in seconds. When the window shows `Uvicorn running on http://127.0.0.1:8000`, open **http://127.0.0.1:8000** in your browser. To stop the app, press `Ctrl+C` or close the window.

To use another port, set it in `.env` (`PYROSYNC_PORT=8010`) or run `PYROSYNC_PORT=8010 ./scripts/start.sh`.

## 2. Import the sample data (`indonesia.zip`)

The sample ZIP is included at `sample_data/indonesia.zip`. It holds 294 FIRMS CSV files: MODIS_SP and VIIRS_NOAA20_SP, 2023-01-01 to 2024-12-31, with 566,644 rows.

**In the browser (recommended):**
1. Open **Data & Methods → Import**.
2. Choose `sample_data/indonesia.zip` and click **1 · Upload & inspect**. You get a validation report without anything being committed yet: columns, previews, platforms, versions, date range, rejected rows, and duplicates.
3. Click **2 · Commit import**. The import takes about 20 seconds on a 4-core laptop.

**From the command line** (stop the server first, because the database allows one writing process at a time):
```bash
./scripts/import.sh sample_data/indonesia.zip                         # macOS / Linux
powershell -ExecutionPolicy Bypass -File scripts\import.ps1 sample_data\indonesia.zip   # Windows
```
Add `--dry-run` to only inspect. Each import writes a JSON validation report and a rejected-rows CSV under `data/reports/`.

Importing the same file again is safe. Duplicates are recognised record by record, the counts stay the same, and the dataset revision does not change.

### Full history (2000–2026)
The full Indonesian FIRMS archive (`indonesia_full_history.zip`, 194 MB, 3,886 CSV files) is too large for GitHub, so it is not in the repository. Import it the same way, preferably from the command line:
```bash
./scripts/import.sh path/to/indonesia_full_history.zip        # about 9 minutes on a 4-core machine
```
Result on the development machine: 10,917,537 rows, 0 rejected, 2000-11-01 to 2026-11-14, MODIS Terra and Aqua, VIIRS S-NPP, NOAA-20 and NOAA-21. With this history the multi-year baselines unlock by themselves.

## 3. Adding future data (upgrading the website)

PyroSync adapts to new data without code changes:

1. Download more data from FIRMS ([archive download](https://firms.modaps.eosdis.nasa.gov/download/) or the Area API) as CSV or ZIP. MODIS (`brightness`/`bright_t31`) and VIIRS (`bright_ti4`/`bright_ti5`) schemas from any satellite are accepted: Terra, Aqua, NOAA-20, NOAA-21 and Suomi NPP.
2. Import it the same way, through **Data & Methods → Import** or `scripts/import.sh path/to/folder_or_zip`. Folders are scanned recursively.
3. The app picks up the new dataset revision automatically. Date ranges, year presets, calendars, available sensors and histories extend to whatever is loaded.

What the importer does with new data:
- Rows are assigned to days by their own `acq_date` and `acq_time` (UTC), never by the file name.
- Exact duplicates from overlapping downloads are stored once.
- **SP (standard/archive) replaces NRT** for the same satellite and UTC day. The NRT rows are kept for audit but excluded from analysis, so nothing is double counted.
- File names like `2024-06-19_5d.csv` or `2024-06-19_2024-06-23.csv` are recorded as *declared download windows*. Days inside a window with no rows become "zero detections reported". Days that no window covers stay "unknown". If your files have no such names, declare the interval yourself: `--declare 2025-01-01 2025-03-31` (optionally `--bbox W S E N`).
- **Baselines unlock by themselves.** When at least five comparable prior years are loaded (see Methods), "unusual above/below" flags and the baseline threshold mode become available. With the 2023–2024 sample they are honestly shown as *insufficient history*.

Large archives can be several GB. The CLI is faster for those, and the upload limits are configurable in `.env`.

### Optional: FIRMS API refresh
Copy `.env.example` to `.env` and set `FIRMS_MAP_KEY=` to your key ([request one](https://firms.modaps.eosdis.nasa.gov/api/map_key/)), then restart. **Data & Methods → FIRMS API** downloads a source, bounding box and date range in documented ≤5-day windows, caches each window on disk, and imports it with verified request intervals. The key stays on the backend. It never reaches the browser, the exports, or the logs.
**Status: the connector is tested with simulated responses (invalid key, rate limit, empty result, cancel, network failure). Authenticated live retrieval has not been verified: the development machine could not reach NASA servers. Test it once on your own computer with your key.**

## 4. Using the app (where things are)
- **Explore**: the map with grid cells or individual detections, the timeline (prev/next, play, speed, date picker, scrubber, daily/7-day/30-day window, histogram), summary cards and the details panel. The map always shows two separate labels, "Fire observations: [window] UTC" and "Satellite imagery: [date], [product]".
- **Burning Calendar**: a month grid with keyboard navigation, month/year navigation, a year overview and ISO-week heatmaps. Clicking a day selects it everywhere.
- **Historical Patterns**: monthly, seasonal and annual summaries; a 2023-vs-2024 comparison; baseline eligibility; rankings; elevated periods with editable rules.
- **Sensor Workbench**: per-sensor series, union versus sum of cells, the **MODIS–VIIRS harmonization** panel (choose the sensor pair, time tolerance, grid and measurement, press *Run harmonization*, download the validation package), confidence and type breakdowns, and paged source records.
- **Data & Methods**: import, current data, import history, the FIRMS API, exports and view-config restore, and the full methodology.
- **Export** (top bar): daily summary CSV, filtered observations CSV, aggregated grid GeoJSON and AOI GeoJSON, each with a `manifest.json` that records the filters, revision and definitions. You can also export a view configuration or copy a local view URL. These contain settings only, never data or credentials.

### Harmonization from the command line
```bash
cd backend
../.venv/bin/python -m pyrosync.cli harmonize --start 2012-01-20 --end 2026-11-14 --out ../harmonization_run
# options: --aoi region:kalimantan --viirs VIIRS_N20 --modis Aqua,Terra --tolerance 60 --grid 0.25 --metric frp_sum
#          --unit-set matched_plus_proxy --test-fraction 0.3 --split-date 2022-01-01 --no-units
```
It writes `report.md`, `report.json` and `units.csv`. See Methodology §15 for the method and what the results do and do not mean.

## 5. Troubleshooting
| Symptom | Fix |
|---|---|
| `PyroSync needs Python 3.11 or newer` | Install Python from python.org, then run the start script again. |
| `pip` fails on a pinned version | The script falls back to `backend/requirements.txt` (compatible ranges) automatically. If that also fails, upgrade pip: `.venv/bin/python -m pip install -U pip` (Windows: `.venv\Scripts\python.exe -m pip install -U pip`). |
| `Address already in use` | Another program uses port 8000. Set `PYROSYNC_PORT=8010` in `.env`. |
| CLI import says the database is locked | Stop the running server (`Ctrl+C`) or import through the browser. |
| Imagery shows "tiles failed to load" | You are offline or NASA GIBS is unreachable. Fire analysis still works. Choose "None (offline)" as the basemap. |
| "Imagery unavailable for this date" | GIBS has no layer for that day. You can explicitly click "Show nearest available date", which is then labeled SUBSTITUTED. |
| Page says "Cannot reach the PyroSync backend" | The start script is not running. Start it and reload. |
| Start over with an empty database | Stop the server and delete the `data/` folder. Your original files are untouched. |
| Windows blocks `start.bat` | Right-click → Properties → Unblock, or run `powershell -ExecutionPolicy Bypass -File scripts\start.ps1`. |

## 6. Upgrading PyroSync itself
The previous version (1.0.0) is kept on the GitHub branch **`legacy-v1`**. To go back to it: `git checkout legacy-v1` (your `data/` folder and `.env` are not affected). Version 1.1 only adds code, endpoints and a panel; it does not change stored data.

1. Stop the server. Back up the `data/` folder, which holds your database, reports and raw copies.
2. Replace the program files with the new version, but keep `data/` and `.env`.
3. Run the start script. It notices changed requirement files and reinstalls the packages. The database schema is created with `IF NOT EXISTS`, so existing data stays. If a release changes `PROCESSING_VERSION`, re-import your raw files (kept under `data/raw/`) to apply the new processing.

## 7. Project layout
```
backend/pyrosync/    FastAPI app, DuckDB storage, ingestion, queries, analysis, exports, FIRMS/GIBS clients, CLI
backend/tests/       pytest suite (synthetic, clearly labelled fixtures in temporary folders)
frontend/src/        React + TypeScript + Vite + Tailwind; Leaflet (+ Geoman drawing), ECharts
frontend/dist/       Pre-built interface served by the backend
frontend/e2e/run.mjs 14 browser-level checks (Playwright)
scripts/             start/import scripts for Windows, macOS, Linux; boundary builder
sample_data/         indonesia.zip (the supplied FIRMS sample)
docs/                data dictionary, methodology, test results, demo script, 18-subtask checklist
data/                created on first run: database, reports, raw copies, caches (not shared)
```

## 8. Running the tests
```bash
cd backend && ../.venv/bin/python -m pytest -q          # backend: 90 tests
cd frontend && npm ci && npm run build && npm run e2e    # browser: 14 flows (needs Node + Playwright Chromium)
```
The browser checks start their own server on port 8765 with a temporary data folder, so they never touch your database. See [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md).

## 9. Documentation
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): methods, definitions, sources and limitations (§15: harmonization)
- [docs/HARMONIZATION_VALIDATION.md](docs/HARMONIZATION_VALIDATION.md): harmonization results on the full archive, with per-run reports in `docs/harmonization/`
- [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md): stored fields, export columns and API metrics
- [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md): what was run and the actual results
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md): a two-minute demonstration
- [docs/CHECKLIST_18_SUBTASKS.md](docs/CHECKLIST_18_SUBTASKS.md): implementation evidence per subtask

## 10. Online read-only demo (Vercel)
The repository can also be deployed to Vercel as a **read-only** demo with a fixed dataset built in. Since 1.1 the demo carries the full history for **Kalimantan only, MODIS (Terra, Aqua) and VIIRS S-NPP, 2000–2026** (2,234,041 rows); the banner on the site states exactly what it contains. Vercel functions have no permanent disk, so importing and the FIRMS refresh are switched off online. Everything else works as it does locally: map, timeline, calendar, history, AOIs and exports.

- `vercel.json` serves `frontend/dist` as static files and routes `/api/*` to `api/index.py`, which runs the same FastAPI backend with `PYROSYNC_READONLY=1`.
- The root `requirements.txt` lists only the packages the demo needs. pyarrow and pyproj are omitted, so the function fits Vercel's size limit.
- The demo database is `deploy/pyrosync-demo.duckdb` (about 72 MB), built from a local full-history database with
  `.venv/bin/python deploy/build_demo_db.py --from-db data/pyrosync.duckdb --aoi region:kalimantan --platforms Terra,Aqua,SNPP`.
  The full archive (about 336 MB even in compact form) does not fit Vercel's 250 MB function limit, so the demo is a subset. Days that are data gaps in the full archive are carried over, so coverage states match the local app. Harmonization "proxy" counts can be lower online, because detections outside Kalimantan are not in the demo.
- You can still build the demo from files instead: `deploy/build_demo_db.py sample_data/indonesia.zip` (the 1.0 demo).
- **To update the online demo with new data:** import locally as usual, rebuild the demo database, commit it, and push. Then redeploy in the Vercel dashboard (Deployments → Redeploy). Pushes do not deploy by themselves unless you connect the repository under Project Settings → Git. Keep the database under about 75 MB so the function stays under Vercel's 250 MB limit.
- Custom drawn or uploaded AOIs are kept in the function's temporary storage. After the function restarts, re-draw them.
- Deploying makes the demo **public** at its vercel.app address.

## Attribution
Fire data: NASA FIRMS (MODIS Collection 6.1 and VIIRS 375 m active-fire products). Imagery: NASA GIBS. *We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS).* Boundaries: Natural Earth (public domain). Basemap: Esri Canvas (© Esri, HERE, Garmin, © OpenStreetMap contributors).
