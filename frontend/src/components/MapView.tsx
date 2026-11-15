import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import '@geoman-io/leaflet-geoman-free'
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css'
import { getJSON, postJSON, useApi, type Frame, type FrameCell, type Imagery, type ObsRecord, type Observations } from '../api'
import { useDisplayQS, useFusionFrame } from '../hooks'
import { GRID_CHOICES, circleId, circleKm, frameWindow, gridForZoom, useApp } from '../state'
import { FUSION_STATUS_TEXT, PLATFORM_SHORT, fusionStatusClass } from '../fusion'
import { PLATFORM_LABEL, RAMP, SERIES_COLOR, SERIES_SHORT, cls, fmtDate, fmtNum, rampColor } from '../util'
import { Icon } from './ui'

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


// ---- 1.5 helpers ------------------------------------------------------------------------------------------
/** Geodesic radius (km) of a circle whose diameter is `frac` of the shortest visible map side, centred at `ll`.
 * Uses the map's own projection at the current zoom and Leaflet's great-circle distance (no fixed km-per-degree). */
export function radiusKmFor(m: L.Map, ll: L.LatLng, frac: number): number {
  const size = m.getSize()
  const rpx = (frac * Math.min(size.x, size.y)) / 2
  const p = m.latLngToContainerPoint(ll)
  const q = m.containerPointToLatLng(L.point(p.x + rpx, p.y))
  return ll.distanceTo(L.latLng(ll.lat, q.lng)) / 1000
}
function parseView(v: string): { lat: number; lon: number; zoom: number } | null {
  const a = v.split(',').map(Number)
  return a.length === 3 && a.every(Number.isFinite) && Math.abs(a[0]) <= 85 && Math.abs(a[1]) <= 180 && a[2] >= 3 && a[2] <= 12 ? { lat: a[0], lon: a[1], zoom: a[2] } : null
}
function parseLatLon(v: string): L.LatLng | null {
  const a = v.split(',').map(Number)
  return a.length === 2 && a.every(Number.isFinite) ? L.latLng(a[0], a[1]) : null
}
const na = '<span class="text-muted">unavailable</span>'
function esc(x: unknown): string { return String(x).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!)) }
function val(x: unknown, unit = '', digits?: number): string {
  if (x === null || x === undefined || x === '') return na
  const v = typeof x === 'number' && digits !== undefined ? x.toFixed(digits) : String(x)
  return esc(v) + (unit ? ` ${unit}` : '')
}
/** FIRMS-style attribute table for one original detection. Fields missing from the database are shown as unavailable. */
export function hotspotHtml(r: ObsRecord): string {
  const modis = r.instrument === 'MODIS'
  const rows: [string, string][] = [
    ['Latitude', val(r.lat, '°', 5)], ['Longitude', val(r.lon, '°', 5)],
    ['Acquired', `${esc(r.acq_date)} ${esc(r.acq_time_utc)}`],
    ['Satellite', val(PLATFORM_LABEL[r.platform] ?? r.platform)], ['Instrument', val(r.instrument)],
    ['Confidence', r.conf_raw ? `${esc(r.conf_raw)}${r.conf_cat && r.conf_cat !== r.conf_raw ? ` (${esc(r.conf_cat)})` : ''}` : na],
    ['FRP', val(r.frp, 'MW')],
    [modis ? 'Brightness T21' : 'Brightness I4', val(modis ? r.modis_brightness : r.viirs_bright_ti4, 'K')],
    [modis ? 'Brightness T31' : 'Brightness I5', val(modis ? r.modis_bright_t31 : r.viirs_bright_ti5, 'K')],
    ['Scan × track', r.scan !== null && r.track !== null ? `${esc(r.scan)} × ${esc(r.track)} km` : na],
    ['Day / night', r.daynight === 'D' ? 'Day' : r.daynight === 'N' ? 'Night' : na],
    ['Type', val(r.type_label)],
    ['Source product', r.source_product ? `${esc(r.source_product)}${r.stream ? ` · ${esc(r.stream)}` : ''}${r.version ? ` · v${esc(r.version)}` : ''}` : na],
  ]
  return `<div class="hotspot-pop" data-testid="hotspot-popup"><div class="mb-1 font-semibold">Observed active-fire detection</div>`
    + `<table class="data"><tbody>${rows.map(([k, v]) => `<tr><th class="pr-2 text-left">${k}</th><td>${v}</td></tr>`).join('')}</tbody></table>`
    + `<p class="mt-1 text-[10px] text-muted">A thermal anomaly detected by the satellite's fire algorithm (NASA FIRMS), not a confirmed fire incident or burned area.</p>`
    + `<button type="button" class="btn btn-primary mt-1 w-full justify-center" data-act="analyze">Analyze around this detection</button></div>`
}

