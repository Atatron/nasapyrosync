import type { Elevated as El, Period } from '../api'
import { useApp, type ElevatedMode } from '../state'
import { METRIC_INFO, SERIES_SHORT, diffDays, fmtDate, fmtNum } from '../util'
import { Empty, ErrorNote, Icon, Info, Loading } from './ui'

export function selectPeriod(p: Period) {
  const s = useApp.getState()
  const len = diffDays(p.start, p.end) + 1
  const mode = len <= 1 ? 1 : len <= 7 ? 7 : 30
  // documented behavior: map shows a trailing window ending on the period's last day
  s.set({ frameMode: mode as 1 | 7 | 30 })
  s.setDate(p.end)
}

export function ElevatedSettings() {
  const s = useApp()
  return (
    <div className="flex flex-wrap items-end gap-3 text-xs">
      <label className="flex flex-col gap-1"><span className="label">Threshold mode</span>
        <select className="field" value={s.elevatedMode} onChange={(e) => s.set({ elevatedMode: e.target.value as ElevatedMode })}>
          <option value="range_percentile">Within-range percentile (descriptive)</option>
          <option value="fixed">User-defined activity threshold</option>
          <option value="baseline">Historical seasonal baseline (needs ≥5 prior years)</option>
        </select>
      </label>
      {s.elevatedMode === 'range_percentile' && <label className="flex flex-col gap-1"><span className="label">Percentile</span>
        <input type="number" className="field w-20" min={50} max={99.9} step={1} value={s.percentile} onChange={(e) => s.set({ percentile: Math.min(99.9, Math.max(50, Number(e.target.value) || 90)) })} /></label>}
      {s.elevatedMode === 'fixed' && <label className="flex flex-col gap-1"><span className="label">Threshold ({METRIC_INFO[s.metric].unit})</span>
        <input type="number" className="field w-24" min={0} step="any" value={s.threshold ?? ''} placeholder="enter value" onChange={(e) => s.set({ threshold: e.target.value === '' ? null : Number(e.target.value) })} /></label>}
      <label className="flex flex-col gap-1"><span className="label">Min. consecutive days</span>
        <input type="number" className="field w-20" min={1} max={60} value={s.minDays} onChange={(e) => s.set({ minDays: Math.min(60, Math.max(1, Number(e.target.value) || 3)) })} /></label>
      <label className="flex flex-col gap-1"><span className="label">Min. activity</span>
        <input type="number" className="field w-20" min={0} step="any" value={s.minActivity} onChange={(e) => s.set({ minActivity: Math.max(0, Number(e.target.value) || 0) })} /></label>
    </div>
  )
}

export function ElevatedList({ q, compact = false }: { q: { data: El | null; loading: boolean; error: string | null }; compact?: boolean }) {
  const s = useApp()
  if (q.error) return <ErrorNote msg={q.error} />
  if (!q.data) return <Loading label="Evaluating elevated-period rule…" />
  const d = q.data
  return (
    <div className="space-y-2" data-testid="elevated-list">
      <p className="text-[11px] leading-snug text-muted">
        <b className="text-ink">{d.rule.threshold.label ?? 'Rule'}</b>: {d.rule.threshold.description ?? ''} Runs need ≥{d.rule.min_consecutive_days} consecutive UTC days and ≥{d.rule.min_activity} {METRIC_INFO[s.metric].unit}. {d.rule.status}
        <Info>{d.rule.missing_days} {d.disclaimer}</Info>
      </p>
      {d.unavailable ? <Empty title="Not available for this configuration">{d.unavailable}</Empty>
        : d.periods.length === 0 ? <Empty title="No period qualifies">No run of ≥{d.rule.min_consecutive_days} consecutive days exceeds the threshold for {SERIES_SHORT[s.series]} in this AOI and range. Adjust the rule, sensor, or range to explore.</Empty>
          : (
            <ol className="space-y-2">
              {(compact ? d.periods.slice(0, 6) : d.periods).map((p) => {
                const active = s.date >= p.start && s.date <= p.end
                return (
                  <li key={p.start}>
                    <button className={`w-full rounded-lg border p-2.5 text-left text-xs hover:bg-soft ${active ? 'border-flag bg-red-50 dark:bg-red-950/40' : 'border-line'}`} onClick={() => selectPeriod(p)}
                      aria-label={`Elevated observed activity ${p.start} to ${p.end}; select to show on map and timeline`}>
                      <div className="flex items-center gap-2 font-semibold"><Icon name="flag" className="h-3.5 w-3.5 text-flag" /><span>{fmtDate(p.start)} – {fmtDate(p.end)}</span><span className="chip bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100">{p.duration_days} days</span></div>
                      <div className="mt-1 text-muted">Peak {fmtNum(p.peak, 1)} {p.unit} on {p.peak_date} · {p.series_label}</div>
                      {!compact && <p className="mt-1 leading-snug">{p.reason}</p>}
                      {!compact && <p className="mt-1 text-muted">Daily values: {p.values.map((v) => fmtNum(v, 1)).join(', ')}</p>}
                      {p.coverage_notes.map((n) => <p key={n} className="mt-1 text-amber-800 dark:text-amber-300">⚠ {n}</p>)}
                    </button>
                  </li>
                )
              })}
              {compact && d.periods.length > 6 && <li className="text-[11px] text-muted">+{d.periods.length - 6} more in Historical Patterns.</li>}
            </ol>
          )}
      <p className="text-[10px] text-muted">{d.disclaimer} Excluded types: {d.filter_disclosure.types_excluded.join(', ') || 'none'}.</p>
    </div>
  )
}
