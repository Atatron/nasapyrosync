# MODIS–VIIRS harmonization: validation report

This report summarizes runs of the three-stage harmonization (`backend/pyrosync/harmonize.py`, method `pyrosync-harmonize-1.0`) on the full FIRMS archive for Indonesia supplied as `indonesia_full_history.zip`. Each configuration has its own complete, generated report in [`docs/harmonization/`](harmonization/) (`report.md` and `report.json`). All numbers below are copied from those files. Nothing was tuned to the held-out data.

**What this is, and is not.** These are results of an implemented, reproducible method on the imported data. They show how well a VIIRS measurement predicts the MODIS measurement for the same cell and overpass in a *later* period. They are not an independent scientific validation: coverage is not verified (see Stage 2), MODIS is a reference scale and not ground truth, and the results have not been peer reviewed.

## Data

Imported on 2026-11-14 with `scripts/import.sh indonesia_full_history.zip` (dataset revision 1, processing version `pyrosync-proc-1.0.0`): 3,886 CSV files, **10,917,537 rows, 0 rejected, 0 duplicates**, 2000-11-01 to 2026-11-14, extent 94–142° E, 12° S–7° N.

| Product | Platform | Version | Rows | First | Last |
|---|---|---|---|---|---|
| MODIS_SP | Terra | 6.03 / 61.03 | 600,962 + 54,306 | 2000-11-01 | 2026-08-31 |
| MODIS_SP | Aqua | 6.03 / 61.03 | 1,163,962 + 122,337 | 2002-07-04 | 2026-08-31 |
| MODIS_NRT | Terra / Aqua | 6.1NRT | 46,122 / 59,364 | 2026-09-01 | 2026-11-14 |
| VIIRS_SNPP_SP / NRT | S-NPP | 2 / 2.0NRT | 4,413,814 / 633,080 | 2012-01-20 | 2026-11-02 |
| VIIRS_NOAA20_SP / NRT | NOAA-20 | 2 / 2.0NRT | 1,791,995 / 684,655 | 2018-04-01 | 2026-11-14 |
| VIIRS_NOAA21_SP / NRT | NOAA-21 | 2 / 2.0NRT | 681,968 / 664,972 | 2023-03-01 | 2026-11-14 |

The NRT files start the day after the SP files end, so no NRT rows were superseded. Note that MODIS SP changes from collection 6.0 (`6.03`, through 2022) to 6.1 (`61.03`, from 2023), and the hold-out period of most runs crosses that change.

## Reproduce

```bash
# from backend/, server stopped, with the archive imported
../.venv/bin/python -m pyrosync.cli harmonize --start 2012-01-20 --end 2026-11-14 --out ../docs/harmonization/A_indonesia_aqua_snpp
# add --viirs VIIRS_N20, --modis Terra, --tolerance 60, --grid 0.25, --metric frp_sum, --unit-set matched_plus_proxy, --aoi region:kalimantan
```
The same analysis is available in the app (Sensor Workbench → MODIS–VIIRS harmonization → Validation package), which also exports every comparison unit as `units.csv`. Shared defaults: MODIS confidence ≥ 30, VIIRS nominal/high, type 0 (vegetation fire), day and night, chronological hold-out of the last 20 % of units.

## Results

| Run | Pair, settings | Matched units | Median \|Δt\| | Train / test units | Test from | α | β | R² (log, train) |
|---|---|---|---|---|---|---|---|---|
| **A** | Indonesia, Aqua–S-NPP, ±30 min, 0.1°, detections | 113,567 | 13 min | 90,772 / 22,795 | 2019-09-22 | 0.6131 | 0.2388 | 0.232 |
| B | as A, + proxy one-sided units | 113,567 (+610,233 proxy) | 13 min | 578,557 / 145,243 | 2019-11-07 | 0.0820 | 0.1321 | 0.038 |
| C | Indonesia, Aqua–NOAA-20, ±60 min, 2018– | 59,563 | 23 min | 47,592 / 11,971 | 2023-09-21 | 0.6036 | 0.2602 | 0.249 |
| D | Kalimantan, Aqua–S-NPP | 36,893 | 13 min | 29,275 / 7,618 | 2019-09-12 | 0.6867 | 0.2052 | 0.163 |
| E | as A, FRP sum (MW) | 113,567 | 13 min | 90,772 / 22,795 | 2019-09-22 | 1.5047 | 0.6030 | 0.437 |
| F | Indonesia, **Terra**–S-NPP (negative control) | 0 | — | — | — | not fitted | | |

Held-out errors, original scale (detections per unit; MW for E). "Unadjusted" uses the raw VIIRS value as the MODIS-scale estimate (M̂ = V). Improvement = 100 × (unadjusted − calibrated) / unadjusted; for MBE the absolute bias is compared.

| Run | MAE unadj → cal | RMSE unadj → cal | MBE unadj → cal | MAE / RMSE / \|MBE\| improvement | Training-mean constant MAE / RMSE |
|---|---|---|---|---|---|
| **A** | 3.562 → 0.842 | 7.539 → 1.423 | +3.262 → −0.228 | 76.4 % / 81.1 % / 93.0 % | 1.006 / 1.595 |
| B | 1.979 → 0.531 | 3.492 → 0.976 | +1.605 → −0.187 | 73.1 % / 72.1 % / 88.3 % | 0.619 / 0.965 |
| C | 3.113 → 0.888 | 6.253 → 1.466 | +2.670 → −0.254 | 71.5 % / 76.6 % / 90.5 % | 1.022 / 1.594 |
| D | 4.169 → 0.975 | 9.215 → 1.654 | +3.752 → −0.300 | 76.6 % / 82.1 % / 92.0 % | 1.098 / 1.783 |
| E (MW) | 40.759 → 40.713 | 113.686 → 137.841 | −8.532 → −24.098 | 0.1 % / −21.2 % / −182.4 % | 70.912 / 158.539 |

