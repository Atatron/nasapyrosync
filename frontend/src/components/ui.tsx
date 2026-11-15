import { Suspense, lazy, useId, useState, type ReactNode } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import { cls } from '../util'

const EChartImpl = lazy(() => import('./EChartImpl'))
export function EChart(props: {
  option: EChartsCoreOption; height?: number | string; onClick?: (p: { dataIndex: number; seriesName?: string; name?: string }) => void
  ariaLabel: string; className?: string
}) {
  return <Suspense fallback={<div role="img" aria-label={props.ariaLabel} className={props.className} style={{ height: props.height ?? 220, width: '100%' }} />}><EChartImpl {...props} /></Suspense>
}

export function Info({ children, label = 'More information' }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <span className="relative inline-block align-middle">
      <button type="button" aria-label={label} aria-expanded={open} aria-describedby={open ? id : undefined}
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-line text-[10px] font-bold text-muted hover:text-ink"
        onClick={() => setOpen((o) => !o)} onBlur={() => setOpen(false)} onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>i</button>
      {open && (
        <span id={id} role="tooltip" className="absolute left-1/2 top-5 z-[1200] w-72 -translate-x-1/2 rounded-lg border border-line bg-panel p-3 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-ink shadow-lg">
          {children}
        </span>
      )}
    </span>
  )
}

export function Panel({ title, info, actions, children, className, id }: { title?: ReactNode; info?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={cls('panel p-4', className)} aria-labelledby={id}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 id={id} className="text-sm font-semibold">{title}{info && <Info>{info}</Info>}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

/** Two or three options: a segmented pill. Four or more: a compact dropdown (same values, same onChange). */
export function Seg<T extends string | number>({ value, options, onChange, label, pills }: { value: T; options: { value: T; label: string; title?: string }[]; onChange: (v: T) => void; label: string; pills?: boolean }) {
  if (options.length >= 4 && !pills) {
    const i = options.findIndex((o) => o.value === value)
    return (
      <select className="field" aria-label={label} value={i < 0 ? '' : String(i)} title={options[i]?.title} onChange={(e) => { const o = options[Number(e.target.value)]; if (o) onChange(o.value) }}>
        {i < 0 && <option value="" disabled>{label}</option>}
        {options.map((o, k) => <option key={String(o.value)} value={String(k)} title={o.title}>{o.label}</option>)}
      </select>
    )
  }
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} title={o.title} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line px-4 py-6 text-center">
      <p className="text-sm font-semibold">{title}</p>
      {children && <div className="max-w-md text-xs text-muted">{children}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="flex items-center gap-2 text-xs text-muted" role="status"><span className="spinner" aria-hidden />{label}</div>
}

export function ErrorNote({ msg }: { msg: string }) {
  return <div role="alert" className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{msg}</div>
}

export function Warnings({ items }: { items?: string[] }) {
  if (!items || !items.length) return null
  return (
    <ul className="space-y-1">
      {items.map((w, i) => <li key={i} className="rounded-md bg-amber-50 px-2 py-1 text-[11px] leading-snug text-amber-900 dark:bg-amber-950 dark:text-amber-200">⚠ {w}</li>)}
    </ul>
  )
}

export function Icon({ name, className = 'h-4 w-4' }: { name: string; className?: string }) {
  const p: Record<string, ReactNode> = {
    map: <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zm0 0v14m6-12v14" />,
    cal: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4m8-4v4" /></>,
    chart: <path d="M4 20V10m6 10V4m6 16v-7m6 7H2" />,
    insights: <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2M12 2v2m0 16v2M2 12h2m16 0h2" /></>,
    doc: <><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5M10 13h6m-6 4h6" /></>,
    harmonize: <path d="M4 7h13m0 0-3-3m3 3-3 3M20 17H7m0 0 3-3m-3 3 3 3" />,
    sensor: <><circle cx="12" cy="12" r="3" /><path d="M5 12a7 7 0 0 1 14 0M2 12a10 10 0 0 1 20 0" /></>,
    data: <><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>,
    panel: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></>,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    play: <path d="M7 5v14l11-7z" />,
    pause: <path d="M7 5h3v14H7zm7 0h3v14h-3z" />,
    prev: <path d="m15 6-6 6 6 6" />,
    next: <path d="m9 6 6 6-6 6" />,
    download: <path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14" />,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
    moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
    filter: <path d="M4 5h16l-6 8v6l-4-2v-4z" />,
    flag: <path d="M5 21V4m0 0h11l-2 4 2 4H5" />,
    x: <path d="M6 6l12 12M18 6 6 18" />,
    upload: <path d="M12 20V9m0 0-4 4m4-4 4 4M5 4h14" />,
    // Lucide icons (ISC licence) for the five workspaces
    compass: <><circle cx="12" cy="12" r="10" /><path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36z" /></>,
    calendar: <><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></>,
    lineChart: <><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" /></>,
    layers: <><path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z" /><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65M22 12.65l-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" /></>,
    database: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0" /></>,
    sidebar: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /></>,
    maximize: <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />,
    minimize: <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />,
    theater: <><rect x="2" y="6" width="20" height="12" rx="2" /></>,
    sliders: <path d="M21 4h-7m-4 0H3m18 8h-9m-4 0H3m18 8h-5m-4 0H3M14 2v4M8 10v4m8 4v4" />,
    panelRight: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M15 3v18" /></>,
    pin: <><path d="M20 10c0 5-5.5 10.2-7.4 11.8a1 1 0 0 1-1.2 0C9.5 20.2 4 15 4 10a8 8 0 0 1 16 0" /><circle cx="12" cy="10" r="3" /></>,
    link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
  }
  return <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className}>{p[name]}</svg>
}

export function StatusSwatch({ status, color }: { status: string; color?: string }) {
  if (status === 'unknown') return <span className="hatch inline-block h-3 w-3 rounded-sm border border-zinc-400" aria-hidden />
  if (status === 'zero_reported') return <span className="inline-block h-3 w-3 rounded-sm border border-zinc-300 bg-zinc-100 dark:bg-zinc-800" aria-hidden />
  if (status === 'outside_range' || status === 'sensor_unavailable') return <span className="inline-block h-3 w-3 rounded-sm border border-dashed border-zinc-300" aria-hidden />
  return <span className="inline-block h-3 w-3 rounded-sm" style={{ background: color ?? '#f59e0b' }} aria-hidden />
}
