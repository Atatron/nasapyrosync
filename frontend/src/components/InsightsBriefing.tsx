// Printable one-page briefing of the AOI Insights tab (added in v1.3), in English or Indonesian.
// It only restates numbers computed by the API; nothing here is estimated or forecast.
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useApi } from '../api'
import {
  BAND_COLOR, BAND_ORDER, T, dayLabel, fmtDay, insQS, phaseText, trackerSentence, useIns,
  type Anomaly, type Critical, type Lang, type Recurrence, type Regime, type YearsReport,
} from '../insights'
import { useApp } from '../state'
import { addDays, type ISODate } from '../util'
import { Loading } from './ui'

const SERIES_NAME: Record<string, string> = { MODIS: 'MODIS (Terra + Aqua)', VIIRS_SNPP: 'VIIRS S-NPP', VIIRS_N20: 'VIIRS NOAA-20', VIIRS_N21: 'VIIRS NOAA-21' }

function fmtDate(iso: string, lang: Lang) { return dayLabel(fmtDay(iso), lang) }
function n(v: number | null | undefined, lang: Lang, d = 0) {
  return v === null || v === undefined ? '—' : v.toLocaleString(lang === 'id' ? 'id-ID' : 'en-US', { maximumFractionDigits: d })
}

export default function Briefing({ asOf, aoiName, onClose }: { asOf: ISODate; aoiName: string; onClose: () => void }) {
  const s = useApp()
  const ins = useIns()
  const lang = ins.lang
  const t = T[lang]
  const first = useApp((x) => x.dataRange?.[0]) ?? asOf
  const qs = insQS(s, ins.series, `${asOf.slice(0, 4)}-01-01`, asOf)
  const aStart = addDays(asOf, -179) < first ? first : addDays(asOf, -179)
  const rg = useApi<Regime>(`/api/insights/regime?${qs}&metric=detections`)
  const an = useApi<Anomaly>(`/api/insights/anomaly?${insQS(s, ins.series, aStart, asOf)}&metric=detections`)
  const cr = useApi<Critical>(`/api/insights/critical?${qs}&metric=detections&percentile=${ins.percentile}`)
  const rc = useApi<Recurrence>(`/api/insights/recurrence?${qs}&chronic_share=${ins.chronicShare}`)
  const yr = useApi<YearsReport>(`/api/insights/years?${qs}&metric=detections`)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const after = () => document.body.classList.remove('printing-briefing')
    window.addEventListener('afterprint', after)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('afterprint', after); after() }
  }, [onClose])

  const print = () => { document.body.classList.add('printing-briefing'); window.print() }
  const loading = [rg, an, cr, rc, yr].some((q) => !q.data && !q.error)
  const r = rg.data, a = an.data, c = cr.data, re = rc.data, y = yr.data
  const last30 = (a?.days ?? []).filter((d) => d.date > addDays(asOf, -30))
  const bandCount = (b: string) => last30.filter((d) => d.band === b).length
  const topWeeks = (c?.available ? [...c.readiness.weeks] : []).filter((w) => w.years_known > 0 && w.years_critical / w.years_known >= 1 / 3)
  const ensoGroup = y?.groups.enso ?? []

  return createPortal(
    <div className="briefing-overlay fixed inset-0 z-[3000] overflow-auto bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={t.title}>
      <div className="no-print mx-auto mb-3 flex max-w-[820px] flex-wrap items-center justify-between gap-2 rounded-lg bg-panel p-2">
        <div className="seg" role="group" aria-label="Briefing language">
          <button type="button" aria-pressed={lang === 'en'} onClick={() => ins.set({ lang: 'en' })}>English</button>
          <button type="button" aria-pressed={lang === 'id'} onClick={() => ins.set({ lang: 'id' })}>Bahasa Indonesia</button>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={print} disabled={loading}>{t.print}</button>
          <button className="btn" onClick={onClose}>{t.close}</button>
        </div>
      </div>
      <article className="briefing-sheet mx-auto max-w-[820px] rounded-lg p-8 text-[13px] leading-relaxed shadow-xl" lang={lang}>
        <header className="border-b border-slate-300 pb-3">
          <h1 className="text-xl font-bold">{t.title}: {aoiName}</h1>
          <p className="text-[12px] text-slate-600">{t.sensor}: {SERIES_NAME[ins.series]} · {t.asof}: {fmtDate(asOf, lang)}
            {r?.history && <> · {t.history}: {fmtDate(r.history.start, lang)} – {fmtDate(r.history.end, lang)}</>}</p>
        </header>
        <section className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-[12px]">
          <b>{t.disclaimerTitle}.</b> {t.disclaimer}
        </section>
        {loading ? <div className="mt-4"><Loading /></div> : <>
          <section>
            <h2>{t.status}</h2>
            {r?.available && r.tracker?.status ? <p>{trackerSentence(r.tracker.status, r.focus_year, 'detections', lang)}</p> : <p>{t.nodata}</p>}
          </section>
          <section>
            <h2>{t.season}</h2>
            {r?.available && r.season ? (
              <table className="data"><tbody>
                <tr><td>{t.onset}</td><td><b>{dayLabel(r.season.onset.median, lang)}</b> ({dayLabel(r.season.onset.early, lang)} – {dayLabel(r.season.onset.late, lang)})</td></tr>
                <tr><td>{t.peak}</td><td><b>{dayLabel(r.season.peak.median, lang)}</b> ({dayLabel(r.season.peak.early, lang)} – {dayLabel(r.season.peak.late, lang)})</td></tr>
                <tr><td>{t.end}</td><td><b>{dayLabel(r.season.end.median, lang)}</b> ({dayLabel(r.season.end.early, lang)} – {dayLabel(r.season.end.late, lang)})</td></tr>
                {r.peak_week && <tr><td>{t.peakweek}</td><td><b>{dayLabel(r.peak_week.label, lang)}</b></td></tr>}
              </tbody></table>
            ) : <p>{t.nodata}</p>}
            <p className="text-[11px] text-slate-600">{lang === 'id' ? 'Rentang dalam kurung: persentil ke-10 sampai ke-90 dari tahun-tahun lengkap.' : 'Range in brackets: 10th to 90th percentile of complete years.'}</p>
          </section>
          <section>
            <h2>{t.unusual}</h2>
            {last30.some((d) => d.band) ? (
              <p>{BAND_ORDER.map((b) => <span key={b} className="mr-3 inline-flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: BAND_COLOR[b] }} />{t[b]}: <b>{bandCount(b)}</b></span>)}</p>
            ) : <p>{t.nodata}</p>}
          </section>
          <section>
            <h2>{t.critical}</h2>
            {c?.available ? <>
              <p>{t.weeks}: {topWeeks.length ? topWeeks.map((w) => `${dayLabel(w.label, lang)} (${w.years_critical}/${w.years_known})`).join(', ') : t.none}.</p>
              <p className="mt-1 font-semibold">{t.criticalTop}</p>
              <table className="data"><tbody>{c.periods.slice(0, 5).map((p) => <tr key={p.start}>
                <td>{fmtDate(p.start, lang)} – {fmtDate(p.end, lang)}</td><td className="text-right">{p.duration_days} {lang === 'id' ? 'hari' : 'days'}</td>
                <td className="text-right">{lang === 'id' ? 'puncak' : 'peak'} {n(p.peak, lang)}</td></tr>)}</tbody></table>
            </> : <p>{t.nodata}</p>}
          </section>
          <section>
            <h2>{t.recurrence}</h2>
            {re?.available ? <p><b>{n(re.chronic_cells, lang)}</b> {t.chronic.replace('{p}', String(Math.round(re.chronic_share * 100)))} {t.of} {n(re.cells_total, lang)} {lang === 'id' ? 'sel dengan kebakaran' : 'cells with fire'} ({re.grid_size}°, {re.n_eligible_years} {t.years}).</p> : <p>{t.nodata}</p>}
          </section>
          <section>
            <h2>{t.climate}</h2>
            {y ? <>
              <p>{t.enso}: {y.climate_latest.oni.season} {y.climate_latest.oni.year} = <b>{y.climate_latest.oni.value.toFixed(2)} °C</b> · {t.iod}: {y.climate_latest.dmi.year}-{String(y.climate_latest.dmi.month).padStart(2, '0')} = <b>{y.climate_latest.dmi.value.toFixed(2)} °C</b></p>
              <p className="mt-1">{t.analog}: {ensoGroup.map((g) => `${phaseText(g.phase, lang)} ${g.enough ? n(g.median_total, lang) : '—'} (${g.n_years} ${t.years})`).join(' · ')}</p>
              <p className="text-[11px] text-slate-600">{lang === 'id'
                ? 'Tahun analog menunjukkan apa yang terjadi pada musim-musim lalu dengan latar iklim serupa. Ini pola dari sedikit musim, bukan prakiraan.'
                : 'Analog years show what happened in past seasons with a similar climate background. A pattern from a handful of seasons, not a forecast.'}</p>
            </> : <p>{t.nodata}</p>}
          </section>
          <footer className="mt-4 border-t border-slate-300 pt-2 text-[11px] text-slate-600">
            {t.sources} {r && <>{lang === 'id' ? 'Versi metode' : 'Method version'} {r.method_version}, {lang === 'id' ? 'revisi data' : 'dataset revision'} {r.dataset_revision}. </>}
            {t.generated}: {new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC.
          </footer>
        </>}
      </article>
    </div>,
    document.body,
  )
}
