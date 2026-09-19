import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { CTMSWorkspacePage, type CTMSView } from '@/features/ctms/WorkspacePage'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
}))

const manifest = {
  module: 'CTMS' as const,
  enabled: true,
  phase: 1 as const,
  capabilities: [
    'canonical_study_references',
    'canonical_site_references',
    'operational_studies',
    'operational_sites',
    'enrollment_planning',
    'operational_milestones',
    'ctms_roles',
    'scoped_authorization',
    'shared_audit',
    'operational_dashboards',
  ],
}

const page = { items: [], page: 1, page_size: 25, total: 0 }

function setViewer() {
  useAuthStore.setState({
    user: {
      id: 'phase1-user',
      email: 'phase1@example.test',
      first_name: 'Phase',
      last_name: 'Viewer',
      roles: [{ role_name: 'CTMS_Viewer' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ],
    },
    isAuthenticated: true,
  })
}

function renderWorkspace(responses: (path: string) => unknown, view: CTMSView = 'overview') {
  vi.spyOn(api, 'get').mockImplementation((url) =>
    Promise.resolve({ data: responses(String(url)) }) as never,
  )
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CTMSWorkspacePage view={view} studyId={view === 'health' ? undefined : 'study-1'} />
    </QueryClientProvider>,
  )
}

describe('CTMS Phase 1 qualification workspace', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('presents the Phase 1 operational dashboard without changing EDC navigation semantics', async () => {
    setViewer()
    renderWorkspace((path) => {
      if (path === '/ctms/capabilities') return manifest
      if (path.endsWith('/dashboard')) {
        return {
          operational: {
            study_id: 'study-1',
            enrollment: { targets: { Enrollment: { target: 25, actual: 1, variance: 24 } } },
            readiness: { status: 'Ready' },
          },
          projected_clinical: [],
        }
      }
      return page
    })

    expect(await screen.findByText('Study operations')).toBeInTheDocument()
    expect(screen.getByText('CTMS operational workspace')).toBeInTheDocument()
    expect(screen.getByText('Canonical EDC identifiers remain read-only; CTMS owns operational records.')).toBeInTheDocument()
    expect(await screen.findByText(/\"target\":25/)).toBeInTheDocument()
  })

  it('keeps the EDC fallback visible when the Phase 1 capability is disabled', async () => {
    setViewer()
    renderWorkspace(() => ({ module: 'CTMS', enabled: false, phase: 0, capabilities: [] }))

    expect(await screen.findByText(/CTMS is disabled or unavailable/)).toBeInTheDocument()
    expect(screen.getByText(/EDC clinical navigation and indicators remain available/)).toBeInTheDocument()
  })
})

function setOnline(value: boolean) {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value })
  window.dispatchEvent(new Event(value ? 'online' : 'offline'))
}

const phase3HealthManifest = {
  ...manifest,
  phase: 3 as const,
  capabilities: ['qualification_evidence'],
}

describe('CTMS workspace shared presentation states', () => {
  beforeEach(() => {
    setOnline(true)
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('renders the shared empty state without inventing operational records', async () => {
    setViewer()
    renderWorkspace((path) => {
      if (path === '/ctms/capabilities') return manifest
      if (path.endsWith('/dashboard')) return { operational: {}, projected_clinical: [] }
      return page
    })

    expect(await screen.findByText('Approved quality signals has no records configured yet.')).toBeInTheDocument()
  })

  it('renders unavailable capability state through the shared degraded pattern', async () => {
    setViewer()
    renderWorkspace((path) => {
      if (path === '/ctms/capabilities') throw new Error('capability service unavailable')
      return page
    })

    expect(await screen.findByText('CTMS is unavailable')).toBeInTheDocument()
    expect(screen.getByText('The CTMS capability manifest could not be loaded. Retry later or continue working in EDC.')).toBeInTheDocument()
  })

  it('preserves direct-route access denial before rendering operational content', async () => {
    setViewer()
    useAuthStore.setState({
      user: { id: 'denied-user', email: 'denied@example.test', first_name: 'Denied', last_name: 'User', roles: [], permissions: [] },
      isAuthenticated: true,
    })
    renderWorkspace(() => manifest)

    expect(await screen.findByRole('heading', { name: 'Access Denied' })).toBeInTheDocument()
    expect(screen.queryByText('CTMS operational workspace')).not.toBeInTheDocument()
  })

  it('renders the offline degraded state without changing the CTMS query response', async () => {
    setViewer()
    setOnline(false)
    renderWorkspace((path) => {
      if (path === '/ctms/capabilities') return manifest
      if (path.endsWith('/dashboard')) return { operational: { enrollment: { target_count: 1 } }, projected_clinical: [] }
      return page
    })

    expect(await screen.findByText('You are offline')).toBeInTheDocument()
    expect(screen.queryByText(/target_count/)).not.toBeInTheDocument()
  })

  it('renders worker-unavailable health through the shared degraded pattern', async () => {
    setViewer()
    renderWorkspace((path) => {
      if (path === '/ctms/capabilities') return phase3HealthManifest
      if (path === '/ctms/health') return { worker_status: 'degraded', worker_available: false }
      return page
    }, 'health')

    expect(await screen.findByText('Coordination worker unavailable')).toBeInTheDocument()
    expect(screen.getByText(/EDC clinical workflows remain available/)).toBeInTheDocument()
  })
})
