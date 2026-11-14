import { useEffect, useRef, useState } from 'react'

// ---- typed contracts (subset of fields used by the UI) ----
export interface Envelope {
  dataset_revision: number
  processing_version: string
  effective_filters: Record<string, unknown>
  filter_disclosure: Record<string, unknown> & { types_excluded: string[]; types_included: string[]; note: string }
  metric_definition: unknown
  warnings: string[]
}
export interface SeriesDaily {
  detections: number[]; cells: number[]; day: number[]; night: number[]
  frp_sum: (number | null)[]; frp_mean: (number | null)[]; frp_max: (number | null)[]; frp_median: (number | null)[]
  unfiltered: number[]; status: string[]; status_origin: (string | null)[]
  terra?: number[]; aqua?: number[]
}
export interface Daily extends Envelope {
  dates: string[]
  series: Record<string, SeriesDaily>
  series_labels: Record<string, string>
  status_doc: Record<string, string>
  grid_doc: Record<string, string>
}
export interface FrameCell { ci: number; cj: number; sensors_detecting: number; by_series: Record<string, number>; frp_max: number | null; frp_sum: number | null; days: number; first: string; last: string }
export interface Frame extends Envelope {
  frame: { date: string; mode_days: number; start: string; end: string; label: string; utc_interval: [string, string] }
  grid_size: number
  cells: FrameCell[]
  cells_total: number
  truncated: boolean
  summary: Record<string, { detections: number; cells: number; frp_sum: number | null; frp_max: number | null; day: number; night: number }>
  union: { cells: number; definition: string }
}
export interface ObsRecord {
  rid: number; acq_date: string; acq_hhmm: string; acq_time_utc: string; lat: number; lon: number; instrument: string; platform: string; series: string
  source_product: string; stream: string; version: string | null; conf_raw: string; conf_cat: string; frp: number | null; daynight: string | null
  type_code: number | null; type_label: string; scan: number | null; track: number | null; modis_brightness: number | null; modis_bright_t31: number | null
  viirs_bright_ti4: number | null; viirs_bright_ti5: number | null; source_file: string; source_row: number; batch_id: string
}
export interface Observations extends Envelope { total: number; returned: number; truncated: boolean; offset: number; limit: number; records: ObsRecord[]; window: { start: string; end: string } }
export interface Region { id: string; name: string; kind: string; source: string; license: string; note: string; bbox: number[]; simplification_tolerance_deg: number }
export interface Inventory {
  dataset_revision: number; processing_version: string; observations_total: number; observations_superseded: number
  date_range: [string, string] | null; extent: { west: number; south: number; east: number; north: number } | null
  products: { series: string; series_label: string; platform: string; platform_label: string; source_product: string; stream: string; version: string; instrument: string; rows: number; superseded: number; first_date: string; last_date: string }[]
  type_counts: { instrument: string; type_code: number | null; label: string; rows: number }[]
  confidence_counts: { instrument: string; category: string; rows: number }[]
  intervals: { series: string; origin: string; count: number; first: string; last: string }[]
  available_platforms: string[]; available_series: string[]; import_batches: number
  grid: Record<string, string>; day_definition: string
}
export interface MonthRow { year: number; month: number; label: string; days_in_range: number; days_in_month: number; partial: boolean
  series: Record<string, { detections: number; sum_daily_cells: number; distinct_cells: number; frp_sum: number; frp_max: number | null; days_detections: number; days_zero: number; days_unknown: number }> }
