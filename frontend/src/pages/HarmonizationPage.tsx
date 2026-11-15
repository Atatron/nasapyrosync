// Harmonization tab (added in v1.2): one page that walks from region choice to historical patterns using ONE harmonization run.
// It reads original observations and shows calibrated values only as labelled, validated estimates. Other pages are unchanged.
import { useEffect, useMemo } from 'react'
import { useApi, type Region } from '../api'
import { useFilterQS, useInventory } from '../hooks'
import { errorGridsFor, harmParams, useHarm, type HarmonizationRun } from '../harmonization'
import { useApp } from '../state'
import { SERIES_SHORT, fmtNum } from '../util'
import { Stage3 } from '../components/Harmonization'
import HarmonizationMap, { WindowDetails } from '../components/HarmonizationMap'
import HarmonizationSeries from '../components/HarmonizationSeries'
import { AggregatePanel, AggregateSeries } from '../components/HarmonizationAggregate'
import { ErrorComparison, MatchingProcess, PipelineCards, StatusBadge, ValidityChecks } from '../components/HarmonizationParts'
import { ErrorNote, Icon, Loading, Panel, Seg } from '../components/ui'
import { FusionPanel } from '../components/FusionParts'

const VIIRS_PLATFORM: Record<string, string> = { VIIRS_SNPP: 'SNPP', VIIRS_N20: 'N20', VIIRS_N21: 'N21' }
const STEPS = [
  ['h-fusion', 'Multi-sensor fusion'], ['h-settings', 'Run settings'], ['h-compare', 'Compare sensors'], ['h-harmonize', 'Harmonize'],
  ['h-validity', 'Evaluate errors'], ['h-aggregate', 'Validate daily totals'], ['h-map', 'View on map'], ['h-history', 'Historical patterns'],
] as const

