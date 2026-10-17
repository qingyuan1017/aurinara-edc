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
    localStorage.clear()
    window.history.replaceState({}, '', window.location.pathname)
    useAuthStore.setState({
      user: { id: 'user-1', email: 'dm@example.com', first_name: 'Data', last_name: 'Manager', roles: [], permissions: ['lock.manage', 'file.upload', 'query.respond', 'query.close', 'query.reopen', 'sdv.manage', 'review.manage', 'designer.editcheck.configure'] },
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

  it('creates a query for a specific saved field value from the data-entry page', async () => {
    useAuthStore.setState((state) => ({
      ...state,
      user: state.user ? { ...state.user, permissions: [...state.user.permissions, 'query.create'] } : null,
    }))
    const get = vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({
      data: url === '/studies/study-1/queries/assignment-roles'
        ? ['Site Coordinator', 'Data Manager']
        : url === '/form-instances/form-1/fields/field-def-1/queries'
          ? { items: [{ id: 'query-old', text: 'Earlier clarification', status: 'Closed', assigned_role: 'Site Coordinator', created_at: '2026-01-01T10:00:00Z' }], page: 1, page_size: 100, total: 1 }
          : {
        id: 'form-1', study_id: 'study-1', form_definition_id: 'def-1', form_name: 'Vitals', subject_id: 'subject-1',
        subject_number: 'SUBJ-001', visit_name: 'Baseline', status: 'Submitted', data_entry_status: 'Submitted', is_frozen: false, is_locked: false,
        sections: [{ id: 'section-1', title: 'Measurements', order: 1, fields: [{ id: 'field-def-1', name: 'weight', label: 'Weight', control_type: 'text', is_required: false }] }],
        data: { 'field-def-1': '70 kg' },
        field_values: [{ id: 'field-value-1', field_definition_id: 'field-def-1', value: '70 kg' }],
      },
    } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'query-1' } } as never)

    renderWithQueryClient(<FormEntryPage formInstanceId="form-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Add query for Weight' }))
    expect(screen.getByRole('dialog', { name: 'Add query for Weight' })).toBeInTheDocument()
    expect(screen.getByText('70 kg')).toBeInTheDocument()
    expect(await screen.findByText('Earlier clarification')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'query status: Closed' })).toBeInTheDocument()
    expect(await screen.findByRole('option', { name: 'Site Coordinator' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/studies/study-1/queries/assignment-roles', {
      params: { target_type: 'Form_Instance', target_id: 'form-1' },
    })
    fireEvent.change(screen.getByLabelText('Assigned role (optional)'), { target: { value: 'Site Coordinator' } })
    fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'Please confirm this measurement.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create query' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/fields/field-def-1/queries', {
      text: 'Please confirm this measurement.',
      assigned_role: 'Site Coordinator',
    }))
    expect(await screen.findByText('Query created for Weight.')).toBeInTheDocument()
  })

  it('creates a field-specific query for an unanswered checkbox', async () => {
    useAuthStore.setState((state) => ({
      ...state,
      user: state.user ? { ...state.user, permissions: [...state.user.permissions, 'query.create'] } : null,
    }))
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({
      data: url === '/studies/study-1/queries/assignment-roles'
        ? ['Site Coordinator']
        : url === '/form-instances/form-1/fields/field-def-checkbox/queries'
          ? { items: [], page: 1, page_size: 100, total: 0 }
          : {
        id: 'form-1', study_id: 'study-1', form_definition_id: 'def-1', form_name: 'Eligibility', subject_id: 'subject-1',
        subject_number: 'SUBJ-001', visit_name: 'Screening', status: 'In Progress', data_entry_status: 'In Progress', is_frozen: false, is_locked: false,
        sections: [{ id: 'section-1', title: 'Eligibility', order: 1, fields: [{ id: 'field-def-checkbox', label: 'Eligibility confirmed', control_type: 'checkbox', is_required: false }] }],
        data: {},
        field_values: [],
      },
    } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'query-2' } } as never)

    renderWithQueryClient(<FormEntryPage formInstanceId="form-1" />)

    const addQuery = await screen.findByRole('button', { name: 'Add query for Eligibility confirmed' })
    expect(addQuery).toBeEnabled()
    fireEvent.click(addQuery)
    expect(screen.getByText('No value entered')).toBeInTheDocument()
    expect(await screen.findByText('No previous queries for this field.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Describe the issue'), { target: { value: 'Please confirm eligibility.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create query' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/fields/field-def-checkbox/queries', {
      text: 'Please confirm eligibility.',
      assigned_role: null,
    }))
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
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [{ form_instance_id: 'form-1', subject_id: 'subject-1', subject_number: 'SUBJ-001', site_name: 'Site 1', visit_name: 'Baseline', form_name: 'Vitals', workflow: 'sdv', workflow_status: 'Not Verified', status: { data_entry: 'Submitted', review: 'Not Reviewed', sdv: 'Not Verified', sdr: 'Not Selected', active_query_count: 0 } }], page: 1, page_size: 100, total: 1 } } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<SDVWorklistPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Mark verified' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/sdv'))
    expect(screen.getByRole('button', { name: 'Clear SDV' })).toBeInTheDocument()
  })

  it('marks a clinical review worklist form reviewed and supports clearing it', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [{ form_instance_id: 'form-1', subject_id: 'subject-1', subject_number: 'SUBJ-001', site_name: 'Site 1', visit_name: 'Baseline', form_name: 'Vitals', workflow: 'review', workflow_status: 'Not Reviewed', status: { data_entry: 'Submitted', review: 'Not Reviewed', sdv: 'Not Verified', sdr: 'Not Selected', active_query_count: 0 } }], page: 1, page_size: 100, total: 1 } } as never)
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
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url === '/studies/study-1/versions'
      ? [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }]
      : [] } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {
      id: 'check-1', name: 'Required weight', description: null, rule_json: { field: 'weight', operator: 'not_null' }, severity: 'warning', is_active: true, created_at: '2026-01-01T10:00:00Z',
    } } as never)

    renderWithQueryClient(<EditCheckBuilderPage studyId="study-1" />)
    const name = await screen.findByPlaceholderText('AE start before end')
    fireEvent.change(name, { target: { value: 'Required weight' } })
    fireEvent.click(screen.getByRole('button', { name: 'Advanced JSON' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Rule definition' }), { target: { value: '{invalid' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save check' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rule JSON must be valid JSON.')
    expect(post).not.toHaveBeenCalled()

    fireEvent.change(screen.getByRole('textbox', { name: 'Rule definition' }), { target: { value: '{"field":"weight","operator":"not_null"}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save check' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/designer/studies/study-1/edit-checks', {
      name: 'Required weight', description: null, severity: 'warning', rule_json: { field: 'weight', operator: 'not_null' }, is_active: true,
    }, { params: { study_version_id: 'ver-draft' } }))
  })

  it('deletes a selected draft edit check after confirmation', async () => {
    const checks = [{
      id: 'check-1', name: 'Required weight', description: null,
      rule_json: { field: 'weight', operator: 'not_null' }, severity: 'warning',
      is_active: true, created_at: '2026-01-01T10:00:00Z',
    }]
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url === '/studies/study-1/versions'
      ? [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }]
      : checks } as never))
    const remove = vi.spyOn(api, 'delete').mockResolvedValue({ data: undefined } as never)

    renderWithQueryClient(<EditCheckBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /Required weight/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete check' }))
    expect(screen.getByRole('dialog', { name: 'Delete edit check?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))

    await waitFor(() => expect(remove).toHaveBeenCalledWith('/designer/edit-checks/check-1'))
    expect(await screen.findByText('Edit check deleted.')).toBeInTheDocument()
  })

  it('tests and marks an imported edit check as retested with a review note', async () => {
    const checks = [{
      id: 'check-1', name: 'Imported weight check', description: null,
      rule_json: { field: 'weight', operator: 'not_null' }, severity: 'query',
      is_active: true, needs_retesting: true, retesting_reason: 'Converted from Rave ALS',
      created_at: '2026-01-01T10:00:00Z',
    }]
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url === '/studies/study-1/versions'
      ? [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }]
      : checks } as never))
    const post = vi.spyOn(api, 'post').mockImplementation((url) => Promise.resolve({ data: url.endsWith('/test')
      ? { passed: false, matched: true }
      : { edit_check_id: 'check-1', passed: false, matched: true, needs_retesting: false } } as never))

    renderWithQueryClient(<EditCheckBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /Imported weight check/ }))
    expect(screen.getByText('Retest required before publication.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Test rule' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/designer/edit-checks/check-1/test', { sample_data: {} }))

    fireEvent.change(screen.getByLabelText('Retest review note'), {
      target: { value: 'Verified the converted condition and query action.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Mark as retested' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/designer/edit-checks/check-1/retest', {
      sample_data: {},
      expected_matched: true,
      review_note: 'Verified the converted condition and query action.',
    }))
    expect(await screen.findByText(/recorded in the audit trail/)).toBeInTheDocument()
  })

  it('bulk marks all pending edit checks retested after an explicit attestation', async () => {
    const checks = [1, 2].map((index) => ({
      id: `check-${index}`, name: `Imported check ${index}`, description: null,
      rule_json: { field: 'weight', operator: 'not_null' }, severity: 'query',
      is_active: true, needs_retesting: true, retesting_reason: 'Converted from Rave ALS',
      created_at: '2026-01-01T10:00:00Z',
    }))
    vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: url === '/studies/study-1/versions'
      ? [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }]
      : checks } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {
      study_version_id: 'ver-draft', reviewed_count: 2, remaining_count: 0,
    } } as never)

    renderWithQueryClient(<EditCheckBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Retest all (2)' }))
    expect(screen.getByRole('dialog', { name: 'Mark all edit checks as retested?' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/Bulk review note/), {
      target: { value: 'Reviewed both imported checks against the approved specification.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Mark all 2 retested' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/designer/studies/study-1/edit-checks/retest-all',
      {
        review_note: 'Reviewed both imported checks against the approved specification.',
        acknowledge_without_individual_samples: true,
      },
      { params: { study_version_id: 'ver-draft' } },
    ))
    expect(await screen.findByText(/2 edit checks marked as retested/)).toBeInTheDocument()
  })
})
