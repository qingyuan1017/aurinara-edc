import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/components/layout/AppShell'
import { CTMSWorkspacePage } from '@/features/ctms/WorkspacePage'
import { CTMS_CAPABILITY_CODES } from '@/features/ctms/capabilities'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useStudyContext } from '@/lib/study-context'
import { PERMISSIONS } from '@/lib/permissions'
import { ThemeProvider } from '@/lib/theme'
import { EDC_NAV_ITEMS } from '@/lib/navigation-model'

let currentPathname = '/ctms'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode; search?: unknown; activeOptions?: unknown; activeProps?: unknown; [key: string]: unknown }) => {
    const { search, activeOptions, activeProps, ...anchorProps } = props
    void search
    void activeOptions
    void activeProps
    return <a href={to} {...anchorProps}>{children}</a>
  },
  Outlet: () => <div data-testid="outlet" />,
  useLocation: () => ({ pathname: currentPathname }),
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
}))

const edcNavigation = EDC_NAV_ITEMS.map((item) => item.label)

const allCTMSCapabilities = Object.values(CTMS_CAPABILITY_CODES)
const enabledManifest = {
  module: 'CTMS' as const,
  enabled: true,
  phase: 3 as const,
  capabilities: allCTMSCapabilities,
  platform_capabilities: { health_observability: true },
}

const permissions = {
  viewer: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ],
  operations: [
    PERMISSIONS.CTMS_OPERATIONAL_DATA_READ,
    PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT,
    PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT,
    PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT,
    PERMISSIONS.CTMS_ENROLLMENT_MANAGEMENT,
    PERMISSIONS.DATA_EXPORT,
  ],
  admin: [
    PERMISSIONS.CTMS_OPERATIONAL_DATA_READ,
    PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT,
    PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT,
    PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT,
    PERMISSIONS.CTMS_ENROLLMENT_MANAGEMENT,
    PERMISSIONS.DATA_EXPORT,
    PERMISSIONS.CTMS_COORDINATION_REPLAY,
    PERMISSIONS.CTMS_CONFLICT_MANAGEMENT,
  ],
  mixed: [
    PERMISSIONS.CTMS_OPERATIONAL_DATA_READ,
    PERMISSIONS.CTMS_CONFLICT_MANAGEMENT,
  ],
} as const

function setUser(grantedPermissions: readonly string[], roleName = 'CTMS_Viewer') {
  useAuthStore.setState({
    user: {
      id: 'ctms-user-1',
      email: 'ctms@example.test',
      first_name: 'CTMS',
      last_name: 'Tester',
      roles: [{ role_name: roleName }],
      permissions: [...grantedPermissions],
    },
    isAuthenticated: true,
  })
}

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function mockCapabilities(response: unknown = enabledManifest) {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (String(url) === '/ctms/capabilities') return Promise.resolve({ data: response }) as never
    return Promise.resolve({ data: { items: [], page: 1, page_size: 20, total: 0 } }) as never
  })
}

function renderShell(grantedPermissions: readonly string[], response: unknown = enabledManifest, roleName = 'CTMS_Viewer', pathname = '/ctms') {
  currentPathname = pathname
  setUser(grantedPermissions, roleName)
  useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: 'site-1' })
  mockCapabilities(response)
  return render(
    <QueryClientProvider client={queryClient()}>
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

function renderWorkspace(
  grantedPermissions: readonly string[],
  responseFactory: (path: string) => unknown,
  props: { view: 'overview' | 'activation'; studyId?: string; siteId?: string },
) {
  setUser(grantedPermissions)
  vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: responseFactory(String(url)) }) as never)
  return render(
    <QueryClientProvider client={queryClient()}>
      <CTMSWorkspacePage {...props} />
    </QueryClientProvider>,
  )
}

function expectBaselineEDCNavigation() {
  for (const label of edcNavigation) {
    expect(screen.getAllByText(label, { exact: true }).length).toBeGreaterThan(0)
  }
}

function expectCTMSLink(label: string, expected: boolean) {
  const links = screen.queryAllByRole('link', { name: label })
  const hasCTMSLink = links.some((link) => link.getAttribute('href')?.includes('/ctms'))
  expect(hasCTMSLink).toBe(expected)
}

function expandNavigationSections(container: HTMLElement) {
  for (const button of within(container).getAllByRole('button')) {
    if (button.getAttribute('aria-expanded') === 'false') fireEvent.click(button)
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  currentPathname = '/ctms'
  useAuthStore.setState({ user: null, isAuthenticated: false })
  useStudyContext.setState({ selectedStudyId: null, selectedSiteId: null })
})

