import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { ScheduleOfAssessmentPage } from '@/features/designer/ScheduleOfAssessmentPage'
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
    user: { id: 'user-1', email: 'd@example.com', first_name: 'D', last_name: 'S', roles: [], permissions },
    isAuthenticated: true,
  })
}

const DRAFT_VERSIONS = [
  { id: 'ver-draft', study_id: 'study-1', version_number: '2', status: 'draft', created_at: '2024-01-02T00:00:00Z' },
]

const VISITS = [
  { id: 'visit-1', study_version_id: 'ver-draft', name: 'Baseline', visit_number: 1, visit_type: 'scheduled', definition_kind: 'visit', target_day: 0, window_before: null, window_after: null, display_order: 1, is_required: true, member_visit_ids: [], created_at: 'x' },
  { id: 'visit-2', study_version_id: 'ver-draft', name: 'Week 2', visit_number: 2, visit_type: 'scheduled', definition_kind: 'visit', target_day: 14, window_before: null, window_after: null, display_order: 2, is_required: true, member_visit_ids: [], created_at: 'x' },
  // Deliberately returned before its owner and with a display order that would
  // otherwise place it after visit #4. Hierarchical sorting must keep it at #3.
  { id: 'cycle-visit-1', study_version_id: 'ver-draft', name: 'Cycle day 8', visit_number: 8, visit_type: 'scheduled', definition_kind: 'cycle_visit', target_day: 8, window_before: null, window_after: null, display_order: 99, is_required: true, member_visit_ids: [], created_at: 'x' },
  { id: 'cycle-1', study_version_id: 'ver-draft', name: 'Treatment cycle', visit_number: 3, visit_type: 'cycle', definition_kind: 'cycle', target_day: null, window_before: null, window_after: null, display_order: 3, is_required: false, member_visit_ids: ['cycle-visit-1'], created_at: 'x' },
  { id: 'visit-4', study_version_id: 'ver-draft', name: 'Week 4', visit_number: 4, visit_type: 'scheduled', definition_kind: 'visit', target_day: 28, window_before: null, window_after: null, display_order: 4, is_required: true, member_visit_ids: [], created_at: 'x' },
]

const FORMS = [
  { id: 'form-1', name: 'Vitals', form_code: 'VITALS', display_order: 1, is_repeating: false },
  { id: 'form-2', name: 'Labs', form_code: 'LABS', display_order: 2, is_repeating: false },
]

function mockBase(soa: unknown = { status: 404 }) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
    if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: VISITS })
    if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
    if (url === '/designer/versions/ver-draft/schedule-of-assessment') {
      return Promise.reject({ response: soa })
    }
    return Promise.resolve({ data: [] })
  })
}

