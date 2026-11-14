// Map of the AOI Insights tab (added in v1.3): fire recurrence per cell, or how unusual the latest window is per cell.
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { getJSON } from '../api'
import { BAND_COLOR, RECUR_RAMP, type AnomCell, type RecCell } from '../insights'
import { useApp } from '../state'

const ESRI_ATTR = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors'
const BASE = {
  light: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
  dark: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
}

export function recurColor(share: number): string {
  return RECUR_RAMP[Math.min(RECUR_RAMP.length - 1, Math.floor(share * RECUR_RAMP.length))]
}

function f(v: number, d = 2) { return v.toLocaleString('en-US', { maximumFractionDigits: d }) }

function recTip(c: RecCell, n: number): string {
  return [`<b>Cell ${c.lon.toFixed(2)}°E, ${c.lat.toFixed(2)}°N</b>`,
    `Fire in <b>${c.fire_years} of ${n}</b> complete years (${Math.round(c.share * 100)} %)${c.chronic ? ' · <b>chronic</b>' : ''}`,
    `Longest run of consecutive fire years: ${c.longest_run}`,
    `First / last fire year: ${c.first_year} / ${c.last_year}`,
    `Detections in complete years: ${c.detections.toLocaleString('en-US')}`].join('<br/>')
}

function anomTip(c: AnomCell, nRef: number): string {
  return [`<b>Cell ${c.lon.toFixed(2)}°E, ${c.lat.toFixed(2)}°N</b>`,
    `Detections in the window: <b>${c.value}</b>`,
    `Same window in ${nRef} earlier years: median ${f(c.reference_median, 1)}, 75th percentile ${f(c.reference_p75, 1)}; fire in ${c.years_with_fire} of them`,
    `Score z = <b>${f(c.z)}</b> → <b>${c.band}</b>${c.floor_applied ? ' (scale floor applied)' : ''}`].join('<br/>')
}

export default function InsightsMap({ aoi, grid, mode, rec, anom, nYears, height = 460 }: {
  aoi: string; grid: number; mode: 'recurrence' | 'anomaly'; rec: RecCell[]; anom: AnomCell[]; nYears: number; height?: number
}) {
  const basemap = useApp((s) => s.basemap)
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const renderer = useRef<L.Canvas | null>(null)
  const lay = useRef<{ base?: L.TileLayer; cells?: L.LayerGroup; aoi?: L.GeoJSON }>({})

  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { center: [-1.5, 113.5], zoom: 5, minZoom: 3, maxZoom: 12, preferCanvas: true })
    renderer.current = L.canvas({ padding: 0.3 })
    m.attributionControl.setPrefix('Leaflet')
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m) return
    lay.current.base?.remove()
    lay.current.base = undefined
    if (basemap !== 'none') {
      lay.current.base = L.tileLayer(BASE[basemap], { attribution: ESRI_ATTR + ' · static basemap', maxNativeZoom: 16, maxZoom: 19 }).addTo(m)
      lay.current.base.bringToBack()
    }
  }, [basemap])

  useEffect(() => {
    const m = map.current
    lay.current.aoi?.remove()
    lay.current.aoi = undefined
    if (!m || aoi === 'none') return
    const url = aoi.startsWith('region:') ? `/api/regions/${aoi.slice(7)}.geojson` : `/api/aoi/${encodeURIComponent(aoi)}`
    let alive = true
    getJSON<GeoJSON.Feature>(url).then((g) => {
      if (!alive || !map.current) return
      lay.current.aoi = L.geoJSON(g, { interactive: false, style: { color: '#0f1d3a', weight: 2, dashArray: '5 4', fill: false } }).addTo(map.current)
      const b = lay.current.aoi.getBounds()
      map.current.invalidateSize()
      if (b.isValid()) map.current.fitBounds(b, { padding: [20, 20], maxZoom: 9, animate: false })
    }).catch(() => {})
    return () => { alive = false }
  }, [aoi])

  useEffect(() => {
    const m = map.current
    if (!m) return
    lay.current.cells?.remove()
    const grp = L.layerGroup()
    const h = grid / 2
    const opts = (fill: string) => ({ renderer: renderer.current!, weight: 0, fillColor: fill, fillOpacity: 0.85 })
    if (mode === 'recurrence') {
      for (const c of rec) {
        L.rectangle([[c.lat - h, c.lon - h], [c.lat + h, c.lon + h]], opts(recurColor(c.share)))
          .bindTooltip(recTip(c, nYears), { sticky: true }).addTo(grp)
      }
    } else {
      // draw normal cells first so unusual ones stay on top
      const order = [...anom].sort((a, b) => a.z - b.z)
      for (const c of order) {
        L.rectangle([[c.lat - h, c.lon - h], [c.lat + h, c.lon + h]], opts(BAND_COLOR[c.band] ?? '#cbd5e1'))
          .bindTooltip(anomTip(c, nYears), { sticky: true }).addTo(grp)
      }
    }
    grp.addTo(m)
    lay.current.cells = grp
  }, [mode, rec, anom, grid, nYears])

  return <div ref={el} className="w-full overflow-hidden rounded-lg border border-line" style={{ height }} role="region"
    aria-label={mode === 'recurrence' ? 'Map of fire recurrence per grid cell' : 'Map of unusual activity per grid cell'} />
}
