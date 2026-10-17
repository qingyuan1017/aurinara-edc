import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataCleaningDashboardPage, StudyDashboardPage } from '@/features/dashboards'
import { SiteListPage } from '@/features/sites'
import { StudyListPage } from '@/features/studies'
import { SubjectListPage } from '@/features/subjects'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { useStudyContext } from '@/lib/study-context'
import { getRouteContext } from '@/lib/route-context'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, params, children, ...props }: { to: string; params?: Record<string, string>; children: React.ReactNode; [key: string]: unknown }) => {
    const href = Object.entries(params ?? {}).reduce(
      (path, [key, value]) => path.replace(`$${key}`, value),
      to,
    )
    return <a href={href} {...props}>{children}</a>
  },
}))

vi.mock('@/api/mutator', () => {
  const customInstance = async <T,>(config: { url?: string; params?: unknown }): Promise<T> => {
    const { api } = await import('@/lib/api')
    const url = String(config.url ?? '').replace(/^\/api\/v1/, '')
    const response = await api.get(url, { params: config.params })
    return response.data as T
  }

  return { customInstance, default: customInstance }
})

function renderWithQueryClient(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function setAuthenticatedPermissions() {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'user@example.com',
      first_name: 'Study',
      last_name: 'Operator',
      roles: [],
      permissions: [PERMISSIONS.STUDY_CREATE, PERMISSIONS.SITE_MANAGE, PERMISSIONS.SUBJECT_CREATE],
    },
    isAuthenticated: true,
  })
}

const dashboardMetrics = {
  subject_counts_by_status: { Enrolled: 1, Screening: 2 },
  total_form_instances: 4,
  submitted_form_instances: 3,
  open_query_count: 1,
}

const queryMetrics = {
  open_count: 1,
  answered_count: 2,
  closed_count: 3,
  cancelled_count: 0,
  overdue_count: 1,
  average_days_open: 2.5,
}

