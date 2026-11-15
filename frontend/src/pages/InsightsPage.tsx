// AOI Insights tab (added in v1.3): historical fire patterns, unusual conditions and critical periods for ONE area of
// interest and ONE sensor series, arranged by role. It describes observed detections; it is not a forecast or a warning.
import { useEffect, useState, type ReactNode } from 'react'
import { useApi, type Region } from '../api'
import { useInventory } from '../hooks'
import {
  BAND_COLOR, BAND_ORDER, ROLES, SECTION_LABEL, TRACKER_COLOR, cellWindow, fmtDay, insQS, seriesLastDay, useIns,
  type Anomaly, type CellAnomaly, type CompareRes, type Critical, type InsSeries, type NowRes, type Recurrence, type Regime,
  type YearsReport,
} from '../insights'
import { useApp } from '../state'
import { SERIES_COLOR, addDays, cls, fmtNum, type ISODate } from '../util'
import InsightsMap, { recurColor } from '../components/InsightsMap'
import Briefing from '../components/InsightsBriefing'
import { ModisEquivalentComparison } from '../components/HarmonizationAggregate'
import { FusionBanner } from '../components/FusionParts'
import { EChart, Empty, ErrorNote, Icon, Info, Loading, Panel, Seg } from '../components/ui'

const SERIES_NAME: Record<InsSeries, string> = { MODIS: 'MODIS (Terra + Aqua)', VIIRS_SNPP: 'VIIRS S-NPP', VIIRS_N20: 'VIIRS NOAA-20', VIIRS_N21: 'VIIRS NOAA-21', FUSED: 'Harmonized (all sensors)' }
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DOY_LABEL = (() => { const out: string[] = []; for (let k = 0; k < 365; k++) { const d = new Date(Date.UTC(2001, 0, 1 + k)); out.push(`${String(d.getUTCDate()).padStart(2, '0')} ${MON[d.getUTCMonth()]}`) } return out })()

function Badge({ color, children }: { color: string; children: ReactNode }) {
  return <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold">
    <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden />{children}</span>
}

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return <div className="rounded-lg border border-line p-3">
    <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
    <div className="mt-0.5 text-lg font-semibold leading-tight">{value}</div>
    {sub && <div className="mt-0.5 text-[11px] text-muted">{sub}</div>}
  </div>
}

function Q<T>({ q, children, what }: { q: { data: T | null; loading: boolean; error: string | null }; children: (d: T) => ReactNode; what: string }) {
  if (q.error) return <ErrorNote msg={`${what}: ${q.error}`} />
  if (!q.data) return <Loading label={`Computing ${what.toLowerCase()}…`} />
  return <>{children(q.data)}</>
}

function Unavailable({ reason }: { reason: string | null }) {
  return <Empty title="Not enough history">{reason ?? 'This area and sensor do not have enough complete years.'} Nothing is estimated to fill the gap.</Empty>
}

