// Date helpers operate on 'YYYY-MM-DD' strings in UTC only. Browser time zones never shift a day.
export type ISODate = string

export function parseISO(d: ISODate): number {
  const [y, m, dd] = d.split('-').map(Number)
  return Date.UTC(y, m - 1, dd)
}
export function toISO(ms: number): ISODate {
  return new Date(ms).toISOString().slice(0, 10)
}
export function addDays(d: ISODate, n: number): ISODate {
  return toISO(parseISO(d) + n * 86400000)
}
export function diffDays(a: ISODate, b: ISODate): number {
  return Math.round((parseISO(b) - parseISO(a)) / 86400000)
}
export function clampDate(d: ISODate, lo: ISODate, hi: ISODate): ISODate {
  return d < lo ? lo : d > hi ? hi : d
}
export function isoWeekday(d: ISODate): number {
  const wd = new Date(parseISO(d)).getUTCDay()
  return wd === 0 ? 7 : wd
}
export function daysInMonth(y: number, m: number): number {
  return new Date(Date.UTC(y, m, 0)).getUTCDate()
}
export function isoWeek(d: ISODate): [number, number] {
  const t = new Date(parseISO(d))
  const day = t.getUTCDay() || 7
  t.setUTCDate(t.getUTCDate() + 4 - day)
  const y = t.getUTCFullYear()
  const w = Math.ceil(((t.getTime() - Date.UTC(y, 0, 1)) / 86400000 + 1) / 7)
  return [y, w]
}
export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
export const MON3 = MONTHS.map((m) => m.slice(0, 3))
export function fmtDate(d: ISODate): string {
  const [y, m, dd] = d.split('-').map(Number)
  return `${dd} ${MON3[m - 1]} ${y}`
}
export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

// Sensor colors: consistent everywhere, distinguishable, not red (red is reserved for documented exceedances).
export const SERIES_COLOR: Record<string, string> = {
  MODIS: '#0f766e',
  VIIRS_N20: '#d97706',
  VIIRS_N21: '#7c3aed',
  VIIRS_SNPP: '#2563eb',
  UNION: '#334155',
}
export const SERIES_SHORT: Record<string, string> = {
  MODIS: 'MODIS',
  VIIRS_N20: 'VIIRS NOAA-20',
  VIIRS_N21: 'VIIRS NOAA-21',
  VIIRS_SNPP: 'VIIRS S-NPP',
  UNION: 'Any selected sensor',
}
export const PLATFORM_SERIES: Record<string, string> = { Terra: 'MODIS', Aqua: 'MODIS', N20: 'VIIRS_N20', N21: 'VIIRS_N21', SNPP: 'VIIRS_SNPP' }
export const PLATFORM_LABEL: Record<string, string> = { Terra: 'Terra (MODIS)', Aqua: 'Aqua (MODIS)', N20: 'NOAA-20 (VIIRS)', N21: 'NOAA-21 (VIIRS)', SNPP: 'Suomi NPP (VIIRS)' }

export const METRIC_INFO: Record<string, { label: string; unit: string; short: string }> = {
  cells: { label: 'Occupied grid cells', unit: 'cells/day', short: 'cells' },
  detections: { label: 'Detections', unit: 'detections/day', short: 'detections' },
  frp_sum: { label: 'Summed FRP', unit: 'MW (sum)', short: 'MW Σ' },
  frp_max: { label: 'Maximum FRP', unit: 'MW', short: 'MW max' },
  frp_mean: { label: 'Mean FRP', unit: 'MW', short: 'MW mean' },
}

// Sequential activity ramp (pale amber -> deep burnt orange). Zero and unknown have their own encodings.
export const RAMP = ['#fef3c7', '#fde68a', '#fcd34d', '#fbbf24', '#f59e0b', '#ea580c', '#c2410c', '#7c2d12']
export function rampColor(v: number, max: number): string {
  if (max <= 0) return RAMP[0]
  const t = Math.min(1, Math.max(0, v / max))
  const i = Math.min(RAMP.length - 1, Math.floor(Math.sqrt(t) * RAMP.length))
  return RAMP[i]
}
export function rampBins(max: number): number[] {
  // lower edges per bin (sqrt scale) for legends
  return RAMP.map((_, i) => Math.round(((i / RAMP.length) ** 2) * max * 100) / 100)
}

export const STATUS_LABEL: Record<string, string> = {
  detections: 'Detections recorded',
  zero_reported: 'Zero detections reported in an imported interval',
  unknown: 'Unknown coverage (not treated as zero)',
  sensor_unavailable: 'Sensor/product unavailable',
  outside_range: 'Outside imported range',
}

export function cls(...xs: (string | false | null | undefined)[]): string {
  return xs.filter(Boolean).join(' ')
}

export function downloadBlob(data: BlobPart, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([data], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
