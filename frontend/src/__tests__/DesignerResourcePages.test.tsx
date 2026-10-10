import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { CodelistsPage } from '@/features/designer/CodelistsPage'
import { ArmsPage } from '@/features/designer/ArmsPage'
import { CrfAccessPage } from '@/features/designer/CrfAccessPage'
import { RawDataVariablesPage } from '@/features/designer/RawDataVariablesPage'
import { VisitsPage } from '@/features/designer/VisitsPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

function renderPage(ui: ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {ui}
    </QueryClientProvider>,
  )
}

function seedPermissions(permissions: string[]) {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'designer@example.com',
      first_name: 'Dee',
      last_name: 'Signer',
      roles: [],
      permissions,
    },
    isAuthenticated: true,
  })
}

const DRAFT_VERSIONS = [
  { id: 'ver-draft', study_id: 'study-1', version_number: '2', status: 'draft', created_at: '2024-01-02T00:00:00Z' },
  { id: 'ver-pub', study_id: 'study-1', version_number: '1', status: 'published', created_at: '2024-01-01T00:00:00Z' },
]

const VISIT_LIST = [
  { id: 'visit-1', study_version_id: 'ver-draft', name: 'Baseline', visit_number: 1, visit_type: 'visit', target_day: 0, window_before: null, window_after: null, display_order: 1, is_required: true, repeat_min: null, repeat_max: null, cycle_length: null, created_at: 'x' },
  { id: 'visit-2', study_version_id: 'ver-draft', name: 'Cycle 1', visit_number: 2, visit_type: 'cycle', target_day: null, window_before: null, window_after: null, display_order: 2, is_required: true, repeat_min: 1, repeat_max: 6, cycle_length: 21, created_at: 'x' },
]

describe('CodelistsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.codelist.read', 'designer.codelist.configure'])
  })

  it('lists codelists and creates a new one with items', async () => {
    const created = { id: 'cl-2', study_version_id: 'ver-draft', name: 'Severity', code: 'SEV', items: [] }
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/designer/studies/study-1/codelists') {
        return Promise.resolve({ data: [{ id: 'cl-1', study_version_id: 'ver-draft', name: 'Yes/No', code: 'YN' }] })
      }
      return Promise.resolve({ data: { id: 'cl-1', study_version_id: 'ver-draft', name: 'Yes/No', code: 'YN', items: [] } })
    })
    vi.mocked(api.post).mockResolvedValue({ data: created } as never)

    renderPage(<CodelistsPage studyId="study-1" />)

    expect(await screen.findByText('Yes/No')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'New codelist' }))
    fireEvent.change(screen.getByPlaceholderText('Severity grades'), { target: { value: 'Severity' } })
    fireEvent.change(screen.getByPlaceholderText('SEV_GRADE'), { target: { value: 'SEV' } })
    fireEvent.change(screen.getByLabelText('Item 1 code'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Item 1 label'), { target: { value: 'Mild' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create codelist' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/studies/study-1/codelists',
      expect.objectContaining({ name: 'Severity', code: 'SEV', items: [expect.objectContaining({ code: '1', label: 'Mild', display_order: 1 })] }),
    ))
  })

  it('denies access without the read permission', () => {
    seedPermissions([])
    renderPage(<CodelistsPage studyId="study-1" />)
    expect(screen.queryByText('Codelists')).not.toBeInTheDocument()
  })
})

describe('ArmsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.arm.read', 'designer.arm.configure'])
  })

  function mockArmsAndVisits() {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/arms') return Promise.resolve({ data: [] })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: VISIT_LIST })
      return Promise.resolve({ data: [] })
    })
  }

  it('lists arms from GET and creates one with member visit ids', async () => {
    mockArmsAndVisits()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'arm-1', study_version_id: 'ver-draft', name: 'Active', display_order: 1, description: null, visit_definition_ids: ['visit-1'], created_at: 'x' } } as never)

    renderPage(<ArmsPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('Active'), { target: { value: 'Active' } })
    fireEvent.click(await screen.findByLabelText('Include visit Baseline'))
    fireEvent.click(screen.getByRole('button', { name: 'Add arm' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/arms',
      { name: 'Active', display_order: 1, description: null, visit_definition_ids: ['visit-1'] },
    ))
  })

  it('reads arms via GET /designer/versions/{versionId}/arms', async () => {
    mockArmsAndVisits()
    renderPage(<ArmsPage studyId="study-1" />)
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/designer/versions/ver-draft/arms'))
  })

  it('denies access without the read permission', async () => {
    seedPermissions([])
    vi.mocked(api.get).mockResolvedValue({ data: DRAFT_VERSIONS } as never)
    renderPage(<ArmsPage studyId="study-1" />)
    await waitFor(() => expect(screen.queryByText('Treatment arms')).not.toBeInTheDocument())
  })
})

