import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { UserListPage } from '@/features/admin'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useStudyContext } from '@/lib/study-context'
import { PERMISSIONS } from '@/lib/permissions'

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function authenticate(permissions: string[]) {
  useAuthStore.setState({
    user: { id: 'admin-1', email: 'admin@example.com', first_name: 'Ad', last_name: 'Min', roles: [], permissions },
    isAuthenticated: true,
  })
}

const roles = {
  items: [
    { id: 'role-study', name: 'PI', scope_level: 'study' },
    { id: 'role-site', name: 'CRA', scope_level: 'site' },
  ],
  page: 1,
  page_size: 100,
  total: 2,
}
const studies = {
  items: [{ id: 'study-1', study_code: 'A-001', title: 'A' }],
  page: 1,
  page_size: 100,
  total: 1,
}
const sites = {
  items: [{ id: 'site-1', site_number: 'S1', name: 'Site One' }],
  page: 1,
  page_size: 100,
  total: 1,
}
const users = {
  items: [{ id: 'user-1', email: 'user@example.com', first_name: 'A', last_name: 'User', status: 'active', created_at: '2026-01-01T00:00:00Z' }],
  page: 1,
  page_size: 20,
  total: 1,
}

function mockGet() {
  return vi.spyOn(api, 'get').mockImplementation((url) => {
    const path = String(url)
    if (path === '/roles') return Promise.resolve({ data: roles }) as never
    if (path === '/studies') return Promise.resolve({ data: studies }) as never
    if (path === '/studies/study-1/sites') return Promise.resolve({ data: sites }) as never
    return Promise.resolve({ data: users }) as never
  })
}

async function openAssignDialog() {
  renderWithQueryClient(<UserListPage />)
  expect(await screen.findByText('user@example.com')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Assign roles' }))
  return within(await screen.findByRole('dialog'))
}

describe('AssignRolesDialog', () => {
  beforeEach(() => {
    authenticate([PERMISSIONS.USER_LIST, PERMISSIONS.USER_ASSIGN, PERMISSIONS.ROLE_LIST])
    useStudyContext.setState({ selectedStudyId: null, selectedSiteId: null })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
    useStudyContext.setState({ selectedStudyId: null, selectedSiteId: null })
  })

  it('shows the Site select only after selecting a site-scoped role', async () => {
    mockGet()
    const dialog = await openAssignDialog()

    expect(dialog.getByText(/Current role assignments aren't returned/)).toBeInTheDocument()
    expect(dialog.queryByLabelText('Site')).not.toBeInTheDocument()

    fireEvent.click(await dialog.findByLabelText(/PI/))
    expect(dialog.queryByLabelText('Site')).not.toBeInTheDocument()

    fireEvent.click(dialog.getByLabelText(/CRA/))
    expect(await dialog.findByLabelText('Site')).toBeInTheDocument()
  })

  it('submits a study-scoped role without site_id', async () => {
    mockGet()
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const dialog = await openAssignDialog()

    fireEvent.change(await dialog.findByLabelText('Study'), { target: { value: 'study-1' } })
    fireEvent.click(dialog.getByLabelText(/PI/))
    fireEvent.click(dialog.getByRole('button', { name: 'Assign roles' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/studies/study-1/users/user-1/assign', [
        { role_id: 'role-study', study_id: 'study-1' },
      ]),
    )
  })

  it('submits a site-scoped role with site_id included', async () => {
    mockGet()
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const dialog = await openAssignDialog()

    fireEvent.change(await dialog.findByLabelText('Study'), { target: { value: 'study-1' } })
    fireEvent.click(dialog.getByLabelText(/CRA/))
    await dialog.findByLabelText('Site')
    await dialog.findByRole('option', { name: /Site One/ })
    fireEvent.change(dialog.getByLabelText('Site'), { target: { value: 'site-1' } })
    fireEvent.click(dialog.getByRole('button', { name: 'Assign roles' }))

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/studies/study-1/users/user-1/assign', [
        { role_id: 'role-site', study_id: 'study-1', site_id: 'site-1' },
      ]),
    )
  })

  it('surfaces the API detail message on error', async () => {
    mockGet()
    vi.spyOn(api, 'post').mockRejectedValue({ response: { data: { detail: 'Forbidden' } } } as never)
    const dialog = await openAssignDialog()

    fireEvent.change(await dialog.findByLabelText('Study'), { target: { value: 'study-1' } })
    fireEvent.click(dialog.getByLabelText(/PI/))
    fireEvent.click(dialog.getByRole('button', { name: 'Assign roles' }))

    expect(await dialog.findByRole('alert')).toHaveTextContent('Forbidden')
  })

  it('defaults the study select to the selected study context', async () => {
    useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: null })
    mockGet()
    const dialog = await openAssignDialog()

    expect(await dialog.findByLabelText('Study')).toHaveValue('study-1')
  })

  it('hides the per-row Assign roles action without the user.assign permission', async () => {
    authenticate([PERMISSIONS.USER_LIST, PERMISSIONS.ROLE_LIST])
    mockGet()
    renderWithQueryClient(<UserListPage />)

    expect(await screen.findByText('user@example.com')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Assign roles' })).not.toBeInTheDocument()
  })
})
