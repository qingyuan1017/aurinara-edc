const LAST_WORKSPACE_KEY = 'ctms-last-workspace'
const PREFERENCES_KEY = 'ctms-workspace-preferences'

export interface CTMSWorkspacePreferences {
  readonly favorites: readonly string[]
  readonly recents: readonly string[]
}

const emptyPreferences: CTMSWorkspacePreferences = { favorites: [], recents: [] }

export function getLastCTMSWorkspacePath(): string {
  try {
    const value = localStorage.getItem(LAST_WORKSPACE_KEY)
    return value?.startsWith('/studies/') && value.includes('/ctms') ? value : '/ctms'
  } catch {
    return '/ctms'
  }
}

export function rememberCTMSWorkspacePath(pathname: string): void {
  if (pathname !== '/ctms' && !(pathname.startsWith('/studies/') && pathname.includes('/ctms'))) return
  try { localStorage.setItem(LAST_WORKSPACE_KEY, pathname) } catch { /* in-memory navigation still works */ }
}

export function readCTMSWorkspacePreferences(): CTMSWorkspacePreferences {
  try {
    const parsed = JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? '{}') as Partial<CTMSWorkspacePreferences>
    return {
      favorites: Array.isArray(parsed.favorites) ? parsed.favorites.filter((value): value is string => typeof value === 'string') : [],
      recents: Array.isArray(parsed.recents) ? parsed.recents.filter((value): value is string => typeof value === 'string').slice(0, 5) : [],
    }
  } catch {
    return emptyPreferences
  }
}

export function saveCTMSWorkspacePreferences(preferences: CTMSWorkspacePreferences): void {
  try { localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences)) } catch { /* optional convenience state */ }
}

export function recordRecentStudy(preferences: CTMSWorkspacePreferences, studyId: string): CTMSWorkspacePreferences {
  return { ...preferences, recents: [studyId, ...preferences.recents.filter((id) => id !== studyId)].slice(0, 5) }
}

export const CTMS_WORKSPACE_STORAGE_KEYS = { lastWorkspace: LAST_WORKSPACE_KEY, preferences: PREFERENCES_KEY } as const
