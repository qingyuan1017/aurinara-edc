import { create } from 'zustand'

/** The two top-level product modules a user can work in. */
export type AppModule = 'edc' | 'ctms'

const STORAGE_KEY = 'active_module'

function readStoredModule(): AppModule | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'edc' || value === 'ctms' ? value : null
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
 * Module store — tracks which product module (EDC or CTMS) the user has
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