// ------------------------------------------------------------------ page
export default function InsightsPage({ regions, view = 'tracker' }: { regions: Region[]; view?: 'tracker' | 'climate' }) {
  const s = useApp()
  const ins = useIns()
  const inv = useInventory()
  const sensorSeries = (inv.data?.available_series ?? []).filter((x): x is InsSeries => ['MODIS', 'VIIRS_SNPP', 'VIIRS_N20', 'VIIRS_N21'].includes(x))
  // 1.5: the harmonized multi-sensor series is offered first whenever MODIS (its reference) is imported
  const avail: InsSeries[] = sensorSeries.includes('MODIS') ? ['FUSED', ...sensorSeries] : sensorSeries

  useEffect(() => {
    if (avail.length && !avail.includes(ins.series)) ins.set({ series: avail.includes('MODIS') ? 'MODIS' : avail[0], asOf: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avail.join(',')])

  const last = seriesLastDay(inv.data, ins.series)
  const first = inv.data?.date_range?.[0] ?? null
  const asOf: ISODate | null = ins.asOf && last && ins.asOf <= last && (!first || ins.asOf >= first) ? ins.asOf : last
  const role = ROLES.find((r) => r.id === ins.role) ?? ROLES[0]
  const aoiName = s.aoi === 'none' ? null : s.aoi.startsWith('region:') ? regions.find((r) => r.id === s.aoi)?.name ?? s.aoi : 'Custom AOI'

  if (!asOf) return <div className="p-6"><Loading /></div>
  const yearStart = `${asOf.slice(0, 4)}-01-01`
  const qsYear = insQS(s, ins.series, yearStart, asOf)

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <header className="panel space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold">{view === 'climate' ? 'Climate background: ENSO and IOD' : 'AOI Insights'}</h1>
            <p className="max-w-3xl text-[13px] text-muted">Historical fire patterns, unusual conditions and critical periods for <b className="text-ink">{aoiName ?? 'no area selected'}</b>,
              from one sensor series at a time. A description of past satellite detections: <b className="text-ink">not a forecast, not a fire-danger rating and not an official warning.</b></p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={() => ins.set({ briefing: true })} disabled={s.aoi === 'none'}><Icon name="doc" />Briefing (EN / ID)</button>
            <button className="btn" onClick={() => ins.set({ methodOpen: !ins.methodOpen })} aria-expanded={ins.methodOpen}><Icon name="data" />Method and data</button>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {view === 'tracker' && <label className="block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">I am…</span>
            <select className="field" aria-label="Role preset" data-testid="role-select" value={ins.role} onChange={(e) => ins.set({ role: e.target.value as typeof ins.role })}>
              {ROLES.map((r) => <option key={r.id} value={r.id} title={r.hint}>{r.label}</option>)}
            </select>
          </label>}
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Sensor series<Info>Each sensor series is analysed on its own, or as the harmonized series: every eligible satellite calibrated to MODIS Aqua and averaged. Raw MODIS and VIIRS detections are never added together. Cell maps (recurrence, cell anomaly) of the harmonized series use the MODIS Aqua reference sensor.</Info></div>
            <Seg label="Sensor series" value={ins.series} onChange={(v) => ins.set({ series: v, asOf: null })}
              options={avail.map((x) => ({ value: x, label: SERIES_NAME[x] }))} />
          </div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-muted">As of
            <input type="date" className="field mt-1 block" value={asOf} min={first ?? undefined} max={last ?? undefined}
              onChange={(e) => e.target.value && ins.set({ asOf: e.target.value })} aria-describedby="asof-help" />
          </label>
          <p id="asof-help" className="max-w-xs text-[11px] text-muted">The history runs from the first imported day ({first}) to this day; its year is the focus year. Latest {SERIES_NAME[ins.series]} day: {last}.</p>
        </div>
        {view === 'tracker'
          ? <p className="text-[12px] text-muted"><b className="text-ink">{role.label}:</b> {role.hint} Years and climate background are in the Climate ENSO / IOD view.</p>
          : <p className="text-[12px] text-muted">ENSO (NOAA ONI) and Indian Ocean Dipole (NOAA DMI) phases of each complete year, next to its detections. Context only, not a forecast.</p>}
      </header>
      {ins.series === 'FUSED' && <FusionBanner force />}

      {ins.methodOpen && <MethodDrawer qs={qsYear} series={ins.series} asOf={asOf} aoi={s.aoi} />}

      {s.aoi === 'none' ? (
        <Panel><Empty title="Choose an area of interest">Pick a region or draw an area in the top bar. Insights describe one area at a time, so that
          its history, thresholds and hotspots are its own.</Empty></Panel>
      ) : (
        <div className="space-y-4">
          {view === 'climate' && <YearsSection qs={qsYear} />}
          {view === 'tracker' && role.sections.filter((id) => id !== 'years').map((id) => (
            <div key={id} id={`ins-${id}`}>
              {id === 'now' && <NowSection asOf={asOf} lastArchive={last!} />}
              {id === 'tracker' && <TrackerSection qs={qsYear} />}
              {id === 'regime' && <RegimeSection qs={qsYear} />}
              {id === 'anomaly' && <AnomalySection asOf={asOf} first={first ?? asOf} />}
              {id === 'critical' && <CriticalSection qs={qsYear} />}
              {id === 'map' && <MapSection asOf={asOf} qs={qsYear} />}
              {id === 'compare' && <CompareSection asOf={asOf} regions={regions} />}
            </div>
          ))}
          {view === 'tracker' && <Panel title="Experimental MODIS-equivalent comparison (1.4, off by default)" info={<>Optional. Uses this area's whole history from {first} to {asOf}: VIIRS daily totals times c = ΣMODIS / ΣVIIRS fitted on earlier days. Drawn only when this area and satellite pair pass the project's aggregate gate; otherwise the original totals are shown and nothing is estimated. Not an official NASA product, and none of the sections above use it.</>}>
            <ModisEquivalentComparison qs={insQS(s, ins.series, first ?? asOf, asOf)} available={avail} preferred={ins.series} testid="ins-meq" />
          </Panel>}
        </div>
      )}
      {ins.briefing && s.aoi !== 'none' && <Briefing asOf={asOf} aoiName={aoiName ?? ''} onClose={() => ins.set({ briefing: false })} />}
    </div>
  )
}

// ------------------------------------------------------------------ D1: status now (FIRMS NRT, on request)
function NowSection({ asOf, lastArchive }: { asOf: ISODate; lastArchive: ISODate }) {
  const s = useApp()
  const ins = useIns()
  // near-real-time data come from one FIRMS sensor; the harmonized series uses S-NPP VIIRS for this live view
  const nowSeries: InsSeries = ins.series === 'FUSED' ? 'VIIRS_SNPP' : ins.series
  const qs = insQS(s, nowSeries, asOf, lastArchive, { days: 10 })
  const q = useApi<NowRes>(ins.nowRun ? `/api/insights/now?${qs}&_run=${ins.nowRun}` : null)
  const d = q.data
  return (
    <Panel id="h-now" title={SECTION_LABEL.now} info={<>Fetches the last 10 days of FIRMS near-real-time (NRT) detections for this area through the server (the FIRMS key never reaches the browser).
      NRT rows are provisional and are not stored. Each day is scored against the same dates in earlier complete years of the archive.</>}
      actions={<button className="btn btn-primary" onClick={() => ins.set({ nowRun: ins.nowRun + 1 })} disabled={q.loading}>
        {ins.nowRun ? 'Fetch again' : 'Fetch last 10 days from FIRMS'}</button>}>
      {!ins.nowRun ? <p className="text-[13px] text-muted">Not fetched yet. Nothing is requested from FIRMS until you press the button.</p>
        : q.error ? <ErrorNote msg={`Near-real-time data unavailable: ${q.error}. The historical sections below do not depend on it.`} />
          : !d ? <Loading label="Fetching FIRMS near-real-time data…" /> : (
            <div className="space-y-3">
              {d.window_score
                ? <p className="text-[14px]"><Badge color={BAND_COLOR[d.window_score.band]}>{d.window_score.band}</Badge> <span className="ml-1">{d.window_score.sentence}</span></p>
                : <p className="text-[13px]">{d.total} NRT detections from {fmtDay(d.window.start)} to {fmtDay(d.window.end)}. Not enough complete earlier years to score the window.</p>}
              <EChart height={180} ariaLabel="Near-real-time detections per day with their anomaly band" option={{
                grid: { left: 44, right: 12, top: 10, bottom: 28 },
                tooltip: { trigger: 'axis', formatter: (p: { dataIndex: number }[]) => { const x = d.days[p[0].dataIndex]; return `${x.date}<br/>${x.nrt_detections} NRT detections<br/>${x.band ? `${x.band} (z ${x.z?.toFixed(2)}, usual median ${fmtNum(x.reference_median, 1)})` : x.state}` } },
                xAxis: { type: 'category', data: d.days.map((x) => x.date.slice(5)) }, yAxis: { type: 'value', name: 'detections', nameTextStyle: { fontSize: 10 } },
                series: [{ type: 'bar', data: d.days.map((x) => ({ value: x.nrt_detections, itemStyle: { color: x.band ? BAND_COLOR[x.band] : '#a1a1aa' } })) }],
              }} />
              <p className="text-[11px] text-muted">Source {d.source}: {d.counts.rows_fetched} rows fetched, {d.counts.outside_aoi} outside the area, {d.counts.filtered_out} removed by the filters,
                {' '}{d.counts.rejected_rows} rejected. Latest ONI {d.climate_now.oni.season} {d.climate_now.oni.year}: {d.climate_now.oni.value.toFixed(2)} °C.</p>
              <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-muted">{d.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </div>
          )}
    </Panel>
  )
}

// ------------------------------------------------------------------ B4: season tracker
function TrackerSection({ qs }: { qs: string }) {
  const q = useApi<Regime>(`/api/insights/regime?${qs}&metric=detections`)
  return (
    <Panel title={SECTION_LABEL.tracker} info={<>Cumulative detections since 1 January in the focus year (line) against the 10th–90th percentile range and the median of all
      complete reference years at the same day of the year. Unknown-coverage days add nothing.</>}>
      <Q q={q} what="Season tracker">{(r) => !r.available || !r.tracker ? <Unavailable reason={r.reason} /> : (
        <div className="space-y-3">
          {r.tracker.status && <p className="text-[14px]"><Badge color={TRACKER_COLOR[r.tracker.status.band] ?? '#71717a'}>{r.tracker.status.band}</Badge> <span className="ml-1">{r.tracker.status.sentence}</span></p>}
          <EChart height={260} ariaLabel="Cumulative detections of the focus year against the reference range" option={trackerOption(r)} />
          <p className="text-[11px] text-muted">{r.tracker.note} Reference years: {r.reference_years.join(', ')}. {String(r.rules.missing_type ?? '')}</p>
        </div>
      )}</Q>
    </Panel>
  )
}

function trackerOption(r: Regime) {
  const e = r.tracker!.envelope
  return {
    grid: { left: 60, right: 16, top: 24, bottom: 30 },
    legend: { top: 0, textStyle: { fontSize: 11 }, data: [String(r.focus_year), 'Median of reference years', '10th–90th percentile'] },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtNum(v) },
    xAxis: { type: 'category', data: DOY_LABEL, axisLabel: { interval: 30 } },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => fmtNum(v) } },
    series: [
      { name: 'p10', type: 'line', data: e.p10, stack: 'band', symbol: 'none', lineStyle: { opacity: 0 }, tooltip: { show: false } },
      { name: '10th–90th percentile', type: 'line', data: e.p90.map((v, i) => v - e.p10[i]), stack: 'band', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(100,116,139,0.22)' }, color: 'rgba(100,116,139,0.5)' },
      { name: 'Median of reference years', type: 'line', data: e.median, symbol: 'none', lineStyle: { type: 'dashed', width: 1.5 }, color: '#52525b' },
      { name: String(r.focus_year), type: 'line', data: r.tracker!.focus, symbol: 'none', lineStyle: { width: 2.5 }, color: SERIES_COLOR[r.series] ?? '#0f766e' },
    ],
  }
}

