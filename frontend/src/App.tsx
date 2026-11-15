import { useEffect, useState } from 'react'
import { clearCache, useApi, type Region } from './api'
import { useInventory } from './hooks'
import { useApp } from './state'
import { cls } from './util'
import { Icon, Seg } from './components/ui'
import { WORKSPACES, useView, workspaceOf } from './workspace'
import TopBar from './components/TopBar'
import Explore from './pages/Explore'
import CalendarPage from './pages/CalendarPage'
import HistoryPage from './pages/HistoryPage'
import Workbench from './pages/Workbench'
import DataMethods from './pages/DataMethods'
import HarmonizationPage from './pages/HarmonizationPage'
import InsightsPage from './pages/InsightsPage'

const SHORT: Record<string, [string, string]> = {
  'region:indonesia': ['IDN', 'Indonesia National'], 'region:kalimantan': ['KAL', 'Kalimantan'], 'region:sumatra': ['SUM', 'Sumatra'],
}

function NavItem({ w, onNavigate }: { w: (typeof WORKSPACES)[number]; onNavigate: () => void }) {
  const s = useApp()
  const active = workspaceOf(s.page) === w.id
  return (
    <li>
      <button type="button" onClick={() => {
        if (!active) {
          // the Calendar opens on the harmonized multi-sensor series; any sensor can still be chosen in the top bar
          s.set({ page: w.page, ...(w.id === 'calendar' ? { series: 'FUSED', metric: 'detections' } : {}) })
        }
        onNavigate()
      }}
        aria-current={active ? 'page' : undefined} title={s.navOpen ? w.hint : `${w.label}: ${w.hint}`} data-testid={`nav-${w.id}`}
        className={cls('flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] font-medium',
          active ? 'bg-zinc-950 text-white dark:bg-zinc-50 dark:text-zinc-950' : 'text-muted hover:bg-soft hover:text-ink')}>
        <Icon name={w.icon} className="h-4 w-4 shrink-0" /><span className={cls('truncate', !s.navOpen && 'lg:sr-only')}>{w.label}</span>
      </button>
    </li>
  )
}

function AoiQuick({ regions, onNavigate }: { regions: Region[]; onNavigate: () => void }) {
  const s = useApp()
  const main = ['region:indonesia', 'region:kalimantan', 'region:sumatra'].filter((id) => regions.some((r) => r.id === id))
  const provinces = regions.filter((r) => !main.includes(r.id))
  const pick = (v: string) => { s.set({ aoi: v, analyzeMode: 'region', clickAt: '', lastRegionAoi: v }); onNavigate() }
  if (!regions.length) return null
  return (
    <div className="border-t border-line p-2" data-testid="aoi-quick">
      <div className={cls('px-2.5 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-wider text-muted', !s.navOpen && 'lg:sr-only')}>Indonesia AOI</div>
      <ul className="space-y-0.5">
        {main.map((id) => {
          const [code, name] = SHORT[id]
          const on = s.aoi === id
          return (
            <li key={id}><button type="button" aria-pressed={on} onClick={() => pick(id)} title={regions.find((r) => r.id === id)?.name}
              className={cls('flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[13px]', on ? 'bg-soft font-semibold text-ink' : 'text-muted hover:bg-soft hover:text-ink')}>
              <span className={cls('inline-flex h-5 w-9 shrink-0 items-center justify-center rounded font-mono text-[10px] font-semibold',
                on ? 'bg-zinc-950 text-white dark:bg-zinc-50 dark:text-zinc-950' : 'border border-line')}>{code}</span>
              <span className={cls('truncate', !s.navOpen && 'lg:sr-only')}>{name}</span>
            </button></li>
          )
        })}
      </ul>
      {provinces.length > 0 && (
        <select className={cls('field mt-1.5 w-full', !s.navOpen && 'lg:hidden')} aria-label="Province AOI" value={provinces.some((r) => r.id === s.aoi) ? s.aoi : ''}
          onChange={(e) => e.target.value && pick(e.target.value)}>
          <option value="">Province…</option>
          {provinces.map((r) => <option key={r.id} value={r.id}>{r.name.replace(/ province$/, '')}</option>)}
        </select>
      )}
    </div>
  )
}

