import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FinancialManagementPage } from '@/features/ctms/FinancialManagementPage'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

function renderPage(initialTab: 'overview' | 'contracts' | 'budgets' | 'payments' | 'invoices' | 'reporting' = 'overview') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><FinancialManagementPage studyId="study-1" initialTab={initialTab} /></QueryClientProvider>)
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: 'finance-user-1', email: 'finance@example.test', first_name: 'Finance', last_name: 'Reviewer',
      roles: [{ role_name: 'CTMS_Operations_User' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT],
    },
    isAuthenticated: true,
  })
  vi.spyOn(api, 'get').mockImplementation(async (url) => {
    if (String(url).endsWith('/overview')) return { data: { study_id: 'study-1', currency: 'USD', approved_budget: '2400000', contracted: '425000', earned: '15600', holdback: '1560', approved: '14040', invoiced: '14040', paid: '8200', outstanding: '5840', overdue: '0' } } as never
    if (String(url).includes('/financials/configuration-options')) return { data: { visits: [], forms: [], payment_rules: [{ code: 'VISIT_SCREENING_VERIFIED', label: 'Verified screening visit', charge_item_count: 1, methods: ['visit_based'] }] } } as never
    return { data: { items: [], page: 1, page_size: 25, total: 0 } } as never
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, isAuthenticated: false })
})

