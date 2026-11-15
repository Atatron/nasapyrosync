// Map of the Harmonization tab (added in v1.2): original MODIS, original VIIRS, experimental calibrated estimates,
// stage-2 matching and the held-out calibration error, all from ONE harmonization run.
import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { getJSON, useApi } from '../api'
import { EST_RAMP, ERR_RAMP, improvementColor, rampOf, useHarm, type ErrCell, type HErrors, type HLayer, type HMap, type MapCell, type RegionRatioCell, type RegionRatios } from '../harmonization'
import { useApp } from '../state'
import { RAMP, addDays, clampDate, fmtDate, fmtNum, rampColor } from '../util'
import { ErrorNote, Loading, Seg } from './ui'

const ESRI_ATTR = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors'
const BASE = {
  light: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
  dark: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
}

export const LAYER_LABEL: Record<HLayer, string> = {
  modis: 'Original MODIS',
  viirs: 'Original VIIRS',
  calibrated: 'Experimental calibrated',
  matching: 'Matching (stage 2)',
  errors: 'Calibration error',
}
const VALIDATION_LABEL = { validated: 'validated region', too_few: 'too few held-out units', no_held_out: 'no held-out units' }

function f2(v: number | null | undefined, d = 2) { return v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }) }
function esc(s: string) { return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string)) }

function cellTip(c: MapCell, d: HMap, g: number): string {
  const w = (c.ci * g - 180).toFixed(2), so = (c.cj * g - 90).toFixed(2)
  const lines = [`<b>Cell ${w}°E, ${so}°N</b> (${g}°)`,
    `${esc(d.modis_label)}: <b>${c.modis}</b> detections in ${c.modis_events} event(s)`,
    `${esc(d.viirs_label)}: <b>${c.viirs}</b> detections in ${c.viirs_events} event(s), ${c.viirs_events_in_domain} in model domain`,
    `Matched pairs: <b>${c.pairs}</b>${c.dt_median !== null ? `, median |Δt| ${c.dt_median.toFixed(0)} min` : ''}`]
  if (d.model.calibrated_available) {
    lines.push(`Calibrated estimate (MODIS scale): <b>${f2(c.value_cal)}</b> <span style="opacity:.7">(${d.scope === 'all' ? 'all VIIRS events' : 'model-domain events'}; all events ${f2(c.cal)})</span>`)
    if (c.extrapolated_events) lines.push(`<span style="color:#b45309">${c.extrapolated_events} event(s) above the largest training VIIRS value (extrapolation)</span>`)
  }
  if (d.ratio_model?.available && c.value_ratio != null) lines.push(`Day-level ratio index (c × VIIRS): <b>${f2(c.value_ratio)}</b> <span style="opacity:.7">(validated for AOI daily totals, not for single cells)</span>`)
  lines.push(`Error region: ${VALIDATION_LABEL[c.validation]}${c.region_mae !== null ? `, held-out MAE ${f2(c.region_mae)} (n = ${c.region_n_test})` : c.region_n_test ? ` (n = ${c.region_n_test})` : ''}`)
  return lines.join('<br/>')
}

function errTip(c: ErrCell, e: HErrors): string {
  const g = e.error_grid_deg
  const head = `<b>Region ${(c.ci * g - 180).toFixed(2)}°E, ${(c.cj * g - 90).toFixed(2)}°N</b> (${g}°)`
  if (c.status === 'no_held_out') return `${head}<br/>VIIRS events, but <b>no held-out units</b>: not validated here.<br/>Training units: ${c.n_train}`
  return [head, `${c.status === 'validated' ? '<b>Validated</b>' : `<b>Too few held-out units</b> (minimum ${e.min_n})`}: n = ${c.n_test} held-out, ${c.n_train} training`,
    `Held-out MAE calibrated <b>${f2(c.mae_cal)}</b> vs unadjusted ${f2(c.mae_unadj)} ${e.unit}`,
    `RMSE ${f2(c.rmse_cal)} · MBE ${f2(c.mbe_cal)} · improvement ${c.improvement_pct === null ? '—' : c.improvement_pct.toFixed(0) + ' %'}`].join('<br/>')
}

