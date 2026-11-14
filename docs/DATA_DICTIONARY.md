# PyroSync data dictionary

All dates are UTC calendar days. All coordinates are WGS84 longitude/latitude in decimal degrees.

## 1. Accepted input (FIRMS CSV)
| Column | MODIS | VIIRS | Notes |
|---|---|---|---|
| `latitude`, `longitude` | ✓ | ✓ | Pixel centre. Must be within ±90 / ±180. |
| `brightness` | ✓ | | MODIS channel 21/22 brightness temperature (K). Its presence identifies a MODIS file. |
| `bright_t31` | ✓ | | MODIS channel 31 brightness temperature (K) |
| `bright_ti4` | | ✓ | VIIRS I-4 brightness temperature (K). Its presence identifies a VIIRS file. |
| `bright_ti5` | | ✓ | VIIRS I-5 brightness temperature (K) |
| `scan`, `track` | ✓ | ✓ | Actual pixel size along scan/track (km). Not fire size. |
| `acq_date` | ✓ | ✓ | `YYYY-MM-DD` (strict) |
| `acq_time` | ✓ | ✓ | HHMM UTC, possibly unpadded (`402` = 04:02). `HH:MM` is also accepted. |
| `satellite` | ✓ | ✓ | MODIS: `Terra`/`T`, `Aqua`/`A`. VIIRS: `N20`/`1`/`J1` (NOAA-20), `N21`/`J2` (NOAA-21), `N`/`NPP`/`SNPP` (Suomi NPP). Other values are rejected. |
| `instrument` | ✓ | ✓ | `MODIS` / `VIIRS` |
| `confidence` | 0–100 | `l`/`n`/`h` | Interpreted per sensor (see Methodology §2) |
| `version` | ✓ | ✓ | Collection/version, e.g. `61.03`, `2`, `2.0NRT`. An `NRT`/`RT`/`URT` suffix marks the stream. |
| `frp` | ✓ | ✓ | Fire radiative power (MW) |
| `daynight` | ✓ | ✓ | `D` / `N` |
| `type` | optional | optional | 0 vegetation, 1 volcano, 2 other static land, 3 offshore. Missing = unknown. |

The processing stream (SP or NRT) comes from the version suffix, then from path tokens such as `MODIS_SP/…`, `…_NRT…` or `fire_archive_…`, and finally from `--stream`. If none applies it is recorded as "unknown".

## 2. Stored observation (`observations` table)
| Field | Type | Description |
|---|---|---|
| `rid` | BIGINT | Stable row id within the local database |
| `record_key` | VARCHAR | SHA-1 of all normalized fields. Identical records share one key. |
| `acq_date` | DATE | UTC day from the record itself |
| `acq_hhmm` | VARCHAR(4) | Zero-padded UTC HHMM |
| `acq_ts` | TIMESTAMP | Full UTC acquisition timestamp |
| `lat`, `lon` | DOUBLE | Coordinates as given (quantized to 1e-5°) |
| `lat_e5`, `lon_e5` | INTEGER | Coordinates × 100,000, round-half-even. Used for exact grid indexing. |
| `instrument` | VARCHAR | MODIS / VIIRS |
| `platform` | VARCHAR | Terra, Aqua, N20, N21, SNPP |
| `satellite_raw` | VARCHAR | Original `satellite` value |
| `series` | VARCHAR | Analysis series: MODIS (Terra+Aqua), VIIRS_N20, VIIRS_N21, VIIRS_SNPP |
| `source_product` | VARCHAR | e.g. MODIS_SP, VIIRS_NOAA20_SP, VIIRS_NOAA20_NRT |
| `stream` | VARCHAR | SP, NRT, RT, URT or unknown |
| `version` | VARCHAR | Original version string |
| `conf_raw` | VARCHAR | Original confidence value |
| `conf_num` | SMALLINT | MODIS numeric confidence (NULL for VIIRS) |
| `conf_cat` | VARCHAR | low / nominal / high (MODIS bins 0–29 / 30–79 / 80–100) |
| `frp` | DOUBLE | MW |
| `daynight` | VARCHAR | D / N |
| `type_code` | SMALLINT | 0–3 or NULL |
| `scan`, `track` | DOUBLE | km |
| `modis_brightness`, `modis_bright_t31` | DOUBLE | K (MODIS only) |
| `viirs_bright_ti4`, `viirs_bright_ti5` | DOUBLE | K (VIIRS only). Not interchangeable with the MODIS fields. |
| `batch_id` | VARCHAR | Import batch that first stored the record |
| `source_file`, `source_row` | VARCHAR, INT | Where the record was first read (file inside a ZIP: `zip:member`) |
| `superseded` | BOOLEAN | TRUE for NRT/RT/URT rows replaced by SP coverage. Excluded from analysis. |
| `superseded_by` | VARCHAR | Reason and batch |

Other tables: `provenance` (every occurrence of every record_key, role `first` or `duplicate`), `import_batches` (full JSON report per import), `import_intervals` (declared or requested coverage windows: series, stream, start, end, origin, optional bbox), `dataset_meta` (`revision`, `processing_version`), and `aoi_members` / `aoi_cache_state` (exact AOI membership, materialized per revision).

## 3. Daily metrics (`/api/daily`, Daily summary CSV)
| Metric | Definition |
|---|---|
| `detections` | Number of records passing the filters that UTC day, per sensor |
| `cells` | Distinct grid cells with ≥1 detection that day, per sensor |
| `union cells` | Distinct cells with detections from **any selected sensor**. A cell seen by several sensors counts once. Union detections and FRP are deliberately not provided. |
| `frp_sum` / `frp_mean` / `frp_max` / `frp_median` | MW over that day's detections. The sum is descriptive (repeated observations add up). |
| `day` / `night` | Detections by overpass |
| `unfiltered` | Records before the quality/type/day-night filters (same AOI and day) |
| `status` | detections, zero_reported, unknown, sensor_unavailable or outside_range (Methodology §5) |
| `status_origin` | Which interval established zero_reported, or the reason a day is unknown |

