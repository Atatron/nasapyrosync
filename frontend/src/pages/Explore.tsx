import { useRef, useState } from 'react'
import { postJSON, type Daily, type Frame, type Region } from '../api'
import { useDaily, useDisplayFrame, useElevated, useFrame } from '../hooks'
import { frameWindow, selectedSeries, useApp } from '../state'
import { SERIES_COLOR, SERIES_SHORT, STATUS_LABEL, cls, diffDays, fmtNum } from '../util'
import MapView from '../components/MapView'
import Timeline from '../components/Timeline'
import { ElevatedList } from '../components/Elevated'
import { ErrorNote, Info, Panel, StatusSwatch, Warnings } from '../components/ui'

function Card({ label, children, info, testid }: { label: string; children: React.ReactNode; info?: React.ReactNode; testid?: string }) {
  return (
    <div className="panel min-w-0 px-3.5 py-3" data-testid={testid}>
      <div className="label">{label}{info && <Info>{info}</Info>}</div>
      <div className="num mt-1.5 text-sm">{children}</div>
    </div>
  )
}

function windowStatus(daily: Daily | null, series: string, w0: string, w1: string) {
  const out: Record<string, number> = {}
  if (!daily) return out
  const ser = daily.series[series]
  if (!ser) return out
  daily.dates.forEach((d, i) => { if (d >= w0 && d <= w1) out[ser.status[i]] = (out[ser.status[i]] ?? 0) + 1 })
  return out
}

function Summary({ frame, daily, regions, elevatedCount }: { frame: Frame | null; daily: Daily | null; regions: Region[]; elevatedCount: number | null }) {
  const s = useApp()
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  const cur = frame && frame.frame.date === s.date && frame.frame.mode_days === s.frameMode ? frame : null
  const aoiName = s.aoi === 'none' ? 'All imported observations' : s.aoi.startsWith('region:') ? regions.find((r) => r.id === s.aoi)?.name ?? s.aoi
    : s.aoi.startsWith('circle:') ? `Circle, radius ${s.aoi.split(',')[2]} km` : 'Custom AOI'
  const sers = selectedSeries(s.platforms)
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="summary-cards">
      <Card label="Selected AOI" testid="card-aoi">
        <div className="truncate font-semibold" title={aoiName}>{aoiName}</div>
        <div className="text-[11px] text-muted">{s.aoi === 'none' ? 'Download extent is broader than Indonesia' : s.aoi.startsWith('circle:') ? 'Click-to-Analyze: radius follows the map zoom' : 'Exact point-in-polygon filter · fixed when zooming'}</div>
      </Card>
      <Card label="Display window" testid="card-window">
        <div className="font-semibold num">{s.frameMode === 1 ? s.date : `${w0} → ${w1}`}</div>
        <div className="text-[11px] text-muted">{s.frameMode === 1 ? 'Daily frame, UTC' : `Trailing ${s.frameMode} days, UTC`}</div>
      </Card>
      <Card label="Detections by sensor" testid="card-detections" info="Raw FIRMS detection counts in the map window, kept separate per sensor. Detections are not fire events or burned area.">
        {cur ? sers.map((k) => <div key={k} className="flex items-center justify-between gap-2 text-xs"><span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: SERIES_COLOR[k] }} />{SERIES_SHORT[k]}</span><b className="num" data-testid={`det-${k}`}>{fmtNum(cur.summary[k]?.detections ?? 0)}</b></div>) : <span className="text-xs text-muted">Loading…</span>}
      </Card>
      <Card label={`Occupied ${s.grid}° cells`} testid="card-cells" info="Distinct grid cells with ≥1 detection in the window, per sensor. 'Any selected sensor' counts a cell once even if both MODIS and VIIRS detected it.">
        {cur ? <>
          {sers.map((k) => <div key={k} className="flex justify-between text-xs"><span>{SERIES_SHORT[k]}</span><b className="num">{fmtNum(cur.summary[k]?.cells ?? 0)}</b></div>)}
          <div className="flex justify-between border-t border-line text-xs"><span>Any selected sensor</span><b className="num" data-testid="union-cells">{fmtNum(cur.union.cells)}</b></div>
        </> : <span className="text-xs text-muted">Loading…</span>}
      </Card>
      <Card label="Data availability" testid="card-availability" info="Coverage state of each day in the map window for the primary sensor. Zero-detection days count as 'zero reported' only inside an imported request interval; otherwise they are unknown.">
        {daily ? Object.entries(windowStatus(daily, s.series, w0, w1)).map(([k, v]) => <div key={k} className="flex items-center gap-1.5 text-xs"><StatusSwatch status={k} color={SERIES_COLOR[s.series]} /><span className="truncate">{STATUS_LABEL[k]}</span><b className="ml-auto num">{v}d</b></div>) : <span className="text-xs text-muted">Loading…</span>}
      </Card>
      <Card label="Elevated periods" testid="card-elevated" info="Number of periods meeting the current elevated-activity rule in the analysis range (see details panel). Descriptive; not a warning.">
        <div className="font-mono text-lg font-semibold tabular-nums">{elevatedCount === null ? '—' : elevatedCount}</div>
        <div className="text-[11px] text-muted">{SERIES_SHORT[s.series]}, {s.start.slice(0, 4)}–{s.end.slice(0, 4)}</div>
      </Card>
    </div>
  )
}

