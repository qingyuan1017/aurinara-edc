import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SubjectCasebookPage } from '@/features/subjects/SubjectCasebookPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'


vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, params, search, children, ...props }: { to: string; params?: Record<string, string>; search?: Record<string, string>; children: React.ReactNode; [key: string]: unknown }) => {
    const path = Object.entries(params ?? {}).reduce((value, [key, replacement]) => value.replace(`$${key}`, replacement), to)
    const query = search && Object.keys(search).length ? `?${new URLSearchParams(search).toString()}` : ''
    return <a href={`${path}${query}`} {...props}>{children}</a>
  },
}))

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() },
}))

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SubjectCasebookPage subjectId="subject-1" />
    </QueryClientProvider>,
  )
}

describe('Study Data subject phase control', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      user: { id: 'user-1', email: 'entry@example.com', first_name: 'Data', last_name: 'Entry', roles: [], permissions: ['subject.update'] },
      isAuthenticated: true,
    })
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/subjects/subject-1/casebook') return Promise.resolve({ data: {
        subject_id: 'subject-1',
        subject_number: '101-001',
        status: 'Screening',
        study_version_id: 'version-1',
        visits: [{ visit_instance_id: 'visit-instance-1', visit_definition_id: 'visit-1', name: 'Screening', status: 'scheduled', forms: [] }],
      } })
      if (url === '/subjects/subject-1/phase') return Promise.resolve({ data: {
        current_phase_definition_id: 'phase-1',
        current_phase_name: 'Registered',
        current_phase_type: 'registered',
        phases: [
          { id: 'phase-1', name: 'Registered', phase_type: 'registered', display_order: 1, visit_definition_ids: ['visit-1'] },
          { id: 'phase-2', name: 'Randomization', phase_type: 'arm', display_order: 2, visit_definition_ids: [] },
          { id: 'phase-3', name: 'Complete', phase_type: 'complete', display_order: 3, visit_definition_ids: [] },
        ],
        next_phases: [
          { id: 'phase-2', name: 'Randomization', phase_type: 'arm', display_order: 2, visit_definition_ids: [] },
        ],
        arms: [{ id: 'arm-1', name: 'Arm A', display_order: 1 }],
      } })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never)
  })

  it('prompts for a configured arm before entering an arm phase', async () => {
    renderPage()

    expect(await screen.findByRole('status', { name: 'Subject status: Registered' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Move to Complete' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Move to Randomization' }))

    expect(screen.getByRole('dialog', { name: 'Choose subject arm' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Subject arm'), { target: { value: 'arm-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Assign arm and continue' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/subjects/subject-1/phase',
      { phase_definition_id: 'phase-2', arm_definition_id: 'arm-1' },
    ))
  })
})
