import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { CTMSWorkspacePage } from '@/features/ctms/WorkspacePage'

let currentSearch: Record<string, unknown> = {}

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  useSearch: () => currentSearch,
}))

const manifest = {
  module: 'CTMS' as const,
  enabled: true,
  phase: 3 as const,
  capabilities: ['operational_dashboards', 'reports'],
}

const dashboard = {
  study_id: 'study-1',
  operational: {
    enrollment: { target_count: 2, actual: 8, variance: 2 },
    monitoring: { total: 5, upcoming: 2 },
    tasks: { total: 7, overdue: 1 },
    readiness: { required_total: 4, required_met: 3, completion_percentage: 75 },
    milestones: { total: 6 },
  },
  projected_clinical: [{
    projection_id: 'projection-1',
    signal_type: 'Approved quality signal',
    value: 2,
    source_module: 'EDC',
    source_timestamp: '2026-03-01T09:55:00Z',
    projected_at: '2026-03-01T10:00:00Z',
    freshness: 'current',
    read_only: true,
  }],
  generated_at: '2026-03-01T10:00:00Z',
}

function setViewer() {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'viewer@example.test',
      first_name: 'CTMS',
      last_name: 'Viewer',
      roles: [{ role_name: 'CTMS_Viewer' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ],
    },
    isAuthenticated: true,
  })
}

function renderWorkspace(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)
}

describe('CTMS scoped dashboards and reports', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    currentSearch = {}
    setViewer()
  })

  it('renders typed study dashboard metrics and approved quality signals without client totals', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path) => {
      if (String(path) === '/ctms/capabilities') return { data: manifest } as never
      return { data: dashboard } as never
    })

    renderWorkspace(<CTMSWorkspacePage view="overview" studyId="study-1" />)

    expect(await screen.findByRole('heading', { name: 'Enrollment' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Monitoring' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Readiness' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Milestones' })).toBeInTheDocument()
    expect(screen.getByText('Approved quality signal')).toBeInTheDocument()
    expect(screen.getByText('Server-generated CTMS operational metrics for the study. Totals are authoritative and are not reconstructed from rendered records.')).toBeInTheDocument()
    expect(screen.getByText(/Generated at:/)).toBeInTheDocument()
  })

  it('renders a site-scoped dashboard and server-owned report totals and pagination', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (path) => {
      const requestPath = String(path)
      if (requestPath === '/ctms/capabilities') return { data: manifest } as never
      if (requestPath.includes('/sites/site-1/dashboard')) return { data: { ...dashboard, site_id: 'site-1' } } as never
      return { data: {
        study_id: 'study-1',
        report_type: 'tasks',
        items: [{ id: 'task-1', title: 'Confirm monitoring date', status: 'Open', operational_only: true }],
        totals: { count: 51, overdue: 3 },
        page: 2,
        page_size: 25,
        total: 51,
        generated_at: '2026-03-01T10:00:00Z',
      } } as never
    })

    renderWorkspace(<CTMSWorkspacePage view="site-dashboard" siteId="site-1" />)
    expect(await screen.findByText('Server-generated CTMS operational metrics for the site. Totals are authoritative and are not reconstructed from rendered records.')).toBeInTheDocument()
    expect(screen.getByText('EDC Site ID')).toBeInTheDocument()

    const { unmount } = renderWorkspace(<CTMSWorkspacePage view="reports" studyId="study-1" reportType="tasks" />)
    expect((await screen.findAllByText('Confirm monitoring date')).length).toBeGreaterThan(0)
    expect(screen.getByText('51')).toBeInTheDocument()
    expect(screen.getByText('Page 2 of 3 (51 total)')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/ctms/studies/study-1/reports/tasks?report_type=tasks')
    unmount()
  })

  it('keeps the last valid report with its server timestamp after a filtered request fails', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (path) => {
      const requestPath = String(path)
      if (requestPath === '/ctms/capabilities') return { data: manifest } as never
      if (requestPath.includes('status=Open')) throw new Error('filtered report unavailable')
      return { data: {
        study_id: 'study-1',
        report_type: 'tasks',
        items: [{ id: 'task-1', title: 'Last valid task', status: 'Open', operational_only: true }],
        totals: { count: 1 },
        generated_at: '2026-03-01T10:00:00Z',
      } } as never
    })

    const { rerender } = renderWorkspace(<CTMSWorkspacePage view="reports" studyId="study-1" reportType="tasks" />)
    await waitFor(() => expect(screen.getAllByText('Last valid task').length).toBeGreaterThan(0))

    currentSearch = { status: 'Open' }
    rerender(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CTMSWorkspacePage view="reports" studyId="study-1" reportType="tasks" /></QueryClientProvider>)

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/Showing the last valid result from/))
    expect(screen.getAllByText('Last valid task').length).toBeGreaterThan(0)
    expect(get).toHaveBeenCalledWith('/ctms/studies/study-1/reports/tasks?status=Open&report_type=tasks')
  })
})
