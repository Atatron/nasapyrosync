import { useMemo, useRef, useState } from 'react'
import { useApi, type Daily, type Weeks } from '../api'
import { useDaily, useElevated, useSeriesParams } from '../hooks'
import { useApp } from '../state'
import { MON3, MONTHS, METRIC_INFO, RAMP, SERIES_COLOR, SERIES_SHORT, STATUS_LABEL, addDays, cls, daysInMonth, fmtDate, fmtNum, isoWeekday, rampBins, rampColor } from '../util'
import { Empty, ErrorNote, Icon, Loading, Panel, Seg, StatusSwatch } from '../components/ui'
import Timeline from '../components/Timeline'
import { FusionBanner, FusionHistory } from '../components/FusionParts'

type DayInfo = { date: string; inRange: boolean; value: number | null; status: string; i: number }

function useDayLookup(daily: Daily | null, series: string, metric: string) {
  return useMemo(() => {
    const m = new Map<string, { v: number | null; st: string; i: number }>()
    if (!daily) return m
    const ser = daily.series[series]
    if (!ser) return m
    daily.dates.forEach((d, i) => {
      const st = ser.status[i]
      const known = st === 'detections' || st === 'zero_reported'
      const raw = (ser as unknown as Record<string, (number | null)[]>)[metric][i]
      m.set(d, { v: known ? raw ?? 0 : null, st, i })
    })
    return m
  }, [daily, series, metric])
}

function cellStyle(info: DayInfo, max: number, color: string): { className: string; style?: React.CSSProperties } {
  if (!info.inRange) return { className: 'border border-dashed border-line text-muted/60' }
  if (info.status === 'unknown' || info.status === 'sensor_unavailable') return { className: 'hatch border border-slate-300 text-muted' }
  if (info.status === 'outside_range') return { className: 'border border-dashed border-line text-muted/60' }
  if (!info.value) return { className: 'border border-line bg-soft text-muted' }
  const bg = rampColor(info.value, max)
  const dark = RAMP.indexOf(bg) >= 5
  return { className: cls('border border-transparent', dark ? 'text-white' : 'text-slate-900'), style: { background: bg, boxShadow: `inset 0 -3px 0 ${color}22` } }
}

