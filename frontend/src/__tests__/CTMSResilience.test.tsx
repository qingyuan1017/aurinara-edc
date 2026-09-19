import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { AppShell } from '@/components/layout/AppShell'
import { SubjectCasebookPage } from '@/features/subjects/SubjectCasebookPage'
import { StudyDashboardPage } from '@/features/dashboards/StudyDashboardPage'
import { PERMISSIONS } from '@/lib/permissions'
import { ThemeProvider } from '@/lib/theme'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
  Outlet: () => <div data-testid="outlet" />,
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
  useLocation: () => ({ pathname: '/', search: {}, hash: '' }),
}))

const edcNavigation = ['Dashboard', 'Studies', 'Sites', 'Subjects', 'Forms', 'Queries', 'Data Cleaning', 'SDV Worklist', 'Clinical Review', 'Edit Checks', 'AI Assistant', 'Notifications', 'Exports', 'Admin', 'Audit Trail']

function renderShell(capability: { enabled: boolean; phase: 0 | 1 | 2 | 3 }) {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'user@example.com',
      first_name: 'EDC',
      last_name: 'User',
      roles: [],
      permissions: [PERMISSIONS.STUDY_READ, PERMISSIONS.CTMS_OPERATIONAL_DATA_READ],
    },
    isAuthenticated: true,
  })
  vi.spyOn(api, 'get').mockImplementation((url) => {
    const path = String(url)
    if (path === '/ctms/capabilities') return Promise.resolve({ data: { module: 'CTMS', ...capability, capabilities: [] } }) as never
    if (path === '/studies') return Promise.resolve({ data: { items: [], page: 1, page_size: 100, total: 0 } }) as never
    return Promise.resolve({ data: {} }) as never
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <AppShell />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('EDC frontend resilience around optional CTMS', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it.each([
    { name: 'disabled', enabled: false, phase: 0 as const, showsCTMS: false },
    { name: 'empty', enabled: true, phase: 1 as const, showsCTMS: true },
    { name: 'worker-unavailable', enabled: true, phase: 3 as const, showsCTMS: true },
  ])('preserves EDC navigation when CTMS is $name', async ({ enabled, phase, showsCTMS }) => {
    renderShell({ enabled, phase })
    const primaryNavigation = within(screen.getByRole('navigation', { name: 'Primary navigation' }))
    for (const label of edcNavigation) expect(await primaryNavigation.findByText(label)).toBeInTheDocument()
    if (showsCTMS) expect(await primaryNavigation.findByText('CTMS')).toBeInTheDocument()
    else expect(primaryNavigation.queryByText('CTMS')).not.toBeInTheDocument()
  })

  it('keeps the clinical casebook and dashboard indicators available without CTMS records', async () => {
    const casebookClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.spyOn(api, 'get').mockImplementation((url) => {
      const path = String(url)
      if (path === '/subjects/subject-1/casebook') return Promise.resolve({ data: {
        subject_id: 'subject-1', subject_number: 'SUBJ-001', status: 'Enrolled',
        visits: [{ visit_instance_id: 'visit-1', visit_definition_id: 'baseline', name: 'Baseline', status: 'Scheduled', forms: [{ form_instance_id: 'form-1', form_definition_id: 'vitals', name: 'Vitals', status: 'Submitted' }] }],
      } }) as never
      if (path.endsWith('/dashboard')) return Promise.resolve({ data: { subject_counts_by_status: { Enrolled: 1 }, total_form_instances: 1, submitted_form_instances: 1, open_query_count: 0 } }) as never
      if (path.endsWith('/query-metrics')) return Promise.resolve({ data: { open_count: 0, answered_count: 0, closed_count: 0, cancelled_count: 0, overdue_count: 0, average_days_open: 0 } }) as never
      if (path.endsWith('/sdv-progress')) return Promise.resolve({ data: { verified: 1, not_verified: 0 } }) as never
      return Promise.resolve({ data: { reviewed: 1, not_reviewed: 0 } }) as never
    })

    render(<QueryClientProvider client={casebookClient}><SubjectCasebookPage subjectId="subject-1" /></QueryClientProvider>)
    expect(await screen.findByText('Subject SUBJ-001')).toBeInTheDocument()
    expect(screen.getByText('Baseline')).toBeInTheDocument()
    expect(screen.getByText('1/1 forms complete')).toBeInTheDocument()

    const dashboardClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={dashboardClient}><StudyDashboardPage studyId="study-1" /></QueryClientProvider>)
    expect(await screen.findByText('Study dashboard')).toBeInTheDocument()
    expect(await screen.findByText('Open queries')).toBeInTheDocument()
    expect(await screen.findByText('Source data verification')).toBeInTheDocument()
  })
})
