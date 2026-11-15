// Day-level (aggregate) calibration views (added in 1.4): validation of the day-level ratio and its time series.
// The event-level model of 1.0 stays available and unchanged; original observations are never replaced.
import { useMemo, useState } from 'react'
import { useApi } from '../api'
import { AGG_METHOD_LABEL, harmParams, useHarm, type HState, type AggEval, type AggQuantity, type AggReport, type AggSeries } from '../harmonization'
import { SERIES_COLOR, fmtNum } from '../util'
import { EChart, ErrorNote, Loading, Seg } from './ui'
import { ValidityChecks } from './HarmonizationParts'

function f(v: number | null | undefined, d = 1) { return v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }) }

export function GateBadge({ status, testid }: { status: string | undefined; testid?: string }) {
  const ok = status === 'passes'
  return <span data-testid={testid} data-status={status ?? 'loading'}
    className={'rounded-full px-2 py-0.5 text-[11px] font-semibold ' + (ok ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100' : 'bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100')}>
    {ok ? 'Validated under project criteria' : status === 'insufficient' ? 'Insufficient data' : 'Not validated'}</span>
}

const QUANTITY_OPTIONS: { value: AggQuantity; label: string; title: string }[] = [
  { value: 'detections', label: 'Detections per day', title: 'FIRMS detections per UTC day, each sensor its own count' },
  { value: 'cells', label: 'Occupied cells per day', title: 'Comparison-grid cells with at least one detection of that sensor' },
]

export function AggregatePanel({ run }: { run: string }) {
  const h = useHarm()
  const q = useApi<AggReport>(`/api/harmonization/aggregate?${run}&events=true`)
  const r = q.data
  if (q.error) return <ErrorNote msg={q.error} />
  if (!r) return <Loading label="Fitting and testing the day-level ratio…" />
  const ev = r.quantities[h.quantity]
  return (
    <div className="space-y-3 text-xs" data-testid="hagg">
      <div className="flex flex-wrap items-end gap-2">
        <Seg label="Quantity" value={h.quantity} onChange={(v) => h.set({ quantity: v })} options={QUANTITY_OPTIONS} />
        <div className="pb-1"><GateBadge status={ev.gate.status} testid="hagg-badge" /></div>
      </div>
      <p className="text-[11px] text-muted"><b>Why a second method?</b> The event-level model (section 3) is fitted only on cells where both sensors fired.
        Summed over days it misses MODIS-only fires (matched events) or credits VIIRS-only fires with MODIS detections (all events), so its daily totals fail.
        The day-level ratio calibrates the quantity the history pages use: the AOI total of one UTC day. {r.equation}.</p>
      {ev.status !== 'ok' ? <p className="text-amber-700" data-testid="hagg-insufficient">{ev.reason}</p> : <AggDetails r={r} ev={ev} />}
      <details className="rounded-lg border border-line px-3 py-2">
        <summary className="cursor-pointer font-semibold">Assumptions and limits</summary>
        <ul className="mt-1 list-disc pl-5 text-[11px]">{r.limitations.map((t) => <li key={t}>{t}</li>)}
          <li>{r.reference_doc}</li><li>Coverage: {r.coverage.note}</li>
          <li>{r.method_version} · gate {r.gate_version} · dataset revision {r.dataset_revision} · split rule: {r.split_rule}.</li></ul>
      </details>
    </div>
  )
}

function AggDetails({ r, ev }: { r: AggReport; ev: AggEval }) {
  const yrs = ev.rolling_origin?.years ?? []
  const option = useMemo(() => ({
    grid: { left: 48, right: 12, top: 28, bottom: 28 }, tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: yrs.map((y) => String(y.year)), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: 'Σ estimate / Σ MODIS', nameTextStyle: { fontSize: 10 }, min: 0, axisLabel: { fontSize: 10 } },
    series: [{
      name: 'Year predicted from earlier years only', type: 'bar', barMaxWidth: 22,
      data: yrs.map((y) => ({ value: y.ratio === null ? null : Number(y.ratio.toFixed(3)), itemStyle: { color: y.within_level ? '#7c3aed' : '#f59e0b' } })),
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#64748b', type: 'dashed' }, label: { fontSize: 9, formatter: '{c}×' },
        data: [{ yAxis: 0.8 }, { yAxis: 1 }, { yAxis: 1.25 }] },
    }],
  }), [yrs])
  const ho = ev.held_out ?? {}
  const keys = Object.keys(ho)
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <div className="space-y-2">
        <table className="data" data-testid="hagg-summary"><tbody>
          <tr><td>Coefficient c (MODIS per VIIRS)</td><td className="num" data-testid="hagg-c">{f(ev.c, 4)}{ev.bootstrap ? ` (95 % ${f(ev.bootstrap.c_lo, 4)}–${f(ev.bootstrap.c_hi, 4)})` : ''}</td></tr>
          <tr><td>Training days</td><td className="num">{fmtNum(ev.train_days)} · {ev.train_period?.join(' → ')}</td></tr>
          <tr><td>Held-out days</td><td className="num">{fmtNum(ev.held_out_days)} · {ev.held_out_period?.join(' → ')}</td></tr>
          <tr><td>Days with unknown coverage (either sensor)</td><td className="num">{ev.unknown_share === null ? '—' : (100 * ev.unknown_share).toFixed(1) + ' %'}</td></tr>
          {ev.loglog_slope_diagnostic && <tr><td>Day-level log-log slope (diagnostic)</td><td className="num">{f(ev.loglog_slope_diagnostic.beta, 3)}</td></tr>}
          <tr><td>Valid period (both sensors)</td><td className="num">{r.valid_period?.join(' → ') ?? '—'}</td></tr>
        </tbody></table>
        <h5 className="font-semibold">Held-out daily totals ({ev.quantity === 'detections' ? 'detections' : 'occupied cells'} per day)</h5>
        <div className="overflow-x-auto"><table className="data" data-testid="hagg-heldout"><thead><tr><th>Estimate</th><th>Σ est / Σ MODIS</th><th>MAE</th><th>RMSE</th><th>MBE</th></tr></thead>
          <tbody>{keys.map((k) => <tr key={k} className={k === 'day_ratio' ? 'font-semibold' : ''}><td>{AGG_METHOD_LABEL[k] ?? k}</td><td className="num">{f(ho[k].ratio, 2)}×</td>
            <td className="num">{f(ho[k].mae)}</td><td className="num">{f(ho[k].rmse)}</td><td className="num">{f(ho[k].mbe)}</td></tr>)}</tbody></table></div>
        {ev.activity && <p className="text-[11px]">High-fire days (MODIS ≥ {f(ev.activity.threshold, 0)}): {ev.activity.high.day_ratio.n} days, ratio {f(ev.activity.high.day_ratio.ratio, 2)}× (raw VIIRS {f(ev.activity.high.raw_viirs.ratio, 2)}×).
          Other days: {ev.activity.low.day_ratio.n} days, {f(ev.activity.low.day_ratio.ratio, 2)}×.</p>}
        {ev.monthly && <p className="text-[11px]">Monthly totals ({ev.monthly.months} months with ≥ {ev.monthly.min_known_days} known days): {f(ev.monthly.day_ratio.ratio, 2)}×, MAE {f(ev.monthly.day_ratio.mae, 0)};
          {' '}{ev.monthly.share_within_level == null ? '' : `${Math.round(100 * ev.monthly.share_within_level)} % of months within 0.8–1.25×.`}</p>}
        {!r.event_model_compared && ev.quantity === 'detections' && <p className="text-[11px] text-muted">Event-model rows appear after a harmonization run.</p>}
      </div>
      <div className="space-y-2">
        <h5 className="font-semibold">Year by year: each year predicted from earlier years only</h5>
        {yrs.length ? <EChart ariaLabel="Rolling-origin ratio of estimated to observed MODIS totals by year" option={option} height={200} /> : <p className="text-muted">No year has enough earlier data.</p>}
        <details><summary className="cursor-pointer text-[11px]">Table</summary>
          <div className="overflow-x-auto"><table className="data" data-testid="hagg-years"><thead><tr><th>Year</th><th>c (earlier years)</th><th>Test days</th><th>Σ est / Σ MODIS</th><th>Raw VIIRS / MODIS</th><th>MAE</th><th>Constant MAE</th></tr></thead>
            <tbody>{yrs.map((y) => <tr key={y.year} data-within={y.within_level ? 'yes' : 'no'}><td>{y.year}</td><td className="num">{f(y.c, 4)}</td><td className="num">{y.test_days}</td>
              <td className={'num ' + (y.within_level ? '' : 'text-amber-700')}>{f(y.ratio, 2)}×</td><td className="num">{f(y.raw_ratio, 2)}×</td><td className="num">{f(y.mae)}</td><td className="num">{f(y.constant_mae)}</td></tr>)}</tbody></table></div>
          <p className="text-[11px] text-muted">{ev.rolling_origin?.rule}</p></details>
        <h5 className="font-semibold">Aggregate gate ({ev.gate.version})</h5>
        <ValidityChecks checks={ev.gate.checks} testid="hagg-checks" />
        <p className="text-[11px] text-muted">{ev.gate.label}. {ev.gate.note}</p>
      </div>
    </div>
  )
}

