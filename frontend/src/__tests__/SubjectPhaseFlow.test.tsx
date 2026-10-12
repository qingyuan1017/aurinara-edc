import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { SubjectPhasesPage } from '@/features/designer/SubjectPhasesPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

// React Flow measures its container with ResizeObserver, which jsdom lacks.
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof ResizeObserverMock }).ResizeObserver = ResizeObserverMock

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

const PHASES = [
  { id: 'ph-1', design_version_id: 'ver-draft', name: 'Screening', phase_type: 'registered', display_order: 1, visit_definition_ids: ['visit-1'], created_at: 'x' },
  { id: 'ph-2', design_version_id: 'ver-draft', name: 'Treatment', phase_type: 'common', display_order: 2, visit_definition_ids: [], created_at: 'x' },
]

function mockBase(transitions: unknown[] = []) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
    if (url === '/designer/versions/ver-draft/subject-phases') return Promise.resolve({ data: PHASES })
    if (url === '/designer/versions/ver-draft/subject-phase-transitions') return Promise.resolve({ data: transitions })
    if (url === '/designer/versions/ver-draft/visits') return Promise.resolve({ data: [
      { id: 'visit-1', name: 'Screening visit', definition_kind: 'visit' },
      { id: 'cycle-visit-1', name: 'Cycle day 1', definition_kind: 'cycle_visit' },
      { id: 'folder-1', name: 'Screening folder', definition_kind: 'folder' },
    ] })
    return Promise.resolve({ data: [] })
  })
}

describe('SubjectPhasesPage (flow)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    window.history.replaceState({}, '', window.location.pathname)
    seedPermissions(['designer.subject_phase.read', 'designer.subject_phase.configure'])
  })

  it('renders nodes from the phases list', async () => {
    mockBase()
    renderPage(<SubjectPhasesPage studyId="study-1" />)
    // The flow graph renders a node per phase; React Flow renders each node's
    // label in the DOM. Both phase names appear (nodes + selects), so assert
    // at least one occurrence of each.
    expect((await screen.findAllByText('Screening')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Treatment').length).toBeGreaterThan(0)
    // The React Flow graph container is present and labelled.
    expect(screen.getByLabelText('Subject phase flow graph')).toBeInTheDocument()
  })

  it('shows visit membership for every phase in a selected published version', async () => {
    localStorage.setItem('designer:selected-version:study-1', 'ver-pub')
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: [
        ...DRAFT_VERSIONS,
        { id: 'ver-pub', study_id: 'study-1', version_number: '1', status: 'published', created_at: '2024-01-01T00:00:00Z' },
      ] })
      if (url === '/designer/versions/ver-pub/subject-phases') return Promise.resolve({ data: [
        { id: 'old-ph-1', design_version_id: 'ver-pub', name: 'Published treatment', phase_type: 'common', display_order: 1, visit_definition_ids: ['old-visit-1', 'old-cycle-visit-1'], created_at: 'x' },
        { id: 'old-ph-2', design_version_id: 'ver-pub', name: 'Published complete', phase_type: 'complete', display_order: 2, visit_definition_ids: [], created_at: 'x' },
      ] })
      if (url === '/designer/versions/ver-pub/subject-phase-transitions') return Promise.resolve({ data: [] })
      if (url === '/designer/versions/ver-pub/visits') return Promise.resolve({ data: [
        { id: 'old-visit-1', name: 'Published baseline', definition_kind: 'visit' },
        { id: 'old-cycle-visit-1', name: 'Published cycle day 1', definition_kind: 'cycle_visit' },
      ] })
      return Promise.resolve({ data: [] })
    })

    renderPage(<SubjectPhasesPage studyId="study-1" />)

    expect(await screen.findByRole('heading', { name: 'Phase visit membership' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Published treatment visit membership' })).toHaveTextContent('Published baseline')
    expect(screen.getByRole('region', { name: 'Published treatment visit membership' })).toHaveTextContent('Published cycle day 1')
    expect(screen.getByRole('region', { name: 'Published complete visit membership' })).toHaveTextContent('This phase completes the study and has no associated visits.')
    expect(screen.queryByRole('button', { name: 'Save phase' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete phase' })).not.toBeInTheDocument()
  })

  it('does NOT POST a transition when source equals target (self-guard)', async () => {
    mockBase()
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    const fromSelect = await screen.findByLabelText('Transition from phase')
    fireEvent.change(fromSelect, { target: { value: 'ph-1' } })
    // The "to" select excludes the chosen "from" phase, so a self-transition
    // cannot be constructed; forcing an equal value is rejected without a POST.
    const toSelect = screen.getByLabelText('Transition to phase')
    fireEvent.change(toSelect, { target: { value: 'ph-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add transition' }))

    await new Promise((r) => setTimeout(r, 20))
    expect(api.post).not.toHaveBeenCalledWith(
      '/designer/versions/ver-draft/subject-phase-transitions',
      expect.anything(),
    )
  })

  it('POSTs a transition for a valid connection between two different phases', async () => {
    mockBase()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 't-1', from_phase_id: 'ph-1', to_phase_id: 'ph-2', label: null } } as never)

    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Transition from phase'), { target: { value: 'ph-1' } })
    fireEvent.change(screen.getByLabelText('Transition to phase'), { target: { value: 'ph-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add transition' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/subject-phase-transitions',
      { from_phase_id: 'ph-1', to_phase_id: 'ph-2' },
    ))
  })

  it('deletes a phase via DELETE', async () => {
    mockBase([{ id: 't-1', from_phase_id: 'ph-1', to_phase_id: 'ph-2', label: null }])
    vi.mocked(api.delete).mockResolvedValue({ data: {} } as never)

    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Select phase'), { target: { value: 'ph-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Delete phase' }))

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/designer/subject-phases/ph-1'))
  })

  it('updates a phase with its associated real visits', async () => {
    mockBase()
    vi.mocked(api.patch).mockResolvedValue({ data: PHASES[0] } as never)
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Select phase'), { target: { value: 'ph-1' } })
    expect(screen.getAllByText('Screening visit').length).toBeGreaterThan(0)
    expect(screen.queryByText('Screening folder')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save phase' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/designer/subject-phases/ph-1',
      { name: 'Screening', phase_type: 'registered', visit_definition_ids: ['visit-1'] },
    ))
  })

  it('does not offer visit membership for arm and complete phases', async () => {
    mockBase()
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('New phase type'), { target: { value: 'arm' } })
    expect(screen.getByText('This phase type does not associate visits.')).toBeInTheDocument()
  })
})
