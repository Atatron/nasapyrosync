import { useEffect, useRef, useState } from 'react'
import { clearCache, getJSON, postJSON, useApi, type Imagery } from '../api'
import { useFilterQS, useInventory } from '../hooks'
import { applyViewConfig, frameWindow, useApp } from '../state'
import { SERIES_COLOR, fmtNum } from '../util'
import { ErrorNote, Icon, Loading, Panel, Seg, Warnings } from '../components/ui'

type Tab = 'import' | 'history' | 'firms' | 'exports' | 'methods'

function ReadonlyNotice({ what }: { what: string }) {
  const health = useApi<{ demo_note?: string | null }>('/api/health')
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Panel title={what}>
        <div className="space-y-2 text-sm" data-testid="readonly-notice">
          <p><b>This is the read-only online demo.</b> It contains {health.data?.demo_note ?? 'a fixed set of FIRMS data'} It cannot store new data.</p>
          <p className="text-muted">To import new FIRMS downloads or refresh from the FIRMS API, run PyroSync locally (see the README: <code>scripts/start.bat</code> on Windows, <code>./scripts/start.sh</code> on macOS/Linux). Everything else here works the same as the local version.</p>
        </div>
      </Panel>
      <CurrentData />
    </div>
  )
}

export default function DataMethods() {
  const health = useApi<{ readonly?: boolean }>('/api/health')
  const ro = !!health.data?.readonly
  const [tab, setTab] = useState<Tab>(ro ? 'methods' : 'import')
  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="mr-1 text-base font-semibold">Methods and Data Inventory</h1>
        <Seg<Tab> pills label="Section" value={tab} onChange={setTab} options={[
          { value: 'import', label: 'Import data' }, { value: 'history', label: 'Import history' }, { value: 'firms', label: 'NASA FIRMS refresh' },
          { value: 'exports', label: 'Exports and view config' }, { value: 'methods', label: 'Methodology' }]} />
      </div>
      {tab === 'import' && (ro ? <ReadonlyNotice what="Import FIRMS CSV or ZIP" /> : <ImportTab />)}
      {tab === 'history' && <HistoryTab />}
      {tab === 'firms' && (ro ? <ReadonlyNotice what="FIRMS API refresh" /> : <FirmsTab />)}
      {tab === 'exports' && <ExportsTab />}
      {tab === 'methods' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="flex min-w-0 flex-col gap-4 lg:col-span-5">
            <Inventory />
            <LocalSync />
            <QuickExports />
          </div>
          <div className="min-w-0 lg:col-span-7"><Methods /></div>
        </div>
      )}
    </div>
  )
}

interface Report {
  batch_id: string; status: string; dry_run: boolean; files_processed: number; rows_read: number; accepted_rows: number; rejected_rows: number
  new_observations: number; duplicate_rows: number; duplicates_of_existing: number; superseded_nrt_rows: number | null; date_range: [string, string] | null
  platforms: Record<string, number>; source_products: Record<string, number>; versions: Record<string, number>
  geographic_extent: { west: number; south: number; east: number; north: number } | null; warnings: string[]; dataset_revision: number; revision_changed: boolean
  rejection_reasons: Record<string, number>
  files?: { file: string; instrument: string | null; platforms: string[]; stream: string; versions: string[]; rows_read: number; accepted: number; rejected: number; status: string; declared_window: [string, string] | null; columns: string[]; preview: Record<string, string>[]; warnings: string[] }[]
}

