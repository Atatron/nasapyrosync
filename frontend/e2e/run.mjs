// PyroSync browser-level checks (13 required flows + harmonization flows added in v1.1/v1.2 + AOI Insights flow added in v1.3
// + day-level ratio flow added in v1.4 + multi-sensor fusion / adaptive map flow added in v1.5).
//
// Starts its OWN backend on 127.0.0.1:8765 with a fresh, temporary data directory, so it never
// touches your real database. The only synthetic rows used (flow 11) are a clearly labelled
// SYNTHETIC TEST FIXTURE written into that temporary directory.
//
// Usage (from frontend/):  npm run build && npm run e2e
// Env: SAMPLE_ZIP (default ../sample_data/indonesia.zip), PYTHON (default ../.venv/bin/python or python)
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..', '..')
const PORT = Number(process.env.E2E_PORT || 8765)
const BASE = `http://127.0.0.1:${PORT}`
const SAMPLE = process.env.SAMPLE_ZIP || path.join(root, 'sample_data', 'indonesia.zip')
const venvPy = process.platform === 'win32' ? path.join(root, '.venv', 'Scripts', 'python.exe') : path.join(root, '.venv', 'bin', 'python')
const PY = process.env.PYTHON || (fs.existsSync(venvPy) ? venvPy : 'python')
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pyrosync-e2e-'))
const results = []
let reload = 0

function log(...a) { console.log(...a) }
const ONLY = (process.env.E2E_ONLY || '').split(',').filter(Boolean)
async function check(name, fn) {
  const no = name.split('.')[0]
  if (ONLY.length && !['1', '2'].includes(no) && !ONLY.includes(no)) return
  const t0 = Date.now()
  try { const note = await fn(); results.push({ name, status: 'passed', ms: Date.now() - t0, note: note ?? '' }); log(`PASS  ${name}${note ? ' — ' + note : ''}`) }
  catch (e) { results.push({ name, status: 'failed', ms: Date.now() - t0, note: String(e?.message ?? e).slice(0, 500) }); log(`FAIL  ${name}\n      ${e?.stack ?? e}`) }
}
function assert(c, msg) { if (!c) throw new Error(msg) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function api(p) { const r = await fetch(BASE + p); if (!r.ok) throw new Error(`${p} → HTTP ${r.status}`); return r.json() }
function num(t) { return Number(String(t).replace(/[^\d.-]/g, '')) }
// UI 1.6: a choice with 2-3 options is a segmented pill (buttons); with 4 or more it is a dropdown (<select>).
async function pick(scope, name) {
  // polls like Playwright's auto-wait: the control may still be rendering
  for (let t = 0; t < 60; t++) {
    const btn = scope.getByRole('button', { name, exact: typeof name === 'string' })
    if (await btn.count()) return btn.first().click()
    const sels = scope.locator('select')
    const n = await sels.count()
    for (let i = 0; i < n; i++) {
      const sel = sels.nth(i)
      const labels = await sel.locator('option').allInnerTexts()
      const hit = labels.find((l) => (typeof name === 'string' ? l.trim() === name : name.test(l.trim())))
      if (hit !== undefined) { await sel.selectOption({ label: hit }); return }
    }
    await sleep(250)
  }
  throw new Error(`no button or dropdown option named ${name}`)
}

async function startServer() {
  const env = { ...process.env, PYROSYNC_DATA_DIR: dataDir, PYROSYNC_OFFLINE: '1', FIRMS_MAP_KEY: '', PYTHONPATH: path.join(root, 'backend') }
  const proc = spawn(PY, ['-m', 'pyrosync.cli', 'serve', '--host', '127.0.0.1', '--port', String(PORT)], { cwd: path.join(root, 'backend'), env, stdio: ['ignore', 'pipe', 'pipe'] })
  let out = ''
  proc.stdout.on('data', (d) => { out += d }); proc.stderr.on('data', (d) => { out += d })
  for (let i = 0; i < 100; i++) {
    try { const r = await fetch(BASE + '/api/health'); if (r.ok) return proc } catch { /* not up yet */ }
    await sleep(200)
  }
  proc.kill(); throw new Error('backend did not start:\n' + out)
}

async function open(page, hash) {
  reload += 1
  await page.goto(`${BASE}/?r=${reload}#${hash}`)
  await page.waitForLoadState('domcontentloaded')
}
async function waitMapIdle(page) {
  await page.waitForFunction(() => !document.querySelector('[data-testid="map-loading"]'), null, { timeout: 30000 }).catch(() => {})
}
async function importFile(page, file) {
  await open(page, 'page=data')
  await page.getByTestId('import-file').setInputFiles(file)
  await page.getByTestId('inspect-btn').click()
  await page.getByText('Inspection & validation report (not yet committed)').waitFor({ timeout: 180000 })
  await page.getByTestId('commit-btn').click()
  await page.getByText('Import report (committed)').waitFor({ timeout: 300000 })
}

const server = await startServer()
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 }, acceptDownloads: true })
// No external network for the whole run (GIBS/CARTO are intercepted per test); the app must still work.
await ctx.route(/^https?:\/\/(?!127\.0\.0\.1)/, (r) => r.abort())
const page = await ctx.newPage()
const consoleErrors = []
page.on('pageerror', (e) => consoleErrors.push(String(e)))

