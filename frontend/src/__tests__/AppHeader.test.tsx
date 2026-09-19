import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppHeader } from '@/components/layout/AppHeader'
import { Breadcrumbs } from '@/components/layout/Breadcrumbs'
import { GlobalSearch } from '@/components/layout/GlobalSearch'
import { SiteSelector } from '@/components/layout/SiteSelector'
import { StudySelector } from '@/components/layout/StudySelector'
import { ThemeToggle } from '@/components/layout/ThemeToggle'
import { UserMenu } from '@/components/layout/UserMenu'
import { ThemeProvider, type ThemeStorageAdapter } from '@/lib/theme'
import { api } from '@/lib/api'
import { useStudyContext } from '@/lib/study-context'

type RouterLinkProps = {
  to: string
  search?: unknown
  children: React.ReactNode
  className?: string
  [key: string]: unknown
}

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, search, children, ...props }: RouterLinkProps) => {
    const preservedSearch = typeof search === 'function'
      ? (search as (previous: Record<string, unknown>) => Record<string, unknown>)({ filter: 'active', page: 2 })
      : search
    const query = preservedSearch && Object.keys(preservedSearch).length > 0
      ? `?${new URLSearchParams(Object.entries(preservedSearch).map(([key, value]) => [key, String(value)])).toString()}`
      : ''
    return <a href={`${to}${query}`} data-preserved-search={JSON.stringify(preservedSearch)} {...props}>{children}</a>
  },
  useLocation: () => ({ pathname: '/subjects/subject-1', search: { filter: 'active', page: 2 }, hash: '' }),
}))

function createMemoryThemeStorage(initial: 'light' | 'dark' | 'system' = 'system'): ThemeStorageAdapter {
  let value = initial
  return {
    get: () => value,
    set: (next) => { value = next; return true },
    remove: () => true,
  }
}

function renderWithQuery(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  useStudyContext.getState().clear()
  document.documentElement.className = ''
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-theme-mode')
  window.history.replaceState({}, '', '/')
  vi.restoreAllMocks()
})

describe('AppHeader controls', () => {
  it('renders selectors, breadcrumbs, notifications, search affordance, theme, and account controls', () => {
    renderWithQuery(
      <ThemeProvider storage={createMemoryThemeStorage()} documentRef={document} windowRef={{ matchMedia: () => ({ matches: false }) }}>
        <AppHeader displayName="Test User" onSignOut={vi.fn()} />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('app-header')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Select study' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Select study' })).toHaveClass('border-input', 'bg-background', 'focus-visible:ring-ring')
    expect(screen.getByRole('combobox', { name: 'Select site' })).toHaveClass('border-input', 'bg-background', 'focus-visible:ring-ring')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Subjects')
    expect(screen.getByRole('link', { name: 'Notifications' })).toHaveAttribute('href', '/notifications?filter=active&page=2')
    expect(screen.getByRole('button', { name: 'Global search unavailable' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Theme: system' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open user menu for Test User' })).toBeInTheDocument()
  })

  it('renders a keyboard-operable mobile navigation trigger without changing route state', async () => {
    const user = userEvent.setup()
    const onMobileMenuOpen = vi.fn()
    window.history.replaceState({}, '', '/subjects/subject-1?filter=active&page=2')

    renderWithQuery(
      <ThemeProvider storage={createMemoryThemeStorage()} documentRef={document} windowRef={{ matchMedia: () => ({ matches: false }) }}>
        <AppHeader displayName="Test User" onSignOut={vi.fn()} onMobileMenuOpen={onMobileMenuOpen} />
      </ThemeProvider>,
    )

    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    expect(trigger).toHaveAttribute('aria-controls', 'mobile-navigation')
    trigger.focus()
    await user.keyboard('{Enter}')

    expect(onMobileMenuOpen).toHaveBeenCalledTimes(1)
    expect(window.location.pathname + window.location.search).toBe('/subjects/subject-1?filter=active&page=2')
  })

  it('preserves route search values in breadcrumb parent links', () => {
    render(<Breadcrumbs />)

    const parentLink = screen.getByRole('link', { name: 'Subjects' })
    expect(parentLink).toHaveAttribute('href', '/subjects?filter=active&page=2')
    expect(parentLink).toHaveAttribute('data-preserved-search', JSON.stringify({ filter: 'active', page: 2 }))
  })

  it('switches theme presentation without changing the route context', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/subjects/subject-1?filter=active&page=2')

    render(
      <ThemeProvider storage={createMemoryThemeStorage()} documentRef={document} windowRef={{ matchMedia: () => ({ matches: false }) }}>
        <ThemeToggle />
      </ThemeProvider>,
    )

    await user.click(screen.getByRole('button', { name: 'Theme: system' }))
    await user.click(screen.getByRole('menuitem', { name: 'Dark' }))

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.location.pathname + window.location.search).toBe('/subjects/subject-1?filter=active&page=2')
    expect(screen.getByRole('button', { name: 'Theme: dark' })).toBeInTheDocument()
  })

  it('invokes the existing sign-out callback and restores focus after the user menu closes', async () => {
    const user = userEvent.setup()
    const onSignOut = vi.fn()

    render(<UserMenu displayName="Test User" onSignOut={onSignOut} />)

    const trigger = screen.getByRole('button', { name: 'Open user menu for Test User' })
    await user.click(trigger)
    await user.click(screen.getByRole('menuitem', { name: /Sign out/i }))

    expect(onSignOut).toHaveBeenCalledTimes(1)
    expect(trigger).toHaveFocus()
  })

  it('keeps global search explicitly non-submitting when no search contract exists', async () => {
    const user = userEvent.setup()
    render(<GlobalSearch />)

    const search = screen.getByRole('button', { name: 'Global search unavailable' })
    await user.click(search)

    expect(search).toBeDisabled()
    expect(window.location.pathname).toBe('/')
  })
})

describe('study and site selectors', () => {
  it('preserves selector query behavior and updates the existing Zustand actions', async () => {
    const user = userEvent.setup()
    const get = vi.spyOn(api, 'get')
      .mockResolvedValueOnce({ data: { items: [{ id: 'study-1', study_code: 'EDC-001', title: 'Example Study' }], page: 1, page_size: 100, total: 1 } } as never)
      .mockResolvedValueOnce({ data: { items: [{ id: 'site-1', site_number: '001', name: 'Example Site' }], page: 1, page_size: 100, total: 1 } } as never)

    renderWithQuery(
      <>
        <StudySelector />
        <SiteSelector />
      </>,
    )

    const study = await screen.findByRole('combobox', { name: 'Select study' })
    await screen.findByRole('option', { name: /EDC-001 — Example Study/ })
    const site = screen.getByRole('combobox', { name: 'Select site' })
    expect(site).toBeDisabled()
    expect(get).toHaveBeenCalledWith('/studies', { params: { page: 1, page_size: 100 } })

    await user.selectOptions(study, 'study-1')
    expect(useStudyContext.getState()).toMatchObject({ selectedStudyId: 'study-1', selectedSiteId: null })
    expect(site).not.toBeDisabled()
    await waitFor(() => expect(get).toHaveBeenCalledWith('/studies/study-1/sites', { params: { page: 1, page_size: 100 } }))

    await user.selectOptions(site, 'site-1')
    expect(useStudyContext.getState()).toMatchObject({ selectedStudyId: 'study-1', selectedSiteId: 'site-1' })
  })
})