export default function HarmonizationPage({ regions }: { regions: Region[] }) {
  const s = useApp()
  const h = useHarm()
  const qs = useFilterQS()
  const inv = useInventory()
  const avail = inv.data?.available_series ?? []
  const availPlat = inv.data?.available_platforms ?? []

  // default VIIRS sensor: one that exists in the imported data (the online demo has S-NPP only)
  useEffect(() => {
    if (!avail.length || avail.includes(h.viirs)) return
    const v = (['VIIRS_SNPP', 'VIIRS_N20', 'VIIRS_N21'] as const).find((x) => avail.includes(x))
    if (v) h.set({ viirs: v })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avail.join(',')])
  // the error-map region size must be a multiple of the comparison grid
  useEffect(() => {
    const ok = errorGridsFor(h.grid)
    if (!ok.some((g) => Math.abs(g - h.errGrid) < 1e-9)) h.set({ errGrid: Math.max(0.5, h.grid) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [h.grid])

  const params = useMemo(() => harmParams(qs, h), [qs, h])
  const stale = h.run !== null && h.run !== params
  const q = useApi<HarmonizationRun>(h.run ? `/api/harmonization?${h.run}` : null)
  const r = q.data
  const runP = useMemo(() => new URLSearchParams(h.run ?? ''), [h.run])
  const aoiName = (id: string) => (id === 'none' ? 'All imported observations (no AOI)' : id.startsWith('region:') ? regions.find((x) => x.id === id)?.name ?? id : 'Custom AOI')

  // Overlap of the selected sensors in the imported data (a helper for choosing the analysis range).
  const overlap = useMemo(() => {
    const prods = inv.data?.products ?? []
    const mp = h.modis.split(',')
    const firstLast = (plats: string[]) => {
      const ps = prods.filter((p) => plats.includes(p.platform))
      if (!ps.length) return null
      return [ps.map((p) => p.first_date).sort()[0], ps.map((p) => p.last_date).sort().slice(-1)[0]] as [string, string]
    }
    const a = firstLast(mp), b = firstLast([VIIRS_PLATFORM[h.viirs]])
    if (!a || !b) return null
    const lo = a[0] > b[0] ? a[0] : b[0], hi = a[1] < b[1] ? a[1] : b[1]
    return lo <= hi ? [lo, hi] as [string, string] : null
  }, [inv.data, h.modis, h.viirs])
  const missing = [...h.modis.split(','), VIIRS_PLATFORM[h.viirs]].filter((p) => availPlat.length && !availPlat.includes(p))
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6" data-testid="harmonization-page">
      <section className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-semibold"><Icon name="harmonize" className="h-5 w-5" />Harmonization diagnostics</h1>
            <p className="text-sm text-muted">Multi-sensor fusion validation, then the cross-sensor MODIS–VIIRS comparison and calibration from one reproducible run.</p>
          </div>
          <StatusBadge r={h.run && r ? r : null} />
        </div>
        <ol className="mt-3 flex flex-wrap gap-1 text-[11px]" aria-label="Workflow">
          {STEPS.map(([id, label], i) => (
            <li key={id}><button className="rounded-full border border-line px-2 py-0.5 hover:bg-soft" onClick={() => go(id)}><b>{i + 1}</b> {label}</button>{i < STEPS.length - 1 && <span className="mx-0.5 text-muted">→</span>}</li>))}
        </ol>
        <p className="mt-2 text-[11px] text-muted">MODIS is used as the reference scale for continuity with the long MODIS record, not as ground truth. Satellite coverage is not verified (FIRMS lists detections only).
          The pairwise calibrated values below are shown only here and only when the run passes its validation rules. The harmonized multi-sensor series (fusion) can be chosen as "Harmonized (all sensors)" in the calendar, history, Insights and the Explore heatmap, always labelled with its validation status; original observations stay available everywhere.</p>
      </section>

      <Panel id="h-fusion" title="Multi-sensor historical fusion (1.5): all satellites on the MODIS Aqua scale"
        info="Every eligible satellite is calibrated to MODIS Aqua with the 1.4 day-level ratio and the calibrated estimates are averaged, never summed. Validated leave-reference-out: Aqua is predicted from the other sensors with ratios fitted on earlier years only. Uses the top-bar AOI and quality filters over the whole imported record.">
        <FusionPanel />
      </Panel>

      <Panel id="h-settings" title="Pairwise MODIS–VIIRS calibration run"
        info="Region, period and quality filters come from the top bar. Only the sensor pair and matching settings below are specific to this run.">
        <div className="flex flex-wrap items-end gap-2 text-xs" data-testid="h-controls">
          <Seg label="VIIRS sensor" value={h.viirs} onChange={(v) => h.set({ viirs: v })}
            options={(['VIIRS_SNPP', 'VIIRS_N20', 'VIIRS_N21'] as const).map((v) => ({ value: v, label: SERIES_SHORT[v].replace('VIIRS ', '') + (avail.length && !avail.includes(v) ? ' (not imported)' : '') }))} />
          <Seg label="MODIS platform" value={h.modis} onChange={(v) => h.set({ modis: v })} options={[{ value: 'Aqua', label: 'Aqua', title: 'Near-simultaneous with VIIRS' }, { value: 'Terra', label: 'Terra', title: 'Morning orbit: few or no matches expected' }, { value: 'Aqua,Terra', label: 'Both' }]} />
          <Seg label="Time tolerance" value={h.tol} onChange={(v) => h.set({ tol: v })} options={[10, 20, 30, 60, 90].map((v) => ({ value: v, label: `±${v} min` }))} />
          <Seg label="Comparison grid" value={h.grid} onChange={(v) => h.set({ grid: v })} options={[0.1, 0.25, 0.5, 1].map((v) => ({ value: v, label: `${v}°` }))} />
          <Seg label="Measurement" value={h.metric} onChange={(v) => h.set({ metric: v })} options={[{ value: 'detections', label: 'Detections' }, { value: 'frp_sum', label: 'FRP sum (evaluation only)' }]} />
          <Seg label="Units in model" value={h.unitSet} onChange={(v) => h.set({ unitSet: v })} options={[{ value: 'matched', label: 'Matched only' }, { value: 'matched_plus_proxy', label: '+ proxy one-sided' }]} />
          <Seg label="Held-out share" value={h.testFraction} onChange={(v) => h.set({ testFraction: v })} options={[0.1, 0.2, 0.3].map((v) => ({ value: v, label: `last ${v * 100}%` }))} />
          <button className="btn btn-primary" data-testid="h-run" onClick={() => h.set({ run: params, selCell: null })}>{h.run ? 'Run again' : 'Run harmonization'}</button>
          {r && <a className="btn" href={`/api/export/harmonization.zip?${h.run}`} download data-testid="h-zip">Validation package (ZIP)</a>}
        </div>
        {missing.length > 0 && <p className="mt-1 text-[11px] text-amber-700">Not in the imported data: {missing.join(', ')}. Choose another sensor pair.</p>}
        {h.metric === 'frp_sum' && <p className="mt-1 text-[11px] text-amber-700">FRP sums can be evaluated but are never applied to the map or series: the log-log model did not reduce held-out FRP errors on the full archive.</p>}
        <p className="mt-1 text-[11px] text-muted">A run over many years and a large region can take up to a minute.{stale && <b className="ml-1 text-amber-700" data-testid="h-stale">Settings or filters changed since the last run: press Run again.</b>}</p>
        {overlap && (overlap[0] !== s.start || overlap[1] !== s.end) && <button className="mt-1 text-[11px] text-accent underline" data-testid="h-use-overlap" onClick={() => s.set({ start: overlap[0], end: overlap[1], date: s.date < overlap[0] || s.date > overlap[1] ? overlap[1] : s.date })}>
          Use all years with both sensors ({overlap[0]} → {overlap[1]})</button>}
      </Panel>

      {!h.run ? (
        <section className="panel p-6 text-center text-sm text-muted" data-testid="h-notrun">Pick the sensor pair above, then press <b>Run harmonization</b>. The region, period and filters come from the top bar. Nothing is estimated before a run.</section>
      ) : q.error ? <ErrorNote msg={q.error} /> : !r ? <section className="panel p-6"><Loading label="Matching events and fitting the model…" /></section> : <>
        <Panel id="h-compare" title={`2 · Compare sensors: ${aoiName(runP.get('aoi') ?? 'none')}, ${runP.get('start')} → ${runP.get('end')}`}
          info="Stage 1 puts both sensors on one grid; stage 2 pairs MODIS and VIIRS observation events of the same cell and overpass.">
          <PipelineCards r={r} />
          <div className="mt-3"><MatchingProcess r={r} /></div>
        </Panel>

        <Panel id="h-harmonize" title="3 · Harmonize: statistical calibration" info="ln(1+M) = α + β ln(1+V) fitted on the earlier units, tested on the later, held-out units.">
          {r.stage3.status !== 'ok' ? <p className="text-xs text-amber-700" data-testid="h-insufficient">Not fitted: {r.stage3.reason}</p>
            : <Stage3 r={r} unit={r.config.metric === 'detections' ? 'detections' : 'MW'} />}
        </Panel>

        <Panel id="h-validity" title="4 · Evaluate errors and validation status" info="Project rules (not a NASA standard) deciding whether this run may be applied to the map and series. All checks use the held-out period only.">
          <div className="grid gap-3 xl:grid-cols-2">
            <div>
              <p className="mb-2 text-sm"><StatusBadge r={r} /> <span className="ml-1 text-xs">{r.validity.label}.</span></p>
              <ValidityChecks checks={r.validity.checks} testid="hvalidity-checks" />
              <p className="mt-1 text-[11px] text-muted">{r.validity.scope}</p>
            </div>
            <div>
              <h5 className="mb-1 text-xs font-semibold">Held-out errors against simple alternatives</h5>
              <ErrorComparison r={r} />
              <p className="mt-1 text-[11px] text-muted">These errors measure agreement with the MODIS <i>scale</i> for matched cells and overpasses, not the accuracy of fire detection.
                A model that only beats "unadjusted VIIRS" mostly corrects the overall level; beating the constants shows that the VIIRS value adds information.</p>
            </div>
          </div>
        </Panel>

        <Panel id="h-aggregate" title="5 · Validate daily totals: day-level ratio (1.4)" info="A second, additive method for AOI totals: c = Σ MODIS / Σ VIIRS over training days, tested on later days, year by year and with a month-block bootstrap. Its own gate decides whether a calibrated total may be drawn.">
          <AggregatePanel run={h.run} />
        </Panel>

        <Panel id="h-map" title="6 · View on the map" info="Original MODIS and VIIRS detections, the matched pairs and, for a validated run, the experimental MODIS-scale estimates on the comparison grid. The error layer shows held-out MAE per region.">
          <div className="flex flex-col gap-3 lg:flex-row">
            <div className="min-w-0 flex-1"><HarmonizationMap run={h.run} /></div>
            <aside className="w-full shrink-0 lg:w-[360px]"><WindowDetails run={h.run} /></aside>
          </div>
        </Panel>

        <Panel id="h-history" title="7 · Historical patterns: original vs calibrated" info="Original series are the same detections as the rest of the app. A calibrated line is drawn only when its method passes its own held-out rules for daily totals.">
          <div className="mb-2 flex flex-wrap items-end gap-2 text-xs">
            <Seg label="Calibration method" value={h.histMethod} onChange={(v) => h.set({ histMethod: v })} options={[
              { value: 'ratio', label: 'Day-level ratio (1.4)', title: 'Calibrates AOI daily totals directly' },
              { value: 'event', label: 'Event model (1.0 baseline)', title: 'Sums the event-level log-log model; its daily totals did not pass validation' }]} />
          </div>
          {h.histMethod === 'ratio' ? <AggregateSeries run={h.run} /> : <HarmonizationSeries run={h.run} />}
        </Panel>

        <Panel title="Interpretation and limits">
          <ul className="list-disc space-y-1 pl-5 text-xs">{r.interpretation.map((t) => <li key={t}>{t}</li>)}
            <li>Calibrated cells are estimates on a {r.stage1.grid_deg}° grid computed from VIIRS observation events; they are not hotspots, not burned area and not MODIS observations.</li>
            <li>Dataset revision {r.dataset_revision} · {r.method_version} · {fmtNum(r.stage3.n_units)} model units.</li></ul>
        </Panel>
      </>}
    </div>
  )
}
