// AOI Insights (added in v1.3): types, settings store, request builders, colours and bilingual (EN/ID) wording.
// Everything describes OBSERVED satellite detections for ONE sensor series. Nothing here is a forecast.
import { create } from 'zustand'
import type { Envelope, Inventory } from './api'
import { filterParams, type AppState } from './state'
import { addDays, type ISODate } from './util'

export type InsSeries = 'MODIS' | 'VIIRS_SNPP' | 'VIIRS_N20' | 'VIIRS_N21'
export type Role = 'warning' | 'responder' | 'manager' | 'scientist' | 'all'
export type SectionId = 'now' | 'tracker' | 'regime' | 'anomaly' | 'critical' | 'map' | 'years' | 'compare'
export type Lang = 'en' | 'id'

export const SECTION_LABEL: Record<SectionId, string> = {
  now: 'Status now (near real time)',
  tracker: 'Season tracker',
  regime: 'Fire regime',
  anomaly: 'Unusual conditions',
  critical: 'Critical periods and readiness calendar',
  map: 'Map: recurrence and unusual cells',
  years: 'Years and climate background',
  compare: 'Compare areas',
}

export const ROLES: { id: Role; label: string; hint: string; sections: SectionId[] }[] = [
  { id: 'warning', label: 'Early warning', hint: 'Is this season unusual so far, and what does the recent record say?',
    sections: ['now', 'tracker', 'anomaly', 'critical', 'years'] },
  { id: 'responder', label: 'Emergency responder', hint: 'Where does fire recur, and when are the historically critical weeks?',
    sections: ['now', 'map', 'critical', 'tracker'] },
  { id: 'manager', label: 'Land manager', hint: 'Chronic hotspots, the usual season and how areas compare.',
    sections: ['map', 'regime', 'critical', 'compare', 'years'] },
  { id: 'scientist', label: 'Scientist', hint: 'Every section, the method and the reproducible package.',
    sections: ['regime', 'tracker', 'anomaly', 'critical', 'map', 'years', 'compare', 'now'] },
  { id: 'all', label: 'All sections', hint: 'Everything in the default order.',
    sections: ['now', 'tracker', 'regime', 'anomaly', 'critical', 'map', 'years', 'compare'] },
]

export interface InsState {
  role: Role
  series: InsSeries
  asOf: ISODate | null
  mapMode: 'recurrence' | 'anomaly'
  cellWindow: 7 | 30 | 90
  chronicShare: number
  percentile: number
  nowRun: number // 0 = not requested; increments to fetch again
  lang: Lang
  briefing: boolean
  methodOpen: boolean
  compare: string[]
  set: (p: Partial<InsState>) => void
}

export const useIns = create<InsState>((set) => ({
  role: 'warning',
  series: 'MODIS',
  asOf: null,
  mapMode: 'recurrence',
  cellWindow: 30,
  chronicShare: 0.4,
  percentile: 90,
  nowRun: 0,
  lang: 'en',
  briefing: false,
  methodOpen: false,
  compare: [],
  set: (p) => set(p),
}))

export const INS_SERIES_PLATFORMS: Record<InsSeries, string[]> = { MODIS: ['Terra', 'Aqua'], VIIRS_SNPP: ['SNPP'], VIIRS_N20: ['N20'], VIIRS_N21: ['N21'] }

/** Last imported day of one sensor series (the default "as of" day). */
export function seriesLastDay(inv: Inventory | null, series: InsSeries): ISODate | null {
  const plats = INS_SERIES_PLATFORMS[series]
  const ds = (inv?.products ?? []).filter((p) => plats.includes(p.platform)).map((p) => p.last_date).sort()
  return ds.length ? ds[ds.length - 1] : null
}

/** Query string for an insights request. The history always starts at the first imported day (server side);
 *  `start` only sets the scored window where one is used. All platforms of the chosen series are included. */
export function insQS(s: AppState, series: InsSeries, start: ISODate, end: ISODate, extra: Record<string, string | number> = {}): string {
  const p = filterParams(s)
  p.set('start', start)
  p.set('end', end)
  p.set('platforms', INS_SERIES_PLATFORMS[series].join(','))
  p.set('series', series)
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v))
  return p.toString()
}

/** A cell-anomaly window may not start or end on 29 February (the same window must exist in earlier years). */
export function cellWindow(asOf: ISODate, days: number): [ISODate, ISODate] {
  let end = asOf
  if (end.endsWith('-02-29')) end = addDays(end, -1)
  let start = addDays(end, -(days - 1))
  if (start.endsWith('-02-29')) start = addDays(start, 1)
  return [start, end]
}