describe('CTMS persona, workspace, and EDC-shell component coverage', () => {
  it.each([
    { persona: 'Admin', role: 'CTMS_Admin', granted: permissions.admin, required: ['Study Dashboard', 'Monitoring Visits', 'Study Financial Overview'] },
    { persona: 'Operations User', role: 'CTMS_Operations_User', granted: permissions.operations, required: ['Study Dashboard', 'Monitoring Plans', 'Study Tasks'] },
    { persona: 'Viewer', role: 'CTMS_Viewer', granted: permissions.viewer, required: ['Study Dashboard', 'Study Information', 'Monitoring Overview'] },
    { persona: 'mixed permissions', role: 'mixed', granted: permissions.mixed, required: ['Study Dashboard', 'Study Information'] },
  ])('resolves CTMS navigation for $persona', async ({ role, granted, required }) => {
    renderShell(granted, enabledManifest, role, '/studies/study-1/ctms')

    const navigation = await screen.findByLabelText('CTMS navigation')
    expandNavigationSections(navigation)
    for (const label of required) expectCTMSLink(label, true)
  })

  it('preserves every baseline EDC navigation item when CTMS is disabled or unavailable', async () => {
    const disabled = renderShell(permissions.viewer, { module: 'CTMS', enabled: false, phase: 0, capabilities: [] }, 'CTMS_Viewer', '/')
    expandNavigationSections(screen.getByRole('navigation', { name: 'Primary navigation' }))
    expectBaselineEDCNavigation()
    expect(screen.queryByLabelText('CTMS navigation')).not.toBeInTheDocument()
    disabled.unmount()

    currentPathname = '/'
    setUser(permissions.viewer)
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url) === '/ctms/capabilities') return Promise.reject(new Error('capability service unavailable')) as never
      return Promise.resolve({ data: { items: [], page: 1, page_size: 20, total: 0 } }) as never
    })
    render(
      <QueryClientProvider client={queryClient()}>
        <ThemeProvider>
          <AppShell />
        </ThemeProvider>
      </QueryClientProvider>,
    )
    expandNavigationSections(screen.getByRole('navigation', { name: 'Primary navigation' }))
    expectBaselineEDCNavigation()
    await vi.waitFor(() => expect(screen.queryByLabelText('CTMS navigation')).not.toBeInTheDocument())
  })

  it('renders direct denied routes without querying or exposing a CTMS workspace', async () => {
    setUser([])
    const get = vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url) === '/ctms/capabilities') return Promise.resolve({ data: enabledManifest }) as never
      return Promise.resolve({ data: {} }) as never
    })
    render(
      <QueryClientProvider client={queryClient()}>
        <CTMSWorkspacePage view="overview" studyId="study-1" />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Access Denied')).toBeInTheDocument()
    expect(screen.queryByText('CTMS operational workspace')).not.toBeInTheDocument()
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('renders canonical study and site identifiers with actionable empty states', async () => {
    renderWorkspace(
      permissions.viewer,
      (path) => path === '/ctms/capabilities' ? enabledManifest : {},
      { view: 'activation', studyId: 'study-123', siteId: 'site-456' },
    )

    expect(await screen.findByText('EDC Study ID')).toBeInTheDocument()
    expect(screen.getByText('study-123')).toBeInTheDocument()
    expect(screen.getByText('EDC Site ID')).toBeInTheDocument()
    expect(screen.getByText('site-456')).toBeInTheDocument()
    expect(screen.queryByText('Canonical scope')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('CTMS workspace sections')).not.toBeInTheDocument()
    expect(await screen.findAllByText(/has no records configured yet/)).not.toHaveLength(0)
    expect(screen.getAllByRole('link', { name: 'Review site activation' }).length).toBeGreaterThan(0)
  })

  it('renders filters inside the active list panel instead of at page level', async () => {
    renderWorkspace(
      permissions.viewer,
      (path) => path === '/ctms/capabilities' ? enabledManifest : { operational: {}, projected_clinical: [], generated_at: '2026-10-13T12:00:00Z' },
      { view: 'overview', studyId: 'study-1' },
    )

    const listPanel = await screen.findByRole('region', { name: 'Overview list and filters' })
    expect(within(listPanel).getByRole('toolbar', { name: 'CTMS filters' })).toBeInTheDocument()
    expect(screen.queryByText('Canonical scope')).not.toBeInTheDocument()
  })

  it.each([
    { name: 'disabled', response: { module: 'CTMS', enabled: false, phase: 0, capabilities: [] }, heading: 'CTMS is disabled or unavailable' },
    { name: 'unavailable', unavailable: true, heading: 'CTMS is unavailable' },
  ])('renders a safe direct-route state when the manifest is $name', async ({ response, unavailable, heading }) => {
    setUser(permissions.viewer)
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url) === '/ctms/capabilities') {
        if (unavailable) return Promise.reject(new Error('manifest unavailable')) as never
        return Promise.resolve({ data: response }) as never
      }
      return Promise.resolve({ data: {} }) as never
    })
    render(
      <QueryClientProvider client={queryClient()}>
        <CTMSWorkspacePage view="overview" studyId="study-1" />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
    expect(screen.getByText(/EDC clinical navigation and indicators remain available|continue working in EDC/)).toBeInTheDocument()
  })
})