export function AggregateSeries({ run }: { run: string }) {
  const h = useHarm()
  const q = useApi<AggSeries>(`/api/harmonization/aggregate/series?${run}&agg=${h.seriesAgg}&quantity=${h.quantity}`)
  const d = q.data
  const option = useMemo(() => d ? aggSeriesOption(d) : null, [d])
  return (
    <div className="space-y-3" data-testid="hagg-series">
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <Seg label="Aggregation" value={h.seriesAgg} onChange={(v) => h.set({ seriesAgg: v })} options={[{ value: 'month', label: 'Monthly' }, { value: 'day', label: 'Daily' }]} />
        <Seg label="Quantity" value={h.quantity} onChange={(v) => h.set({ quantity: v })} options={QUANTITY_OPTIONS} />
      </div>
      {q.error ? <ErrorNote msg={q.error} /> : !d || !option ? <Loading label="Building the series…" /> : <>
        <div className={'rounded-lg border px-3 py-2 text-xs ' + (d.calibrated ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100' : 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100')} data-testid="hagg-series-status">
          <b>{d.gate.label}.</b> {d.calibrated ? `c = ${f(d.evaluation.c, 4)}; valid period ${d.valid_period?.join(' → ')}; held out from ${d.split}.` : 'Original MODIS and VIIRS are shown; see the failed checks in "Aggregate validation".'}
        </div>
        <EChart ariaLabel="Original MODIS and VIIRS totals and, when validated, the day-level calibrated totals with their bootstrap band" option={option} height={320} />
        <ul className="list-disc pl-5 text-[11px] text-muted">{d.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </>}
    </div>
  )
}

export function aggSeriesOption(d: AggSeries, opts: { showViirs?: boolean } = {}) {
  const split = d.split
  const splitKey = split ? (d.agg === 'month' ? split.slice(0, 7) : split) : null
  const unit = d.quantity === 'detections' ? 'detections' : 'occupied cells'
  const series: Record<string, unknown>[] = [
    { name: d.modis_label, type: 'line', showSymbol: false, connectNulls: false, itemStyle: { color: SERIES_COLOR.MODIS }, lineStyle: { width: 1.6 }, data: d.modis,
      markArea: splitKey && d.calibrated ? { silent: true, itemStyle: { color: 'rgba(16,185,129,0.08)' }, label: { show: true, position: 'insideTop', fontSize: 10, color: '#047857' },
        data: [[{ name: 'Held-out period', xAxis: splitKey }, { xAxis: d.dates[d.dates.length - 1] }]] } : undefined },
  ]
  if (opts.showViirs !== false) series.push({ name: d.viirs_label, type: 'line', showSymbol: false, connectNulls: false, itemStyle: { color: SERIES_COLOR.VIIRS_SNPP }, lineStyle: { width: 1, type: 'dashed' }, data: d.viirs })
  if (d.calibrated) {
    if (d.band) {
      series.push({ name: '95 % band (bootstrap of c)', type: 'line', stack: 'band', showSymbol: false, lineStyle: { opacity: 0 }, data: d.band.map((b) => (b ? b[0] : null)), tooltip: { show: false } })
      series.push({ name: '95 % band (bootstrap of c)', type: 'line', stack: 'band', showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(147,51,234,0.15)' },
        data: d.band.map((b) => (b ? b[1] - b[0] : null)), tooltip: { show: false } })
    }
    series.push({ name: d.calibrated_label, type: 'line', showSymbol: false, connectNulls: false, itemStyle: { color: '#9333ea' }, lineStyle: { width: 1.6 }, data: d.calibrated })
  }
  return {
    grid: { left: 56, right: 16, top: 48, bottom: 56 }, legend: { top: 0, textStyle: { fontSize: 11 }, data: series.map((s) => s.name as string).filter((n, i, a) => a.indexOf(n) === i) },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: d.agg === 'month' ? `${unit} / month (known days)` : `${unit} / day`, nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 6 }], series,
  }
}

