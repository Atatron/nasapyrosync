// PyroSync browser-level checks (13 required flows).
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
    await page.getByRole('button', { name: 'Burning Calendar' }).click()
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
    await page.getByTestId('card-elevated').getByText('MODIS').first().waitFor({ timeout: 15000 })
    await sleep(500)
    page.off('request', h)
    assert(reqs.includes('MODIS'), `elevated requests: ${reqs.join(',')}`)
    return 'elevated-period request and summary card switched to MODIS'
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