export default function MapView({ frame, onUploadRequest }: { frame: { data: Frame | null; loading: boolean; error: string | null }; onUploadRequest: () => void }) {
  const s = useApp()
  const { qs, grid: dGrid } = useDisplayQS()
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const renderer = useRef<L.Canvas | null>(null)
  const layers = useRef<{ base?: L.TileLayer; img?: L.TileLayer; cells?: L.LayerGroup; aoi?: L.Layer; pts?: L.LayerGroup; context?: L.GeoJSON; harm?: L.LayerGroup }>({})
  const imagery = useApi<Imagery>('/api/imagery/layers')
  const fusion = useFusionFrame(s.mapLayer === 'harmonized')
  const [imgState, setImgState] = useState<{ key: string; status: 'loading' | 'ready' | 'failed' | 'unavailable' | 'off'; errors: number }>({ key: '', status: 'off', errors: 0 })
  const [bbox, setBbox] = useState<string | null>(null)
  const [aoiErr, setAoiErr] = useState<string | null>(null)
  const [pts, setPts] = useState<Observations | null>(null)
  const [ptsErr, setPtsErr] = useState<string | null>(null)
  const [tools, setTools] = useState(false)
  const [legend, setLegend] = useState(() => typeof window === 'undefined' || window.innerWidth >= 640) // phones: folded by default
  const initialView = useRef(useApp.getState().view) // captured before the map writes its own view

  // Click-to-Analyze: centre a zoom-adaptive circle on a location (map click, a cell, or a hotspot's "Analyze around")
  const analyzeAt = useCallback((ll: L.LatLng) => {
    const m = map.current
    if (!m) return
    const st = useApp.getState()
    const id = circleId(ll.lat, ll.lng, radiusKmFor(m, ll, st.circleFrac))
    st.set({ analyzeMode: 'click', clickAt: `${ll.lat.toFixed(5)},${ll.lng.toFixed(5)}`, aoi: id, selectedCell: null,
      lastRegionAoi: st.aoi.startsWith('circle:') ? st.lastRegionAoi : st.aoi })
  }, [])
  const analyzeRef = useRef(analyzeAt)
  analyzeRef.current = analyzeAt

  // ---- init
  useEffect(() => {
    if (!el.current || map.current) return
    const v = parseView(initialView.current)
    const m = L.map(el.current, { center: v ? [v.lat, v.lon] : [-1.5, 113.5], zoom: v ? v.zoom : 5, minZoom: 3, maxZoom: 12, preferCanvas: true, worldCopyJump: false, keyboard: true })
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
        useApp.getState().set({ aoi: r.id, analyzeMode: 'region', clickAt: '', lastRegionAoi: r.id })
      } catch (err) { setAoiErr((err as Error).message) }
    })
    // background click: only in Analyze Location mode, and never while drawing a polygon
    m.on('click', (e: L.LeafletMouseEvent) => {
      if (useApp.getState().analyzeMode !== 'click' || m.pm.globalDrawModeEnabled()) return
      analyzeRef.current(e.latlng)
    })
    let lastZoom = -1
    let dead = false
    const upd = () => {
      if (dead) return
      const b = m.getBounds()
      const c = m.getCenter()
      const z = m.getZoom()
      const st = useApp.getState()
      const patch: Partial<typeof st> = {
        mapBbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((x) => x.toFixed(3)).join(','),
        mapZoom: z, view: `${c.lat.toFixed(4)},${c.lng.toFixed(4)},${z}`,
      }
      // zoom-adaptive analysis circle: same share of the screen, new geographic radius (zoom changes only, not pans)
      if (z !== lastZoom && st.analyzeMode === 'click') {
        const ll = parseLatLon(st.clickAt)
        if (ll) {
          const id = circleId(ll.lat, ll.lng, radiusKmFor(m, ll, st.circleFrac))
          if (id !== st.aoi) patch.aoi = id
        }
      }
      lastZoom = z
      setBbox(patch.mapBbox!)
      st.set(patch)
    }
    let t: number | undefined
    m.on('moveend', () => { window.clearTimeout(t); t = window.setTimeout(upd, 300) })
    // a circle restored from a shared link keeps its radius; only a later zoom recomputes it
    if (useApp.getState().aoi.startsWith('circle:') && parseLatLon(useApp.getState().clickAt)) lastZoom = m.getZoom()
    upd()
    map.current = m
    getJSON<GeoJSON.Feature>('/api/regions/indonesia.geojson').then((f) => {
      layers.current.context = L.geoJSON(f, { interactive: false, style: { color: '#71717a', weight: 0.8, fill: false, opacity: 0.7 } }).addTo(m)
      layers.current.context.bringToBack()
    }).catch(() => {})
    // keep the map filling its box when the sidebar or details panel opens or closes (never clipped)
    let raf = 0
    const ro = new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { if (!dead) m.invalidateSize({ pan: false }) }) })
    ro.observe(el.current!)
    return () => { dead = true; ro.disconnect(); cancelAnimationFrame(raf); m.off(); window.clearTimeout(t); m.stop(); m.remove(); map.current = null }
  }, [])

  // close the map-tools popover on any click outside it
  useEffect(() => {
    if (!tools) return
    const h = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest?.('[data-testid="map-controls"]')) setTools(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [tools])

  // crosshair cursor in Analyze Location mode
  useEffect(() => { el.current?.classList.toggle('analyze-mode', s.analyzeMode === 'click') }, [s.analyzeMode])

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

  // ---- AOI outline: fixed region/polygon from the server; a Click-to-Analyze circle is drawn locally from its id
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.aoi?.remove()
    layers.current.aoi = undefined
    if (s.aoi === 'none') return
    if (s.aoi.startsWith('circle:')) {
      const [lat, lon, km] = s.aoi.slice(7).split(',').map(Number)
      const g = L.featureGroup([
        L.circle([lat, lon], { radius: km * 1000, interactive: false, color: '#09090b', weight: 2, dashArray: '6 4', fill: true, fillOpacity: 0.04 }),
        L.circleMarker([lat, lon], { radius: 5, interactive: false, color: '#fff', weight: 2, fillColor: '#09090b', fillOpacity: 1 }),
      ]).addTo(m)
      layers.current.aoi = g
      setAoiErr(null)
      return
    }
    const url = s.aoi.startsWith('region:') ? `/api/regions/${s.aoi.slice(7)}.geojson` : `/api/aoi/${encodeURIComponent(s.aoi)}`
    let alive = true
    getJSON<GeoJSON.Feature>(url).then((f) => {
      if (!alive || !map.current) return
      layers.current.aoi = L.geoJSON(f, { interactive: false, style: { color: '#09090b', weight: 2, dashArray: '5 4', fill: false } }).addTo(map.current)
      setAoiErr(null)
    }).catch((e) => setAoiErr(`AOI unavailable: ${(e as Error).message}`))
    return () => { alive = false }
  }, [s.aoi])

  // ---- zoom to a Region AOI when it changes (never for circles: their size follows the zoom, not the other way round)
  const lastAoi = useRef<string>('')
  useEffect(() => {
    if (s.aoi === lastAoi.current) return
    const first = lastAoi.current === ''
    lastAoi.current = s.aoi
    if (s.aoi === 'none' || s.aoi.startsWith('circle:')) return
    if (first && parseView(initialView.current)) return // a restored shared view wins over fitting the AOI
    const url = s.aoi.startsWith('region:') ? `/api/regions/${s.aoi.slice(7)}.geojson` : `/api/aoi/${encodeURIComponent(s.aoi)}`
    getJSON<GeoJSON.Feature>(url).then((f) => { const b = L.geoJSON(f).getBounds(); if (b.isValid()) map.current?.fitBounds(b, { padding: [20, 20], maxZoom: 9, animate: false }) }).catch(() => {})
  }, [s.aoi])

  // ---- detection grid layer (display grid; only the response for the CURRENT frame and grid)
  const current = frame.data && frame.data.frame.date === s.date && frame.data.frame.mode_days === s.frameMode && Math.abs(frame.data.grid_size - dGrid) < 1e-9 ? frame.data : null
  // Colour by the PRIMARY sensor's own count (or, for the union, by how many selected sensors detected the cell).
  // Raw MODIS and VIIRS counts are never added together.
  const isUnion = s.series === 'UNION'
  const cellSeries = s.series === 'FUSED' ? 'UNION' : s.series
  const cellValue = useCallback((c: FrameCell) => (cellSeries === 'UNION' ? c.sensors_detecting : c.by_series[cellSeries] ?? 0), [cellSeries])
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
        ? L.rectangle([[so, w], [so + g, w + g]], { renderer: renderer.current!, bubblingMouseEvents: false, weight: sel ? 2.5 : 0.4, color: sel ? '#09090b' : '#7c2d12', fillColor: rampColor(v, maxN), fillOpacity: 0.85 })
        : L.rectangle([[so, w], [so + g, w + g]], { renderer: renderer.current!, bubblingMouseEvents: false, weight: sel ? 2.5 : 0.8, color: sel ? '#09090b' : '#71717a', fillColor: '#a1a1aa', fillOpacity: 0.12 })
      r.on('click', (e: L.LeafletMouseEvent) => {
        if (useApp.getState().analyzeMode === 'click') analyzeRef.current(e.latlng)
        else useApp.getState().set({ selectedCell: { ci: c.ci, cj: c.cj }, detailsOpen: true })
      })
      grp.addLayer(r)
    }
    grp.addTo(m)
    layers.current.cells = grp
  }, [current, s.mapLayer, maxN, s.selectedCell, cellValue])

  // a selected cell belongs to one grid: forget it when the display grid changes
  const prevGrid = useRef(dGrid)
  useEffect(() => { if (prevGrid.current !== dGrid) { prevGrid.current = dGrid; if (useApp.getState().selectedCell) useApp.getState().set({ selectedCell: null }) } }, [dGrid])

  // ---- harmonized activity heatmap (multi-sensor fusion on the display grid)
  const fz = fusion.data && fusion.data.frame.date === s.date && fusion.data.frame.mode_days === s.frameMode && Math.abs(fusion.data.grid_size - dGrid) < 1e-9 ? fusion.data : null
  const maxH = useMemo(() => Math.max(1e-9, ...(fz?.cells.map((c) => c.value) ?? [1])), [fz])
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.harm?.remove()
    layers.current.harm = undefined
    if (!fz || s.mapLayer !== 'harmonized') return
    const g = fz.grid_size
    const grp = L.layerGroup()
    for (const c of fz.cells) {
      const w = c.ci * g - 180, so = c.cj * g - 90
      const r = L.rectangle([[so, w], [so + g, w + g]], { renderer: renderer.current!, bubblingMouseEvents: false, weight: 0.3, color: '#7c2d12', fillColor: rampColor(c.value, maxH), fillOpacity: 0.85 })
      r.on('click', (e: L.LeafletMouseEvent) => {
        if (useApp.getState().analyzeMode === 'click') { analyzeRef.current(e.latlng); return }
        const obs = Object.entries(c.observed).map(([p, n]) => `${PLATFORM_SHORT[p] ?? p} ${n}`).join(', ')
        L.popup({ maxWidth: 280 }).setLatLng(e.latlng).setContent(
          `<div data-testid="harm-cell-popup"><b>${g}° cell</b> ${w.toFixed(2)}–${(w + g).toFixed(2)}° E, ${so.toFixed(2)}–${(so + g).toFixed(2)}° N<br/>`
          + `Harmonized activity: <b>${c.value.toFixed(2)}</b> MODIS-Aqua-equivalent detections (${fz.frame.start} → ${fz.frame.end})<br/>`
          + `Original detections: ${obs || 'none'}<br/><span class="text-[10px] text-muted">Experimental index; single cells are not validated. Not burned area.</span></div>`).openOn(m)
      })
      grp.addLayer(r)
    }
    grp.addTo(m)
    layers.current.harm = grp
  }, [fz, s.mapLayer, maxH])

  // ---- observed detections (bounded, viewport-limited)
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  const filterQs = useMemo(() => { const p = new URLSearchParams(qs); p.delete('bbox'); return p.toString() }, [qs])
  useEffect(() => {
    if (s.mapLayer !== 'points' || !bbox) { setPts(null); return }
    const ac = new AbortController()
    useApp.getState().set({ mapBusy: true })
    getJSON<Observations>(`/api/observations?${filterQs}&window_start=${w0}&window_end=${w1}&bbox=${bbox}&limit=5000`, ac.signal)
      .then((d) => { setPts(d); setPtsErr(null) }, (e) => { if ((e as Error).name !== 'AbortError') setPtsErr((e as Error).message) })
      .finally(() => useApp.getState().set({ mapBusy: false }))
    return () => ac.abort()
  }, [s.mapLayer, bbox, filterQs, w0, w1])
  useEffect(() => {
    const m = map.current
    if (!m) return
    layers.current.pts?.remove()
    layers.current.pts = undefined
    if (!pts || s.mapLayer !== 'points' || pts.window.end !== w1 || pts.window.start !== w0) return
    const grp = L.layerGroup()
    for (const r of pts.records as ObsRecord[]) {
      const cm = L.circleMarker([r.lat, r.lon], { renderer: renderer.current!, bubblingMouseEvents: false, radius: r.instrument === 'MODIS' ? 5 : 3.2, weight: 1, color: '#fff', fillColor: SERIES_COLOR[r.series], fillOpacity: 0.95 })
      cm.bindTooltip(`<b>${SERIES_SHORT[r.series]}</b> · ${r.platform}<br/>${r.acq_date} ${r.acq_time_utc}<br/>Click for details`)
      cm.on('click', (e: L.LeafletMouseEvent) => {
        const div = document.createElement('div')
        div.innerHTML = hotspotHtml(r)
        const pop = L.popup({ maxWidth: 320, minWidth: 240 }).setLatLng(e.latlng).setContent(div)
        div.querySelector('[data-act="analyze"]')?.addEventListener('click', () => { m.closePopup(pop); analyzeRef.current(L.latLng(r.lat, r.lon)) })
        pop.openOn(m)
      })
      grp.addLayer(cm)
    }
    grp.addTo(m)
    layers.current.pts = grp
  }, [pts, s.mapLayer, w0, w1])

  useEffect(() => { useApp.getState().set({ mapBusy: frame.loading || fusion.loading }) }, [frame.loading, fusion.loading])

  const fireLabel = s.frameMode === 1 ? `${s.date} 00:00–24:00 UTC (daily frame)` : `${w0} 00:00 → ${w1} 24:00 UTC (trailing ${s.frameMode}-day)`
  const imgLabel = s.imagery === 'off'
    ? (s.basemap === 'none' ? 'No imagery or basemap (offline-safe outline only)' : `Static ${s.basemap} basemap — not historical conditions`)
    : `${imgDate}${s.imageryOverride ? ' (SUBSTITUTED — nearest available)' : ''}, ${imgLayer?.label ?? s.imagery}`
  const showLoading = s.mapLayer === 'cells' ? (frame.loading || !current) : s.mapLayer === 'points' ? !pts : (fusion.loading || !fz)
  const km = circleKm(s.aoi)
  const regionBack = s.lastRegionAoi && !s.lastRegionAoi.startsWith('circle:') ? s.lastRegionAoi : 'none'
  const layerErr = s.mapLayer === 'harmonized' ? fusion.error : s.mapLayer === 'cells' ? frame.error : ptsErr

  return (
    <div className="relative h-full min-h-[320px] overflow-hidden">
      <div ref={el} className="absolute inset-0" aria-label="Fire map. Use the timeline below to change the date." role="region" tabIndex={0} data-testid="explore-map" />
      {/* window labels (one compact card) */}
      <div className="pointer-events-none absolute left-14 right-14 top-2 z-[500] flex flex-col items-start gap-1 text-[11px] sm:right-auto" data-testid="map-labels">
        <div className="pointer-events-auto max-w-full space-y-0.5 rounded-md bg-panel/95 px-2 py-1 leading-snug shadow">
          <div className="truncate" data-testid="fire-window-label"><b>Fire observations:</b> {fireLabel}</div>
          <div className="truncate text-muted" data-testid="imagery-label"><b className="text-ink">Imagery:</b> {imgLabel}</div>
          {s.mapLayer !== 'points' && <div className="text-muted" data-testid="grid-label"><b className="text-ink">Grid:</b> {dGrid}° {s.gridMode === 'auto' ? `(auto, zoom ${s.mapZoom})` : '(manual)'}</div>}
        </div>
        {s.analyzeMode === 'click' && <div className="pointer-events-auto rounded-md bg-panel/95 px-2 py-1 shadow" data-testid="analyze-label">
          {km !== null ? <><b>Analysis circle:</b> radius <b className="num" data-testid="circle-km">{km}</b> km · follows the zoom (zoom out = larger area) · statistics use this circle</>
            : <><b>Analyze Location:</b> click the map or a detection to analyse the area around it</>}</div>}
        {s.imagery !== 'off' && s.frameMode > 1 && <div className="rounded-md bg-amber-50 px-2 py-1 text-amber-900 shadow dark:bg-amber-950 dark:text-amber-100">Imagery shows one day; fire layer covers {s.frameMode} days — different temporal windows.</div>}
      </div>
      {/* map tools: one button, one popover (keeps the canvas clear) */}
      <div className="absolute right-2 top-2 z-[700] flex flex-col items-end gap-1" data-testid="map-controls">
        <div className="flex items-center gap-1">
          {s.analyzeMode === 'click' && s.aoi.startsWith('circle:') && <button className="btn shadow" data-testid="back-to-region"
            onClick={() => s.set({ analyzeMode: 'region', clickAt: '', aoi: regionBack })}>Back to region</button>}
          <button type="button" className="btn shadow" aria-expanded={tools} aria-controls="map-tools" data-testid="map-tools-toggle" onClick={() => setTools(!tools)}>
            <Icon name="sliders" /><span className="max-sm:sr-only">Map tools</span></button>
        </div>
        {tools && <div id="map-tools" role="dialog" aria-label="Map tools" onKeyDown={(e) => e.key === 'Escape' && setTools(false)}
          className="w-64 space-y-3 rounded-xl border border-line bg-panel p-3 text-xs shadow-xl" data-testid="map-tools">
          <div>
            <div className="label mb-1">Analysis area</div>
            <div className="seg w-full" role="group" aria-label="Analysis area mode">
              <button className="flex-1" aria-pressed={s.analyzeMode === 'region'} title="Fixed region, drawn polygon or uploaded GeoJSON: zooming never changes its statistics"
                onClick={() => s.set({ analyzeMode: 'region', clickAt: '', ...(s.aoi.startsWith('circle:') ? { aoi: regionBack } : {}) })}>Region AOI</button>
              <button className="flex-1" aria-pressed={s.analyzeMode === 'click'} data-testid="analyze-toggle" title="Click anywhere: analyse a circle around it whose radius follows the zoom"
                onClick={() => s.set({ analyzeMode: 'click', lastRegionAoi: s.aoi.startsWith('circle:') ? s.lastRegionAoi : s.aoi })}>Analyze Location</button>
            </div>
          </div>
          <label className="block"><span className="label mb-1 block">Grid</span>
            <select className="field w-full" aria-label="Grid resolution" data-testid="grid-mode" value={s.gridMode === 'auto' ? 'auto' : String(s.grid)}
              onChange={(e) => { const v = e.target.value; if (v === 'auto') s.set({ gridMode: 'auto' }); else s.set({ gridMode: 'manual', grid: Number(v) }) }}>
              <option value="auto">Auto (recommended)</option>
              {GRID_CHOICES.map((g) => <option key={g} value={g}>{g}° (manual)</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-1.5">
            <button className="btn justify-center" onClick={() => { setTools(false); onUploadRequest() }}><Icon name="upload" />Upload GeoJSON</button>
            <button className="btn justify-center" disabled={s.aoi === 'none'} onClick={() => s.set({ aoi: 'none', clickAt: '', analyzeMode: 'region' })}>Clear AOI</button>
            <button className="btn col-span-2 justify-center" onClick={() => s.set({ page: 'harmonization' })} title="Calibration, errors, regional validity and statistics">Diagnostics (calibration audit)</button>
          </div>
          <p className="text-[11px] text-muted">Draw a rectangle or polygon with the tools on the left of the map.</p>
        </div>}
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
          <span className="spinner" aria-hidden />Loading {fmtDate(s.date)}{showLoading ? (s.mapLayer === 'harmonized' ? ' harmonized activity' : ' fire observations') : ''}{s.imagery !== 'off' && imgState.status === 'loading' ? ' + imagery' : ''}…
        </div>
      )}
      {(layerErr || aoiErr) && <div role="alert" className="absolute bottom-14 left-2 z-[600] max-w-sm rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">{layerErr || aoiErr}</div>}
      {/* legend */}
      {!legend && <button type="button" className="btn absolute bottom-6 right-2 z-[500] shadow max-sm:bottom-auto max-sm:top-24" aria-expanded={false} onClick={() => setLegend(true)}>Legend</button>}
      <div className={cls('absolute bottom-6 right-2 z-[500] max-w-[300px] rounded-lg bg-panel/95 px-2 py-1.5 text-[10px] shadow max-sm:bottom-auto max-sm:top-24 max-sm:max-w-[240px]', !legend && 'hidden')} aria-label="Map legend" data-testid="map-legend">
        <button type="button" className="float-right ml-1 rounded p-0.5 text-muted hover:text-ink" aria-label="Hide legend" onClick={() => setLegend(false)}><Icon name="x" className="h-3 w-3" /></button>
        {s.mapLayer === 'cells' ? (
          <>
            <div className="mb-1 font-semibold">{cellSeries === 'UNION' ? `Selected sensors detecting each ${dGrid}° cell` : `${SERIES_SHORT[cellSeries] ?? cellSeries} detections per ${dGrid}° cell in window`}</div>
            <div className="flex items-center gap-1"><span>1</span>{RAMP.map((c) => <span key={c} className="inline-block h-2.5 w-4" style={{ background: c }} />)}<span>{fmtNum(maxN)}</span></div>
            {!isUnion && cellSeries !== 'UNION' && <div className="mt-0.5 flex items-center gap-1 text-muted"><span className="inline-block h-2.5 w-4 border border-zinc-500 bg-zinc-400/20" />Detected only by other selected sensor(s)</div>}
            <div className="mt-0.5 text-muted">Original observations. Cells are grid summaries, not burned-area polygons.</div>
            {current?.truncated && <div className="text-amber-700">Showing {current.cells.length} of {current.cells_total} cells (truncated)</div>}
          </>
        ) : s.mapLayer === 'points' ? (
          <>
            <div className="mb-1 font-semibold">Observed Active-Fire Detections</div>
            {['MODIS', 'VIIRS_N20', 'VIIRS_N21', 'VIIRS_SNPP'].map((k) => <div key={k} className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SERIES_COLOR[k] }} />{SERIES_SHORT[k]}</div>)}
            {pts && <div className="text-muted">{fmtNum(pts.returned)} of {fmtNum(pts.total)} in view{pts.truncated ? ' (truncated; zoom in)' : ''}</div>}
            <div className="text-muted">Pixel centres (~1 km MODIS / ~375 m VIIRS nominal); not fire sizes, not confirmed fires. Click a point for its NASA FIRMS attributes.</div>
          </>
        ) : (
          <div data-testid="harm-legend">
            <div className="mb-1 font-semibold">Experimental Harmonized Activity Index</div>
            <div className="flex items-center gap-1"><span>&gt;0</span>{RAMP.map((c) => <span key={c} className="inline-block h-2.5 w-4" style={{ background: c }} />)}<span>{fz ? fmtNum(maxH, 1) : '…'}</span></div>
            <div className="mt-0.5">MODIS-Aqua-equivalent detections per {dGrid}° cell, summed over the window</div>
            {fz && <>
              <div className="mt-0.5">Sensors: {fz.contributors.map((p) => PLATFORM_SHORT[p] ?? p).join(', ') || 'none known'} · reference MODIS Aqua · {fz.days_known} of {fz.days} day(s) with known data</div>
              <div className="mt-0.5"><span className={cls('rounded px-1 font-semibold', fusionStatusClass(fz.validation_status))} data-testid="harm-status" data-status={fz.validation_status}>{FUSION_STATUS_TEXT[fz.validation_status]}</span>
                {fz.coefficient_source.aoi !== s.aoi && <span className="text-amber-700"> · {fz.coefficient_source.label}</span>}</div>
              <div className="mt-0.5 text-muted">Window total {fmtNum(fz.fused_total, 1)}. Single cells are not validated at any grid size; not burned area or fire boundaries.</div>
              {fz.truncated && <div className="text-amber-700">Showing {fz.cells.length} of {fz.cells_total} cells</div>}
            </>}
          </div>
        )}
        <div className="mt-0.5 text-muted">Auto grid: zoom 3–5 → 0.25°, 6–7 → 0.1°, 8–10 → 0.05°, 11+ → 0.01° (now {gridForZoom(s.mapZoom)}°).</div>
      </div>
    </div>
  )
}

