// Original vs calibrated time series of the Harmonization tab (added in v1.2). The calendar and history pages are unchanged.
import { useMemo } from 'react'
import { useApi } from '../api'
import { useHarm, type HSeries, type TotalsPeriod } from '../harmonization'
import { SERIES_COLOR, fmtNum } from '../util'
import { EChart, ErrorNote, Loading, Seg } from './ui'
import { ValidityChecks } from './HarmonizationParts'

function f1(v: number | null | undefined, d = 1) { return v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }) }
function pct(v: number | null | undefined) { return v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)} %` }

export default function HarmonizationSeries({ run }: { run: string }) {
  const h = useHarm()
  const q = useApi<HSeries>(`/api/harmonization/series?${run}&agg=${h.seriesAgg}&scope=${h.scope}`)
  const d = q.data
  const option = useMemo(() => {
    if (!d) return null
    const split = d.model.test_starts
    const splitKey = split ? (d.agg === 'month' ? split.slice(0, 7) : split) : null
    const series: Record<string, unknown>[] = [
      { name: d.modis_label, type: 'line', showSymbol: false, connectNulls: false, itemStyle: { color: SERIES_COLOR.MODIS }, lineStyle: { width: 1.6 }, data: d.modis,
        markArea: splitKey ? { silent: true, itemStyle: { color: 'rgba(16,185,129,0.08)' }, label: { show: true, position: 'insideTop', fontSize: 10, color: '#047857' },
          data: [[{ name: 'Held-out period', xAxis: splitKey }, { xAxis: d.dates[d.dates.length - 1] }]] } : undefined },
      { name: d.viirs_label, type: 'line', showSymbol: false, connectNulls: false, itemStyle: { color: SERIES_COLOR.VIIRS_SNPP }, lineStyle: { width: 1, type: 'dashed' }, data: d.viirs },
    ]
    if (d.calibrated) series.push({ name: d.calibrated_label, type: 'line', showSymbol: false, connectNulls: false, itemStyle: { color: '#9333ea' }, lineStyle: { width: 1.6 }, data: d.calibrated })
    return {
      grid: { left: 56, right: 16, top: 48, bottom: 56 }, legend: { top: 0, textStyle: { fontSize: 11 } }, tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: d.dates, axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', name: d.agg === 'month' ? 'detections / month (known days)' : 'detections / day', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 6 }], series,
    }
  }, [d])
  return (
    <div className="space-y-3" data-testid="hseries">
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <Seg label="Aggregation" value={h.seriesAgg} onChange={(v) => h.set({ seriesAgg: v })} options={[{ value: 'month', label: 'Monthly' }, { value: 'day', label: 'Daily' }]} />
        <Seg label="Events in estimate" value={h.scope} onChange={(v) => h.set({ scope: v })}
          options={[{ value: 'domain', label: 'In model domain only' }, { value: 'all', label: 'All VIIRS events' }]} />
      </div>
      {q.error ? <ErrorNote msg={q.error} /> : !d || !option ? <Loading label="Building the series…" /> : <>
        <div className={'rounded-lg border px-3 py-2 text-xs ' + (d.calibrated ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100' : 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100')} data-testid="hseries-status">
          <b>{d.totals_validity.label}.</b> {d.totals_validity.note}
        </div>
        <EChart ariaLabel="Original MODIS and VIIRS series and, when validated, the calibrated series" option={option} height={320} />
        <div className="grid gap-3 xl:grid-cols-2">
          <div>
            <h5 className="mb-1 text-xs font-semibold">Rules for drawing calibrated totals</h5>
            <ValidityChecks checks={d.totals_validity.checks} testid="hseries-checks" />
          </div>
          <div>
            <h5 className="mb-1 text-xs font-semibold">Daily AOI totals check ({d.scope === 'domain' ? 'model-domain events' : 'all VIIRS events'})</h5>
            {d.check ? <div className="overflow-x-auto"><TotalsTable ho={d.check.held_out} tr={d.check.training} /></div> : <p className="text-xs text-muted">Not computed: the run does not pass the unit-level rules, so no calibrated values exist.</p>}
            {d.check && <p className="mt-1 text-[11px] text-muted">{d.check.definition}</p>}
          </div>
        </div>
        <ul className="list-disc pl-5 text-[11px] text-muted">{d.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </>}
    </div>
  )
}

function TotalsTable({ ho, tr }: { ho: TotalsPeriod | null; tr: TotalsPeriod | null }) {
  const rows = [['Held out', ho], ['Training (in-sample)', tr]] as const
  return (
    <table className="data" data-testid="hseries-totals"><thead><tr><th>Period</th><th>Days</th><th>Σ MODIS</th><th>Σ VIIRS / Σ MODIS</th><th>Σ calibrated / Σ MODIS</th><th>Daily MAE unadj → cal</th><th>Constant MAE</th></tr></thead>
      <tbody>{rows.map(([k, p]) => p ? (
        <tr key={k}><td>{k}<div className="text-[10px] text-muted">{p.first} → {p.last}</div></td><td className="num">{fmtNum(p.days)}</td><td className="num">{fmtNum(p.sum_modis)}</td>
          <td className="num">{f1(p.ratio_viirs_to_modis, 2)}×</td><td className="num"><b>{f1(p.ratio_calibrated_to_modis, 2)}×</b></td>
          <td className="num">{f1(p.unadjusted.mae)} → {f1(p.calibrated.mae)} <span className="text-muted">({pct(p.improvement_vs_unadjusted.mae_pct)})</span></td>
          <td className="num">{p.constant_reference ? f1(p.constant_reference.mae) : '—'}</td></tr>
      ) : <tr key={k}><td>{k}</td><td colSpan={6} className="text-muted">no days</td></tr>)}</tbody></table>
  )
}