describe('ScheduleOfAssessmentPage (matrix)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    window.history.replaceState({}, '', window.location.pathname)
    seedPermissions(['designer.soa.read', 'designer.soa.configure'])
  })

  it('defaults to the newest draft after an ODM import', async () => {
    const versions = [
      { id: 'ver-old', study_id: 'study-1', version_number: '2.0', status: 'draft', created_at: '2024-01-02T00:00:00Z' },
      { id: 'ver-imported', study_id: 'study-1', version_number: '2.0_23Dec2025', status: 'draft', created_at: '2024-01-03T00:00:00Z' },
    ]
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: versions })
      if (url === '/designer/versions/ver-imported/visits') return Promise.resolve({ data: VISITS })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/versions/ver-imported/schedule-of-assessment') {
        return Promise.reject({ response: { status: 404 } })
      }
      return Promise.resolve({ data: [] })
    })

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    expect(await screen.findByRole('checkbox', { name: 'VITALS at Baseline' })).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/designer/versions/ver-imported/visits')
  })

  it('shows a legacy imported folder when the saved schedule uses it as a visit', async () => {
    const legacyFolderVisit = {
      ...VISITS[0],
      id: 'legacy-screening',
      definition_kind: 'folder',
    }
    const importedSoa = {
      id: 'soa-imported',
      design_version_id: 'ver-draft',
      created_at: 'x',
      entries: [{
        id: 'entry-1',
        schedule_of_assessment_id: 'soa-imported',
        form_definition_id: 'form-1',
        procedure_name: null,
        visit_definition_id: 'legacy-screening',
        display_order: 1,
        created_at: 'x',
      }],
    }
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: [legacyFolderVisit] })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/versions/ver-draft/schedule-of-assessment') return Promise.resolve({ data: importedSoa })
      return Promise.resolve({ data: [] })
    })

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    expect(await screen.findByRole('checkbox', { name: 'VITALS at Baseline' })).toHaveAttribute('aria-checked', 'true')
  })

  it('toggling a form cell then saving POSTs the full entry set with visit_definition_id and no cycle_definition_id', async () => {
    mockBase()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'soa-1', design_version_id: 'ver-draft', created_at: 'x', entries: [] } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('checkbox', { name: 'VITALS at Baseline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/schedule-of-assessment',
      { arm_definition_id: null, entries: [{ form_definition_id: 'form-1', procedure_name: null, visit_definition_id: 'visit-1', display_order: 1 }] },
    ))
    const payload = vi.mocked(api.post).mock.calls[0][1] as { entries: Record<string, unknown>[] }
    expect(payload.entries.every((e) => !('cycle_definition_id' in e))).toBe(true)
    expect(screen.getByRole('checkbox', { name: 'VITALS at Cycle day 8' })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'VITALS at Treatment cycle' })).not.toBeInTheDocument()
  })

  it('loads and saves an independent schedule for the selected treatment arm', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: VISITS })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/versions/ver-draft/arms') return Promise.resolve({ data: [{
        id: 'arm-a', study_version_id: 'ver-draft', name: 'Arm A', display_order: 1,
        description: null, created_at: 'x',
      }] })
      if (url === '/designer/versions/ver-draft/schedule-of-assessment') {
        return Promise.reject({ response: { status: 404 } })
      }
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: {
      id: 'soa-arm-a', design_version_id: 'ver-draft', arm_definition_id: 'arm-a',
      created_at: 'x', entries: [],
    } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Schedule scope'), { target: { value: 'arm-a' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'VITALS at Baseline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/schedule-of-assessment',
      { arm_definition_id: 'arm-a', entries: [{ form_definition_id: 'form-1', procedure_name: null, visit_definition_id: 'visit-1', display_order: 1 }] },
    ))
  })

  it('copies the common schedule into an arm draft and saves it for that arm', async () => {
    const commonSoa = {
      id: 'soa-common', design_version_id: 'ver-draft', arm_definition_id: null,
      created_at: 'x', entries: [
        { id: 'entry-1', schedule_of_assessment_id: 'soa-common', form_definition_id: 'form-1', procedure_name: null, visit_definition_id: 'visit-1', display_order: 1, created_at: 'x' },
        { id: 'entry-2', schedule_of_assessment_id: 'soa-common', form_definition_id: null, procedure_name: 'ECG', visit_definition_id: 'visit-2', display_order: 2, created_at: 'x' },
      ],
    }
    vi.mocked(api.get).mockImplementation((url: string, config?: unknown) => {
      const armDefinitionId = (config as { params?: { arm_definition_id?: string } } | undefined)?.params?.arm_definition_id
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: VISITS })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/versions/ver-draft/arms') return Promise.resolve({ data: [{
        id: 'arm-a', study_version_id: 'ver-draft', name: 'Arm A', display_order: 1,
        description: null, created_at: 'x',
      }] })
      if (url === '/designer/versions/ver-draft/schedule-of-assessment') {
        if (armDefinitionId === 'arm-a') return Promise.reject({ response: { status: 404 } })
        return Promise.resolve({ data: commonSoa })
      }
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: {
      id: 'soa-arm-a', design_version_id: 'ver-draft', arm_definition_id: 'arm-a',
      created_at: 'x', entries: [],
    } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Schedule scope'), { target: { value: 'arm-a' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Copy from common' }))

    expect(screen.getByRole('checkbox', { name: 'VITALS at Baseline' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('checkbox', { name: 'ECG at Week 2' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText(/unsaved draft/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/schedule-of-assessment',
      { arm_definition_id: 'arm-a', entries: [
        { form_definition_id: 'form-1', procedure_name: null, visit_definition_id: 'visit-1', display_order: 1 },
        { form_definition_id: null, procedure_name: 'ECG', visit_definition_id: 'visit-2', display_order: 2 },
      ] },
    ))
  })

  it('keeps cycle-owned visits at the cycle hierarchy position between peer visits', async () => {
    mockBase()

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    await screen.findByRole('checkbox', { name: 'VITALS at Cycle day 8' })
    const headers = screen.getAllByRole('columnheader').map((header) => header.textContent)
    expect(headers).toEqual([
      'Form / procedure',
      '1 · Baseline',
      '2 · Week 2',
      '8 · Cycle day 8Treatment cycle',
      '4 · Week 4',
    ])
  })

  it('a second toggle+save POSTs the full updated set again (replace contract)', async () => {
    mockBase()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'soa-1', design_version_id: 'ver-draft', created_at: 'x', entries: [] } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('checkbox', { name: 'VITALS at Baseline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))

    // Add a second cell and save again — the client sends the complete set.
    fireEvent.click(screen.getByRole('checkbox', { name: 'LABS at Week 2' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
    const secondPayload = vi.mocked(api.post).mock.calls[1][1] as { entries: Record<string, unknown>[] }
    expect(secondPayload.entries).toHaveLength(2)
    expect(secondPayload.entries).toEqual([
      { form_definition_id: 'form-1', procedure_name: null, visit_definition_id: 'visit-1', display_order: 1 },
      { form_definition_id: 'form-2', procedure_name: null, visit_definition_id: 'visit-2', display_order: 2 },
    ])
  })

  it('a toggled procedure cell POSTs form_definition_id=null and the trimmed procedure_name (never both ids)', async () => {
    mockBase()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'soa-1', design_version_id: 'ver-draft', created_at: 'x', entries: [] } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Add procedure row' }))
    fireEvent.change(screen.getByLabelText('Procedure name'), { target: { value: '  ECG  ' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'ECG at Baseline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(api.post).mock.calls[0][1] as { entries: Record<string, unknown>[] }
    expect(payload.entries).toEqual([
      { form_definition_id: null, procedure_name: 'ECG', visit_definition_id: 'visit-1', display_order: 1 },
    ])
  })

  it('blocks save (no POST) while a toggled procedure row name is blank, with an inline error', async () => {
    mockBase()

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Add procedure row' }))
    // Toggle a cell on the blank-named procedure row.
    fireEvent.click(screen.getByRole('checkbox', { name: 'Procedure at Baseline' }))

    expect(screen.getByText('A scheduled procedure row needs a name.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save schedule' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))
    await new Promise((r) => setTimeout(r, 20))
    expect(api.post).not.toHaveBeenCalled()
  })

  it('display_order is contiguous and deterministic across mixed form + procedure rows', async () => {
    mockBase()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'soa-1', design_version_id: 'ver-draft', created_at: 'x', entries: [] } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    // Two form cells + one procedure cell across the matrix.
    fireEvent.click(await screen.findByRole('checkbox', { name: 'VITALS at Week 2' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'LABS at Baseline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add procedure row' }))
    fireEvent.change(screen.getByLabelText('Procedure name'), { target: { value: 'ECG' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'ECG at Baseline' }))

    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(api.post).mock.calls[0][1] as { entries: Record<string, unknown>[] }
    // Running index: form rows (by display_order) x visits (by display_order),
    // then procedure rows. form-1@visit-2 (ord1), form-2@visit-1 (ord2), ECG@visit-1 (ord3).
    expect(payload.entries).toEqual([
      { form_definition_id: 'form-1', procedure_name: null, visit_definition_id: 'visit-2', display_order: 1 },
      { form_definition_id: 'form-2', procedure_name: null, visit_definition_id: 'visit-1', display_order: 2 },
      { form_definition_id: null, procedure_name: 'ECG', visit_definition_id: 'visit-1', display_order: 3 },
    ])
    expect(payload.entries.map((e) => e.display_order)).toEqual([1, 2, 3])
  })
})