// ---- response types (subset used by the UI)
export interface Disclaimed { method_version: string; disclaimer: string }
export interface SeasonPoint { median_doy: number; p10_doy: number; p90_doy: number; n_years: number; median: string; early: string; late: string }
export interface TrackerStatus {
  as_of: string; cumulative: number; reference_median: number; percentile_among_reference_years: number; years_below: number
  n_reference_years: number; known_days: number; days: number; band: string; sentence: string
}
export interface Regime extends Envelope, Disclaimed {
  available: boolean; reason: string | null; series: InsSeries; series_label: string; focus_year: number; as_of: string
  history: { start: string; end: string }
  weeks: { week: number; label: string; n_years: number; median: number | null; p10: number | null; p90: number | null }[]
  focus_weeks: (number | null)[]
  peak_week: { week: number; label: string; median: number } | null
  season: { onset: SeasonPoint; peak: SeasonPoint; end: SeasonPoint } | null
  season_by_year: { year: number; total: number; onset_date: string; peak_date: string; end_date: string }[]
  variability: { mean_annual: number; median_annual: number; min: number; max: number; cv: number; max_year: number; min_year: number } | null
  tracker: { days: number; envelope: { p10: number[]; median: number[]; p90: number[] }; focus: number[]; status: TrackerStatus | null; note: string } | null
  years: { year: number; known_share: number; eligible: boolean; total: number; is_focus: boolean }[]
  reference_years: number[]
  rules: Record<string, unknown>
}
export interface Score {
  value: number; z: number; band: string; reference_median: number; reference_p25: number; reference_p75: number; n_reference: number
  scale: number; floor_applied: boolean; higher_than_pct: number
}
export interface AnomDay extends Partial<Omit<Score, 'value' | 'z' | 'band'>> { date: string; value: number | null; z: number | null; band: string | null; state: string; reference_years?: number }
export interface AnomWeek extends Partial<Omit<Score, 'value' | 'z' | 'band'>> { year: number; week: number; label: string; value: number | null; z: number | null; band: string | null; state: string }
export interface Anomaly extends Envelope, Disclaimed {
  series_label: string; days: AnomDay[]; weeks: AnomWeek[]
  summary: { days: number; scored: number; unknown: number; insufficient: number; by_band: Record<string, number>; max: AnomDay | null }
  method: { score: string; reference: string; floor: Record<string, number>; bands: string; why: string }
}
export interface AnomCell extends Score { ci: number; cj: number; lon: number; lat: number; years_with_fire: number }
export interface CellAnomaly extends Envelope, Disclaimed {
  available: boolean; reason: string | null; cells: AnomCell[]; cells_total?: number; truncated?: boolean; grid_size: number
  window: { start: string; end: string }; reference_years: number[]; window_known_days?: number; window_days?: number; notes?: string[]
}
export interface RecCell { ci: number; cj: number; lon: number; lat: number; fire_years: number; share: number; longest_run: number; first_year: number; last_year: number; detections: number; chronic: boolean }
export interface Recurrence extends Envelope, Disclaimed {
  available: boolean; reason: string | null; series_label: string; eligible_years: number[]; n_eligible_years: number; chronic_share: number
  grid_size: number; cells: RecCell[]; cells_total: number; truncated: boolean; chronic_cells: number; histogram: { fire_years: number; cells: number }[]; notes: string[]
}
export interface CritPeriod { start: string; end: string; duration_days: number; peak: number; peak_date: string; total: number; excess: number; year: number; rank: number; reason: string; coverage_notes: string[] }
export interface Critical extends Envelope, Disclaimed {
  available: boolean; reason: string | null; series_label: string; periods: CritPeriod[]; periods_total: number
  readiness: { weeks: { week: number; label: string; years_known: number; years_critical: number; share: number | null }[]; years: number[]; by_year: { year: number; critical_days: number; periods: number }[]; definition: string }
  thresholds_by_year: { year: number; threshold: number | null }[]
  rule: { percentile: number; min_days: number; min_activity: number; min_other_years: number }; rule_text: string
}
export interface PhaseGroup { phase: string; n_years: number; years: number[]; median_total: number | null; median_peak_season: number | null; median_critical_days: number | null; enough: boolean }
export interface YearRow {
  year: number; eligible: boolean; known_share: number; total: number; peak_season_total: number; peak_season_known_days: number
  critical_days: number | null; critical_periods: number | null; enso: string | null; oni: number | null; iod: string | null; dmi: number | null; is_focus: boolean
  rank?: number; vs_median_of_other_years?: number | null
}
export interface ClimateLatest { oni: { season: string; year: number; value: number }; dmi: { year: number; month: number; value: number } }
export interface YearsReport extends Envelope, Disclaimed {
  series_label: string; years: YearRow[]; groups: { enso: PhaseGroup[]; iod: PhaseGroup[] }; focus_year: number
  focus_phase: { year: number; oni: number | null; enso: string | null; dmi: number | null; iod: string | null; oni_complete: boolean; dmi_complete: boolean }
  climate_latest: ClimateLatest; phase_rules: { enso: string; iod: string }; climate_sources: { name: string; url: string; retrieved: string }[]
  peak_months: number[]; notes: string[]
}
export interface CompareRow {
  aoi: string; name: string; area_km2: number | null; small_area: boolean; regime_available: boolean; reason: string | null
  mean_annual: number | null; mean_annual_per_1000km2: number | null; cv: number | null; peak_week: string | null; season_peak: string | null
  tracker: TrackerStatus | null; cells_with_fire: number | null; chronic_cells: number | null; chronic_share_of_fire_cells: number | null
  median_critical_days: number | null; critical_threshold_note?: string
}
export interface CompareRes extends Disclaimed { series_label: string; rows: CompareRow[]; as_of: string; notes: string[] }
export interface NowRes extends Disclaimed {
  available: boolean; detail?: string; series_label: string; source: string; aoi: string; window: { start: string; end: string; days: number }
  days: (Partial<Score> & { date: string; nrt_detections: number; reference_years: number; state: string; z: number | null; band: string | null })[]
  total: number; window_score: (Score & { higher_than_years: number; n_years: number; sentence: string }) | null
  reference_windows: { year: number; total: number }[]; climate_now: ClimateLatest
  counts: { rows_fetched: number; rejected_rows: number; outside_aoi: number; filtered_out: number }; notes: string[]
}