// ------------------------------------------------------------------ 1.4: optional comparison mode in History and AOI Insights
// Off by default. Draws the experimental MODIS-equivalent line only when the day-level ratio passes the gate for exactly these
// filters and this Aqua + VIIRS pair; otherwise it says why and shows nothing estimated. Original observations are not changed.
const VIIRS_NAME: Record<string, string> = { VIIRS_SNPP: 'VIIRS S-NPP', VIIRS_N20: 'VIIRS NOAA-20', VIIRS_N21: 'VIIRS NOAA-21' }

export function ModisEquivalentComparison({ qs, available, preferred, testid }: { qs: string; available: string[]; preferred?: string; testid: string }) {
  const [on, setOn] = useState(false)
  const viirsAvail = available.filter((x) => x in VIIRS_NAME)
  const [viirs, setViirs] = useState<string | null>(null)
  const pick = viirs && viirsAvail.includes(viirs) ? viirs : preferred && viirsAvail.includes(preferred) ? preferred : viirsAvail[0] ?? null
  const [agg, setAgg] = useState<'day' | 'month'>('month')
  const [quantity, setQuantity] = useState<AggQuantity>('detections')
  const run = pick ? harmParams(qs, { viirs: pick as HState['viirs'], modis: 'Aqua', tol: pick === 'VIIRS_SNPP' ? 30 : 60, grid: 0.1, metric: 'detections', unitSet: 'matched', testFraction: 0.2 }) : null
  const q = useApi<AggSeries>(on && run ? `/api/harmonization/aggregate/series?${run}&agg=${agg}&quantity=${quantity}` : null)
  const d = q.data
  const option = useMemo(() => d ? aggSeriesOption(d) : null, [d])
  const failed = d?.gate.checks.filter((c) => !c.passed) ?? []
  return (
    <div className="space-y-2 text-xs" data-testid={testid}>
      <label className="flex items-center gap-2 font-medium">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} disabled={!pick} data-testid={`${testid}-toggle`} />
        Show the experimental MODIS-equivalent comparison (day-level ratio, Aqua and one VIIRS satellite)
      </label>
      {!pick && <p className="text-muted">No VIIRS series is imported, so there is nothing to compare.</p>}
      {on && pick && <>
        <div className="flex flex-wrap items-end gap-2">
          <Seg label="VIIRS satellite" value={pick} onChange={setViirs} options={viirsAvail.map((x) => ({ value: x, label: VIIRS_NAME[x] }))} />
          <Seg label="Aggregation" value={agg} onChange={setAgg} options={[{ value: 'month', label: 'Monthly' }, { value: 'day', label: 'Daily' }]} />
          <Seg label="Quantity" value={quantity} onChange={setQuantity} options={QUANTITY_OPTIONS} />
          {d && <GateBadge status={d.gate.status} testid={`${testid}-gate`} />}
        </div>
        {q.error ? <ErrorNote msg={q.error} /> : !d || !option ? <Loading label="Checking the gate for these filters…" /> : <>
          <div className={'rounded-lg border px-3 py-2 ' + (d.calibrated ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100' : 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100')} data-testid={`${testid}-status`}>
            {d.calibrated
              ? <><b>Experimental estimate, validated under project criteria only.</b> MODIS-equivalent = c × {VIIRS_NAME[pick]} with c = {f(d.evaluation.c, 4)}; valid period {d.valid_period?.join(' → ')}; held out from {d.split}. Days without a known state for both sensors stay empty. Not an official NASA product.</>
              : <><b>{d.gate.label}: no estimate is drawn for these filters.</b> {failed.length ? `Failed checks: ${failed.map((c) => c.label).join('; ')}.` : ''} The original MODIS and VIIRS totals are shown unchanged.</>}
          </div>
          <EChart ariaLabel="Original MODIS and VIIRS totals with, when validated, the experimental MODIS-equivalent line" option={option} height={280} />
        </>}
      </>}
    </div>
  )
}