// ------------------------------------------------------------------ A1: fire regime
function RegimeSection({ qs }: { qs: string }) {
  const q = useApi<Regime>(`/api/insights/regime?${qs}&metric=detections`)
  return (
    <Panel title={SECTION_LABEL.regime} info={<>Weekly detections per known day: median and 10th–90th percentile of complete years, with the focus year. Season start, peak and end are the
      days on which 10 %, 50 % and 90 % of a year's detections had been reached.</>}>
      <Q q={q} what="Fire regime">{(r) => !r.available ? <Unavailable reason={r.reason} /> : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            {r.season && <>
              <Stat label="Season start (median)" value={r.season.onset.median} sub={`usually ${r.season.onset.early} – ${r.season.onset.late}`} />
              <Stat label="Season peak (median)" value={r.season.peak.median} sub={`usually ${r.season.peak.early} – ${r.season.peak.late}`} />
              <Stat label="Season end (median)" value={r.season.end.median} sub={`usually ${r.season.end.early} – ${r.season.end.late}`} />
            </>}
            {r.peak_week && <Stat label="Busiest week" value={r.peak_week.label} sub={`median ${fmtNum(r.peak_week.median, 1)} detections/day`} />}
            {r.variability && <Stat label="Year-to-year variability" value={`CV ${r.variability.cv.toFixed(2)}`}
              sub={`${fmtNum(r.variability.min)} (${r.variability.min_year}) to ${fmtNum(r.variability.max)} (${r.variability.max_year}) per year`} />}
          </div>
          <EChart height={240} ariaLabel="Weekly fire regime with the focus year" option={{
            grid: { left: 50, right: 16, top: 24, bottom: 40 },
            legend: { top: 0, textStyle: { fontSize: 11 }, data: [String(r.focus_year), 'Median', '10th–90th percentile'] },
            tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtNum(v, 1) },
            xAxis: { type: 'category', data: r.weeks.map((w) => w.label), axisLabel: { interval: 3, fontSize: 10, rotate: 30 } },
            yAxis: { type: 'value', name: 'detections/day', nameTextStyle: { fontSize: 10 } },
            series: [
              { name: 'p10', type: 'line', stack: 'b', data: r.weeks.map((w) => w.p10), symbol: 'none', lineStyle: { opacity: 0 }, tooltip: { show: false } },
              { name: '10th–90th percentile', type: 'line', stack: 'b', data: r.weeks.map((w) => (w.p90 ?? 0) - (w.p10 ?? 0)), symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(100,116,139,0.22)' }, color: 'rgba(100,116,139,0.5)' },
              { name: 'Median', type: 'line', data: r.weeks.map((w) => w.median), symbol: 'none', lineStyle: { type: 'dashed' }, color: '#52525b' },
              { name: String(r.focus_year), type: 'line', data: r.focus_weeks, symbol: 'circle', symbolSize: 3, color: SERIES_COLOR[r.series] ?? '#0f766e' },
            ],
          }} />
          <details className="text-[12px]"><summary className="cursor-pointer text-muted">Season dates per year ({r.season_by_year.length} complete years)</summary>
            <div className="scroll-box mt-2"><table className="data"><thead><tr><th>Year</th><th className="text-right">Detections</th><th>Start</th><th>Peak</th><th>End</th></tr></thead>
              <tbody>{r.season_by_year.map((y) => <tr key={y.year}><td>{y.year}</td><td className="text-right">{fmtNum(y.total)}</td><td>{y.onset_date}</td><td>{y.peak_date}</td><td>{y.end_date}</td></tr>)}</tbody></table></div>
          </details>
        </div>
      )}</Q>
    </Panel>
  )
}

