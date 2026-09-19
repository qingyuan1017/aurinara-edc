import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { FormBuilderPage } from '@/features/forms/FormBuilderPage'
import { QueryListPage } from '@/features/queries/QueryListPage'
import { VisitListPage } from '@/features/visits/VisitListPage'

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('EDC lifecycle presentation migrations', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: { id: 'user-1', email: 'dm@example.com', first_name: 'Data', last_name: 'Manager', roles: [], permissions: ['form.configure', 'query.create', 'form.enter'] }, isAuthenticated: true })
  })

  it('keeps form builder creation payload and endpoint while using labeled shared controls', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: [] } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<FormBuilderPage studyId="study-1" />)

    fireEvent.change(await screen.findByLabelText('Form name'), { target: { value: 'Vitals' } })
    fireEvent.change(screen.getByLabelText('Form code'), { target: { value: 'VITALS' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create form' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/forms', { name: 'Vitals', form_code: 'VITALS', display_order: 0, is_repeating: false }))
  })

  it('keeps query creation contract and presents the workflow in an accessible dialog', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [], page: 1, page_size: 50, total: 0 } } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<QueryListPage studyId="study-1" />)

    fireEvent.click(screen.getByRole('button', { name: 'New query' }))
    fireEvent.change(screen.getByLabelText('Affected object ID'), { target: { value: 'form-1' } })
    fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'Confirm the source date.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/queries', { target_type: 'Subject', target_id: 'form-1', text: 'Confirm the source date.', assigned_role: null }))
  })

  it('keeps visit creation and date-recording endpoints while replacing prompt/modal presentation', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: [{ id: 'visit-1', name: 'Baseline', visit_date: null, window_status: 'In window', status: 'scheduled' }] } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<VisitListPage subjectId="subject-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Record date' }))
    fireEvent.change(screen.getByLabelText('Visit date'), { target: { value: '2026-02-01' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Record date' }).at(-1)!)
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/visits/visit-1', { visit_date: '2026-02-01' }))

    fireEvent.click(screen.getByRole('button', { name: 'Add unscheduled visit' }))
    fireEvent.change(screen.getByLabelText('Visit name'), { target: { value: 'Unscheduled' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/subjects/subject-1/visits/unscheduled', { name: 'Unscheduled', visit_date: null }))
  })
})
