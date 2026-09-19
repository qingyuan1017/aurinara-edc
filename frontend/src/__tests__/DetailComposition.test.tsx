import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuditViewerPage, UserListPage } from '@/features/admin'
import { StudyDetailPage } from '@/features/studies/StudyDetailPage'
import { SubjectCasebookPage } from '@/features/subjects/SubjectCasebookPage'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function authenticate(permissions: string[]) {
  useAuthStore.setState({
    user: { id: 'user-1', email: 'operator@example.com', first_name: 'Study', last_name: 'Operator', roles: [], permissions },
    isAuthenticated: true,
  })
}

describe('detail, casebook, audit, and notification composition', () => {
  beforeEach(() => authenticate([PERMISSIONS.STUDY_CONFIGURE, PERMISSIONS.VERSION_PUBLISH, PERMISSIONS.USER_CREATE, PERMISSIONS.USER_DEACTIVATE]))
  afterEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('preserves study detail and version contracts while using detail cards and tabs', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url) === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'A-001', title: 'A Study', phase: 'II', status: 'Draft', description: 'Study description', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' } }) as never
      return Promise.resolve({ data: [{ id: 'version-1', version_number: '1.0', status: 'draft', created_at: '2026-01-01T00:00:00Z' }] }) as never
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<StudyDetailPage studyId="study-1" />)

    expect(await screen.findByRole('heading', { name: 'A Study' })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: /authoritative module: EDC; ownership: Authoritative · Read only/ })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/studies/study-1')
    expect(get).toHaveBeenCalledWith('/studies/study-1/versions')

    fireEvent.click(screen.getByRole('tab', { name: 'Versions' }))
    expect(await screen.findByText('v1.0')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/versions/version-1/publish'))
  })

  it('preserves casebook routes and clinical status ownership in the shared composition', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: {
      subject_id: 'subject-1', subject_number: 'SUBJ-001', status: 'Enrolled', visits: [{ visit_instance_id: 'visit-1', visit_definition_id: 'baseline', name: 'Baseline', status: 'Scheduled', forms: [{ form_instance_id: 'form-1', form_definition_id: 'vitals', name: 'Vitals', status: 'Submitted' }] }],
    } } as never)

    renderWithQueryClient(<SubjectCasebookPage subjectId="subject-1" />)

    expect(await screen.findByRole('heading', { name: 'Subject SUBJ-001' })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: /authoritative module: EDC; ownership: Authoritative · Read only/ })).toBeInTheDocument()
    expect(screen.getByText('1/1 forms complete')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show forms for Baseline' }))
    expect(screen.getByRole('link', { name: /Vitals/ })).toHaveAttribute('href', '/subjects/subject-1/forms/form-1')
    expect(get).toHaveBeenCalledWith('/subjects/subject-1/casebook')
  })

  it('preserves audit filtering parameters, server ordering, and event metadata', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: {
      items: [{ id: 'event-1', actor_email: 'actor@example.com', action: 'update', entity_type: 'study', entity_id: 'entity-12345678', timestamp: '2026-01-01T10:00:00Z', request_id: 'request-1' }],
      page: 1, page_size: 50, total: 1,
    } } as never)

    renderWithQueryClient(<AuditViewerPage />)

    expect(await screen.findByText('actor@example.com')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Audit action: update' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/audit-events', { params: { page: 1, page_size: 50 } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Search' }), { target: { value: 'actor' } })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/audit-events', { params: { page: 1, page_size: 50, search: 'actor' } }))
  })

  it('preserves permission affordances and invite payload in the user detail table', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation((url) => {
      if (String(url) === '/roles') return Promise.resolve({ data: { items: [{ id: 'role-1', name: 'Coordinator' }] } }) as never
      return Promise.resolve({ data: { items: [{ id: 'user-1', email: 'user@example.com', first_name: 'A', last_name: 'User', status: 'active', created_at: '2026-01-01T00:00:00Z' }], page: 1, page_size: 20, total: 1 } }) as never
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<UserListPage />)

    expect(await screen.findByText('user@example.com')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Invite User' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Deactivate' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Invite User' }))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'new@example.com' } })
    fireEvent.change(screen.getByLabelText('First Name'), { target: { value: 'New' } })
    fireEvent.change(screen.getByLabelText('Last Name'), { target: { value: 'User' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'role-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Invite' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/auth/invite', { email: 'new@example.com', role_id: 'role-1' }))
    expect(get).toHaveBeenCalledWith('/users', { params: { page: 1, page_size: 20 } })
  })
})
