import { useEffect, useRef, useState } from 'react'
import { postJSON, prefetch, type Daily, type Frame } from '../api'
import { frameUrl, useDaily, useDisplayFrame, useDisplayQS, useElevated, useFilterQS, useFrame } from '../hooks'
import { selectedSeries, useApp } from '../state'
import { useView } from '../workspace'
import { SERIES_COLOR, SERIES_SHORT, STATUS_LABEL, addDays, cls, diffDays, fmtNum } from '../util'
import MapView, { BasemapSelect, MapLayerPills } from '../components/MapView'
import Timeline from '../components/Timeline'
import { ElevatedList } from '../components/Elevated'
import { ErrorNote, Icon, Panel, StatusSwatch } from '../components/ui'

function Details({ cellFrame, daily }: { cellFrame: Frame | null; daily: Daily | null }) {
  const s = useApp()
  const el = useElevated()
  const cf = cellFrame && cellFrame.frame.date === s.date && cellFrame.frame.mode_days === s.frameMode ? cellFrame : null
  const cell = cf && s.selectedCell ? cf.cells.find((c) => c.ci === s.selectedCell!.ci && c.cj === s.selectedCell!.cj) : null
  const i = daily ? daily.dates.indexOf(s.date) : -1
  return (
    <aside aria-label="Details" data-testid="details-drawer" className="flex min-w-0 flex-col gap-4 lg:w-80 lg:shrink-0">
      <Panel title={`Selected day · ${s.date}`} info="Values for the single selected UTC day across all selected sensors (independent of the map window length). Square: sensor colour = detections recorded; grey = zero reported; hatched = unknown coverage; dashed = outside range.">
        {daily && i >= 0 ? (
          <table className="data compact text-[11px]" data-testid="day-table"><thead><tr><th>Sensor</th><th className="text-right">Det.</th><th className="text-right">Cells</th><th className="text-right" title="Maximum fire radiative power, MW">FRP max</th></tr></thead>
            <tbody>{Object.entries(daily.series).map(([k, v]) => (
              <tr key={k} title={`${SERIES_SHORT[k]}: ${daily.status_doc[v.status[i]] ?? v.status[i]}`}><td className="whitespace-nowrap"><span className="mr-1.5 inline-flex align-middle"><StatusSwatch status={v.status[i]} color={SERIES_COLOR[k]} /></span>{SERIES_SHORT[k]}<span className="sr-only"> ({STATUS_LABEL[v.status[i]] ?? v.status[i]})</span></td>
                <td className="num text-right">{k === 'UNION' ? '—' : fmtNum(v.detections[i])}</td><td className="num text-right">{fmtNum(v.cells[i])}</td><td className="num text-right">{k === 'UNION' ? '—' : fmtNum(v.frp_max[i], 1)}</td></tr>))}</tbody></table>
        ) : <p className="text-xs text-muted">Loading…</p>}
        {daily && i >= 0 && daily.series.MODIS && <p className="mt-1 text-[11px] text-muted">MODIS by platform: Terra {daily.series.MODIS.terra?.[i] ?? 0}, Aqua {daily.series.MODIS.aqua?.[i] ?? 0}. {daily.series[s.series]?.unfiltered[i] ? `${daily.series[s.series].unfiltered[i] - daily.series[s.series].detections[i]} ${SERIES_SHORT[s.series]} records removed by quality/type filters.` : ''}</p>}
      </Panel>
      {cell && cf && (
        <Panel title="Selected grid cell" actions={<button className="text-xs underline" onClick={() => s.set({ selectedCell: null })}>Clear</button>}>
          <div className="space-y-1 text-xs" data-testid="cell-details">
            <div>{cf.grid_size}° cell col {cell.ci}, row {cell.cj}: {(cell.ci * cf.grid_size - 180).toFixed(2)}° to {(cell.ci * cf.grid_size - 180 + cf.grid_size).toFixed(2)}° E, {(cell.cj * cf.grid_size - 90).toFixed(2)}° to {(cell.cj * cf.grid_size - 90 + cf.grid_size).toFixed(2)}° N</div>
            {Object.entries(cell.by_series).map(([k, v]) => <div key={k} className="flex justify-between"><span>{SERIES_SHORT[k]}</span><b className="num">{v} detections</b></div>)}
            <div>Max FRP {fmtNum(cell.frp_max, 1)} MW · active on {cell.days} day(s) in window ({cell.first} → {cell.last})</div>
            <p className="text-muted">A grid cell with detections is not a burned-area polygon.</p>
          </div>
        </Panel>
      )}
      <Panel title="Elevated observed activity" info="Explainable rule applied to the primary sensor and metric over the analysis range. Click a period to show it on the map and timeline. Descriptive; not a warning.">
        <p className="mb-2 text-[11px] text-muted" data-testid="elevated-summary">{el.data ? (el.data.unavailable ? 'Not available for this selection' : `${el.data.periods.length} period(s)`) : 'Loading…'} · {SERIES_SHORT[s.series]}, {s.start.slice(0, 4)}–{s.end.slice(0, 4)}</p>
        <div className="max-h-[320px] overflow-y-auto" data-testid="elevated-box"><ElevatedList q={el} compact /></div>
      </Panel>
    </aside>
  )
}

