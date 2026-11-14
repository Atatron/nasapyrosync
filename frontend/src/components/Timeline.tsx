import { useEffect, useMemo, useRef, useState } from 'react'
import { prefetch, type Daily, type Elevated } from '../api'
import { frameUrl, useFilterQS } from '../hooks'
import { frameWindow, useApp, type FrameMode } from '../state'
import { METRIC_INFO, SERIES_COLOR, SERIES_SHORT, addDays, diffDays, fmtDate, fmtNum } from '../util'
import { EChart, Icon, Seg } from './ui'

const SPEEDS = [{ v: 1200, l: '0.5×' }, { v: 650, l: '1×' }, { v: 320, l: '2×' }, { v: 150, l: '4×' }]

export default function Timeline({ daily, elevated, compact = false }: { daily: Daily | null; elevated?: Elevated | null; compact?: boolean }) {
  const s = useApp()
  const qs = useFilterQS()
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(650)
  const n = diffDays(s.start, s.end) + 1
  const idx = Math.max(0, Math.min(n - 1, diffDays(s.start, s.date)))
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  const ser = daily?.series[s.series]

  // playback that never runs ahead of what is displayed
  const lastTick = useRef(0)
  useEffect(() => {
    if (!playing) return
    const id = window.setInterval(() => {
      const st = useApp.getState()
      if (st.mapBusy || st.imageryBusy) return
      if (Date.now() - lastTick.current < speed) return
      lastTick.current = Date.now()
      if (st.date >= st.end) { setPlaying(false); return }
      const next = addDays(st.date, 1)
      st.setDate(next)
      const after = addDays(next, 1)
      if (after <= st.end) prefetch(frameUrl(qs, after, st.frameMode)) // limited adjacent-date prefetch
    }, 60)
    return () => window.clearInterval(id)
  }, [playing, speed, qs])

  const option = useMemo(() => {
    if (!daily || !ser) return {}
    const metric = s.metric
    const vals = daily.dates.map((_, i) => {
      const st = ser.status[i]
      const known = st === 'detections' || st === 'zero_reported'
      const v = (ser as unknown as Record<string, (number | null)[]>)[metric]?.[i] ?? 0
      return { value: known ? v ?? 0 : 0, itemStyle: { color: known ? SERIES_COLOR[s.series] : 'rgba(148,163,184,0.5)' } }
    })
    const areas: unknown[] = []
    areas.push([{ xAxis: w0, itemStyle: { color: 'rgba(15,29,58,0.10)' } }, { xAxis: w1 }])
    for (const p of elevated?.periods ?? []) areas.push([{ xAxis: p.start, itemStyle: { color: 'rgba(185,28,28,0.10)', borderColor: 'rgba(185,28,28,0.5)', borderWidth: 1 } }, { xAxis: p.end }])
    return {
      grid: { left: 44, right: 12, top: 10, bottom: 22 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0].dataIndex
          const d = daily.dates[i]
          const lines = Object.entries(daily.series).filter(([k]) => k !== 'UNION' || metric === 'cells').map(([k, v]) => `${SERIES_SHORT[k]}: ${fmtNum((v as unknown as Record<string, number[]>)[metric]?.[i] ?? 0, 1)} <span style="color:#888">(${v.status[i]?.replace('_', ' ')})</span>`)
          return `<b>${d} (UTC day)</b><br/>${METRIC_INFO[metric].label}<br/>${lines.join('<br/>')}`
        },
      },
      xAxis: { type: 'category', data: daily.dates, axisLabel: { fontSize: 10, color: '#64748b', hideOverlap: true, formatter: (v: string) => (v.endsWith('-01') && ['01', '04', '07', '10'].includes(v.slice(5, 7))) ? v.slice(0, 7) : '', interval: 0 }, axisTick: { show: false } },
      yAxis: { type: 'value', axisLabel: { fontSize: 10, color: '#64748b' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } } },
      series: [{ type: 'bar', data: vals, barCategoryGap: '10%', large: false, markArea: { silent: true, data: areas },
        markLine: { silent: true, symbol: 'none', data: [{ xAxis: s.date }], lineStyle: { color: '#0f1d3a', width: 1.5 }, label: { show: false } } }],
    }
  }, [daily, ser, s.metric, s.series, s.date, w0, w1, elevated])

  const label = s.frameMode === 1 ? `Daily frame ${s.date} UTC` : `Trailing ${s.frameMode} days ${w0} → ${w1} UTC`
  return (
    <section aria-label="Timeline" className="panel p-3" data-testid="timeline">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <button className="btn px-2" aria-label="Previous day" onClick={() => s.setDate(addDays(s.date, -1))} disabled={s.date <= s.start}><Icon name="prev" /></button>
          <button className="btn btn-primary px-2.5" aria-label={playing ? 'Pause playback' : 'Play through days'} onClick={() => setPlaying((p) => !p)}><Icon name={playing ? 'pause' : 'play'} /></button>
          <button className="btn px-2" aria-label="Next day" onClick={() => s.setDate(addDays(s.date, 1))} disabled={s.date >= s.end}><Icon name="next" /></button>
        </div>
        <label className="flex items-center gap-1 text-xs"><span className="sr-only">Selected date (UTC)</span>
          <input type="date" className="field" data-testid="date-input" value={s.date} min={s.start} max={s.end} onChange={(e) => e.target.value && s.setDate(e.target.value)} />
        </label>
        <select className="field" aria-label="Playback speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((x) => <option key={x.v} value={x.v}>{x.l}</option>)}
        </select>
        <Seg<FrameMode> label="Map frame window" value={s.frameMode} onChange={(v) => s.set({ frameMode: v })}
          options={[{ value: 1, label: 'Daily' }, { value: 7, label: '7-day' }, { value: 30, label: '30-day' }]} />
        <div className="ml-auto rounded-md bg-soft px-2 py-1 text-xs font-medium" data-testid="active-window" aria-live="polite">
          {label} · {fmtDate(s.date)}
        </div>
      </div>
      {!compact && (daily && ser ? <EChart ariaLabel={`Daily histogram of ${METRIC_INFO[s.metric].label} for ${SERIES_SHORT[s.series]}; click a bar to select that day`} option={option} height={92}
        onClick={(p) => daily && s.setDate(daily.dates[p.dataIndex])} /> : <div className="h-[92px]" />)}
      <input type="range" className="mt-1 w-full accent-orange-600" min={0} max={n - 1} value={idx} aria-label="Timeline scrubber" data-testid="scrubber"
        aria-valuetext={s.date} onChange={(e) => s.setDate(addDays(s.start, Number(e.target.value)))} />
      <div className="flex flex-wrap justify-between gap-x-2 text-[10px] text-muted sm:flex-nowrap">
        <span>{s.start}</span>
        <span className="max-sm:order-last max-sm:w-full">Histogram: {METRIC_INFO[s.metric].label}, {SERIES_SHORT[s.series]}; grey = unknown coverage; shaded = map window{elevated?.periods.length ? '; red bands = elevated periods' : ''}. Analysis range {s.start} → {s.end} (UTC days)</span>
        <span>{s.end}</span>
      </div>
    </section>
  )
}