function WorkspaceTabs() {
  const s = useApp()
  const v = useView()
  const ws = workspaceOf(s.page)
  if (ws === 'insights') {
    const cur = s.page === 'history' ? 'history' : v.insView
    return (
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4 lg:px-6 lg:pt-6" data-testid="ws-tabs">
        <Seg label="Insights view" value={cur} onChange={(x) => { if (x === 'history') s.set({ page: 'history' }); else { v.set({ insView: x }); s.set({ page: 'insights' }) } }}
          options={[{ value: 'tracker', label: 'Season Tracker' }, { value: 'history', label: 'Seasonal History' }, { value: 'climate', label: 'Climate ENSO / IOD' }]} />
      </div>
    )
  }
  if (ws === 'harmonization') {
    const cur = s.page === 'harmonization' ? 'audit' : v.wbView
    const presets: Record<string, [number, string[]]> = { default: [30, ['nominal', 'high']], high: [80, ['high']], all: [0, ['low', 'nominal', 'high']] }
    const conf = Object.entries(presets).find(([, [m, c]]) => m === s.modisMinConf && c.join() === s.viirsConf.join())?.[0] ?? 'custom'
    return (
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4 lg:px-6 lg:pt-6" data-testid="ws-tabs">
        <Seg label="Harmonization view" value={cur} onChange={(x) => { if (x === 'audit') s.set({ page: 'harmonization' }); else { v.set({ wbView: x }); s.set({ page: 'workbench' }) } }}
          options={[{ value: 'audit', label: 'Calibration Audit' }, { value: 'series', label: 'Sensor Workbench' }, { value: 'records', label: 'Source Records' }]} />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted">Grid
            <select className="field" aria-label="Grid resolution" value={s.gridMode === 'auto' ? 'auto' : s.grid}
              onChange={(e) => { const x = e.target.value; if (x === 'auto') s.set({ gridMode: 'auto' }); else s.set({ gridMode: 'manual', grid: Number(x) }) }}>
              <option value="auto">Auto ({s.grid}° statistics)</option><option value={0.25}>0.25°</option><option value={0.1}>0.1°</option><option value={0.05}>0.05°</option><option value={0.01}>0.01°</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-xs text-muted">Confidence
            <select className="field" aria-label="Confidence gate" value={conf}
              onChange={(e) => { const p = presets[e.target.value]; if (p) s.set({ modisMinConf: p[0], viirsConf: p[1] }) }}>
              <option value="default">Nominal + High (default)</option><option value="high">High only</option><option value="all">All, including low</option>
              {conf === 'custom' && <option value="custom">Custom (see Filters)</option>}
            </select>
          </label>
        </div>
      </div>
    )
  }
  return null
}

