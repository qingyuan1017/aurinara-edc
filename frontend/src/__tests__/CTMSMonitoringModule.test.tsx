import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MonitoringModulePage } from '@/features/ctms'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

const page = (items: unknown[]) => ({ items, page: 1, page_size: 100, total: items.length })

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MonitoringModulePage studyId="study-1" view="overview" /></QueryClientProvider>)
}

beforeEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({
    isAuthenticated: true,
    user: {
      id: 'cra-1',
      email: 'cra@example.test',
      first_name: 'Casey',
      last_name: 'CRA',
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT],
      roles: [{ role_name: 'CRA' }],
    },
  })
})

describe('CTMS monitoring module', () => {
  it('renders the six monitoring submodules and derives oversight data from study records', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      const path = String(url)
      if (path.includes('/monitoring-plans')) return Promise.resolve({ data: page([]) }) as never
      if (path.includes('/monitoring-activities')) return Promise.resolve({ data: page([
        { id: 'visit-1', study_id: 'study-1', site_id: 'US-001', activity_type: 'IMV', modality: 'On-site', planned_date: '2020-01-01T12:00:00Z', assigned_cra_id: 'cra-1', status: 'Overdue', created_at: '2020-01-01T00:00:00Z', updated_at: '2020-01-01T00:00:00Z' },
      ]) }) as never
      if (path.includes('/monitoring-findings')) return Promise.resolve({ data: page([
        { id: 'finding-1', finding_code: 'FIND-0001', study_id: 'study-1', site_id: 'US-001', category: 'Informed Consent', severity: 'Major', description: 'Reconsent documentation missing', status: 'Open', capa_required: true, actions: [], created_at: '2020-01-01T00:00:00Z', updated_at: '2020-01-01T00:00:00Z' },
      ]) }) as never
      return Promise.resolve({ data: page([]) }) as never
    })

    renderPage()

    expect(await screen.findByText('CRA view')).toBeInTheDocument()
    expect(await screen.findByText('US-001')).toBeInTheDocument()
    expect(screen.getByText('1 critical or major')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/studies/study-1/ctms/monitoring')
    expect(screen.getByRole('link', { name: 'Monitoring Plans' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Monitoring Visits' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Findings & Actions' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Risk-Based Monitoring' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Monitoring Reports' })).toBeInTheDocument()
  })
})
