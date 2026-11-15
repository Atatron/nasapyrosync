# PyroSync UI 1.7: decluttered shell, map stage, faster loading

Frontend 1.7.0 builds on UI 1.6. The FIRMS data, the harmonization math, the Python/FastAPI endpoints and the
URL hash routing (`#page=…&aoi=…`) are unchanged. There is one deployment-layer addition: `api/index.py` sets CDN
cache headers (see "Speed" below). The backend still reports version 1.5.0.

## What changed

| Area | Change |
|---|---|
| Shell | Desktop: the top-bar hamburger is gone; the sidebar's own **Collapse** button is the only toggle. Below 1024 px the sidebar is a hidden drawer, so a menu button stays there (it is the only way to open it). |
| Shell | The "Indonesia AOI" block (IDN / KAL / SUM / Province) is removed from the sidebar; the top-bar area selector is the single region control. Sidebar: brand, the five workspaces (Explore, Calendar, Insights, Harmonization, Methods; order unchanged, no "&"), observations badge, Light/Dark, Collapse. |
| Explore | The six KPI cards are removed. Per-sensor detections and occupied cells for the map window now sit in the map's control bar. |
| Explore | The "Filters applied" card is removed; the same disclosure (quality rules, included/excluded types, revision, data warnings) is now at the bottom of the **Filters** popover under "Applied to the current results". |
| Explore | Map stage: 16:9 (at least 540 px tall on desktop) with a control bar below it: histogram + scrubber, previous / play / next day, date, speed, Daily / 7-day / 30-day, layer pills (Detections, cells, Harmonized), imagery/basemap, live counters, and on the right: panel, theater and full-screen buttons. Esc leaves theater / full screen. |
| Explore | Map tools: the floating controls (Region AOI / Analyze Location, grid, Upload GeoJSON, Clear AOI, Diagnostics) are in one **Map tools** popover. "Back to region" stays visible on the map while a click-to-analyze circle is active. The legend can be folded (folded by default on phones). |
| Explore | Right drawer (w-80): Selected day (status shown as a swatch next to each sensor) and Elevated observed activity (bounded at 320 px, with the period count and sensor). It collapses in theater and full screen and comes back when you return to the default size. |
| Calendar | Day cells have 8 px gaps (`gap-2`, `rounded-lg`, `p-2.5`). The separate playback bar is gone: month/year navigation and day stepping (previous / play / next, date, speed) share one header inside the calendar card. |
| Harmonization | The read-only "Region / Analysis period / Quality filters (top bar)" block is removed. The pairwise-run controls (VIIRS sensor, MODIS platform, tolerance, grid, measurement, held-out share, Run) remain in a compact "Pairwise MODIS–VIIRS calibration run" panel, because no other control sets them. |
| Tables | Long tables are bounded at 340 px with a border and sticky headers: platform weights, held-out daily totals, gate checks, aggregate held-out and per-year tables, critical periods, annual summary, years, source records. |
| Fixes | Info tooltips and two map notices were not centred: the 1.6 colour sweep had turned `translate` into `tranzinc`. Fixed. The timeline's map-window shading used a navy tint; now neutral zinc. |

## Speed (chosen option: browser + CDN caching)

* **Browser cache that survives reloads** (Cache Storage). Answers are keyed by dataset revision, processing version,
  observation count, date range and app version, so a new dataset or app version never reuses old answers. Live or
  per-request endpoints are never stored (health, FIRMS near-real-time, imports, uploads, imagery, inventory, AOIs, regions).
* **Prefetch**: after the selected day settles, the previous and next day (map grid and counters) are fetched quietly.
* **Smaller first download**: pages and the chart library load on demand. Main bundle 870 KB → 262 KB (gzip 286 → 82 KB).
* **CDN**: in the read-only demo, successful GET answers carry `Cache-Control: public, max-age=0, s-maxage=86400,
  stale-while-revalidate=604800`, so Vercel's edge answers repeat requests. Not cached: health, FIRMS, insights/now,
  imports, uploads, imagery, AOIs, and any non-200 answer. A new deployment purges the edge cache.
* **Loading progress**: a bar under the top bar shows finished vs started data requests ("Loading data · 2 of 7") and
  disappears when the burst is done. Background prefetches are not counted.

## Not changed

Backend Python, ingestion, harmonization/fusion math, query logic, the seven page ids of the hash, dataset hooks, and
every number shown. `git diff backup/ui-1.6 -- backend` is empty.

## 1.7.1: all 38 provinces in the area list

* The area selector now lists all 38 Indonesian provinces, including North Kalimantan and the 2022 Papua provinces
  (South, Central and Highland Papua, Southwest Papua), under "Provinces (38)". Indonesia, Sumatra and Kalimantan stay
  under "Country and islands" with unchanged boundaries, so their numbers do not change.
* Province outlines come from Badan Informasi Geospasial (BIG), via github.com/ardian28/GeoJson-Indonesia-38-Provinsi
  (MIT). Each province is trimmed to the Natural Earth national outline and simplified at 0.002°, so no detection is
  counted in two provinces and no province reaches outside Indonesia. `tools/build_regions38.py` rebuilds the file.
* Checked on the full archive: 0 detections in two provinces, 0 outside the Indonesia boundary, and 8,763,495 of the
  8,779,400 Indonesia detections (99.8 %) fall in a province; the rest sit in small coastal gaps.
* The 7 provinces that were already listed (Riau, Jambi, South Sumatra, four in Kalimantan) keep their ids, so shared
  links still work, but their outlines now follow BIG, so their totals shift slightly. East Kalimantan no longer
  includes North Kalimantan.
* Only data file changed in the backend: `backend/pyrosync/resources/regions.geojson`. No Python code or math changed.
