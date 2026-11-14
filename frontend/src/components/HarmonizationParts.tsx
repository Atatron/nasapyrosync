// Building blocks of the Harmonization tab (added in v1.2).
import { useMemo } from 'react'
import { CLASS_LABEL } from './Harmonization'
import type { Check, HarmonizationRun } from '../harmonization'
import { SERIES_SHORT, cls, fmtNum } from '../util'
import { EChart } from './ui'

function f3(v: number | null | undefined, d = 3) { return v === null || v === undefined ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) }

export function ValidityChecks({ checks, testid }: { checks: Check[]; testid?: string }) {
  return (
    <table className="data" data-testid={testid}><thead><tr><th>Check</th><th>Result</th><th>Value</th></tr></thead>
      <tbody>{checks.map((c) => (
        <tr key={c.id} title={c.rule} data-check={c.id} data-passed={c.passed ? 'yes' : 'no'}>
          <td>{c.label}<div className="text-[10px] text-muted">{c.rule}</div></td>
          <td className={cls('whitespace-nowrap font-semibold', c.passed ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-700 dark:text-amber-400')}>{c.passed ? '✓ passed' : '✗ not met'}</td>
          <td className="text-[11px]">{c.value}</td>
        </tr>))}</tbody></table>
  )
}

export function StatusBadge({ r }: { r: HarmonizationRun | null }) {
  if (!r) return <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted">Not run yet</span>
  const ok = r.validity.status === 'passes'
  return <span data-testid="hvalidity-badge" data-status={r.validity.status}
    className={cls('rounded-full px-2 py-0.5 text-[11px] font-semibold', ok ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100' : 'bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100')}>
    {ok ? 'Passes validation rules (this configuration)' : 'Not validated for application'}</span>
}

export function PipelineCards({ r }: { r: HarmonizationRun }) {
  const s2 = r.stage2, s3 = r.stage3
  const ho = s3.evaluation?.held_out
  const cards = [
    { n: '01', t: 'Spatial', sub: 'Same grid', body: <>{r.stage1.grid_deg}° WGS84 cells, same integer rule as the map. {fmtNum(s2.events.modis)} MODIS and {fmtNum(s2.events.viirs)} {SERIES_SHORT[s2.viirs_series]} observation events after the shared filters.</> },
    { n: '02', t: 'Temporal', sub: 'Match time', body: <>{fmtNum(s2.candidate_pairs)} candidate pairs within ±{s2.tolerance_min} min → <b data-testid="hpipe-matched">{fmtNum(s2.class_counts.matched)}</b> one-to-one matches, median |Δt| {s2.dt_minutes.median === null ? '—' : `${s2.dt_minutes.median.toFixed(0)} min`}. Coverage not verified.</> },
    { n: '03', t: 'Calibration', sub: 'Regression', body: s3.status === 'ok' && s3.fit && ho ? <>ln(1+M) = {f3(s3.fit.alpha, 3)} + {f3(s3.fit.beta, 3)}·ln(1+V). Held-out MAE {f3(ho.unadjusted.mae)} → <b>{f3(ho.calibrated.mae)}</b> ({ho.improvement_vs_unadjusted.mae_pct === null ? '—' : ho.improvement_vs_unadjusted.mae_pct.toFixed(1)} %).</> : <>Not fitted: {s3.reason}</> },
  ]
  return (
    <div className="grid gap-2 md:grid-cols-3" data-testid="hpipeline">
      {cards.map((c) => (
        <div key={c.n} className="rounded-lg border border-line bg-soft/50 p-3">
          <div className="flex items-baseline gap-2"><span className="text-[11px] font-semibold text-muted">{c.n}</span><span className="text-sm font-semibold">{c.t}</span><span className="text-[11px] text-muted">{c.sub}</span></div>
          <p className="mt-1 text-xs">{c.body}</p>
        </div>))}
    </div>
  )
}

export function MatchingProcess({ r }: { r: HarmonizationRun }) {
  const s2 = r.stage2
  const hist = useMemo(() => ({
    grid: { left: 44, right: 10, top: 24, bottom: 36 }, tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', name: '|Δt| (min)', nameLocation: 'middle', nameGap: 24, data: s2.dt_minutes.histogram.map((b) => `${b.from_min}–${b.to_min}`), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: 'matched pairs', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
    series: [{ type: 'bar', itemStyle: { color: '#16a34a' }, data: s2.dt_minutes.histogram.map((b) => b.n) }],
  }), [s2])
  const funnel = [
    ['MODIS observation events', s2.events.modis],
    [`${SERIES_SHORT[s2.viirs_series]} observation events`, s2.events.viirs],
    [`Candidate pairs (same cell, |Δt| ≤ ${s2.tolerance_min} min)`, s2.candidate_pairs],
    ['Accepted one-to-one matches', s2.class_counts.matched],
  ] as const
  return (
    <div className="grid gap-3 xl:grid-cols-3">
      <div>
        <h5 className="mb-1 text-xs font-semibold">From events to matches</h5>
        <table className="data" data-testid="hfunnel"><tbody>{funnel.map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{fmtNum(v)}</td></tr>)}</tbody></table>
        <p className="mt-1 text-[11px] text-muted">{s2.matching_rule}</p>
      </div>
      <div>
        <h5 className="mb-1 text-xs font-semibold">Time difference of accepted matches</h5>
        <EChart ariaLabel="Histogram of the time difference between matched MODIS and VIIRS events" option={hist} height={200} />
        <p className="text-[11px] text-muted">Median {s2.dt_minutes.median === null ? '—' : s2.dt_minutes.median.toFixed(1)} min, maximum {s2.dt_minutes.max === null ? '—' : s2.dt_minutes.max.toFixed(1)} min. Event time = first acquisition (FIRMS granule time).</p>
      </div>
      <div>
        <h5 className="mb-1 text-xs font-semibold">Every event, classified</h5>
        <table className="data" data-testid="hclasses"><tbody>{Object.entries(s2.class_counts).map(([k, v]) => <tr key={k} title={s2.class_doc[k]}><td>{CLASS_LABEL[k] ?? k}</td><td className="num">{fmtNum(v)}</td></tr>)}</tbody></table>
        <p className="mt-1 text-[11px] text-muted">{s2.coverage_verification.note}</p>
        {s2.warning && <p className="mt-1 text-[11px] text-amber-700">{s2.warning}</p>}
      </div>
    </div>
  )
}

export function ErrorComparison({ r }: { r: HarmonizationRun }) {
  const ev = r.stage3.evaluation
  if (!ev) return null
  const ho = ev.held_out
  const med = ho.training_median_reference
  const unit = r.config.metric === 'detections' ? 'detections' : 'MW'
  const rows: [string, { mae: number; rmse: number; mbe: number } | undefined, string][] = [
    ['Unadjusted VIIRS (M̂ = V)', ho.unadjusted, 'raw VIIRS value used as MODIS-scale value'],
    ['Calibrated (this model)', ho.calibrated, 'α + β ln(1+V), back-transformed'],
    ['Constant: training MODIS mean', ho.training_mean_reference, 'ignores VIIRS entirely'],
    ['Constant: training MODIS median', med, 'best constant for MAE; ignores VIIRS'],
  ]
  return (
    <table className="data" data-testid="herrors-table"><thead><tr><th>Held-out estimate ({unit})</th><th>MAE</th><th>RMSE</th><th>MBE</th></tr></thead>
      <tbody>{rows.map(([k, e, note]) => e && (
        <tr key={k} className={k.startsWith('Calibrated') ? 'font-semibold' : k.startsWith('Constant') ? 'text-muted' : ''}><td>{k}<div className="text-[10px] font-normal text-muted">{note}</div></td>
          <td className="num">{f3(e.mae)}</td><td className="num">{f3(e.rmse)}</td><td className="num">{f3(e.mbe)}</td></tr>))}</tbody></table>
  )
}
