import { useMemo, useState } from 'react'
import { useApi, type Baseline, type Compare, type History, type Rankings } from '../api'
import { useDaily, useElevated, useFilterQS, useInventory, useSeriesParams } from '../hooks'
import { useApp } from '../state'
import { MON3, METRIC_INFO, SERIES_COLOR, SERIES_SHORT, addDays, fmtDate, fmtNum } from '../util'
import { EChart, Empty, ErrorNote, Info, Loading, Panel, Seg } from '../components/ui'
import { ElevatedList, ElevatedSettings } from '../components/Elevated'
import { ModisEquivalentComparison } from '../components/HarmonizationAggregate'
import { FusionBanner, FusionHistory } from '../components/FusionParts'
import type { FusionSeries } from '../fusion'

type Measure = 'detections' | 'sum_daily_cells' | 'distinct_cells' | 'frp_sum'
const MEASURE_LABEL: Record<Measure, string> = {
  detections: 'Detections', sum_daily_cells: 'Sum of daily occupied cells', distinct_cells: 'Distinct cells in month', frp_sum: 'Summed FRP (MW)',
}

function usePeakDay() {
  const daily = useDaily()
  const s = useApp()
  return (prefix: string) => {
    const d = daily.data
    if (!d) return
    const ser = d.series[s.series]
    let best = -1, bd = ''
    const vals = s.series === 'FUSED' ? (ser.detections as (number | null)[]) : ser.cells
    d.dates.forEach((x, i) => { const v = vals[i] ?? -1; if (x.startsWith(prefix) && v > best) { best = v; bd = x } })
    if (bd) { s.set({ frameMode: 1 }); s.setDate(bd) }
  }
}

