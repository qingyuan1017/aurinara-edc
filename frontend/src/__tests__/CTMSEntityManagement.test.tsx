import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EntityManagementPage } from '@/features/ctms'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { useStudyContext } from '@/lib/study-context'

const entities = {
  items: [
    {
      id: '11111111-1111-4111-8111-111111111111',
      entity_type: 'staff',
      code: 'JANE-EXAMPLE-TEST',
      name: 'Jane Coordinator',
      attributes: { first_name: 'Jane', last_name: 'Coordinator', email: 'jane@example.test' },
      active: true,
      created_at: '2026-10-12T12:00:00Z',
      updated_at: '2026-10-12T12:00:00Z',
    },
    {
      id: '22222222-2222-4222-8222-222222222222',
      entity_type: 'participating_organization',
      code: 'SPONSOR-ONE',
      name: 'Sponsor One',
      attributes: { address: '1 Sponsor Plaza', phone: '+1 555 0100', organization_type: 'Sponsor' },
      active: true,
      created_at: '2026-10-12T12:00:00Z',
      updated_at: '2026-10-12T12:00:00Z',
    },
    {
      id: '33333333-3333-4333-8333-333333333333',
      entity_type: 'depot',
      code: 'UNASSIGNED-DEPOT',
      name: 'Unassigned Depot',
      attributes: { country: 'US', state: 'Ohio', city: 'Columbus' },
      active: true,
      created_at: '2026-10-12T12:00:00Z',
      updated_at: '2026-10-12T12:00:00Z',
    },
  ],
  page: 1,
  page_size: 20,
  total: 3,
}

const referenceValues = {
  items: [
    { id: 'ref-country-us', category: 'country', code: 'US', label: 'United States', sort_order: 10, active: true, created_at: '', updated_at: '' },
    { id: 'ref-org-sponsor', category: 'participating_organization_type', code: 'SPONSOR', label: 'Sponsor', sort_order: 10, active: true, created_at: '', updated_at: '' },
  ],
  page: 1,
  page_size: 100,
  total: 2,
}

const assignments = {
  items: entities.items.slice(0, 2).map((entity, index) => ({
    id: `assignment-${index + 1}`,
    study_id: 'study-1',
    entity_id: entity.id,
    entity,
    attributes: {},
    created_at: '2026-10-12T12:00:00Z',
  })),
  page: 1,
  page_size: 20,
  total: 2,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><EntityManagementPage /></QueryClientProvider>)
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: 'ctms-user-1',
      email: 'ctms@example.test',
      first_name: 'CTMS',
      last_name: 'Manager',
      roles: [{ role_name: 'CTMS_Operations_User' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT],
    },
    isAuthenticated: true,
  })
  useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: null })
  vi.spyOn(api, 'get').mockImplementation((url) => {
    const path = String(url)
    if (path.startsWith('/ctms/reference-values')) return Promise.resolve({ data: referenceValues }) as never
    if (path.startsWith('/ctms/studies/study-1/entities')) return Promise.resolve({ data: assignments }) as never
    return Promise.resolve({ data: entities }) as never
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, isAuthenticated: false })
  useStudyContext.setState({ selectedStudyId: null, selectedSiteId: null })
})

