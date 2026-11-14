// Contracts and UI state of the Harmonization tab (added in v1.2).
import { create } from 'zustand'
import type { Err, Harmonization } from './components/Harmonization'

export interface Check { id: string; label: string; passed: boolean; value: string; rule: string }
export interface Validity { status: 'passes' | 'not_validated'; label: string; rules_version?: string; checks: Check[]; scope: string; applies_to?: string; note?: string }
export type HarmonizationRun = Harmonization & {
  validity: Validity
  stage3: Harmonization['stage3'] & { evaluation?: { held_out: { training_median_reference?: Err } } }
}

export interface ModelSummary {
  method_version: string; apply_version: string; config: Record<string, unknown>; validity: Validity; calibrated_available: boolean
  fit_status: string; unit_set: string; domain_doc: string; estimate_doc: string; grid_deg: number; dataset_revision: number
  alpha?: number; beta?: number; test_starts?: string; train_period?: [string, string]; test_period?: [string, string]; train_v_max?: number | null
  calibrated_unavailable_reason?: string
}
export type Validation = 'validated' | 'too_few' | 'no_held_out'
export interface MapCell {
  ci: number; cj: number; modis: number; viirs: number; modis_events: number; viirs_events: number; pairs: number; viirs_events_in_domain: number
  cal: number | null; cal_domain: number | null; value_cal: number | null; extrapolated_events: number; dt_median: number | null
  validation: Validation; region_mae: number | null; region_n_test: number
}
export interface Pair { ci: number; cj: number; modis_platform: string; t_modis: string; t_viirs: string; dt_min: number; M: number; V: number; M_hat: number | null; set: 'train' | 'test' | null }
export interface HMap {
  window: { date: string; mode_days: number; start: string; end: string; utc_interval: [string, string]; period_role: 'held_out' | 'training' | 'mixed' | null; period_role_doc: string | null }
  scope: 'all' | 'domain'; error_grid_deg: number; min_n: number; cells: MapCell[]; truncated: boolean; pairs: Pair[]; pairs_truncated: boolean
  totals: { modis: number; viirs: number; modis_events: number; viirs_events: number; pairs: number; cells: number; cal: number | null; cal_domain: number | null; cells_viirs: number; cells_viirs_validated: number }
  model: ModelSummary; event_day_rule: string; modis_label: string; viirs_label: string
  suggested_days: { training: { date: string; pairs: number }[]; held_out: { date: string; pairs: number }[] }
}
export interface ErrCell { ci: number; cj: number; n_test: number; n_train: number; mae_cal: number | null; mae_unadj: number | null; rmse_cal: number | null; mbe_cal: number | null; improvement_pct: number | null; status: Validation }
export interface HErrors {
  error_grid_deg: number; comparison_grid_deg: number; min_n: number; metric: string; unit: string; definition: string; error_grids: number[]; min_n_choices: number[]
  model: ModelSummary; cells: ErrCell[]
  summary: null | { cells_validated: number; cells_too_few: number; cells_no_held_out: number; held_out_units: number; held_out_units_in_validated_cells: number
    share_in_validated_cells: number | null; overall_mae_cal: number; overall_mae_unadj: number; validated_cells_mae_cal_range: [number, number] | null; validated_cells_worse_than_unadjusted: number }
}
export interface TotalsPeriod {
  days: number; first: string; last: string; sum_modis: number; sum_viirs: number; sum_calibrated: number; ratio_viirs_to_modis: number | null; ratio_calibrated_to_modis: number | null
  unadjusted: Err; calibrated: Err; improvement_vs_unadjusted: { mae_pct: number | null; rmse_pct: number | null; abs_mbe_pct: number | null }; constant_reference?: Err & { value: number }
}
export interface HSeries {
  agg: 'day' | 'month'; scope: 'all' | 'domain'; model: ModelSummary
  check: null | { held_out: TotalsPeriod | null; training: TotalsPeriod | null; definition: string }
  totals_validity: Validity
  dates: string[]; modis: (number | null)[]; viirs: (number | null)[]; calibrated: (number | null)[] | null; known_days: number[] | null; days?: number[]
  modis_label: string; viirs_label: string; calibrated_label: string; notes: string[]
}

export type HLayer = 'modis' | 'viirs' | 'calibrated' | 'matching' | 'errors'
export interface HState {
  viirs: 'VIIRS_SNPP' | 'VIIRS_N20' | 'VIIRS_N21'
  modis: 'Aqua' | 'Terra' | 'Aqua,Terra'
  tol: number
  grid: number
  metric: 'detections' | 'frp_sum'
  unitSet: 'matched' | 'matched_plus_proxy'
  testFraction: number
  run: string | null
  layer: HLayer
  scope: 'all' | 'domain'
  errGrid: number
  minN: number
  errColor: 'mae' | 'improvement'
  seriesAgg: 'day' | 'month'
  selCell: { ci: number; cj: number } | null
  set: (p: Partial<HState>) => void
}

export const useHarm = create<HState>((set) => ({
  viirs: 'VIIRS_SNPP', modis: 'Aqua', tol: 30, grid: 0.1, metric: 'detections', unitSet: 'matched', testFraction: 0.2,
  run: null, layer: 'modis', scope: 'domain', errGrid: 0.5, minN: 20, errColor: 'mae', seriesAgg: 'month', selCell: null,
  set: (p) => set(p),
}))

export function errorGridsFor(unitGrid: number): number[] {
  return [0.1, 0.25, 0.5, 1, 2].filter((g) => g >= unitGrid - 1e-9 && Math.abs(g / unitGrid - Math.round(g / unitGrid)) < 1e-9)
}

export function harmParams(qs: string, h: Pick<HState, 'viirs' | 'modis' | 'tol' | 'grid' | 'metric' | 'unitSet' | 'testFraction'>): string {
  const p = new URLSearchParams(qs)
  p.set('viirs_series', h.viirs); p.set('modis_platforms', h.modis); p.set('tolerance_min', String(h.tol)); p.set('unit_grid', String(h.grid))
  p.set('metric', h.metric); p.set('unit_set', h.unitSet); p.set('test_fraction', String(h.testFraction))
  return p.toString()
}

// Calibrated estimates: a purple ramp, deliberately different from the observation ramp, so an estimate never looks like an observation.
export const EST_RAMP = ['#f3e8ff', '#e9d5ff', '#d8b4fe', '#c084fc', '#a855f7', '#9333ea', '#7e22ce', '#581c87']
// Error magnitude: light = small held-out error, dark = large (blues; red stays reserved for documented exceedances).
export const ERR_RAMP = ['#eff6ff', '#dbeafe', '#bfdbfe', '#93c5fd', '#60a5fa', '#3b82f6', '#1d4ed8', '#1e3a8a']
// Improvement over unadjusted VIIRS: green = calibrated better, orange = calibrated worse.
export function improvementColor(p: number): string {
  if (p < 0) return p < -25 ? '#c2410c' : '#fb923c'
  return p >= 75 ? '#15803d' : p >= 50 ? '#22c55e' : p >= 25 ? '#86efac' : '#dcfce7'
}
export function rampOf(ramp: string[], v: number, max: number): string {
  if (max <= 0) return ramp[0]
  const t = Math.min(1, Math.max(0, v / max))
  return ramp[Math.min(ramp.length - 1, Math.floor(Math.sqrt(t) * ramp.length))]
}