export default function HistoryPage() {
  const s = useApp()
  const qs = useFilterQS()
  const h = useApi<History>(`/api/history?${qs}`)
  const [measure, setMeasure] = useState<Measure>('sum_daily_cells')
  const peak = usePeakDay()
  const el = useElevated()
  const inv = useInventory()
  const fused = s.series === 'FUSED'
  const fm = useApi<FusionSeries>(fused ? `/api/fusion/series?${qs}&agg=month` : null)

  const monthly = useMemo(() => {
    if (!h.data) return {}
    const keys = Object.keys(h.data.series_labels).filter((k) => k !== 'UNION' || measure === 'distinct_cells' || measure === 'sum_daily_cells')
    return {
      grid: { left: 56, right: 12, top: 36, bottom: 40 },
      legend: { top: 0, textStyle: { fontSize: 11 } },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: h.data.months.map((m) => m.label + (m.partial ? '*' : '')), axisLabel: { fontSize: 10, rotate: 45 } },
      yAxis: { type: 'value', name: MEASURE_LABEL[measure], nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
      series: keys.map((k) => ({ name: SERIES_SHORT[k], type: k === 'UNION' ? 'line' : 'bar', itemStyle: { color: SERIES_COLOR[k] }, lineStyle: { type: 'dashed' },
        data: h.data!.months.map((m) => m.series[k]?.[measure] ?? 0) })),
    }
  }, [h.data, measure])

  const seasonal = useMemo(() => {
    if (fused) {
      if (!fm.data) return {}
      const d = fm.data
      const years = Array.from(new Set(d.dates.map((x) => Number(x.slice(0, 4)))))
      const palette = ['#0f1d3a', '#ea580c', '#0f766e', '#7c3aed', '#2563eb', '#a16207']
      return {
        grid: { left: 56, right: 12, top: 30, bottom: 28 }, legend: { top: 0, type: 'scroll' }, tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: MON3 }, yAxis: { type: 'value', name: 'MODIS-Aqua-eq. detections', nameTextStyle: { fontSize: 10 } },
        series: years.map((y, i) => ({ name: String(y), type: 'line', symbolSize: 6, itemStyle: { color: palette[i % palette.length] },
          data: Array.from({ length: 12 }, (_, mi) => { const k = d.dates.indexOf(`${y}-${String(mi + 1).padStart(2, '0')}`); return k >= 0 ? d.fused[k] : null }) })),
      }
    }
    if (!h.data) return {}
    const years = Array.from(new Set(h.data.months.map((m) => m.year)))
    const palette = ['#0f1d3a', '#ea580c', '#0f766e', '#7c3aed', '#2563eb', '#a16207']
    return {
      grid: { left: 56, right: 12, top: 30, bottom: 28 }, legend: { top: 0 }, tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: MON3 }, yAxis: { type: 'value', name: MEASURE_LABEL[measure], nameTextStyle: { fontSize: 10 } },
      series: years.map((y, i) => ({ name: String(y), type: 'line', symbolSize: 6, itemStyle: { color: palette[i % palette.length] },
        data: Array.from({ length: 12 }, (_, mi) => { const m = h.data!.months.find((x) => x.year === y && x.month === mi + 1); return m ? m.series[s.series]?.[measure] ?? 0 : null }) })),
    }
  }, [h.data, measure, s.series, fused, fm.data])

  return (
    <div className="flex flex-col gap-3 p-3">
      <FusionBanner />
      {h.error && <ErrorNote msg={h.error} />}
      {fused && <Panel title="Harmonized multi-sensor record (whole archive)" info="All eligible satellites on the MODIS Aqua scale, averaged per day; the per-sensor charts below keep the original observations.">
        <FusionHistory range="record" />
      </Panel>}
      <Panel title="Monthly totals by sensor" info="Each sensor is kept separate. 'Sum of daily occupied cells' counts a cell once per day it has detections; 'Distinct cells in month' counts it once per month. * = partial month in the analysis range. Click a bar to jump to that month's most active day."
        actions={<Seg<Measure> label="Monthly measure" value={measure} onChange={setMeasure} options={(Object.keys(MEASURE_LABEL) as Measure[]).map((k) => ({ value: k, label: MEASURE_LABEL[k] }))} />}>
        {!h.data ? <Loading /> : <EChart ariaLabel="Monthly totals by sensor" option={monthly} height={280} onClick={(p) => peak(h.data!.months[p.dataIndex].label)} />}
        {h.data && <p className="mt-1 text-[11px] text-muted">{h.data.notes.join(' ')} MODIS and VIIRS columns are not summed: their detection sensitivities differ.</p>}
      </Panel>
      <Panel title="Experimental MODIS-equivalent comparison (1.4, off by default)" info="Optional. Converts VIIRS daily totals to a MODIS (Aqua) scale with the day-level ratio c = ΣMODIS / ΣVIIRS fitted on earlier days, for the current area, period and type filters. The line is drawn only when that exact setting passes the project's aggregate gate (chronological hold-out plus year-by-year stability); otherwise only the original totals appear. Not an official NASA product, and the bars above are never replaced.">
        <ModisEquivalentComparison qs={qs} available={inv.data?.available_series ?? []} preferred={s.series} testid="hist-meq" />
      </Panel>
      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title={`Seasonal profile · ${SERIES_SHORT[s.series]}`} info="Month-of-year profile for each imported year (primary sensor). Two years cannot establish a seasonal shift or trend.">
          {!h.data ? <Loading /> : <EChart ariaLabel="Seasonal profile by year" option={seasonal} height={240} onClick={(p) => { const y = (seasonal as { series: { name: string }[] }).series.find((x) => x.name === p.seriesName)?.name; if (y) peak(`${y}-${String(p.dataIndex + 1).padStart(2, '0')}`) }} />}
        </Panel>
        <Panel title="Annual summary" info="Per-year totals within the analysis range. Partial years are labeled; compare matched dates in the year comparison below.">
          {!h.data ? <Loading /> : (
            <div className="overflow-x-auto"><table className="data"><thead><tr><th>Year</th><th>Sensor</th><th>Detections</th><th>Σ daily cells</th><th>Distinct cells</th><th>Days w/ det.</th><th>Unknown days</th></tr></thead>
              <tbody>{h.data.years.flatMap((y) => Object.entries(y.series).map(([k, v]) => (
                <tr key={`${y.year}${k}`}><td>{y.year}{y.days_in_range < y.days_in_year && <span className="chip ml-1 bg-amber-100 text-amber-900">partial {y.days_in_range}/{y.days_in_year}d</span>}</td>
                  <td>{SERIES_SHORT[k]}</td><td className="num">{k === 'UNION' ? '—' : fmtNum(v.detections)}</td><td className="num">{fmtNum(v.sum_daily_cells)}</td><td className="num">{fmtNum(v.distinct_cells)}</td><td className="num">{v.days_detections}</td><td className="num">{v.days_unknown}</td></tr>)))}</tbody></table></div>
          )}
        </Panel>
      </div>
      <YearCompare />
      <div className="grid gap-3 xl:grid-cols-2">
        <BaselinePanel />
        <RankingsPanel />
      </div>
      <Panel title="Elevated observed activity" info="Explainable rule; every period lists the exact reason it qualified. Click a period to show it on the map and timeline." actions={<ElevatedSettings />}>
        <ElevatedList q={el} />
      </Panel>
    </div>
  )
}