function ReportView({ r }: { r: Report }) {
  const [showFiles, setShowFiles] = useState(false)
  return (
    <div className="space-y-2 text-xs" data-testid="import-report">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {([['Files processed', r.files_processed], ['Rows read', r.rows_read], ['Accepted rows', r.accepted_rows], ['Rejected rows', r.rejected_rows],
          [r.dry_run ? 'Would be new' : 'New observations', r.new_observations], ['Duplicate rows', r.duplicate_rows], ['NRT rows superseded by SP', r.superseded_nrt_rows ?? '—'], ['Dataset revision', `${r.dataset_revision}${r.revision_changed ? ' (changed)' : ' (unchanged)'}`]] as [string, number | string][]).map(([k, v]) => (
          <div key={k} className="rounded-lg bg-soft p-2"><div className="label">{k}</div><div className="num text-sm font-semibold" data-testid={`rep-${k.replace(/\W+/g, '-').toLowerCase()}`}>{typeof v === 'number' ? fmtNum(v) : v}</div></div>))}
      </div>
      <p><b>Date range:</b> {r.date_range ? `${r.date_range[0]} → ${r.date_range[1]}` : '—'} · <b>Platforms:</b> {Object.entries(r.platforms).map(([k, v]) => `${k} ${fmtNum(v)}`).join(', ') || '—'}</p>
      <p><b>Products:</b> {Object.entries(r.source_products).map(([k, v]) => `${k} (${fmtNum(v)})`).join(', ') || '—'} · <b>Versions:</b> {Object.keys(r.versions).join(', ') || '—'}</p>
      {r.geographic_extent && <p><b>Geographic extent:</b> lon {r.geographic_extent.west} → {r.geographic_extent.east}, lat {r.geographic_extent.south} → {r.geographic_extent.north} (a bounding box, not a country boundary)</p>}
      {Object.keys(r.rejection_reasons).length > 0 && <div><b>Rejection reasons:</b><ul className="list-disc pl-5">{Object.entries(r.rejection_reasons).map(([k, v]) => <li key={k}>{fmtNum(v)} × {k}</li>)}</ul></div>}
      <Warnings items={r.warnings} />
      {r.files && <button className="text-accent underline" onClick={() => setShowFiles(!showFiles)}>{showFiles ? 'Hide' : 'Show'} per-file schema, mapping and preview ({r.files.length} files)</button>}
      {showFiles && r.files && (
        <div className="max-h-[420px] overflow-auto rounded-lg border border-line">
          <table className="data"><thead><tr><th>File</th><th>Schema</th><th>Platforms</th><th>Stream</th><th>Version</th><th>Declared window</th><th>Rows</th><th>Accepted</th><th>Rejected</th><th>Status</th></tr></thead>
            <tbody>{r.files.map((f) => <tr key={f.file}><td className="max-w-[260px] truncate" title={f.file}>{f.file}</td><td>{f.instrument ?? 'unknown'}</td><td>{f.platforms.join(', ') || '—'}</td><td>{f.stream}</td><td>{f.versions.join(', ') || '—'}</td><td>{f.declared_window ? f.declared_window.join(' → ') : '—'}</td><td className="num">{f.rows_read}</td><td className="num">{f.accepted}</td><td className="num">{f.rejected}</td><td title={f.warnings.join('; ')}>{f.status}</td></tr>)}</tbody></table>
          {r.files[0]?.preview?.length > 0 && <div className="p-2"><div className="label mb-1">Preview: {r.files.find((f) => f.preview.length)?.file}</div>
            <table className="data"><thead><tr>{Object.keys(r.files.find((f) => f.preview.length)!.preview[0]).map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{r.files.find((f) => f.preview.length)!.preview.map((row, i) => <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody></table></div>}
        </div>
      )}
      {!r.dry_run && <p className="flex gap-3"><a className="text-accent underline" href={`/api/imports/${r.batch_id}/report.json`} download>Download validation report (JSON)</a><a className="text-accent underline" href={`/api/imports/${r.batch_id}/rejections.csv`} download>Download rejected rows (CSV)</a></p>}
    </div>
  )
}

function ImportTab() {
  const s = useApp()
  const [files, setFiles] = useState<File[]>([])
  const [uploadId, setUploadId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const inp = useRef<HTMLInputElement>(null)

  const runJob = async (dry: boolean) => {
    if (!uploadId) return
    setErr(null)
    setBusy(dry ? 'Inspecting & validating (nothing is committed)…' : 'Committing import…')
    try {
      const { job_id } = await postJSON<{ job_id: string }>('/api/imports', { upload_id: uploadId, dry_run: dry })
      for (;;) {
        await new Promise((r) => setTimeout(r, 700))
        const j = await fetch(`/api/imports/jobs/${job_id}`).then((r) => r.json())
        if (j.progress?.stage === 'reading') setBusy(`${dry ? 'Inspecting' : 'Importing'} file ${j.progress.index + 1}/${j.progress.total} · ${fmtNum(j.progress.rows_read)} rows read…`)
        if (j.status === 'done') { setReport(j.report); if (!dry) { setUploadId(null); setFiles([]); clearCache(); s.set({ revision: j.report.dataset_revision }) } break }
        if (j.status === 'error') { setErr(j.error); break }
      }
    } catch (e) { setErr((e as Error).message) }
    setBusy(null)
  }
  const upload = async () => {
    setErr(null); setReport(null); setBusy('Uploading…')
    try {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      const r = await fetch('/api/uploads', { method: 'POST', body: fd })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail ?? 'Upload failed')
      setUploadId(j.upload_id)
      setBusy(null)
      return j.upload_id as string
    } catch (e) { setErr((e as Error).message); setBusy(null); return null }
  }
  useEffect(() => { if (uploadId && !report) runJob(true) // auto-inspect after upload
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadId])

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Panel title="Import FIRMS CSV or ZIP" info="Pipeline: inspect → validate → normalize → deduplicate/reconcile → commit. Re-importing the same data does not change counts. A failed import is rolled back and previous data stay intact.">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input ref={inp} type="file" multiple accept=".csv,.zip" className="field max-w-full" data-testid="import-file" aria-label="Choose CSV or ZIP files"
              onChange={(e) => { setFiles(Array.from(e.target.files ?? [])); setUploadId(null); setReport(null) }} />
            <button className="btn btn-primary" disabled={!files.length || !!busy} onClick={upload} data-testid="inspect-btn">1 · Upload &amp; inspect</button>
            <button className="btn btn-primary" disabled={!uploadId || !report || !report.dry_run || !!busy} onClick={() => runJob(false)} data-testid="commit-btn">2 · Commit import</button>
          </div>
          {busy && <Loading label={busy} />}
          {err && <ErrorNote msg={err} />}
          {report && <><div className="text-sm font-semibold">{report.dry_run ? 'Inspection & validation report (not yet committed)' : 'Import report (committed)'}</div><ReportView r={report} /></>}
          {!report && !busy && <p className="text-xs text-muted">Accepted: FIRMS MODIS (brightness/bright_t31) and VIIRS (bright_ti4/bright_ti5) CSV schemas, and ZIP archives containing them. Each row is assigned by its own acq_date/acq_time (UTC), never by the file name. Large datasets: use the CLI (see README).</p>}
        </div>
      </Panel>
      <CurrentData />
    </div>
  )
}

/** Dataset inventory: real rows and date span per sensor, from /api/inventory. */
function Inventory() {
  const inv = useInventory()
  if (!inv.data) return <Panel title="Currently loaded dataset"><Loading /></Panel>
  const d = inv.data
  const by = new Map<string, { label: string; rows: number; first: string; last: string; files: number }>()
  for (const p of d.products) {
    const x = by.get(p.series) ?? { label: p.series_label, rows: 0, first: p.first_date, last: p.last_date, files: 0 }
    x.rows += p.rows; x.files += 1
    if (p.first_date < x.first) x.first = p.first_date
    if (p.last_date > x.last) x.last = p.last_date
    by.set(p.series, x)
  }
  const [a, b] = d.date_range ?? ['', '']
  const span = a && b ? (Date.parse(b) - Date.parse(a)) || 1 : 1
  return (
    <Panel title="Currently loaded dataset" info="Totals of the imported FIRMS archive, before any filter. Bars show each sensor's first and last day within the whole record.">
      <div className="rounded-lg border border-line p-3" data-testid="current-data">
        <div className="font-mono text-xl font-semibold tabular-nums"><span data-testid="obs-total">{fmtNum(d.observations_total)}</span> <span className="font-sans text-sm font-normal text-muted">observations</span></div>
        <div className="mt-0.5 text-xs text-muted">Date range {d.date_range ? `${d.date_range[0]} → ${d.date_range[1]}` : '—'} · revision <b data-testid="revision">{d.dataset_revision}</b> · {d.processing_version} · {fmtNum(d.observations_superseded)} superseded NRT rows kept for audit</div>
      </div>
      <ul className="mt-3 space-y-2" aria-label="Rows by sensor">
        {Array.from(by.entries()).map(([k, x]) => (
          <li key={k} className="rounded-lg border border-line p-2.5">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="flex min-w-0 items-center gap-1.5 font-medium"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SERIES_COLOR[k] }} /><span className="truncate">{x.label}</span></span>
              <span className="font-mono tabular-nums">{fmtNum(x.rows)} rows</span>
            </div>
            <div className="mt-1.5 h-1.5 rounded-full bg-soft" aria-hidden>
              <div className="h-1.5 rounded-full" style={{ background: SERIES_COLOR[k], marginLeft: `${((Date.parse(x.first) - Date.parse(a)) / span) * 100}%`, width: `${Math.max(1, ((Date.parse(x.last) - Date.parse(x.first)) / span) * 100)}%` }} />
            </div>
            <div className="mt-1 font-mono text-[10px] tabular-nums text-muted">{x.first} → {x.last}</div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function LocalSync() {
  return (
    <Panel title="Refresh data locally">
      <p className="text-xs text-muted">The online demo is read-only. To import new FIRMS downloads or refresh from the FIRMS API, run PyroSync on your computer with your own FIRMS key.</p>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 rounded-lg bg-zinc-950 px-3 py-2 font-mono text-[11px] text-zinc-100 dark:bg-zinc-950">
        <span>Windows: scripts/start.bat</span><span className="text-zinc-500">|</span><span>macOS / Linux: ./scripts/start.sh</span>
      </div>
    </Panel>
  )
}

function QuickExports() {
  const s = useApp()
  const qs = useFilterQS()
  const [w0, w1] = frameWindow(s.date, s.frameMode)
  return (
    <Panel title="Export" info="The same files as the Export menu in the top bar, for the current area, dates and filters. Each comes with a manifest.">
      <div className="flex flex-wrap gap-2">
        <a className="btn btn-primary" href={`/api/export/daily.zip?${qs}&series=${s.series}&metric=${s.metric}`} download><Icon name="download" />Export CSV</a>
        <a className="btn" href={`/api/export/grid.geojson?${qs}&date=${s.date}&mode=${s.frameMode}`} download><Icon name="download" />Export GeoJSON</a>
      </div>
      <p className="mt-2 text-[11px] text-muted">CSV: daily summary {s.start} → {s.end}. GeoJSON: {s.grid}° cells for the map window {w0} → {w1}.</p>
    </Panel>
  )
}

function CurrentData() {
  const inv = useInventory()
  if (!inv.data) return <Panel title="Currently loaded"><Loading /></Panel>
  const d = inv.data
  return (
    <Panel title="Currently loaded">
      <div className="space-y-1 text-xs" data-testid="current-data">
        <p><b className="num" data-testid="obs-total">{fmtNum(d.observations_total)}</b> observations ({fmtNum(d.observations_superseded)} superseded NRT rows retained for audit)</p>
        <p>Date range: <b>{d.date_range ? `${d.date_range[0]} → ${d.date_range[1]}` : '—'}</b></p>
        <p>Dataset revision <b data-testid="revision">{d.dataset_revision}</b> · {d.processing_version} · {d.import_batches} import batch(es)</p>
        <p>Coverage intervals: {d.intervals.map((i) => `${i.series} ${i.origin} ×${i.count} (${i.first}→${i.last})`).join('; ') || 'none'}</p>
      </div>
    </Panel>
  )
}

function HistoryTab() {
  const rev = useApp((s) => s.revision)
  const q = useApi<{ batches: Report[] & { started_at?: string; origin?: string; label?: string }[] }>(`/api/imports?_rev=${rev}`)
  return (
    <Panel title="Import history">
      {!q.data ? <Loading /> : (
        <div className="overflow-x-auto"><table className="data"><thead><tr><th>Batch</th><th>Origin</th><th>Label</th><th>Rows read</th><th>New</th><th>Duplicates</th><th>Rejected</th><th>Superseded</th><th>Revision</th><th>Reports</th></tr></thead>
          <tbody>{(q.data.batches as unknown as (Report & { origin: string; label: string })[]).map((b) => <tr key={b.batch_id}><td className="whitespace-nowrap">{b.batch_id}</td><td>{b.origin}</td><td className="max-w-[200px] truncate" title={b.label}>{b.label}</td>
            <td className="num">{fmtNum(b.rows_read)}</td><td className="num">{fmtNum(b.new_observations)}</td><td className="num">{fmtNum(b.duplicate_rows)}</td><td className="num">{fmtNum(b.rejected_rows)}</td><td className="num">{b.superseded_nrt_rows ?? 0}</td><td>{b.dataset_revision}</td>
            <td className="whitespace-nowrap"><a className="text-accent underline" href={`/api/imports/${b.batch_id}/report.json`}>JSON</a> · <a className="text-accent underline" href={`/api/imports/${b.batch_id}/rejections.csv`}>rejections</a></td></tr>)}</tbody></table></div>
      )}
    </Panel>
  )
}

function FirmsTab() {
  const s = useApp()
  const st = useApi<{ key_configured: boolean; sources: string[]; max_day_range: number; note: string }>('/api/firms/status')
  const [form, setForm] = useState({ source: 'VIIRS_NOAA20_SP', west: 108.5, south: -4.2, east: 119.5, north: 4.5, start: s.start, end: s.start })
  const [job, setJob] = useState<{ id: string; status: string; message: string; error: string | null; windows_done: number; windows_total: number; rows_downloaded: number; cached_hits: number } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!job || ['done', 'error', 'cancelled'].includes(job.status)) return
    const t = setTimeout(async () => {
      const j = await getJSON<typeof job>(`/api/firms/jobs/${job.id}?t=${Date.now()}`).catch(() => job)
      setJob(j)
      if (j?.status === 'done') { clearCache(); const h = await fetch('/api/health').then((r) => r.json()); s.set({ revision: h.dataset_revision }) }
    }, 1000)
    return () => clearTimeout(t)
  }, [job, s])
  const upd = (k: string, v: string | number) => setForm({ ...form, [k]: v })
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title="Optional NASA FIRMS Area API refresh">
        {!st.data ? <Loading /> : (
          <div className="space-y-3 text-xs">
            <p className={st.data.key_configured ? 'text-emerald-700' : 'text-amber-800'}>{st.data.key_configured ? 'A FIRMS_MAP_KEY is configured on the server (it is never sent to the browser).' : 'No FIRMS_MAP_KEY is configured. Local imports and all analysis work without it. To enable refresh, add FIRMS_MAP_KEY to the .env file and restart.'}</p>
            <p className="text-muted">{st.data.note} Requests are split into windows of ≤{st.data.max_day_range} days, cached on disk, retried with backoff on rate limits, and passed through the same validation pipeline as uploads. Requires internet access.</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <label className="col-span-full flex flex-col gap-1">Source<select className="field" value={form.source} onChange={(e) => upd('source', e.target.value)}>{st.data.sources.map((x) => <option key={x}>{x}</option>)}</select></label>
              {(['west', 'south', 'east', 'north'] as const).map((k) => <label key={k} className="flex flex-col gap-1">{k}<input type="number" step="0.01" className="field" value={form[k]} onChange={(e) => upd(k, Number(e.target.value))} /></label>)}
              <label className="flex flex-col gap-1">Start<input type="date" className="field" value={form.start} onChange={(e) => upd('start', e.target.value)} /></label>
              <label className="flex flex-col gap-1">End<input type="date" className="field" value={form.end} onChange={(e) => upd('end', e.target.value)} /></label>
            </div>
            <div className="flex gap-2">
              <button className="btn btn-primary" disabled={!st.data.key_configured || (!!job && !['done', 'error', 'cancelled'].includes(job.status))} onClick={async () => {
                setErr(null)
                try { setJob(await postJSON('/api/firms/jobs', form)) } catch (e) { setErr((e as Error).message) }
              }}>Start refresh</button>
              {job && !['done', 'error', 'cancelled'].includes(job.status) && <button className="btn" onClick={() => postJSON(`/api/firms/jobs/${job.id}/cancel`, {}).then((j) => setJob(j as typeof job))}>Cancel</button>}
            </div>
            {err && <ErrorNote msg={err} />}
            {job && <div className="rounded-lg bg-soft p-2"><b>{job.status}</b> · windows {job.windows_done}/{job.windows_total} (cached {job.cached_hits}) · rows {fmtNum(job.rows_downloaded)}<br />{job.message}{job.error && <span className="text-red-700"> {job.error}</span>}</div>}
          </div>
        )}
      </Panel>
      <Panel title="Archive downloads">
        <div className="prose-methods">
          <p>For long histories (e.g. 2012–present), the FIRMS archive download tool is usually more practical than many API calls: <a href="https://firms.modaps.eosdis.nasa.gov/download/" target="_blank" rel="noreferrer">firms.modaps.eosdis.nasa.gov/download</a>. Import the resulting CSV/ZIP here or with the CLI; standard-processing (SP/archive) records supersede NRT records for the same platform and UTC day.</p>
          <p>Compare against the official map: <a href="https://firms.modaps.eosdis.nasa.gov/map/" target="_blank" rel="noreferrer">NASA FIRMS Fire Map</a>. Set the same date and sensor layers there manually (deep-link parameters were not verified, so none are generated). Expect consistency for matching source data and filters, not pixel-identical screenshots.</p>
        </div>
      </Panel>
    </div>
  )
}

function ExportsTab() {
  const s = useApp()
  const [msg, setMsg] = useState<string | null>(null)
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title="Exports">
        <p className="text-xs text-muted">Use the <b>Export</b> menu in the top bar: daily summary CSV, filtered observations CSV, aggregated grid GeoJSON (real cell polygons), AOI GeoJSON, view configuration, and local view URL. Each data export carries a manifest with AOI, UTC time range, sensors, quality/type filters, metric definitions, grid configuration, dataset revision, source products/versions, processing version and export time. Values come from the same queries that power the screen.</p>
      </Panel>
      <Panel title="Restore a view configuration">
        <input type="file" accept=".json,application/json" className="field" aria-label="Load view configuration" onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return
          try { s.set({ ...applyViewConfig(JSON.parse(await f.text())), page: 'explore' }); setMsg(null) } catch (err) { setMsg((err as Error).message) }
        }} />
        {msg && <div className="mt-2"><ErrorNote msg={msg} /></div>}
        <p className="mt-2 text-xs text-muted">View configurations and URLs contain settings only — never uploaded data or credentials. Custom AOIs are referenced by an id registered on this machine; export the AOI GeoJSON to move it elsewhere.</p>
      </Panel>
    </div>
  )
}

