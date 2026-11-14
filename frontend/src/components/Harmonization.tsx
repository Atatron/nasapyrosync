import { useMemo, useState } from 'react'
import { useApi } from '../api'
import { useFilterQS } from '../hooks'
import { useApp } from '../state'
import { SERIES_COLOR, SERIES_SHORT, fmtNum } from '../util'
import { EChart, ErrorNote, Loading, Panel, Seg } from './ui'

// ---- contract of /api/harmonization (added in v1.1) ----
export interface Err { mae: number; rmse: number; mbe: number; n: number }
export interface Harmonization {
  dataset_revision: number
  method_version: string
  config: Record<string, unknown>
  stage1: { unit: string; grid_deg: number; grid_rule: string; measurement: string; filters_applied: string; sensor_note: string }
  stage2: {
    modis_platforms: string[]; viirs_series: string; tolerance_min: number; event_gap_min: number; evidence_radius_deg: number
    events: { modis: number; viirs: number }; candidate_pairs: number; class_counts: Record<string, number>; class_doc: Record<string, string>
    dt_minutes: { histogram: { from_min: number; to_min: number; n: number }[]; median: number | null; max: number | null }
    matching_rule: string; coverage_verification: { status: string; note: string }; platforms_missing: string[]; warning?: string
  }
  stage3: {
    equation: string; prediction: string; estimator: string; unit_set: string; n_units: number; status: 'ok' | 'insufficient'; reason: string | null
    split?: { test_starts: string; rule: string; train_period: [string, string] | null; test_period: [string, string] | null; n_train: number; n_test: number }
    fit?: { alpha: number; beta: number; se_alpha: number; se_beta: number; ci95_alpha: [number, number]; ci95_beta: [number, number]; r2_log: number | null; residual_sd_log: number; n: number; duan_smearing_factor: number }
    evaluation?: {
      held_out: { unadjusted: Err; calibrated: Err; training_mean_reference: Err; improvement_vs_unadjusted: { mae_pct: number | null; rmse_pct: number | null; abs_mbe_pct: number | null; definition: string } }
      definitions: Record<string, string>; retransformation_note: string
      observed_means: { train_M: number; train_V: number; test_M: number; test_V: number }
    }
    bins?: { V_range: string; n: number; mean_V: number; mean_M: number; mean_M_hat: number }[]
    daily_test?: { date: string; M: number; V: number; M_hat: number; units: number }[]
    scatter?: { V: number; M: number; set: string; class: string; date: string }[]
    curve?: { V: number; M_hat: number }[]
  }
  interpretation: string[]
}

export const CLASS_LABEL: Record<string, string> = {
  matched: 'Candidate matches (both detected)',
  viirs_only_proxy: 'VIIRS only · MODIS imaging nearby (proxy)',
  viirs_only_no_evidence: 'VIIRS only · no MODIS evidence',
  modis_only_proxy: 'MODIS only · VIIRS imaging nearby (proxy)',
  modis_only_no_evidence: 'MODIS only · no VIIRS evidence',
}