describe('dashboard and list page composition', () => {
  beforeEach(() => {
    setAuthenticatedPermissions()
    useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: 'site-1' })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
    useStudyContext.getState().clear()
  })

  it('renders dashboard loading, error, populated, and status-count states without changing API paths', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      const path = String(url)
      if (path.endsWith('/dashboard')) return { data: dashboardMetrics } as never
      if (path.endsWith('/query-metrics')) return { data: queryMetrics } as never
      if (path.endsWith('/sdv-progress')) return { data: { verified: 1, not_verified: 0 } } as never
      return { data: { reviewed: 1, not_reviewed: 0 } } as never
    })

    const { unmount } = renderWithQueryClient(<StudyDashboardPage studyId="study-1" />)
    expect(await screen.findByRole('status', { name: 'Subject status: Enrolled' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Subjects by status' })).toHaveAttribute('data-state', 'success')
    expect(screen.getAllByText('1 of 1 complete')).toHaveLength(2)
    expect(screen.getByText('2.5')).toBeInTheDocument()

    const calledPaths = vi.mocked(api.get).mock.calls.map(([url]) => String(url))
    expect(calledPaths).toEqual(expect.arrayContaining([
      '/studies/study-1/dashboard',
      '/studies/study-1/query-metrics',
      '/studies/study-1/sdv-progress',
      '/studies/study-1/review-progress',
      '/sites/site-1/dashboard',
    ]))
    unmount()

    vi.restoreAllMocks()
    vi.spyOn(api, 'get').mockRejectedValue(new Error('network failure'))
    renderWithQueryClient(<StudyDashboardPage studyId="study-1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load dashboard metrics.')
  })

  it('keeps the data-cleaning dashboard route presentation as the same query-backed page', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      const path = String(url)
      if (path.endsWith('/dashboard')) return { data: dashboardMetrics } as never
      if (path.endsWith('/query-metrics')) return { data: queryMetrics } as never
      if (path.endsWith('/sdv-progress')) return { data: { verified: 1, not_verified: 0 } } as never
      return { data: { reviewed: 1, not_reviewed: 0 } } as never
    })

    renderWithQueryClient(<DataCleaningDashboardPage studyId="study-1" />)
    expect(await screen.findByText('Data-cleaning progress')).toBeInTheDocument()
  })

  it('preserves study server ordering, canonical platform fields, pagination, and empty state', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{ id: 'study-1', study_code: 'A-001', title: 'First study', sponsor: 'Acme Pharma', status: 'Active', platform_managed: true, platform_revision: 7, platform_registry_status: 'active', created_at: '2026-01-01T00:00:00Z' }],
        page: 1,
        page_size: 20,
        total: 41,
      },
    } as never)

    renderWithQueryClient(<StudyListPage />)
    expect(await screen.findByText('41 total studies · server ordered')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Study status: Active' })).toBeInTheDocument()
    expect(screen.getByText('Acme Pharma')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create Study' })).not.toBeInTheDocument()
    expect(screen.getByText('Page 1 of 3 (41 total)')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/studies', { params: { page: 1, page_size: 20 } })

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/studies', { params: { page: 2, page_size: 20 } }))

    get.mockResolvedValue({ data: { items: [], page: 2, page_size: 20, total: 0 } } as never)
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(await screen.findByRole('heading', { name: 'No studies found.' })).toBeInTheDocument()
  })

  it('preserves site server metadata and status labels in the shared table shell', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{ id: 'site-1', site_number: '001', name: 'North Clinic', principal_investigator: 'Dr. Lee', country: 'US', status: 'Active' }],
        page: 1,
        page_size: 20,
        total: 1,
      },
    } as never)

    renderWithQueryClient(<SiteListPage studyId="study-1" />)
    expect(await screen.findByText('1 total sites · server ordered')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Site status: Active' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/studies/study-1/sites', { params: { page: 1, page_size: 20 } })
  })

  it('preserves subject search parameters, selected-site mutation context, and server totals', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (url) => ({
      data: String(url).endsWith('/enrollment-readiness')
        ? { study_id: 'study-1', ready: true, published_version_id: 'version-1', published_version_number: '1.0', authorized_active_site_count: 1, blockers: [] }
        : String(url).endsWith('/sites')
          ? { items: [{ id: 'site-1', site_number: '001', name: 'North Clinic', status: 'active' }], page: 1, page_size: 100, total: 1 }
          : {
              items: [{ id: 'subject-1', subject_number: 'SUBJ-001', site_id: 'site-1', site_name: 'North Clinic', status: 'Enrolled', current_phase_name: 'Treatment', current_phase_type: 'common', created_at: '2026-01-01T00:00:00Z' }],
              page: 1,
              page_size: 10,
              total: 1,
            },
    } as never))

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)
    expect(await screen.findByText('1 total subjects · server ordered')).toBeInTheDocument()
    expect(screen.getByText('North Clinic')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Subject status: Enrolled' })).toBeInTheDocument()
    expect(screen.getByText('Phase: Treatment')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/studies/study-1/subjects', { params: { page: 1, page_size: 10 } })

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search subjects' }), { target: { value: 'SUBJ' } })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/studies/study-1/subjects', { params: { page: 1, page_size: 10, search: 'SUBJ' } }))
  })

  it('shows the sanitized backend message when subject creation fails', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => ({
      data: String(url).endsWith('/enrollment-readiness')
        ? { study_id: 'study-1', ready: true, published_version_id: 'version-1', published_version_number: '1.0', authorized_active_site_count: 1, blockers: [] }
        : String(url).endsWith('/sites')
        ? { items: [{ id: 'site-1', site_number: '001', name: 'North Clinic' }], page: 1, page_size: 100, total: 1 }
        : { items: [], page: 1, page_size: 10, total: 0 },
    } as never))
    const config = { headers: {} } as InternalAxiosRequestConfig
    vi.spyOn(api, 'post').mockRejectedValue(new AxiosError(
      'Request failed',
      'ERR_BAD_REQUEST',
      config,
      undefined,
      {
        config,
        data: { error: { code: 'AuthenticationError', message: 'Missing authentication credentials' } },
        headers: {},
        status: 401,
        statusText: 'Unauthorized',
      },
    ))

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)
    const addSubject = await screen.findByRole('button', { name: 'Add subject' })
    await waitFor(() => expect(addSubject).toBeEnabled())
    fireEvent.click(addSubject)
    const siteSelect = await screen.findByRole('combobox', { name: 'Subject site' })
    await screen.findByRole('option', { name: '001 — North Clinic' })
    fireEvent.change(siteSelect, { target: { value: 'site-1' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Missing authentication credentials')
  })

  it('rejects stale cross-study context and posts only an explicitly authorized site', async () => {
    const user = userEvent.setup()
    useStudyContext.setState({ selectedStudyId: 'other-study', selectedSiteId: 'site-from-other-study' })
    vi.spyOn(api, 'get').mockImplementation(async (url) => ({
      data: String(url).endsWith('/enrollment-readiness')
        ? { study_id: 'study-1', ready: true, published_version_id: 'version-1', published_version_number: '1.0', authorized_active_site_count: 1, blockers: [] }
        : String(url).endsWith('/sites')
        ? { items: [{ id: 'site-current', site_number: '002', name: 'Current Study Site' }], page: 1, page_size: 100, total: 1 }
        : { items: [], page: 1, page_size: 10, total: 0 },
    } as never))
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'subject-1' } } as never)

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)
    const addSubject = await screen.findByRole('button', { name: 'Add subject' })
    await waitFor(() => expect(addSubject).toBeEnabled())
    fireEvent.click(addSubject)

    const siteSelect = await screen.findByRole('combobox', { name: 'Subject site' })
    await screen.findByRole('option', { name: '002 — Current Study Site' })
    expect(siteSelect).toHaveValue('')
    expect(screen.queryByRole('option', { name: 'site-from-other-study' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()

    await user.selectOptions(siteSelect, 'site-current')
    const subjectNumberInput = screen.getByLabelText('Subject number (optional)')
    fireEvent.change(subjectNumberInput, { target: { value: '123' } })
    expect(subjectNumberInput).toHaveValue('123')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/subjects', {
      site_id: 'site-current',
      subject_number: '123',
    }))
  })

  it('blocks subject creation until a study design is published', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => ({
      data: String(url).endsWith('/enrollment-readiness')
        ? {
            study_id: 'study-1',
            ready: false,
            published_version_id: null,
            published_version_number: null,
            authorized_active_site_count: 1,
            blockers: [{ code: 'NO_PUBLISHED_DESIGN', message: 'Publish a valid study design before enrolling subjects.' }],
          }
        : String(url).endsWith('/sites')
          ? { items: [{ id: 'site-1', site_number: '001', name: 'North Clinic', status: 'active' }], page: 1, page_size: 100, total: 1 }
          : { items: [], page: 1, page_size: 10, total: 0 },
    } as never))

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)

    expect(await screen.findByText('Subject enrollment is not ready.')).toBeInTheDocument()
    expect(screen.getByText('Publish a valid study design before enrolling subjects.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open study versioning' })).toHaveAttribute('href', '/studies/study-1/versions')
    expect(screen.getByRole('button', { name: 'Add subject' })).toBeDisabled()
  })

  it('requires the subject number and audit reason before removal', async () => {
    useAuthStore.setState({
      user: {
        id: 'user-1',
        email: 'manager@example.com',
        first_name: 'Data',
        last_name: 'Manager',
        roles: [],
        permissions: [PERMISSIONS.SUBJECT_DELETE, PERMISSIONS.SUBJECT_RESTORE],
      },
      isAuthenticated: true,
    })
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{
          id: 'subject-1',
          subject_number: 'SUBJ-001',
          site_id: 'site-1',
          site_name: 'North Clinic',
          status: 'Screening',
          created_at: '2026-01-01T00:00:00Z',
        }],
        page: 1,
        page_size: 10,
        total: 1,
      },
    } as never)
    const remove = vi.spyOn(api, 'delete').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Open actions for SUBJ-001' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove entered in error' }))
    expect(screen.getByRole('button', { name: 'Remove subject' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Type SUBJ-001 to confirm'), {
      target: { value: 'SUBJ-001' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: /Removal reason/ }), {
      target: { value: 'Duplicate subject created during setup' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Remove subject' }))

    await waitFor(() => expect(remove).toHaveBeenCalledWith('/subjects/subject-1', {
      data: {
        reason: 'Duplicate subject created during setup',
        subject_number_confirmation: 'SUBJ-001',
      },
    }))
  })

  it('offers inactive and discontinue from the subject-row actions menu', async () => {
    useAuthStore.setState({
      user: {
        id: 'user-1',
        email: 'manager@example.com',
        first_name: 'Data',
        last_name: 'Manager',
        roles: [],
        permissions: [PERMISSIONS.SUBJECT_UPDATE],
      },
      isAuthenticated: true,
    })
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{
          id: 'subject-1',
          subject_number: 'SUBJ-001',
          site_id: 'site-1',
          site_name: 'North Clinic',
          status: 'Enrolled',
          created_at: '2026-01-01T00:00:00Z',
        }],
        page: 1,
        page_size: 10,
        total: 1,
      },
    } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)
    expect(screen.queryByRole('button', { name: 'Mark inactive' })).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Open actions for SUBJ-001' }))
    expect(screen.getByRole('menuitem', { name: 'Discontinue' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Mark inactive' }))

    fireEvent.change(screen.getByRole('textbox', { name: /Reason for change/ }), {
      target: { value: 'Subject is temporarily inactive' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Mark inactive' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/subjects/subject-1/deactivate', {
      reason: 'Subject is temporarily inactive',
    }))
  })

  it('keeps dashboard deep-link breadcrumbs and search state intact', () => {
    const context = getRouteContext({ pathname: '/studies/study-1/dashboard', search: { tab: 'quality', page: 2 } })
    expect(context.breadcrumbs.map((item) => item.label)).toEqual(['Studies', 'Study study-1', 'Dashboard'])
    expect(context.breadcrumbs[1].search?.({ ignored: true })).toEqual({ tab: 'quality', page: 2 })
    expect(context.search).toEqual({ tab: 'quality', page: 2 })
  })
})
