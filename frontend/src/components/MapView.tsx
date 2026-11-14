import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import '@geoman-io/leaflet-geoman-free'
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css'
import { getJSON, postJSON, useApi, type Frame, type FrameCell, type Imagery, type ObsRecord, type Observations } from '../api'
import { useFilterQS } from '../hooks'
import { frameWindow, useApp } from '../state'
import { RAMP, SERIES_COLOR, SERIES_SHORT, fmtDate, fmtNum, rampColor } from '../util'

// Keyless static basemaps (Esri Canvas). CARTO's tiles now show an "API KEY REQUIRED" watermark without a key.
const ESRI_ATTR = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors'
const BASEMAPS = {
  light: { url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', attr: ESRI_ATTR, maxNativeZoom: 16 },
  dark: { url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', attr: ESRI_ATTR, maxNativeZoom: 16 },
}

export function imageryAvailable(img: Imagery | null, layerId: string, date: string): boolean {
  const l = img?.layers.find((x) => x.id === layerId)
  if (!l) return false
  return l.ranges.some(([a, b]) => a <= date && date <= b)
}
export function nearestImagery(img: Imagery | null, layerId: string, date: string): string | null {
  const l = img?.layers.find((x) => x.id === layerId)
  if (!l) return null
  let best: string | null = null
  let bd = Infinity
  for (const [a, b] of l.ranges) {
    const c = date < a ? a : date > b ? b : date
    const d = Math.abs(Date.parse(c) - Date.parse(date))
    if (d < bd) { bd = d; best = c }
  }
  return best
}

export default function MapView({ frame, onUploadRequest }: { frame: { data: Frame | null; loading: boolean; error: string | null }; onUploadRequest: () => void }) {
  const s = useApp()
  const qs = useFilterQS()
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const renderer = useRef<L.Canvas | null>(null)
  const layers = useRef<{ base?: L.TileLayer; img?: L.TileLayer; cells?: L.LayerGroup; aoi?: L.GeoJSON; pts?: L.LayerGroup; context?: L.GeoJSON }>({})
  const imagery = useApi<Imagery>('/api/imagery/layers')
  const [imgState, setImgState] = useState<{ key: string; status: 'loading' | 'ready' | 'failed' | 'unavailable' | 'off'; errors: number }>({ key: '', status: 'off', errors: 0 })
  const [bbox, setBbox] = useState<string | null>(null)
  const [aoiErr, setAoiErr] = useState<string | null>(null)
  const [pts, setPts] = useState<Observations | null>(null)
  const [ptsErr, setPtsErr] = useState<string | null>(null)

  // ---- init
  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { center: [-1.5, 113.5], zoom: 5, minZoom: 3, maxZoom: 12, preferCanvas: true, worldCopyJump: false, keyboard: true })
    renderer.current = L.canvas({ padding: 0.3 })
    m.attributionControl.setPrefix('Leaflet')
    m.pm.setGlobalOptions({ snappable: false })
    m.pm.addControls({ position: 'topleft', drawMarker: false, drawCircleMarker: false, drawPolyline: false, drawCircle: false, drawText: false,
      editMode: false, dragMode: false, cutPolygon: false, removalMode: false, rotateMode: false, drawRectangle: true, drawPolygon: true })
    m.on('pm:create', async (e: { layer: L.Layer }) => {
      const gj = (e.layer as L.Polygon).toGeoJSON()
      m.removeLayer(e.layer)
      try {
        setAoiErr(null)
        const r = await postJSON<{ id: string }>('/api/aoi', { geojson: gj, name: 'Drawn AOI' })
        useApp.getState().set({ aoi: r.id })
      } catch (err) { setAoiErr((err as Error).message) }
    })
    const upd = () => {
      const b = m.getBounds()
      setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((x) => x.toFixed(3)).join(','))
    }
    let t: number | undefined
    m.on('moveend', () => { window.clearTimeout(t); t = window.setTimeout(upd, 250) })
    upd()
    map.current = m
    // offline-safe context outline (Indonesia national land boundary, bundled)
    getJSON<GeoJSON.Feature>('/api/regions/indonesia.geojson').then((f) => {
      layers.current.context = L.geoJSON(f, { interactive: false, style: { color: '#64748b', weight: 0.8, fill: false, opacity: 0.7 } }).addTo(m)
      layers.current.context.bringToBack()
    }).catch(() => {})
    return () => { m.stop(); m.off(); m.remove(); map.current = null }
  }, [])

  // ---- basemap
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.base?.remove()
    layers.current.base = undefined
    if (s.basemap !== 'none') {
      const b = BASEMAPS[s.basemap]
      layers.current.base = L.tileLayer(b.url, { attribution: b.attr + ' · static basemap, not historical conditions', maxNativeZoom: b.maxNativeZoom, maxZoom: 19 }).addTo(m)
      layers.current.base.bringToBack()
    }
  }, [s.basemap])

  // ---- dated GIBS imagery (explicit date in every tile URL; old layer removed immediately)
  const imgDate = s.imageryOverride ?? s.date
  const imgLayer = imagery.data?.layers.find((l) => l.id === s.imagery)
  const imgKey = `${s.imagery}|${imgDate}`
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.img?.remove()
    layers.current.img = undefined
    if (s.imagery === 'off' || !imagery.data) { setImgState({ key: imgKey, status: 'off', errors: 0 }); useApp.getState().set({ imageryBusy: false }); return }
    if (!imgLayer || !imageryAvailable(imagery.data, s.imagery, imgDate)) { setImgState({ key: imgKey, status: 'unavailable', errors: 0 }); useApp.getState().set({ imageryBusy: false }); return }
    const url = imgLayer.url_template.replace('{date}', imgDate)
    const tl = L.tileLayer(url, { maxNativeZoom: imgLayer.max_native_zoom, maxZoom: 12, attribution: 'Imagery: NASA GIBS (ESDIS)', crossOrigin: true, className: 'gibs-layer' })
    let errors = 0
    let loaded = 0
    setImgState({ key: imgKey, status: 'loading', errors: 0 })
    useApp.getState().set({ imageryBusy: true })
    tl.on('tileerror', () => { errors++ })
    tl.on('tileload', () => { loaded++ })
    tl.on('load', () => {
      if (layers.current.img !== tl) return // stale layer: ignore
      setImgState({ key: imgKey, status: loaded === 0 && errors > 0 ? 'failed' : 'ready', errors })
      useApp.getState().set({ imageryBusy: false })
    })
    tl.addTo(m)
    tl.bringToBack()
    layers.current.base?.bringToBack()
    layers.current.img = tl
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imgKey, imagery.data])

  // ---- AOI outline
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.aoi?.remove()
    layers.current.aoi = undefined
    if (s.aoi === 'none') return
    const url = s.aoi.startsWith('region:') ? `/api/regions/${s.aoi.slice(7)}.geojson` : `/api/aoi/${encodeURIComponent(s.aoi)}`
    let alive = true
    getJSON<GeoJSON.Feature>(url).then((f) => {
      if (!alive || !map.current) return
      layers.current.aoi = L.geoJSON(f, { interactive: false, style: { color: '#0f1d3a', weight: 2, dashArray: '5 4', fill: false } }).addTo(map.current)
      setAoiErr(null)
    }).catch((e) => setAoiErr(`AOI unavailable: ${(e as Error).message}`))
    return () => { alive = false }
  }, [s.aoi])

  // ---- zoom to AOI on change
  const lastAoi = useRef<string>('')
  useEffect(() => {
    if (s.aoi === lastAoi.current) return
    lastAoi.current = s.aoi
    if (s.aoi === 'none') return
    const url = s.aoi.startsWith('region:') ? `/api/regions/${s.aoi.slice(7)}.geojson` : `/api/aoi/${encodeURIComponent(s.aoi)}`
    getJSON<GeoJSON.Feature>(url).then((f) => { const b = L.geoJSON(f).getBounds(); if (b.isValid()) map.current?.fitBounds(b, { padding: [20, 20], maxZoom: 9, animate: false }) }).catch(() => {})
  }, [s.aoi])

  // ---- cells layer (only from the response for the CURRENT frame)
  const current = frame.data && frame.data.frame.date === s.date && frame.data.frame.mode_days === s.frameMode ? frame.data : null
  // Colour by the PRIMARY sensor's own count (or, for the union, by how many selected sensors detected the cell).
  // Raw MODIS and VIIRS counts are never added together.
  const isUnion = s.series === 'UNION'
  const cellValue = useCallback((c: FrameCell) => (isUnion ? c.sensors_detecting : c.by_series[s.series] ?? 0), [isUnion, s.series])
  const maxN = useMemo(() => Math.max(1, ...(current?.cells.map(cellValue) ?? [1])), [current, cellValue])
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.cells?.remove()
    layers.current.cells = undefined
    if (!current || s.mapLayer !== 'cells') return
    const g = current.grid_size
    const grp = L.layerGroup()
    for (const c of current.cells) {
      const w = c.ci * g - 180, so = c.cj * g - 90
      const sel = s.selectedCell && s.selectedCell.ci === c.ci && s.selectedCell.cj === c.cj
      const v = cellValue(c)
      const r = v > 0
        ? L.rectangle([[so, w], [so + g, w + g]], { renderer: renderer.current!, weight: sel ? 2.5 : 0.4, color: sel ? '#0f1d3a' : '#7c2d12', fillColor: rampColor(v, maxN), fillOpacity: 0.85 })
        : L.rectangle([[so, w], [so + g, w + g]], { renderer: renderer.current!, weight: sel ? 2.5 : 0.8, color: sel ? '#0f1d3a' : '#64748b', fillColor: '#94a3b8', fillOpacity: 0.12 })
      r.on('click', () => useApp.getState().set({ selectedCell: { ci: c.ci, cj: c.cj }, detailsOpen: true }))
      grp.addLayer(r)
    }
    grp.addTo(m)
    layers.current.cells = grp
  }, [current, s.mapLayer, maxN, s.selectedCell, cellValue])

  // ---- points layer (bounded, viewport-limited)
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  useEffect(() => {
    if (s.mapLayer !== 'points' || !bbox) { setPts(null); return }
    const ac = new AbortController()
    useApp.getState().set({ mapBusy: true })
    getJSON<Observations>(`/api/observations?${qs}&window_start=${w0}&window_end=${w1}&bbox=${bbox}&limit=5000`, ac.signal)
      .then((d) => { setPts(d); setPtsErr(null) }, (e) => { if ((e as Error).name !== 'AbortError') setPtsErr((e as Error).message) })
      .finally(() => useApp.getState().set({ mapBusy: false }))
    return () => ac.abort()
  }, [s.mapLayer, bbox, qs, w0, w1])
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.pts?.remove()
    layers.current.pts = undefined
    if (!pts || s.mapLayer !== 'points' || pts.window.end !== w1 || pts.window.start !== w0) return
    const grp = L.layerGroup()
    for (const r of pts.records as ObsRecord[]) {
      const cm = L.circleMarker([r.lat, r.lon], { renderer: renderer.current!, radius: r.instrument === 'MODIS' ? 5 : 3.2, weight: 1, color: '#fff', fillColor: SERIES_COLOR[r.series], fillOpacity: 0.95 })
      cm.bindTooltip(`<b>${SERIES_SHORT[r.series]}</b> · ${r.platform}<br/>${r.acq_date} ${r.acq_time_utc}<br/>FRP ${r.frp ?? '—'} MW · conf ${r.conf_raw} · ${r.daynight === 'D' ? 'day' : 'night'}<br/>${r.type_label}`)
      grp.addLayer(cm)
    }
    grp.addTo(m)
    layers.current.pts = grp
  }, [pts, s.mapLayer, w0, w1])

  useEffect(() => { useApp.getState().set({ mapBusy: frame.loading }) }, [frame.loading])

  const fireLabel = s.frameMode === 1 ? `${s.date} 00:00–24:00 UTC (daily frame)` : `${w0} 00:00 → ${w1} 24:00 UTC (trailing ${s.frameMode}-day)`
  const imgLabel = s.imagery === 'off'
    ? (s.basemap === 'none' ? 'No imagery or basemap (offline-safe outline only)' : `Static ${s.basemap} basemap — not historical conditions`)
    : `${imgDate}${s.imageryOverride ? ' (SUBSTITUTED — nearest available)' : ''}, ${imgLayer?.label ?? s.imagery}`
  const showLoading = frame.loading || !current || (s.mapLayer === 'points' && !pts)

  return (
    <div className="relative h-full min-h-[320px] overflow-hidden rounded-xl border border-line">
      <div ref={el} className="absolute inset-0" aria-label="Fire map. Use the timeline below to change the date." role="region" tabIndex={0} />
      {/* window labels */}
      <div className="pointer-events-none absolute left-14 right-2 top-2 z-[500] flex flex-col items-start gap-1 text-[11px] sm:right-auto" data-testid="map-labels">
        <div className="pointer-events-auto rounded-md bg-panel/95 px-2 py-1 shadow" data-testid="fire-window-label"><b>Fire observations:</b> {fireLabel}</div>
        <div className="pointer-events-auto rounded-md bg-panel/95 px-2 py-1 shadow" data-testid="imagery-label"><b>Satellite imagery:</b> {imgLabel}</div>
        {s.imagery !== 'off' && s.frameMode > 1 && <div className="rounded-md bg-amber-50 px-2 py-1 text-amber-900 shadow dark:bg-amber-950 dark:text-amber-100">Imagery shows one day; fire layer covers {s.frameMode} days — different temporal windows.</div>}
      </div>
      {/* map controls */}
      <div className="absolute right-2 top-2 z-[500] flex flex-col items-end gap-1 max-sm:top-[124px] max-sm:scale-90 max-sm:origin-top-right">
        <div className="seg shadow" role="group" aria-label="Map layer">
          <button aria-pressed={s.mapLayer === 'cells'} onClick={() => s.set({ mapLayer: 'cells' })}>{s.grid}° cells</button>
          <button aria-pressed={s.mapLayer === 'points'} onClick={() => s.set({ mapLayer: 'points' })}>Detections</button>
        </div>
        <select className="field max-w-[200px] shadow sm:max-w-[300px]" aria-label="Imagery or basemap" value={s.imagery === 'off' ? `base:${s.basemap}` : s.imagery}
          onChange={(e) => { const v = e.target.value; if (v.startsWith('base:')) s.set({ imagery: 'off', basemap: v.slice(5) as 'light' | 'dark' | 'none', imageryOverride: null }); else s.set({ imagery: v, imageryOverride: null }) }}>
          <optgroup label="Dated NASA GIBS imagery">
            {(imagery.data?.layers ?? []).map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </optgroup>
          <optgroup label="Static basemaps">
            <option value="base:light">Light basemap (static)</option><option value="base:dark">Dark basemap (static)</option><option value="base:none">None (offline)</option>
          </optgroup>
        </select>
        <div className="flex gap-1">
          <button className="btn shadow" onClick={onUploadRequest}>Upload GeoJSON</button>
          {s.aoi !== 'none' && <button className="btn shadow" onClick={() => s.set({ aoi: 'none' })}>Clear AOI</button>}
        </div>
      </div>
      {/* imagery status */}
      {s.imagery !== 'off' && imgState.key === imgKey && imgState.status === 'unavailable' && (
        <div role="status" data-testid="imagery-unavailable" className="absolute left-1/2 top-24 z-[600] -translate-x-1/2 rounded-lg border border-line bg-panel px-3 py-2 text-center text-xs shadow-lg">
          <b>Imagery unavailable for this date</b> ({imgDate}).<br />
          {(() => { const n = nearestImagery(imagery.data, s.imagery, s.date); return n && n !== imgDate ? <button className="mt-1 text-accent underline" onClick={() => s.set({ imageryOverride: n })}>Show nearest available date ({n}) — will be labeled as substituted</button> : null })()}
        </div>
      )}
      {s.imagery !== 'off' && imgState.key === imgKey && imgState.status === 'failed' && (
        <div role="status" className="absolute left-1/2 top-24 z-[600] -translate-x-1/2 rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg"><b>Imagery tiles failed to load</b> for {imgDate} (offline or service error). Fire analysis still works.</div>
      )}
      {(showLoading || (s.imagery !== 'off' && imgState.key === imgKey && imgState.status === 'loading')) && (
        <div role="status" data-testid="map-loading" className="absolute inset-x-0 bottom-3 z-[600] mx-auto flex w-fit items-center gap-2 rounded-full bg-panel px-3 py-1.5 text-xs shadow-lg">
          <span className="spinner" aria-hidden />Loading {fmtDate(s.date)}{showLoading ? ' fire observations' : ''}{s.imagery !== 'off' && imgState.status === 'loading' ? ' + imagery' : ''}…
        </div>
      )}
      {(frame.error || aoiErr || ptsErr) && <div role="alert" className="absolute bottom-14 left-2 z-[600] max-w-sm rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">{frame.error || aoiErr || ptsErr}</div>}
      {/* legend */}
      <div className="absolute bottom-2 right-2 z-[500] max-sm:bottom-12 rounded-lg bg-panel/95 px-2 py-1.5 text-[10px] shadow" aria-label="Map legend">
        {s.mapLayer === 'cells' ? (
          <>
            <div className="mb-1 font-semibold">{isUnion ? `Selected sensors detecting each ${s.grid}° cell` : `${SERIES_SHORT[s.series] ?? s.series} detections per ${s.grid}° cell in window`}</div>
            <div className="flex items-center gap-1"><span>1</span>{RAMP.map((c) => <span key={c} className="inline-block h-2.5 w-4" style={{ background: c }} />)}<span>{fmtNum(maxN)}</span></div>
            {!isUnion && <div className="mt-0.5 flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-slate-500 bg-slate-400/20" />Detected only by other selected sensor(s)</div>}
            <div className="mt-0.5 text-muted">Cells are grid summaries, not burned-area polygons.</div>
            {current?.truncated && <div className="text-amber-700">Showing {current.cells.length} of {current.cells_total} cells (truncated)</div>}
          </>
        ) : (
          <>
            <div className="mb-1 font-semibold">Detection pixel centres</div>
            {['MODIS', 'VIIRS_N20', 'VIIRS_N21', 'VIIRS_SNPP'].map((k) => <div key={k} className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SERIES_COLOR[k] }} />{SERIES_SHORT[k]}</div>)}
            {pts && <div className="text-muted">{fmtNum(pts.returned)} of {fmtNum(pts.total)} in view{pts.truncated ? ' (truncated; zoom in)' : ''}</div>}
            <div className="text-muted">~1 km MODIS / ~375 m VIIRS are nominal pixel sizes, not fire sizes.</div>
          </>
        )}
      </div>
    </div>
  )
}
