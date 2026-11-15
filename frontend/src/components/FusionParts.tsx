// Multi-sensor historical fusion views (added in 1.5): status banner, validation panel and the long-record chart.
// Original observations are never replaced; the fused series is labelled with its validation status everywhere.
import { useMemo, useState } from 'react'
import { useApi } from '../api'
import { useFilterQS } from '../hooks'
import { useApp } from '../state'
import { FUSION_STATUS_TEXT, PLATFORM_SHORT, fusionStatusClass, type FusionRegions, type FusionReport, type FusionSeries, type FusionStatus } from '../fusion'
import { MON3, SERIES_COLOR, cls, fmtNum } from '../util'
import { EChart, ErrorNote, Loading, Seg } from './ui'
import { ValidityChecks } from './HarmonizationParts'

function f2(v: number | null | undefined, d = 2) { return v === null || v === undefined ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) }

export function FusionStatusPill({ status, testid }: { status: FusionStatus | undefined; testid?: string }) {
  return <span data-testid={testid} data-status={status ?? 'loading'} className={cls('rounded-full px-2 py-0.5 text-[11px] font-semibold', fusionStatusClass(status))}>
    {status ? FUSION_STATUS_TEXT[status] : 'Checking validation…'}</span>
}

/** Shown wherever the harmonized series is the selected series (calendar, history, Explore). */
export function FusionBanner({ force = false }: { force?: boolean } = {}) {
  const s = useApp()
  const qs = useFilterQS()
  const on = force || s.series === 'FUSED'
  const q = useApi<FusionSeries>(on ? `/api/fusion/series?${qs}&agg=year` : null)
  if (!on) return null
  const d = q.data
  return (
    <div className="panel flex flex-wrap items-center gap-2 px-3 py-2 text-xs" data-testid="fusion-banner" role="note">
      <b>Harmonized activity</b>
      <span className="text-muted">= every eligible satellite calibrated to the MODIS Aqua scale, then averaged (never summed). Unit: MODIS-Aqua-equivalent detections per day.</span>
      {q.error ? <span className="text-red-700">{q.error}</span> : !d ? <span className="text-muted">Loading…</span> : <>
        <FusionStatusPill status={d.validation_status} testid="fusion-banner-status" />
        <span>Sensors: Aqua (reference){d.eligible.map((p) => `, ${PLATFORM_SHORT[p]} ×${f2(d.coefficients[p], 4)}`).join('')}</span>
        {d.coefficient_source.aoi !== s.aoi && <span className="text-amber-700">Coefficients: {d.coefficient_source.label}</span>}
      </>}
      <button className="ml-auto text-accent underline" onClick={() => s.set({ page: 'harmonization' })}>How it was validated</button>
    </div>
  )
}

export function fusionChartOption(d: FusionSeries, showAqua = true) {
  return {
    grid: { left: 52, right: 16, top: 30, bottom: 48 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number | null) => (v === null || v === undefined ? 'unknown' : fmtNum(v, 1)) },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 6 }],
    xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: 'MODIS-Aqua-eq. detections', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
    series: [
      { name: 'Harmonized (all eligible sensors)', type: 'line', data: d.fused, symbol: 'none', connectNulls: false, lineStyle: { width: 2 }, color: SERIES_COLOR.FUSED },
      ...(showAqua ? [{ name: 'MODIS Aqua observed (reference)', type: 'line', data: d.aqua_observed, symbol: 'none', connectNulls: false, lineStyle: { width: 1, type: 'dashed' }, color: SERIES_COLOR.MODIS }] : []),
    ],
  }
}

