import { useMemo, useState } from 'react'
import { useApi, type Observations } from '../api'
import { useDaily, useFilterQS, useInventory } from '../hooks'
import { frameWindow, useApp } from '../state'
import { SERIES_COLOR, SERIES_SHORT, fmtNum } from '../util'
import { EChart, ErrorNote, Loading, Panel, Seg } from '../components/ui'
import Harmonization from '../components/Harmonization'

export default function Workbench({ view = 'series' }: { view?: 'series' | 'records' }) {
  const daily = useDaily()
  const inv = useInventory()
  const [m, setM] = useState<'cells' | 'detections'>('cells')

  const option = useMemo(() => {
    const d = daily.data
    if (!d) return {}
    const keys = Object.keys(d.series).filter((k) => k !== 'UNION')
    const sumCells = d.dates.map((_, i) => keys.reduce((a, k) => a + d.series[k].cells[i], 0))
    const series: unknown[] = keys.map((k) => ({ name: SERIES_SHORT[k], type: 'line', showSymbol: false, lineStyle: { width: 1.2 }, itemStyle: { color: SERIES_COLOR[k] }, data: d.series[k][m] }))
    if (m === 'cells' && keys.length > 1) {
      series.push({ name: 'Any selected sensor (union)', type: 'line', showSymbol: false, lineStyle: { width: 1.5, type: 'dashed' }, itemStyle: { color: SERIES_COLOR.UNION }, data: d.series.UNION.cells })
      series.push({ name: 'Sum of per-sensor cells (double counts overlap)', type: 'line', showSymbol: false, lineStyle: { width: 1, type: 'dotted' }, itemStyle: { color: '#a1a1aa' }, data: sumCells })
    }
    return { grid: { left: 50, right: 12, top: 40, bottom: 50 }, legend: { top: 0, textStyle: { fontSize: 11 } }, tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10 } }, yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 6 }], series }
  }, [daily.data, m])

  const totals = useMemo(() => {
    const d = daily.data
    if (!d) return null
    const out: Record<string, { det: number; day: number; night: number; cellsSum: number; terra: number; aqua: number; frpN: number }> = {}
    for (const [k, v] of Object.entries(d.series)) {
      if (k === 'UNION') continue
      out[k] = { det: v.detections.reduce((a, b) => a + b, 0), day: v.day.reduce((a, b) => a + b, 0), night: v.night.reduce((a, b) => a + b, 0),
        cellsSum: v.cells.reduce((a, b) => a + b, 0), terra: (v.terra ?? []).reduce((a, b) => a + b, 0), aqua: (v.aqua ?? []).reduce((a, b) => a + b, 0), frpN: 0 }
    }
    return out
  }, [daily.data])
  const overlap = daily.data && Object.keys(daily.data.series).length > 2
    ? (() => { const d = daily.data!; const keys = Object.keys(d.series).filter((k) => k !== 'UNION'); const sum = keys.reduce((a, k) => a + d.series[k].cells.reduce((x, y) => x + y, 0), 0); const uni = d.series.UNION.cells.reduce((x, y) => x + y, 0); return { sum, uni } })()
    : null

  if (view === 'records') return <div className="flex flex-col gap-4 p-4 lg:p-6"><SourceRecords /></div>
  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Panel title="Sensor-by-sensor daily series" info="Partial harmonization: all sensors share the same UTC days and grid, but detection sensitivity still differs (VIIRS 375 m detects more small/cool fires than MODIS ~1 km). Series are never merged into one bias-corrected trend."
        actions={<Seg label="Workbench metric" value={m} onChange={setM} options={[{ value: 'cells', label: 'Occupied cells' }, { value: 'detections', label: 'Detections' }]} />}>
        {daily.error ? <ErrorNote msg={daily.error} /> : !daily.data ? <Loading /> : <EChart ariaLabel="Per-sensor daily series" option={option} height={300} />}
        {overlap && m === 'cells' && <p className="mt-1 text-xs">Over the range, summing per-sensor occupied cells gives <b className="num">{fmtNum(overlap.sum)}</b> cell-days; the union counts <b className="num">{fmtNum(overlap.uni)}</b> because cells detected by several sensors on the same day count once. The difference ({fmtNum(overlap.sum - overlap.uni)}) is sensor overlap, which is why per-sensor cell counts are never added together.</p>}
      </Panel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Range totals by sensor">
          {!totals ? <Loading /> : (
            <div className="scroll-box"><table className="data"><thead><tr><th>Sensor</th><th>Detections</th><th>Day</th><th>Night</th><th>Σ daily cells</th></tr></thead>
              <tbody>{Object.entries(totals).map(([k, v]) => <tr key={k}><td><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: SERIES_COLOR[k] }} />{SERIES_SHORT[k]}{k === 'MODIS' && <div className="text-[10px] text-muted">Terra {fmtNum(v.terra)} · Aqua {fmtNum(v.aqua)}</div>}</td>
                <td className="num">{fmtNum(v.det)}</td><td className="num">{fmtNum(v.day)}</td><td className="num">{fmtNum(v.night)}</td><td className="num">{fmtNum(v.cellsSum)}</td></tr>)}</tbody></table></div>
          )}
          <p className="mt-2 text-[11px] text-muted">Day/night flags describe the overpass, not land use, peat burning, crown fire or ignition cause. Terra and Aqua overpass at different local times, and platform availability changes counts.</p>
        </Panel>
        <Panel title="Imported products (all data, unfiltered)">
          {!inv.data ? <Loading /> : (
            <div className="space-y-2">
              <div className="scroll-box"><table className="data"><thead><tr><th>Product</th><th>Platform</th><th>Stream</th><th>Version</th><th>Rows</th><th>Dates</th></tr></thead>
                <tbody>{inv.data.products.map((p) => <tr key={p.source_product + p.platform + p.version}><td>{p.source_product}</td><td>{p.platform_label}</td><td>{p.stream}</td><td>{p.version}</td><td className="num">{fmtNum(p.rows)}</td><td className="whitespace-nowrap">{p.first_date} → {p.last_date}</td></tr>)}</tbody></table></div>
              <div className="grid gap-2 sm:grid-cols-2">
                <table className="data"><thead><tr><th>Confidence</th><th>Rows</th></tr></thead><tbody>{inv.data.confidence_counts.map((c) => <tr key={c.instrument + c.category}><td>{c.instrument} {c.category}</td><td className="num">{fmtNum(c.rows)}</td></tr>)}</tbody></table>
                <table className="data"><thead><tr><th>Type</th><th>Rows</th></tr></thead><tbody>{inv.data.type_counts.map((c) => <tr key={c.instrument + c.type_code}><td>{c.instrument} {c.type_code ?? '—'} {c.label}</td><td className="num">{fmtNum(c.rows)}</td></tr>)}</tbody></table>
              </div>
              <p className="text-[11px] text-muted">MODIS confidence is a numeric 0–100 value; VIIRS confidence is categorical. They are not interchangeable probabilities. MODIS normalized categories use the documented classes (low &lt;30, nominal 30–79, high ≥80).</p>
            </div>
          )}
        </Panel>
      </div>
      <Harmonization />
    </div>
  )
}

