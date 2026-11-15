// Multi-sensor historical fusion (added in 1.5): types and labels for /api/fusion*.
import type { Check } from './harmonization'

export type FusionStatus = 'passes' | 'not_validated' | 'insufficient'
export interface FusionGate { version: string; status: FusionStatus; checks: Check[]; label: string; note?: string }
export interface FusionMetrics { n: number; mae: number | null; rmse: number | null; mbe: number | null; ratio: number | null; sum_pred: number; sum_obs: number; value?: number }
export interface FusionPair {
  platform: string; platform_label: string; status: string; reason?: string | null; c: number | null
  bootstrap?: { c_lo: number; c_hi: number } | null; split?: string | null; train_days?: number; held_out_days?: number; overlap_days?: number
  eligible: boolean; used?: boolean; gate: FusionGate; held_out?: { day_ratio: FusionMetrics; raw: FusionMetrics; constant: FusionMetrics }
  rolling_years?: { year: number; c: number; ratio: number | null; within_level: boolean; test_days: number }[]
}
export interface FusionValidation {
  status: string; reason?: string; design: string; split?: string; split_rule?: string; train_days?: number; held_out_days?: number
  held_out_period?: [string, string] | null; train_coefficients?: Record<string, number | null>
  held_out?: Record<string, FusionMetrics>
  single_sensor_comparison?: Record<string, { days: number; single_ratio: FusionMetrics; fusion: FusionMetrics }>
  activity?: { threshold: number; high: Record<string, FusionMetrics> }
  monthly?: { months: { month: string; days: number; aqua: number; fusion: number; ratio: number | null }[]; share_within_level: number | null }
  seasonal?: { months: { month: number; days: number; aqua: number; fusion: number; ratio: number | null }[]; share_within_level: number | null; rule: string }
  rolling_origin?: { years: { year: number; contributors: string[]; test_days: number; ratio: number | null; mae: number | null; constant_mae: number | null; within_level: boolean }[]; rule: string }
  transitions?: { platforms: { platform: string; joins: string; leave_reference_out: { before: number; after: number; step: number } | null; fused: { before: number; after: number; step: number } | null }[]; rule: string }
  missing?: { days: number; no_known_platform: number; aqua_unknown: number; per_platform_known: Record<string, number> }
  gate: FusionGate
}
export interface FusionEffective { coefficients: Record<string, number>; eligible: string[]; source: { aoi: string; label: string }; status: FusionStatus; status_label: string }
export interface FusionReport {
  method_version: string; gate_version: string; aoi: string; record: [string, string]; platform_records: Record<string, [string, string]>
  reference: string; reference_available: boolean; reference_doc: string; equation: string; coefficients: Record<string, number>; eligible: string[]
  eligibility_rule: string; pairs: Record<string, FusionPair>; validation: FusionValidation; gate: FusionGate; coverage: { status: string; note: string }
  effective: FusionEffective
}
export interface FusionSeries {
  agg: 'day' | 'month' | 'year'; label: string; unit: string; reference: string; coefficients: Record<string, number>; eligible: string[]
  coefficient_source: { aoi: string; label: string }; validation_status: FusionStatus; validation_label: string; gate: FusionGate
  dates: string[]; fused: (number | null)[]; aqua_observed: (number | null)[]; contributors: string[][]
  known_days?: number[]; days?: number[]; reference_days?: number[]; mean_platforms?: (number | null)[]; n_platforms?: number[]
  calibrated?: Record<string, (number | null)[]>; observed?: Record<string, (number | null)[]>; notes: string[]
}
export interface FusionCell { ci: number; cj: number; value: number; observed: Record<string, number> }
export interface FusionFrame {
  method_version: string; frame: { date: string; mode_days: number; start: string; end: string }; grid_size: number; cells: FusionCell[]; cells_total: number
  truncated: boolean; fused_total: number; days_known: number; days: number; contributors: string[]; coefficients: Record<string, number>
  coefficient_source: { aoi: string; label: string }; reference: string; unit: string; validation_status: FusionStatus; validation_label: string
  cells_validated: boolean; label: string; notes: string[]
}
export interface FusionRegions {
  available: boolean; reason?: string; grid_deg: number; min_days: number; split?: string
  cells: { ci: number; cj: number; west: number; south: number; aqua: number; fusion: number; ratio: number | null; active_days: number; status: string }[]
  summary?: { within: number; outside: number; too_few: number; share_within: number | null }; definition?: string
}

export const PLATFORM_SHORT: Record<string, string> = { Terra: 'Terra', Aqua: 'Aqua', SNPP: 'S-NPP', N20: 'NOAA-20', N21: 'NOAA-21' }
export const FUSION_STATUS_TEXT: Record<FusionStatus, string> = {
  passes: 'Validated (project rules, AOI daily totals)',
  not_validated: 'Experimental — not validated for this area',
  insufficient: 'Insufficient validation data',
}
export function fusionStatusClass(st: string | undefined): string {
  return st === 'passes' ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100' : 'bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100'
}