// ------------------------------------------------------------------ B2: unusual conditions
function AnomalySection({ asOf, first }: { asOf: ISODate; first: ISODate }) {
  const s = useApp()
  const ins = useIns()
  const start = addDays(asOf, -179) < first ? first : addDays(asOf, -179)
  const q = useApi<Anomaly>(`/api/insights/anomaly?${insQS(s, ins.series, start, asOf)}&metric=detections`)
  return (
    <Panel title={`${SECTION_LABEL.anomaly}: last 180 days`} info={<>Each day is compared with the same dates (±15 days) in every EARLIER complete year, so the score asks
      “unusual for this time of year?”. Robust score on log(1 + detections) using median and MAD; bands at 1, 2 and 3. A positive band also needs the value above the
      usual 75th percentile and at least 3 above the usual median, so one or two detections in a usually empty season stay normal.</>}>
      <Q q={q} what="Unusual conditions">{(a) => (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {BAND_ORDER.map((b) => <Badge key={b} color={BAND_COLOR[b]}>{b}: {a.summary.by_band[b] ?? 0} days</Badge>)}
            {a.summary.unknown > 0 && <Badge color="#a1a1aa">unknown coverage: {a.summary.unknown}</Badge>}
            {a.summary.insufficient > 0 && <Badge color="#e4e4e7">not enough history: {a.summary.insufficient}</Badge>}
          </div>
          {a.summary.max && a.summary.max.band && a.summary.max.band !== 'normal' && <p className="text-[13px]">Most unusual day: <b>{fmtDay(a.summary.max.date)}</b> with {fmtNum(a.summary.max.value)} detections
            (usually {fmtNum(a.summary.max.reference_median, 1)} around that date; higher than {fmtNum(a.summary.max.higher_than_pct)} % of those reference days), <b>{a.summary.max.band}</b>.</p>}
          <EChart height={200} ariaLabel="Daily detections coloured by anomaly band" option={{
            grid: { left: 50, right: 12, top: 10, bottom: 28 },
            tooltip: { trigger: 'axis', formatter: (p: { dataIndex: number }[]) => { const x = a.days[p[0].dataIndex]; return `${x.date}<br/>${x.value === null ? 'unknown coverage' : `${fmtNum(x.value)} detections`}<br/>${x.band ? `${x.band} · z ${x.z?.toFixed(2)}<br/>usual median ${fmtNum(x.reference_median, 1)} · higher than ${fmtNum(x.higher_than_pct)} % of reference days` : x.state}` } },
            xAxis: { type: 'category', data: a.days.map((x) => x.date), axisLabel: { formatter: (v: string) => v.slice(5) } },
            yAxis: { type: 'value', name: 'detections/day', nameTextStyle: { fontSize: 10 } },
            dataZoom: [{ type: 'inside' }],
            series: [{ type: 'bar', barCategoryGap: '10%', data: a.days.map((x) => ({ value: x.value ?? 0, itemStyle: { color: x.value === null ? '#e4e4e7' : x.band ? BAND_COLOR[x.band] : '#a1a1aa' } })) }],
          }} />
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Weeks (mean detections per known day vs the same week in earlier complete years)</div>
            <div className="flex flex-wrap gap-0.5" role="list" aria-label="Weekly anomaly bands">
              {a.weeks.map((w) => <span key={`${w.year}-${w.week}`} role="listitem" className="inline-block h-5 w-5 rounded-sm border border-line"
                style={{ background: w.band ? BAND_COLOR[w.band] : w.state === 'unknown coverage' ? 'transparent' : '#e4e4e7' }}
                title={`${w.year} ${w.label}: ${w.value === null ? 'unknown' : fmtNum(w.value, 1) + ' /day'}${w.band ? ` · ${w.band} (usual ${fmtNum(w.reference_median, 1)})` : ` · ${w.state}`}`} />)}
            </div>
          </div>
        </div>
      )}</Q>
    </Panel>
  )
}

