import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
import {
  PV_DISABLED_MANIFEST,
  normalizePVCapabilities,
  unavailablePVCapabilities,
  type PVCapabilityState,
} from '@/features/pv'
import { PERMISSIONS } from '@/lib/permissions'
import { useAuthStore } from '@/lib/auth'
import { ThemeProvider } from '@/lib/theme'
import { resolveAppModule, type AppModule } from '@/lib/module-context'

const mockUseCTMSCapabilityState = vi.hoisted(() => vi.fn())
const mockUsePVCapabilityState = vi.hoisted(() => vi.fn())
const mockUsePermission = vi.hoisted(() => vi.fn())
const mockNavigate = vi.hoisted(() => vi.fn())
const mockLogout = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('@/features/ctms', async () => {
  const actual = await vi.importActual<typeof import('@/features/ctms')>('@/features/ctms')
  return { ...actual, useCTMSCapabilityState: mockUseCTMSCapabilityState }
})

vi.mock('@/features/pv', async () => {
  const actual = await vi.importActual<typeof import('@/features/pv')>('@/features/pv')
  return { ...actual, usePVCapabilityState: mockUsePVCapabilityState }
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

const pvReadyState = normalizePVCapabilities({
  module: 'PV',
  enabled: true,
  phase: 1,
  capabilities: ['safety_case_intake', 'safety_dashboards', 'safety_exports', 'shared_audit'],
})
const pvDisabledState = normalizePVCapabilities(PV_DISABLED_MANIFEST)
const pvUnavailableState = unavailablePVCapabilities(new Error('safety capability service unavailable'))

function renderResolvedSidebar(
  state: typeof readyState,
  permissions: readonly string[],
  scope = { studyId: 'study-1', siteId: 'site-1' },
  activeModule?: AppModule,
  pvState: PVCapabilityState = pvDisabledState,
) {
  const model = resolveNavigationModel(state, pvState, permissions, scope)
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AppSidebar
      collapsed={false}
      onCollapsedChange={vi.fn()}
      edcSections={model.edcSections}
      designerSections={model.designerSections}
      ctmsSections={model.ctmsSections}
      pvSections={model.pvSections}
      showCTMS={state.status === 'ready' && permissions.includes(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)}
      showDesigner={model.designerSections.length > 0}
      showPV={pvState.status === 'ready' && permissions.includes(PERMISSIONS.PV_SAFETY_CASE_READ)}
      activeModule={activeModule}
    /></QueryClientProvider>,
  )
}

function renderAppShell() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>
    </QueryClientProvider>,
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
    expect(screen.getByRole('link', { name: 'Study Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Study Health' })).toBeInTheDocument()
  })

  it('does not expose CTMS navigation when the permission affordance denies it', () => {
    renderResolvedSidebar(readyState, [])

    expect(screen.getByRole('link', { name: 'EDC Dashboard' })).toBeInTheDocument()
    expect(screen.queryByText('CTMS')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Overview' })).toBeInTheDocument()
  })

  it('shows only the selected module hierarchy', () => {
    renderResolvedSidebar(readyState, allPermissions, undefined, 'edc')

    expect(screen.getByRole('combobox', { name: 'Select module' })).toHaveValue('edc')
    expect(screen.getByRole('link', { name: 'EDC Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.queryByLabelText('CTMS navigation')).not.toBeInTheDocument()
  })

  it('shows only CTMS navigation when CTMS is selected', () => {
    renderResolvedSidebar(readyState, allPermissions, undefined, 'ctms')

    expect(screen.getByRole('combobox', { name: 'Select module' })).toHaveValue('ctms')
    expect(screen.getByRole('link', { name: 'Study Dashboard' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'EDC Dashboard' })).not.toBeInTheDocument()
    expect(screen.getByTestId('workspace-switcher')).toBeInTheDocument()
  })

  it('groups CTMS destinations into collapsible workspace modules', async () => {
    const user = userEvent.setup()
    renderResolvedSidebar(readyState, allPermissions, undefined, 'ctms')

    const monitoring = screen.getByRole('button', { name: 'Monitoring' })
    expect(screen.getByRole('link', { name: 'Monitoring Visits' })).toHaveAttribute('href', '/studies/study-1/ctms/monitoring/visits')
    await user.click(monitoring)
    expect(screen.queryByRole('link', { name: 'Monitoring Visits' })).not.toBeInTheDocument()
    await user.click(monitoring)
    expect(screen.getByRole('link', { name: 'Monitoring Visits' })).toBeInTheDocument()
  })

  it('shows Designer as a separate module without EDC navigation', () => {
    renderResolvedSidebar(readyState, allPermissions, undefined, 'designer')

    expect(screen.getByRole('combobox', { name: 'Select module' })).toHaveValue('designer')
    expect(screen.getByLabelText('Designer navigation')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Form Builder' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Version History' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Studies' })).not.toBeInTheDocument()
  })

  it('reports module changes from the selector', async () => {
    const user = userEvent.setup()
    const onModuleChange = vi.fn()
    const model = resolveNavigationModel(readyState, pvDisabledState, allPermissions, { studyId: 'study-1', siteId: 'site-1' })

    render(
      <AppSidebar
        collapsed={false}
        onCollapsedChange={vi.fn()}
        edcSections={model.edcSections}
        designerSections={model.designerSections}
        ctmsSections={model.ctmsSections}
        pvSections={model.pvSections}
        showCTMS
        showDesigner
        showPV={false}
        activeModule="edc"
        onModuleChange={onModuleChange}
      />,
    )

    await user.selectOptions(screen.getByRole('combobox', { name: 'Select module' }), 'ctms')

    expect(onModuleChange).toHaveBeenCalledWith('ctms')
  })

  it.each([
    ['disabled', disabledState],
    ['unavailable', unavailableState],
  ] as const)('keeps EDC navigation while CTMS is %s', (_name, state) => {
    renderResolvedSidebar(state, [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])

    expect(screen.getByRole('link', { name: 'EDC Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Database Lock' })).toBeInTheDocument()
    expect(screen.queryByText('CTMS')).not.toBeInTheDocument()
  })

  it('renders PV navigation and a selectable PV option when PV is ready and the user may read safety cases', () => {
    renderResolvedSidebar(readyState, allPermissions, undefined, 'pv', pvReadyState)

    expect(screen.getByRole('combobox', { name: 'Select module' })).toHaveValue('pv')
    expect(screen.getByLabelText('PV navigation')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Cases' })).toBeInTheDocument()

    const pvOption = screen.getByRole('option', { name: 'PV' }) as HTMLOptionElement
    expect(pvOption.disabled).toBe(false)
  })

  it.each([
    ['disabled', pvDisabledState],
    ['unavailable', pvUnavailableState],
  ] as const)('keeps the PV affordance hidden and disabled while PV is %s', (_name, pvState) => {
    renderResolvedSidebar(readyState, allPermissions, undefined, 'edc', pvState)

    expect(screen.getByRole('link', { name: 'EDC Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Select module' })).toHaveValue('edc')
    expect(screen.queryByLabelText('PV navigation')).not.toBeInTheDocument()

    const pvOption = screen.getByRole('option', { name: /^PV/ }) as HTMLOptionElement
    expect(pvOption.disabled).toBe(true)
  })

  it('uses compact collapse semantics and labels collapsed links with tooltips', async () => {
    const onCollapsedChange = vi.fn()
    const model = resolveNavigationModel(readyState, pvDisabledState, allPermissions, { studyId: 'study-1', siteId: 'site-1' })
    render(
      <AppSidebar
        collapsed
        onCollapsedChange={onCollapsedChange}
        edcSections={model.edcSections}
        designerSections={model.designerSections}
        ctmsSections={model.ctmsSections}
        pvSections={model.pvSections}
        showCTMS
        showDesigner
        showPV={false}
      />,
    )

    const dashboard = screen.getByRole('link', { name: 'Overview' })
    expect(dashboard.querySelector('svg')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
    expect(dashboard.querySelector('span')).toHaveClass('sr-only')
  })
})

describe('module route resolution', () => {
  it.each([
    ['/designer/forms', 'designer'],
    ['/studies/study-1/designer/visits', 'designer'],
    ['/forms', 'designer'],
    ['/studies/study-1/versions', 'designer'],
    ['/subjects/subject-1/forms/form-1', 'edc'],
    ['/studies/study-1/ctms', 'ctms'],
    ['/studies/study-1/pv/cases', 'pv'],
  ] as const)('maps %s to the %s module', (pathname, module) => {
    expect(resolveAppModule(pathname)).toBe(module)
  })
})

describe('AppShell sidebar integration', () => {
  beforeEach(() => {
    mockUseCTMSCapabilityState.mockReturnValue(disabledState)
    mockUsePVCapabilityState.mockReturnValue(pvDisabledState)
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
    renderAppShell()

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
    renderAppShell()

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
    renderAppShell()

    expect(screen.getByTestId('app-sidebar')).toHaveClass('hidden', 'md:flex')
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('preserves the existing sign-out flow and navigates to login', async () => {
    const user = userEvent.setup()
    renderAppShell()

    await user.click(screen.getByRole('button', { name: 'Open user menu for EDC User' }))
    await user.click(screen.getByRole('menuitem', { name: /Sign out/i }))

    expect(mockLogout).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/login' })
  })
})
