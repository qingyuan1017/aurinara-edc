import { createContext, createElement, useCallback, useContext, useState, type ReactNode } from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = Exclude<ThemeMode, 'system'>

export const THEME_STORAGE_KEY = 'edc-theme-mode'

export interface ThemeStorageAdapter {
  get: () => ThemeMode | null
  set: (mode: ThemeMode) => boolean
  remove: () => boolean
}

export interface ThemeWindow {
  matchMedia?: (query: string) => Pick<MediaQueryList, 'matches'>
}

function isThemeMode(value: string | null): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

function getWindow(): ThemeWindow | undefined {
  if (typeof window === 'undefined') return undefined
  return window
}

function getDocument(): Document | undefined {
  if (typeof document === 'undefined') return undefined
  return document
}

function getSafeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    // Storage can be unavailable in private browsing, sandboxed documents, or SSR.
    return null
  }
}

export function createThemeStorage(storage: Storage | null = getSafeStorage()): ThemeStorageAdapter {
  return {
    get: () => {
      try {
        const value = storage?.getItem(THEME_STORAGE_KEY) ?? null
        return isThemeMode(value) ? value : null
      } catch {
        return null
      }
    },
    set: (mode) => {
      if (!isThemeMode(mode)) return false
      try {
        storage?.setItem(THEME_STORAGE_KEY, mode)
        return storage !== null
      } catch {
        return false
      }
    },
    remove: () => {
      try {
        storage?.removeItem(THEME_STORAGE_KEY)
        return storage !== null
      } catch {
        return false
      }
    },
  }
}

/** A namespaced adapter that never reads or writes auth, route, query, or study state. */
export const themeStorage: ThemeStorageAdapter = {
  get: () => createThemeStorage().get(),
  set: (mode) => createThemeStorage().set(mode),
  remove: () => createThemeStorage().remove(),
}

export function getStoredTheme(storage: ThemeStorageAdapter = themeStorage): ThemeMode | null {
  return storage.get()
}

export function persistTheme(mode: ThemeMode, storage: ThemeStorageAdapter = themeStorage): boolean {
  return storage.set(mode)
}

export function clearPersistedTheme(storage: ThemeStorageAdapter = themeStorage): boolean {
  return storage.remove()
}

export function resolveSystemTheme(windowRef: ThemeWindow | undefined = getWindow()): ResolvedTheme {
  try {
    return windowRef?.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function resolveTheme(
  mode: ThemeMode,
  windowRef: ThemeWindow | undefined = getWindow(),
): ResolvedTheme {
  return mode === 'system' ? resolveSystemTheme(windowRef) : mode
}

export function applyTheme(
  mode: ThemeMode,
  documentRef: Document | undefined = getDocument(),
  windowRef: ThemeWindow | undefined = getWindow(),
): ResolvedTheme {
  const resolvedTheme = resolveTheme(mode, windowRef)
  const root = documentRef?.documentElement

  if (!root) return resolvedTheme

  root.classList.toggle('dark', resolvedTheme === 'dark')
  root.classList.toggle('light', resolvedTheme === 'light')
  root.setAttribute('data-theme', resolvedTheme)
  root.setAttribute('data-theme-mode', mode)

  return resolvedTheme
}

export function initializeTheme(
  storage: ThemeStorageAdapter = themeStorage,
  documentRef: Document | undefined = getDocument(),
  windowRef: ThemeWindow | undefined = getWindow(),
): ResolvedTheme {
  return applyTheme(storage.get() ?? 'system', documentRef, windowRef)
}

export function setTheme(
  mode: ThemeMode,
  options: {
    persist?: boolean
    storage?: ThemeStorageAdapter
    documentRef?: Document
    windowRef?: ThemeWindow
  } = {},
): ResolvedTheme {
  const storage = options.storage ?? themeStorage
  if (options.persist !== false) storage.set(mode)
  return applyTheme(mode, options.documentRef ?? getDocument(), options.windowRef ?? getWindow())
}

export interface ThemeContextValue {
  mode: ThemeMode
  resolvedTheme: ResolvedTheme
  setTheme: (mode: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export interface ThemeProviderProps {
  children: ReactNode
  storage?: ThemeStorageAdapter
  documentRef?: Document
  windowRef?: ThemeWindow
}

export function ThemeProvider({
  children,
  storage = themeStorage,
  documentRef,
  windowRef,
}: ThemeProviderProps) {
  const [mode, setMode] = useState<ThemeMode>(() => storage.get() ?? 'system')
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() =>
    applyTheme(mode, documentRef ?? getDocument(), windowRef ?? getWindow()),
  )

  const changeTheme = useCallback(
    (nextMode: ThemeMode) => {
      const nextResolvedTheme = setTheme(nextMode, {
        storage,
        documentRef,
        windowRef,
      })
      setMode(nextMode)
      setResolvedTheme(nextResolvedTheme)
    },
    [documentRef, storage, windowRef],
  )

  return createElement(
    ThemeContext.Provider,
    { value: { mode, resolvedTheme, setTheme: changeTheme } },
    children,
  )
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within a ThemeProvider')
  return context
}
