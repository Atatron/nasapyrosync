import { useEffect, useRef, useState } from 'react'
import type { Inventory, Region } from '../api'
import { useFilterQS } from '../hooks'
import { frameWindow, serializeState, useApp, viewConfig, type Metric } from '../state'
import { PLATFORM_LABEL, SERIES_SHORT, cls, downloadBlob } from '../util'
import { Icon, Info } from './ui'

export function AoiSelect({ regions, id = 'aoi-select' }: { regions: Region[]; id?: string }) {
  const { aoi, set } = useApp()
  const custom = aoi.startsWith('custom:')
  const circle = aoi.startsWith('circle:')
  return (
    <select id={id} className="field w-auto max-w-[190px]" value={aoi} aria-label="Area of interest"
      onChange={(e) => { const v = e.target.value; if (v.startsWith('circle:')) set({ aoi: v }); else set({ aoi: v, analyzeMode: 'region', clickAt: '', lastRegionAoi: v }) }}>
      <option value="none">All imported observations (no AOI)</option>
      <optgroup label="Named regions (boundaries)">
        {regions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </optgroup>
      {custom && <option value={aoi}>Custom AOI (drawn/uploaded)</option>}
      {circle && <option value={aoi}>Click-to-Analyze circle ({aoi.split(',')[2]} km)</option>}
    </select>
  )
}

export function SeriesMetric() {
  const { series, metric, platforms, set } = useApp()
  const map: Record<string, string> = { Terra: 'MODIS', Aqua: 'MODIS', N20: 'VIIRS_N20', N21: 'VIIRS_N21', SNPP: 'VIIRS_SNPP' }
  const avail = Array.from(new Set(platforms.map((p) => map[p])))
  const opts = ['VIIRS_N20', 'MODIS', 'VIIRS_N21', 'VIIRS_SNPP'].filter((x) => avail.includes(x))
  return (
    <>
      <label className="sr-only" htmlFor="series-select">Sensor for calendar, timeline and flags</label>
      <select id="series-select" className="field w-auto max-w-[170px]" value={series} onChange={(e) => set({ series: e.target.value, ...(e.target.value === 'FUSED' ? { metric: 'detections' } : {}) })}>
        <option value="FUSED" title="Multi-sensor fusion: every eligible satellite calibrated to MODIS Aqua and averaged (detections only)">Harmonized (all sensors)</option>
        {opts.map((o) => <option key={o} value={o}>{SERIES_SHORT[o]}</option>)}
        <option value="UNION" disabled={metric !== 'cells'}>Any selected sensor (union)</option>
        {!opts.includes(series) && series !== 'UNION' && series !== 'FUSED' && <option value={series}>{SERIES_SHORT[series] ?? series} (not selected)</option>}
      </select>
      <label className="sr-only" htmlFor="metric-select">Metric</label>
      <select id="metric-select" className="field w-auto max-w-[170px]" value={metric} onChange={(e) => {
        const m = e.target.value as Metric
        set({ metric: m, ...((series === 'UNION' && m !== 'cells') || (series === 'FUSED' && m !== 'detections') ? { series: opts[0] ?? 'VIIRS_N20' } : {}) })
      }}>
        <option value="cells">Occupied cells / day</option>
        <option value="detections">Detections / day</option>
        <option value="frp_sum">Summed FRP (MW)</option>
        <option value="frp_max">Max FRP (MW)</option>
        <option value="frp_mean">Mean FRP (MW)</option>
      </select>
    </>
  )
}

function FilterPanel({ inventory, onClose }: { inventory?: Inventory | null; onClose: () => void }) {
  const s = useApp()
  const avail = inventory?.available_platforms ?? []
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.querySelector<HTMLElement>('input,button')?.focus() }, [])
  return (
    <div ref={ref} role="dialog" aria-label="Filters" onKeyDown={(e) => e.key === 'Escape' && onClose()}
      className="absolute right-0 top-11 z-[1300] w-[340px] max-w-[calc(100vw-1rem)] space-y-4 rounded-xl border border-line bg-panel p-4 text-sm shadow-xl">
      <div>
        <div className="label mb-1">Sensors / platforms</div>
        {['Terra', 'Aqua', 'N20', 'N21', 'SNPP'].map((p) => {
          const has = avail.includes(p)
          return (
            <label key={p} className={cls('flex items-center gap-2 py-0.5', !has && 'text-muted')}>
              <input type="checkbox" checked={s.platforms.includes(p)} onChange={() => s.set({ platforms: toggle(s.platforms, p) })} />
              {PLATFORM_LABEL[p]} {!has && <span className="text-[11px]">(not in imported data)</span>}
            </label>
          )
        })}
        <p className="mt-1 text-[11px] text-muted">Adding satellites can increase detections even if underlying activity is unchanged.</p>
      </div>
      <div>
        <div className="label mb-1">Quality <Info>Sensor-specific filters. MODIS confidence is numeric 0–100 (FIRMS classes: low &lt;30, nominal 30–79, high ≥80). VIIRS confidence is categorical (low/nominal/high) and defined differently. The default preset (MODIS ≥30; VIIRS nominal+high) is a filter choice, not a guarantee of equivalent detection performance.</Info></div>
        <label className="flex items-center gap-2">MODIS confidence ≥
          <input type="number" min={0} max={100} className="field w-20" value={s.modisMinConf} onChange={(e) => s.set({ modisMinConf: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })} />
        </label>
        <div className="mt-1 flex flex-wrap gap-3">VIIRS:
          {['low', 'nominal', 'high'].map((c) => (
            <label key={c} className="flex items-center gap-1"><input type="checkbox" checked={s.viirsConf.includes(c)} onChange={() => s.set({ viirsConf: toggle(s.viirsConf, c) })} />{c}</label>
          ))}
        </div>
        <button className="mt-1 text-[11px] text-accent underline" onClick={() => s.set({ modisMinConf: 30, viirsConf: ['nominal', 'high'] })}>Reset to default preset</button>
      </div>
      <div>
        <div className="label mb-1">Detection type <Info>FIRMS type codes (MODIS/VIIRS user guides): 0 presumed vegetation fire, 1 active volcano, 2 other static land source, 3 offshore. NRT files may lack a type (shown as unknown). Excluded types are disclosed on every derived result.</Info></div>
        {[['0', 'Presumed vegetation fire (0)'], ['1', 'Active volcano (1)'], ['2', 'Other static land source (2)'], ['3', 'Offshore (3)'], ['unknown', 'Unknown / missing type (FIRMS NRT has no type column)']].map(([v, l]) => (
          <label key={v} className="flex items-center gap-2 py-0.5"><input type="checkbox" checked={s.types.includes(v)} onChange={() => s.set({ types: toggle(s.types, v) })} />{l}</label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <div>
          <div className="label mb-1">Day / night</div>
          {['D', 'N'].map((v) => <label key={v} className="mr-3 inline-flex items-center gap-1"><input type="checkbox" checked={s.daynight.includes(v)} onChange={() => s.set({ daynight: toggle(s.daynight, v) })} />{v === 'D' ? 'Day' : 'Night'}</label>)}
        </div>
        <div>
          <div className="label mb-1">Grid <Info>WGS84 degree grid anchored at (−180°, −90°). Degree cells are not equal-area; a 0.01° cell is not 1 km². Auto changes only the map display with the zoom (3–5: 0.25°, 6–7: 0.1°, 8–10: 0.05°, 11+: 0.01°); statistics keep the analysis grid ({s.grid}°). A manual choice sets both.</Info></div>
          <select className="field" value={s.gridMode === 'auto' ? 'auto' : s.grid} onChange={(e) => { const v = e.target.value; if (v === 'auto') s.set({ gridMode: 'auto' }); else s.set({ gridMode: 'manual', grid: Number(v) }) }} aria-label="Grid size">
            <option value="auto">Auto (recommended)</option><option value={0.25}>0.25°</option><option value={0.1}>0.1°</option><option value={0.05}>0.05°</option><option value={0.01}>0.01° (exploration)</option>
          </select>
        </div>
      </div>
      <div className="flex justify-end"><button className="btn" onClick={onClose}>Close</button></div>
    </div>
  )
}

function ExportMenu({ onClose }: { onClose: () => void }) {
  const s = useApp()
  const qs = useFilterQS()
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.querySelector<HTMLElement>('a,button')?.focus() }, [])
  const item = 'flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-soft'
  return (
    <div ref={ref} role="menu" onKeyDown={(e) => e.key === 'Escape' && onClose()} className="absolute right-0 top-11 z-[1300] w-[330px] rounded-xl border border-line bg-panel p-2 text-sm shadow-xl">
      <a role="menuitem" className={item} href={`/api/export/daily.zip?${qs}&series=${s.series}&metric=${s.metric}`} download onClick={() => setTimeout(onClose, 0)}><Icon name="download" /><span><b>Daily summary CSV</b><br /><span className="text-xs text-muted">Analysis range {s.start} → {s.end}, all selected sensors + manifest.json</span></span></a>
      <a role="menuitem" className={item} href={`/api/export/observations.zip?${qs}&window_start=${w0}&window_end=${w1}`} download onClick={() => setTimeout(onClose, 0)}><Icon name="download" /><span><b>Filtered observations CSV</b><br /><span className="text-xs text-muted">Map frame window {w0} → {w1} + manifest.json</span></span></a>
      <a role="menuitem" className={item} href={`/api/export/grid.geojson?${qs}&date=${s.date}&mode=${s.frameMode}`} download onClick={() => setTimeout(onClose, 0)}><Icon name="download" /><span><b>Aggregated grid GeoJSON</b><br /><span className="text-xs text-muted">{s.grid}° cell polygons for the frame window</span></span></a>
      {s.aoi !== 'none'
        ? <a role="menuitem" className={item} href={`/api/export/aoi.geojson?aoi=${encodeURIComponent(s.aoi)}`} download onClick={() => setTimeout(onClose, 0)}><Icon name="download" /><span><b>AOI GeoJSON</b><br /><span className="text-xs text-muted">Selected area boundary (lon/lat)</span></span></a>
        : <div className={cls(item, 'cursor-not-allowed text-muted')} aria-disabled="true"><Icon name="download" /><span><b>AOI GeoJSON</b><br /><span className="text-xs">Select an AOI first</span></span></div>}
      <button role="menuitem" className={item} onClick={() => { downloadBlob(JSON.stringify(viewConfig(useApp.getState()), null, 2), 'pyrosync_view.json', 'application/json'); onClose() }}>
        <Icon name="download" /><span><b>View configuration (.json)</b><br /><span className="text-xs text-muted">Restores these settings via Methods, Exports</span></span></button>
      <button role="menuitem" className={item} onClick={async () => {
        const url = `${location.origin}${location.pathname}#${serializeState(useApp.getState())}`
        try { await navigator.clipboard.writeText(url) } catch { window.prompt('Copy this local view URL', url) }
        onClose()
      }}><Icon name="link" /><span><b>Copy local view URL</b><br /><span className="text-xs text-muted">Settings only — no data or credentials. Custom AOIs resolve only on this machine.</span></span></button>
    </div>
  )
}