/** Map layer pills for the Explore control bar: original detections, grid cells, harmonized index. */
export function MapLayerPills() {
  const s = useApp()
  const { grid: dGrid } = useDisplayQS()
  return (
    <div className="seg" role="group" aria-label="Map layer">
      <button aria-pressed={s.mapLayer === 'points'} onClick={() => s.set({ mapLayer: 'points' })} title="Original NASA FIRMS detections (pixel centres); click one for its attributes">Detections</button>
      <button aria-pressed={s.mapLayer === 'cells'} onClick={() => s.set({ mapLayer: 'cells' })} title="Original detections of the primary sensor per grid cell">{dGrid}° cells</button>
      <button aria-pressed={s.mapLayer === 'harmonized'} data-testid="layer-harmonized" onClick={() => s.set({ mapLayer: 'harmonized' })} title="Multi-sensor harmonized activity index per grid cell (experimental)">Harmonized</button>
    </div>
  )
}

/** Dated NASA GIBS imagery or a static basemap, for the Explore control bar. */
export function BasemapSelect() {
  const s = useApp()
  const imagery = useApi<Imagery>('/api/imagery/layers')
  return (
    <select className="field max-w-[200px]" aria-label="Imagery or basemap" value={s.imagery === 'off' ? `base:${s.basemap}` : s.imagery}
      onChange={(e) => { const v = e.target.value; if (v.startsWith('base:')) s.set({ imagery: 'off', basemap: v.slice(5) as 'light' | 'dark' | 'none', imageryOverride: null }); else s.set({ imagery: v, imageryOverride: null }) }}>
      <optgroup label="Dated NASA GIBS imagery">
        {(imagery.data?.layers ?? []).map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
      </optgroup>
      <optgroup label="Static basemaps">
        <option value="base:light">Light basemap (static)</option><option value="base:dark">Dark basemap (static)</option><option value="base:none">None (offline)</option>
      </optgroup>
    </select>
  )
}
