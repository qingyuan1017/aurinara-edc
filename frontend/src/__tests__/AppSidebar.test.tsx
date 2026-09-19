import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/components/layout/AppShell'
import { AppSidebar } from '@/components/layout/AppSidebar'
import {
  EDC_NAVIGATION_SECTIONS,
  resolveNavigationModel,
} from '@/lib/navigation-model'
import {
  CTMS_PHASE_CAPABILITIES,
  normalizeCTMSCapabilities,
  unavailableCTMSCapabilities,
} from '@/features/ctms'
import { PERMISSIONS } from '@/lib/permissions'
import { useAuthStore } from '@/lib/auth'
import { ThemeProvider } from '@/lib/theme'

const mockUseCTMSCapabilityState = vi.hoisted(() => vi.fn())
const mockUsePermission = vi.hoisted(() => vi.fn())
const mockNavigate = vi.hoisted(() => vi.fn())
const mockLogout = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('@/features/ctms', async () => {
  const actual = await vi.importActual<typeof import('@/features/ctms')>('@/features/ctms')
  return { ...actual, useCTMSCapabilityState: mockUseCTMSCapabilityState }
})

vi.mock('@/lib/permissions', async () => {
  const actual = await vi.importActual<typeof import('@/lib/permissions')>('@/lib/permissions')
  return { ...actual, usePermission: mockUsePermission }
})

vi.mock('@/components/layout/StudySelector', () => ({
  StudySelector: () => <select aria-label="Select study" />,
}))

vi.mock('@/components/layout/SiteSelector', () => ({
  SiteSelector: () => <select aria-label="Select site" disabled />,
}))

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    to,
    children,
    className,
    activeProps,
    search: _search,
    activeOptions: _activeOptions,
    ...props
  }: {
    to: string
    children: React.ReactNode
    className?: string
    activeProps?: { className?: string }
    search?: unknown
    activeOptions?: unknown
  }) => {
    void _search
    void _activeOptions
    return (
      <a href={to} className={className ?? activeProps?.className} {...props}>
        {children}
      </a>
    )
  },
  Outlet: () => <div data-testid="outlet">Existing route outlet</div>,
  useLocation: () => ({ pathname: '/', search: {}, hash: '' }),
  useNavigate: () => mockNavigate,
}))

const allPermissions = Object.values(PERMISSIONS)
const readyState = normalizeCTMSCapabilities({
  module: 'CTMS',
  enabled: true,
  phase: 3,
  capabilities: [...CTMS_PHASE_CAPABILITIES[3]],
  platform_capabilities: { health_observability: true },
})
const disabledState = normalizeCTMSCapabilities({
  module: 'CTMS',
  enabled: false,
  phase: 0,
  capabilities: [],
})
const unavailableState = unavailableCTMSCapabilities(new Error('capability service unavailable'))

function renderResolvedSidebar(
  state: typeof readyState,
  permissions: readonly string[],
  scope = { studyId: 'study-1', siteId: 'site-1' },
) {
  const model = resolveNavigationModel(state, permissions, scope)
  return render(
    <AppSidebar
      collapsed={false}
      onCollapsedChange={vi.fn()}
      edcSections={model.edcSections}
      ctmsSections={model.ctmsSections}
      showCTMS={state.status === 'ready' && permissions.includes(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)}
    />,
  )
}

describe('AppSidebar', () => {
  it('renders every grouped EDC destination and allowed CTMS navigation', () => {
    renderResolvedSidebar(readyState, allPermissions)

    for (const item of EDC_NAVIGATION_SECTIONS.flatMap((section) => section.items)) {
      expect(screen.getAllByRole('link', { name: item.label }).length).toBeGreaterThan(0)
    }
    expect(screen.getByRole('navigation', { name: 'Primary navigation' })).toBeInTheDocument()
    expect(screen.getByText('CTMS')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Health' })).toBeInTheDocument()
  })

  it('does not expose CTMS navigation when the permission affordance denies it', () => {
    renderResolvedSidebar(readyState, [])

    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.queryByText('CTMS')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Overview' })).not.toBeInTheDocument()
  })

  it.each([
    ['disabled', disabledState],
    ['unavailable', unavailableState],
  ] as const)('keeps EDC navigation while CTMS is %s', (_name, state) => {
    renderResolvedSidebar(state, [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])

    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Audit Trail' })).toBeInTheDocument()
    expect(screen.queryByText('CTMS')).not.toBeInTheDocument()
  })

  it('uses compact collapse semantics and labels collapsed links with tooltips', async () => {
    const onCollapsedChange = vi.fn()
    const model = resolveNavigationModel(readyState, allPermissions, { studyId: 'study-1', siteId: 'site-1' })
    render(
      <AppSidebar
        collapsed
        onCollapsedChange={onCollapsedChange}
        edcSections={model.edcSections}
        ctmsSections={model.ctmsSections}
        showCTMS
      />,
    )

    const dashboard = screen.getByRole('link', { name: 'Dashboard' })
    expect(dashboard.querySelector('svg')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Dashboard')).toHaveClass('sr-only')
  })
})

describe('AppShell sidebar integration', () => {
  beforeEach(() => {
    mockUseCTMSCapabilityState.mockReturnValue(disabledState)
    mockUsePermission.mockReturnValue(false)
    useAuthStore.setState({
      user: {
        id: 'user-1',
        email: 'user@example.com',
        first_name: 'EDC',
        last_name: 'User',
        roles: [],
        permissions: [],
      },
      isAuthenticated: true,
      logout: mockLogout,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('keeps one authenticated shell and renders the existing route outlet', () => {
    render(
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>,
    )

    expect(screen.getAllByTestId('app-sidebar')).toHaveLength(1)
    expect(screen.getByTestId('outlet')).toHaveTextContent('Existing route outlet')
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-controls', 'mobile-navigation')
    expect(screen.getByRole('combobox', { name: 'Select study' })).toBeInTheDocument()
    expect(screen.getByTestId('app-shell')).toHaveClass('min-w-0', 'max-w-full', 'overflow-x-hidden')
    expect(screen.getByTestId('app-shell-content')).toHaveClass('max-w-full', 'overflow-x-auto')
  })

  it('opens the mobile Sheet without navigating and restores focus to its invoking control', async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>,
    )

    const menuTrigger = screen.getByRole('button', { name: 'Open navigation' })
    await user.click(menuTrigger)

    expect(mockNavigate).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toHaveAttribute('id', 'mobile-navigation')
    expect(screen.getByRole('navigation', { name: 'Mobile primary navigation' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close sheet' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(menuTrigger).toHaveFocus()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('keeps desktop collapse controls separate from the mobile Sheet presentation', () => {
    render(
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('app-sidebar')).toHaveClass('hidden', 'md:flex')
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('preserves the existing sign-out flow and navigates to login', async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>,
    )

    await user.click(screen.getByRole('button', { name: 'Open user menu for EDC User' }))
    await user.click(screen.getByRole('menuitem', { name: /Sign out/i }))

    expect(mockLogout).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/login' })
  })
})