function SourceRecords() {
  const s = useApp()
  const qs = useFilterQS()
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  const [page, setPage] = useState(0)
  const [all, setAll] = useState(false)
  const size = 50
  const q = useApi<Observations>(`/api/observations?${qs}&window_start=${w0}&window_end=${w1}&limit=${size}&offset=${page * size}&include_filtered_out=${all}`)
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / size)) : 1
  return (
    <Panel title={`Source records · map window ${w0} → ${w1} UTC`} info="Inspect individual FIRMS records behind the map, including sensor-specific thermal channels. 'Include filtered-out' shows records removed by quality/type filters (AOI and sensors still apply)."
      actions={<label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={all} onChange={(e) => { setAll(e.target.checked); setPage(0) }} />Include filtered-out records</label>}>
      {q.error ? <ErrorNote msg={q.error} /> : !q.data ? <Loading /> : (
        <>
          <div className="scroll-box">
            <table className="data" data-testid="records-table"><thead><tr><th>Date</th><th>Time (UTC)</th><th>Sensor</th><th>Lat</th><th>Lon</th><th>Conf.</th><th>FRP MW</th><th>D/N</th><th>Type</th><th>Thermal (K)</th><th>Scan×Track</th><th>Product · ver</th><th>Source</th></tr></thead>
              <tbody>{q.data.records.map((r) => (
                <tr key={r.rid}><td>{r.acq_date}</td><td className="num">{r.acq_hhmm.slice(0, 2)}:{r.acq_hhmm.slice(2)}</td><td><span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: SERIES_COLOR[r.series] }} />{r.platform}</td>
                  <td className="num">{r.lat.toFixed(5)}</td><td className="num">{r.lon.toFixed(5)}</td><td>{r.conf_raw} <span className="text-muted">({r.conf_cat})</span></td><td className="num">{r.frp ?? '—'}</td><td>{r.daynight ?? '—'}</td>
                  <td title={r.type_label}>{r.type_code ?? '—'}</td>
                  <td className="whitespace-nowrap">{r.instrument === 'MODIS' ? `brightness ${r.modis_brightness} / T31 ${r.modis_bright_t31 ?? '—'}` : `I4 ${r.viirs_bright_ti4} / I5 ${r.viirs_bright_ti5 ?? '—'}`}</td>
                  <td>{r.scan ?? '—'}×{r.track ?? '—'}</td><td>{r.source_product} · {r.version}</td><td className="max-w-[180px] truncate" title={`${r.source_file} row ${r.source_row}`}>{r.source_file.split(':').pop()}:{r.source_row}</td></tr>))}</tbody></table>
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span>Page {page + 1} of {pages} · {fmtNum(q.data.total)} records</span>
            <button className="btn" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
          <p className="mt-1 text-[11px] text-muted">MODIS brightness (channels 21/22) and T31 differ from VIIRS I4/I5 brightness temperatures; they are stored separately and never treated as the same measurement. Scan/track are along-scan/along-track pixel dimensions as reported by FIRMS.</p>
        </>
      )}
    </Panel>
  )
}
