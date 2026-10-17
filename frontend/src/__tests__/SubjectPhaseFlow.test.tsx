import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { SubjectPhasesPage } from '@/features/designer/SubjectPhasesPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

// Keep flow interaction tests deterministic in jsdom while exercising the
// page's actual onConnect and onNodeClick handlers.
vi.mock('@xyflow/react', () => ({
  ReactFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  ReactFlow: ({
    nodes,
    edges,
    onConnect,
    onNodeClick,
    onEdgeClick,
    children,
    'aria-label': ariaLabel,
  }: {
    nodes: Array<{ id: string; data: { label?: string }; className?: string }>
    edges: Array<{ id: string }>
    onConnect?: (connection: { source: string; target: string; sourceHandle: null; targetHandle: null }) => void
    onNodeClick?: (event: unknown, node: { id: string; data: { label?: string } }) => void
    onEdgeClick?: (event: unknown, edge: { id: string }) => void
    children?: ReactNode
    'aria-label'?: string
  }) => (
    <div aria-label={ariaLabel}>
      {nodes.map((node) => (
        <button key={node.id} type="button" className={node.className} aria-label={`Edit ${node.data.label ?? node.id}`} onClick={() => onNodeClick?.({}, node)}>
          {node.data.label}
        </button>
      ))}
      {edges.map((edge) => (
        <button key={edge.id} type="button" aria-label={`Select link ${edge.id}`} onClick={() => onEdgeClick?.({}, edge)} />
      ))}
      <button type="button" aria-label="Connect ph-1 to ph-2" onClick={() => onConnect?.({ source: 'ph-1', target: 'ph-2', sourceHandle: null, targetHandle: null })} />
      <button type="button" aria-label="Connect ph-1 to itself" onClick={() => onConnect?.({ source: 'ph-1', target: 'ph-1', sourceHandle: null, targetHandle: null })} />
      {children}
    </div>
  ),
  Background: () => null,
  Controls: () => null,
  addEdge: (connection: unknown, edges: unknown[]) => [...edges, connection],
  applyEdgeChanges: (_changes: unknown[], edges: unknown[]) => edges,
  applyNodeChanges: (_changes: unknown[], nodes: unknown[]) => nodes,
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
    expect(screen.getByLabelText('Phase type color legend')).toHaveTextContent('Registered')
    expect(screen.getByRole('button', { name: 'Edit Screening (registered)' })).toHaveClass('!border-blue-500')
    expect(screen.getByRole('button', { name: 'Edit Treatment (common)' })).toHaveClass('!border-slate-500')
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
        { id: 'old-ph-2', design_version_id: 'ver-pub', name: 'Published complete', phase_type: 'complete', display_order: 2, visit_definition_ids: ['old-complete-visit'], created_at: 'x' },
      ] })
      if (url === '/designer/versions/ver-pub/subject-phase-transitions') return Promise.resolve({ data: [] })
      if (url === '/designer/versions/ver-pub/visits') return Promise.resolve({ data: [
        { id: 'old-visit-1', name: 'Published baseline', definition_kind: 'visit' },
        { id: 'old-cycle-visit-1', name: 'Published cycle day 1', definition_kind: 'cycle_visit' },
        { id: 'old-complete-visit', name: 'End of study', definition_kind: 'visit' },
      ] })
      return Promise.resolve({ data: [] })
    })

    renderPage(<SubjectPhasesPage studyId="study-1" />)

    expect(await screen.findByRole('heading', { name: 'Phase visit membership' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Published treatment visit membership' })).toHaveTextContent('Published baseline')
    expect(screen.getByRole('region', { name: 'Published treatment visit membership' })).toHaveTextContent('Published cycle day 1')
    expect(screen.getByRole('region', { name: 'Published complete visit membership' })).toHaveTextContent('End of study')
    expect(screen.queryByRole('button', { name: 'Save phase' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete phase' })).not.toBeInTheDocument()
  })

  it('does NOT POST a transition when source equals target (self-guard)', async () => {
    mockBase()
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Connect ph-1 to itself' }))

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

    expect(await screen.findByText(/Drag from a phase connection handle/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Add transition' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Connect ph-1 to ph-2' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/subject-phase-transitions',
      { from_phase_id: 'ph-1', to_phase_id: 'ph-2' },
    ))
  })

  it('does not POST a duplicate directed connection', async () => {
    mockBase([{ id: 't-1', from_phase_id: 'ph-1', to_phase_id: 'ph-2', label: null }])
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Connect ph-1 to ph-2' }))

    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(api.post).not.toHaveBeenCalledWith(
      '/designer/versions/ver-draft/subject-phase-transitions',
      expect.anything(),
    )
  })

  it('deletes a selected link using the visible action', async () => {
    mockBase([{ id: 't-1', from_phase_id: 'ph-1', to_phase_id: 'ph-2', label: null }])
    vi.mocked(api.delete).mockResolvedValue({ data: {} } as never)
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    const deleteLink = await screen.findByRole('button', { name: 'Delete selected link' })
    expect(deleteLink).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Select link t-1' }))
    expect(deleteLink).toBeEnabled()
    fireEvent.click(deleteLink)

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(
      '/designer/versions/ver-draft/subject-phase-transitions/t-1',
    ))
  })

  it('deletes a phase via DELETE', async () => {
    mockBase([{ id: 't-1', from_phase_id: 'ph-1', to_phase_id: 'ph-2', label: null }])
    vi.mocked(api.delete).mockResolvedValue({ data: {} } as never)

    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Select phase to edit'), { target: { value: 'ph-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Delete phase' }))

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/designer/subject-phases/ph-1'))
  })

  it('updates a phase with its associated real visits', async () => {
    mockBase()
    vi.mocked(api.patch).mockResolvedValue({ data: PHASES[0] } as never)
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Edit Screening (registered)' }))
    expect(screen.getAllByText('Screening visit').length).toBeGreaterThan(0)
    expect(screen.queryByText('Screening folder')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save phase' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/designer/subject-phases/ph-1',
      { name: 'Screening', phase_type: 'registered', visit_definition_ids: ['visit-1'] },
    ))
  })

  it('offers visit membership for complete phases but not arm phases', async () => {
    mockBase()
    renderPage(<SubjectPhasesPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('New phase type'), { target: { value: 'complete' } })
    expect(screen.getByText('Associated visits')).toBeInTheDocument()

    fireEvent.change(await screen.findByLabelText('New phase type'), { target: { value: 'arm' } })
    expect(screen.getByText('This phase type does not associate visits.')).toBeInTheDocument()
  })
})