describe('CTMS financial management', () => {
  it('shows one ledger-derived overview across the financial lifecycle', async () => {
    renderPage()
    expect((await screen.findAllByText('$2.4M')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('$8.2K').length).toBeGreaterThan(0)
    expect(screen.getByText('$5.8K')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Contracts' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Budgets' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Payments' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Invoices' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Reporting' })).toBeInTheDocument()
    expect(screen.getByText('Budget utilization')).toBeInTheDocument()
    expect(screen.getByText('Recent payment activity')).toBeInTheDocument()
  })

  it('submits a verified financial event with an idempotency key', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { event: { id: 'event-1' }, payable_items: [], replayed: false } } as never)
    renderPage('payments')
    expect(await screen.findByText('No calculated payments')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'New payment request' }))
    const drawer = screen.getByRole('dialog', { name: 'New payment request' })
    fireEvent.change(within(drawer).getByLabelText('Activity date *'), { target: { value: '2026-02-01' } })
    await within(drawer).findByRole('option', { name: /Verified screening visit/ })
    fireEvent.change(within(drawer).getByLabelText('Payment rule *'), { target: { value: 'VISIT_SCREENING_VERIFIED' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Create payment request' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/financials/events/calculate', expect.objectContaining({
      trigger_code: 'VISIT_SCREENING_VERIFIED',
      idempotency_key: expect.stringMatching(/^manual:/),
      verification_status: 'verified',
    })))
  })

  it('opens the six-tab contract management workspace with versioned payment terms', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => {
      const path = String(url)
      if (path.endsWith('/overview')) return { data: { study_id: 'study-1', currency: 'USD', approved_budget: '2400000', contracted: '425000', earned: '15600', holdback: '1560', approved: '14040', invoiced: '14040', paid: '8200', outstanding: '5840', overdue: '0' } } as never
      if (path.endsWith('/financials/contracts')) return { data: { items: [{ id: 'contract-1', study_id: 'study-1', site_id: 'site-14', contract_number: 'CTA-2026-014', title: 'Memorial CTA', contract_type: 'clinical_trial_agreement', direction: 'payable', party_name: 'Memorial Research Hospital', status: 'executed', currency: 'USD', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-15T00:00:00Z' }], page: 1, page_size: 25, total: 1 } } as never
      if (path.endsWith('/contracts/contract-1/versions')) return { data: [{ id: 'version-2', contract_id: 'contract-1', version_number: 2, amendment_reason: 'Updated visit rates', effective_from: '2026-01-15', status: 'executed', total_value: '425000', holdback_percent: '10', payment_window_days: 30, invoice_required: true, executed_at: '2026-01-15T00:00:00Z', created_at: '2026-01-10T00:00:00Z' }] } as never
      if (path.endsWith('/versions/version-2/terms')) return { data: [{ id: 'term-1', version_id: 'version-2', code: 'STARTUP', description: 'Startup Fee', payment_method: 'fixed', trigger_code: 'SITE_ACTIVATED', unit_rate: '15000', active: true }] } as never
      return { data: { items: [], page: 1, page_size: 25, total: 0 } } as never
    })

    renderPage('contracts')
    fireEvent.click(await screen.findByRole('button', { name: /Open contract/i }))
    expect(await screen.findByText('Contract · CTA-2026-014')).toBeInTheDocument()
    for (const name of ['Details', 'Documents', 'Budget', 'Payment Terms', 'Amendments', 'Audit Trail']) expect(screen.getByRole('tab', { name })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Payment Terms' }))
    expect(await screen.findByText('Startup Fee')).toBeInTheDocument()
    expect(screen.getByText('$15,000.00')).toBeInTheDocument()
  })

  it('creates a versioned budget baseline with decimal line inputs', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'budget-1', study_id: 'study-1', name: 'FY26 baseline', scope: 'study', currency: 'USD', status: 'draft', created_at: '2026-01-01T00:00:00Z', current_version: { id: 'budget-version-1', budget_id: 'budget-1', version_number: 1, status: 'draft', effective_from: '2026-01-01', total: '2400000', lines: [], created_at: '2026-01-01T00:00:00Z' } } } as never)
    renderPage('budgets')
    fireEvent.click(await screen.findByRole('button', { name: 'Add budget' }))
    const drawer = screen.getByRole('dialog', { name: 'Add budget baseline' })
    fireEvent.change(within(drawer).getByLabelText('Budget name *'), { target: { value: 'FY26 baseline' } })
    fireEvent.change(within(drawer).getByLabelText('Effective from *'), { target: { value: '2026-01-01' } })
    fireEvent.change(within(drawer).getByLabelText('Category 1 *'), { target: { value: 'Site costs' } })
    fireEvent.change(within(drawer).getByLabelText('Description 1 *'), { target: { value: 'Investigator grants' } })
    fireEvent.change(within(drawer).getByLabelText('Quantity 1 *'), { target: { value: '10' } })
    fireEvent.change(within(drawer).getByLabelText('Unit cost 1 *'), { target: { value: '1200' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Create budget' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/financials/budgets', expect.objectContaining({
      name: 'FY26 baseline',
      currency: 'USD',
      lines: [{ category: 'Site costs', description: 'Investigator grants', quantity: 10, unit_cost: 1200 }],
    })))
  })

  it('adds an EDC-linked CRF charge item to a draft contract rate card', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => {
      const path = String(url)
      if (path.endsWith('/overview')) return { data: { study_id: 'study-1', currency: 'USD', approved_budget: '100000', contracted: '50000', earned: '0', holdback: '0', approved: '0', invoiced: '0', paid: '0', outstanding: '0', overdue: '0' } } as never
      if (path.endsWith('/financials/contracts')) return { data: { items: [{ id: 'contract-1', study_id: 'study-1', contract_number: 'CTA-RATE-CARD', title: 'Configurable CTA', contract_type: 'clinical_trial_agreement', direction: 'payable', party_name: 'Research Site', status: 'draft', currency: 'USD', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }], page: 1, page_size: 25, total: 1 } } as never
      if (path.endsWith('/contracts/contract-1/versions')) return { data: [{ id: 'version-1', contract_id: 'contract-1', version_number: 1, effective_from: '2026-01-01', status: 'draft', total_value: '50000', holdback_percent: '0', payment_window_days: 30, invoice_required: true, created_at: '2026-01-01T00:00:00Z' }] } as never
      if (path.endsWith('/versions/version-1/terms')) return { data: [] } as never
      if (path.endsWith('/financials/configuration-options')) return { data: { visits: [], forms: [{ id: 'form-lab', code: 'LAB', label: 'Central Laboratory', version: '1.0' }], payment_rules: [] } } as never
      return { data: { items: [], page: 1, page_size: 25, total: 0 } } as never
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'term-crf' } } as never)

    renderPage('contracts')
    fireEvent.click(await screen.findByRole('button', { name: /Open contract/i }))
    fireEvent.click(screen.getByRole('tab', { name: 'Payment Terms' }))
    fireEvent.change(await screen.findByLabelText('Item code *'), { target: { value: 'LAB-CRF' } })
    fireEvent.change(screen.getByLabelText('Description *'), { target: { value: 'Completed lab CRF' } })
    fireEvent.change(screen.getByLabelText('Calculation method'), { target: { value: 'crf_based' } })
    fireEvent.change(screen.getByLabelText('Payment rule code *'), { target: { value: 'CRF_SUBMITTED' } })
    fireEvent.change(screen.getByLabelText('Unit rate *'), { target: { value: '25' } })
    fireEvent.change(screen.getByLabelText('EDC CRF definition *'), { target: { value: 'form-lab' } })
    fireEvent.change(screen.getByLabelText('Additional dimensions (key=value, comma separated)'), { target: { value: 'cohort=A, region=US' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add charge item' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/financials/versions/version-1/terms', expect.objectContaining({
      payment_method: 'crf_based',
      form_definition_id: 'form-lab',
      dimensions_json: { cohort: 'A', region: 'US' },
    })))
  })
})