// ---- colours: diverging for anomaly bands (blue below, neutral, orange/red above); red only for "exceptional"
export const BAND_COLOR: Record<string, string> = {
  exceptional: '#b91c1c',
  'well above normal': '#ea580c',
  'above normal': '#f59e0b',
  normal: '#cbd5e1',
  'below normal': '#3b82f6',
}
export const BAND_ORDER = ['exceptional', 'well above normal', 'above normal', 'normal', 'below normal']
export const TRACKER_COLOR: Record<string, string> = {
  'among the highest on record': '#b91c1c',
  'above the usual range': '#ea580c',
  'within the usual range': '#64748b',
  'below the usual range': '#3b82f6',
  'among the lowest on record': '#1d4ed8',
}
export const RECUR_RAMP = ['#fef3c7', '#fde68a', '#fbbf24', '#f59e0b', '#ea580c', '#c2410c', '#7c2d12']

// ---- bilingual wording for the briefing (Indonesian is the second language of the target users)
export const T: Record<Lang, Record<string, string>> = {
  en: {
    title: 'Fire history briefing',
    area: 'Area', sensor: 'Sensor series', asof: 'As of', history: 'History used', generated: 'Generated',
    status: 'This season so far', season: 'Usual fire season (median of complete years)', onset: 'Start (10 % of detections)',
    peak: 'Peak (50 %)', end: 'End (90 %)', peakweek: 'Busiest week of the year (median)', unusual: 'Unusual days in the last 30 days',
    critical: 'Historically critical weeks', criticalTop: 'Largest critical periods on record', climate: 'Climate background',
    recurrence: 'Recurring fire cells', chronic: 'chronic cells (fire in at least {p} % of complete years)', none: 'none',
    nodata: 'Not enough history for this item.', disclaimerTitle: 'Read this first',
    disclaimer: 'Historical description of satellite fire detections. Not a forecast, not a fire-danger rating and not an official warning. Clouds, smoke and overpass timing hide some fires, so few detections do not prove few fires.',
    sources: 'Data: NASA FIRMS (MODIS/VIIRS active fire detections), NOAA CPC ONI and NOAA PSL DMI. Independent prototype, not an official NASA product.',
    years: 'years', of: 'of', weeks: 'Weeks critical in at least a third of complete years', print: 'Print or save as PDF', close: 'Close',
    enso: 'ENSO (latest ONI)', iod: 'IOD (latest DMI)', analog: 'Median annual detections by dry-season ENSO phase',
    exceptional: 'exceptional', 'well above normal': 'well above normal', 'above normal': 'above normal', normal: 'normal', 'below normal': 'below normal',
  },
  id: {
    title: 'Ringkasan riwayat kebakaran',
    area: 'Wilayah', sensor: 'Seri sensor', asof: 'Per tanggal', history: 'Riwayat yang digunakan', generated: 'Dibuat',
    status: 'Musim ini sejauh ini', season: 'Musim kebakaran biasa (median tahun lengkap)', onset: 'Mulai (10 % deteksi)',
    peak: 'Puncak (50 %)', end: 'Berakhir (90 %)', peakweek: 'Minggu tersibuk dalam setahun (median)', unusual: 'Hari tidak biasa dalam 30 hari terakhir',
    critical: 'Minggu kritis secara historis', criticalTop: 'Periode kritis terbesar dalam catatan', climate: 'Latar belakang iklim',
    recurrence: 'Sel kebakaran berulang', chronic: 'sel kronis (ada kebakaran pada sedikitnya {p} % tahun lengkap)', none: 'tidak ada',
    nodata: 'Riwayat belum cukup untuk butir ini.', disclaimerTitle: 'Baca ini dahulu',
    disclaimer: 'Deskripsi historis deteksi kebakaran oleh satelit. Bukan prakiraan, bukan peringkat bahaya kebakaran, dan bukan peringatan resmi. Awan, asap, dan waktu lintasan satelit menyembunyikan sebagian kebakaran, sehingga sedikitnya deteksi tidak membuktikan sedikitnya kebakaran.',
    sources: 'Data: NASA FIRMS (deteksi titik api aktif MODIS/VIIRS), NOAA CPC ONI dan NOAA PSL DMI. Prototipe independen, bukan produk resmi NASA.',
    years: 'tahun', of: 'dari', weeks: 'Minggu yang kritis pada sedikitnya sepertiga tahun lengkap', print: 'Cetak atau simpan sebagai PDF', close: 'Tutup',
    enso: 'ENSO (ONI terbaru)', iod: 'IOD (DMI terbaru)', analog: 'Median deteksi tahunan menurut fase ENSO musim kemarau',
    exceptional: 'luar biasa', 'well above normal': 'jauh di atas normal', 'above normal': 'di atas normal', normal: 'normal', 'below normal': 'di bawah normal',
  },
}

