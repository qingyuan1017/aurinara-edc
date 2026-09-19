import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useForm } from 'react-hook-form'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import { useAuthStore, type CurrentUser } from '@/lib/auth'
import {
  ThemeProvider,
  useTheme,
  type ThemeStorageAdapter,
} from '@/lib/theme'
import { useStudyContext } from '@/lib/study-context'

vi.mock('@/lib/router', () => ({ router: {} }))
vi.mock('@/features/auth', () => ({ useInactivityLogout: () => undefined }))
vi.mock('@tanstack/react-router', () => ({
  RouterProvider: ({ router }: { router: unknown }) => (
    <div data-testid="router-provider" data-router-present={String(router !== undefined)} />
  ),
}))

const authenticatedUser: CurrentUser = {
  id: 'user-1',
  email: 'user@example.com',
  first_name: 'Test',
  last_name: 'User',
  roles: [],
  permissions: ['studies:read'],
}

function createMemoryStorage(initial: string | null = null): ThemeStorageAdapter {
  let value = initial
  return {
    get: () => (value === 'light' || value === 'dark' || value === 'system' ? value : null),
    set: (nextMode) => {
      value = nextMode
      return true
    },
    remove: () => {
      value = null
      return true
    },
  }
}

function StateProbe() {
  const { mode, resolvedTheme, setTheme } = useTheme()
  const queryClient = useQueryClient()
  const { register, watch } = useForm({ defaultValues: { draft: 'initial draft' } })
  const draft = watch('draft')
  const { selectedStudyId, selectedSiteId } = useStudyContext()

  return (
    <div>
      <output data-testid="theme-mode">{mode}</output>
      <output data-testid="resolved-theme">{resolvedTheme}</output>
      <output data-testid="route-state">{window.location.pathname}{window.location.search}</output>
      <output data-testid="query-client">{String(queryClient.getQueryData(['theme-test']))}</output>
      <output data-testid="study-context">{selectedStudyId}:{selectedSiteId}</output>
      <input aria-label="form draft" {...register('draft')} />
      <output data-testid="form-draft">{draft}</output>
      <button type="button" onClick={() => setTheme('light')}>Use light theme</button>
    </div>
  )
}

afterEach(() => {
  useAuthStore.getState().setUser(null)
  useStudyContext.getState().clear()
  localStorage.clear()
  document.documentElement.className = ''
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-theme-mode')
  window.history.replaceState({}, '', '/')
  vi.clearAllMocks()
})

describe('application theme root', () => {
  it('resolves the persisted theme before rendering the existing router tree', () => {
    localStorage.setItem('edc-theme-mode', 'dark')

    render(<App />)

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.dataset.themeMode).toBe('dark')
    expect(screen.getByTestId('router-provider')).toHaveAttribute('data-router-present', 'true')
  })

  it('switches only presentation state while preserving route, auth, query, form, and study context', async () => {
    const user = userEvent.setup()
    const queryClient = new QueryClient()
    queryClient.setQueryData(['theme-test'], 'cached query data')
    const storage = createMemoryStorage('dark')
    const routeState = '/studies/study-1?filter=active&page=2'

    useAuthStore.getState().setUser(authenticatedUser)
    useStudyContext.getState().setStudy('study-1')
    useStudyContext.getState().setSite('site-1')
    window.history.replaceState({}, '', routeState)

    render(
      <ThemeProvider storage={storage} documentRef={document} windowRef={{ matchMedia: () => ({ matches: false }) }}>
        <QueryClientProvider client={queryClient}>
          <StateProbe />
        </QueryClientProvider>
      </ThemeProvider>,
    )

    const draft = screen.getByRole('textbox', { name: 'form draft' })
    await user.clear(draft)
    await user.type(draft, 'edited draft')
    await user.click(screen.getByRole('button', { name: 'Use light theme' }))

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(document.documentElement.dataset.themeMode).toBe('light')
    expect(screen.getByTestId('theme-mode')).toHaveTextContent('light')
    expect(screen.getByTestId('resolved-theme')).toHaveTextContent('light')
    expect(screen.getByTestId('route-state')).toHaveTextContent(routeState)
    expect(screen.getByTestId('query-client')).toHaveTextContent('cached query data')
    expect(screen.getByTestId('study-context')).toHaveTextContent('study-1:site-1')
    expect(draft).toHaveValue('edited draft')
    expect(useAuthStore.getState().user).toEqual(authenticatedUser)
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
  })
})
