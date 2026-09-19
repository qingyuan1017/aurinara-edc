import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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

  it('preserves study server ordering, totals, pagination, permission action, and empty state', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{ id: 'study-1', study_code: 'A-001', title: 'First study', phase: 'II', status: 'Active', created_at: '2026-01-01T00:00:00Z' }],
        page: 1,
        page_size: 20,
        total: 41,
      },
    } as never)

    renderWithQueryClient(<StudyListPage />)
    expect(await screen.findByText('41 total studies · server ordered')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Study status: Active' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Study' })).toBeInTheDocument()
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
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{ id: 'subject-1', subject_number: 'SUBJ-001', site_id: 'site-1', site_name: 'North Clinic', status: 'Enrolled', created_at: '2026-01-01T00:00:00Z' }],
        page: 1,
        page_size: 10,
        total: 1,
      },
    } as never)

    renderWithQueryClient(<SubjectListPage studyId="study-1" />)
    expect(await screen.findByText('1 total subjects · server ordered')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Subject status: Enrolled' })).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/studies/study-1/subjects', { params: { page: 1, page_size: 10 } })

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search subjects' }), { target: { value: 'SUBJ' } })
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/studies/study-1/subjects', { params: { page: 1, page_size: 10, search: 'SUBJ' } }))
  })

  it('keeps dashboard deep-link breadcrumbs and search state intact', () => {
    const context = getRouteContext({ pathname: '/studies/study-1/dashboard', search: { tab: 'quality', page: 2 } })
    expect(context.breadcrumbs.map((item) => item.label)).toEqual(['Studies', 'Study study-1', 'Dashboard'])
    expect(context.breadcrumbs[1].search?.({ ignored: true })).toEqual({ tab: 'quality', page: 2 })
    expect(context.search).toEqual({ tab: 'quality', page: 2 })
  })
})
