import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PortfolioManagementPage, PortfolioOperationsPage } from '@/features/ctms'
import { CTMS_CAPABILITY_CODES } from '@/features/ctms/capabilities'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode; params?: unknown }) => {
    const { params, ...anchorProps } = props
    void params
    return <a href={to} {...anchorProps}>{children}</a>
  },
  useNavigate: () => vi.fn(),
}))

const manifest = {
  module: 'CTMS',
  enabled: true,
  phase: 3,
  capabilities: Object.values(CTMS_CAPABILITY_CODES),
  platform_capabilities: { health_observability: true },
}

function renderPage(view: Parameters<typeof PortfolioOperationsPage>[0]['view']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><PortfolioOperationsPage view={view} /></QueryClientProvider>)
}

function renderManagementPage(view: Parameters<typeof PortfolioManagementPage>[0]['view']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><PortfolioManagementPage view={view} /></QueryClientProvider>)
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: 'portfolio-user',
      email: 'portfolio@example.test',
      first_name: 'Portfolio',
      last_name: 'Manager',
      roles: [{ role_name: 'CTMS_Operations_User' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT],
    },
    isAuthenticated: true,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CTMS portfolio operations', () => {
  it('renders monitoring rows from one server-side portfolio request', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation((url) => {
      const path = String(url)
      if (path === '/ctms/capabilities') return Promise.resolve({ data: manifest }) as never
      if (path === '/ctms/portfolio/monitoring/summary') return Promise.resolve({ data: { total: 1, upcoming: 0, overdue: 1, in_progress: 0, completed: 0, unassigned: 1, open_findings: 2 } }) as never
      return Promise.resolve({ data: { items: [{ id: 'visit-1', study_id: 'study-1', study_code: 'ONC-001', study_title: 'Oncology Study', site_id: 'site-1', site_number: '001', site_name: 'Research Center', activity_type: 'Routine', modality: 'On-site', planned_date: '2026-10-01T12:00:00Z', assigned_cra_id: null, assigned_cra_name: null, status: 'Scheduled', is_overdue: true, overdue_days: 12, open_findings: 2, report_status: 'Draft' }], page: 1, page_size: 25, total: 1 } }) as never
    })

    renderPage('monitoring-visits')

    expect(await screen.findByRole('heading', { name: 'All Monitoring Visits' })).toBeInTheDocument()
    expect(await screen.findAllByText('ONC-001')).not.toHaveLength(0)
    expect(screen.getAllByText(/12d overdue/).length).toBeGreaterThan(0)
    expect(get.mock.calls.some(([url]) => String(url).startsWith('/ctms/portfolio/monitoring/activities?'))).toBe(true)
    expect(get.mock.calls.some(([url]) => String(url).includes('/ctms/studies/'))).toBe(false)
  })

  it('keeps portfolio financial totals separated by currency', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      const path = String(url)
      if (path === '/ctms/capabilities') return Promise.resolve({ data: manifest }) as never
      return Promise.resolve({ data: { currencies: [
        { currency: 'EUR', approved_budget: 500, contracted: 0, calculated_payables: 0, approved_payables: 0, invoiced: 0, paid: 0, outstanding: 0, overdue: 0, budget_variance: 500 },
        { currency: 'USD', approved_budget: 2000, contracted: 1000, calculated_payables: 50, approved_payables: 200, invoiced: 125, paid: 50, outstanding: 150, overdue: 75, budget_variance: 1000 },
      ] } }) as never
    })

    renderPage('financial-dashboard')

    expect(await screen.findByRole('heading', { name: 'Portfolio Financial Dashboard' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'EUR' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'USD' })).toBeInTheDocument()
    expect(screen.getByText(/Unlike currencies are never combined/)).toBeInTheDocument()
  })

  it('loads My Work from one scoped portfolio endpoint without study fan-out', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [{ source_type: 'operational_task', source_id: 'task-1', study_id: 'study-1', study_code: 'ONC-001', study_title: 'Oncology Study', title: 'Confirm activation package', status: 'Open', due_at: '2026-10-15T12:00:00Z', is_overdue: false, destination_path: '/studies/study-1/ctms/tasks', permitted_actions: ['update'] }], page: 1, page_size: 100, total: 1 } } as never)

    renderManagementPage('work')

    expect(await screen.findByRole('heading', { name: 'My Work' })).toBeInTheDocument()
    expect(await screen.findByText('Confirm activation package')).toBeInTheDocument()
    expect(get.mock.calls.some(([url]) => String(url).startsWith('/ctms/portfolio/work?'))).toBe(true)
    expect(get.mock.calls.some(([url]) => String(url).includes('/ctms/studies/'))).toBe(false)
  })

  it('shows capacity and visit workload as separate measures', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [{ user_id: 'cra-1', user_name: 'Casey Monitor', week_start: '2026-10-12', timezone: 'America/New_York', capacity_hours: '40.00', exception_hours: '8.00', available_hours: '32.00', allocated_hours: '36.00', utilization_percent: '112.50', upcoming_visits: 3, overdue_visits: 1, is_over_capacity: true }], page: 1, page_size: 100, total: 1 } } as never)

    renderManagementPage('capacity')

    expect(await screen.findByText('Casey Monitor')).toBeInTheDocument()
    expect(screen.getByText(/36.00h allocated \/ 32.00h available/)).toBeInTheDocument()
    expect(screen.getByText(/112.50%/)).toBeInTheDocument()
    expect(screen.getByText(/3 upcoming visits · 1 overdue visits/)).toBeInTheDocument()
  })
})
