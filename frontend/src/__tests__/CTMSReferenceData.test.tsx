import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OperationalStudyForm, ReferenceDataPage } from '@/features/ctms'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

const references = {
  items: [
    { id: 'country-us', category: 'country', code: 'US', label: 'United States', sort_order: 10, active: true, created_at: '', updated_at: '' },
    { id: 'org-sponsor', category: 'participating_organization_type', code: 'SPONSOR', label: 'Sponsor', sort_order: 10, active: true, created_at: '', updated_at: '' },
    { id: 'area-oncology', category: 'therapeutic_area', code: 'ONCOLOGY', label: 'Oncology', sort_order: 10, active: true, created_at: '', updated_at: '' },
    { id: 'indication-breast-cancer', category: 'indication', code: 'BREAST_CANCER', label: 'Breast Cancer', sort_order: 10, active: true, created_at: '', updated_at: '' },
    { id: 'project-status-draft', category: 'project_status', code: 'DRAFT', label: 'Draft', sort_order: 10, active: true, created_at: '', updated_at: '' },
  ],
  page: 1,
  page_size: 100,
  total: 5,
}

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: 'ctms-user-1', email: 'ctms@example.com', first_name: 'CTMS', last_name: 'Manager',
      roles: [{ role_name: 'CTMS_Operations_User' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT],
    },
    isAuthenticated: true,
  })
  vi.spyOn(api, 'get').mockResolvedValue({ data: references } as never)
})

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, isAuthenticated: false })
})

describe('CTMS reference data', () => {
  it('manages dropdown and project workflow categories from Configuration', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} } as never)
    renderWithClient(<ReferenceDataPage />)

    expect(await screen.findByRole('tab', { name: 'Country' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Participating Organization Type' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Therapeutic Area' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Project Status' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Indication' }))
    expect(screen.getByText('Breast Cancer')).toBeInTheDocument()

    expect(screen.queryByRole('textbox', { name: 'Display value *' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add value' }))
    const drawer = screen.getByRole('dialog', { name: 'Add Indication' })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Display value *' }), { target: { value: 'Melanoma' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Add value' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/reference-values', {
      category: 'indication', code: 'MELANOMA', label: 'Melanoma', sort_order: 0,
    }))

    fireEvent.click(screen.getByRole('tab', { name: 'Project Status' }))
    expect(screen.getByText('Draft')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const editDrawer = screen.getByRole('dialog', { name: 'Edit Project Status' })
    fireEvent.change(within(editDrawer).getByRole('textbox', { name: 'Display value *' }), { target: { value: 'Ready' } })
    fireEvent.click(within(editDrawer).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/reference-values/project-status-draft', { label: 'Ready', sort_order: 10 }))
  })

  it('supplies therapeutic area and indication values to operational study dropdowns', async () => {
    renderWithClient(<OperationalStudyForm studyId="study-1" />)

    await screen.findByRole('option', { name: 'Oncology' })
    expect(screen.getByRole('combobox', { name: 'Therapeutic area' })).toHaveTextContent('Oncology')
    expect(screen.getByRole('combobox', { name: 'Indication' })).toHaveTextContent('Breast Cancer')
  })
})
