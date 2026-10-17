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
    {
      id: '44444444-4444-4444-8444-444444444444',
      entity_type: 'site',
      code: 'GENERAL-HOSPITAL',
      name: 'General Hospital',
      attributes: { country: 'US', state: 'New York', city: 'New York' },
      active: true,
      created_at: '2026-10-12T12:00:00Z',
      updated_at: '2026-10-12T12:00:00Z',
    },
  ],
  page: 1,
  page_size: 20,
  total: 4,
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

const workspaceStudies = {
  items: [{ id: 'study-1', study_code: 'STUDY-001', title: 'Portfolio Study', status: 'active' }],
  page: 1,
  page_size: 100,
  total: 1,
}

function renderPage(props: Parameters<typeof EntityManagementPage>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><EntityManagementPage {...props} /></QueryClientProvider>)
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
    if (path === '/studies') return Promise.resolve({ data: workspaceStudies }) as never
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
  it('separates the portfolio Site and Entity directories', async () => {
    const sites = renderPage({ view: 'site-directory' })
    expect(await screen.findByRole('heading', { name: 'Site directory' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Site' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Staff' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create entity' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Site' })).toBeInTheDocument()
    expect(await screen.findByText('General Hospital')).toBeInTheDocument()
    sites.unmount()

    renderPage({ view: 'entity-directory' })
    expect(await screen.findByRole('heading', { name: 'Entity directory' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Site' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Staff' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Participating Organization' })).toBeInTheDocument()
  })

  it('filters dedicated portfolio entity pages to their requested type', async () => {
    renderPage({ view: 'entity-directory', entityType: 'staff' })
    expect(await screen.findByRole('heading', { name: 'Staff' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Staff' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Depot' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Participating Organization' })).not.toBeInTheDocument()
  })

  it('creates and edits Sites from the portfolio Site Directory', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} } as never)
    renderPage({ view: 'site-directory' })

    fireEvent.click(await screen.findByRole('button', { name: 'Create Site' }))
    let drawer = screen.getByRole('dialog', { name: 'Create Site' })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Name *' }), { target: { value: 'New Research Site' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'State *' }), { target: { value: 'New York' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'City *' }), { target: { value: 'Albany' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Create Site' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/sites', {
      name: 'New Research Site',
      state: 'New York',
      city: 'Albany',
    }))

    fireEvent.click(await screen.findByRole('button', { name: 'Edit Site' }))
    drawer = screen.getByRole('dialog', { name: 'Edit Site' })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Name *' }), { target: { value: 'General Hospital Research Center' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Save Site' }))

    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/entities/44444444-4444-4444-8444-444444444444', expect.objectContaining({
      name: 'General Hospital Research Center',
      attributes: expect.objectContaining({ state: 'New York', city: 'New York' }),
    })))
  })

  it('provides a dedicated tab and required form fields for each entity type', async () => {
    renderPage()

    expect(await screen.findByRole('tab', { name: 'Site' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Depot' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Staff' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Participating Organization' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Investigational Product' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Name *' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add Site' }))
    let drawer = screen.getByRole('dialog', { name: 'Add Site' })
    expect(within(drawer).queryByRole('tab')).not.toBeInTheDocument()
    await within(drawer).findByRole('option', { name: /General Hospital/ })
    expect(within(drawer).getByRole('combobox', { name: 'Available Site *' })).toHaveTextContent('General Hospital')
    expect(within(drawer).getByRole('textbox', { name: 'Study Site ID *' })).toBeRequired()
    expect(within(drawer).queryByRole('textbox', { name: 'Name *' })).not.toBeInTheDocument()

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

  it('adds an available Site with a Study-specific Site ID', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Add Site' }))
    const drawer = screen.getByRole('dialog', { name: 'Add Site' })

    const siteSelect = await within(drawer).findByRole('combobox', { name: 'Available Site *' })
    await within(drawer).findByRole('option', { name: /General Hospital/ })
    fireEvent.change(siteSelect, { target: { value: '44444444-4444-4444-8444-444444444444' } })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Study Site ID *' }), { target: { value: 'SITE-101' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Add Site' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/sites', {
      entity_id: '44444444-4444-4444-8444-444444444444',
      site_number: 'SITE-101',
    }))
  })
})