export function Methods() {
  const inv = useInventory()
  const img = useApi<Imagery>('/api/imagery/layers')
  return (
    <Panel title="Methodology, definitions and limitations">
      <div className="prose-methods max-w-4xl">
        <p className="rounded-lg bg-soft p-3"><b>Independent hackathon prototype using NASA FIRMS data and, where enabled, NASA GIBS imagery. Not an official NASA application.</b> Nothing here is a fire forecast, an emergency warning, or a validated cross-sensor calibration.</p>
        <h3>What FIRMS detections represent</h3>
        <ul>
          <li>Each record is a satellite pixel flagged as containing one or more thermal anomalies (active fires, and other hot sources such as volcanoes or industrial sites). The coordinates are the pixel centre.</li>
          <li>A detection is not a separate fire event; one fire can produce many detections across pixels and overpasses. Detection counts and occupied grid cells are not burned area, and grid cells are not burned-area polygons.</li>
          <li>FIRMS active-fire files list only positive detections. The MODIS user guide notes they include no information about cloud cover or missing data, so a day without rows is not proof that a place was observed and fire-free.</li>
          <li>FRP (fire radiative power, MW) is the pixel-integrated radiative power at the time of observation. Summing FRP across observations is a descriptive sum, not total energy, emissions, or simultaneous regional fire power.</li>
          <li>Active-fire CSVs contain no satellite photographs. Imagery shown on the map comes separately from NASA GIBS.</li>
        </ul>
        <h3>How MODIS and VIIRS differ</h3>
        <ul>
          <li>MODIS (Terra, Aqua) has a nominal ~1 km active-fire pixel at nadir; VIIRS I-band has ~375 m. These are nominal resolutions that grow toward the swath edge (see scan/track), not fire sizes.</li>
          <li>VIIRS generally detects more small and cooler fires, so raw counts are not interchangeable; adding satellites can raise detection counts even if activity is unchanged.</li>
          <li>Confidence fields differ: MODIS uses a numeric 0–100 value (classes: low 0 ≤ C &lt; 30, nominal 30 ≤ C &lt; 80, high ≥ 80, per the MODIS Collection 6 Active Fire User's Guide); VIIRS uses categorical low/nominal/high defined by different criteria (e.g. sun glint, temperature anomaly, saturation). They are not equivalent probabilities.</li>
          <li>Thermal channels are kept separate: MODIS <code>brightness</code> / <code>bright_t31</code> vs VIIRS <code>bright_ti4</code> / <code>bright_ti5</code> (Kelvin).</li>
          <li>Day/night (D/N) describes the overpass. It does not identify agricultural clearing, peat burning, crown fire, or ignition cause. High FRP alone does not establish a crown fire.</li>
        </ul>
        <h3>What PyroSync standardizes (sensor-aware spatial and daily standardization)</h3>
        <ul>
          <li>Timestamps: <code>acq_date</code> + <code>acq_time</code> (HHMM, UTC; '402' → 04:02, '137' → 01:37). Days are UTC: [D 00:00, D+1 00:00). Browser time zones are never applied.</li>
          <li>Grid: {String(inv.data?.grid.crs ?? 'WGS84')}; origin {String(inv.data?.grid.origin ?? '')}; index {String(inv.data?.grid.cell_index ?? '')}. {String(inv.data?.grid.boundary ?? '')} {String(inv.data?.grid.note ?? '')}</li>
          <li>Per cell and day, counts are kept per sensor (MODIS Terra+Aqua, each VIIRS platform), along with occupied-cell indicators, FRP summaries and day/night counts. The union metric is labeled "cells with detections from any selected sensor"; its sensitivity changes with sensor availability. Raw MODIS and VIIRS detection counts and FRP are never added together; the map colours cells by the primary sensor's own count.</li>
          <li>This is partial harmonization: common grids and days improve organization and comparison, but detection sensitivity differences remain. No bias-correction factor, regression calibration, or probability surface is applied.</li>
        </ul>
        <h3>Quality and type filtering</h3>
        <ul>
          <li>Default preset: MODIS confidence ≥ 30 and VIIRS nominal/high — a filter choice, not equivalent detection performance. All valid source records are retained and can be inspected in the Sensor Workbench.</li>
          <li>Type codes (MODIS/VIIRS user guides): 0 presumed vegetation fire, 1 active volcano, 2 other static land source, 3 offshore. The default includes type 0 only; excluded types are disclosed on each result. Missing types (e.g. NRT files) are treated as "unknown".</li>
          <li>The VIIRS 375 m user guide (v1.2) documents a type-attribution issue in collection versions 1–2 (some type-2 static sources labeled type 0), corrected in version 3. The supplied VIIRS sample is version 2, so some static industrial sources may remain in the vegetation class.</li>
        </ul>
        <h3>Coverage and missing data</h3>
        <ul>
          <li>Day states: detections recorded; zero detections reported in an imported interval; unknown coverage; sensor/product unavailable; outside imported range.</li>
          <li>Import intervals are recorded separately from observations: verified API request windows (with bounding box), CLI-declared windows, and windows declared by FIRMS-style file names such as <code>2024-06-19_5d.csv</code> (rows are still assigned by their own timestamps). A successful interval shows that no records were returned — not that every location was seen under clear skies.</li>
          <li>Days without an interval are unknown and are never silently treated as zero.</li>
          <li>Likely-gap rule: within one import batch, if the median number of rows per declared day is ≥ 20, a declared day on which a sensor has no rows anywhere is treated as unknown (probable acquisition/processing gap), not as zero. Small AOI downloads keep genuine zero days. Affected days are labeled with this reason.</li>
        </ul>
        <h3>Imports, deduplication and reconciliation</h3>
        <ul>
          <li>Each record gets a key from all normalized fields; exact duplicates (repeat imports, overlapping downloads) are stored once, with every occurrence kept in provenance. Records are never merged merely because coordinates match; different platforms or times stay distinct.</li>
          <li>Standard processing (SP/archive) supersedes NRT/RT/URT for the same platform and UTC day: superseded rows are retained but excluded from analysis, so NRT and replacement SP data are never double counted. Record-level matching across streams is not attempted.</li>
          <li>Commits are transactional; a dataset revision increments only when data change, and all caches are keyed by revision.</li>
        </ul>
        <h3>Baselines and unusual conditions</h3>
        <ul>
          <li>Eligibility rule (conservative project choice, not an official standard): ≥5 prior comparable years, each with ≥80% known coverage in a ±15-day seasonal window around the same month-day, and ≥100 reference days. The evaluation year is excluded; Feb 29 maps to Feb 28 in non-leap reference years; windows crossing New Year use actual dates.</li>
          <li>When eligible, empirical P95/P5 thresholds flag descriptive above/below exceedances. Low flags are suppressed when the lower threshold is zero or coverage is unknown; ratios to a zero median are undefined, never infinite.</li>
          <li>With the initial 2023–2024 sample the baseline is ineligible ("Insufficient history for a robust multi-year baseline"). Descriptive 2023-vs-2024 comparisons and rankings are offered instead; they are not significance tests and do not show a seasonal shift.</li>
        </ul>
        <h3>Elevated observed activity</h3>
        <ul>
          <li>Rule: ≥N consecutive UTC days (default 3) on which the selected metric exceeds the threshold and is ≥ a minimum activity (default 1). Unknown-coverage days break runs and are disclosed next to each period.</li>
          <li>Threshold modes: within-range percentile (default P90 of the analysis range, descriptive and relative), user-defined activity threshold, or historical seasonal baseline (only when eligible). These are project settings, not NASA-validated danger thresholds.</li>
        </ul>
        <h3>Imagery and dates</h3>
        <ul>
          <li>Dated imagery: NASA GIBS WMTS corrected-reflectance true-color layers ({(img.data?.layers ?? []).map((l) => l.id).join(', ')}), EPSG:3857, tile matrix set GoogleMapsCompatible_Level9. Every tile URL includes the selected date explicitly; availability is read from DescribeDomains ({img.data ? `${img.data.domain_source}, checked ${img.data.domain_checked}` : 'loading'}).</li>
          <li>A daily image is assembled from that day's overpasses and is not captured at the instant of each hotspot. With 7- or 30-day fire windows, the fire window and imagery date are labeled separately. Cloud, smoke or blank imagery does not prove absence of fire.</li>
          <li>Unavailable dates show "Imagery unavailable for this date"; a nearest-date substitution happens only on request and is labeled. Static basemaps (Esri Canvas, built on OpenStreetMap and other sources) do not represent historical conditions. Imagery and basemaps need internet; analysis does not.</li>
          <li>{img.data?.acknowledgement}</li>
        </ul>
        <h3>Boundaries</h3>
        <ul>
          <li>Indonesia, Sumatra and Kalimantan use Natural Earth 1:10m admin-0/admin-1 boundaries (public domain), simplified at 0.002°. Sumatra = 8 provinces; Kalimantan = Indonesian Borneo provinces as delineated by Natural Earth. The 38 provinces (including the 2022 Papua provinces and North Kalimantan) use Badan Informasi Geospasial (BIG) boundaries, trimmed to the Natural Earth national outline so province totals never exceed the Indonesia total, and simplified at 0.002°. Points on an AOI boundary are included. Antimeridian-crossing AOIs are rejected.</li>
          <li>The imported extent (≈ lon 94.27–142.0, lat −12.0–7.0) is a download bounding box broader than Indonesia; "All imported observations" is not "Indonesia".</li>
        </ul>
        <h3>Sources</h3>
        <ul>
          <li>NASA FIRMS Area API: <a href="https://firms.modaps.eosdis.nasa.gov/api/area/" target="_blank" rel="noreferrer">firms.modaps.eosdis.nasa.gov/api/area</a>; archive download: <a href="https://firms.modaps.eosdis.nasa.gov/download/" target="_blank" rel="noreferrer">/download</a>; FAQ: <a href="https://www.earthdata.nasa.gov/data/tools/firms/faq" target="_blank" rel="noreferrer">earthdata.nasa.gov FIRMS FAQ</a>.</li>
          <li>MODIS Collection 6 Active Fire Product User's Guide, Revision B: <a href="https://www.earthdata.nasa.gov/sites/default/files/imported/MODIS_C6_Fire_User_Guide_B.pdf" target="_blank" rel="noreferrer">PDF</a>. VIIRS 375 m Active Fire User Guide v1.2: <a href="https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf" target="_blank" rel="noreferrer">PDF</a>.</li>
          <li>NASA GIBS API documentation: <a href="https://nasa-gibs.github.io/gibs-api-docs/" target="_blank" rel="noreferrer">nasa-gibs.github.io/gibs-api-docs</a>.</li>
          <li>Boundaries: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noreferrer">Natural Earth</a> (public domain). Basemap: Esri Canvas (© Esri, HERE, Garmin, © OpenStreetMap contributors).</li>
        </ul>
        <h3>Known limitations</h3>
        <ul>
          <li>Two years of data cannot support baselines, trends, or seasonal-shift claims.</li>
          <li>Authenticated live FIRMS retrieval has not been verified with credentials in this build; connector behavior is tested with controlled responses.</li>
          <li>File-name windows are declared, not verified, coverage; the original request bounding box of archive files is unknown unless supplied on import.</li>
          <li>Static-source contamination (VIIRS v2 type issue), cloud/smoke obscuration, and overpass timing affect all counts.</li>
        </ul>
      </div>
    </Panel>
  )
}