// ------------------------------------------------------------------ C1 + C2: critical periods and readiness calendar
function CriticalSection({ qs }: { qs: string }) {
  const ins = useIns()
  const q = useApi<Critical>(`/api/insights/critical?${qs}&metric=detections&percentile=${ins.percentile}`)
  return (
    <Panel title={SECTION_LABEL.critical} info={<>A critical period is at least 3 consecutive days above a high level: the chosen percentile of ALL known days in all OTHER
      complete years (so a year never sets its own threshold). The readiness calendar counts, for each week of the year, in how many complete years it held a critical day.
      It summarises the past; it does not predict this year.</>}
      actions={<Seg label="Threshold percentile" value={ins.percentile} onChange={(v) => ins.set({ percentile: v })}
        options={[{ value: 85, label: 'P85' }, { value: 90, label: 'P90' }, { value: 95, label: 'P95' }]} />}>
      <Q q={q} what="Critical periods">{(c) => !c.available ? <Unavailable reason={c.reason} /> : (
        <div className="space-y-4">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Readiness calendar: share of complete years with a critical day in each week</div>
            <div className="grid gap-0.5" style={{ gridTemplateColumns: 'repeat(52, minmax(0, 1fr))' }} role="list" aria-label="Readiness calendar by week">
              {c.readiness.weeks.map((w) => <div key={w.week} role="listitem" className="h-8 rounded-sm border border-line"
                style={{ background: w.share ? `rgba(194,65,12,${0.12 + 0.88 * w.share})` : 'transparent' }}
                title={`${w.label}: critical in ${w.years_critical} of ${w.years_known} complete years`} aria-label={`${w.label}: ${w.years_critical} of ${w.years_known} years`} />)}
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-muted">{MON.map((m) => <span key={m}>{m}</span>)}</div>
            <TopWeeks c={c} />
          </div>
          <div>
            <div className="scroll-box"><table className="data">
              <thead><tr><th>#</th><th>Period (UTC days)</th><th className="text-right">Days</th><th className="text-right">Peak</th><th className="text-right">Total</th><th className="text-right">Above threshold</th></tr></thead>
              <tbody>{c.periods.slice(0, 10).map((p) => <tr key={p.start} title={p.reason}>
                <td>{p.rank}</td><td>{fmtDay(p.start)} – {fmtDay(p.end)}{p.coverage_notes.length > 0 && <span className="text-amber-700"> ⚠</span>}</td>
                <td className="text-right">{p.duration_days}</td><td className="text-right">{fmtNum(p.peak)} ({p.peak_date.slice(5)})</td>
                <td className="text-right">{fmtNum(p.total)}</td><td className="text-right">{fmtNum(p.excess)}</td></tr>)}</tbody>
            </table></div>
            <p className="mt-1 text-[11px] text-muted">{c.periods_total} critical periods in total; the 10 with the most detections above the threshold are listed. {c.rule_text}</p>
          </div>
        </div>
      )}</Q>
    </Panel>
  )
}

function TopWeeks({ c }: { c: Critical }) {
  const top = [...c.readiness.weeks].filter((w) => (w.share ?? 0) > 0).sort((a, b) => (b.share ?? 0) - (a.share ?? 0)).slice(0, 4)
  if (!top.length) return <p className="mt-2 text-[12px] text-muted">No week held a critical day in any complete year.</p>
  return <p className="mt-2 text-[13px]">Historically most critical weeks: {top.map((w, i) => <span key={w.week}>{i > 0 && ', '}<b>{w.label}</b> ({w.years_critical} of {w.years_known} years)</span>)}.</p>
}

