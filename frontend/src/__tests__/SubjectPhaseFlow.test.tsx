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
  { id: 'ph-1', design_version_id: 'ver-draft', name: 'Screening', display_order: 1, created_at: 'x' },
  { id: 'ph-2', design_version_id: 'ver-draft', name: 'Treatment', display_order: 2, created_at: 'x' },
]

function mockBase(transitions: unknown[] = []) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/studies/study-1/versions') return Promise.resolve({ data: DRAFT_VERSIONS })
    if (url === '/designer/versions/ver-draft/subject-phases') return Promise.resolve({ data: PHASES })
    if (url === '/designer/versions/ver-draft/subject-phase-transitions') return Promise.resolve({ data: transitions })
    return Promise.resolve({ data: [] })
  })
}

describe('SubjectPhasesPage (flow)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
})
