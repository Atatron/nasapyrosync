// UI-only workspace grouping (no data logic). The seven page ids of the URL hash (#page=…) are unchanged:
// the sidebar shows five workspaces, and the sub-views of Insights and Harmonization map back onto those ids,
// so every existing link still opens the same content.
import { create } from 'zustand'
import type { Page } from './state'

export type WorkspaceId = 'explore' | 'calendar' | 'insights' | 'harmonization' | 'methods'

export const WORKSPACES: { id: WorkspaceId; label: string; icon: string; page: Page; hint: string }[] = [
  { id: 'explore', label: 'Explore', icon: 'compass', page: 'explore', hint: 'Map and daily monitoring' },
  { id: 'calendar', label: 'Calendar', icon: 'calendar', page: 'calendar', hint: 'Burning-activity calendar' },
  { id: 'insights', label: 'Insights', icon: 'lineChart', page: 'insights', hint: 'Season tracker, seasonal history and climate background' },
  { id: 'harmonization', label: 'Harmonization', icon: 'layers', page: 'harmonization', hint: 'Calibration audit, sensor workbench and source records' },
  { id: 'methods', label: 'Methods', icon: 'database', page: 'data', hint: 'Dataset inventory, methodology, imports and exports' },
]

export function workspaceOf(p: Page): WorkspaceId {
  if (p === 'history') return 'insights'
  if (p === 'workbench') return 'harmonization'
  if (p === 'data') return 'methods'
  return p
}

interface ViewState {
  insView: 'tracker' | 'climate' // page=insights shows the season tracker or the climate (ENSO / IOD) view
  wbView: 'series' | 'records' // page=workbench shows the sensor workbench or the source records
  demoHidden: boolean
  set: (p: Partial<Omit<ViewState, 'set'>>) => void
}

function readHidden() { try { return sessionStorage.getItem('pyrosync-demo-bar') === 'hidden' } catch { return false } }

export const useView = create<ViewState>((set) => ({
  insView: 'tracker',
  wbView: 'series',
  demoHidden: readHidden(),
  set: (p) => set(p),
}))