export default function TopBar({ regions, inventory }: { regions: Region[]; inventory?: Inventory | null }) {
  const s = useApp()
  const [open, setOpen] = useState<'filters' | 'export' | null>(null)
  const [more, setMore] = useState(false) // phones: dates and sensor controls fold into one row toggle
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(null) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const dr = s.dataRange
  const nf = (s.modisMinConf !== 30 ? 1 : 0) + (s.viirsConf.join() !== 'nominal,high' ? 1 : 0) + (s.types.join() !== '0' ? 1 : 0) + (s.daynight.length !== 2 ? 1 : 0) + (s.gridMode === 'manual' ? 1 : 0)
  return (
    <header className="sticky top-0 z-[1000] flex min-h-14 flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2 lg:px-4">
      <button className="btn px-2" aria-label={s.navOpen ? 'Collapse navigation' : 'Expand navigation'} aria-expanded={s.navOpen} onClick={() => s.set({ navOpen: !s.navOpen })}><Icon name="menu" /></button>
      <AoiSelect regions={regions} />
      <button type="button" className="btn md:hidden" aria-expanded={more} aria-controls="topbar-more" onClick={() => setMore(!more)}>{s.start.slice(0, 4) === s.end.slice(0, 4) ? s.start.slice(0, 4) : `${s.start.slice(0, 4)}–${s.end.slice(0, 4)}`} · {SERIES_SHORT[s.series] ?? s.series}</button>
      <div id="topbar-more" className={cls('flex flex-wrap items-center gap-2 max-md:order-last max-md:w-full', !more && 'max-md:hidden')}>
      <div className="flex items-center gap-1 text-sm" role="group" aria-label="Analysis range (UTC days)">
        <input type="date" className="field" aria-label="Analysis range start" value={s.start} min={dr?.[0]} max={s.end}
          onChange={(e) => e.target.value && s.set({ start: e.target.value, date: s.date < e.target.value ? e.target.value : s.date })} />
        <span className="text-muted">→</span>
        <input type="date" className="field" aria-label="Analysis range end" value={s.end} min={s.start} max={dr?.[1]}
          onChange={(e) => e.target.value && s.set({ end: e.target.value, date: s.date > e.target.value ? e.target.value : s.date })} />
        {dr && <select className="field" aria-label="Range preset" value="" onChange={(e) => {
          const v = e.target.value
          if (v === 'all') s.set({ start: dr[0], end: dr[1] })
          else if (v) { const a = `${v}-01-01` < dr[0] ? dr[0] : `${v}-01-01`; const b = `${v}-12-31` > dr[1] ? dr[1] : `${v}-12-31`; s.set({ start: a, end: b, date: s.date < a || s.date > b ? a : s.date }) }
        }}>
          <option value="">Preset…</option><option value="all">All imported</option>
          {Array.from({ length: Number(dr[1].slice(0, 4)) - Number(dr[0].slice(0, 4)) + 1 }, (_, i) => Number(dr[0].slice(0, 4)) + i).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>}
      </div>
      <SeriesMetric />
      </div>
      <div ref={wrap} className="relative ml-auto flex items-center gap-2">
        <button className="btn" aria-expanded={open === 'filters'} onClick={() => setOpen(open === 'filters' ? null : 'filters')}><Icon name="filter" />Filters{nf > 0 && <span className="chip bg-accent text-white">{nf}</span>}</button>
        <button className="btn" aria-expanded={open === 'export'} onClick={() => setOpen(open === 'export' ? null : 'export')}><Icon name="download" />Export</button>
        {s.page === 'explore' && <button className="btn px-2" aria-label={s.detailsOpen ? 'Hide details panel' : 'Show details panel'} aria-expanded={s.detailsOpen} onClick={() => s.set({ detailsOpen: !s.detailsOpen })}><Icon name="panel" /></button>}
        {open === 'filters' && <FilterPanel inventory={inventory} onClose={() => setOpen(null)} />}
        {open === 'export' && <ExportMenu onClose={() => setOpen(null)} />}
      </div>
    </header>
  )
}
