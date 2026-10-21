import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { FormBuilderPage } from '@/features/designer/FormBuilderPage'
import { QueryListPage } from '@/features/queries/QueryListPage'
import { VisitListPage } from '@/features/visits/VisitListPage'

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('EDC lifecycle presentation migrations', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    window.history.replaceState({}, '', window.location.pathname)
    useAuthStore.setState({ user: { id: 'user-1', email: 'dm@example.com', first_name: 'Data', last_name: 'Manager', roles: [], permissions: ['designer.form.read', 'designer.form.configure', 'designer.field.configure', 'query.create', 'form.enter'] }, isAuthenticated: true })
  })

  it('keeps form builder creation payload and endpoint while using labeled shared controls', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url === '/studies/study-1/versions'
      ? [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }]
      : [] } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Add form' }))
    fireEvent.change(await screen.findByLabelText('Form name'), { target: { value: 'Vitals' } })
    fireEvent.change(screen.getByLabelText('Form code'), { target: { value: 'VITALS' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create form' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/designer/studies/study-1/forms', {
      name: 'Vitals',
      form_code: 'VITALS',
      display_order: 0,
      is_repeating: false,
      form_type: 'simple',
      access_type: 'open_access',
      domain: null,
      label: null,
      grid_rows: null,
      grid_columns: null,
      header_name: null,
      detail_name: null,
      detail_type: null,
      show_variable_name: false,
      show_crf_id: false,
      show_odm_id: false,
    }, { params: { study_version_id: 'ver-draft' } }))
  })

  it('keeps query creation contract and presents the workflow in an accessible dialog', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url.endsWith('/subjects')
      ? { items: [{ id: 'subject-1', subject_number: 'SUBJ-001', site_id: 'site-1', site_number: '101' }], page: 1, page_size: 100, total: 1 }
      : { items: [], page: 1, page_size: 50, total: 0 } } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<QueryListPage studyId="study-1" />)

    fireEvent.click(screen.getByRole('button', { name: 'New query' }))
    const subjectSelect = screen.getByLabelText('Affected subject')
    await screen.findByRole('option', { name: /SUBJ-001/ })
    fireEvent.change(subjectSelect, { target: { value: 'subject-1' } })
    fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'Confirm the source date.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/queries', { target_type: 'Subject', target_id: 'subject-1', text: 'Confirm the source date.', assigned_role: null }))
  })

  it('keeps visit date recording while hiding creation when the design has no addable visits', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url.endsWith('/addable') ? [] : [{ id: 'visit-1', name: 'Baseline', visit_date: null, window_status: 'In window', status: 'scheduled' }] } as never))
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<VisitListPage subjectId="subject-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Record date' }))
    fireEvent.change(screen.getByLabelText('Visit date'), { target: { value: '2026-02-01' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Record date' }).at(-1)!)
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/visits/visit-1', { visit_date: '2026-02-01' }))

    expect(screen.queryByRole('button', { name: 'Add visit' })).not.toBeInTheDocument()
  })

  it('adds only a Designer-approved addable visit in EDC', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url.endsWith('/addable')
      ? [{ id: 'definition-1', name: 'Optional follow-up', visit_type: 'unscheduled', definition_kind: 'visit' }]
      : [] } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'visit-new' } } as never)
    renderWithQueryClient(<VisitListPage subjectId="subject-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Add visit' }))
    expect(screen.queryByRole('button', { name: 'Add unscheduled visit' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Visit'), { target: { value: 'definition-1' } })
    fireEvent.change(screen.getByLabelText('Visit date'), { target: { value: '2026-02-02' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Add visit' }).at(-1)!)

    await waitFor(() => expect(post).toHaveBeenCalledWith('/subjects/subject-1/visits/addable', {
      visit_definition_id: 'definition-1',
      visit_date: '2026-02-02',
    }))
  })

  it('marks a user-added visit as added in error with a required reason', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url.endsWith('/addable')
      ? []
      : [{ id: 'visit-1', name: 'Unscheduled', visit_date: null, window_status: null, status: 'unscheduled', is_user_added: true }] } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'visit-1', status: 'added_in_error' } } as never)
    renderWithQueryClient(<VisitListPage subjectId="subject-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Added in error' }))
    fireEvent.click(screen.getByRole('button', { name: 'Mark added in error' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A reason is required.')

    fireEvent.change(screen.getByLabelText('Reason *'), { target: { value: 'Added for the wrong subject' } })
    fireEvent.click(screen.getByRole('button', { name: 'Mark added in error' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/visits/visit-1/mark-added-in-error', {
      reason: 'Added for the wrong subject',
    }))
  })
})