/** Per-sensor detections and occupied cells for the map window (the HUD's live counters). */
function Counters({ frame }: { frame: Frame | null }) {
  const s = useApp()
  const cur = frame && frame.frame.date === s.date && frame.frame.mode_days === s.frameMode ? frame : null
  const sers = selectedSeries(s.platforms)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]" data-testid="hud-counters" aria-live="polite"
      title={`Raw FIRMS detections in the map window, per sensor (not fire events or burned area). Cells = distinct ${s.grid}° cells with ≥1 detection by any selected sensor.`}>
      {cur ? <>
        {sers.map((k) => <span key={k} className="flex items-center gap-1 whitespace-nowrap"><span className="h-2 w-2 rounded-full" style={{ background: SERIES_COLOR[k] }} />{SERIES_SHORT[k]} <b className="num" data-testid={`det-${k}`}>{fmtNum(cur.summary[k]?.detections ?? 0)}</b></span>)}
        <span className="whitespace-nowrap text-muted">Cells <b className="num text-ink" data-testid="union-cells">{fmtNum(cur.union.cells)}</b></span>
      </> : <span className="text-muted">Loading counts…</span>}
    </div>
  )
}

export default function Explore() {
  const s = useApp()
  const view = useView()
  const frame = useFrame() // analysis grid: counters and statistics (never change with zoom for a fixed AOI)
  const mapFrame = useDisplayFrame() // display grid: the map's detection-grid layer
  const daily = useDaily()
  const el = useElevated()
  const fileRef = useRef<HTMLInputElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const drawerBefore = useRef(s.detailsOpen)
  const [upErr, setUpErr] = useState<string | null>(null)
  const stage = view.stage
  const onFile = async (f: File) => {
    setUpErr(null)
    try {
      const gj = JSON.parse(await f.text())
      const r = await postJSON<{ id: string; notes: string[] }>('/api/aoi', { geojson: gj, name: f.name.replace(/\.[^.]+$/, '').slice(0, 60) })
      s.set({ aoi: r.id })
    } catch (e) { setUpErr(e instanceof SyntaxError ? 'File is not valid JSON/GeoJSON.' : (e as Error).message) }
  }
  // Theater and fullscreen collapse the info drawer; going back to the default size restores it.
  const setStage = (next: typeof stage) => {
    if (next === stage) return
    if (stage === 'default') drawerBefore.current = useApp.getState().detailsOpen
    if (next === 'fullscreen') { try { void stageRef.current?.requestFullscreen?.() } catch { /* not supported: CSS fallback below */ } }
    else if (document.fullscreenElement) { void document.exitFullscreen().catch(() => {}) }
    view.set({ stage: next })
    useApp.getState().set({ detailsOpen: next === 'default' ? drawerBefore.current : false })
  }
  const setStageRef = useRef(setStage)
  setStageRef.current = setStage
  useEffect(() => {
    // leaving browser fullscreen (Esc) returns to the default stage
    const onFs = () => { if (!document.fullscreenElement && useView.getState().stage === 'fullscreen') setStageRef.current('default') }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && useView.getState().stage !== 'default') setStageRef.current('default') }
    document.addEventListener('fullscreenchange', onFs)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('fullscreenchange', onFs); document.removeEventListener('keydown', onKey) }
  }, [])
  // leaving the page resets the stage
  useEffect(() => () => { if (useView.getState().stage !== 'default') { useView.getState().set({ stage: 'default' }); if (document.fullscreenElement) void document.exitFullscreen().catch(() => {}) } }, [])
  // speed: once the selected day settles, quietly fetch the previous and next day (map grid and counters)
  const filterQs = useFilterQS()
  const { qs: displayQs } = useDisplayQS()
  useEffect(() => {
    const t = window.setTimeout(() => {
      for (const d of [addDays(s.date, 1), addDays(s.date, -1)]) {
        if (d < s.start || d > s.end) continue
        prefetch(frameUrl(displayQs, d, s.frameMode))
        prefetch(frameUrl(filterQs, d, s.frameMode))
      }
    }, 700)
    return () => window.clearTimeout(t)
  }, [s.date, s.start, s.end, s.frameMode, displayQs, filterQs])
  const tooLong = diffDays(s.start, s.end) < 0
  const full = stage === 'fullscreen'
  return (
    <div className={cls('flex flex-col gap-4', stage === 'theater' ? 'p-2 lg:p-3' : 'p-4 lg:p-6')}>
      {upErr && <ErrorNote msg={`GeoJSON AOI rejected: ${upErr}`} />}
      {tooLong && <ErrorNote msg="Analysis range end is before its start." />}
      <input ref={fileRef} type="file" accept=".geojson,.json,application/geo+json,application/json" className="hidden" aria-label="Upload GeoJSON AOI"
        data-testid="geojson-input" onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <div ref={stageRef} data-testid="map-stage" data-stage={stage}
          className={cls('flex min-w-0 flex-1 flex-col overflow-hidden border border-line bg-panel',
            full ? 'fixed inset-0 z-[1500] rounded-none border-0' : 'rounded-xl')}>
          <div className={cls('relative min-h-0',
            full ? 'flex-1' : stage === 'theater' ? 'h-[calc(100dvh-20rem)] min-h-[420px]' : 'aspect-video min-h-[360px] max-h-[78vh] md:min-h-[540px]')}>
            <MapView frame={mapFrame} onUploadRequest={() => fileRef.current?.click()} />
          </div>
          <Timeline daily={daily.data} elevated={el.data} variant="hud"
            tools={<><MapLayerPills /><BasemapSelect /><Counters frame={frame.data} /></>}
            end={<>
              <button type="button" className="btn px-2 max-lg:hidden" aria-pressed={s.detailsOpen} data-testid="drawer-toggle"
                aria-label={s.detailsOpen ? 'Hide day and activity panel' : 'Show day and activity panel'} title={s.detailsOpen ? 'Hide panel' : 'Show panel'}
                onClick={() => s.set({ detailsOpen: !s.detailsOpen })}><Icon name="panelRight" /></button>
              <button type="button" className="btn px-2 max-md:hidden" aria-pressed={stage === 'theater'} data-testid="stage-theater"
                aria-label={stage === 'theater' ? 'Default view' : 'Theater mode'} title={stage === 'theater' ? 'Default view' : 'Theater mode'}
                onClick={() => setStage(stage === 'theater' ? 'default' : 'theater')}><Icon name="theater" /></button>
              <button type="button" className="btn px-2" aria-pressed={full} data-testid="stage-fullscreen"
                aria-label={full ? 'Exit full screen' : 'Full screen'} title={full ? 'Exit full screen (Esc)' : 'Full screen'}
                onClick={() => setStage(full ? 'default' : 'fullscreen')}><Icon name={full ? 'minimize' : 'maximize'} /></button>
            </>} />
          {daily.error && <div className="p-2"><ErrorNote msg={daily.error} /></div>}
        </div>
        {s.detailsOpen && stage === 'default' && <Details cellFrame={mapFrame.data} daily={daily.data} />}
      </div>
      {stage === 'default' && !s.detailsOpen && <div className="lg:hidden"><Details cellFrame={mapFrame.data} daily={daily.data} /></div>}
    </div>
  )
}