describe('CrfAccessPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.crf_access.configure'])
    vi.mocked(api.get).mockResolvedValue({ data: DRAFT_VERSIONS } as never)
  })

  it('sends blinded and unblind_role once blinded is checked', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'crf-1', design_version_id: 'ver-draft', role: 'Monitor', can_read: true, can_write: false, form_definition_id: null, field_definition_id: null, blinded: true, unblind_role: 'Medical Monitor', created_at: 'x' } } as never)

    renderPage(<CrfAccessPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('Investigator'), { target: { value: 'Monitor' } })
    // unblind_role is disabled until blinded is checked.
    expect(screen.getByPlaceholderText('Medical Monitor')).toBeDisabled()
    fireEvent.click(screen.getByLabelText('Blinded'))
    fireEvent.change(screen.getByPlaceholderText('Medical Monitor'), { target: { value: 'Medical Monitor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add rule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/crf-access',
      expect.objectContaining({ role: 'Monitor', blinded: true, unblind_role: 'Medical Monitor' }),
    ))
  })

  it('omits unblind_role when blinded is not checked', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'crf-2', design_version_id: 'ver-draft', role: 'Investigator', can_read: true, can_write: false, form_definition_id: null, field_definition_id: null, blinded: false, unblind_role: null, created_at: 'x' } } as never)

    renderPage(<CrfAccessPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('Investigator'), { target: { value: 'Investigator' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add rule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/crf-access',
      expect.objectContaining({ role: 'Investigator', blinded: false, unblind_role: null }),
    ))
  })
})

describe('RawDataVariablesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.raw_data_variable.configure'])
    vi.mocked(api.get).mockResolvedValue({ data: DRAFT_VERSIONS } as never)
  })

  it('sends optional label and suffix on create', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'rdv-1', design_version_id: 'ver-draft', name: 'SUBJID', data_type: 'string', attributes: {}, label: 'Subject identifier', suffix: '_RAW', created_at: 'x' } } as never)

    renderPage(<RawDataVariablesPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('SUBJID'), { target: { value: 'SUBJID' } })
    fireEvent.change(screen.getByPlaceholderText('string'), { target: { value: 'string' } })
    fireEvent.change(screen.getByPlaceholderText('Subject identifier'), { target: { value: 'Subject identifier' } })
    fireEvent.change(screen.getByPlaceholderText('_RAW'), { target: { value: '_RAW' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add variable' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/raw-data-variables',
      expect.objectContaining({ name: 'SUBJID', data_type: 'string', label: 'Subject identifier', suffix: '_RAW' }),
    ))
  })
})

describe('VisitsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.visit.read', 'designer.visit.configure'])
  })

  it('creates a visit with visit_type default "visit"', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      return Promise.resolve({ data: [VISIT_LIST[0]] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: { ...VISIT_LIST[0], id: 'vd-new', name: 'Week 2' } } as never)

    renderPage(<VisitsPage studyId="study-1" />)

    expect(await screen.findByText('Baseline')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Baseline'), { target: { value: 'Week 2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add visit' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/visits',
      expect.objectContaining({ name: 'Week 2', visit_type: 'visit', is_required: true, repeat_min: null, repeat_max: null, cycle_length: null }),
    ))
  })

  it('reveals cycle-only fields when visit_type is cycle', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      return Promise.resolve({ data: [VISIT_LIST[0]] })
    })

    renderPage(<VisitsPage studyId="study-1" />)

    await screen.findByText('Baseline')
    // Cycle-only fields are hidden until the visit type is 'cycle'.
    expect(screen.queryByLabelText('Cycle length')).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'cycle' } })
    expect(await screen.findByLabelText('Cycle length')).toBeInTheDocument()
  })

  it('visit dependency select excludes the current visit and POSTs a prerequisite; cycle_member rows are hidden', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: VISIT_LIST })
      if (url === '/designer/visits/visit-1/dependencies') {
        return Promise.resolve({ data: [
          { id: 'dep-1', visit_definition_id: 'visit-1', depends_on_visit_definition_id: 'visit-2', dependency_type: 'cycle_member', condition_expression: null },
        ] })
      }
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'dep-2', visit_definition_id: 'visit-1', depends_on_visit_definition_id: 'visit-2', dependency_type: 'prerequisite', condition_expression: null } } as never)

    renderPage(<VisitsPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Show dependencies for Baseline' }))

    const select = await screen.findByLabelText('Prerequisite visit for Baseline') as HTMLSelectElement
    const optionValues = Array.from(select.options).map((o) => o.value)
    expect(optionValues).not.toContain('visit-1') // self excluded
    expect(optionValues).toContain('visit-2')

    // The cycle_member dependency row must NOT be rendered as a prerequisite.
    expect(screen.getByText('No prerequisites.')).toBeInTheDocument()

    fireEvent.change(select, { target: { value: 'visit-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add prerequisite' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/visits/visit-1/dependencies',
      { depends_on_visit_definition_id: 'visit-2', dependency_type: 'prerequisite', condition_expression: null },
    ))
  })

  it('denies access without the read permission', async () => {
    seedPermissions([])
    vi.mocked(api.get).mockResolvedValue({ data: DRAFT_VERSIONS } as never)
    renderPage(<VisitsPage studyId="study-1" />)
    await waitFor(() => expect(screen.queryByText('Visits')).not.toBeInTheDocument())
  })
})
