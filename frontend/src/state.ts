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
  mapLayer: 'cells' | 'points' | 'harmonized'
  // 1.5: adaptive display grid, Click-to-Analyze and a restorable map view
  gridMode: 'auto' | 'manual'
  analyzeMode: 'region' | 'click'
  clickAt: string // 'lat,lon' of the Click-to-Analyze centre ('' = none)
  circleFrac: number // circle diameter as a fraction of the shortest visible map side
  lastRegionAoi: string // Region AOI to return to from Click-to-Analyze
  view: string // 'lat,lon,zoom' of the Explore map ('' = fit the AOI)
  mapZoom: number
  mapBbox: string | null
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
  'baselineMinYears', 'calendarScale', 'theme', 'gridMode', 'analyzeMode', 'clickAt', 'circleFrac', 'lastRegionAoi', 'view',
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
      else if (['frameMode', 'grid', 'modisMinConf', 'percentile', 'minDays', 'minActivity', 'baselineWindow', 'baselineMinYears', 'circleFrac'].includes(k)) out[k] = Number(v)
      else if (k === 'threshold') out[k] = v === '' ? null : Number(v)
      else out[k] = v
    }
    // links made before 1.5 name a grid but no grid mode: they keep that manual grid
    if (h.has('grid') && !h.has('gridMode')) out.gridMode = 'manual'
    if (out.circleFrac !== undefined && !(Number(out.circleFrac) >= 0.05 && Number(out.circleFrac) <= 0.8)) delete out.circleFrac
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
  types: ['0', 'unknown'], // 1.3: FIRMS NRT rows carry no type column; excluding them would read recent weeks as zero
  daynight: ['D', 'N'],
  basemap: 'light',
  imagery: 'off',
  imageryOverride: null,
  mapLayer: 'cells',
  gridMode: 'auto',
  analyzeMode: 'region',
  clickAt: '',
  circleFrac: 0.22,
  lastRegionAoi: 'region:kalimantan',
  view: '',
  mapZoom: 5,
  mapBbox: null,
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
  const order = ['MODIS', 'VIIRS_N20', 'VIIRS_N21', 'VIIRS_SNPP']  // the harmonized series (FUSED) is never a per-sensor column
  const map: Record<string, string> = { Terra: 'MODIS', Aqua: 'MODIS', N20: 'VIIRS_N20', N21: 'VIIRS_N21', SNPP: 'VIIRS_SNPP' }
  const set_ = new Set(platforms.map((p) => map[p]))
  return order.filter((x) => set_.has(x))
}

// ---- 1.5: adaptive display grid (presentation only; analysis statistics keep the analysis grid `grid`)
export const GRID_CHOICES = [0.25, 0.1, 0.05, 0.01] as const
export function gridForZoom(z: number): number {
  if (z <= 5) return 0.25
  if (z <= 7) return 0.1
  if (z <= 10) return 0.05
  return 0.01
}
export function displayGrid(s: Pick<AppState, 'gridMode' | 'grid' | 'mapZoom'>): number {
  return s.gridMode === 'auto' ? gridForZoom(Math.round(s.mapZoom)) : s.grid
}
/** Bounding box for map requests on fine grids: the viewport snapped outward to 0.5° (better cache reuse), or null when the grid is coarse. */
export function displayBbox(s: Pick<AppState, 'mapBbox'>, grid: number): string | null {
  if (grid > 0.05 || !s.mapBbox) return null
  const [w, so, e, n] = s.mapBbox.split(',').map(Number)
  const f = (x: number) => Math.floor(x * 2) / 2, c = (x: number) => Math.ceil(x * 2) / 2
  return [Math.max(-180, f(w)), Math.max(-90, f(so)), Math.min(180, c(e)), Math.min(90, c(n))].join(',')
}
export function circleKm(aoi: string): number | null {
  if (!aoi.startsWith('circle:')) return null
  const r = Number(aoi.split(',')[2])
  return Number.isFinite(r) ? r : null
}
export function circleId(lat: number, lon: number, km: number): string {
  const r = Math.min(2000, Math.max(0.1, Number(km.toPrecision(3))))
  return `circle:${lat.toFixed(4)},${lon.toFixed(4)},${r}`
}