function Details({ frame, cellFrame, daily }: { frame: Frame | null; cellFrame: Frame | null; daily: Daily | null }) {
  const s = useApp()
  const el = useElevated()
  const cur = frame && frame.frame.date === s.date && frame.frame.mode_days === s.frameMode ? frame : null
  const cf = cellFrame && cellFrame.frame.date === s.date && cellFrame.frame.mode_days === s.frameMode ? cellFrame : null
  const cell = cf && s.selectedCell ? cf.cells.find((c) => c.ci === s.selectedCell!.ci && c.cj === s.selectedCell!.cj) : null
  const i = daily ? daily.dates.indexOf(s.date) : -1
  return (
    <aside aria-label="Details" className="flex min-w-0 flex-col gap-4 lg:col-span-4">
      <Panel title={`Selected day · ${s.date}`} info="Values for the single selected UTC day across all selected sensors (independent of the map window length).">
        {daily && i >= 0 ? (
          <table className="data" data-testid="day-table"><thead><tr><th>Sensor</th><th>Det.</th><th>Cells</th><th>Max FRP</th><th>Status</th></tr></thead>
            <tbody>{Object.entries(daily.series).map(([k, v]) => (
              <tr key={k}><td><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: SERIES_COLOR[k] }} />{SERIES_SHORT[k]}</td>
                <td className="num">{k === 'UNION' ? '—' : fmtNum(v.detections[i])}</td><td className="num">{fmtNum(v.cells[i])}</td><td className="num">{k === 'UNION' ? '—' : fmtNum(v.frp_max[i], 1)}</td>
                <td title={daily.status_doc[v.status[i]]}><StatusSwatch status={v.status[i]} color={SERIES_COLOR[k]} /></td></tr>))}</tbody></table>
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
      <Panel title="Elevated observed activity" info="Explainable rule applied to the primary sensor and metric over the analysis range. Click a period to show it on the map and timeline.">
        <div className="max-h-[320px] overflow-y-auto" data-testid="elevated-box"><ElevatedList q={el} compact /></div>
      </Panel>
      {cur && <Panel title="Filters applied"><ul className="space-y-0.5 text-[11px] text-muted">
        <li>{String(cur.filter_disclosure.modis_quality)}; {String(cur.filter_disclosure.viirs_quality)}</li>
        <li>Types included: {cur.filter_disclosure.types_included.join(', ')}</li>
        <li>Types excluded: {cur.filter_disclosure.types_excluded.join(', ') || 'none'}</li>
        <li>Revision {cur.dataset_revision} · {cur.processing_version}</li></ul>
        <div className="mt-2"><Warnings items={cur.warnings} /></div></Panel>}
    </aside>
  )
}

export default function Explore({ regions }: { regions: Region[] }) {
  const s = useApp()
  const frame = useFrame() // analysis grid: cards and statistics (never change with zoom for a fixed AOI)
  const mapFrame = useDisplayFrame() // display grid: the map's detection-grid layer
  const daily = useDaily()
  const el = useElevated()
  const fileRef = useRef<HTMLInputElement>(null)
  const [upErr, setUpErr] = useState<string | null>(null)
  const onFile = async (f: File) => {
    setUpErr(null)
    try {
      const gj = JSON.parse(await f.text())
      const r = await postJSON<{ id: string; notes: string[] }>('/api/aoi', { geojson: gj, name: f.name.replace(/\.[^.]+$/, '').slice(0, 60) })
      s.set({ aoi: r.id })
    } catch (e) { setUpErr(e instanceof SyntaxError ? 'File is not valid JSON/GeoJSON.' : (e as Error).message) }
  }
  const tooLong = diffDays(s.start, s.end) < 0
  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Summary frame={frame.data} daily={daily.data} regions={regions} elevatedCount={el.data ? (el.data.unavailable ? null : el.data.periods.length) : null} />
      {upErr && <ErrorNote msg={`GeoJSON AOI rejected: ${upErr}`} />}
      {tooLong && <ErrorNote msg="Analysis range end is before its start." />}
      <input ref={fileRef} type="file" accept=".geojson,.json,application/geo+json,application/json" className="hidden" aria-label="Upload GeoJSON AOI"
        data-testid="geojson-input" onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className={cls('flex min-w-0 flex-col gap-4', s.detailsOpen ? 'lg:col-span-8' : 'lg:col-span-12')}>
          <div className="h-[56vh] min-h-[360px]"><MapView frame={mapFrame} onUploadRequest={() => fileRef.current?.click()} /></div>
          <Timeline daily={daily.data} elevated={el.data} />
          {daily.error && <ErrorNote msg={daily.error} />}
        </div>
        {s.detailsOpen && <Details frame={frame.data} cellFrame={mapFrame.data} daily={daily.data} />}
      </div>
    </div>
  )
}