/** The fused record over the whole archive (or the selected range), with sensor contributions per period. */
export function FusionHistory({ range = 'record' }: { range?: 'record' | 'selected' }) {
  const s = useApp()
  const qs = useFilterQS()
  const [agg, setAgg] = useState<'month' | 'year'>('month')
  const p = useMemo(() => {
    const x = new URLSearchParams(qs)
    if (range === 'record' && s.dataRange) { x.set('start', s.dataRange[0]); x.set('end', s.dataRange[1]) }
    x.set('agg', agg)
    return x.toString()
  }, [qs, range, s.dataRange, agg])
  const q = useApi<FusionSeries>(`/api/fusion/series?${p}`)
  const d = q.data
  const opt = useMemo(() => (d ? fusionChartOption(d) : {}), [d])
  if (q.error) return <ErrorNote msg={q.error} />
  if (!d) return <Loading label="Building the harmonized record…" />
  const phases: { label: string; plats: string }[] = []
  d.contributors.forEach((c, i) => { const k = c.join('+'); if (!phases.length || phases[phases.length - 1].plats !== k) phases.push({ label: d.dates[i], plats: k }) })
  return (
    <div data-testid="fusion-history">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
        <Seg label="Aggregation" value={agg} onChange={setAgg} options={[{ value: 'month', label: 'Monthly' }, { value: 'year', label: 'Yearly' }]} />
        <FusionStatusPill status={d.validation_status} testid="fusion-history-status" />
      </div>
      <EChart option={opt} height={260} ariaLabel="Harmonized multi-sensor activity and observed MODIS Aqua over time" />
      <div className="mt-1 text-[11px] text-muted">Contributing sensors: {phases.map((x) => `${x.label}: ${x.plats ? x.plats.split('+').map((p) => PLATFORM_SHORT[p] ?? p).join(', ') : 'none (unknown)'}`).join(' → ')}.
        Sums use only days with a known sensor; periods with no eligible sensor are empty, not zero.</div>
    </div>
  )
}

