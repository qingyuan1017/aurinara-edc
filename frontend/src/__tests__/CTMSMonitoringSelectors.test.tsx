import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MonitoringActivityForm, MonitoringPlanForm } from '@/features/ctms/forms'
import { api } from '@/lib/api'

const projectOptions = {
  users: [{ id: 'user-1', label: 'Casey Chen', secondary_label: 'casey@example.test' }],
  roles: [],
  sites: [{ id: 'site-1', label: 'North Hospital', secondary_label: 'US-001', country_code: 'US' }],
}
const monitoringPlans = {
  items: [{ id: 'plan-1', study_id: 'study-1', name: 'Study monitoring plan', status: 'Approved', current_version_id: 'version-1', created_at: '', updated_at: '' }],
  page: 1,
  page_size: 100,
  total: 1,
}

function renderForm(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'get').mockImplementation((url) => {
    const path = String(url)
    if (path.includes('/project-management/options')) return Promise.resolve({ data: projectOptions }) as never
    if (path.includes('/monitoring-plans')) return Promise.resolve({ data: monitoringPlans }) as never
    return Promise.resolve({ data: { items: [], page: 1, page_size: 100, total: 0 } }) as never
  })
})

describe('monitoring identity selectors', () => {
  it('selects a site by readable label when creating a monitoring plan', async () => {
    renderForm(<MonitoringPlanForm studyId="study-1" />)

    const site = await screen.findByRole('combobox', { name: /Site scope/ })
    expect(await screen.findByRole('option', { name: 'North Hospital · US-001' })).toHaveValue('site-1')
    fireEvent.change(site, { target: { value: 'site-1' } })
    expect(site).toHaveValue('site-1')
  })

  it('submits selected plan, site, and CRA identifiers without manual ID entry', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'visit-1' } } as never)
    renderForm(<MonitoringActivityForm studyId="study-1" />)

    const plan = await screen.findByRole('combobox', { name: /Monitoring plan/ })
    expect(await screen.findByRole('option', { name: 'Study monitoring plan · Study plan · Approved' })).toHaveValue('plan-1')
    const site = screen.getByRole('combobox', { name: /^Site/ })
    const cra = screen.getByRole('combobox', { name: /Assigned CRA/ })
    expect(screen.getByRole('option', { name: 'Casey Chen · casey@example.test' })).toHaveValue('user-1')

    fireEvent.change(plan, { target: { value: 'plan-1' } })
    fireEvent.change(site, { target: { value: 'site-1' } })
    fireEvent.change(cra, { target: { value: 'user-1' } })
    fireEvent.change(screen.getByLabelText(/Planned date and time/), { target: { value: '2026-11-01T09:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Schedule visit' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/monitoring-activities', expect.objectContaining({
      plan_id: 'plan-1', site_id: 'site-1', assigned_cra_id: 'user-1',
    })))
    expect(screen.queryByRole('textbox', { name: /Monitoring plan ID|Site ID|Assigned CRA ID|EDC Visit Instance ID/ })).not.toBeInTheDocument()
  })
})