function YearCompare() {
  const s = useApp()
  const years = s.dataRange ? Array.from({ length: Number(s.dataRange[1].slice(0, 4)) - Number(s.dataRange[0].slice(0, 4)) + 1 }, (_, i) => Number(s.dataRange![0].slice(0, 4)) + i) : []
  const [year, setYear] = useState(years[years.length - 1] ?? 2024)
  const [ref, setRef] = useState(years[0] ?? 2023)
  const p = useSeriesParams({ year: String(year), reference_year: String(ref) })
  const ok = year !== ref && s.metric !== 'frp_mean'
  const q = useApi<Compare>(ok ? `/api/compare?${p}` : null)
  const option = useMemo(() => q.data ? {
    grid: { left: 56, right: 12, top: 30, bottom: 28 }, legend: { top: 0 }, tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: MON3 }, yAxis: { type: 'value', name: METRIC_INFO[s.metric].unit.replace('/day', ' (matched days)'), nameTextStyle: { fontSize: 10 } },
    series: [{ name: `${q.data.year}`, type: 'bar', itemStyle: { color: SERIES_COLOR[s.series] }, data: q.data.months.map((m) => m.value) },
      { name: `${q.data.reference_year} (reference)`, type: 'bar', itemStyle: { color: '#94a3b8' }, data: q.data.months.map((m) => m.ref_value) }],
  } : {}, [q.data, s.metric, s.series])
  if (years.length < 2) return <Panel title="Year comparison"><Empty title="Only one year imported">Import another year to compare.</Empty></Panel>
  return (
    <Panel title={`Year comparison · ${SERIES_SHORT[s.series]}`} info="Descriptive comparison of a selected year against a clearly labeled reference year on matched month-days with known coverage in both. It is not a baseline and cannot show a trend."
      actions={<>
        <label className="text-xs">Year <select className="field" value={year} onChange={(e) => setYear(Number(e.target.value))}>{years.map((y) => <option key={y}>{y}</option>)}</select></label>
        <label className="text-xs">Reference <select className="field" value={ref} onChange={(e) => setRef(Number(e.target.value))}>{years.map((y) => <option key={y}>{y}</option>)}</select></label>
      </>}>
      {!ok ? <Empty title="Choose two different years">{s.metric === 'frp_mean' ? 'Mean FRP is not additive across days; choose another metric.' : ''}</Empty> : q.error ? <ErrorNote msg={q.error} /> : !q.data ? <Loading /> : (
        <>
          <EChart ariaLabel="Monthly comparison of two years" option={option} height={240} />
          <p className="mt-1 text-xs">Matched days: <b>{q.data.totals.matched_days}</b> · {q.data.year}: <b className="num">{fmtNum(q.data.totals.value, 1)}</b> · {q.data.reference_year}: <b className="num">{fmtNum(q.data.totals.ref_value, 1)}</b> · ratio {q.data.totals.ratio === null ? 'undefined (reference is zero)' : q.data.totals.ratio}</p>
          <ul className="mt-1 list-disc pl-5 text-[11px] text-muted">{q.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </>
      )}
    </Panel>
  )
}

