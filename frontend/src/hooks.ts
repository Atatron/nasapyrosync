import { useMemo } from 'react'
import { useApi, type Daily, type Elevated, type Frame, type Inventory } from './api'
import { displayBbox, displayGrid, filterParams, useApp, type AppState } from './state'
import type { FusionFrame } from './fusion'

export function useFilterQS(): string {
  const s = useApp()
  return useMemo(() => filterParams(s).toString(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [s.start, s.end, s.platforms, s.modisMinConf, s.viirsConf, s.types, s.daynight, s.aoi, s.grid, s.revision])
}

export function useInventory() {
  const rev = useApp((s) => s.revision)
  return useApi<Inventory>(`/api/inventory?_rev=${rev}`)
}

export function useDaily() {
  const qs = useFilterQS()
  const ok = useApp((s) => s.platforms.length > 0)
  const fused = useApp((s) => s.series === 'FUSED')
  return useApi<Daily>(ok ? `/api/daily?${qs}${fused ? '&fused=true' : ''}` : null)
}

/** 1.5: query string for MAP layers only: the display grid (auto from zoom or manual) and, on fine grids, the snapped viewport.
 * Statistics (cards, calendar, insights) keep the analysis grid, so zooming never changes them for a fixed Region AOI. */
export function useDisplayQS(): { qs: string; grid: number; bbox: string | null } {
  const qs = useFilterQS()
  const gridMode = useApp((s) => s.gridMode)
  const grid = useApp((s) => s.grid)
  const zoom = useApp((s) => s.mapZoom)
  const mb = useApp((s) => s.mapBbox)
  const g = displayGrid({ gridMode, grid, mapZoom: zoom })
  const bbox = displayBbox({ mapBbox: mb }, g)
  return useMemo(() => {
    const p = new URLSearchParams(qs)
    p.set('grid', String(g))
    if (bbox) p.set('bbox', bbox)
    return { qs: p.toString(), grid: g, bbox }
  }, [qs, g, bbox])
}

export function useDisplayFrame() {
  const { qs } = useDisplayQS()
  const { date, frameMode } = useApp()
  const ok = useApp((s) => s.platforms.length > 0)
  return useApi<Frame>(ok ? frameUrl(qs, date, frameMode) : null)
}

export function useFusionFrame(enabled: boolean) {
  const { qs } = useDisplayQS()
  const { date, frameMode } = useApp()
  return useApi<FusionFrame>(enabled ? `/api/fusion/map?${qs}&date=${date}&mode=${frameMode}` : null)
}

export function frameUrl(qs: string, date: string, mode: number): string {
  return `/api/frame?${qs}&date=${date}&mode=${mode}`
}

export function useFrame() {
  const qs = useFilterQS()
  const { date, frameMode } = useApp()
  const ok = useApp((s) => s.platforms.length > 0)
  return useApi<Frame>(ok ? frameUrl(qs, date, frameMode) : null)
}

export function elevatedUrl(qs: string, s: AppState): string {
  const p = new URLSearchParams(qs)
  p.set('series', s.series)
  p.set('metric', s.metric)
  p.set('mode', s.elevatedMode)
  p.set('percentile', String(s.percentile))
  if (s.threshold !== null) p.set('threshold', String(s.threshold))
  p.set('min_days', String(s.minDays))
  p.set('min_activity', String(s.minActivity))
  return `/api/elevated?${p.toString()}`
}

export function useElevated() {
  const qs = useFilterQS()
  const s = useApp()
  const valid = s.platforms.length > 0 && seriesAvailable(s)
  return useApi<Elevated>(valid ? elevatedUrl(qs, s) : null)
}

export function seriesAvailable(s: Pick<AppState, 'series' | 'platforms'>): boolean {
  if (s.series === 'UNION' || s.series === 'FUSED') return s.platforms.length > 0
  const map: Record<string, string> = { Terra: 'MODIS', Aqua: 'MODIS', N20: 'VIIRS_N20', N21: 'VIIRS_N21', SNPP: 'VIIRS_SNPP' }
  return s.platforms.some((p) => map[p] === s.series)
}

export function useSeriesParams(extra: Record<string, string> = {}) {
  const qs = useFilterQS()
  const { series, metric } = useApp()
  const p = new URLSearchParams(qs)
  p.set('series', series)
  p.set('metric', metric)
  for (const [k, v] of Object.entries(extra)) p.set(k, v)
  return p.toString()
}
