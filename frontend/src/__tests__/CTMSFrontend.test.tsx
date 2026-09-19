import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { CTMSWorkspacePage } from '@/features/ctms/WorkspacePage'
import {
  GuardedCTMSAction,
  MonitoringActivitySummary,
  ProjectionFreshness,
} from '@/features/ctms/components'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
}))

type ResponseFactory = (path: string) => unknown

const enabledManifest = {
  module: 'CTMS' as const,
  enabled: true,
  phase: 3 as const,
  capabilities: ['operational_study', 'monitoring', 'exports'],
}

const defaultList = { items: [], page: 1, page_size: 20, total: 0 }

function setUser(permissions: string[]) {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'user@example.com',
      first_name: 'Study',
      last_name: 'User',
      roles: [{ role_name: 'CTMS_Viewer' }],
      permissions,
    },
    isAuthenticated: true,
  })
}

function renderWithApi(ui: React.ReactNode, responseFactory: ResponseFactory, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  vi.spyOn(api, 'get').mockImplementation((url) => Promise.resolve({ data: responseFactory(String(url)) }) as never)
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function enabledResponses(path: string): unknown {
  if (path === '/ctms/capabilities') return enabledManifest
  if (path.endsWith('/enrollment-targets')) return {
    items: [{ id: 'target-1', study_id: 'study-1', site_id: 'site-1', target_type: 'Enrollment', target_quantity: 120, planning_period: '2026-Q1', status: 'Active' }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/monitoring-activities')) return {
    items: [{ id: 'activity-1', study_id: 'study-1', site_id: 'site-1', activity_type: 'Routine Monitoring', planned_date: '2026-02-10T10:00:00Z', assigned_cra_id: 'cra-1', status: 'Scheduled', completion_evidence: null, edc_visit_instance_id: 'visit-1', updated_at: '2026-02-01T10:00:00Z' }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/tasks')) return {
    items: [{ id: 'task-1', study_id: 'study-1', title: 'Confirm monitoring date', status: 'Open', query_id: 'query-1' }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/contacts')) return {
    items: [{ id: 'contact-1', study_id: 'study-1', name: 'Alex CRA', role: 'CRA', status: 'Active' }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/projections')) return {
    items: [{ id: 'projection-1', study_id: 'study-1', source_module: 'EDC', source_record_id: 'signal-1', projection_type: 'Data quality', source_version: 4, source_timestamp: '2026-01-01T10:00:00Z', projected_at: '2026-01-01T10:05:00Z', payload: { open_queries: 2 }, status: 'Current' }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/exports')) return {
    items: [{ id: 'export-1', study_id: 'study-1', export_type: 'Enrollment', status: 'Completed', filters: { site_id: 'site-1', status: 'active' } }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/failed-events')) return {
    items: [{ id: 'failed-1', event_id: 'event-1', event_type: 'SUBJECT_STATUS', status: 'Failed', reason_code: 'COORDINATION_CONFLICT', sanitized_details: { message: 'safe remediation detail' } }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path.endsWith('/coordination-conflicts')) return {
    items: [{ id: 'conflict-1', event_id: 'event-2', entity_type: 'Subject', conflict_type: 'OWNERSHIP', status: 'Open', sanitized_details: { message: 'safe conflict detail' }, policy_choices: ['keep_current', 'apply_source'], available_actions: ['resolve'], correlation_id: 'correlation-conflict-1', source_version: '4', current_version: '5' }],
    page: 1,
    page_size: 20,
    total: 1,
  }
  if (path === '/ctms/health') return { worker_status: 'healthy', pending_event_count: 0, failed_event_count: 0, conflict_count: 0 }
  return defaultList
}

describe('CTMS frontend workspace and ownership controls', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('renders disabled and permission-denied states without exposing CTMS content', async () => {
    setUser([])
    renderWithApi(
      <CTMSWorkspacePage view="overview" studyId="study-1" />,
      () => ({ module: 'CTMS', enabled: false, phase: 0, capabilities: [] }),
    )
    expect(await screen.findByText(/CTMS is disabled or unavailable/)).toBeInTheDocument()
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()

    const { unmount } = renderWithApi(
      <CTMSWorkspacePage view="overview" studyId="study-1" />,
      (path) => path === '/ctms/capabilities' ? enabledManifest : defaultList,
    )
    expect(await screen.findByText('Access Denied')).toBeInTheDocument()
    unmount()
  })

  it('keeps CTMS_Viewer views read-only while rendering operational workflow data', async () => {
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])
    renderWithApi(<CTMSWorkspacePage view="tasks" studyId="study-1" />, enabledResponses)

    expect(await screen.findByText('Operational follow-up task · CTMS')).toBeInTheDocument()
    expect(screen.getByText('EDC Query ID: query-1')).toBeInTheDocument()
    expect(screen.getByText(/query lifecycle actions remain in EDC/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders enrollment, monitoring, and contact workflows with operational labels', async () => {
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])
    const { unmount } = renderWithApi(<CTMSWorkspacePage view="enrollment" studyId="study-1" />, enabledResponses)
    expect(await screen.findByText('Enrollment')).toBeInTheDocument()
    expect((await screen.findAllByText('120')).length).toBeGreaterThan(0)
    unmount()

    renderWithApi(<CTMSWorkspacePage view="monitoring-activities" studyId="study-1" />, enabledResponses)
    expect(await screen.findByText('Monitoring activity · CTMS operational record')).toBeInTheDocument()
    expect(screen.getByText('Linked protocol visit · EDC clinical record')).toBeInTheDocument()
    expect(screen.getByText('EDC Visit Instance ID: visit-1')).toBeInTheDocument()
    expect((await screen.findAllByText('Scheduled')).length).toBeGreaterThan(0)
    expect(screen.getByText('cra-1')).toBeInTheDocument()
    expect(screen.getByText(/cannot reschedule, complete, freeze, or lock/)).toBeInTheDocument()
    unmount()

    renderWithApi(<CTMSWorkspacePage view="contacts" studyId="study-1" />, enabledResponses)
    expect(await screen.findByText('Alex CRA')).toBeInTheDocument()
    expect(screen.getByText('CRA')).toBeInTheDocument()
  })

  it('shows canonical identifiers, ownership badges, and projection freshness', () => {
    render(
      <div>
        <ProjectionFreshness metadata={{ sourceModule: 'EDC', sourceRecordId: 'signal-1', sourceTimestamp: '2026-01-01T10:00:00Z', projectedAt: '2026-01-01T10:05:00Z', readOnly: true }} now={new Date('2026-01-01T12:00:00Z')} />
        <MonitoringActivitySummary activityType="Routine Monitoring" operationalStatus="Scheduled" assignedCra="cra-1" plannedDate="2026-02-10T10:00:00Z" edcVisitInstanceId="visit-1" />
      </div>,
    )
    expect(screen.getByLabelText(/authoritative module: EDC; ownership: Projected/i)).toBeInTheDocument()
    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.getAllByLabelText('read-only').length).toBeGreaterThan(0)
    expect(screen.getByText('EDC Visit Instance ID: visit-1')).toBeInTheDocument()
  })

  it('renders sanitized failed-event and conflict views with only permitted remediation', async () => {
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])
    const { unmount } = renderWithApi(<CTMSWorkspacePage view="failed-events" studyId="study-1" />, enabledResponses)
    expect(await screen.findByText(/COORDINATION_CONFLICT/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Replay failed event' })).not.toBeInTheDocument()
    expect(screen.queryByText(/safe remediation detail/)).not.toBeInTheDocument()
    unmount()

    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_CONFLICT_MANAGEMENT])
    renderWithApi(<CTMSWorkspacePage view="conflicts" studyId="study-1" />, enabledResponses)
    expect(await screen.findByText(/OWNERSHIP/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resolve conflict' })).toBeInTheDocument()
    expect(screen.queryByText(/safe conflict detail/)).not.toBeInTheDocument()
  })

  it('renders operational export filters without clinical payloads', async () => {
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])
    renderWithApi(<CTMSWorkspacePage view="exports" studyId="study-1" />, enabledResponses)

    expect(await screen.findByText('Enrollment')).toBeInTheDocument()
    expect(await screen.findByText('{"site_id":"site-1","status":"active"}')).toBeInTheDocument()
    expect(screen.queryByText(/Clinical_Data|source document|raw event|secret/i)).not.toBeInTheDocument()
  })

  it('hides or exposes attachment access controls according to CTMS permission', () => {
    const onClick = vi.fn()
    const { rerender } = render(
      <GuardedCTMSAction permission={PERMISSIONS.CTMS_OPERATIONAL_DATA_READ} onClick={onClick}>
        Download operational attachment
      </GuardedCTMSAction>,
    )
    expect(screen.queryByRole('button', { name: 'Download operational attachment' })).not.toBeInTheDocument()

    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])
    rerender(
      <GuardedCTMSAction permission={PERMISSIONS.CTMS_OPERATIONAL_DATA_READ} onClick={onClick}>
        Download operational attachment
      </GuardedCTMSAction>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Download operational attachment' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('renders an access-denied view for a missing action permission', () => {
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ])
    render(
      <GuardedCTMSAction permission={PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT} deniedView="message">
        Update operational profile
      </GuardedCTMSAction>,
    )
    expect(screen.getByTestId('ctms-access-denied')).toHaveTextContent('Access denied')
    expect(screen.queryByRole('button', { name: 'Update operational profile' })).not.toBeInTheDocument()
  })

  it('keeps API remediation authoritative after a permitted action', async () => {
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_CONFLICT_MANAGEMENT])
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    renderWithApi(<CTMSWorkspacePage view="conflicts" studyId="study-1" />, enabledResponses)
    expect(await screen.findByText('Source version')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resolve conflict' }))
    await screen.findByRole('dialog')
    fireEvent.change(screen.getByLabelText(/Resolution reason/), { target: { value: 'Current server state was reviewed before resolution.' } })
    const confirm = screen.getAllByRole('button', { name: 'Resolve conflict' })
    fireEvent.click(confirm[confirm.length - 1])
    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/coordination-conflicts/conflict-1/resolve', {
      policy: 'keep_current',
      reason: 'Current server state was reviewed before resolution.',
    }))
  })
})
