# Run T: Indonesia, sensitivity run with MODIS Terra as the reference (not used by the app)

Method `pyrosync-fusion-1.0`, gate `pyrosync-fusion-gate-1.0`, dataset revision 1.
AOI `region:indonesia`; record 2000-11-01 → 2026-11-14; filters {'start': '2000-11-01', 'end': '2026-11-14', 'platforms': ['Terra', 'Aqua', 'N20', 'N21', 'SNPP'], 'modis_min_conf': 30, 'viirs_conf': ['nominal', 'high'], 'types': ['0', 'unknown'], 'daynight': ['D', 'N'], 'aoi': 'region:indonesia'}.

Reference scale: MODIS Aqua active-fire detections per UTC day in the AOI. Aqua is the longest single-platform MODIS record with an afternoon overpass, the one the 1.4 day-level ratio was validated against. It is a reference observational scale, not ground truth: MODIS misses small fires and fires under cloud or smoke, and its own errors stay in the target. Aqua's overpass has drifted later since it left the A-Train in 2022; the year-by-year checks show whether that changes the ratios.

Equation: F_d = mean over eligible platforms p known on day d of c_p · X_p,d;  c_Aqua = 1,  c_p = Σ_train Aqua / Σ_train p (1.4 day-level ratio, pairwise chronological split).

## Pairwise calibration against Terra (1.4 rules, unchanged)

| Platform | c (95 % bootstrap) | overlap days | held-out ratio | rolling years within 0.8–1.25× | pair gate | eligible |
|---|---|---|---|---|---|---|
| Aqua (MODIS) | 0.4260 (0.3895–0.4649) | 8,702 | 0.81 | 13 of 23 (0.61–1.89) | not_validated | no |
| Suomi NPP (VIIRS) | 0.0639 (0.0597–0.0682) | 5,269 | 0.83 | 8 of 14 (0.69–1.92) | not_validated | no |
| NOAA-20 (VIIRS) | 0.0635 (0.0538–0.0720) | 3,085 | 0.78 | 1 of 8 (0.70–1.87) | not_validated | no |
| NOAA-21 (VIIRS) | 0.0512 (0.0396–0.0591) | 1,327 | 0.57 | 0 of 3 (0.58–1.60) | not_validated | no |

## Fused series validation (leave-reference-out)

Leave-reference-out: the fused estimate WITHOUT Aqua, with each ratio fitted only on days before the evaluation period, is compared with the observed Aqua totals. Aqua is never an input to its own prediction.

Not tested: No platform passes its pairwise calibration gate against Terra, so there is nothing to fuse and validate.

**Fusion gate: insufficient** — Insufficient validation data

- ✘ Fusion can be tested: No platform passes its pairwise calibration gate against Terra, so there is nothing to fuse and validate. (At least one eligible platform with 180 known overlap days before the split, and held-out days.)

Coverage: Satellite observation coverage (swath, cloud, smoke) is not verified. A day is 'known' when the sensor's record and an imported request interval cover it; a known day with no detection is a reported zero, not proof of a clear-sky observation.