export default function App() {
  const s = useApp()
  const inv = useInventory()
  const regions = useApi<{ regions: Region[] }>('/api/regions')
  const health = useApi<{ readonly?: boolean; demo_note?: string | null }>('/api/health')
  const [hashPlatforms] = useState(() => new URLSearchParams(window.location.hash.slice(1)).has('platforms'))
  const view = useView()
  // below 1024 px the sidebar is a slide-over drawer: close it after a choice
  const closeOnSmall = () => { if (window.innerWidth < 1024) s.set({ navOpen: false }) }

  useEffect(() => {
    document.documentElement.classList.toggle('dark', s.theme === 'dark')
    try { localStorage.setItem('pyrosync-theme', s.theme) } catch { /* storage unavailable */ }
  }, [s.theme])

  // adopt the imported data range & platforms
  useEffect(() => {
    const d = inv.data
    if (!d) return
    if (d.dataset_revision !== s.revision) { clearCache(); s.set({ revision: d.dataset_revision }) }
    if (d.date_range) {
      const [a, b] = d.date_range
      const patch: Partial<typeof s> = { dataRange: [a, b] }
      if (!s.dataRange) {
        if (s.start < a || s.start > b) patch.start = a
        if (s.end > b || s.end < a) patch.end = b
        if (s.date < a || s.date > b) patch.date = b
        if (!hashPlatforms && d.available_platforms.length) patch.platforms = d.available_platforms
      }
      // primary sensor must exist in the data (e.g. the online demo has no NOAA-20)
      // (the harmonized series FUSED needs the MODIS Aqua reference; UNION needs any sensor)
      const ok = s.series === 'UNION' || (s.series === 'FUSED' ? d.available_series.includes('MODIS') : d.available_series.includes(s.series))
      if (d.available_series.length && !ok) {
        patch.series = ['VIIRS_N20', 'VIIRS_SNPP', 'VIIRS_N21', 'MODIS'].find((x) => d.available_series.includes(x)) ?? d.available_series[0]
      }
      s.set(patch)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inv.data])

  // poll revision so imports from the CLI show up automatically
  useEffect(() => {
    const id = window.setInterval(async () => {
      try {
        const r = await fetch('/api/health').then((x) => x.json())
        if (r.dataset_revision !== useApp.getState().revision) { clearCache(); useApp.getState().set({ revision: r.dataset_revision }) }
      } catch { /* offline backend: handled by error states */ }
    }, 15000)
    return () => window.clearInterval(id)
  }, [])

  const empty = inv.data && inv.data.observations_total === 0

  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[2000] focus:rounded focus:bg-panel focus:p-2">Skip to content</a>
      {s.navOpen && <div className="fixed inset-0 z-[1090] bg-zinc-950/40 lg:hidden" aria-hidden onClick={() => s.set({ navOpen: false })} />}
      <nav aria-label="Main" data-testid="sidebar" className={cls('z-[1100] flex shrink-0 flex-col border-r border-line bg-panel transition-[width,transform] duration-200',
        'max-lg:fixed max-lg:inset-y-0 max-lg:left-0 max-lg:w-64 max-lg:shadow-xl', s.navOpen ? 'lg:w-56' : 'max-lg:-translate-x-full lg:w-14')}>
        <div className="flex h-14 items-center gap-2 border-b border-line px-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white" aria-hidden>
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor"><path d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-3-1-6 1-9z" /></svg>
          </span>
          <div className={cls('min-w-0', !s.navOpen && 'lg:hidden')}><div className="text-[15px] font-semibold leading-tight">PyroSync</div><div className="truncate text-[11px] text-muted">Indonesia Fire Archive</div></div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className={cls('px-5 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted', !s.navOpen && 'lg:sr-only')}>Navigation</div>
          <ul className="space-y-0.5 p-2 pt-1">
            {WORKSPACES.map((w) => <NavItem key={w.id} w={w} onNavigate={closeOnSmall} />)}
          </ul>
          <AoiQuick regions={regions.data?.regions ?? []} onNavigate={closeOnSmall} />
        </div>
        <div className="space-y-2 border-t border-line p-2">
          {inv.data && <div className={cls('rounded-lg border border-line p-2.5 text-[11px] leading-snug', !s.navOpen && 'lg:hidden')} data-testid="sidebar-dataset">
            <div className="font-semibold text-ink">FIRMS {inv.data.date_range ? `${inv.data.date_range[0].slice(0, 4)}–${inv.data.date_range[1].slice(0, 4)}` : ''}</div>
            <div className="num text-muted">{inv.data.observations_total.toLocaleString('en-US')} observations</div>
          </div>}
          <div className={cls('seg w-full', !s.navOpen && 'lg:hidden')} role="group" aria-label="Color theme">
            <button className="flex-1" aria-pressed={s.theme === 'light'} onClick={() => s.set({ theme: 'light' })}>Light</button>
            <button className="flex-1" aria-pressed={s.theme === 'dark'} onClick={() => s.set({ theme: 'dark' })}>Dark</button>
          </div>
          <button type="button" className={cls('btn w-full justify-center px-0', s.navOpen && 'lg:hidden', 'max-lg:hidden')} aria-label={s.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            onClick={() => s.set({ theme: s.theme === 'dark' ? 'light' : 'dark' })}><Icon name={s.theme === 'dark' ? 'sun' : 'moon'} /></button>
          <button type="button" className="btn w-full justify-center px-0 max-lg:hidden" aria-label={s.navOpen ? 'Collapse sidebar' : 'Expand sidebar'} aria-expanded={s.navOpen}
            data-testid="sidebar-toggle" onClick={() => s.set({ navOpen: !s.navOpen })}><Icon name="sidebar" />{s.navOpen && <span>Collapse</span>}</button>
          <p className={cls('px-1 text-[10px] leading-snug text-muted', !s.navOpen && 'lg:hidden')}>Independent prototype using NASA FIRMS data and, where enabled, NASA GIBS imagery. Not an official NASA application.</p>
        </div>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar regions={regions.data?.regions ?? []} inventory={inv.data} />
        {health.data?.readonly && !view.demoHidden && <div className="flex items-start gap-2 border-b border-line bg-zinc-100 px-4 py-1 text-xs text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400" role="note" data-testid="demo-bar">
          <span className="min-w-0 flex-1">Read-only online demo: {health.data.demo_note ?? 'FIRMS sample data.'} Importing new data works in the local version only.</span>
          <button type="button" className="shrink-0 rounded p-0.5 hover:text-ink" aria-label="Dismiss demo notice"
            onClick={() => { view.set({ demoHidden: true }); try { sessionStorage.setItem('pyrosync-demo-bar', 'hidden') } catch { /* storage unavailable */ } }}><Icon name="x" className="h-3.5 w-3.5" /></button>
        </div>}
        <main id="main" className="min-h-0 flex-1 overflow-auto max-md:pb-16">
          {!empty && inv.data && <WorkspaceTabs />}
          {inv.error && <div className="p-6"><div role="alert" className="panel p-4 text-sm">Cannot reach the PyroSync backend ({inv.error}). Start it with the start script, then reload.</div></div>}
          {empty && s.page !== 'data' ? (
            <div className="mx-auto max-w-xl p-8">
              <div className="panel p-6">
                <h1 className="text-lg font-semibold">No data imported yet</h1>
                <p className="mt-2 text-sm text-muted">Import FIRMS MODIS/VIIRS CSV files or a ZIP archive to begin. Nothing is shown until real observations exist.</p>
                <button className="btn btn-primary mt-4" onClick={() => s.set({ page: 'data' })}>Go to Methods, Import</button>
              </div>
            </div>
          ) : s.page === 'data' ? <DataMethods /> : !inv.data ? null : s.page === 'explore' ? <Explore regions={regions.data?.regions ?? []} />
            : s.page === 'calendar' ? <CalendarPage /> : s.page === 'history' ? <HistoryPage /> : s.page === 'harmonization' ? <HarmonizationPage regions={regions.data?.regions ?? []} />
            : s.page === 'insights' ? <InsightsPage regions={regions.data?.regions ?? []} view={view.insView} /> : <Workbench view={view.wbView} />}
        </main>
        <BottomNav />
      </div>
    </div>
  )
}

/** Phone layout: the five workspaces as a bottom tab bar (same items and order as the sidebar). */
function BottomNav() {
  const s = useApp()
  return (
    <nav aria-label="Workspaces" data-testid="bottom-nav" className="fixed inset-x-0 bottom-0 z-[1050] grid grid-cols-5 border-t border-line bg-panel pb-[env(safe-area-inset-bottom)] md:hidden">
      {WORKSPACES.map((w) => {
        const active = workspaceOf(s.page) === w.id
        return (
          <button key={w.id} type="button" aria-current={active ? 'page' : undefined} data-testid={`tab-${w.id}`}
            onClick={() => { if (!active) s.set({ page: w.page, ...(w.id === 'calendar' ? { series: 'FUSED', metric: 'detections' } : {}) }) }}
            className={cls('flex h-14 min-w-0 flex-col items-center justify-center gap-0.5 text-[10px] font-medium', active ? 'text-ink' : 'text-muted')}>
            <Icon name={w.icon} className="h-[18px] w-[18px]" />
            <span className="max-w-full truncate px-0.5">{w.id === 'harmonization' ? 'Harmonize' : w.label}</span>
            <span className={cls('h-0.5 w-6 rounded-full', active ? 'bg-accent' : 'bg-transparent')} aria-hidden />
          </button>
        )
      })}
    </nav>
  )
}