const TRACKER_ID: Record<string, string> = {
  'among the highest on record': 'termasuk yang tertinggi dalam catatan',
  'above the usual range': 'di atas kisaran biasa',
  'within the usual range': 'dalam kisaran biasa',
  'below the usual range': 'di bawah kisaran biasa',
  'among the lowest on record': 'termasuk yang terendah dalam catatan',
}
const PHASE_ID: Record<string, string> = { 'El Niño': 'El Niño', 'La Niña': 'La Niña', neutral: 'netral', positive: 'positif', negative: 'negatif' }
const MON_ID: Record<string, string> = { Jan: 'Jan', Feb: 'Feb', Mar: 'Mar', Apr: 'Apr', May: 'Mei', Jun: 'Jun', Jul: 'Jul', Aug: 'Agu', Sep: 'Sep', Oct: 'Okt', Nov: 'Nov', Dec: 'Des' }

export function phaseText(p: string | null | undefined, lang: Lang): string {
  if (!p) return '—'
  return lang === 'id' ? PHASE_ID[p] ?? p : p
}
/** Translate English month abbreviations inside a "05 Sep" or "24 Sep – 30 Sep" label. */
export function dayLabel(s: string | null | undefined, lang: Lang): string {
  if (!s) return '—'
  return lang === 'id' ? s.replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/g, (m) => MON_ID[m]) : s
}
function n0(v: number, lang: Lang) { return v.toLocaleString(lang === 'id' ? 'id-ID' : 'en-US', { maximumFractionDigits: 0 }) }

/** The tracker sentence, built from numbers so both languages say exactly the same thing. */
export function trackerSentence(st: TrackerStatus, year: number, unit: string, lang: Lang): string {
  const d = dayLabel(fmtDay(st.as_of), lang)
  if (lang === 'id') {
    const u = unit === 'detections' ? 'deteksi' : 'sel-hari terisi'
    return `Hingga ${d}, ${year} mencatat ${n0(st.cumulative, lang)} ${u}: lebih tinggi dari ${st.years_below} dari ${st.n_reference_years} tahun acuan pada tanggal yang sama (median ${n0(st.reference_median, lang)}), ${TRACKER_ID[st.band] ?? st.band}. ${st.known_days} dari ${st.days} hari memiliki cakupan yang diketahui.`
  }
  return `By ${d}, ${year} had ${n0(st.cumulative, lang)} ${unit === 'detections' ? 'detections' : 'occupied cell-days'}: higher than ${st.years_below} of ${st.n_reference_years} reference years at the same date (median ${n0(st.reference_median, lang)}), ${st.band}. ${st.known_days} of ${st.days} days have known coverage.`
}

const MON3 = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function fmtDay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${d} ${MON3[m - 1]} ${y}`
}
