import { useEffect, useState } from 'react'
import { clearCache, useApi, type Region } from './api'
import { useInventory } from './hooks'
import { useApp, type Page } from './state'
import { cls } from './util'
import { Icon } from './components/ui'
import TopBar from './components/TopBar'
import Explore from './pages/Explore'
import CalendarPage from './pages/CalendarPage'
import HistoryPage from './pages/HistoryPage'
import Workbench from './pages/Workbench'
import DataMethods from './pages/DataMethods'

const NAV: { id: Page; label: string; icon: string; hint: string }[] = [
  { id: 'explore', label: 'Explore', icon: 'map', hint: 'Map, timeline and frame details' },
  { id: 'calendar', label: 'Burning Calendar', icon: 'cal', hint: 'Daily heatmap and ISO weeks' },
  { id: 'history', label: 'Historical Patterns', icon: 'chart', hint: 'Monthly, seasonal, annual, baselines, elevated periods' },
  { id: 'workbench', label: 'Sensor Workbench', icon: 'sensor', hint: 'Sensor-by-sensor comparison and source records' },
  { id: 'data', label: 'Data & Methods', icon: 'data', hint: 'Imports, FIRMS refresh, exports, methodology' },
]

export default function App() {
  const s = useApp()
  const inv = useInventory()
  const regions = useApi<{ regions: Region[] }>('/api/regions')
  const health = useApi<{ readonly?: boolean; demo_note?: string | null }>('/api/health')
  const [hashPlatforms] = useState(() => new URLSearchParams(window.location.hash.slice(1)).has('platforms'))

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
      if (s.series !== 'UNION' && d.available_series.length && !d.available_series.includes(s.series)) {
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
      <nav aria-label="Main" className={cls('z-[1100] flex shrink-0 flex-col border-r border-line bg-panel transition-[width]', s.navOpen ? 'w-56' : 'w-14',
        'max-md:fixed max-md:inset-y-0 max-md:left-0', !s.navOpen && 'max-md:w-0 max-md:overflow-hidden max-md:border-0')}>
        <div className="flex h-14 items-center gap-2 border-b border-line px-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white" aria-hidden>
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor"><path d="M12 2c1 4 6 6 6 12a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 3 0-3-1-6 1-9z" /></svg>
          </span>
          {s.navOpen && <div className="min-w-0"><div className="text-[15px] font-bold leading-tight">PyroSync</div><div className="truncate text-[11px] text-muted">Fire history, in context</div></div>}
        </div>
        <ul className="flex-1 space-y-1 p-2">
          {NAV.map((n) => (
            <li key={n.id}>
              <button type="button" onClick={() => { s.set({ page: n.id }); if (window.innerWidth < 768) s.set({ navOpen: false }) }}
                aria-current={s.page === n.id ? 'page' : undefined} title={n.hint}
                className={cls('flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm', s.page === n.id ? 'bg-soft font-semibold text-ink' : 'text-muted hover:bg-soft hover:text-ink')}>
                <Icon name={n.icon} className="h-[18px] w-[18px] shrink-0" />{s.navOpen && <span className="truncate">{n.label}</span>}
              </button>
            </li>
          ))}
        </ul>
        {s.navOpen && (
          <div className="space-y-2 border-t border-line p-3 text-[11px] leading-snug text-muted">
            <div className="seg w-full" role="group" aria-label="Color theme">
              <button className="flex-1" aria-pressed={s.theme === 'light'} onClick={() => s.set({ theme: 'light' })}>Light</button>
              <button className="flex-1" aria-pressed={s.theme === 'dark'} onClick={() => s.set({ theme: 'dark' })}>Dark</button>
            </div>
            <p>Independent hackathon prototype using NASA FIRMS data and, where enabled, NASA GIBS imagery. Not an official NASA application.</p>
          </div>
        )}
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar regions={regions.data?.regions ?? []} inventory={inv.data} />
        {health.data?.readonly && <div className="border-b border-line bg-amber-50 px-3 py-1.5 text-[12px] text-amber-900 dark:bg-amber-950 dark:text-amber-100" role="note">
          Read-only online demo: {health.data.demo_note ?? 'FIRMS sample data.'} Importing new data works in the local version only.</div>}
        <main id="main" className="min-h-0 flex-1 overflow-auto">
          {inv.error && <div className="p-6"><div role="alert" className="panel p-4 text-sm">Cannot reach the PyroSync backend ({inv.error}). Start it with the start script, then reload.</div></div>}
          {empty && s.page !== 'data' ? (
            <div className="mx-auto max-w-xl p-8">
              <div className="panel p-6">
                <h1 className="text-lg font-semibold">No data imported yet</h1>
                <p className="mt-2 text-sm text-muted">Import FIRMS MODIS/VIIRS CSV files or a ZIP archive to begin. Nothing is shown until real observations exist.</p>
                <button className="btn btn-primary mt-4" onClick={() => s.set({ page: 'data' })}>Go to Data &amp; Methods → Import</button>
              </div>
            </div>
          ) : s.page === 'data' ? <DataMethods /> : !inv.data ? null : s.page === 'explore' ? <Explore regions={regions.data?.regions ?? []} />
            : s.page === 'calendar' ? <CalendarPage /> : s.page === 'history' ? <HistoryPage /> : <Workbench />}
        </main>
      </div>
    </div>
  )
}
