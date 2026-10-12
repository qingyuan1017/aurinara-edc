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
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
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
  { id: 'visit-1', study_version_id: 'ver-draft', name: 'Baseline', visit_number: 1, visit_type: 'scheduled', definition_kind: 'visit', target_day: 0, window_before: null, window_after: null, display_order: 1, is_required: true, repeat_min: null, repeat_max: null, cycle_length: null, member_visit_ids: [], created_at: 'x' },
  { id: 'visit-2', study_version_id: 'ver-draft', name: 'Week 2', visit_number: 2, visit_type: 'scheduled', definition_kind: 'visit', target_day: 14, window_before: 2, window_after: 2, display_order: 2, is_required: true, repeat_min: null, repeat_max: null, cycle_length: null, member_visit_ids: [], created_at: 'x' },
]
const CYCLE_VISIT = { id: 'cycle-visit-1', study_version_id: 'ver-draft', name: 'Cycle day 8', visit_number: 8, visit_type: 'scheduled', definition_kind: 'cycle_visit', target_day: 8, window_before: 1, window_after: 1, display_order: 3, is_required: true, repeat_min: null, repeat_max: null, cycle_length: null, member_visit_ids: [], created_at: 'x' }
const CYCLE = { id: 'cycle-1', study_version_id: 'ver-draft', name: 'Treatment cycle', visit_number: 3, visit_type: 'cycle', definition_kind: 'cycle', target_day: null, window_before: null, window_after: null, display_order: 3, is_required: true, repeat_min: 1, repeat_max: 6, cycle_length: 28, member_visit_ids: ['cycle-visit-1'], created_at: 'x' }

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState({}, '', window.location.pathname)
})

describe('CodelistsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    seedPermissions(['designer.codelist.read', 'designer.codelist.configure'])
  })

  it('lists codelists and creates a new one with items', async () => {
    const created = { id: 'cl-2', study_version_id: 'ver-draft', name: 'Severity', code: 'SEV', items: [] }
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
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
      { params: { study_version_id: 'ver-draft' } },
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
    localStorage.clear()
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

  it('selects a previous published version inside Designer and hides arm authoring controls', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-pub/arms') return Promise.resolve({ data: [{ id: 'arm-old', study_version_id: 'ver-pub', name: 'Previous ARM', display_order: 1, description: null, visit_definition_ids: [], created_at: 'x' }] })
      if (url === '/designer/versions/ver-pub/visits') return Promise.resolve({ data: [] })
      if (url === '/designer/versions/ver-draft/arms' || url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    renderPage(<ArmsPage studyId="study-1" />)
    fireEvent.change(await screen.findByLabelText('Design version'), { target: { value: 'ver-pub' } })

    expect(await screen.findByText('Previous ARM')).toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).get('design_version_id')).toBe('ver-pub')
    expect(screen.getByText('Viewing published version 1. This design is read-only.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add arm' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit Previous ARM' })).not.toBeInTheDocument()
  })

  it('selects a visit folder as a group while allowing individual child overrides', async () => {
    const hierarchicalVisits = [
      { ...VISIT_LIST[0], id: 'folder-1', name: 'Screening', visit_number: 1, definition_kind: 'folder', visit_type: 'folder' },
      { ...VISIT_LIST[0], id: 'screen-1', name: 'Consent', visit_number: 1, parent_folder_id: 'folder-1' },
      { ...VISIT_LIST[0], id: 'screen-2', name: 'Eligibility', visit_number: 2, parent_folder_id: 'folder-1' },
      { ...VISIT_LIST[1], id: 'visit-4', name: 'Week 4', visit_number: 4 },
    ]
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/arms') return Promise.resolve({ data: [] })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: hierarchicalVisits })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'arm-1' } } as never)

    renderPage(<ArmsPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('Active'), { target: { value: 'Screening arm' } })
    fireEvent.click(screen.getByLabelText('Include group Screening'))
    expect(screen.getByLabelText('Include visit Consent')).toBeChecked()
    expect(screen.getByLabelText('Include visit Eligibility')).toBeChecked()

    fireEvent.click(screen.getByLabelText('Include visit Eligibility'))
    expect(screen.getByLabelText('Include group Screening')).toHaveAttribute('aria-checked', 'mixed')
    fireEvent.click(screen.getByRole('button', { name: 'Add arm' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/arms',
      { name: 'Screening arm', display_order: 1, description: null, visit_definition_ids: ['screen-1'] },
    ))
  })

  it('edits a legacy arm by expanding its cycle container to real visit leaves', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/arms') return Promise.resolve({ data: [{
        id: 'arm-b', study_version_id: 'ver-draft', name: 'ARM B', display_order: 2,
        description: null, visit_definition_ids: ['visit-1', 'cycle-1'], created_at: 'x',
      }] })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: [...VISIT_LIST, CYCLE, CYCLE_VISIT] })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.patch).mockResolvedValue({ data: {
      id: 'arm-b', study_version_id: 'ver-draft', name: 'ARM B', display_order: 2,
      description: null, visit_definition_ids: ['visit-1', 'cycle-visit-1'], created_at: 'x',
    } } as never)

    renderPage(<ArmsPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Edit ARM B' }))
    expect(screen.getByLabelText('Include visit Baseline')).toBeChecked()
    expect(screen.getByLabelText('Include group Treatment cycle')).toBeChecked()
    expect(screen.getByLabelText('Include visit Cycle day 8')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Update arm' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/arms/arm-b',
      { name: 'ARM B', display_order: 2, description: null, visit_definition_ids: ['visit-1', 'cycle-visit-1'] },
    ))
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
  })

  it('shows generated variables and configures field suffixes', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: [{
        id: 'form-1', form_code: 'DM', name: 'Demographics', sections: [{
          is_label_only: false, output_to_dataset: true, fields: [
            { id: 'severity', label: 'Severity', variable_name: 'SEV', control_type: 'radio', data_type: 'string', codelist_id: 'cl-1' },
            { id: 'age', label: 'Age', variable_name: 'AGE', control_type: 'integer', data_type: 'integer' },
            { id: 'dob', label: 'Birth date', variable_name: 'DOB', control_type: 'date', data_type: 'date' },
          ],
        }],
      }] })
      if (url === '/designer/versions/ver-draft/raw-data-variables') return Promise.resolve({ data: [] })
      if (url === '/designer/versions/ver-draft/raw-data-datasets') return Promise.resolve({ data: [{
        form_definition_id: 'form-1', form_code: 'DM', dataset_name: 'DM', variables: [
          { name: 'PROTOCOL', data_type: 'string', label: 'Protocol', source: 'fixed' },
          { name: 'SEV', data_type: 'string', label: 'Severity', source: 'field', field_definition_id: 'severity' },
          { name: 'SEV_LABEL', data_type: 'string', label: 'Severity (codelist)', source: 'codelist_companion', field_definition_id: 'severity' },
          { name: 'DOB_YEAR', data_type: 'integer', label: 'Birth date (year)', source: 'date_year', field_definition_id: 'dob' },
        ],
      }] })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.put).mockResolvedValue({ data: { id: 'rdv-1', field_definition_id: 'severity', suffix: 'DECODE' } } as never)

    renderPage(<RawDataVariablesPage studyId="study-1" />)

    expect(await screen.findByText('PROTOCOL')).toBeInTheDocument()
    expect(screen.getByText('SEV_LABEL')).toBeInTheDocument()
    expect(screen.getByText('DOB_YEAR')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('SEV companion suffix'), { target: { value: 'DECODE' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Save' })[0])

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/raw-data-variables/fields/severity',
      { suffix: 'DECODE' },
    ))
  })
})