export default function CalendarPage() {
  const s = useApp()
  const daily = useDaily()
  const el = useElevated()
  const look = useDayLookup(daily.data, s.series, s.metric)
  const [y, m] = s.date.split('-').map(Number)
  const [focus, setFocus] = useState<string>(s.date)
  const gridRef = useRef<HTMLDivElement>(null)
  const flagged = useMemo(() => {
    const set = new Map<string, string>()
    for (const p of el.data?.periods ?? []) {
      let d = p.start
      while (d <= p.end) { set.set(d, p.reason); d = addDays(d, 1) }
    }
    return set
  }, [el.data])

  const rangeMax = useMemo(() => Math.max(0, ...Array.from(look.values()).map((x) => x.v ?? 0)), [look])
  const monthMax = useMemo(() => {
    let mx = 0
    for (let d = 1; d <= daysInMonth(y, m); d++) mx = Math.max(mx, look.get(`${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`)?.v ?? 0)
    return mx
  }, [look, y, m])
  const max = s.calendarScale === 'month' ? monthMax : rangeMax

  const info = (d: string): DayInfo => {
    const x = look.get(d)
    const inRange = d >= s.start && d <= s.end
    return { date: d, inRange, value: x?.v ?? null, status: inRange ? x?.st ?? 'outside_range' : 'outside_range', i: x?.i ?? -1 }
  }

  const goMonth = (dy: number, dm: number) => {
    let ny = y + dy, nm = m + dm
    if (nm < 1) { nm = 12; ny-- } if (nm > 12) { nm = 1; ny++ }
    const nd = `${ny}-${String(nm).padStart(2, '0')}-${String(Math.min(Number(s.date.slice(8)), daysInMonth(ny, nm))).padStart(2, '0')}`
    s.setDate(nd)
    setFocus(nd < s.start ? s.start : nd > s.end ? s.end : nd)
  }

  const first = `${y}-${String(m).padStart(2, '0')}-01`
  const lead = isoWeekday(first) - 1
  const nd = daysInMonth(y, m)
  const cells: (string | null)[] = [...Array(lead).fill(null), ...Array.from({ length: nd }, (_, i) => `${y}-${String(m).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}`)]
  while (cells.length % 7) cells.push(null)

  const onKey = (e: React.KeyboardEvent, d: string) => {
    const step: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
    if (e.key in step) {
      e.preventDefault()
      const n = addDays(d, step[e.key])
      setFocus(n)
      if (n.slice(0, 7) !== d.slice(0, 7)) s.set({ date: n < s.start ? s.start : n > s.end ? s.end : n })
      requestAnimationFrame(() => gridRef.current?.querySelector<HTMLElement>(`[data-date="${n}"]`)?.focus())
    } else if (e.key === 'PageUp' || e.key === 'PageDown') { e.preventDefault(); goMonth(0, e.key === 'PageUp' ? -1 : 1) }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); s.setDate(d) }
  }

  const years = s.dataRange ? Array.from({ length: Number(s.dataRange[1].slice(0, 4)) - Number(s.dataRange[0].slice(0, 4)) + 1 }, (_, i) => Number(s.dataRange![0].slice(0, 4)) + i) : [y]
  const sel = info(focus)
  const ser = daily.data?.series[s.series]

  return (
    <div className="flex flex-col gap-3 p-3">
      <FusionBanner />
      <Timeline daily={daily.data} elevated={el.data} compact />
      {daily.error && <ErrorNote msg={daily.error} />}
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Panel title={`Burning-activity calendar · ${SERIES_SHORT[s.series]}`} id="cal-title"
          info={<>Each day is one UTC calendar day. Color = {METRIC_INFO[s.metric].label} ({METRIC_INFO[s.metric].unit}). Hatched = unknown coverage (not zero). Grey = zero detections reported inside an imported interval. Dashed = outside the analysis/imported range. Clicking a day selects it on the shared timeline and map.</>}
          actions={<>
            <button className="btn px-2" aria-label="Previous month" onClick={() => goMonth(0, -1)}><Icon name="prev" /></button>
            <select className="field" aria-label="Month" value={m} onChange={(e) => goMonth(0, Number(e.target.value) - m)}>{MONTHS.map((n, i) => <option key={n} value={i + 1}>{n}</option>)}</select>
            <select className="field" aria-label="Year" value={y} onChange={(e) => goMonth(Number(e.target.value) - y, 0)}>{years.map((yy) => <option key={yy} value={yy}>{yy}</option>)}</select>
            <button className="btn px-2" aria-label="Next month" onClick={() => goMonth(0, 1)}><Icon name="next" /></button>
            <Seg label="Color scale" value={s.calendarScale} onChange={(v) => s.set({ calendarScale: v })} options={[{ value: 'range', label: 'Stable scale', title: 'Same color domain for the whole analysis range' }, { value: 'month', label: 'Rescale per month', title: 'Colors rescaled to this month only' }]} />
          </>}>
          {!daily.data ? <Loading /> : !ser ? <Empty title="Sensor not selected">Enable the sensor in Filters or pick another sensor.</Empty> : (
            <>
              {s.calendarScale === 'month' && <p className="mb-2 rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-900 dark:bg-amber-950 dark:text-amber-100">Automatic rescaling is ON: colors are relative to this month's maximum ({fmtNum(monthMax, 1)}); similar colors in different months are not equal values.</p>}
              <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-semibold text-muted" aria-hidden>{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => <div key={d}>{d}</div>)}</div>
              <div ref={gridRef} role="grid" aria-labelledby="cal-title" className="mt-1 grid grid-cols-7 gap-1" data-testid="calendar-grid">
                {cells.map((d, k) => {
                  if (!d) return <div key={`e${k}`} aria-hidden />
                  const di = info(d)
                  const st = cellStyle(di, max, SERIES_COLOR[s.series])
                  const isSel = d === s.date
                  const fl = flagged.get(d)
                  return (
                    <button key={d} type="button" role="gridcell" data-date={d} data-testid={`day-${d}`} tabIndex={d === focus ? 0 : -1}
                      aria-selected={isSel} aria-label={`${fmtDate(d)}: ${di.value === null ? STATUS_LABEL[di.status] : `${fmtNum(di.value, 1)} ${METRIC_INFO[s.metric].unit}`}${fl ? '; elevated observed activity' : ''}`}
                      onClick={() => { s.setDate(d); setFocus(d) }} onFocus={() => setFocus(d)} onMouseEnter={() => setFocus(d)} onKeyDown={(e) => onKey(e, d)}
                      className={cls('relative flex h-16 flex-col items-start justify-between rounded-md p-1.5 text-left text-xs sm:h-20', st.className, isSel && 'ring-2 ring-ink ring-offset-1 ring-offset-panel')}
                      style={st.style}>
                      <span className="font-semibold">{Number(d.slice(8))}</span>
                      <span className="num text-[11px]">{di.inRange && di.value !== null ? fmtNum(di.value, s.metric.startsWith('frp') ? 0 : 0) : di.status === 'unknown' ? '?' : ''}</span>
                      {fl && <span className="absolute right-1 top-1 text-flag" title="Elevated observed activity"><Icon name="flag" className="h-3.5 w-3.5" /></span>}
                    </button>
                  )
                })}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]" aria-label="Calendar legend">
                <span className="flex items-center gap-1">{METRIC_INFO[s.metric].unit}: {rampBins(max).slice(1).map((b, i) => <span key={i} className="inline-block h-3 w-4" style={{ background: RAMP[i + 1] }} title={`≥ ${b}`} />)}<span>max {fmtNum(max, 1)}</span></span>
                <span className="flex items-center gap-1"><StatusSwatch status="zero_reported" />zero reported</span>
                <span className="flex items-center gap-1"><StatusSwatch status="unknown" />unknown coverage</span>
                <span className="flex items-center gap-1"><StatusSwatch status="outside_range" />outside range</span>
                <span className="flex items-center gap-1 text-flag"><Icon name="flag" className="h-3 w-3" />elevated period</span>
              </div>
            </>
          )}
        </Panel>
        <Panel title="Day details" info="Updates as you hover or move keyboard focus; click/Enter selects the day for the map and timeline.">
          <div aria-live="polite" className="space-y-2 text-xs" data-testid="day-details">
            <div className="text-sm font-semibold">{fmtDate(sel.date)} <span className="text-muted">(UTC)</span></div>
            <div>{METRIC_INFO[s.metric].label}: <b className="num">{sel.value === null ? '—' : fmtNum(sel.value, 2)}</b> {METRIC_INFO[s.metric].unit}</div>
            <div className="flex items-center gap-1.5"><StatusSwatch status={sel.status} color={SERIES_COLOR[s.series]} />{STATUS_LABEL[sel.status]}{ser && sel.i >= 0 && ser.status_origin[sel.i] ? ` (${ser.status_origin[sel.i]})` : ''}</div>
            {daily.data && sel.i >= 0 && (
              <table className="data"><thead><tr><th>Sensor</th><th>Det.</th><th>Cells</th><th>Status</th></tr></thead><tbody>
                {Object.entries(daily.data.series).map(([k, v]) => <tr key={k}><td>{SERIES_SHORT[k]}</td><td className="num">{k === 'UNION' ? '—' : fmtNum(v.detections[sel.i], k === 'FUSED' ? 1 : 0)}</td><td className="num">{fmtNum(v.cells[sel.i])}</td><td>{v.status[sel.i].replace('_', ' ')}</td></tr>)}
              </tbody></table>
            )}
            {flagged.get(sel.date) && <p className="rounded-md border border-red-200 bg-red-50 p-2 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100"><b>Elevated observed activity.</b> {flagged.get(sel.date)}</p>}
            {daily.data && <p className="text-muted">Filters: {String(daily.data.filter_disclosure.modis_quality)}; {String(daily.data.filter_disclosure.viirs_quality)}; types: {daily.data.filter_disclosure.types_included.join(', ')}. {sel.status === 'zero_reported' ? daily.data.status_doc.zero_reported : sel.status === 'unknown' ? daily.data.status_doc.unknown : ''}</p>}
            <button className="btn" onClick={() => { s.setDate(sel.date); s.set({ page: 'explore' }) }}>Open this day on the map</button>
          </div>
        </Panel>
      </div>
      <YearOverview look={look} max={rangeMax} year={y} flagged={flagged} />
      <WeeklyOverview />
      {s.series === 'FUSED' && <Panel title="Historical activity timeline · whole record (harmonized)" info="The harmonized series over the whole imported record (2000 → today where eligible sensors exist), with the observed MODIS Aqua reference. Monthly or yearly sums of known days.">
        <FusionHistory range="record" />
      </Panel>}
    </div>
  )
}