function f3(v: number | null | undefined, d = 3) { return v === null || v === undefined ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }) }
function pct(v: number | null | undefined) { return v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)} %` }

export default function Harmonization() {
  const qs = useFilterQS()
  const s = useApp()
  const [viirs, setViirs] = useState<'VIIRS_SNPP' | 'VIIRS_N20' | 'VIIRS_N21'>('VIIRS_SNPP')
  const [modis, setModis] = useState<'Aqua' | 'Terra' | 'Aqua,Terra'>('Aqua')
  const [tol, setTol] = useState<number>(30)
  const [grid, setGrid] = useState<number>(0.1)
  const [metric, setMetric] = useState<'detections' | 'frp_sum'>('detections')
  const [unitSet, setUnitSet] = useState<'matched' | 'matched_plus_proxy'>('matched')
  const [testFraction, setTestFraction] = useState<number>(0.2)
  const [run, setRun] = useState<string | null>(null)

  const params = useMemo(() => {
    const p = new URLSearchParams(qs)
    p.set('viirs_series', viirs); p.set('modis_platforms', modis); p.set('tolerance_min', String(tol)); p.set('unit_grid', String(grid))
    p.set('metric', metric); p.set('unit_set', unitSet); p.set('test_fraction', String(testFraction))
    return p.toString()
  }, [qs, viirs, modis, tol, grid, metric, unitSet, testFraction])
  const stale = run !== null && run !== params
  const q = useApi<Harmonization>(run ? `/api/harmonization?${run}` : null)
  const r = q.data
  const unit = metric === 'detections' ? 'detections' : 'MW'

  return (
    <Panel id="harmonization" title="MODIS–VIIRS harmonization (three stages)"
      info="Stage 1 puts both sensors on the same grid cells with the shared filters. Stage 2 pairs MODIS and VIIRS observation events in the same cell within a time tolerance. Stage 3 fits ln(1+M) = α + β ln(1+V) on the earlier units and tests it on later, held-out units. MODIS is the reference scale, not ground truth.">
      <div className="flex flex-wrap items-end gap-2 text-xs" data-testid="harmonization-controls">
        <Seg label="VIIRS sensor" value={viirs} onChange={setViirs} options={[{ value: 'VIIRS_SNPP', label: 'S-NPP' }, { value: 'VIIRS_N20', label: 'NOAA-20' }, { value: 'VIIRS_N21', label: 'NOAA-21' }]} />
        <Seg label="MODIS platform" value={modis} onChange={setModis} options={[{ value: 'Aqua', label: 'Aqua', title: 'Near-simultaneous with VIIRS (afternoon/night orbit)' }, { value: 'Terra', label: 'Terra', title: 'Morning orbit: few matches expected' }, { value: 'Aqua,Terra', label: 'Both' }]} />
        <Seg label="Time tolerance" value={tol} onChange={setTol} options={[10, 20, 30, 60, 90].map((v) => ({ value: v, label: `±${v} min` }))} />
        <Seg label="Comparison grid" value={grid} onChange={setGrid} options={[0.1, 0.25, 0.5, 1].map((v) => ({ value: v, label: `${v}°` }))} />
        <Seg label="Measurement" value={metric} onChange={setMetric} options={[{ value: 'detections', label: 'Detections' }, { value: 'frp_sum', label: 'FRP sum' }]} />
        <Seg label="Units in model" value={unitSet} onChange={setUnitSet} options={[{ value: 'matched', label: 'Matched only' }, { value: 'matched_plus_proxy', label: '+ proxy one-sided', title: 'Adds one-sided events where the other instrument was imaging nearby (unverified)' }]} />
        <Seg label="Held-out share" value={testFraction} onChange={setTestFraction} options={[0.1, 0.2, 0.3].map((v) => ({ value: v, label: `last ${v * 100}%` }))} />
        <button className="btn btn-primary" data-testid="harmonization-run" onClick={() => setRun(params)}>{run ? 'Run again' : 'Run harmonization'}</button>
        {r && r.stage3.status === 'ok' && <a className="btn" href={`/api/export/harmonization.zip?${run}`} download>Validation package (ZIP)</a>}
      </div>
      <p className="mt-1 text-[11px] text-muted">Uses the current analysis range ({s.start} → {s.end}), AOI and quality filters. Long ranges over a large area can take several seconds.{stale && <b className="ml-1 text-amber-700">Settings changed: press Run again.</b>}</p>

      {!run ? null : q.error ? <ErrorNote msg={q.error} /> : !r ? <Loading label="Matching and fitting…" /> : (
        <div className="mt-3 space-y-3" data-testid="harmonization-result">
          <div className="grid gap-3 xl:grid-cols-3">
            <div className="rounded border border-line p-2">
              <h4 className="text-xs font-semibold">Stage 1 · Spatial standardization</h4>
              <p className="mt-1 text-xs">{r.stage1.unit}. {r.stage1.measurement}</p>
              <p className="mt-1 text-[11px] text-muted">{r.stage1.sensor_note} {r.stage1.filters_applied}</p>
            </div>
            <div className="rounded border border-line p-2">
              <h4 className="text-xs font-semibold">Stage 2 · Temporal matching</h4>
              <p className="mt-1 text-xs">{fmtNum(r.stage2.events.modis)} MODIS and {fmtNum(r.stage2.events.viirs)} {SERIES_SHORT[r.stage2.viirs_series]} events; median |Δt| of matches {r.stage2.dt_minutes.median === null ? '—' : `${r.stage2.dt_minutes.median.toFixed(1)} min`}.</p>
              <table className="data mt-1" data-testid="harmonization-classes"><tbody>{Object.entries(r.stage2.class_counts).map(([k, v]) => <tr key={k} title={r.stage2.class_doc[k]}><td>{CLASS_LABEL[k] ?? k}</td><td className="num">{fmtNum(v)}</td></tr>)}</tbody></table>
              {r.stage2.warning && <p className="mt-1 text-[11px] text-amber-700">{r.stage2.warning}</p>}
              {r.stage2.platforms_missing.length > 0 && <p className="mt-1 text-[11px] text-amber-700">Not in the imported data: {r.stage2.platforms_missing.join(', ')}.</p>}
            </div>
            <div className="rounded border border-line p-2">
              <h4 className="text-xs font-semibold">Coverage is not verified</h4>
              <p className="mt-1 text-[11px]">{r.stage2.coverage_verification.note}</p>
            </div>
          </div>

          <div className="rounded border border-line p-2">
            <h4 className="text-xs font-semibold">Stage 3 · Statistical calibration</h4>
            <p className="mt-1 text-xs"><code>{r.stage3.equation}</code> · <code>{r.stage3.prediction}</code></p>
            {r.stage3.status !== 'ok' ? <p className="mt-2 text-xs text-amber-700" data-testid="harmonization-insufficient">Not fitted: {r.stage3.reason}</p> : <Stage3 r={r} unit={unit} />}
          </div>

          <ul className="list-disc pl-5 text-[11px] text-muted">{r.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
    </Panel>
  )
}

export function Stage3({ r, unit }: { r: Harmonization; unit: string }) {
  const s3 = r.stage3
  const fit = s3.fit!, sp = s3.split!, ev = s3.evaluation!
  const ho = ev.held_out
  const scatter = useMemo(() => {
    const lg = (x: number) => Math.log1p(x)
    const tr = (s3.scatter ?? []).filter((p) => p.set === 'train').map((p) => [lg(p.V), lg(p.M)])
    const te = (s3.scatter ?? []).filter((p) => p.set === 'test').map((p) => [lg(p.V), lg(p.M)])
    const curve = (s3.curve ?? []).map((p) => [lg(p.V), lg(p.M_hat)])
    const vmax = Math.max(1, ...curve.map((c) => c[0]))
    return {
      grid: { left: 56, right: 12, top: 44, bottom: 40 }, legend: { top: 0, textStyle: { fontSize: 11 } }, tooltip: { trigger: 'item' },
      xAxis: { type: 'value', name: 'ln(1 + V)  (VIIRS)', nameLocation: 'middle', nameGap: 24, axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', name: 'ln(1 + M)  (MODIS)', nameLocation: 'middle', nameGap: 34, axisLabel: { fontSize: 10 } },
      series: [
        { name: 'Training units', type: 'scatter', symbolSize: 4, itemStyle: { color: SERIES_COLOR.VIIRS_SNPP, opacity: 0.35 }, data: tr },
        { name: 'Held-out units', type: 'scatter', symbolSize: 4, itemStyle: { color: '#ea580c', opacity: 0.45 }, data: te },
        { name: 'Fitted α + β ln(1+V)', type: 'line', showSymbol: false, lineStyle: { width: 2 }, itemStyle: { color: SERIES_COLOR.MODIS }, data: curve },
        { name: 'M = V (no adjustment)', type: 'line', showSymbol: false, lineStyle: { width: 1, type: 'dashed' }, itemStyle: { color: '#94a3b8' }, data: [[0, 0], [vmax, vmax]] },
      ],
    }
  }, [s3])
  const daily = useMemo(() => {
    const d = s3.daily_test ?? []
    return {
      grid: { left: 50, right: 12, top: 30, bottom: 50 }, legend: { top: 0, textStyle: { fontSize: 11 } }, tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: d.map((x) => x.date), axisLabel: { fontSize: 10 } }, yAxis: { type: 'value', axisLabel: { fontSize: 10 } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 6 }],
      series: [
        { name: 'MODIS (observed)', type: 'line', showSymbol: false, itemStyle: { color: SERIES_COLOR.MODIS }, data: d.map((x) => x.M) },
        { name: 'Calibrated from VIIRS', type: 'line', showSymbol: false, itemStyle: { color: '#ea580c' }, data: d.map((x) => +x.M_hat.toFixed(3)) },
        { name: 'VIIRS unadjusted', type: 'line', showSymbol: false, lineStyle: { type: 'dashed', width: 1 }, itemStyle: { color: '#94a3b8' }, data: d.map((x) => x.V) },
      ],
    }
  }, [s3])
  return (
    <div className="mt-2 space-y-3">
      <div className="grid gap-3 xl:grid-cols-2">
        <div>
          <table className="data" data-testid="harmonization-fit"><thead><tr><th>Coefficient</th><th>Estimate</th><th>SE</th><th>95 % CI</th></tr></thead>
            <tbody>
              <tr><td>α</td><td className="num">{f3(fit.alpha, 4)}</td><td className="num">{f3(fit.se_alpha, 4)}</td><td className="num">{f3(fit.ci95_alpha[0], 4)} to {f3(fit.ci95_alpha[1], 4)}</td></tr>
              <tr><td>β</td><td className="num">{f3(fit.beta, 4)}</td><td className="num">{f3(fit.se_beta, 4)}</td><td className="num">{f3(fit.ci95_beta[0], 4)} to {f3(fit.ci95_beta[1], 4)}</td></tr>
            </tbody></table>
          <p className="mt-1 text-[11px] text-muted">Training: {fmtNum(sp.n_train)} units, {sp.train_period?.[0]} → {sp.train_period?.[1]}. Held out: {fmtNum(sp.n_test)} units, {sp.test_period?.[0]} → {sp.test_period?.[1]}. R² (log scale, training) {f3(fit.r2_log)}. {sp.rule}</p>
          <table className="data mt-2" data-testid="harmonization-eval"><thead><tr><th>Held-out estimate ({unit})</th><th>MAE</th><th>RMSE</th><th>MBE</th></tr></thead>
            <tbody>
              <tr><td>Unadjusted VIIRS (M̂ = V)</td><td className="num">{f3(ho.unadjusted.mae)}</td><td className="num">{f3(ho.unadjusted.rmse)}</td><td className="num">{f3(ho.unadjusted.mbe)}</td></tr>
              <tr><td><b>Calibrated</b></td><td className="num"><b>{f3(ho.calibrated.mae)}</b></td><td className="num"><b>{f3(ho.calibrated.rmse)}</b></td><td className="num"><b>{f3(ho.calibrated.mbe)}</b></td></tr>
              <tr className="text-muted"><td>Training-mean constant (context)</td><td className="num">{f3(ho.training_mean_reference.mae)}</td><td className="num">{f3(ho.training_mean_reference.rmse)}</td><td className="num">{f3(ho.training_mean_reference.mbe)}</td></tr>
              <tr><td>Improvement vs unadjusted</td><td className="num">{pct(ho.improvement_vs_unadjusted.mae_pct)}</td><td className="num">{pct(ho.improvement_vs_unadjusted.rmse_pct)}</td><td className="num">{pct(ho.improvement_vs_unadjusted.abs_mbe_pct)} (|MBE|)</td></tr>
            </tbody></table>
          <p className="mt-1 text-[11px] text-muted">{ho.improvement_vs_unadjusted.definition} MBE = mean(prediction − MODIS). {ev.retransformation_note}</p>
        </div>
        <EChart ariaLabel="Log-log scatter of MODIS against VIIRS with the fitted calibration curve" option={scatter} height={300} />
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <div>
          <h5 className="text-xs font-semibold">Held-out units by VIIRS value</h5>
          <table className="data mt-1"><thead><tr><th>V</th><th>Units</th><th>Mean V</th><th>Mean MODIS</th><th>Mean M̂</th></tr></thead>
            <tbody>{(s3.bins ?? []).map((b) => <tr key={b.V_range}><td>{b.V_range}</td><td className="num">{fmtNum(b.n)}</td><td className="num">{f3(b.mean_V, 2)}</td><td className="num">{f3(b.mean_M, 2)}</td><td className="num">{f3(b.mean_M_hat, 2)}</td></tr>)}</tbody></table>
        </div>
        <div>
          <h5 className="text-xs font-semibold">Held-out period: daily sums over matched units</h5>
          <EChart ariaLabel="Held-out daily sums: MODIS observed, calibrated and unadjusted VIIRS" option={daily} height={220} />
          <p className="text-[11px] text-muted">Sums over comparison units only (not the full daily series). The existing per-sensor daily series are unchanged.</p>
        </div>
      </div>
    </div>
  )
}