/** Full validation of the fusion for the current AOI and filters (Harmonization diagnostics). */
export function FusionPanel() {
  const qs = useFilterQS()
  const q = useApi<FusionReport>(`/api/fusion?${qs}`)
  const [grid, setGrid] = useState(1)
  const rq = useApi<FusionRegions>(`/api/fusion/regions?${qs}&grid_deg=${grid}&min_days=20`)
  const r = q.data
  if (q.error) return <ErrorNote msg={q.error} />
  if (!r) return <Loading label="Fitting the pairwise ratios and testing the fusion on later years…" />
  const v = r.validation
  const ho = v.held_out
  const yrs = v.rolling_origin?.years ?? []
  const rollOpt = {
    grid: { left: 40, right: 10, top: 16, bottom: 24 }, tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: yrs.map((y) => String(y.year)), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', min: 0, max: 2, axisLabel: { fontSize: 10 } },
    series: [{ type: 'bar', data: yrs.map((y) => ({ value: y.ratio === null ? null : Number(y.ratio.toFixed(3)), itemStyle: { color: y.within_level ? '#059669' : '#d97706' } })),
      markArea: { silent: true, itemStyle: { color: 'rgba(16,185,129,0.08)' }, data: [[{ yAxis: 0.8 }, { yAxis: 1.25 }]] },
      markLine: { silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: '#71717a' }, data: [{ yAxis: 1 }] } }],
  }
  return (
    <div className="space-y-3 text-xs" data-testid="fusion-panel">
      <div className="flex flex-wrap items-center gap-2">
        <FusionStatusPill status={r.gate.status} testid="fusion-gate" />
        <span>{r.gate.label}.</span>
        {r.effective.source.aoi !== r.aoi && <span className="text-amber-700">Applied coefficients: {r.effective.source.label}.</span>}
        <a className="btn ml-auto" href={`/api/export/fusion.zip?${qs}`} download data-testid="fusion-zip">Fusion report (ZIP)</a>
      </div>
      <p className="text-muted">{r.reference_doc}</p>
      <p><b>Formula.</b> {r.equation}. Eligible: {r.eligibility_rule}.</p>
      <div className="overflow-x-auto">
        <div className="scroll-box"><table className="data" data-testid="fusion-pairs"><thead><tr><th>Platform</th><th>Record</th><th>c vs Aqua (95 %)</th><th>Overlap days</th><th>Held-out Σ/Σ</th><th>Rolling years in band</th><th>Pair gate</th><th>Used</th></tr></thead>
          <tbody>
            <tr><td>Aqua (MODIS) · reference</td><td className="num">{r.platform_records.Aqua?.join(' → ') ?? '—'}</td><td className="num">1 (by definition)</td><td>—</td><td>—</td><td>—</td><td>—</td><td>yes</td></tr>
            {Object.values(r.pairs).map((p) => {
              const ry = p.rolling_years ?? []
              return (
                <tr key={p.platform} data-platform={p.platform} data-used={r.effective.eligible.includes(p.platform) ? 'yes' : 'no'}>
                  <td>{p.platform_label}</td><td className="num">{r.platform_records[p.platform]?.join(' → ') ?? 'not imported'}</td>
                  <td className="num">{f2(p.c, 4)}{p.bootstrap ? ` (${f2(p.bootstrap.c_lo, 4)}–${f2(p.bootstrap.c_hi, 4)})` : ''}</td>
                  <td className="num">{fmtNum(p.overlap_days ?? 0)}</td><td className="num">{f2(p.held_out?.day_ratio.ratio)}</td>
                  <td className="num">{ry.length ? `${ry.filter((y) => y.within_level).length} of ${ry.length}` : '—'}</td>
                  <td>{p.gate.status === 'passes' ? '✓ passes' : p.gate.status === 'insufficient' ? 'insufficient' : '✗ ' + (p.gate.checks.filter((c) => !c.passed).map((c) => c.label.toLowerCase()).join('; ') || 'not validated')}</td>
                  <td>{r.effective.eligible.includes(p.platform) ? 'yes' : 'no'}</td>
                </tr>)
            })}
          </tbody></table></div>
      </div>
      <p className="text-muted">{v.design}</p>
      {v.status !== 'ok' ? <p className="text-amber-700" data-testid="fusion-insufficient">Not tested: {v.reason}</p> : <>
        <div className="grid gap-3 xl:grid-cols-2">
          <div>
            <h5 className="mb-1 font-semibold">Held-out daily totals ({fmtNum(v.held_out_days)} days, {v.held_out_period?.join(' → ')}; split {v.split})</h5>
            <div className="scroll-box"><table className="data" data-testid="fusion-heldout"><thead><tr><th>Method</th><th>Σ est / Σ Aqua</th><th>MAE</th><th>RMSE</th><th>Bias</th></tr></thead>
              <tbody>{ho && ([['fusion_leave_reference_out', 'Fusion without Aqua (calibrated average)'], ['raw_unadjusted_mean', 'Uncalibrated mean of raw counts'], ['constant_train_mean', 'Constant (training mean)']] as const).map(([k, l]) => (
                <tr key={k}><td>{l}</td><td className="num">{f2(ho[k].ratio)}</td><td className="num">{f2(ho[k].mae, 1)}</td><td className="num">{f2(ho[k].rmse, 1)}</td><td className="num">{f2(ho[k].mbe, 1)}</td></tr>))}</tbody></table></div>
            {v.single_sensor_comparison && Object.keys(v.single_sensor_comparison).length > 0 && <table className="data mt-2"><thead><tr><th>Same days</th><th>Single-sensor ratio (1.4) Σ/Σ · MAE</th><th>Fusion Σ/Σ · MAE</th></tr></thead>
              <tbody>{Object.entries(v.single_sensor_comparison).map(([p, c]) => <tr key={p}><td>{PLATFORM_SHORT[p]} ({c.days} d)</td><td className="num">{f2(c.single_ratio.ratio)} · {f2(c.single_ratio.mae, 1)}</td><td className="num">{f2(c.fusion.ratio)} · {f2(c.fusion.mae, 1)}</td></tr>)}</tbody></table>}
            <p className="mt-1 text-muted">High-fire days (Aqua ≥ {f2(v.activity?.threshold, 0)}): {v.activity?.high.fusion_leave_reference_out.n} days, {f2(v.activity?.high.fusion_leave_reference_out.ratio)}×.
              Held-out months within 0.8–1.25×: {v.monthly?.share_within_level === null || v.monthly?.share_within_level === undefined ? '—' : `${Math.round(v.monthly.share_within_level * 100)} %`} of {v.monthly?.months.length}.
              Seasonal (rolling-origin, by calendar month): {v.seasonal?.months.map((m) => `${MON3[m.month - 1]} ${f2(m.ratio)}`).join(', ')}.</p>
          </div>
          <div>
            <h5 className="mb-1 font-semibold">Rolling-origin years (predicted without Aqua, from earlier years only)</h5>
            <EChart option={rollOpt} height={170} ariaLabel="Ratio of fused to Aqua totals per year, predicted from earlier years" />
            <p className="text-muted">{v.rolling_origin?.rule} Green band: 0.8–1.25×.</p>
            <h5 className="mb-1 mt-2 font-semibold">Sensor transitions</h5>
            <table className="data" data-testid="fusion-transitions"><thead><tr><th>Platform joins</th><th>Step without Aqua</th><th>Step with Aqua</th></tr></thead>
              <tbody>{v.transitions?.platforms.map((t) => <tr key={t.platform}><td>{PLATFORM_SHORT[t.platform]} {t.joins}</td>
                <td className="num">{t.leave_reference_out ? `${f2(t.leave_reference_out.step)}× (${f2(t.leave_reference_out.before)} → ${f2(t.leave_reference_out.after)})` : 'not testable'}</td>
                <td className="num">{t.fused ? `${f2(t.fused.step)}×` : '—'}</td></tr>)}</tbody></table>
            <p className="text-muted">{v.transitions?.rule}</p>
            {v.missing && <p className="text-muted">Missing data: {fmtNum(v.missing.no_known_platform)} of {fmtNum(v.missing.days)} record days have no known sensor; Aqua unknown on {fmtNum(v.missing.aqua_unknown)} days. Unknown days are never read as zero.</p>}
          </div>
        </div>
      </>}
      <div>
        <h5 className="mb-1 font-semibold">Gate checks (pyrosync-fusion-gate-1.0)</h5>
        <ValidityChecks checks={r.gate.checks} testid="fusion-checks" />
        {r.gate.note && <p className="mt-1 text-muted">{r.gate.note}</p>}
      </div>
      <div>
        <div className="mb-1 flex flex-wrap items-center gap-2"><h5 className="font-semibold">Regional check of the held-out period</h5>
          <Seg label="Region size" value={grid} onChange={setGrid} options={[0.5, 1, 2].map((g) => ({ value: g, label: `${g}°` }))} /></div>
        {rq.error ? <ErrorNote msg={rq.error} /> : !rq.data ? <Loading /> : !rq.data.available ? <p className="text-muted">{rq.data.reason}</p> : <p data-testid="fusion-regions">
          <b className="num" data-testid="fusion-regions-within">{rq.data.summary!.within}</b> region cells within 0.8–1.25×, <b className="num">{rq.data.summary!.outside}</b> outside,
          {' '}{rq.data.summary!.too_few} with fewer than {rq.data.min_days} active days{rq.data.summary!.share_within !== null ? ` (share within: ${Math.round(rq.data.summary!.share_within * 100)} %)` : ''}. {rq.data.definition}</p>}
      </div>
      <div>
        <h5 className="mb-1 font-semibold">Harmonized record for this area</h5>
        <FusionHistory range="record" />
      </div>
      <p className="text-muted">{r.coverage.note}</p>
    </div>
  )
}