function BaselinePanel() {
  const s = useApp()
  const p = useSeriesParams({ window_days: String(s.baselineWindow), min_years: String(s.baselineMinYears) })
  const q = useApi<Baseline>(s.metric === 'frp_mean' ? null : `/api/baseline?${p}`)
  return (
    <Panel title="Unusual conditions · baseline eligibility" info="Above/below-baseline flags use empirical percentiles of prior comparable years in a seasonal window (default ±15 days, P95/P5). They are descriptive threshold exceedances, not significance tests or risk probabilities.">
      {s.metric === 'frp_mean' ? <Empty title="Not supported for mean FRP" /> : q.error ? <ErrorNote msg={q.error} /> : !q.data ? <Loading /> : (
        <div className="space-y-2 text-xs" data-testid="baseline-panel">
          {q.data.eligibility.eligible ? (
            <p className="rounded-md bg-emerald-50 p-2 text-emerald-900">Baseline eligible for some dates. {q.data.flags.length} day(s) flagged above/below their seasonal reference.</p>
          ) : (
            <div className="rounded-md border border-line bg-soft p-3">
              <p className="font-semibold">Insufficient history for a robust multi-year baseline</p>
              <p className="mt-1 text-muted">{q.data.eligibility.reason}</p>
              <p className="mt-1 text-muted">No historical anomaly flags are generated. Use the descriptive year comparison, rankings, or a user-defined threshold instead.</p>
            </div>
          )}
          <div className="flex flex-wrap gap-3">
            <label>Seasonal window ±<input type="number" className="field ml-1 w-16" min={3} max={45} value={s.baselineWindow} onChange={(e) => s.set({ baselineWindow: Math.min(45, Math.max(3, Number(e.target.value) || 15)) })} /> days</label>
            <label>Min. prior years<input type="number" className="field ml-1 w-16" min={1} max={30} value={s.baselineMinYears} onChange={(e) => s.set({ baselineMinYears: Math.min(30, Math.max(1, Number(e.target.value) || 5)) })} /></label>
          </div>
          <p className="text-[11px] text-muted">{q.data.eligibility.rule_note} Lowering the minimum below 5 years weakens the comparison; results remain descriptive. {q.data.notes.join(' ')}</p>
        </div>
      )}
    </Panel>
  )
}

function RankingsPanel() {
  const s = useApp()
  const p = useSeriesParams({ top: '8' })
  const q = useApi<Rankings>(`/api/rankings?${p}`)
  return (
    <Panel title={`Most active observed periods · ${SERIES_SHORT[s.series]}`} info="Descriptive rankings within the selected range; not statistically significant anomalies. Click to select on the timeline.">
      {q.error ? <ErrorNote msg={q.error} /> : !q.data ? <Loading /> : (
        <div className="grid gap-3 sm:grid-cols-2 text-xs" data-testid="rankings">
          <div><div className="label mb-1">Top days</div>
            <ol className="space-y-0.5">{q.data.top_days.map((d) => <li key={d.date}><button className="flex w-full justify-between rounded px-1 hover:bg-soft" onClick={() => { s.set({ frameMode: 1 }); s.setDate(d.date) }}><span>{d.rank}. {fmtDate(d.date)}</span><b className="num">{fmtNum(d.value, 1)}</b></button></li>)}</ol></div>
          <div><div className="label mb-1">Top ISO weeks<Info>Weekly value is the sum of daily values (for cells: summed daily occupied cells).</Info></div>
            <ol className="space-y-0.5">{q.data.top_weeks.map((w) => <li key={w.start}><button className="flex w-full justify-between rounded px-1 hover:bg-soft" onClick={() => { s.set({ frameMode: 7 }); const e = addDays(w.start, 6); s.setDate(e > s.end ? s.end : e) }}><span>{w.rank}. {w.iso_year}-W{String(w.iso_week).padStart(2, '0')}{w.partial ? '*' : ''}</span><b className="num">{fmtNum(w.value, 1)}</b></button></li>)}</ol></div>
          <p className="col-span-full text-[11px] text-muted">{q.data.note}</p>
        </div>
      )}
    </Panel>
  )
}