describe('CTMS entity management', () => {
  it('provides a dedicated tab and required form fields for each entity type', async () => {
    renderPage()

    expect(await screen.findByRole('tab', { name: 'Site' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Depot' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Staff' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Participating Organization' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Investigational Product' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Name *' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
    let drawer = screen.getByRole('dialog', { name: 'Create Site' })
    expect(within(drawer).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(drawer).getByRole('textbox', { name: 'Name *' })).toBeRequired()
    expect(within(drawer).queryByRole('textbox', { name: 'Canonical Site ID *' })).not.toBeInTheDocument()
    expect(within(drawer).queryByRole('combobox', { name: 'Canonical Site *' })).not.toBeInTheDocument()
    expect(within(drawer).getByRole('textbox', { name: 'State *' })).toBeRequired()
    expect(within(drawer).getByRole('textbox', { name: 'City *' })).toBeRequired()
    await within(drawer).findByRole('option', { name: 'United States' })
    expect(within(drawer).getByRole('combobox', { name: 'Country' })).toHaveTextContent('United States')

    fireEvent.click(within(drawer).getByRole('button', { name: 'Close sheet' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Staff' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
    drawer = screen.getByRole('dialog', { name: 'Create Staff' })
    expect(within(drawer).getByRole('textbox', { name: 'First Name *' })).toBeRequired()
    expect(within(drawer).getByRole('textbox', { name: 'Last Name *' })).toBeRequired()
    expect(within(drawer).getByRole('textbox', { name: 'Email *' })).toBeRequired()

    fireEvent.click(within(drawer).getByRole('button', { name: 'Close sheet' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Participating Organization' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
    drawer = screen.getByRole('dialog', { name: 'Create Participating Organization' })
    expect(within(drawer).getByRole('combobox', { name: 'Type *' })).toBeRequired()
    expect(within(drawer).getByRole('combobox', { name: 'Primary Contact' })).toHaveTextContent('Jane Coordinator')

    fireEvent.click(within(drawer).getByRole('button', { name: 'Close sheet' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Investigational Product' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
    drawer = screen.getByRole('dialog', { name: 'Create Investigational Product' })
    expect(within(drawer).getByRole('textbox', { name: 'Compound Name *' })).toBeRequired()
    expect(within(drawer).getByRole('combobox', { name: 'Pharmaceutical Company *' })).toHaveTextContent('Sponsor One')
  })

  it('shows only entities assigned to the selected study in the main area', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('tab', { name: 'Staff' }))
    expect(await screen.findByText('Jane Coordinator')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Depot' }))
    expect(screen.getByText('No depot entities have been added to this study.')).toBeInTheDocument()
    expect(screen.queryByText('Unassigned Depot')).not.toBeInTheDocument()
    expect(vi.mocked(api.get).mock.calls.some(([url]) => String(url).includes('available-entities'))).toBe(false)
  })

  it('submits depot details through the managed entity attributes contract', async () => {
    const post = vi.spyOn(api, 'post').mockImplementation((url) => Promise.resolve({ data: String(url) === '/ctms/entities' ? { id: 'new-depot-id' } : {} }) as never)
    renderPage()
    fireEvent.click(await screen.findByRole('tab', { name: 'Depot' }))
    fireEvent.click(screen.getByRole('button', { name: 'Create entity' }))
    const drawer = screen.getByRole('dialog', { name: 'Create Depot' })

    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Name *' }), { target: { value: 'East Coast Depot' } })
    fireEvent.change(within(drawer).getByRole('combobox', { name: 'Country *' }), { target: { value: 'US' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'State *' }), { target: { value: 'New Jersey' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'City *' }), { target: { value: 'Newark' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Email *' }), { target: { value: 'depot@example.test' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Phone *' }), { target: { value: '+1 555 0100' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Zip Code *' }), { target: { value: '07101' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Address *' }), { target: { value: '100 Supply Way' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Create Depot' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/entities', {
      entity_type: 'depot',
      code: 'EAST-COAST-DEPOT',
      name: 'East Coast Depot',
      attributes: {
        country: 'US',
        state: 'New Jersey',
        city: 'Newark',
        email: 'depot@example.test',
        phone: '+1 555 0100',
        zip_code: '07101',
        address: '100 Supply Way',
      },
    }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/entities', {
      entity_id: 'new-depot-id',
      attributes: {},
    }))
  })

  it('creates a Site in CTMS without asking the user to enter its generated ID', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Create entity' }))
    const drawer = screen.getByRole('dialog', { name: 'Create Site' })

    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Name *' }), { target: { value: 'General Hospital' } })
    fireEvent.change(within(drawer).getByRole('combobox', { name: 'Country' }), { target: { value: 'US' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'State *' }), { target: { value: 'New York' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'City *' }), { target: { value: 'New York' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Address' }), { target: { value: '1 Main Street' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Create Site' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/sites', {
      name: 'General Hospital',
      country: 'US',
      state: 'New York',
      city: 'New York',
      address: '1 Main Street',
    }))
  })
})