export interface History extends Envelope { months: MonthRow[]; years: (Omit<MonthRow, 'month' | 'label' | 'days_in_month'> & { days_in_year: number })[]; series_labels: Record<string, string>; notes: string[] }
export interface Week { iso_year: number; iso_week: number; start: string; days_in_range: number; days_known: number; value: number; partial: boolean; coverage_complete: boolean; sum_daily_cells?: number; distinct_cells?: number; n_weeks_in_iso_year: number }
export interface Weeks extends Envelope { weeks: Week[]; iso_note: string; series_label: string }
export interface Rankings extends Envelope { top_days: { date: string; value: number; rank: number }[]; top_weeks: (Week & { rank: number })[]; note: string; series_label: string }
export interface Compare extends Envelope { year: number; reference_year: number; months: { month: number; matched_days: number; value: number; ref_value: number; difference: number; ratio: number | null }[]; totals: { value: number; ref_value: number; matched_days: number; ratio: number | null }; notes: string[] }
export interface Baseline extends Envelope { eligibility: { eligible: boolean; reason: string | null; config: Record<string, number>; rule_note: string; years: unknown[] }; days: { date: string; eligible: boolean; n: number; eligible_years: number[]; median?: number; p_low?: number; p_high?: number; value: number | null; flag: string | null }[]; flags: unknown[]; notes: string[] }
export interface Period { start: string; end: string; duration_days: number; values: number[]; thresholds: number[]; peak: number; peak_date: string; total: number; coverage_notes: string[]; series: string; series_label: string; metric: string; unit: string; threshold_label: string; reason: string; label: string }
export interface Elevated extends Envelope { rule: { min_consecutive_days: number; min_activity: number; threshold: Record<string, unknown> & { label?: string; description?: string; value?: number }; missing_days: string; status: string }; unavailable: string | null; periods: Period[]; unknown_coverage_days: number; disclaimer: string; series_label: string }
export interface ImageryLayer { id: string; label: string; platform: string; format: string; tile_matrix_set: string; max_native_zoom: number; ranges: [string, string][]; url_template: string }
export interface Imagery { layers: ImageryLayer[]; domain_source: string; domain_checked: string; acknowledgement: string; notes: string[]; warning?: string }

// ---- fetch with cache + cancellation ----
const cache = new Map<string, unknown>()
const inflight = new Map<string, Promise<unknown>>()

export class ApiError extends Error {
  status: number
  constructor(status: number, msg: string) { super(msg); this.status = status }
}

export async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  if (cache.has(url)) return cache.get(url) as T
  let p = inflight.get(url) as Promise<T> | undefined
  if (!p) {
    p = fetch(url).then(async (r) => {
      if (!r.ok) {
        let msg = `${r.status} ${r.statusText}`
        try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not JSON */ }
        throw new ApiError(r.status, msg)
      }
      return r.json() as Promise<T>
    })
    inflight.set(url, p)
    p.then((v) => { cache.set(url, v); if (cache.size > 300) cache.delete(cache.keys().next().value as string) })
      .catch(() => {}).finally(() => inflight.delete(url))
  }
  if (!signal) return p
  return new Promise<T>((res, rej) => {
    signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    p!.then(res, rej)
  })
}

export function prefetch(url: string) {
  getJSON(url).catch(() => {})
}

export function clearCache() { cache.clear() }

export interface Q<T> { data: T | null; loading: boolean; error: string | null; url: string | null }

/** Returns data only for the CURRENT url: results of outdated requests are discarded. */
export function useApi<T>(url: string | null): Q<T> {
  const [state, setState] = useState<Q<T>>({ data: null, loading: !!url, error: null, url: null })
  const cur = useRef<string | null>(null)
  useEffect(() => {
    cur.current = url
    if (!url) { setState({ data: null, loading: false, error: null, url: null }); return }
    const ac = new AbortController()
    if (cache.has(url)) { setState({ data: cache.get(url) as T, loading: false, error: null, url }); return }
    setState((s) => ({ ...s, loading: true, error: null }))
    getJSON<T>(url, ac.signal).then(
      (d) => { if (cur.current === url) setState({ data: d, loading: false, error: null, url }) },
      (e: unknown) => {
        if ((e as Error).name === 'AbortError') return
        if (cur.current === url) setState({ data: null, loading: false, error: (e as Error).message || 'Request failed', url })
      },
    )
    return () => ac.abort()
  }, [url])
  return state
}

export async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, typeof j.detail === 'string' ? j.detail : `Request failed (${r.status})`)
  return j as T
}