describe('VisitsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.visit.read', 'designer.visit.configure'])
  })

  it('creates a real visit with scheduled type by default', async () => {
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
      expect.objectContaining({ name: 'Week 2', definition_kind: 'visit', visit_type: 'scheduled', is_required: true, repeat_min: null, repeat_max: null, cycle_length: null }),
    ))
  })

  it('reveals cycle-only fields when definition kind is cycle', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      return Promise.resolve({ data: [VISIT_LIST[0]] })
    })

    renderPage(<VisitsPage studyId="study-1" />)

    await screen.findByText('Baseline')
    // Cycle-only fields are hidden until the definition kind is 'cycle'.
    expect(screen.queryByLabelText('Cycle length')).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: /Definition kind/ }), { target: { value: 'cycle' } })
    expect(await screen.findByLabelText('Cycle length')).toBeInTheDocument()
  })

  it('configures child visits inside their owning cycle instead of using a shared list', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      return Promise.resolve({ data: [...VISIT_LIST, CYCLE, CYCLE_VISIT] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: CYCLE_VISIT } as never)

    renderPage(<VisitsPage studyId="study-1" />)

    expect(await screen.findByText('Treatment cycle')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Treatment cycle: visits' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show visits for Treatment cycle' }))
    expect(await screen.findByRole('heading', { name: 'Treatment cycle: visits' })).toBeInTheDocument()
    expect(screen.getAllByText('Cycle day 8').length).toBeGreaterThanOrEqual(1)
    fireEvent.change(screen.getByPlaceholderText('Cycle day 1'), { target: { value: 'Cycle day 15' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add cycle visit' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/cycles/cycle-1/visits',
      expect.objectContaining({ name: 'Cycle day 15', definition_kind: 'cycle_visit' }),
    ))
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
