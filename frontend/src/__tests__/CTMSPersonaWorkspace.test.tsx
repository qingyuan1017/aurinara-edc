import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/components/layout/AppShell'
import { CTMSWorkspacePage } from '@/features/ctms/WorkspacePage'
import { CTMS_CAPABILITY_CODES } from '@/features/ctms/capabilities'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useStudyContext } from '@/lib/study-context'
import { PERMISSIONS } from '@/lib/permissions'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode; [key: string]: unknown }) => (
    <a href={to} {...props}>{children}</a>
  ),
  Outlet: () => <div data-testid="outlet" />,
  useNavigate: () => vi.fn(),
}))

const edcNavigation = [
  'Dashboard',
  'Studies',
  'Sites',
  'Subjects',
  'Forms',
  'Queries',
  'Data Cleaning',
  'SDV Worklist',
  'Clinical Review',
  'Edit Checks',
  'AI Assistant',
  'Notifications',
  'Exports',
  'Admin',
  'Audit Trail',
]

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

function renderShell(grantedPermissions: readonly string[], response: unknown = enabledManifest, roleName = 'CTMS_Viewer') {
  setUser(grantedPermissions, roleName)
  useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: 'site-1' })
  mockCapabilities(response)
  return render(
    <QueryClientProvider client={queryClient()}>
      <AppShell />
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
    expect(screen.getByText(label, { exact: true })).toBeInTheDocument()
  }
}

function expectCTMSLink(label: string, expected: boolean) {
  const links = screen.queryAllByRole('link', { name: label, exact: true })
  const hasCTMSLink = links.some((link) => link.getAttribute('href')?.includes('/ctms'))
  expect(hasCTMSLink).toBe(expected)
}

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, isAuthenticated: false })
  useStudyContext.setState({ selectedStudyId: null, selectedSiteId: null })
})

describe('CTMS persona, workspace, and EDC-shell component coverage', () => {
  it.each([
    { persona: 'Admin', role: 'CTMS_Admin', granted: permissions.admin, required: ['Failed events', 'Conflicts', 'Exports'] },
    { persona: 'Operations User', role: 'CTMS_Operations_User', granted: permissions.operations, required: ['Exports', 'Monitoring activities'], absent: ['Failed events', 'Conflicts'] },
    { persona: 'Viewer', role: 'CTMS_Viewer', granted: permissions.viewer, required: ['Overview', 'Projections'], absent: ['Failed events', 'Conflicts'] },
    { persona: 'mixed permissions', role: 'mixed', granted: permissions.mixed, required: ['Conflicts'], absent: ['Failed events', 'Exports'] },
  ])('resolves CTMS navigation for $persona without changing EDC navigation', async ({ role, granted, required, absent }) => {
    renderShell(granted, enabledManifest, role)

    expectBaselineEDCNavigation()
    expect(await screen.findByLabelText('CTMS navigation')).toBeInTheDocument()
    for (const label of required) expectCTMSLink(label, true)
    for (const label of absent ?? []) expectCTMSLink(label, false)
  })

  it('preserves every baseline EDC navigation item when CTMS is disabled or unavailable', async () => {
    const disabled = renderShell(permissions.viewer, { module: 'CTMS', enabled: false, phase: 0, capabilities: [] })
    expectBaselineEDCNavigation()
    expect(screen.queryByLabelText('CTMS navigation')).not.toBeInTheDocument()
    disabled.unmount()

    setUser(permissions.viewer)
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url) === '/ctms/capabilities') return Promise.reject(new Error('capability service unavailable')) as never
      return Promise.resolve({ data: {} }) as never
    })
    render(
      <QueryClientProvider client={queryClient()}>
        <AppShell />
      </QueryClientProvider>,
    )
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
    expect(await screen.findAllByText(/has no records configured yet/)).not.toHaveLength(0)
    expect(screen.getAllByRole('link', { name: 'Review site activation' }).length).toBeGreaterThan(0)
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