try {
  await check('1. App launches and shows an honest empty state', async () => {
    await open(page, 'page=explore')
    await page.getByText('No data imported yet').waitFor({ timeout: 15000 })
    const h = await api('/api/health')
    return `backend ${h.version ?? ''} on ${BASE}; no data shown before import`
  })

  let inv0
  await check('2. Sample import through the browser (upload → inspect → commit)', async () => {
    assert(fs.existsSync(SAMPLE), `sample not found at ${SAMPLE}`)
    await importFile(page, SAMPLE)
    inv0 = await api('/api/inventory')
    const shown = num(await page.getByTestId('obs-total').innerText())
    assert(inv0.observations_total > 0 && shown === inv0.observations_total, `UI ${shown} vs API ${inv0.observations_total}`)
    return `${inv0.observations_total.toLocaleString()} observations, ${inv0.date_range.join(' → ')}, revision ${inv0.dataset_revision}`
  })

  await check('3. Changing the AOI changes the results', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15&frameMode=1&series=VIIRS_N20')
    await waitMapIdle(page)
    const kal = num(await page.getByTestId('det-VIIRS_N20').innerText())
    await page.getByLabel('Area of interest').selectOption('region:sumatra')
    await page.waitForFunction((k) => { const el = document.querySelector('[data-testid="det-VIIRS_N20"]'); return el && Number(el.textContent.replace(/[^\d]/g, '')) !== k }, kal, { timeout: 20000 })
    const sum = num(await page.getByTestId('det-VIIRS_N20').innerText())
    const apiK = await api('/api/frame?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&date=2023-09-15&mode=1')
    assert(apiK.summary.VIIRS_N20.detections === kal, `Kalimantan UI ${kal} vs API ${apiK.summary.VIIRS_N20.detections}`)
    // draw a rectangle AOI on the map (Leaflet-Geoman), which registers a custom AOI on the server
    await page.locator('.leaflet-pm-icon-rectangle').first().click()
    const mb = await page.locator('.leaflet-container').first().boundingBox()
    await page.mouse.click(mb.x + mb.width * 0.40, mb.y + mb.height * 0.35)
    await page.mouse.click(mb.x + mb.width * 0.60, mb.y + mb.height * 0.65)
    await page.waitForFunction(() => decodeURIComponent(location.hash).includes('aoi=custom:'), null, { timeout: 15000 })
    await waitMapIdle(page)
    const aoiId = decodeURIComponent(await page.evaluate(() => location.hash)).match(/aoi=(custom:[0-9a-f]+)/)[1]
    const cust = await api(`/api/frame?start=2023-01-01&end=2024-12-31&aoi=${aoiId}&date=2023-09-15&mode=1`)
    await page.waitForFunction((n) => { const el = document.querySelector('[data-testid="det-VIIRS_N20"]'); return el && Number(el.textContent.replace(/[^\d]/g, '')) === n }, cust.summary.VIIRS_N20.detections, { timeout: 15000 })
    // the calendar follows the AOI
    await page.getByTestId('nav-calendar').click()
    const calReq = page.waitForRequest((r) => r.url().includes('/api/daily?') && r.url().includes('aoi=region%3Aprov-id-ri'), { timeout: 15000 })
    await page.getByLabel('Area of interest').selectOption('region:prov-id-ri')
    await calReq
    return `VIIRS N20 detections 2023-09-15: Kalimantan ${kal}, Sumatra ${sum}, drawn rectangle ${cust.summary.VIIRS_N20.detections}; calendar re-queried for the new AOI`
  })

  await check('4. Moving one day changes the fire query and labels', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15&frameMode=1')
    await waitMapIdle(page)
    const reqs = []
    const h = (r) => { if (r.url().includes('/api/frame?')) reqs.push(new URL(r.url()).searchParams.get('date')) }
    page.on('request', h)
    await page.getByLabel('Next day').click()
    await page.getByTestId('fire-window-label').getByText('2023-09-16').waitFor({ timeout: 10000 })
    await waitMapIdle(page)
    page.off('request', h)
    assert(reqs.includes('2023-09-16'), `frame requests: ${reqs.join(',')}`)
    const lbl = await page.getByTestId('active-window').innerText()
    assert(lbl.includes('2023-09-16'), lbl)
    return `frame request date=2023-09-16 issued; label "${lbl.split('·')[0].trim()}"`
  })

  await check('5. Clicking a calendar day selects that date everywhere', async () => {
    await open(page, 'page=calendar&aoi=region:kalimantan&date=2023-09-15')
    await page.getByTestId('day-2023-09-20').click()
    await page.waitForFunction(() => location.hash.includes('date=2023-09-20'), null, { timeout: 10000 })
    await page.getByTestId('day-details').getByText('20 Sep 2023').first().waitFor({ timeout: 10000 })
    await page.getByTestId('day-details').getByRole('button', { name: 'Open this day on the map' }).click()
    await page.getByTestId('fire-window-label').getByText('2023-09-20').waitFor({ timeout: 10000 })
    const v = await page.getByTestId('date-input').inputValue()
    assert(v === '2023-09-20', `timeline date ${v}`)
    // month / year navigation
    await open(page, 'page=calendar&aoi=region:kalimantan&date=2023-09-15')
    await page.getByLabel('Next month').click()
    await page.getByTestId('day-2023-10-01').waitFor({ timeout: 10000 })
    await page.getByLabel('Year').selectOption('2024')
    await page.getByTestId('day-2024-10-01').waitFor({ timeout: 10000 })
    return 'calendar click → shared date 2023-09-20; map label and timeline date input follow; next-month and year navigation work'
  })

  await check('6. Changing the sensor updates dependent panels', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15&series=VIIRS_N20&metric=cells')
    await waitMapIdle(page)
    const reqs = []
    const h = (r) => { const u = r.url(); if (u.includes('/api/elevated?')) reqs.push(new URL(u).searchParams.get('series')) }
    page.on('request', h)
    await page.locator('#series-select').selectOption('MODIS')
    await page.getByTestId('elevated-summary').getByText('MODIS').first().waitFor({ timeout: 15000 })
    await sleep(500)
    page.off('request', h)
    assert(reqs.includes('MODIS'), `elevated requests: ${reqs.join(',')}`)
    return 'elevated-period request and the elevated-activity summary switched to MODIS'
  })

  await check('7. Imagery tile requests include the selected date', async () => {
    const tiles = []
    await page.route('**/wmts/**', (r) => { tiles.push(r.request().url()); r.fulfill({ status: 200, contentType: 'image/jpeg', body: Buffer.alloc(0) }) })
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15&imagery=VIIRS_NOAA20_CorrectedReflectance_TrueColor')
    await page.waitForFunction(() => document.querySelector('[data-testid="imagery-label"]')?.textContent.includes('2023-09-15'))
    for (let i = 0; i < 50 && !tiles.length; i++) await sleep(200)
    await page.getByLabel('Next day').click()
    for (let i = 0; i < 50 && !tiles.some((u) => u.includes('/2023-09-16/')); i++) await sleep(200)
    await page.unroute('**/wmts/**')
    assert(tiles.length > 0, 'no GIBS tile requests seen')
    const bad = tiles.filter((u) => !/\/default\/\d{4}-\d{2}-\d{2}\//.test(u))
    assert(!bad.length, `tile without explicit date: ${bad[0]}`)
    assert(tiles.some((u) => u.includes('/default/2023-09-15/')) && tiles.some((u) => u.includes('/default/2023-09-16/')), 'dates not followed')
    return `${tiles.length} tile requests, all with /default/YYYY-MM-DD/; followed 09-15 → 09-16`
  })

  await check('8. Unavailable imagery is not replaced by another day', async () => {
    const tiles = []
    await page.route('**/wmts/**', (r) => { tiles.push(r.request().url()); r.fulfill({ status: 200, contentType: 'image/jpeg', body: Buffer.alloc(0) }) })
    await page.route('**/api/imagery/layers**', async (r) => {
      const res = await r.fetch(); const j = await res.json()
      for (const l of j.layers) l.ranges = [['2023-01-01', '2023-09-10']]
      r.fulfill({ response: res, json: j })
    })
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15&imagery=VIIRS_NOAA20_CorrectedReflectance_TrueColor')
    await page.getByTestId('imagery-unavailable').waitFor({ timeout: 15000 })
    await sleep(1000)
    const lbl = await page.getByTestId('imagery-label').innerText()
    await page.unroute('**/wmts/**'); await page.unroute('**/api/imagery/layers**')
    assert(!tiles.length, `unexpected tile requests: ${tiles.slice(0, 2).join(', ')}`)
    assert(lbl.includes('2023-09-15') && !lbl.includes('SUBSTITUTED'), lbl)
    return 'unavailable notice shown, 0 tiles requested, label keeps 2023-09-15 (nearest-date only on explicit click)'
  })

  await check('9. Rapid scrubbing never leaves stale results', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-01&frameMode=1&series=VIIRS_N20')
    await waitMapIdle(page)
    for (let i = 0; i < 14; i++) await page.getByLabel('Next day').click({ delay: 0 })
    const sc = page.getByTestId('scrubber')
    const box = await sc.boundingBox()
    for (const fx of [0.2, 0.9, 0.4, 0.71]) await page.mouse.click(box.x + box.width * fx, box.y + box.height / 2)
    await sleep(300)
    await waitMapIdle(page)
    await sleep(800)
    const date = (await page.getByTestId('date-input').inputValue())
    const lbl = await page.getByTestId('fire-window-label').innerText()
    const shown = num(await page.getByTestId('det-VIIRS_N20').innerText())
    const truth = await api(`/api/frame?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&date=${date}&mode=1`)
    assert(lbl.includes(date), `label ${lbl} vs date ${date}`)
    assert(shown === truth.summary.VIIRS_N20.detections, `shown ${shown} vs API ${truth.summary.VIIRS_N20.detections} for ${date}`)
    return `settled on ${date}; card ${shown} = API ${truth.summary.VIIRS_N20.detections}`
  })

  await check('10. Re-importing the same sample leaves counts unchanged', async () => {
    await importFile(page, SAMPLE)
    const inv = await api('/api/inventory')
    const rep = await page.getByTestId('import-report').innerText()
    assert(inv.observations_total === inv0.observations_total, `${inv.observations_total} vs ${inv0.observations_total}`)
    assert(inv.dataset_revision === inv0.dataset_revision, `revision ${inv.dataset_revision} vs ${inv0.dataset_revision}`)
    return `total ${inv.observations_total.toLocaleString()} and revision ${inv.dataset_revision} unchanged${rep.includes('0') ? '' : ''}`
  })

  await check('11. An additional file extends coverage with no code changes (SYNTHETIC TEST FIXTURE)', async () => {
    const dir = fs.mkdtempSync(path.join(dataDir, 'fixture-'))
    const f = path.join(dir, 'SYNTHETIC_TEST_FIXTURE_VIIRS_NOAA20_SP_2025-01-01_3d.csv')
    fs.writeFileSync(f, 'latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight,type\n' +
      '-1.50000,113.90000,330.0,0.4,0.4,2025-01-02,545,N20,VIIRS,n,2,290.0,3.0,D,0\n')
    await importFile(page, f)
    const inv = await api('/api/inventory')
    assert(inv.date_range[1] === '2025-01-03' || inv.date_range[1] === '2025-01-02', `range ${inv.date_range}`)
    const d = await api('/api/daily?start=2025-01-01&end=2025-01-03&platforms=N20')
    const st = d.series.VIIRS_N20.status
    assert(st[0] === 'zero_reported' && st[1] === 'detections' && st[2] === 'zero_reported', st.join(','))
    return `range now ${inv.date_range.join(' → ')}; 2025-01-01..03 statuses ${st.join('/')}; revision ${inv.dataset_revision}`
  })

  await check('12. CSV and GeoJSON downloads contain the filtered data', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31&date=2023-09-15&frameMode=7&series=VIIRS_N20')
    await waitMapIdle(page)
    const grab = async (text) => {
      await page.getByRole('button', { name: 'Export' }).click()
      const item = page.getByRole('menuitem', { name: new RegExp(text) })
      await item.waitFor()
      const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 60000 }), item.click()])
      const p = await dl.path(); return fs.readFileSync(p)
    }
    const AdmZip = null // zip parsed via python (no extra npm dependency)
    const obsZip = await grab('Filtered observations CSV')
    const zp = path.join(dataDir, 'obs.zip'); fs.writeFileSync(zp, obsZip)
    const py = spawn(PY, ['-c', 'import zipfile,sys,csv,io;z=zipfile.ZipFile(sys.argv[1]);r=list(csv.DictReader(io.StringIO(z.read("observations.csv").decode())));print(len(r), sorted({x["acq_date"] for x in r})[0], sorted({x["acq_date"] for x in r})[-1], sorted({x["type_code"] for x in r}))', zp])
    let out = ''; py.stdout.on('data', (d) => { out += d }); await new Promise((r) => py.on('close', r))
    const [n, dmin, dmax] = out.trim().split(' ')
    const pts = await api('/api/observations?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&window_start=2023-09-09&window_end=2023-09-15&limit=1')
    assert(Number(n) === pts.total, `CSV rows ${n} vs API ${pts.total}`)
    assert(dmin >= '2023-09-09' && dmax <= '2023-09-15', `dates ${dmin}..${dmax}`)
    assert(out.includes("['0']"), `types ${out}`)
    const grid = JSON.parse((await grab('Aggregated grid GeoJSON')).toString())
    const fr = await api('/api/frame?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&date=2023-09-15&mode=7&limit=100000')
    assert(grid.features.length === fr.cells_total, `grid ${grid.features.length} vs frame ${fr.cells_total}`)
    const aoi = JSON.parse((await grab('AOI GeoJSON')).toString())
    assert(aoi.features[0].geometry.type.includes('Polygon'), 'AOI geometry')
    void AdmZip
    return `observations CSV ${n} rows (= API, window 09-09..09-15, type 0 only); grid ${grid.features.length} cells (= frame); AOI ${aoi.features[0].geometry.type}`
  })

  await check('13. Analysis works without external imagery or network', async () => {
    // all non-localhost requests are aborted for this whole run
    await open(page, 'page=history&aoi=region:kalimantan&series=VIIRS_N20&metric=cells&imagery=VIIRS_NOAA20_CorrectedReflectance_TrueColor')
    await page.getByTestId('baseline-panel').getByText(/Insufficient history|eligible/i).first().waitFor({ timeout: 30000 })
    await page.getByTestId('elevated-list').first().waitFor({ timeout: 30000 })
    const el = await api('/api/elevated?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&series=VIIRS_N20&metric=cells')
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15&imagery=VIIRS_NOAA20_CorrectedReflectance_TrueColor')
    await waitMapIdle(page)
    const det = num(await page.getByTestId('det-VIIRS_N20').innerText())
    assert(det > 0, 'no detections rendered offline')
    return `history/baseline/elevated rendered offline (${el.periods.length} elevated periods); explore shows ${det} detections with imagery blocked`
  })

  await check('14. Harmonization runs the three stages and matches the API', async () => {
    // Real sample: MODIS (Terra+Aqua) and VIIRS NOAA-20, 2023-2024, Kalimantan
    await open(page, 'page=workbench&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31')
    const ctl = page.getByTestId('harmonization-controls')
    await pick(ctl, 'NOAA-20')
    await pick(ctl, '±60 min')
    await page.getByTestId('harmonization-run').click()
    await page.getByTestId('harmonization-result').waitFor({ timeout: 120000 })
    const q = 'start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&viirs_series=VIIRS_N20&modis_platforms=Aqua&tolerance_min=60&unit_grid=0.1&metric=detections&unit_set=matched&test_fraction=0.2'
    const h = await api('/api/harmonization?' + q)
    const matchedUi = num(await page.getByTestId('harmonization-classes').locator('tr').first().locator('td').nth(1).innerText())
    assert(matchedUi === h.stage2.class_counts.matched, `matched UI ${matchedUi} != API ${h.stage2.class_counts.matched}`)
    assert(h.stage2.coverage_verification.status === 'not_verified', 'coverage must not be claimed as verified')
    if (h.stage3.status === 'ok') {
      await page.getByTestId('harmonization-eval').waitFor()
      assert(h.stage3.split.train_period[1] < h.stage3.split.test_period[0], 'hold-out is not chronological')
      return `${h.stage2.class_counts.matched} matched Aqua–N20 units; beta ${h.stage3.fit.beta.toFixed(3)}; held-out MAE ${h.stage3.evaluation.held_out.unadjusted.mae.toFixed(2)} → ${h.stage3.evaluation.held_out.calibrated.mae.toFixed(2)}`
    }
    await page.getByTestId('harmonization-insufficient').waitFor()
    return `${h.stage2.class_counts.matched} matched units; stage 3 honestly reported as insufficient`
  })
  await check('15. Harmonization tab: stages, validation, map layers and error map match the API', async () => {
    await open(page, 'page=harmonization&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31&date=2024-09-15&frameMode=1')
    await page.getByTestId('h-notrun').waitFor()
    const ctl = page.getByTestId('h-controls')
    await pick(ctl, /^NOAA-20/)
    await pick(ctl, '±60 min')
    await page.getByTestId('h-run').click()
    await page.getByTestId('hpipeline').waitFor({ timeout: 180000 })
    const q = 'start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&viirs_series=VIIRS_N20&modis_platforms=Aqua&tolerance_min=60&unit_grid=0.1&metric=detections&unit_set=matched&test_fraction=0.2'
    const h = await api('/api/harmonization?' + q)
    const matchedUi = num(await page.getByTestId('hpipe-matched').innerText())
    assert(matchedUi === h.stage2.class_counts.matched, `matched UI ${matchedUi} != API ${h.stage2.class_counts.matched}`)
    const badge = await page.getByTestId('hvalidity-badge').first().getAttribute('data-status')
    assert(badge === h.validity.status, `badge ${badge} != API ${h.validity.status}`)
    const rows = page.getByTestId('hvalidity-checks').locator('tbody tr')
    assert(await rows.count() === h.validity.checks.length, 'validity check rows differ from API')
    for (let i = 0; i < h.validity.checks.length; i++) {
      const p = await rows.nth(i).getAttribute('data-passed')
      assert(p === (h.validity.checks[i].passed ? 'yes' : 'no'), `check ${h.validity.checks[i].id} differs`)
    }
    // map: original MODIS and VIIRS totals for the selected day equal the API and the app's daily series
    const m = await api(`/api/harmonization/map?${q}&date=2024-09-15&mode=1&scope=domain&err_grid=0.5&min_n=20`)
    await page.getByTestId('hmap-total-modis').waitFor({ timeout: 60000 })
    const um = num(await page.getByTestId('hmap-total-modis').innerText()), uv = num(await page.getByTestId('hmap-total-viirs').innerText())
    assert(um === m.totals.modis && uv === m.totals.viirs, `map totals UI ${um}/${uv} != API ${m.totals.modis}/${m.totals.viirs}`)
    const d = await api('/api/daily?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&platforms=Aqua,N20')
    const i = d.dates.indexOf('2024-09-15')
    assert(d.series.MODIS.detections[i] === m.totals.modis && d.series.VIIRS_N20.detections[i] === m.totals.viirs, 'map totals differ from the daily series')
    const ctl2 = page.getByTestId('hmap-controls')
    await pick(ctl2, 'Experimental calibrated')
    await page.waitForTimeout(500)
    const unavailable = await page.getByTestId('hmap-cal-unavailable').count()
    assert((unavailable === 0) === (h.validity.status === 'passes'), 'calibrated layer availability does not follow the validity status')
    await pick(ctl2, 'Calibration error')
    let errNote = 'not fitted'
    if (h.stage3.status === 'ok') {
      await page.getByTestId('herr-validated').waitFor({ timeout: 60000 })
      const e = await api(`/api/harmonization/errors?${q}&err_grid=0.5&min_n=20`)
      const v = num(await page.getByTestId('herr-validated').innerText())
      assert(v === e.summary.cells_validated, `validated regions UI ${v} != API ${e.summary.cells_validated}`)
      errNote = `${v} validated 0.5° regions`
    }
    // 1.4: the history panel opens on the day-level ratio; the 1.0 event-model series is one click away and unchanged
    await pick(page, 'Event model (1.0 baseline)')
    await page.getByTestId('hseries-status').waitFor({ timeout: 60000 })
    const sr = await api(`/api/harmonization/series?${q}&agg=month&scope=domain`)
    const st = await page.getByTestId('hseries-status').innerText()
    assert(st.includes(sr.totals_validity.label), 'series status text differs from the API')
    assert((sr.calibrated !== null) === (sr.totals_validity.status === 'passes'), 'calibrated series drawn without passing the totals rules')
    return `${matchedUi} matches; validity ${h.validity.status}; map day 2024-09-15 MODIS ${um} / VIIRS ${uv} (= daily series); ${errNote}; series totals ${sr.totals_validity.status}`
  })

  await check('16. Original-data pages are unchanged by the Harmonization tab', async () => {
    const qs = 'start=2023-01-01&end=2024-12-31&aoi=region:kalimantan'
    const before = await api(`/api/daily?${qs}`)
    const elb = await api(`/api/elevated?${qs}&series=VIIRS_N20&metric=cells`)
    await api('/api/harmonization/series?' + qs + '&viirs_series=VIIRS_N20&modis_platforms=Aqua&tolerance_min=60&agg=day')
    const after = await api(`/api/daily?${qs}`)
    const ela = await api(`/api/elevated?${qs}&series=VIIRS_N20&metric=cells`)
    assert(JSON.stringify(before.series) === JSON.stringify(after.series), 'daily series changed')
    assert(ela.periods.length === elb.periods.length, 'elevated periods changed')
    await open(page, 'page=calendar&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31')
    await page.getByTestId('calendar-grid').waitFor({ timeout: 30000 })
    await open(page, 'page=workbench&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31')
    await page.getByTestId('harmonization-controls').waitFor({ timeout: 30000 })
    await open(page, 'page=explore&aoi=region:kalimantan&date=2023-09-15')
    await waitMapIdle(page)
    const det = num(await page.getByTestId('det-VIIRS_N20').innerText())
    assert(det > 0, 'explore lost its detections')
    return `daily series and ${ela.periods.length} elevated periods identical after harmonization requests; calendar, workbench panel and explore (${det} N20 detections) still render`
  })

  await check('17. AOI Insights: roles, honest "not enough history", no NRT call until asked, bilingual briefing, method drawer', async () => {
    const nowCalls = []
    page.on('request', (r) => { if (r.url().includes('/api/insights/now')) nowCalls.push(r.url()) })
    await open(page, 'page=insights&aoi=region:kalimantan')
    await page.getByRole('heading', { name: 'AOI Insights' }).waitFor({ timeout: 30000 })
    const inv = await api('/api/inventory')
    const last = inv.products.filter((p) => ['Terra', 'Aqua'].includes(p.platform)).map((p) => p.last_date).sort().pop()
    const qs = `start=${last.slice(0, 4)}-01-01&end=${last}&aoi=region:kalimantan&platforms=Terra,Aqua&series=MODIS`
    const reg = await api(`/api/insights/regime?${qs}&metric=detections`)
    const tracker = page.locator('#ins-tracker')
    await tracker.waitFor()
    if (reg.available) {
      await tracker.getByText(reg.tracker.status.band).first().waitFor({ timeout: 60000 })
    } else {
      await tracker.getByText('Not enough history').waitFor({ timeout: 60000 })
      assert((await tracker.locator('canvas').count()) === 0, 'a tracker chart is drawn without enough history')
    }
    // role presets change the sections shown
    await page.getByTestId('role-select').selectOption('manager')
    await page.locator('#ins-map').waitFor()
    assert((await page.locator('#ins-now').count()) === 0, 'land manager view should not show the NRT section')
    await page.getByTestId('role-select').selectOption('warning')
    await page.locator('#ins-now').waitFor()
    await page.waitForTimeout(800)
    assert(nowCalls.length === 0, 'FIRMS NRT was requested without pressing the button')
    // briefing in both languages, always with the disclaimer
    await page.getByRole('button', { name: /Briefing/ }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByText('Not a forecast, not a fire-danger rating and not an official warning').waitFor({ timeout: 30000 })
    await dlg.getByRole('button', { name: 'Bahasa Indonesia' }).click()
    await dlg.getByText('Bukan prakiraan, bukan peringkat bahaya kebakaran').waitFor()
    await dlg.getByRole('button', { name: 'Tutup' }).click()
    // method drawer and exports
    await page.getByRole('button', { name: /Method and data/ }).click()
    await page.getByText('python -m pyrosync.cli insights --aoi region:kalimantan').waitFor()
    for (const f of ['csv', 'geojson', 'kml']) {
      const r = await fetch(`${BASE}/api/export/hotspots.${f}?${qs}&top=50`)
      assert(r.ok, `hotspots ${f} HTTP ${r.status}`)
    }
    const z = await fetch(`${BASE}/api/export/insights.zip?${qs}&metric=detections`)
    assert(z.ok && (await z.arrayBuffer()).byteLength > 200, 'insights.zip missing')
    return reg.available ? `tracker: ${reg.tracker.status.band}` : `sample history too short: "${reg.reason}" shown, nothing estimated; NRT not called; EN/ID briefing; exports OK`
  })

  await check('18. Day-level ratio (1.4): gate badge, series, map views and the off-by-default History/Insights comparison follow the API', async () => {
    const q = 'start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&viirs_series=VIIRS_N20&modis_platforms=Aqua&tolerance_min=60&unit_grid=0.1&metric=detections&unit_set=matched&test_fraction=0.2'
    await open(page, 'page=harmonization&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31&date=2024-09-15&frameMode=1')
    const ctl = page.getByTestId('h-controls')
    await pick(ctl, /^NOAA-20/)
    await pick(ctl, '±60 min')
    await page.getByTestId('h-run').click()
    await page.getByTestId('hagg').waitFor({ timeout: 180000 })
    const a = await api(`/api/harmonization/aggregate?${q}&events=true`)
    const g = a.quantities.detections.gate
    const badge = await page.getByTestId('hagg-badge').getAttribute('data-status')
    assert(badge === g.status, `aggregate badge ${badge} != API ${g.status}`)
    assert(a.coverage.status === 'not_verified', 'coverage must not be claimed as verified')
    // the history panel defaults to the ratio series; a calibrated line exists only if the gate passes
    await pick(page, 'Day-level ratio (1.4)')
    await page.getByTestId('hagg-series-status').waitFor({ timeout: 60000 })
    const sr = await api(`/api/harmonization/aggregate/series?${q}&agg=month&quantity=detections`)
    assert((sr.calibrated !== null) === (sr.gate.status === 'passes'), 'ratio series drawn without passing the gate')
    assert((await page.getByTestId('hagg-series-status').innerText()).includes(sr.gate.label), 'series status differs from the API')
    // map: ratio estimate note and regional ratio error view
    const mc = page.getByTestId('hmap-controls')
    await pick(mc, 'Experimental calibrated')
    await pick(mc, 'Day-level ratio index (1.4)')
    await page.getByTestId('hmap-ratio-note').waitFor({ timeout: 60000 })
    const m = await api(`/api/harmonization/map?${q}&date=2024-09-15&mode=1&scope=domain&err_grid=0.5&min_n=20`)
    assert(m.ratio_model.available === (g.status === 'passes'), 'map ratio layer availability does not follow the gate')
    await pick(mc, 'Calibration error')
    await pick(mc, 'Regional daily totals (1.4)')
    await page.getByTestId('hratio-within').waitFor({ timeout: 60000 })
    const rr = await api(`/api/harmonization/aggregate/regions?${q}&err_grid=0.5&min_days=20`)
    const within = num(await page.getByTestId('hratio-within').innerText())
    assert(within === rr.summary.within, `regions within UI ${within} != API ${rr.summary.within}`)
    // History: off by default (no request), then the same gate as the API for the page's own filters
    const meqCalls = []
    page.on('request', (r) => { if (r.url().includes('/api/harmonization/aggregate/series')) meqCalls.push(r.url()) })
    await open(page, 'page=history&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31&platforms=Aqua,N20&series=VIIRS_N20')
    await page.getByTestId('hist-meq-toggle').waitFor({ timeout: 30000 })
    await page.waitForTimeout(800)
    assert(meqCalls.length === 0, 'the comparison was requested before it was switched on')
    assert(!(await page.getByTestId('hist-meq-toggle').isChecked()), 'the comparison must be off by default')
    await page.getByTestId('hist-meq-toggle').check()
    await page.getByTestId('hist-meq-status').waitFor({ timeout: 60000 })
    const hq = new URL(meqCalls[meqCalls.length - 1]).search
    const hs = await api('/api/harmonization/aggregate/series' + hq)
    const hb = await page.getByTestId('hist-meq-gate').getAttribute('data-status')
    assert(hb === hs.gate.status && (hs.calibrated !== null) === (hs.gate.status === 'passes'), 'history comparison does not follow the gate')
    // AOI Insights: the same comparison, off by default
    await open(page, 'page=insights&aoi=region:kalimantan')
    await page.getByTestId('ins-meq-toggle').waitFor({ timeout: 60000 })
    assert(!(await page.getByTestId('ins-meq-toggle').isChecked()), 'insights comparison must be off by default')
    await page.getByTestId('ins-meq-toggle').check()
    await page.getByTestId('ins-meq-status').waitFor({ timeout: 60000 })
    const ib = await page.getByTestId('ins-meq-gate').getAttribute('data-status')
    return `sample Kalimantan Aqua–N20: aggregate gate ${g.status} (UI = API); series line ${sr.calibrated ? 'drawn' : 'withheld'}; map ratio layer ${m.ratio_model.available ? 'on' : 'withheld'}; ${within} regions within 0.8–1.25×; history gate ${hb}; insights gate ${ib}; nothing requested before the toggle`
  })

  await check('19. 1.5 map: 4 destinations, adaptive grid with fixed region statistics, harmonized layer status, Analyze Location, shared circle, hotspot popup', async () => {
    const qs0 = 'start=2023-01-01&end=2024-12-31'
    // navigation (UI 1.6): five single-word workspaces in a fixed order; old page ids map onto them
    await open(page, 'page=explore')
    const navNames = await page.getByTestId('sidebar').locator('[data-testid^="nav-"]').allInnerTexts()
    assert(JSON.stringify(navNames.map((t) => t.trim())) === JSON.stringify(['Explore', 'Calendar', 'Insights', 'Harmonization', 'Methods']), `sidebar order ${navNames}`)
    assert(navNames.every((t) => !t.includes('&')), 'ampersand in navigation')
    await page.getByTestId('nav-harmonization').click()
    await page.getByTestId('harmonization-page').waitFor({ timeout: 15000 })
    const navAfter = await page.getByTestId('sidebar').locator('[data-testid^="nav-"]').allInnerTexts()
    assert(JSON.stringify(navAfter) === JSON.stringify(navNames), 'sidebar reordered after switching workspace')
    await open(page, 'page=history')
    await page.getByTestId('ws-tabs').getByRole('button', { name: 'Seasonal History' }).and(page.locator('[aria-pressed="true"]')).waitFor({ timeout: 15000 })
    await open(page, 'page=workbench')
    await page.getByTestId('ws-tabs').getByRole('button', { name: 'Sensor Workbench' }).and(page.locator('[aria-pressed="true"]')).waitFor({ timeout: 15000 })
    // old bookmark with a grid but no gridMode keeps that grid as a manual choice
    await open(page, `page=explore&aoi=region:kalimantan&date=2023-09-15&frameMode=1&grid=0.05&view=-1.5,113.5,5`)
    await page.getByTestId('grid-label').getByText('0.05° (manual)').waitFor({ timeout: 15000 })
    await page.getByTestId('map-tools-toggle').click()
    assert(await page.getByTestId('grid-mode').inputValue() === '0.05', 'old bookmarked grid not preserved')
    // auto grid: 0.25° at zoom 5, finer when zooming in; the region statistics stay the same
    const obs = await api(`/api/observations?${qs0}&aoi=region:kalimantan&platforms=N20&window_start=2023-09-15&window_end=2023-09-15&limit=20`)
    const r = obs.records[0]
    assert(r, 'no NOAA-20 detection in Kalimantan on 2023-09-15')
    const frames = []
    const fh = (q) => { if (q.url().includes('/api/frame?')) frames.push(new URL(q.url()).searchParams) }
    page.on('request', fh)
    await open(page, `page=explore&aoi=region:kalimantan&date=2023-09-15&frameMode=1&series=VIIRS_N20&view=${r.lat},${r.lon},5`)
    await waitMapIdle(page)
    await page.getByTestId('grid-label').getByText('0.25° (auto, zoom 5)').waitFor({ timeout: 15000 })
    const det0 = num(await page.getByTestId('det-VIIRS_N20').innerText())
    const apiK = await api(`/api/frame?${qs0}&aoi=region:kalimantan&date=2023-09-15&mode=1`)
    assert(det0 === apiK.summary.VIIRS_N20.detections, `region card ${det0} vs API ${apiK.summary.VIIRS_N20.detections}`)
    for (const [z, g] of [[6, '0.1'], [7, '0.1'], [8, '0.05']]) {
      await page.locator('.leaflet-control-zoom-in').click()
      await page.getByTestId('grid-label').getByText(`${g}° (auto, zoom ${z})`).waitFor({ timeout: 15000 })
    }
    await waitMapIdle(page)
    await sleep(800)
    page.off('request', fh)
    const grids = new Set(frames.map((p) => p.get('grid')))
    assert(grids.has('0.25') && grids.has('0.05'), `display grids requested: ${[...grids].join(',')}`)
    assert(frames.some((p) => p.get('grid') === '0.05' && p.get('bbox')), 'fine display grid without a viewport bbox')
    const det1 = num(await page.getByTestId('det-VIIRS_N20').innerText())
    assert(det1 === det0, `region statistics changed with zoom: ${det0} → ${det1}`)
    // harmonized layer: status label equals the API for the same request
    const fz = page.waitForRequest((r) => r.url().includes('/api/fusion/map?'), { timeout: 15000 })
    await page.getByTestId('layer-harmonized').click()
    const fzUrl = new URL((await fz).url())
    await page.getByTestId('harm-status').waitFor({ timeout: 120000 })
    const fzApi = await api(fzUrl.pathname + fzUrl.search)
    const hs = await page.getByTestId('harm-status').getAttribute('data-status')
    assert(hs === fzApi.validation_status, `harmonized status UI ${hs} vs API ${fzApi.validation_status}`)
    assert(fzApi.label === 'Experimental Harmonized Activity Index' && fzApi.cells_validated === false, 'cells must be labelled experimental')
    await page.getByTestId('harm-legend').getByText('Experimental Harmonized Activity Index').first().waitFor()
    // Analyze Location: click → circle AOI; zoom in → smaller radius; statistics follow the circle
    await page.getByRole('button', { name: /cells$/ }).click()
    await page.getByTestId('map-tools-toggle').click()
    await page.getByTestId('analyze-toggle').click()
    const mb = await page.locator('.leaflet-container').first().boundingBox()
    await page.mouse.click(mb.x + mb.width / 2, mb.y + mb.height / 2)
    await page.waitForFunction(() => decodeURIComponent(location.hash).includes('aoi=circle:'), null, { timeout: 15000 })
    const km1 = num(await page.getByTestId('circle-km').innerText())
    assert(km1 > 0, 'no radius shown')
    await page.locator('.leaflet-control-zoom-in').click()
    await page.waitForFunction((k) => { const el = document.querySelector('[data-testid="circle-km"]'); return el && Number(el.textContent) < k * 0.7 }, km1, { timeout: 15000 })
    const km2 = num(await page.getByTestId('circle-km').innerText())
    await waitMapIdle(page)
    await page.waitForFunction((k) => { const m = decodeURIComponent(location.hash).match(/aoi=circle:[-\d.]+,[-\d.]+,([\d.]+)/); return m && Number(m[1]) === k }, km2, { timeout: 10000 })
    const circ = decodeURIComponent(await page.evaluate(() => location.hash)).match(/aoi=(circle:[-\d.,]+)/)[1]
    const cApi = await api(`/api/frame?${qs0}&aoi=${encodeURIComponent(circ)}&date=2023-09-15&mode=1`)
    assert(cApi.summary.VIIRS_N20.detections > 0, 'the circle around a detection must contain it')
    await page.waitForFunction((n) => { const el = document.querySelector('[data-testid="det-VIIRS_N20"]'); return el && Number(el.textContent.replace(/[^\d]/g, '')) === n }, cApi.summary.VIIRS_N20.detections, { timeout: 20000 })
    // shared link restores the same circle and view in a fresh page
    const hash = (await page.evaluate(() => location.hash)).slice(1)
    const p2 = await ctx.newPage()
    await p2.goto(`${BASE}/?r=share#${hash}`)
    await p2.getByTestId('circle-km').waitFor({ timeout: 20000 })
    const km3 = num(await p2.getByTestId('circle-km').innerText())
    const h2 = decodeURIComponent(await p2.evaluate(() => location.hash))
    await p2.close()
    assert(km3 === km2 && h2.includes(`aoi=${circ}`), `shared circle ${km3} km / ${h2.match(/aoi=[^&]+/)?.[0]} vs ${km2} km / ${circ}`)
    // back to the region: the original region and its statistics return
    await page.getByTestId('back-to-region').click()
    await page.waitForFunction(() => decodeURIComponent(location.hash).includes('aoi=region:kalimantan'), null, { timeout: 15000 })
    await page.waitForFunction((n) => { const el = document.querySelector('[data-testid="det-VIIRS_N20"]'); return el && Number(el.textContent.replace(/[^\d]/g, '')) === n }, det0, { timeout: 20000 })
    // hotspot popup (FIRMS-style attributes) and "Analyze around this detection"
    await open(page, `page=explore&aoi=region:kalimantan&date=2023-09-15&frameMode=1&platforms=N20&mapLayer=points&view=${r.lat},${r.lon},12`)
    await page.waitForFunction(() => !document.querySelector('[data-testid="map-loading"]'), null, { timeout: 30000 })
    await sleep(1200)
    const mb2 = await page.locator('.leaflet-container').first().boundingBox()
    await page.mouse.click(mb2.x + mb2.width / 2, mb2.y + mb2.height / 2)
    const pop = page.getByTestId('hotspot-popup')
    await pop.waitFor({ timeout: 15000 })
    for (const k of ['Latitude', 'Longitude', 'Acquired', 'Satellite', 'Confidence', 'FRP', 'Scan × track', 'Source product']) await pop.getByText(k, { exact: true }).waitFor()
    const latTxt = await pop.locator('tr', { hasText: 'Latitude' }).locator('td').innerText()
    await pop.getByRole('button', { name: 'Analyze around this detection' }).click()
    await page.waitForFunction(() => decodeURIComponent(location.hash).includes('aoi=circle:'), null, { timeout: 15000 })
    const c2 = decodeURIComponent(await page.evaluate(() => location.hash)).match(/aoi=circle:([-\d.]+),([-\d.]+),([\d.]+)/)
    assert(Math.abs(Number(c2[1]) - num(latTxt)) < 1e-4, `circle centre ${c2[1]} vs detection latitude ${latTxt}`)
    return `nav 4+advanced; grid 0.25→0.1→0.05 with zoom, region N20 ${det0} unchanged; harmonized status ${hs} (= API); circle ${km1} → ${km2} km on zoom (= ${cApi.summary.VIIRS_N20.detections} N20 detections, = API); shared link restored ${km3} km; popup + Analyze around → circle at ${c2[1]}, ${c2[2]}`
  })

  await check('20. Harmonized Calendar and Insights show the fused series with the API validation status', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31&date=2023-09-15')
    await page.getByTestId('nav-calendar').click()
    await page.waitForFunction(() => location.hash.includes('series=FUSED'), null, { timeout: 15000 })
    await page.getByTestId('fusion-banner-status').waitFor({ timeout: 120000 })
    const ser = await api('/api/fusion/series?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&agg=year')
    const st = await page.getByTestId('fusion-banner-status').getAttribute('data-status')
    assert(st === ser.validation_status, `calendar banner ${st} vs API ${ser.validation_status}`)
    const d = await api('/api/daily?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&fused=true')
    assert('FUSED' in d.series && d.series.FUSED.detections.length === d.dates.length, 'daily fused series missing')
    await page.getByTestId('calendar-grid').waitFor({ timeout: 30000 })
    // Methods: the fusion panel lists every pair and the gate checks of the API
    await open(page, 'page=harmonization&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31')
    await page.getByTestId('fusion-panel').waitFor({ timeout: 120000 })
    const fr = await api('/api/fusion?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan')
    const g = await page.getByTestId('fusion-gate').getAttribute('data-status')
    assert(g === fr.effective.status, `fusion gate UI ${g} vs API ${fr.effective.status}`)
    // AOI Insights: the harmonized series is selectable; its banner states the API status; the live NRT view is not offered for it
    const insReq = []
    const ih = (q) => { const u = q.url(); if (u.includes('/api/insights/') && u.includes('series=FUSED')) insReq.push(u) }
    page.on('request', ih)
    await open(page, 'page=insights&aoi=region:kalimantan')
    await pick(page.locator('#main header').first(), 'Harmonized (all sensors)')
    await page.getByTestId('fusion-banner-status').waitFor({ timeout: 120000 })
    const ist = await page.getByTestId('fusion-banner-status').getAttribute('data-status')
    await sleep(1500)
    page.off('request', ih)
    assert(ist === ser.validation_status, `insights banner ${ist} vs API ${ser.validation_status}`)
    assert(insReq.length > 0, 'Insights did not query the harmonized series')
    assert(!insReq.some((u) => u.includes('/api/insights/now')), 'NRT requested for the harmonized series')
    const zr = await fetch(`${BASE}/api/export/fusion.zip?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan`)
    assert(zr.ok && (await zr.arrayBuffer()).byteLength > 200, 'fusion.zip missing')
    return `sample: fusion status ${fr.effective.status} (${fr.effective.status_label}); eligible ${fr.eligible.join(', ') || 'none'}; calendar and Insights banners = API (${insReq.length} Insights requests for FUSED); fusion.zip OK`
  })

  await check('21. UI 1.7: one control per job, map stage sizes, unified calendar header, compact harmonization, loading bar', async () => {
    await open(page, 'page=explore&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31&date=2023-09-15&frameMode=1&series=VIIRS_N20')
    await waitMapIdle(page)
    // shell: no AOI block in the sidebar, no top-bar hamburger on desktop, the sidebar keeps its own Collapse button
    assert(await page.getByTestId('aoi-quick').count() === 0, 'sidebar AOI quick-selector still present')
    assert(!(await page.getByRole('button', { name: 'Open navigation' }).isVisible()), 'top-bar hamburger visible on desktop')
    await page.getByTestId('sidebar-toggle').waitFor()
    // Explore: no KPI strip, no Filters-applied card; counters live in the map control bar and equal the API
    assert(await page.getByTestId('summary-cards').count() === 0, 'KPI strip still present')
    assert(await page.getByText('Filters applied', { exact: true }).count() === 0, 'Filters applied card still present')
    const det = num(await page.getByTestId('hud-counters').getByTestId('det-VIIRS_N20').innerText())
    const apiK = await api('/api/frame?start=2023-01-01&end=2024-12-31&aoi=region:kalimantan&date=2023-09-15&mode=1')
    assert(det === apiK.summary.VIIRS_N20.detections, `HUD ${det} vs API ${apiK.summary.VIIRS_N20.detections}`)
    // the filter disclosure moved into the Filters popover
    await page.getByRole('button', { name: /^Filters/ }).click()
    await page.getByTestId('filters-applied').getByText('Types included', { exact: false }).waitFor({ timeout: 15000 })
    await page.getByRole('button', { name: 'Close' }).click()
    // map stage: default → theater collapses the drawer → default restores it → full screen → Esc returns
    await page.getByTestId('details-drawer').waitFor()
    const h0 = (await page.getByTestId('map-stage').boundingBox()).height
    await page.getByTestId('stage-theater').click()
    await page.waitForFunction(() => document.querySelector('[data-testid="map-stage"]')?.getAttribute('data-stage') === 'theater')
    assert(await page.getByTestId('details-drawer').count() === 0, 'drawer not collapsed in theater mode')
    await page.getByTestId('stage-theater').click()
    await page.getByTestId('details-drawer').waitFor({ timeout: 5000 })
    await page.getByTestId('stage-fullscreen').click()
    await page.waitForFunction(() => document.querySelector('[data-testid="map-stage"]')?.getAttribute('data-stage') === 'fullscreen')
    const vp = page.viewportSize()
    const fb = await page.getByTestId('map-stage').boundingBox()
    assert(fb.width >= vp.width - 2 && fb.height >= vp.height - 2, `fullscreen stage ${fb.width}x${fb.height} vs viewport ${vp.width}x${vp.height}`)
    await page.keyboard.press('Escape')
    await page.waitForFunction(() => document.querySelector('[data-testid="map-stage"]')?.getAttribute('data-stage') === 'default', null, { timeout: 5000 })
    await page.getByTestId('details-drawer').waitFor({ timeout: 5000 })
    // map tools popover holds the area mode, grid, upload, clear and diagnostics controls
    await page.getByTestId('map-tools-toggle').click()
    for (const n of ['Region AOI', 'Analyze Location', 'Upload GeoJSON', 'Clear AOI']) await page.getByTestId('map-tools').getByRole('button', { name: n }).waitFor()
    await page.getByTestId('map-tools-toggle').click()
    // calendar: one navigation header (month and day controls together), no separate playback bar, spaced cells
    await page.getByTestId('nav-calendar').click()
    await page.getByTestId('calendar-nav').waitFor({ timeout: 15000 })
    assert(await page.getByTestId('timeline').count() === 0, 'separate playback bar still on the calendar')
    for (const n of ['Previous month', 'Next month', 'Previous day', 'Next day']) assert(await page.getByTestId('calendar-nav').getByLabel(n).count() === 1, `${n} missing from the calendar header`)
    const gap = await page.getByTestId('calendar-grid').evaluate((e) => getComputedStyle(e).columnGap)
    assert(gap === '8px', `calendar gap ${gap}`)
    await page.getByTestId('calendar-nav').getByLabel('Next day').click()
    await page.waitForFunction(() => location.hash.includes('date=2023-09-16'), null, { timeout: 10000 })
    // harmonization: the region/period/filters block is gone; the run controls remain
    await open(page, 'page=harmonization&aoi=region:kalimantan&start=2023-01-01&end=2024-12-31')
    await page.getByTestId('h-controls').waitFor({ timeout: 15000 })
    assert(await page.getByText('Region (top bar)').count() === 0, 'redundant region block still present')
    // loading bar: shows request progress while a new query loads, then disappears
    await open(page, 'page=explore&aoi=region:sumatra&start=2023-01-01&end=2024-12-31&date=2023-08-02&frameMode=1')
    await page.getByTestId('load-bar').waitFor({ state: 'attached', timeout: 10000 })
    const vt = await page.getByRole('progressbar', { name: 'Loading data' }).getAttribute('aria-valuetext')
    assert(/\d+ of \d+ data requests finished/.test(vt), `progress text ${vt}`)
    await page.getByTestId('load-bar').waitFor({ state: 'detached', timeout: 60000 })
    return `HUD N20 ${det} = API; filters disclosure in popover; theater/fullscreen/default with drawer collapse and restore; calendar gap ${gap}; loading bar "${vt}"`
  })

} finally {
  await browser.close()
  server.kill()
}

const passed = results.filter((r) => r.status === 'passed').length
const summary = { ran_at_utc: new Date().toISOString(), node: process.version, platform: `${process.platform} ${os.release()}`, passed, failed: results.length - passed,
  page_errors: consoleErrors, results }
fs.writeFileSync(path.join(here, 'results.json'), JSON.stringify(summary, null, 2))
log(`\n${passed}/${results.length} browser checks passed. Details: e2e/results.json`)
if (consoleErrors.length) log('Page errors:', consoleErrors)
fs.rmSync(dataDir, { recursive: true, force: true })
process.exit(passed === results.length ? 0 : 1)