Sensitivity of run A to its settings (same data, same rules):

| Setting | Matched units | α | β | MAE unadj → cal | RMSE unadj → cal | MBE cal |
|---|---|---|---|---|---|---|
| ±10 min | 42,542 | 0.5619 | 0.2599 | 3.498 → 0.814 | 7.376 → 1.453 | −0.283 |
| ±20 min | 79,076 | 0.5924 | 0.2425 | 3.551 → 0.818 | 7.429 → 1.434 | −0.254 |
| **±30 min (A)** | 113,567 | 0.6131 | 0.2388 | 3.562 → 0.842 | 7.539 → 1.423 | −0.228 |
| ±60 min | 170,793 | 0.6303 | 0.2389 | 3.490 → 0.882 | 7.210 → 1.483 | −0.224 |
| 0.25° grid | 93,132 | 0.5480 | 0.3119 | 5.400 → 1.245 | 12.263 → 2.461 | −0.424 |
| 0.5° grid | 72,695 | 0.4547 | 0.3770 | 7.339 → 1.699 | 17.180 → 3.909 | −0.693 |

## Interpretation

1. **For detection counts, the calibration removes most of the scale difference between the sensors.** In every detection-count run the raw VIIRS count overestimates the MODIS count of the same cell and overpass (MBE +1.6 to +6.8 detections), because VIIRS 375 m pixels resolve one fire into several detections and see smaller fires. The calibrated values cut MAE by 71–77 %, RMSE by 72–82 % and the absolute bias by 88–93 % on the later, held-out period. The improvement is stable across time tolerances (10–60 min), grid sizes and the NOAA-20 pair.
2. **The model explains only a small part of the unit-to-unit variation.** R² on the log scale is 0.16–0.38 for matched-unit runs (0.23 for run A), and a constant equal to the training-period MODIS mean is only slightly worse than the calibrated model (run A: MAE 1.006 vs 0.842, RMSE 1.595 vs 1.423). Most of the gain over "unadjusted" therefore comes from correcting the overall level; the VIIRS value adds modest information about how many MODIS detections a matched cell will have. β ≈ 0.24 means a 10 % larger VIIRS count goes with roughly a 2.4 % larger (1 + MODIS) count.
3. **The calibrated estimate is slightly low** (MBE −0.19 to −0.69). This is the expected back-transformation effect of a log model (it predicts a conditional median). The Duan smearing factors (1.07–1.16) are reported in each report but deliberately not applied, so the prediction follows the stated equation.
4. **FRP does not calibrate with this model (run E).** MAE is unchanged (+0.1 %), RMSE gets worse (−21 %) and the bias triples. Per-event FRP sums are heavy-tailed and depend on pixel size and view geometry; the log-log model is not adequate for them. The app reports these numbers as they are; no FRP harmonization claim is made.
5. **Terra is correctly not matched (run F, 0 units).** Terra overpasses about three hours before S-NPP, so a ±30 min tolerance finds no pairs. This is a negative control for the matching rule, not a failure.
6. **Including proxy one-sided units (run B) changes the question.** The model then also learns from VIIRS-only events with M = 0 (and MODIS-only with V = 0). Proxy units are *not* verified coverage: a nearby MODIS detection shows the instrument was imaging the region, not that this cell was inside the swath and cloud-free. Run B's coefficients describe "all events with nearby evidence", A's describe "events both sensors detected". Neither is a coverage-corrected relationship.
7. **Coefficients are local.** Kalimantan (D) and all of Indonesia (A) differ (β 0.205 vs 0.239), and coefficients depend on the grid size. Re-fit for another AOI, period, filter set or sensor pair before using the values.

## Stage 2 coverage statement (applies to every run)

Verified satellite coverage is not established. FIRMS active-fire records list detections only; they do not say which cells each overpass imaged or which were cloud-free. Verifying coverage would require swath geolocation and fire/cloud masks (MOD03/MOD14 for MODIS, VNP03/VNP14 or VJ103/VJ114 for VIIRS), which PyroSync does not import. Candidate matches therefore mean "both sensors reported at least one detection in the same cell within the tolerance".

## Known limitations

- Standard errors and 95 % intervals assume independent units. Neighbouring cells and successive overpasses are correlated, so the intervals are too narrow.
- The hold-out is a single chronological split. Because 2015 and 2019 had very large fire seasons, the last 20 % of units starts in late 2019 and covers a different mix of years from the training period. The split date is printed in every report and can be set explicitly (`--split-date`).
- The MODIS collection change (6.0 → 6.1 in 2023) and the NRT records after 2026-08/09 are inside the held-out period. No collection-specific correction is applied.
- Event clustering uses a fixed 20-minute gap, and event time is the first acquisition in the event. FIRMS acquisition times are granule times, not per-pixel times.
- Quality and type filters are applied identically to both sensors, but MODIS confidence (numeric) and VIIRS confidence (categorical) are different scales.
