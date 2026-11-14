import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { cls } from '../util'

echarts.use([BarChart, LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, DataZoomComponent, CanvasRenderer])

export function EChart({ option, height = 220, onClick, ariaLabel, className }: {
  option: echarts.EChartsCoreOption; height?: number | string; onClick?: (p: { dataIndex: number; seriesName?: string; name?: string }) => void
  ariaLabel: string; className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)
  const clickRef = useRef(onClick)
  clickRef.current = onClick
  useEffect(() => {
    if (!ref.current) return
    const c = echarts.init(ref.current, undefined, { renderer: 'canvas' })
    inst.current = c
    c.on('click', (p) => clickRef.current?.(p as never))
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); c.dispose(); inst.current = null }
  }, [])
  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    inst.current?.setOption({ animation: !reduced, ...(option as object) }, true)
  }, [option])
  return <div ref={ref} role="img" aria-label={ariaLabel} className={className} style={{ height, width: '100%' }} />
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

export function Seg<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string; title?: string }[]; onChange: (v: T) => void; label: string }) {
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
    link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
  }
  return <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className}>{p[name]}</svg>
}

export function StatusSwatch({ status, color }: { status: string; color?: string }) {
  if (status === 'unknown') return <span className="hatch inline-block h-3 w-3 rounded-sm border border-slate-400" aria-hidden />
  if (status === 'zero_reported') return <span className="inline-block h-3 w-3 rounded-sm border border-slate-300 bg-slate-100 dark:bg-slate-800" aria-hidden />
  if (status === 'outside_range' || status === 'sensor_unavailable') return <span className="inline-block h-3 w-3 rounded-sm border border-dashed border-slate-300" aria-hidden />
  return <span className="inline-block h-3 w-3 rounded-sm" style={{ background: color ?? '#f59e0b' }} aria-hidden />
}
