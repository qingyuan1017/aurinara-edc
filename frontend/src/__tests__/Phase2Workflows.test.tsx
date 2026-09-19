import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { FileUpload } from '@/features/forms/components/FileUpload'
import { FormEntryPage } from '@/features/forms/FormEntryPage'
import { LockControls } from '@/features/forms/components/LockControls'
import { QueryDetailPage } from '@/features/queries/QueryDetailPage'
import { EditCheckBuilderPage } from '@/features/edit-checks/EditCheckBuilderPage'
import { NotificationsPage } from '@/features/notifications/NotificationsPage'
import { ReviewWorklistPage, SDVWorklistPage } from '@/features/quality'

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('Phase 2 workflow controls', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({
      user: { id: 'user-1', email: 'dm@example.com', first_name: 'Data', last_name: 'Manager', roles: [], permissions: ['lock.manage', 'file.upload', 'query.respond', 'query.close', 'query.reopen', 'sdv.manage', 'review.manage', 'editcheck.configure'] },
      isAuthenticated: true,
    })
  })

  it('calls the audited form lock endpoint and reports the disabled state', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const onChanged = vi.fn()
    renderWithQueryClient(<LockControls formInstanceId="form-1" isFrozen={false} isLocked={false} onChanged={onChanged} />)

    fireEvent.click(screen.getByRole('button', { name: 'Lock' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/lock', undefined))
    expect(onChanged).toHaveBeenCalledWith({ isFrozen: false, isLocked: true })
  })

  it('requires an unlock reason before removing a lock', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderWithQueryClient(<LockControls formInstanceId="form-1" isFrozen={false} isLocked={true} onChanged={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(screen.getByRole('alert')).toHaveTextContent('A reason is required')
    expect(post).not.toHaveBeenCalled()

    fireEvent.change(screen.getByPlaceholderText(/Document why/), { target: { value: 'Correction approved by data management' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/unlock', { reason: 'Correction approved by data management' }))
  })

  it('disables uploads when the parent form is frozen or locked', () => {
    renderWithQueryClient(<FileUpload objectType="form_instance" objectId="form-1" disabled />)
    expect(screen.getByRole('button', { name: 'Upload file' })).toBeDisabled()
    expect(screen.getByText(/Uploads are disabled/)).toBeInTheDocument()
  })

  it.each([
    { status: 'Frozen', is_frozen: true, is_locked: false, message: 'This form is frozen and cannot be edited.' },
    { status: 'Locked', is_frozen: false, is_locked: true, message: 'This form is locked and cannot be edited.' },
  ])('disables all form controls and file upload for a $status form', async ({ status, is_frozen, is_locked, message }) => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        id: 'form-1', form_definition_id: 'def-1', form_name: 'Vitals', subject_id: 'subject-1',
        subject_number: 'SUBJ-001', visit_name: 'Baseline', status, is_frozen, is_locked,
        sections: [{ id: 'section-1', title: 'Measurements', order: 1, fields: [{ id: 'weight', name: 'weight', label: 'Weight', control_type: 'text', is_required: false }] }],
        data: { weight: '70' },
      },
    } as never)

    renderWithQueryClient(<FormEntryPage formInstanceId="form-1" />)

    expect(await screen.findByLabelText('Weight')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Upload file' })).toBeDisabled()
    expect(screen.getByText(message)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save Draft' })).not.toBeInTheDocument()
  })

  it('renders a query thread and posts a response and close action', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: {
      id: 'query-1', target_type: 'Form_Instance', target_id: 'form-1', text: 'Confirm the visit date.',
      query_type: 'manual', assigned_role: 'Site Coordinator', status: 'Open', created_at: '2026-01-01T10:00:00Z',
      messages: [{ id: 'message-1', author_id: 'user-1', message: 'Please confirm the source document date.', created_at: '2026-01-01T11:00:00Z' }],
    } } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<QueryDetailPage queryId="query-1" />)

    expect(await screen.findByText('Please confirm the source document date.')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Describe the data clarification/), { target: { value: 'The source document confirms 2026-01-01.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send response' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/queries/query-1/respond', { message: 'The source document confirms 2026-01-01.' }))

    fireEvent.click(screen.getByRole('button', { name: 'Close query' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/queries/query-1/close', undefined))
  })

  it('marks an SDV worklist form verified and refreshes its workflow state', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url).endsWith('/sdv-progress')) return Promise.resolve({ data: { verified: 0, not_verified: 1 } }) as never
      if (String(url).includes('/subjects/')) return Promise.resolve({ data: { visits: [{ name: 'Baseline', forms: [{ form_instance_id: 'form-1', name: 'Vitals', status: 'Submitted' }] }] } }) as never
      return Promise.resolve({ data: { items: [{ id: 'subject-1', subject_number: 'SUBJ-001', site_id: 'site-1', status: 'Enrolled' }], page: 1, page_size: 100, total: 1 } }) as never
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<SDVWorklistPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Mark verified' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/sdv'))
    expect(screen.getByRole('button', { name: 'Clear SDV' })).toBeInTheDocument()
  })

  it('marks a clinical review worklist form reviewed and supports clearing it', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url).endsWith('/review-progress')) return Promise.resolve({ data: { reviewed: 0, not_reviewed: 1 } }) as never
      if (String(url).includes('/subjects/')) return Promise.resolve({ data: { visits: [{ name: 'Baseline', forms: [{ form_instance_id: 'form-1', name: 'Vitals', status: 'Submitted' }] }] } }) as never
      return Promise.resolve({ data: { items: [{ id: 'subject-1', subject_number: 'SUBJ-001', site_id: 'site-1', status: 'Enrolled' }], page: 1, page_size: 100, total: 1 } }) as never
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<ReviewWorklistPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Mark reviewed' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/review'))
    fireEvent.click(screen.getByRole('button', { name: 'Clear review' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/unreview'))
  })

  it('marks an unread notification as read and archives it through the workflow API', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [{ id: 'notification-1', type: 'QUERY_ASSIGNED', payload_json: { message: 'A query needs your response.' }, status: 'Unread', created_at: '2026-01-01T10:00:00Z' }], page: 1, page_size: 50, total: 1 } } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<NotificationsPage />)

    expect(await screen.findByText('A query needs your response.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/notifications/notification-1/read'))
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/notifications/notification-1/archive'))
  })

  it('validates edit-check JSON before saving and sends a valid rule to the API', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: [] } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {
      id: 'check-1', name: 'Required weight', description: null, rule_json: { field: 'weight', operator: 'not_null' }, severity: 'warning', is_active: true, created_at: '2026-01-01T10:00:00Z',
    } } as never)

    renderWithQueryClient(<EditCheckBuilderPage studyId="study-1" />)
    const name = screen.getByPlaceholderText('AE start before end')
    fireEvent.change(name, { target: { value: 'Required weight' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Rule definition' }), { target: { value: '{invalid' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save check' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rule JSON must be valid JSON.')
    expect(post).not.toHaveBeenCalled()

    fireEvent.change(screen.getByRole('textbox', { name: 'Rule definition' }), { target: { value: '{"field":"weight","operator":"not_null"}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save check' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/edit-checks', {
      name: 'Required weight', description: null, severity: 'warning', rule_json: { field: 'weight', operator: 'not_null' }, is_active: true,
    }))
  })
})
