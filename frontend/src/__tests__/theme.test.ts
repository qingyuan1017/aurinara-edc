import { afterEach, describe, expect, it } from 'vitest'
import {
  applyTheme,
  createThemeStorage,
  initializeTheme,
  resolveTheme,
  resolveSystemTheme,
} from '@/lib/theme'

describe('theme adapter', () => {
  afterEach(() => {
    document.documentElement.className = ''
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-theme-mode')
  })

  it('resolves system preference without changing application state', () => {
    const darkWindow = { matchMedia: () => ({ matches: true }) }
    const lightWindow = { matchMedia: () => ({ matches: false }) }

    expect(resolveSystemTheme(darkWindow)).toBe('dark')
    expect(resolveTheme('system', lightWindow)).toBe('light')
    expect(resolveTheme('dark', lightWindow)).toBe('dark')
  })

  it('applies only the document theme presentation state', () => {
    expect(applyTheme('dark', document)).toBe('dark')

    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.classList.contains('light')).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.dataset.themeMode).toBe('dark')

    applyTheme('light', document)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.classList.contains('light')).toBe(true)
  })

  it('persists only validated values under the theme storage key', () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    } as unknown as Storage
    const adapter = createThemeStorage(storage)

    expect(adapter.set('dark')).toBe(true)
    expect(adapter.get()).toBe('dark')
    expect(values.size).toBe(1)
    expect(adapter.remove()).toBe(true)
    expect(adapter.get()).toBeNull()
  })

  it('initializes from persisted mode and safely handles unavailable storage', () => {
    const values = new Map<string, string>([['edc-theme-mode', 'dark']])
    const storage = createThemeStorage({
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    } as unknown as Storage)

    expect(initializeTheme(storage, document)).toBe('dark')
    expect(document.documentElement.dataset.themeMode).toBe('dark')

    const unavailable = createThemeStorage(null)
    expect(unavailable.get()).toBeNull()
    expect(unavailable.set('light')).toBe(false)
    expect(unavailable.remove()).toBe(false)
  })
})
