# PyroSync UI 1.6: interface refactor (frontend only)

**Scope.** Only `frontend/` changed. No Python/FastAPI file, ingestion script, harmonization or fusion calculation, grid binning,
percentile rule or API contract was modified (`git diff 8a5b7b9 -- backend api deploy` is empty). The URL hash keys and the seven
`page=` values are unchanged, so every existing link still opens the same content. The backend still reports 1.5.0.

## What changed
| Area | Change |
|---|---|
| Colours (`index.css`) | Neutral zinc tokens. Light: background #FAFAFA, cards white, borders #E4E4E7, text #09090B / #71717A. Dark: background #09090B, cards #18181B, borders #27272A, text #FAFAFA / #A1A1AA. Slate/navy hex values in charts and map outlines replaced by zinc. Component classes moved into `@layer components` so Tailwind utilities win |
| Navigation (`App.tsx`, `workspace.ts`) | Five fixed, single-word workspaces with Lucide icons: Explore, Calendar, Insights, Harmonization, Methods. Order never changes; no “&” in names. Old pages map onto them: `history` → Insights › Seasonal History, `workbench` → Harmonization › Sensor Workbench / Source Records, `data` → Methods |
| Sidebar | Collapsible on desktop (w-56 / w-14 icon rail), slide-over drawer below 1024 px, Indonesia AOI quick picker (Indonesia National, Kalimantan, Sumatra, plus a province dropdown; only regions that exist in the data), live observation count, theme toggle |
| Phone layout | Bottom tab bar with the five workspaces; the top bar folds dates and sensor into one toggle |
| Controls (`ui.tsx` `Seg`) | 2–3 options render as a segmented pill; 4 or more render as a compact dropdown with the same values and handlers |
| Demo banner | Slim neutral bar, dismissible for the session |
| Explore | 6 KPI cards (`grid-cols-2 md:grid-cols-3 xl:grid-cols-6`), 8:4 bento: map and timeline left, selected day and a bounded elevated list right. The map re-fits itself whenever its box changes size (sidebar or details toggle) |
| Calendar | 8:4 month grid and day details; the 12-month overview and the multi-year ISO-week matrix share one card with a segmented switch |
| Insights | Season Tracker (role preset as a dropdown; all sections except years), Seasonal History (the former Historical Patterns page), Climate ENSO / IOD (the real ONI/DMI phase tables and the per-year table) |
| Harmonization | Calibration Audit (the diagnostics page), Sensor Workbench, Source Records, plus Grid and Confidence dropdowns bound to the existing filter state |
| Methods | Dataset inventory with per-sensor rows and date-span bars from `/api/inventory`, local refresh instructions, Export CSV / Export GeoJSON (same endpoints as the Export menu), methodology |
| Tables | Long tables and lists sit in bounded scroll boxes with sticky headers |

## Not built (would need data or backend work)
- Java, Sulawesi and Papua are not regions in the boundary file, so they are not offered.
- Numbers shown in the design mockups that the app does not compute (e.g. “α = 0.242, R² = 0.941”, “Footprint-aware overlap −28.2 %”,
  “68.2 % co-located”, per-region row counts) were not added: the brief forbids invented data.

## Tests (run 2026-11-15)
- Browser: 20 of 20 flows passed. Flows changed only where controls changed form: navigation by workspace, role preset as a dropdown,
  4+-option choices as dropdowns (helper `pick`), and flow 19 now checks the five-item order, no “&”, no reordering, and the
  `history`/`workbench` link mapping.
- Visual check with the full archive (10,917,537 rows): every workspace at 1440×900 (light and dark), 768×1024 and 390×844 rendered
  with 0 page errors and no horizontal page scroll.
- Backend unchanged (no file touched), so the 137 backend tests of 1.5 apply unchanged.
