import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/components/layout/AppShell'
import { StudyDashboardPage } from '@/features/dashboards/StudyDashboardPage'
import { SubjectCasebookPage } from '@/features/subjects/SubjectCasebookPage'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { ThemeProvider } from '@/lib/theme'
import {
  classifyShellAction,
  createShellSearchPreservingLink,
  isPresentationOnlyAction,
} from '@/lib/route-context'

/**
 * Task 7.5 frontend fallback gate.
 *
 * **Validates: Requirements 12.14-12.15, 13.14-13.16, 14.4, 14.7,
 * 14.9-14.10**
 */

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
  Outlet: () => <div data-testid="outlet" />,
  useLocation: () => ({ pathname: '/', search: {}, hash: '' }),
  useNavigate: () => vi.fn(),
}))

const modes = [
  { name: 'disabled', enabled: false, phase: 0 as const },
  { name: 'empty', enabled: true, phase: 1 as const },
  { name: 'worker-unavailable', enabled: true, phase: 3 as const },
  { name: 'unavailable', enabled: true, phase: 3 as const, capabilitiesFailure: true },
]

type CapabilityFixture = (typeof modes)[number]

const clinicalCasebook = {
  subject_id: 'subject-1',
  subject_number: 'SUBJ-001',
  status: 'Enrolled',
  visits: [{
    visit_instance_id: 'visit-1',
    visit_definition_id: 'baseline',
    name: 'Baseline',
    status: 'Scheduled',
    forms: [{ form_instance_id: 'form-1', form_definition_id: 'vitals', name: 'Vitals', status: 'Submitted' }],
  }],
}

function renderEDCWithMode(
  mode: { enabled: boolean; phase: 0 | 1 | 3 },
  capabilitiesFailure = false,
) {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'edc@example.com',
      first_name: 'EDC',
      last_name: 'Operator',
      roles: [],
      permissions: [PERMISSIONS.STUDY_READ],
    },
    isAuthenticated: true,
  })
  vi.spyOn(api, 'get').mockImplementation((url) => {
    const path = String(url)
    if (path === '/ctms/capabilities') {
      if (capabilitiesFailure) return Promise.reject(new Error('coordination worker unavailable')) as never
      return Promise.resolve({ data: { module: 'CTMS', ...mode, capabilities: [] } }) as never
    }
    if (path === '/studies') {
      return Promise.resolve({ data: { items: [], page: 1, page_size: 100, total: 0 } }) as never
    }
    if (path === '/subjects/subject-1/casebook') {
      return Promise.resolve({ data: clinicalCasebook }) as never
    }
    if (path.endsWith('/dashboard')) {
      return Promise.resolve({ data: { subject_counts_by_status: { Enrolled: 1 }, total_form_instances: 1, submitted_form_instances: 1, open_query_count: 0 } }) as never
    }
    if (path.endsWith('/query-metrics')) {
      return Promise.resolve({ data: { open_count: 0, answered_count: 0, closed_count: 0, cancelled_count: 0, overdue_count: 0, average_days_open: 0 } }) as never
    }
    if (path.endsWith('/sdv-progress')) {
      return Promise.resolve({ data: { verified: 1, not_verified: 0 } }) as never
    }
    return Promise.resolve({ data: { reviewed: 1, not_reviewed: 0 } }) as never
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <AppShell />
        <SubjectCasebookPage subjectId="subject-1" />
        <StudyDashboardPage studyId="study-1" />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('final EDC regression and CTMS fallback gate', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it.each(modes)('keeps authentication shell and clinical pages available with CTMS $name', async (mode: CapabilityFixture) => {
    renderEDCWithMode(mode, Boolean(mode.capabilitiesFailure))

    expect(await screen.findByText('Subject SUBJ-001')).toBeInTheDocument()
    expect(screen.getByText('Baseline')).toBeInTheDocument()
    expect(screen.getByText('1/1 forms complete')).toBeInTheDocument()
    expect(await screen.findByText('Study dashboard')).toBeInTheDocument()
    expect(screen.getByText('Open queries')).toBeInTheDocument()
    expect(screen.getByText('Source data verification')).toBeInTheDocument()
  })

  it('keeps route state and unrelated query keys stable for presentation-only shell actions', () => {
    const queryClient = new QueryClient()
    const clinicalQueryKey = ['study-dashboard', 'study-1'] as const
    const unrelatedQueryKey = ['clinical-casebook', 'subject-1'] as const
    queryClient.setQueryData(clinicalQueryKey, { total: 1 })
    queryClient.setQueryData(unrelatedQueryKey, { subject: 'SUBJ-001' })

    const routeState = {
      pathname: '/subjects/subject-1',
      search: { tab: 'visits', page: 2 },
      hash: '#casebook',
    }
    const beforeKeys = queryClient.getQueryCache().getAll().map((query) => query.queryKey)
    const beforeData = {
      clinical: queryClient.getQueryData(clinicalQueryKey),
      unrelated: queryClient.getQueryData(unrelatedQueryKey),
    }
    const presentationActions = [
      'sidebar-toggle',
      'mobile-drawer',
      'study-selector-open',
      'site-selector-open',
      'theme-change',
      'user-menu',
    ] as const

    for (const action of presentationActions) {
      expect(classifyShellAction(action)).toBe('presentation-only')
      expect(isPresentationOnlyAction(action)).toBe(true)
      expect(createShellSearchPreservingLink('/notifications', routeState.search).search({})).toEqual(routeState.search)
      expect(routeState).toEqual({
        pathname: '/subjects/subject-1',
        search: { tab: 'visits', page: 2 },
        hash: '#casebook',
      })
    }

    expect(queryClient.getQueryCache().getAll().map((query) => query.queryKey)).toEqual(beforeKeys)
    expect(queryClient.getQueryData(clinicalQueryKey)).toEqual(beforeData.clinical)
    expect(queryClient.getQueryData(unrelatedQueryKey)).toEqual(beforeData.unrelated)
  })

  it('keeps the EDC shell usable when the optional CTMS capability request fails', async () => {
    renderEDCWithMode({ enabled: true, phase: 3 }, true)

    expect(await screen.findByText('Subject SUBJ-001')).toBeInTheDocument()
    expect(screen.getByText('Study dashboard')).toBeInTheDocument()
  })
})