function YearOverview({ look, max, year, flagged }: { look: Map<string, { v: number | null; st: string }>; max: number; year: number; flagged: Map<string, string> }) {
  const s = useApp()
  return (
    <Panel title={`Year overview · ${year}`} info="Twelve months on the stable color scale of the analysis range. Click a day to select it.">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {MON3.map((mn, mi) => {
          const first = `${year}-${String(mi + 1).padStart(2, '0')}-01`
          const lead = isoWeekday(first) - 1
          const n = daysInMonth(year, mi + 1)
          return (
            <div key={mn}>
              <div className="mb-1 text-[11px] font-semibold">{mn}</div>
              <div className="grid grid-cols-7 gap-[2px]">
                {Array.from({ length: lead }).map((_, k) => <span key={`l${k}`} />)}
                {Array.from({ length: n }, (_, k) => {
                  const d = `${first.slice(0, 8)}${String(k + 1).padStart(2, '0')}`
                  const x = look.get(d)
                  const inR = d >= s.start && d <= s.end && !!x
                  const known = x && x.v !== null
                  return <button key={d} aria-label={`${d}: ${inR ? (known ? fmtNum(x!.v, 1) : 'unknown coverage') : 'outside range'}`} onClick={() => s.setDate(d)}
                    className={cls('h-3 w-full rounded-[2px]', !inR ? 'border border-dashed border-line' : !known ? 'hatch' : !x!.v ? 'bg-soft' : '', d === s.date && 'ring-2 ring-ink', flagged.has(d) && 'outline outline-1 outline-flag')}
                    style={inR && known && x!.v ? { background: rampColor(x!.v, max) } : undefined} />
                })}
              </div>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

function WeeklyOverview() {
  const s = useApp()
  const p = useSeriesParams()
  const q = useApi<Weeks>(`/api/weeks?${p}`)
  if (q.error) return <ErrorNote msg={q.error} />
  if (!q.data) return <Panel title="Multi-year ISO-week overview"><Loading /></Panel>
  const weeks = q.data.weeks
  const years = Array.from(new Set(weeks.map((w) => w.iso_year))).sort()
  const max = Math.max(0, ...weeks.map((w) => w.value))
  const by = new Map(weeks.map((w) => [`${w.iso_year}-${w.iso_week}`, w]))
  return (
    <Panel title="Multi-year ISO-week overview" info={<>{q.data.iso_note} Weekly value = {String((q.data.metric_definition as Record<string, string>).weekly_value)} Click a week to show a trailing 7-day map window ending that Sunday.</>}>
      <div className="overflow-x-auto">
        <table className="text-[10px]" aria-label="ISO week heatmap">
          <thead><tr><th className="pr-2 text-left text-muted">ISO year</th>{Array.from({ length: 53 }, (_, i) => <th key={i} className="w-4 font-normal text-muted">{(i + 1) % 4 === 1 ? i + 1 : ''}</th>)}</tr></thead>
          <tbody>
            {years.map((yy) => {
              const nw = weeks.find((w) => w.iso_year === yy)?.n_weeks_in_iso_year ?? 52
              return (
                <tr key={yy}>
                  <th className="pr-2 text-left font-semibold">{yy}<span className="ml-1 font-normal text-muted">({nw} wk)</span></th>
                  {Array.from({ length: 53 }, (_, i) => {
                    const w = by.get(`${yy}-${i + 1}`)
                    if (i + 1 > nw) return <td key={i} className="p-[1px]"><span className="block h-4 w-4 text-center text-muted" title={`${yy} has no ISO week 53`}>·</span></td>
                    if (!w) return <td key={i} className="p-[1px]"><span className="block h-4 w-4 rounded-sm border border-dashed border-line" title="Outside analysis range" /></td>
                    const end = addDays(w.start, 6)
                    const sel = s.date >= w.start && s.date <= end
                    return <td key={i} className="p-[1px]"><button aria-label={`${yy}-W${String(i + 1).padStart(2, '0')} (${w.start}): ${fmtNum(w.value, 1)}${w.partial ? ', partial week' : ''}`}
                      title={`${yy}-W${String(i + 1).padStart(2, '0')} from ${w.start}\n${fmtNum(w.value, 1)} ${METRIC_INFO[s.metric].unit.replace('/day', '')} (sum over ${w.days_in_range} day(s))${w.distinct_cells !== undefined ? `\nDistinct cells: ${w.distinct_cells}` : ''}${w.partial ? '\nPartial week (range boundary)' : ''}${!w.coverage_complete ? '\nIncludes unknown-coverage days' : ''}`}
                      onClick={() => { s.set({ frameMode: 7 }); s.setDate(end > s.end ? s.end : end) }}
                      className={cls('block h-4 w-4 rounded-sm', w.partial && 'border border-slate-500', !w.coverage_complete && 'hatch', sel && 'ring-2 ring-ink')}
                      style={{ background: w.value > 0 ? rampColor(w.value, max) : undefined }} /></td>
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted">Outlined squares are partial ISO weeks at the range edges (e.g. 2023-01-01 belongs to 2022-W52 and 2024-12-30/31 to 2025-W01). Stable color domain: 0–{fmtNum(max, 1)}.</p>
    </Panel>
  )
}
