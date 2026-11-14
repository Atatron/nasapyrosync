# PyroSync 1.3: change record (AOI Insights)

Backups: version 1.2.0 (the state of `main` before this work, commit `1ade128`) is unchanged on the GitHub branch `legacy-v1.2`; `legacy-v1.1` and `legacy-v1` are unchanged too. No stored data is modified; `PROCESSING_VERSION` is unchanged.

1.3 adds the **AOI Insights** tab (Phases 1 and 2 of the plan): historical fire patterns, unusual conditions and critical periods for one area of interest and one sensor series, arranged for early warning, emergency responders, land managers and scientists. It describes observed detections only. It is not a forecast, not a fire-danger rating and not an official warning, and every response and the briefing say so.

## Added
| File | Purpose |
|---|---|
| `backend/pyrosync/insights.py` | Fire regime and season dates (A1), season tracker (B4), recurrence and chronic cells (A2), critical periods with a leave-one-year-out threshold (C1), readiness calendar (C2), robust anomaly score for days, weeks and cells with guard rails (B2), year report with climate phases and analog years (D2, F2), area comparison (F1), hotspot rows (E2), the demo-subset guard |
| `backend/pyrosync/climate.py`, `resources/climate/oni.txt`, `dmi.txt` | NOAA CPC ONI and NOAA PSL DMI (retrieved 2026-11-14, SHA-256 checked by a test) and the project's phase rules |
| `backend/pyrosync/live.py` | "Status now": the last 3–10 days of FIRMS NRT for the AOI, fetched on request through the server, cached in memory for 30 minutes, never stored, scored against the archive |
| `backend/tests/test_insights.py` | 14 tests (see TEST_RESULTS) |
| `frontend/src/pages/InsightsPage.tsx` | The tab: role presets, sensor series and "as of" controls, eight sections, method & data drawer |
| `frontend/src/components/InsightsMap.tsx` | Recurrence map and unusual-cells map |
| `frontend/src/components/InsightsBriefing.tsx` | Printable one-page briefing in English or Bahasa Indonesia |
| `frontend/src/insights.ts` | Types, tab state, colours and the bilingual wording |
| `docs/notebooks/aoi_insights_api.ipynb` | Example notebook reading the endpoints |
| `docs/CHANGES_1.3.md` | This file |

## Modified (and why)
| File | Change | Why |
|---|---|---|
| `backend/pyrosync/api.py` | `/api/insights/regime`, `/anomaly`, `/anomaly_cells`, `/recurrence`, `/critical`, `/years`, `/compare`, `/now`, `/climate`; `/api/export/hotspots.{csv,geojson,kml}`, `/api/export/insights.zip` | New read-only endpoints (allowed in the online demo) |
| `backend/pyrosync/exports.py` | Hotspot CSV/GeoJSON/KML and the insights package | Exports |
| `backend/pyrosync/cli.py` | `insights` sub-command | Reproducible package from the command line |
| `backend/pyrosync/query.py`, `frontend/src/state.ts`, `components/TopBar.tsx` | **Default type filter `0` → `0,unknown`**; the filter label says that FIRMS NRT has no type column | Defect fix chosen by Ata for every tab: FIRMS NRT area files have no `type` column, and with the 1.2 default every NRT row was dropped, so Kalimantan read as zero fire from Aug/Sep 2026 in all tabs. Users can still untick "unknown/missing type". |
| `backend/pyrosync/config.py`, `frontend/package.json` | Version 1.3.0 | Version |
| `frontend/src/App.tsx`, `components/ui.tsx`, `index.css` | Navigation entry, icons, briefing print styles | The new tab. No existing page was removed. |
| `deploy/build_demo_db.py`, `deploy/pyrosync-demo.duckdb`, `backend/pyrosync/api.py` (demo note) | `--slim` option; demo rebuilt for all of Indonesia (Terra, Aqua, NOAA-21); the banner says what is omitted | Ata asked for all of Indonesia online |
| `backend/tests/test_api_exports.py` | Expected default `types` | Follows the new default |
| `frontend/e2e/run.mjs` | Flow 17 | Browser check of the tab; flows 1–16 unchanged and passing |
| `README.md`, `docs/METHODOLOGY.md` (§4, new §17), `DATA_DICTIONARY.md` (§11), `TEST_RESULTS.md`, `CHECKLIST_18_SUBTASKS.md` (I1–I11) | Documentation | Methods, fields, real results and limits |

## Method decisions made during implementation
- **Critical vs unusual.** "Critical" uses an absolute threshold from all other complete years (a seasonal threshold spread "critical" weeks into quiet months); "unusual" is the separate, season-aware robust score.
- **Anomaly guard rail.** With a near-empty reference season the scale floor alone turned one detection into "well above normal"; a positive band now also needs the value above the reference 75th percentile and at least 3 above its median. A share "higher than X % of reference days" is reported with every score.
- **Analog years exclude the focus year**, so the current partial season does not vote in its own analog group.
- **Online demo now covers all of Indonesia** (Ata's choice): MODIS 2000–2026 and VIIRS NOAA-21 2023–2026, built with the new `--slim` option of `deploy/build_demo_db.py` (77 MB). All five satellites (338 MB) do not fit Vercel's function limit. Should a demo ever again hold one AOI only, Insights refuses other areas there instead of reading them as "no fire".

## Not changed
Ingestion, stored rows, grid rules, the Explore map, calendar, history, Sensor Workbench and Harmonization calculations (apart from the default type filter above), existing exports, start and import scripts, `requirements*.txt`, `vercel.json`, `api/index.py`. The NASA proposal documents were not touched.