// ------------------------------------------------------------------ A2 + E2: map (recurrence or unusual cells) and hotspot exports
function MapSection({ asOf, qs }: { asOf: ISODate; qs: string }) {
  const s = useApp()
  const ins = useIns()
  const rq = useApi<Recurrence>(`/api/insights/recurrence?${qs}&chronic_share=${ins.chronicShare}`)
  const [a, b] = cellWindow(asOf, ins.cellWindow)
  const aq = useApi<CellAnomaly>(ins.mapMode === 'anomaly' ? `/api/insights/anomaly_cells?${insQS(s, ins.series, a, b)}` : null)
  const rec = rq.data?.available ? rq.data.cells : []
  const an = aq.data?.available ? aq.data.cells : []
  const nYears = ins.mapMode === 'recurrence' ? rq.data?.n_eligible_years ?? 0 : aq.data?.reference_years.length ?? 0
  const grid = (ins.mapMode === 'recurrence' ? rq.data?.grid_size : aq.data?.grid_size) ?? s.grid
  const unusual = an.filter((c) => c.band !== 'normal' && c.band !== 'below normal').length
  return (
    <Panel title={SECTION_LABEL.map} info={<>Recurrence: in how many complete years each grid cell had at least one detection; “chronic” cells burned in at least the chosen share of years.
      Unusual cells: detections in the latest window compared with the same window in every earlier complete year, with the same robust score as the daily view.</>}
      actions={<>
        <Seg label="Map layer" value={ins.mapMode} onChange={(v) => ins.set({ mapMode: v })} options={[{ value: 'recurrence', label: 'Recurrence' }, { value: 'anomaly', label: 'Unusual cells' }]} />
        {ins.mapMode === 'recurrence'
          ? <Seg label="Chronic share" value={ins.chronicShare} onChange={(v) => ins.set({ chronicShare: v })} options={[{ value: 0.25, label: '≥25 %' }, { value: 0.4, label: '≥40 %' }, { value: 0.6, label: '≥60 %' }]} />
          : <Seg label="Window" value={ins.cellWindow} onChange={(v) => ins.set({ cellWindow: v })} options={[{ value: 7, label: '7 days' }, { value: 30, label: '30 days' }, { value: 90, label: '90 days' }]} />}
      </>}>
      <div className="space-y-2">
        {ins.mapMode === 'recurrence' ? (
          rq.error ? <ErrorNote msg={rq.error} /> : !rq.data ? <Loading label="Computing recurrence…" /> : !rq.data.available ? <Unavailable reason={rq.data.reason} /> :
            <p className="text-[13px]"><b>{fmtNum(rq.data.cells_total)}</b> cells had fire in at least one of {rq.data.n_eligible_years} complete years; <b>{fmtNum(rq.data.chronic_cells)}</b> are chronic
              (fire in ≥ {Math.round(rq.data.chronic_share * 100)} % of years).{rq.data.truncated && ' Only the most recurrent cells are drawn.'}</p>
        ) : aq.error ? <ErrorNote msg={aq.error} /> : !aq.data ? <Loading label="Scoring cells…" /> : !aq.data.available ? <Unavailable reason={aq.data.reason} /> :
          <p className="text-[13px]">{fmtDay(aq.data.window.start)} – {fmtDay(aq.data.window.end)}: <b>{unusual}</b> of {fmtNum(aq.data.cells_total ?? 0)} cells above normal
            against {aq.data.reference_years.length} earlier years ({aq.data.window_known_days} of {aq.data.window_days} days with known coverage).</p>}
        <InsightsMap aoi={s.aoi} grid={grid} mode={ins.mapMode} rec={rec} anom={an} nYears={nYears} />
        <div className="flex flex-wrap items-center justify-between gap-2">
          {ins.mapMode === 'recurrence'
            ? <div className="flex items-center gap-1 text-[11px] text-muted">Share of years with fire:
              {[0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95].map((v) => <span key={v} className="inline-block h-3 w-6" style={{ background: recurColor(v) }} title={`${Math.round(v * 100)} %`} />)}
              <span>0 % → 100 % of complete years</span></div>
            : <div className="flex flex-wrap gap-2">{BAND_ORDER.map((b) => <Badge key={b} color={BAND_COLOR[b]}>{b}</Badge>)}</div>}
          <div className="flex flex-wrap gap-2 text-[12px]">
            <span className="text-muted">Top 200 recurrent cells:</span>
            {(['csv', 'geojson', 'kml'] as const).map((f) => <a key={f} className="btn" href={`/api/export/hotspots.${f}?${qs}&top=200`} download><Icon name="download" />{f.toUpperCase()}</a>)}
          </div>
        </div>
        {rq.data?.notes && ins.mapMode === 'recurrence' && <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-muted">{rq.data.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------------ D2 + F2: years report and climate background (analog years)
function YearsSection({ qs }: { qs: string }) {
  const q = useApi<YearsReport>(`/api/insights/years?${qs}&metric=detections`)
  const [sort, setSort] = useState<'year' | 'total'>('year')
  return (
    <Panel title={SECTION_LABEL.years} info={<>Each complete year with its detections, dry-season (Jul–Oct) detections and critical days, labelled with the ENSO phase (mean ONI of JAS and ASO)
      and the IOD phase (mean DMI of Aug–Oct) from NOAA. Grouping years by phase shows analog years: a pattern from a handful of seasons, not a forecast.</>}
      actions={<Seg label="Sort years" value={sort} onChange={setSort} options={[{ value: 'year', label: 'By year' }, { value: 'total', label: 'By detections' }]} />}>
      <Q q={q} what="Years and climate">{(y) => {
        const rows = y.years.filter((r) => r.eligible || r.is_focus)
        const sorted = sort === 'year' ? rows : [...rows].sort((a, b) => b.total - a.total)
        return (
          <div className="space-y-3">
            <div className="grid gap-2 md:grid-cols-2">
              {(['enso', 'iod'] as const).map((k) => (
                <div key={k} className="rounded-lg border border-line p-3">
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{k === 'enso' ? 'ENSO phase of the dry season' : 'Indian Ocean Dipole phase (Aug–Oct)'}</div>
                  <table className="data"><thead><tr><th>Phase</th><th className="text-right">Years</th><th className="text-right">Median detections</th><th className="text-right">Median critical days</th></tr></thead>
                    <tbody>{y.groups[k].map((g) => <tr key={g.phase} title={g.years.join(', ')}><td>{g.phase}</td><td className="text-right">{g.n_years}</td>
                      <td className="text-right">{g.enough ? fmtNum(g.median_total) : <span className="text-muted">too few</span>}</td>
                      <td className="text-right">{g.enough ? fmtNum(g.median_critical_days) : '—'}</td></tr>)}</tbody></table>
                </div>
              ))}
            </div>
            <p className="text-[13px]">Focus year {y.focus_year}: ENSO <b>{y.focus_phase.enso ?? 'not yet known'}</b>{y.focus_phase.oni !== null && ` (ONI ${y.focus_phase.oni.toFixed(2)}${y.focus_phase.oni_complete ? '' : ', partial'})`},
              {' '}IOD <b>{y.focus_phase.iod ?? 'not yet known'}</b>{y.focus_phase.dmi !== null && ` (DMI ${y.focus_phase.dmi.toFixed(2)}${y.focus_phase.dmi_complete ? '' : ', partial'})`}.
              {' '}Latest values: ONI {y.climate_latest.oni.season} {y.climate_latest.oni.year} = {y.climate_latest.oni.value.toFixed(2)} °C, DMI {MON[y.climate_latest.dmi.month - 1]} {y.climate_latest.dmi.year} = {y.climate_latest.dmi.value.toFixed(2)} °C.</p>
            <div className="scroll-box">
              <table className="data">
                <thead><tr><th>Year</th><th className="text-right">Detections</th><th className="text-right">Jul–Oct</th><th className="text-right">Critical days</th><th>ENSO</th><th className="text-right">ONI</th><th>IOD</th><th className="text-right">DMI</th></tr></thead>
                <tbody>{sorted.map((r) => <tr key={r.year} className={cls(r.is_focus && 'font-semibold')}>
                  <td>{r.year}{r.is_focus && ' (focus, to date)'}</td><td className="text-right">{fmtNum(r.total)}</td><td className="text-right">{fmtNum(r.peak_season_total)}</td>
                  <td className="text-right">{r.critical_days ?? '—'}</td><td>{r.enso ?? '—'}</td><td className="text-right">{r.oni === null ? '—' : r.oni.toFixed(2)}</td>
                  <td>{r.iod ?? '—'}</td><td className="text-right">{r.dmi === null ? '—' : r.dmi.toFixed(2)}</td></tr>)}</tbody>
              </table>
            </div>
            <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-muted">{y.notes.map((n, i) => <li key={i}>{n}</li>)}
              {y.climate_sources.map((c) => <li key={c.url}>{c.name}, <a className="underline" href={c.url} target="_blank" rel="noreferrer">{c.url}</a>, retrieved {c.retrieved}.</li>)}</ul>
          </div>
        )
      }}</Q>
    </Panel>
  )
}

// ------------------------------------------------------------------ F1: compare areas
function CompareSection({ asOf, regions }: { asOf: ISODate; regions: Region[] }) {
  const s = useApp()
  const ins = useIns()
  const others = regions.filter((r) => r.id !== s.aoi && r.kind !== 'country')
  const aois = [s.aoi, ...ins.compare.filter((x) => x !== s.aoi)].slice(0, 6)
  const q = useApi<CompareRes>(aois.length >= 2 ? `/api/insights/compare?${insQS(s, ins.series, `${asOf.slice(0, 4)}-01-01`, asOf)}&aois=${encodeURIComponent(aois.join(','))}&metric=detections` : null)
  const toggle = (id: string) => ins.set({ compare: ins.compare.includes(id) ? ins.compare.filter((x) => x !== id) : [...ins.compare, id].slice(0, 5) })
  return (
    <Panel title={SECTION_LABEL.compare} info={<>The same measures for up to six areas, each with its own history and thresholds. Detections per 1,000 km² use an approximate area. Critical days
      compare how often an area exceeds its OWN high-activity level, not absolute activity.</>}>
      <div className="space-y-3">
        <fieldset className="flex max-h-40 flex-wrap gap-2 overflow-auto text-[12px]"><legend className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Compare the current area with…</legend>
          {others.map((r) => <label key={r.id} className="flex items-center gap-1 rounded border border-line px-2 py-1">
            <input type="checkbox" checked={ins.compare.includes(r.id)} onChange={() => toggle(r.id)} />{r.name}</label>)}
        </fieldset>
        {aois.length < 2 ? <p className="text-[13px] text-muted">Tick at least one more area.</p> : (
          <Q q={q} what="Comparison">{(c) => (
            <div className="overflow-auto">
              <table className="data">
                <thead><tr><th>Area</th><th className="text-right">Area km²</th><th className="text-right">Mean detections / year</th><th className="text-right">per 1,000 km²</th><th className="text-right">CV</th>
                  <th>Busiest week</th><th className="text-right">Chronic cells</th><th className="text-right">Median critical days</th><th>{asOf.slice(0, 4)} so far</th></tr></thead>
                <tbody>{c.rows.map((r) => <tr key={r.aoi}>
                  <td className="font-semibold">{r.name}{r.small_area && <span className="text-amber-700" title="Small area: few detections, noisy statistics"> ⚠</span>}</td>
                  <td className="text-right">{fmtNum(r.area_km2)}</td>
                  {r.regime_available ? <>
                    <td className="text-right">{fmtNum(r.mean_annual)}</td><td className="text-right">{fmtNum(r.mean_annual_per_1000km2, 1)}</td><td className="text-right">{r.cv?.toFixed(2) ?? '—'}</td>
                    <td>{r.peak_week ?? '—'}</td><td className="text-right">{fmtNum(r.chronic_cells)}</td><td className="text-right">{fmtNum(r.median_critical_days)}</td>
                    <td>{r.tracker ? <Badge color={TRACKER_COLOR[r.tracker.band] ?? '#71717a'}>{r.tracker.band}</Badge> : '—'}</td>
                  </> : <td colSpan={7} className="text-muted">{r.reason}</td>}
                </tr>)}</tbody>
              </table>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[11px] text-muted">{c.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </div>
          )}</Q>
        )}
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------------ G1: method & data drawer
function MethodDrawer({ qs, series, asOf, aoi }: { qs: string; series: InsSeries; asOf: ISODate; aoi: string }) {
  const ins = useIns()
  const r = useApi<Regime>(`/api/insights/regime?${qs}&metric=detections`)
  const d = r.data
  const cli = `python -m pyrosync.cli insights --aoi ${aoi} --series ${series} --as-of ${asOf} --out insights_${series}_${asOf}`
  const [copied, setCopied] = useState(false)
  return (
    <Panel title="Method and data" actions={<button className="btn" onClick={() => ins.set({ methodOpen: false })} aria-label="Close method and data"><Icon name="x" /></button>}>
      <div className="grid gap-4 text-[12px] md:grid-cols-2">
        <div className="space-y-2">
          <p><b>{d?.disclaimer ?? 'Historical description of satellite fire detections. Not a forecast.'}</b></p>
          <ul className="list-disc space-y-1 pl-5">
            <li>One sensor series at a time ({SERIES_NAME[series]}); MODIS and VIIRS are never added together.</li>
            <li>History: {d ? `${d.history.start} to ${d.history.end}` : '…'}; a complete year has at least 80 % of days with known coverage. Unknown days are never counted as zero.</li>
            <li>Reference years: {d ? d.reference_years.length : '…'} complete years other than the focus year; at least 5 are needed for any statistic.</li>
            <li>Weeks: day-of-year bins of 7 days (the last one runs to 31 Dec); values are means per known day.</li>
            <li>Unusual conditions: robust score on log(1 + x) with median and MAD, compared with EARLIER complete years only.</li>
            <li>Critical periods: ≥ 3 consecutive days above the percentile of all days in all OTHER complete years.</li>
            <li>Climate: NOAA CPC ONI and NOAA PSL DMI, bundled with checksums; phases use project thresholds.</li>
            <li>{d ? String(d.rules.missing_type ?? '') : 'FIRMS near-real-time rows carry no fire-type column.'}</li>
          </ul>
          <p className="text-muted">Method version {d?.method_version ?? '…'}, processing {d?.processing_version ?? '…'}, dataset revision {d?.dataset_revision ?? '…'}. Full description: docs/METHODOLOGY.md §17.</p>
        </div>
        <div className="space-y-2">
          <a className="btn btn-primary" href={`/api/export/insights.zip?${qs}&metric=detections`} download><Icon name="download" />Download the insights package (ZIP)</a>
          <p className="text-muted">JSON and CSV for the regime, critical periods, years and recurrence, a manifest with every setting and a README.</p>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">Reproduce from the command line</div>
          <div className="flex items-start gap-2">
            <code className="block flex-1 overflow-x-auto whitespace-pre rounded bg-soft p-2 text-[11px]">{cli}</code>
            <button className="btn" onClick={() => { navigator.clipboard?.writeText(cli).then(() => setCopied(true), () => {}) }}>{copied ? 'Copied' : 'Copy'}</button>
          </div>
          <p className="text-muted">API: <code>/api/insights/regime</code>, <code>/anomaly</code>, <code>/anomaly_cells</code>, <code>/recurrence</code>, <code>/critical</code>, <code>/years</code>, <code>/compare</code>, <code>/now</code>, <code>/climate</code>. An example notebook is in <code>docs/notebooks/</code>.</p>
        </div>
      </div>
    </Panel>
  )
}
