import { create } from 'zustand'

/** The top-level product modules a user can work in. */
export type AppModule = 'designer' | 'edc' | 'ctms' | 'pv'

const STORAGE_KEY = 'active_module'
const LEGACY_DESIGNER_PATH = /^\/studies\/[^/]+\/(?:forms|versions|edit-checks)\/?$/

/** Resolve the product hierarchy for direct links as well as module switches. */
export function resolveAppModule(pathname: string): AppModule {
  if (pathname.includes('/pv')) return 'pv'
  if (pathname.includes('/ctms')) return 'ctms'
  if (
    pathname.includes('/designer')
    || pathname === '/forms'
    || pathname === '/edit-checks'
    || LEGACY_DESIGNER_PATH.test(pathname)
  ) return 'designer'
  return 'edc'
}

function readStoredModule(): AppModule | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'designer' || value === 'edc' || value === 'ctms' || value === 'pv' ? value : null
  } catch {
    return null
  }
}

function persistModule(module: AppModule | null): void {
  try {
    if (module) {
      localStorage.setItem(STORAGE_KEY, module)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // localStorage may be unavailable (private mode); state still works in-memory.
  }
}

interface ModuleState {
  /** The module the user is actively working in, or null before a choice is made. */
  activeModule: AppModule | null
  /**
   * True once the picker has been shown (or auto-resolved) during the current
   * session. Lets us always show the picker on a fresh login while still
   * remembering the last choice across page refreshes.
   */
  resolvedThisSession: boolean
  setModule: (module: AppModule) => void
  clearModule: () => void
  markResolved: () => void
}

/**
 * Module store — tracks which product module (Designer, EDC, CTMS, or PV) the user has
 * selected. The choice is persisted to localStorage so a returning user's
 * preference is remembered, while `resolvedThisSession` lets the app re-show
 * the picker once per fresh login.
 */
export const useModuleStore = create<ModuleState>((set) => ({
  activeModule: readStoredModule(),
  resolvedThisSession: false,
  setModule: (module) => {
    persistModule(module)
    set({ activeModule: module, resolvedThisSession: true })
  },
  clearModule: () => {
    persistModule(null)
    set({ activeModule: null })
  },
  markResolved: () => set({ resolvedThisSession: true }),
}))

export const MODULE_STORAGE_KEY = STORAGE_KEY
