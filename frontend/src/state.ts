import { create } from 'zustand'
import { addDays, clampDate, type ISODate } from './util'

export type Page = 'explore' | 'insights' | 'calendar' | 'history' | 'workbench' | 'harmonization' | 'data'
export type Metric = 'cells' | 'detections' | 'frp_sum' | 'frp_max' | 'frp_mean'
export type FrameMode = 1 | 7 | 30
export type ElevatedMode = 'range_percentile' | 'fixed' | 'baseline'

export interface AppState {
  page: Page
  theme: 'light' | 'dark'
  navOpen: boolean
  detailsOpen: boolean
  // shared analysis state
  aoi: string
  start: ISODate
  end: ISODate
  date: ISODate
  frameMode: FrameMode
  metric: Metric
  series: string
  grid: number
  platforms: string[]
  modisMinConf: number
  viirsConf: string[]
  types: string[]
  daynight: string[]
  basemap: 'light' | 'dark' | 'none'
  imagery: string // GIBS layer id or 'off'
  imageryOverride: ISODate | null // explicit nearest-date substitution
  mapLayer: 'cells' | 'points'
  elevatedMode: ElevatedMode
  percentile: number
  threshold: number | null
  minDays: number
  minActivity: number
  baselineWindow: number
  baselineMinYears: number
  calendarScale: 'range' | 'month'
  revision: number
  mapBusy: boolean
  imageryBusy: boolean
  selectedCell: { ci: number; cj: number } | null
  dataRange: [ISODate, ISODate] | null
  set: (p: Partial<AppState>) => void
  setDate: (d: ISODate) => void
}

const SHARED_KEYS = [
  'page', 'aoi', 'start', 'end', 'date', 'frameMode', 'metric', 'series', 'grid', 'platforms', 'modisMinConf', 'viirsConf', 'types',
  'daynight', 'basemap', 'imagery', 'mapLayer', 'elevatedMode', 'percentile', 'threshold', 'minDays', 'minActivity', 'baselineWindow',
  'baselineMinYears', 'calendarScale', 'theme',
] as const
export type SharedKey = (typeof SHARED_KEYS)[number]

function readHash(): Partial<AppState> {
  const out: Record<string, unknown> = {}
  try {
    const h = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    for (const k of SHARED_KEYS) {
      const v = h.get(k)
      if (v === null) continue
      if (['platforms', 'viirsConf', 'types', 'daynight'].includes(k)) out[k] = v ? v.split(',') : []
      else if (['frameMode', 'grid', 'modisMinConf', 'percentile', 'minDays', 'minActivity', 'baselineWindow', 'baselineMinYears'].includes(k)) out[k] = Number(v)
      else if (k === 'threshold') out[k] = v === '' ? null : Number(v)
      else out[k] = v
    }
  } catch { /* ignore malformed hash */ }
  return out as Partial<AppState>
}

export const useApp = create<AppState>((set, get) => ({
  page: 'explore',
  theme: (() => { try { return (localStorage.getItem('pyrosync-theme') as 'light' | 'dark') || 'light' } catch { return 'light' } })(),
  navOpen: typeof window === 'undefined' || window.innerWidth >= 768,
  detailsOpen: true,
  aoi: 'region:kalimantan',
  start: '2023-01-01',
  end: '2024-12-31',
  date: '2023-09-15',
  frameMode: 1,
  metric: 'cells',
  series: 'VIIRS_N20',
  grid: 0.1,
  platforms: ['Terra', 'Aqua', 'N20', 'N21', 'SNPP'],
  modisMinConf: 30,
  viirsConf: ['nominal', 'high'],
  types: ['0'],
  daynight: ['D', 'N'],
  basemap: 'light',
  imagery: 'off',
  imageryOverride: null,
  mapLayer: 'cells',
  elevatedMode: 'range_percentile',
  percentile: 90,
  threshold: null,
  minDays: 3,
  minActivity: 1,
  baselineWindow: 15,
  baselineMinYears: 5,
  calendarScale: 'range',
  revision: 0,
  mapBusy: false,
  imageryBusy: false,
  selectedCell: null,
  dataRange: null,
  ...readHash(),
  set: (p) => set(p),
  setDate: (d) => {
    const s = get()
    set({ date: clampDate(d, s.start, s.end), imageryOverride: null })
  },
}))

export function serializeState(s: AppState): string {
  const h = new URLSearchParams()
  for (const k of SHARED_KEYS) {
    const v = s[k] as unknown
    h.set(k, Array.isArray(v) ? v.join(',') : v === null ? '' : String(v))
  }
  return h.toString()
}

export function viewConfig(s: AppState) {
  const o: Record<string, unknown> = {}
  for (const k of SHARED_KEYS) o[k] = s[k]
  return { pyrosync_view_config: 1, settings: o }
}

export function applyViewConfig(cfg: unknown): Partial<AppState> {
  if (!cfg || typeof cfg !== 'object' || !('settings' in cfg)) throw new Error('Not a PyroSync view configuration file.')
  const s = (cfg as { settings: Record<string, unknown> }).settings
  const out: Record<string, unknown> = {}
  for (const k of SHARED_KEYS) if (k in s) out[k] = s[k]
  return out as Partial<AppState>
}

// Keep the URL hash in sync (no data, no credentials; custom AOIs are referenced by server-side id only).
let t: number | undefined
useApp.subscribe((s) => {
  window.clearTimeout(t)
  t = window.setTimeout(() => {
    const h = '#' + serializeState(s)
    if (window.location.hash !== h) history.replaceState(null, '', h)
  }, 150)
})

export function frameWindow(date: ISODate, mode: FrameMode): [ISODate, ISODate] {
  return [addDays(date, -(mode - 1)), date]
}

export function filterParams(s: AppState): URLSearchParams {
  const p = new URLSearchParams()
  p.set('start', s.start)
  p.set('end', s.end)
  p.set('platforms', s.platforms.join(','))
  p.set('modis_min_conf', String(s.modisMinConf))
  p.set('viirs_conf', s.viirsConf.join(','))
  p.set('types', s.types.join(','))
  p.set('daynight', s.daynight.join(','))
  p.set('aoi', s.aoi)
  p.set('grid', String(s.grid))
  p.set('_rev', String(s.revision))
  return p
}

export function selectedSeries(platforms: string[]): string[] {
  const order = ['MODIS', 'VIIRS_N20', 'VIIRS_N21', 'VIIRS_SNPP']
  const map: Record<string, string> = { Terra: 'MODIS', Aqua: 'MODIS', N20: 'VIIRS_N20', N21: 'VIIRS_N21', SNPP: 'VIIRS_SNPP' }
  const set_ = new Set(platforms.map((p) => map[p]))
  return order.filter((x) => set_.has(x))
}
