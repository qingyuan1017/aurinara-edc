import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { CodelistsPage } from '@/features/designer/CodelistsPage'
import { SubjectPhasesPage } from '@/features/designer/SubjectPhasesPage'
import { ArmsPage } from '@/features/designer/ArmsPage'
import { ScheduleOfAssessmentPage } from '@/features/designer/ScheduleOfAssessmentPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
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

describe('SubjectPhasesPage (version-scoped)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.subject_phase.configure'])
  })

  it('prompts to create an amendment when no draft exists', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [DRAFT_VERSIONS[1]] } as never)
    renderPage(<SubjectPhasesPage studyId="study-1" />)
    expect(await screen.findByText(/no open draft version/i)).toBeInTheDocument()
  })

  it('creates a phase against the resolved draft version', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: DRAFT_VERSIONS } as never)
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'ph-1', design_version_id: 'ver-draft', name: 'Screening', display_order: 1, created_at: 'x' } } as never)

    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('Screening'), { target: { value: 'Screening' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add phase' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/subject-phases',
      { name: 'Screening', display_order: 1 },
    ))
    expect(await screen.findByText('Screening')).toBeInTheDocument()
  })
})

describe('ArmsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.arm.configure'])
  })

  it('creates an arm with an optional description', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: DRAFT_VERSIONS } as never)
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'arm-1', study_version_id: 'ver-draft', name: 'Active', display_order: 1, description: 'Treatment', created_at: 'x' } } as never)

    renderPage(<ArmsPage studyId="study-1" />)

    fireEvent.change(await screen.findByPlaceholderText('Active'), { target: { value: 'Active' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add arm' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/arms',
      { name: 'Active', display_order: 1, description: null },
    ))
  })
})

describe('ScheduleOfAssessmentPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.soa.read', 'designer.soa.configure'])
  })

  it('treats a 404 SoA as an empty editable matrix and submits entries', async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
      return Promise.reject({ response: { status: 404 } })
    })
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'soa-1', design_version_id: 'ver-draft', created_at: 'x', entries: [] } } as never)

    renderPage(<ScheduleOfAssessmentPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Entry 1 form definition ID'), { target: { value: 'form-1' } })
    fireEvent.change(screen.getByLabelText('Entry 1 visit definition ID'), { target: { value: 'visit-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/schedule-of-assessment',
      { entries: [expect.objectContaining({ form_definition_id: 'form-1', visit_definition_id: 'visit-1', procedure_name: null, cycle_definition_id: null, display_order: 1 })] },
    ))
  })
})