### Daily summary CSV columns
`date_utc`, then for each selected sensor `<S>_detections, <S>_cells, <S>_frp_sum_mw, <S>_frp_mean_mw, <S>_frp_max_mw, <S>_day, <S>_night, <S>_status`, then `union_cells_any_selected_sensor, union_status`.

## 4. Filtered observations CSV
Columns: `rid, acq_date, acq_hhmm, lat, lon, instrument, platform, series, source_product, stream, version, conf_raw, conf_cat, frp, daynight, type_code, scan, track, modis_brightness, modis_bright_t31, viirs_bright_ti4, viirs_bright_ti5, source_file, source_row, batch_id, acq_timestamp_utc`. Only non-superseded records passing the current filters, AOI and map window are included, ordered by time.

## 5. Aggregated grid GeoJSON
One Polygon feature per occupied cell in the map window (cell extent, closed ring, lon/lat). Properties: `cell_col`, `cell_row`, `west`, `south`, `<SERIES>_detections` (per sensor, never summed across sensors), `sensors_detecting` (number of selected sensors with ≥1 detection), `frp_max_mw`, `frp_sum_mw`, `days_with_detections`, `first_date`, `last_date`. The `pyrosync_metadata` member holds the manifest. Cells are not burned-area polygons.

## 6. AOI GeoJSON
A FeatureCollection with the AOI geometry and its description (name, source, licence for named regions), plus `pyrosync_metadata` (CRS, export time, attribution).

## 7. `manifest.json` (in every ZIP export)
`generator`, `attribution`, `export_kind`, `exported_at_utc`, `dataset_revision`, `processing_version`, `aoi` (id, name, source/licence, bbox, geometry, boundary rule), `time` (start, end, timezone UTC, day definition), `filters` (exact values), `filter_disclosure`, `grid` (size and indexing rule), `metric_definitions`, `source_products` (product, platform, stream, versions, date range, rows), plus export-specific fields (`row_count`, `window`, `analysis_settings`, `columns_note`). Manifests never contain API keys.

## 8. View configuration / shareable URL
JSON or a URL hash containing only settings: page, AOI id, analysis range, date, frame window, sensor, metric, grid, filters, imagery/basemap choice, elevated-period rules, calendar scale and theme. It holds no observations and no credentials. Custom AOIs are referenced by a local id and resolve only on the machine where they were created.

## 9. Harmonization (`/api/harmonization`, validation package), added in 1.1
Query parameters: the shared filters (`start`, `end`, `aoi`, `modis_min_conf`, `viirs_conf`, `types`, `daynight`; `platforms` and `grid` are replaced by the settings below) plus
`modis_platforms` (`Aqua`, `Terra` or `Aqua,Terra`; default `Aqua`), `viirs_series` (`VIIRS_SNPP` default, `VIIRS_N20`, `VIIRS_N21`), `unit_grid` (0.1 default, 0.25, 0.5, 1.0), `tolerance_min` (1–180, default 30), `metric` (`detections` default, `frp_sum`), `unit_set` (`matched` default, `matched_plus_proxy`), `evidence_radius_deg` (default 5), `test_fraction` (0.05–0.5, default 0.2), `split_date` (optional, first held-out UTC day).

Response: `stage1` (unit and measurement definitions), `stage2` (`events`, `candidate_pairs`, `class_counts` for `matched`, `viirs_only_proxy`, `viirs_only_no_evidence`, `modis_only_proxy`, `modis_only_no_evidence`, `dt_minutes`, `coverage_verification.status` = `not_verified`), `stage3` (`status` ok/insufficient, `reason`, `split`, `fit` with `alpha`, `beta`, standard errors, 95 % CIs, `r2_log`, `residual_sd_log`, `duan_smearing_factor`, `evaluation.held_out` with `unadjusted`, `calibrated`, `training_mean_reference` {`mae`, `rmse`, `mbe`, `n`} and `improvement_vs_unadjusted`, `bins`, `daily_test`, a deterministic `scatter` sample of at most 2,500 units, and the fitted `curve`), `interpretation`, `dataset_revision`, `method_version`.

`harmonization.zip` holds `manifest.json`, `harmonization_report.json` (the response above), `HARMONIZATION_REPORT.md` and `units.csv` with one row per comparison unit used by the model:

| Column | Meaning |
|---|---|
| `set` | `train` or `test` (chronological hold-out) |
| `class` | `matched`, `viirs_only_proxy` or `modis_only_proxy` |
| `date_utc` | UTC day of the unit (MODIS event time when present) |
| `t_modis_utc`, `t_viirs_utc` | First acquisition time of each event (empty for the missing side) |
| `dt_min` | \|Δt\| in minutes for matched units |
| `cell_col`, `cell_row`, `cell_center_lon`, `cell_center_lat` | Comparison cell (grid rule of Methodology §3 at `unit_grid`) |
| `modis_platform` | Terra or Aqua |
| `M`, `V` | MODIS and VIIRS measurement (detections or FRP sum in MW) |
| `M_hat` | Calibrated prediction max(0, exp(α̂ + β̂ ln(1+V)) − 1) |
| `modis_detections`, `viirs_detections` | Detection counts in each event (also for the FRP metric) |