const RATIO_STATUS = { within: 'held-out total within 0.8–1.25×', outside: 'held-out total outside 0.8–1.25×', too_few: 'too few active held-out days' }
function ratioColor(r: number | null): string {
  if (r === null) return '#94a3b8'
  return r < 0.67 ? '#c2410c' : r < 0.8 ? '#fb923c' : r <= 1.25 ? '#22c55e' : r <= 1.5 ? '#a78bfa' : '#6d28d9'
}
function ratioTip(c: RegionRatioCell, e: RegionRatios): string {
  const g = e.error_grid_deg
  return [`<b>Region ${(c.ci * g - 180).toFixed(2)}°E, ${(c.cj * g - 90).toFixed(2)}°N</b> (${g}°)`, `<b>${RATIO_STATUS[c.status]}</b> · ${c.active_days} active held-out days`,
    `Held-out MODIS ${fmtNum(c.M)} · VIIRS ${fmtNum(c.V)} · estimate c × VIIRS ${f2(c.estimate, 0)}`,
    `Σ estimate / Σ MODIS: <b>${c.ratio === null ? '— (no MODIS detections)' : f2(c.ratio) + '×'}</b> (AOI c = ${f2(e.c, 4)})`].join('<br/>')
}

export default function HarmonizationMap({ run }: { run: string }) {
  const s = useApp()
  const h = useHarm()
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const renderer = useRef<L.Canvas | null>(null)
  const lay = useRef<{ base?: L.TileLayer; cells?: L.LayerGroup; aoi?: L.GeoJSON }>({})
  const runP = useMemo(() => new URLSearchParams(run), [run])
  const runStart = runP.get('start') ?? s.start
  const runEnd = runP.get('end') ?? s.end
  const runAoi = runP.get('aoi') ?? 'none'

  const mq = useApi<HMap>(`/api/harmonization/map?${run}&date=${s.date}&mode=${s.frameMode}&scope=${h.scope}&err_grid=${h.errGrid}&min_n=${h.minN}`)
  const eq = useApi<HErrors>(h.layer === 'errors' && h.errView === 'units' ? `/api/harmonization/errors?${run}&err_grid=${h.errGrid}&min_n=${h.minN}` : null)
  const rq = useApi<RegionRatios>(h.layer === 'errors' && h.errView === 'ratio' ? `/api/harmonization/aggregate/regions?${run}&err_grid=${h.errGrid}&min_days=${h.minDays}` : null)
  const d = mq.data
  const g = d?.model.grid_deg ?? Number(runP.get('unit_grid') ?? 0.1)

  // ---- init
  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { center: [-1.5, 113.5], zoom: 5, minZoom: 3, maxZoom: 12, preferCanvas: true })
    renderer.current = L.canvas({ padding: 0.3 })
    m.attributionControl.setPrefix('Leaflet')
    map.current = m
    getJSON<GeoJSON.Feature>('/api/regions/indonesia.geojson').then((f) => {
      L.geoJSON(f, { interactive: false, style: { color: '#64748b', weight: 0.8, fill: false, opacity: 0.7 } }).addTo(m).bringToBack()
    }).catch(() => {})
    return () => { m.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m) return
    lay.current.base?.remove()
    lay.current.base = undefined
    if (s.basemap !== 'none') {
      lay.current.base = L.tileLayer(BASE[s.basemap], { attribution: ESRI_ATTR + ' · static basemap', maxNativeZoom: 16, maxZoom: 19 }).addTo(m)
      lay.current.base.bringToBack()
    }
  }, [s.basemap])

  // ---- AOI of the run (outline + zoom)
  useEffect(() => {
    const m = map.current
    lay.current.aoi?.remove()
    lay.current.aoi = undefined
    if (!m || runAoi === 'none') return
    const url = runAoi.startsWith('region:') ? `/api/regions/${runAoi.slice(7)}.geojson` : `/api/aoi/${encodeURIComponent(runAoi)}`
    let alive = true
    getJSON<GeoJSON.Feature>(url).then((f) => {
      if (!alive || !map.current) return
      lay.current.aoi = L.geoJSON(f, { interactive: false, style: { color: '#0f1d3a', weight: 2, dashArray: '5 4', fill: false } }).addTo(map.current)
      const b = lay.current.aoi.getBounds()
      if (b.isValid()) map.current.fitBounds(b, { padding: [20, 20], maxZoom: 9, animate: false })
    }).catch(() => {})
    return () => { alive = false }
  }, [runAoi])

  // ---- scales: MODIS and calibrated share one MODIS-scale ramp; VIIRS has its own
  const scales = useMemo(() => {
    const cs = d?.cells ?? []
    const maxM = Math.max(1, ...cs.map((c) => c.modis))
    const maxC = Math.max(0, ...cs.map((c) => (h.estimate === 'ratio' ? c.value_ratio : c.value_cal) ?? 0))
    return { modisScale: Math.max(maxM, maxC), viirs: Math.max(1, ...cs.map((c) => c.viirs)) }
  }, [d, h.estimate])
  const errMax = useMemo(() => Math.max(0.5, ...(eq.data?.cells ?? []).filter((c) => c.status !== 'no_held_out').map((c) => c.mae_cal ?? 0)), [eq.data])
  const tol = Number(runP.get('tolerance_min') ?? 30)

  // ---- draw
  useEffect(() => {
    const m = map.current
    if (!m) return
    lay.current.cells?.remove()
    lay.current.cells = undefined
    const grp = L.layerGroup()
    const rect = (ci: number, cj: number, size: number, o: L.PathOptions, tip: string, onClick?: () => void) => {
      const w = ci * size - 180, so = cj * size - 90
      const r = L.rectangle([[so, w], [so + size, w + size]], { renderer: renderer.current!, ...o })
      r.bindTooltip(tip, { sticky: true })
      if (onClick) r.on('click', onClick)
      grp.addLayer(r)
    }
    if (h.layer === 'errors' && h.errView === 'ratio') {
      const e = rq.data
      if (!e) return
      for (const c of e.cells) {
        const tip = ratioTip(c, e)
        if (c.status === 'too_few') rect(c.ci, c.cj, e.error_grid_deg, { weight: 0.8, color: '#64748b', dashArray: '3 3', fillColor: '#94a3b8', fillOpacity: 0.3 }, tip)
        else rect(c.ci, c.cj, e.error_grid_deg, { weight: 0.5, color: '#1e293b', fillColor: ratioColor(c.ratio), fillOpacity: 0.85 }, tip)
      }
    } else if (h.layer === 'errors') {
      const e = eq.data
      if (!e) return
      for (const c of e.cells) {
        const tip = errTip(c, e)
        if (c.status === 'validated') {
          const fill = h.errColor === 'mae' ? rampOf(ERR_RAMP, c.mae_cal ?? 0, errMax) : improvementColor(c.improvement_pct ?? 0)
          rect(c.ci, c.cj, e.error_grid_deg, { weight: 0.5, color: '#1e293b', fillColor: fill, fillOpacity: 0.85 }, tip)
        } else if (c.status === 'too_few') {
          rect(c.ci, c.cj, e.error_grid_deg, { weight: 0.8, color: '#64748b', dashArray: '3 3', fillColor: '#94a3b8', fillOpacity: 0.35 }, tip)
        } else {
          rect(c.ci, c.cj, e.error_grid_deg, { weight: 1, color: '#94a3b8', dashArray: '2 4', fill: false }, tip)
        }
      }
    } else if (d) {
      for (const c of d.cells) {
        const sel = h.selCell && h.selCell.ci === c.ci && h.selCell.cj === c.cj
        const click = () => useHarm.getState().set({ selCell: { ci: c.ci, cj: c.cj } })
        const tip = cellTip(c, d, g)
        const edge = sel ? { weight: 2.5, color: '#0f1d3a' } : null
        if (h.layer === 'modis') {
          if (c.modis > 0) rect(c.ci, c.cj, g, { weight: 0.4, color: '#7c2d12', ...edge, fillColor: rampColor(c.modis, scales.modisScale), fillOpacity: 0.85 }, tip, click)
        } else if (h.layer === 'viirs') {
          if (c.viirs > 0) rect(c.ci, c.cj, g, { weight: 0.4, color: '#7c2d12', ...edge, fillColor: rampColor(c.viirs, scales.viirs), fillOpacity: 0.85 }, tip, click)
        } else if (h.layer === 'calibrated' && h.estimate === 'ratio') {
          if (!d.ratio_model?.available || c.viirs_events === 0 || !c.value_ratio) continue
          rect(c.ci, c.cj, g, { weight: 0.6, color: '#581c87', ...edge, fillColor: rampOf(EST_RAMP, c.value_ratio, scales.modisScale), fillOpacity: 0.8 }, tip, click)
        } else if (h.layer === 'calibrated') {
          if (!d.model.calibrated_available || c.viirs_events === 0) continue
          const v = c.value_cal ?? 0
          const validated = c.validation === 'validated'
          if (v <= 0) {
            rect(c.ci, c.cj, g, { weight: 0.8, color: '#a855f7', dashArray: '2 3', fill: false, ...edge }, tip, click)
          } else {
            rect(c.ci, c.cj, g, { weight: validated ? 0.6 : 1, color: validated ? '#581c87' : '#64748b', dashArray: validated ? undefined : '3 3', ...edge,
              fillColor: rampOf(EST_RAMP, v, scales.modisScale), fillOpacity: validated ? 0.85 : 0.4 }, tip, click)
          }
        } else if (h.layer === 'matching') {
          if (c.pairs > 0) {
            const t = Math.min(1, (c.dt_median ?? 0) / Math.max(1, tol))
            const fill = t < 0.34 ? '#16a34a' : t < 0.67 ? '#eab308' : '#f97316'
            rect(c.ci, c.cj, g, { weight: 0.6, color: '#14532d', ...edge, fillColor: fill, fillOpacity: 0.85 }, tip, click)
          } else if (c.modis_events > 0 && c.viirs_events > 0) {
            rect(c.ci, c.cj, g, { weight: 1.2, color: '#475569', ...edge, fillColor: '#cbd5e1', fillOpacity: 0.5 }, tip, click)
          } else if (c.modis_events > 0) {
            rect(c.ci, c.cj, g, { weight: 1.4, color: '#0f766e', ...edge, fill: false }, tip, click)
          } else {
            rect(c.ci, c.cj, g, { weight: 1, color: '#2563eb', ...edge, fill: false }, tip, click)
          }
        }
      }
    }
    grp.addTo(m)
    lay.current.cells = grp
  }, [d, eq.data, rq.data, h.layer, h.errView, h.estimate, h.selCell, h.errColor, scales, errMax, g, tol])

  const outOfRun = s.date < runStart || s.date > runEnd
  const step = (n: number) => s.set({ date: clampDate(addDays(s.date, n), runStart, runEnd) })
  const loading = (h.layer === 'errors' ? (h.errView === 'ratio' ? rq.loading || !rq.data : eq.loading || !eq.data) : mq.loading || !d)
  const role = d?.window.period_role

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2 text-xs" data-testid="hmap-controls">
        <Seg label="Map layer" value={h.layer} onChange={(v) => h.set({ layer: v })}
          options={(['modis', 'viirs', 'calibrated', 'matching', 'errors'] as HLayer[]).map((k) => ({ value: k, label: LAYER_LABEL[k] }))} />
        {h.layer !== 'errors' && <>
          <div className="flex items-center gap-1">
            <button className="btn px-2" aria-label="Previous day" onClick={() => step(-1)}>‹</button>
            <input type="date" className="field" aria-label="Map date (UTC)" data-testid="hmap-date" value={s.date} min={runStart} max={runEnd}
              onChange={(e) => e.target.value && s.set({ date: clampDate(e.target.value, runStart, runEnd) })} />
            <button className="btn px-2" aria-label="Next day" onClick={() => step(1)}>›</button>
          </div>
          <Seg label="Window" value={s.frameMode} onChange={(v) => s.set({ frameMode: v })} options={[{ value: 1, label: '1 day' }, { value: 7, label: '7 days' }, { value: 30, label: '30 days' }]} />
        </>}
        {h.layer === 'calibrated' && <Seg label="Estimate" value={h.estimate} onChange={(v) => h.set({ estimate: v })}
          options={[{ value: 'event', label: 'Event model (1.0)', title: 'Log-log model per VIIRS event' }, { value: 'ratio', label: 'Day-level ratio index (1.4)', title: 'c × VIIRS detections per cell' }]} />}
        {h.layer === 'calibrated' && h.estimate === 'event' && <Seg label="Events in estimate" value={h.scope} onChange={(v) => h.set({ scope: v })}
          options={[{ value: 'domain', label: 'In model domain only', title: 'Only VIIRS events of the kind the model was fitted on' }, { value: 'all', label: 'All VIIRS events', title: 'Includes events outside the fitted domain (tends to overstate)' }]} />}
        {h.layer === 'errors' && <Seg label="Error view" value={h.errView} onChange={(v) => h.set({ errView: v })}
          options={[{ value: 'units', label: 'Unit-level MAE (1.0)' }, { value: 'ratio', label: 'Regional daily totals (1.4)' }]} />}
        {h.layer === 'errors' && h.errView === 'units' && <Seg label="Colour by" value={h.errColor} onChange={(v) => h.set({ errColor: v })}
          options={[{ value: 'mae', label: 'Held-out MAE' }, { value: 'improvement', label: 'Improvement vs unadjusted' }]} />}
      </div>
      {outOfRun && <p className="text-[11px] text-amber-700">The selected date {s.date} is outside the run's range ({runStart} → {runEnd}); choose a date inside it.</p>}
      <div className="relative h-[58vh] min-h-[380px] overflow-hidden rounded-xl border border-line">
        <div ref={el} className="absolute inset-0" role="region" aria-label={`Harmonization map: ${LAYER_LABEL[h.layer]}`} data-testid="hmap" />
        <div className="pointer-events-none absolute left-14 right-2 top-2 z-[500] flex flex-col items-start gap-1 text-[11px]">
          <div className="pointer-events-auto rounded-md bg-panel/95 px-2 py-1 shadow" data-testid="hmap-label">
            <b>{LAYER_LABEL[h.layer]}</b>{h.layer === 'errors'
              ? ` · held-out units ${eq.data ? `${eq.data.model.test_period?.[0]} → ${eq.data.model.test_period?.[1]}` : ''}, regions ${h.errGrid}°, minimum ${h.minN} units`
              : ` · ${s.frameMode === 1 ? `${s.date} UTC` : `${addDays(s.date, -(s.frameMode - 1))} → ${s.date} UTC`} · ${g}° comparison grid`}
          </div>
          {h.layer !== 'errors' && role && <div className={'rounded-md px-2 py-1 shadow ' + (role === 'held_out' ? 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' : 'bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100')} data-testid="hmap-role">
            {role === 'held_out' ? 'Held-out period' : role === 'training' ? 'Training period (in-sample)' : 'Window spans the split date'}: {d?.window.period_role_doc}</div>}
          {h.layer === 'calibrated' && h.estimate === 'ratio' && d && <div className={'pointer-events-auto max-w-md rounded-md px-2 py-1 shadow ' + (d.ratio_model?.available ? 'bg-panel/95' : 'bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100')} data-testid="hmap-ratio-note">
            {d.ratio_model?.available ? <>{d.ratio_model.label}; c = {f2(d.ratio_model.c, 4)}.</> : <><b>No day-level estimates:</b> the day-level ratio does not pass the aggregate gate for this AOI and sensor pair (see section 5).</>}</div>}
          {h.layer === 'calibrated' && h.estimate === 'event' && d && !d.model.calibrated_available && <div className="pointer-events-auto max-w-md rounded-md bg-amber-50 px-2 py-1 text-amber-900 shadow dark:bg-amber-950 dark:text-amber-100" data-testid="hmap-cal-unavailable">
            <b>No calibrated estimates:</b> this run does not pass the validity rules ({d.model.calibrated_unavailable_reason}).</div>}
        </div>
        {loading && <div role="status" data-testid="hmap-loading" className="absolute inset-x-0 bottom-3 z-[600] mx-auto flex w-fit items-center gap-2 rounded-full bg-panel px-3 py-1.5 text-xs shadow-lg"><span className="spinner" aria-hidden />Loading {h.layer === 'errors' ? 'error map' : fmtDate(s.date)}…</div>}
        {(mq.error || eq.error || rq.error) && <div className="absolute bottom-14 left-2 z-[600] max-w-sm"><ErrorNote msg={(mq.error || eq.error || rq.error) as string} /></div>}
        {h.layer === 'errors' && h.errView === 'ratio' ? <RatioLegend minDays={h.minDays} />
          : <Legend layer={h.layer} d={d} e={eq.data} scales={scales} errMax={errMax} errColor={h.errColor} tol={tol} ratio={h.estimate === 'ratio'} />}
      </div>
    </div>
  )
}

function RatioLegend({ minDays }: { minDays: number }) {
  const sw = (c: string) => <span className="inline-block h-2.5 w-4" style={{ background: c }} />
  return (
    <div className="absolute bottom-2 right-2 z-[500] max-w-[300px] rounded-lg bg-panel/95 px-2 py-1.5 text-[10px] shadow" aria-label="Map legend" data-testid="hmap-legend">
      <div className="mb-1 font-semibold">Held-out Σ (c × VIIRS) / Σ MODIS per region</div>
      <div className="flex flex-wrap items-center gap-1">{sw('#c2410c')}&lt; 0.67{sw('#fb923c')}0.67–0.8{sw('#22c55e')}0.8–1.25{sw('#a78bfa')}1.25–1.5{sw('#6d28d9')}&gt; 1.5</div>
      <div className="mt-0.5 flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-dashed border-slate-500 bg-slate-400/40" />Fewer than {minDays} active held-out days</div>
      <div className="mt-0.5 text-muted">One AOI-wide c is applied everywhere; this view shows where that c holds and where it does not.</div>
    </div>
  )
}

function Legend({ layer, d, e, scales, errMax, errColor, tol, ratio }: { layer: HLayer; d: HMap | null; e: HErrors | null; scales: { modisScale: number; viirs: number }; errMax: number; errColor: 'mae' | 'improvement'; tol: number; ratio?: boolean }) {
  const sw = (c: string, extra = '') => <span className={'inline-block h-2.5 w-4 ' + extra} style={{ background: c }} />
  return (
    <div className="absolute bottom-2 right-2 z-[500] max-w-[300px] rounded-lg bg-panel/95 px-2 py-1.5 text-[10px] shadow" aria-label="Map legend" data-testid="hmap-legend">
      {layer === 'modis' || layer === 'viirs' ? <>
        <div className="mb-1 font-semibold">{layer === 'modis' ? d?.modis_label : d?.viirs_label} detections per cell (observed)</div>
        <div className="flex items-center gap-1"><span>1</span>{RAMP.map((c) => <span key={c}>{sw(c)}</span>)}<span>{fmtNum(layer === 'modis' ? scales.modisScale : scales.viirs)}</span></div>
        <div className="mt-0.5 text-muted">{layer === 'modis' ? 'Same MODIS scale as the calibrated layer.' : 'Own scale: VIIRS counts are not on the MODIS scale.'} Cells are grid summaries, not burned area.</div>
      </> : layer === 'calibrated' && ratio ? <>
        <div className="mb-1 font-semibold">Day-level ratio index per cell: c × VIIRS detections (estimate)</div>
        <div className="flex items-center gap-1"><span>0</span>{EST_RAMP.map((c) => <span key={c}>{sw(c)}</span>)}<span>{fmtNum(scales.modisScale, 1)}</span></div>
        <div className="mt-0.5 text-muted">MODIS-equivalent index. Validated for AOI daily totals only; a single cell's value is not a tested MODIS count.</div>
      </> : layer === 'calibrated' ? <>
        <div className="mb-1 font-semibold">Estimated MODIS-scale detections per cell (not observations)</div>
        <div className="flex items-center gap-1"><span>0</span>{EST_RAMP.map((c) => <span key={c}>{sw(c)}</span>)}<span>{fmtNum(scales.modisScale, 1)}</span></div>
        <div className="mt-0.5 flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-dashed border-slate-500 bg-purple-200/40" />Faded, dashed: region not validated (too few or no held-out units)</div>
        <div className="flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-dashed border-purple-500" />Outline only: VIIRS events outside the model domain</div>
        <div className="mt-0.5 text-muted">Estimate on the grid from VIIRS events; no new hotspots are created.</div>
      </> : layer === 'matching' ? <>
        <div className="mb-1 font-semibold">Stage 2 in this window</div>
        <div className="flex items-center gap-1">{sw('#16a34a')}matched, median |Δt| &lt; {Math.round(tol / 3)} min</div>
        <div className="flex items-center gap-1">{sw('#eab308')}matched, {Math.round(tol / 3)}–{Math.round((2 * tol) / 3)} min</div>
        <div className="flex items-center gap-1">{sw('#f97316')}matched, ≥ {Math.round((2 * tol) / 3)} min (tolerance ±{tol})</div>
        <div className="flex items-center gap-1">{sw('#cbd5e1', 'border border-slate-600')}both sensors, but not within tolerance</div>
        <div className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 border-2 border-teal-700" />MODIS only</div>
        <div className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 border border-blue-600" />VIIRS only</div>
        <div className="mt-0.5 text-muted">One-sided cells are not proof that the other sensor saw nothing (coverage is not verified).</div>
      </> : <>
        <div className="mb-1 font-semibold">{errColor === 'mae' ? `Held-out MAE per region (${e?.unit ?? ''})` : 'Held-out MAE improvement vs unadjusted VIIRS'}</div>
        {errColor === 'mae'
          ? <div className="flex items-center gap-1"><span>0</span>{ERR_RAMP.map((c) => <span key={c}>{sw(c)}</span>)}<span>{f2(errMax)}</span></div>
          : <div className="flex flex-wrap items-center gap-1">{sw('#c2410c')}&lt; −25 %{sw('#fb923c')}worse{sw('#dcfce7')}0–25{sw('#86efac')}25–50{sw('#22c55e')}50–75{sw('#15803d')}≥ 75 %</div>}
        <div className="mt-0.5 flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-dashed border-slate-500 bg-slate-400/40" />Too few held-out units (&lt; {e?.min_n})</div>
        <div className="flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-dashed border-slate-400" />VIIRS activity, no held-out units: not validated</div>
      </>}
    </div>
  )
}

export function WindowDetails({ run }: { run: string }) {
  const s = useApp()
  const h = useHarm()
  const mq = useApi<HMap>(h.layer === 'errors' ? null : `/api/harmonization/map?${run}&date=${s.date}&mode=${s.frameMode}&scope=${h.scope}&err_grid=${h.errGrid}&min_n=${h.minN}`)
  const eq = useApi<HErrors>(h.layer === 'errors' && h.errView === 'units' ? `/api/harmonization/errors?${run}&err_grid=${h.errGrid}&min_n=${h.minN}` : null)
  const rq = useApi<RegionRatios>(h.layer === 'errors' && h.errView === 'ratio' ? `/api/harmonization/aggregate/regions?${run}&err_grid=${h.errGrid}&min_days=${h.minDays}` : null)
  const d = mq.data
  if (h.layer === 'errors' && h.errView === 'ratio') {
    const e = rq.data
    if (!e) return rq.error ? <ErrorNote msg={rq.error} /> : <Loading />
    return (
      <div className="space-y-2 text-xs" data-testid="hratio-summary">
        <div className="flex flex-wrap items-end gap-2">
          <Seg label="Region size" value={h.errGrid} onChange={(v) => h.set({ errGrid: v })} options={e.error_grids.map((x) => ({ value: x, label: `${x}°` }))} />
          <Seg label="Minimum active held-out days" value={h.minDays} onChange={(v) => h.set({ minDays: v })} options={e.min_days_choices.map((x) => ({ value: x, label: `≥ ${x}` }))} />
        </div>
        <table className="data"><tbody>
          <tr><td>AOI coefficient c</td><td className="num">{f2(e.c, 4)} (aggregate gate: {e.gate_status ?? '—'})</td></tr>
          <tr><td>Held-out period from</td><td className="num">{e.split ?? '—'}</td></tr>
          <tr><td>Regions within 0.8–1.25×</td><td className="num" data-testid="hratio-within">{fmtNum(e.summary.within)}</td></tr>
          <tr><td>Regions outside 0.8–1.25×</td><td className="num">{fmtNum(e.summary.outside)}</td></tr>
          <tr><td>Regions with too few active days</td><td className="num">{fmtNum(e.summary.too_few)}</td></tr>
        </tbody></table>
        <p className="text-[11px] text-muted">{e.definition}</p>
      </div>
    )
  }
  if (h.layer === 'errors') {
    const e = eq.data
    if (!e) return eq.error ? <ErrorNote msg={eq.error} /> : <Loading />
    const sm = e.summary
    return (
      <div className="space-y-2 text-xs" data-testid="herr-summary">
        <div className="flex flex-wrap items-end gap-2">
          <Seg label="Region size" value={h.errGrid} onChange={(v) => h.set({ errGrid: v })} options={e.error_grids.map((x) => ({ value: x, label: `${x}°` }))} />
          <Seg label="Minimum held-out units" value={h.minN} onChange={(v) => h.set({ minN: v })} options={e.min_n_choices.map((x) => ({ value: x, label: `n ≥ ${x}` }))} />
        </div>
        {!sm ? <p className="text-amber-700">The model was not fitted, so there are no held-out errors.</p> : (
          <table className="data"><tbody>
            <tr><td>Validated regions (n ≥ {e.min_n})</td><td className="num" data-testid="herr-validated">{fmtNum(sm.cells_validated)}</td></tr>
            <tr><td>Regions with too few held-out units</td><td className="num">{fmtNum(sm.cells_too_few)}</td></tr>
            <tr><td>Regions with VIIRS activity but no held-out units</td><td className="num">{fmtNum(sm.cells_no_held_out)}</td></tr>
            <tr><td>Held-out units in validated regions</td><td className="num">{fmtNum(sm.held_out_units_in_validated_cells)} of {fmtNum(sm.held_out_units)} ({sm.share_in_validated_cells === null ? '—' : (100 * sm.share_in_validated_cells).toFixed(1) + ' %'})</td></tr>
            <tr><td>MAE range in validated regions</td><td className="num">{sm.validated_cells_mae_cal_range ? `${f2(sm.validated_cells_mae_cal_range[0])} – ${f2(sm.validated_cells_mae_cal_range[1])}` : '—'} {e.unit}</td></tr>
            <tr><td>Validated regions where calibrated is worse than unadjusted</td><td className="num">{fmtNum(sm.validated_cells_worse_than_unadjusted)}</td></tr>
            <tr><td>Overall held-out MAE (all units)</td><td className="num">{f2(sm.overall_mae_cal, 3)} vs unadjusted {f2(sm.overall_mae_unadj, 3)}</td></tr>
          </tbody></table>)}
        <p className="text-[11px] text-muted">{e.definition}</p>
      </div>
    )
  }
  if (!d) return mq.error ? <ErrorNote msg={mq.error} /> : <Loading />
  const t = d.totals
  const sel = h.selCell ? d.cells.find((c) => c.ci === h.selCell!.ci && c.cj === h.selCell!.cj) : null
  const selPairs = sel ? d.pairs.filter((p) => p.ci === sel.ci && p.cj === sel.cj) : []
  return (
    <div className="space-y-3 text-xs" data-testid="hmap-details">
      <table className="data" data-testid="hmap-totals"><tbody>
        <tr><td>{d.modis_label} detections (observed)</td><td className="num" data-testid="hmap-total-modis">{fmtNum(t.modis)}</td></tr>
        <tr><td>{d.viirs_label} detections (observed)</td><td className="num" data-testid="hmap-total-viirs">{fmtNum(t.viirs)}</td></tr>
        <tr><td>Matched pairs (stage 2)</td><td className="num" data-testid="hmap-total-pairs">{fmtNum(t.pairs)}</td></tr>
        <tr><td>Calibrated estimate, model-domain events</td><td className="num">{t.cal_domain === null ? 'not available' : f2(t.cal_domain, 1)}</td></tr>
        <tr><td>Calibrated estimate, all VIIRS events</td><td className="num">{t.cal === null ? 'not available' : f2(t.cal, 1)}</td></tr>
        <tr><td>Cells with VIIRS events in a validated region</td><td className="num">{fmtNum(t.cells_viirs_validated)} of {fmtNum(t.cells_viirs)}</td></tr>
      </tbody></table>
      <p className="text-[11px] text-muted">{d.event_day_rule} {d.model.estimate_doc}</p>
      {(d.suggested_days.held_out.length > 0 || d.suggested_days.training.length > 0) && (
        <div>
          <div className="label mb-1">Days with many matched pairs</div>
          {(['held_out', 'training'] as const).map((k) => d.suggested_days[k].length > 0 && (
            <div key={k} className="mb-1 flex flex-wrap items-center gap-1"><span className="w-16 text-muted">{k === 'held_out' ? 'Held out' : 'Training'}</span>
              {d.suggested_days[k].map((x) => <button key={x.date} className="btn px-1.5 py-0.5 text-[11px]" onClick={() => s.set({ date: x.date, frameMode: 1 })}>{x.date} ({x.pairs})</button>)}</div>))}
        </div>
      )}
      {sel ? (
        <div data-testid="hmap-cell">
          <div className="label mb-1">Selected cell {(sel.ci * d.model.grid_deg - 180).toFixed(2)}°E, {(sel.cj * d.model.grid_deg - 90).toFixed(2)}°N <button className="ml-1 underline" onClick={() => h.set({ selCell: null })}>clear</button></div>
          <p>MODIS {sel.modis} det. ({sel.modis_events} ev.) · VIIRS {sel.viirs} det. ({sel.viirs_events} ev.) · calibrated {f2(sel.value_cal)} · {VALIDATION_LABEL[sel.validation]}{sel.region_mae !== null ? ` (MAE ${f2(sel.region_mae)}, n = ${sel.region_n_test})` : ''}</p>
          {selPairs.length > 0 ? (
            <table className="data mt-1"><thead><tr><th>MODIS time</th><th>VIIRS time</th><th>|Δt|</th><th>M</th><th>V</th><th>M̂</th><th>Set</th></tr></thead>
              <tbody>{selPairs.map((p, i) => <tr key={i}><td>{p.t_modis.slice(11, 16)} {p.modis_platform}</td><td>{p.t_viirs.slice(11, 16)}</td><td className="num">{p.dt_min.toFixed(0)} min</td><td className="num">{p.M}</td><td className="num">{p.V}</td><td className="num">{f2(p.M_hat)}</td><td>{p.set === 'test' ? 'held out' : p.set === 'train' ? 'training' : '—'}</td></tr>)}</tbody></table>
          ) : <p className="text-muted">No matched pair in this cell in the window.</p>}
        </div>
      ) : <p className="text-muted">Click a cell to see its observations, matched pairs (times, |Δt|, M, V, M̂) and validation status.</p>}
      {d.truncated && <p className="text-amber-700">Map truncated to the first cells of the window.</p>}
    </div>
  )
}
