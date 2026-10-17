import { useNavigate, useSearch } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useStudyContext } from '@/lib/study-context'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { DataTableShell, DetailCard, EmptyState as SharedEmptyState, ErrorState, PageContainer, PageHeader } from '@/components/patterns'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useCTMSCapabilityState, CTMS_CAPABILITY_CODES, type CTMSCapabilityCode, type CTMSCapabilityState } from './capabilities'
import { MonitoringVisitWorkspace } from './monitoring'
import { useCTMSMutation, useCTMSOfflineState } from './offline'
import { classifyCTMSQueryState, type CTMSQueryState } from './state'
import {
  ActivationActionForm,
  EnrollmentTargetForm,
  MonitoringActivityActions,
  MonitoringActivityForm,
  MonitoringPlanForm,
  MonitoringPlanVersionActions,
  OperationalContactForm,
  OperationalContactStatusForm,
  OperationalSiteForm,
  OperationalStudyForm,
  OperationalTaskForm,
  OperationalTaskStatusForm,
  ProjectMilestoneForm,
  QueryFollowUpForm,
  StudyPlanForm,
} from './forms'
import {
  ctmsApi,
  getCTMSErrorMessage,
  normalizeCTMSError,
  useCTMSActivation,
  useCTMSConflicts,
  useCTMSContacts,
  useCTMSDashboard,
  useCTMSExports,
  useCTMSFailedEvents,
  useCTMSHealth,
  useCTMSMonitoringActivities,
  useCTMSMonitoringPlanVersions,
  useCTMSMonitoringPlans,
  useCTMSPlans,
  useCTMSProjectMilestones,
  useCTMSProjectOptions,
  useCTMSReferenceValues,
  useCTMSProjections,
  useCTMSReport,
  useCTMSStudyProfile,
  useCTMSSiteDashboard,
  useCTMSSiteProfile,
  useCTMSTargets,
  useCTMSTasks,
  type CTMSDashboard,
  type CTMSCoordinationEvent,
  type CTMSFailedEvent,
  type CTMSConflict,
  type CTMSMonitoringActivity,
  type CTMSMonitoringPlan,
  type CTMSProjectMilestone,
  type CTMSQualitySignal,
  type CTMSQueryContext,
  type CTMSStudyPlan,
} from './api'
import { invalidateCTMSCoordinationRemediation } from './cache'
import {
  activeCTMSFilters,
  filtersFromSearch,
  paginationFromSearch,
  parseCTMSSearch,
  serializeCTMSSearch,
  type CTMSSearchState,
} from './filters'
import {
  ModuleBadge,
  MonitoringActivitySummary,
  OwnershipCard,
  QualitySignalPresentation,
  QueryFollowUpSummary,
  ReadOnlyIndicator,
  StatusPresentation,
  CTMSMutationFeedback,
  CTMSFilterBar,
  CoordinationRemediationPanel,
  OperationalExportPanel,
  MilestoneHierarchy,
  ProjectGantt,
  ProjectIssueList,
  ProjectKanban,
  ProjectToolbar,
  ProjectWorkspaceHeader,
  OperationalAttachmentPanel,
  ResponsiveRecordList,
  type ResponsiveRecordColumn,
  type ResponsiveRecordPagination,
} from './components'

export type CTMSView = 'overview' | 'site-dashboard' | 'profile' | 'plans' | 'activation' | 'enrollment' | 'milestones' | 'monitoring-plans' | 'monitoring-activities' | 'tasks' | 'contacts' | 'projections' | 'reports' | 'exports' | 'health' | 'failed-events' | 'conflicts'

interface WorkspaceProps { view: CTMSView; studyId?: string; siteId?: string; reportType?: string }
interface Scope { studyId?: string; siteId?: string }

type FilterableView = Extract<CTMSView, 'overview' | 'enrollment' | 'monitoring-plans' | 'monitoring-activities' | 'tasks' | 'contacts' | 'projections' | 'reports' | 'exports'>

function supportsFilters(view: CTMSView): view is FilterableView {
  return view !== 'profile' && view !== 'plans' && view !== 'milestones' && view !== 'site-dashboard' && view !== 'activation' && view !== 'health' && view !== 'failed-events' && view !== 'conflicts'
}

const VIEW_CAPABILITIES: Record<CTMSView, { phase: 1 | 2 | 3; capability: CTMSCapabilityCode }> = {
  overview: { phase: 1, capability: CTMS_CAPABILITY_CODES.operationalDashboards },
  'site-dashboard': { phase: 1, capability: CTMS_CAPABILITY_CODES.operationalDashboards },
  profile: { phase: 1, capability: CTMS_CAPABILITY_CODES.operationalStudies },
  plans: { phase: 1, capability: CTMS_CAPABILITY_CODES.operationalStudies },
  activation: { phase: 1, capability: CTMS_CAPABILITY_CODES.operationalSites },
  enrollment: { phase: 1, capability: CTMS_CAPABILITY_CODES.enrollmentPlanning },
  milestones: { phase: 1, capability: CTMS_CAPABILITY_CODES.operationalMilestones },
  'monitoring-plans': { phase: 2, capability: CTMS_CAPABILITY_CODES.monitoring },
  'monitoring-activities': { phase: 2, capability: CTMS_CAPABILITY_CODES.monitoring },
  tasks: { phase: 2, capability: CTMS_CAPABILITY_CODES.operationalTasks },
  contacts: { phase: 2, capability: CTMS_CAPABILITY_CODES.operationalContacts },
  projections: { phase: 2, capability: CTMS_CAPABILITY_CODES.ctmsOperationalProjections },
  reports: { phase: 3, capability: CTMS_CAPABILITY_CODES.advancedOperationalReports },
  exports: { phase: 3, capability: CTMS_CAPABILITY_CODES.operationalExports },
  health: { phase: 3, capability: CTMS_CAPABILITY_CODES.qualificationEvidence },
  'failed-events': { phase: 3, capability: CTMS_CAPABILITY_CODES.failedEvents },
  conflicts: { phase: 3, capability: CTMS_CAPABILITY_CODES.coordinationConflicts },
}

// These aliases keep older manifests readable while the server migrates to the
// canonical capability-code names. They are convenience checks, not authority.
const LEGACY_CAPABILITY_ALIASES: Partial<Record<CTMSCapabilityCode, readonly string[]>> = {
  [CTMS_CAPABILITY_CODES.operationalDashboards]: ['operational_dashboard', 'operational_study'],
  [CTMS_CAPABILITY_CODES.operationalStudies]: ['operational_study'],
  [CTMS_CAPABILITY_CODES.enrollmentPlanning]: ['enrollment'],
  [CTMS_CAPABILITY_CODES.operationalMilestones]: ['milestones'],
  [CTMS_CAPABILITY_CODES.operationalTasks]: ['tasks'],
  [CTMS_CAPABILITY_CODES.operationalContacts]: ['contacts'],
  [CTMS_CAPABILITY_CODES.ctmsOperationalProjections]: ['projections'],
  [CTMS_CAPABILITY_CODES.advancedOperationalReports]: ['reports'],
  [CTMS_CAPABILITY_CODES.operationalExports]: ['exports'],
  [CTMS_CAPABILITY_CODES.qualificationEvidence]: ['health'],
  [CTMS_CAPABILITY_CODES.failedEvents]: ['failed_events'],
  [CTMS_CAPABILITY_CODES.coordinationConflicts]: ['conflicts'],
}

function Card({ title, children }: { title: string; children: React.ReactNode }) { return <DetailCard title={title}>{children}</DetailCard> }
function EmptyState({ label, actionHref, actionLabel }: { label: string; actionHref?: string; actionLabel?: string }) {
  return <SharedEmptyState title={label} description={`${label} has no records configured yet.`} action={actionHref && actionLabel ? <Button asChild variant="outline" size="sm"><a href={actionHref}>{actionLabel}</a></Button> : undefined} />
}

type WorkspaceQuery = { isLoading: boolean; isFetching?: boolean; error: unknown; refetch: () => unknown; data?: unknown }

function QueryState({ query, label, children, workerStatus, unframed = false }: { query: WorkspaceQuery; label: string; children: React.ReactNode; workerStatus?: string | null; unframed?: boolean }) {
  const { isOffline } = useCTMSOfflineState()
  const classified = classifyCTMSQueryState({ isLoading: query.isLoading, isFetching: query.isFetching, data: query.data, error: query.error, isOnline: isOffline ? false : true, workerStatus })
  const state: Exclude<CTMSQueryState, 'success' | 'empty' | 'refreshing'> | 'refreshing' | undefined = classified === 'success' || classified === 'empty' ? undefined : classified
  if (unframed && state === undefined) return <section aria-label={label} data-state="success" className="min-w-0">{children}</section>
  return <DataTableShell label={label} state={state} errorMessage={query.error ? getCTMSErrorMessage(query.error) : undefined} onRetry={() => void query.refetch()}>{children}</DataTableShell>
}

type LastValidResult<T> = { data: T; timestamp: string }

function useLastValidResult<T extends object>(query: { data?: T; error: unknown; dataUpdatedAt?: number }): LastValidResult<T> | undefined {
  const [last, setLast] = useState<LastValidResult<T>>()
  useEffect(() => {
    if (!query.data || query.error) return
    const record = query.data as Record<string, unknown>
    const generatedAt = typeof record.generated_at === 'string' ? record.generated_at : undefined
    const timestamp = generatedAt ?? (query.dataUpdatedAt ? new Date(query.dataUpdatedAt).toISOString() : new Date().toISOString())
    queueMicrotask(() => setLast({ data: query.data as T, timestamp }))
  }, [query.data, query.error, query.dataUpdatedAt])
  return last
}

function formatServerTimestamp(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function QueryStateWithFallback<T extends object>({
  query,
  label,
  lastValid,
  children,
}: {
  query: { isLoading: boolean; error: unknown; refetch: () => unknown; data?: T }
  label: string
  lastValid?: LastValidResult<T>
  children: (data: T) => React.ReactNode
}) {
  if (query.error && lastValid) {
    return <div className="space-y-3"><Alert variant="warning" role="alert"><AlertTitle>Unable to load the latest {label}.</AlertTitle><AlertDescription><p>{getCTMSErrorMessage(query.error)} Showing the last valid result from {formatServerTimestamp(lastValid.timestamp)}.</p><Button type="button" variant="link" size="sm" className="mt-2 px-0" onClick={() => void query.refetch()}>Retry</Button></AlertDescription></Alert>{children(lastValid.data)}</div>
  }
  return <QueryState query={query} label={label}>{query.data ? children(query.data) : null}</QueryState>
}

function routePath(view: CTMSView, scope: Scope, reportType = 'dashboard'): string | null {
  if (view === 'site-dashboard') return scope.siteId ? `/sites/${encodeURIComponent(scope.siteId)}/ctms` : null
  if (view === 'activation') return scope.siteId ? `/sites/${encodeURIComponent(scope.siteId)}/ctms/activation` : null
  if (!scope.studyId) return view === 'overview' ? '/ctms' : null
  if (view === 'reports') return `/studies/${encodeURIComponent(scope.studyId)}/ctms/reports/${encodeURIComponent(reportType)}`
  const suffix: Record<Exclude<CTMSView, 'activation' | 'site-dashboard' | 'overview' | 'reports'>, string> = {
    profile: '/details', plans: '/project-management', enrollment: '/enrollment', milestones: '/project-management',
    'monitoring-plans': '/monitoring/plans', 'monitoring-activities': '/monitoring/visits', tasks: '/tasks', contacts: '/contacts', projections: '/projections', exports: '/exports', health: '/health', 'failed-events': '/coordination/failed-events', conflicts: '/coordination/conflicts',
  }
  return `/studies/${encodeURIComponent(scope.studyId)}/ctms${view === 'overview' ? '' : suffix[view]}`
}

function hasCapability(state: CTMSCapabilityState, view: CTMSView): boolean {
  const required = VIEW_CAPABILITIES[view]
  if (state.manifest.phase < required.phase) return false
  const capabilities = state.manifest.capabilities
  if (capabilities.includes(required.capability)) return true
  const aliases = LEGACY_CAPABILITY_ALIASES[required.capability] ?? []
  if (aliases.some((alias) => capabilities.includes(alias))) return true

  // Pre-matrix manifests exposed broad feature names (for example
  // `monitoring` and `exports`). Keep those manifests usable by phase while
  // the server contract migrates; canonical manifests remain capability-gated.
  const canonicalCodes = new Set(Object.values(CTMS_CAPABILITY_CODES))
  const isLegacyManifest = capabilities.some((code) => !canonicalCodes.has(code as CTMSCapabilityCode))
  return isLegacyManifest
}

function titleFor(view: CTMSView) { return ({ overview: 'Overview', 'site-dashboard': 'Site dashboard', profile: 'Study Details', plans: 'Master Activities', activation: 'Site activation', enrollment: 'Enrollment planning', milestones: 'Milestones', 'monitoring-plans': 'Monitoring Plan', 'monitoring-activities': 'Monitoring Visit', tasks: 'Operational tasks', contacts: 'Operational contacts', projections: 'Clinical projections', reports: 'Reports & dashboards', exports: 'Operational exports', health: 'CTMS health', 'failed-events': 'Failed events', conflicts: 'Coordination conflicts' })[view] }

function DirectRouteState({ kind, title, message }: { kind: 'disabled' | 'unavailable'; title: string; message: string }) {
  return (
    <PageContainer>
      <DataTableShell
        label={title}
        state={kind}
        stateSlots={{
          [kind]: <ErrorState state={kind} title={title} message={message} actions={<Button asChild variant="outline" size="sm"><a href="/">Return to EDC dashboard</a></Button>} />,
        }}
      />
      {kind === 'unavailable' ? <p className="mt-3 text-xs text-muted-foreground">CTMS availability is server-controlled; this state does not change EDC authorization or navigation.</p> : null}
    </PageContainer>
  )
}

function CTMSWorkspaceLayout({ view, scope, children }: { view: CTMSView; scope: Scope; children: React.ReactNode }) {
  const canManageStudy = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, scope.studyId)
  const canManageSite = usePermission(PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT, scope.studyId, scope.siteId)
  const readOnly = !canManageStudy && !canManageSite
  if (view === 'plans' || view === 'milestones') {
    return <PageContainer wide data-testid="ctms-workspace">{children}</PageContainer>
  }
  return (
    <PageContainer wide data-testid="ctms-workspace">
      <PageHeader
        title={titleFor(view)}
        description={<span><span className="block text-xs font-semibold uppercase tracking-wide text-primary">CTMS operational workspace</span><span className="block">The platform Study identity and EDC clinical identifiers remain read-only; CTMS owns operational records.</span></span>}
        status={<ModuleBadge module="CTMS" state="authoritative" />}
        ownership={readOnly ? <ReadOnlyIndicator reason="Your CTMS permissions provide read access only; the API remains authoritative." /> : undefined}
      />
      {children}
    </PageContainer>
  )
}

function CreateDrawer({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; children: React.ReactNode }) {
  return <Sheet open={open} onOpenChange={onOpenChange}><SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl"><SheetHeader className="pr-8"><SheetTitle>{title}</SheetTitle><SheetDescription>{description}</SheetDescription></SheetHeader><div className="mt-2 pt-4">{children}</div></SheetContent></Sheet>
}

function ViewContent({ view, scope, reportType, search, onPageChange, onFilterChange, onClearFilters }: { view: CTMSView; scope: Scope; reportType: string; search: CTMSSearchState; onPageChange: (page: number) => void; onFilterChange: (change: Partial<CTMSSearchState>) => void; onClearFilters: () => void }) {
  const filters = filtersFromSearch(search)
  const pagination = paginationFromSearch(search)
  const context: CTMSQueryContext = { routeScope: scope.siteId ? `site:${scope.siteId}` : `study:${scope.studyId ?? 'none'}`, studyId: scope.studyId, siteId: scope.siteId, filters, pagination }
  const filtered = (content: React.ReactNode) => supportsFilters(view) ? <section aria-label={`${titleFor(view)} list and filters`} className="overflow-hidden rounded-lg border bg-card"><CTMSFilterBar embedded filters={filters} onChange={(change) => onFilterChange(change)} onClear={onClearFilters} showReportType={view === 'reports'} /><div className="p-4">{content}</div></section> : content
  if (view === 'health') return filtered(<HealthView context={context} />)
  if (view === 'site-dashboard') return filtered(<SiteDashboardView studyId={scope.studyId} siteId={scope.siteId ?? ''} context={context} />)
  if (view === 'activation') return filtered(<ActivationView studyId={scope.studyId} siteId={scope.siteId ?? ''} context={context} />)
  if (view === 'profile') return filtered(<ProfileView studyId={scope.studyId ?? ''} context={context} />)
  if (view === 'plans') return filtered(<ListView label="master activities" empty="Master Activities" actionHref={routePath('profile', scope)} actionLabel="Configure study details" queryHook="plans" studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'overview') return filtered(<OverviewView studyId={scope.studyId ?? ''} context={context} />)
  if (view === 'enrollment') return filtered(<ListView label="enrollment targets" empty="Enrollment targets" actionHref={routePath('profile', scope)} actionLabel="Configure operational study data" queryHook="targets" studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'milestones') return filtered(<ListView label="operational milestones" empty="Operational milestones" actionHref={routePath('profile', scope)} actionLabel="Configure operational study data" queryHook="milestones" studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'monitoring-plans') return filtered(<ListView label="monitoring plan" empty="Monitoring Plan" actionHref={routePath('profile', scope)} actionLabel="Configure monitoring setup" queryHook="monitoringPlans" studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'monitoring-activities') return filtered(<ActivitiesView studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'tasks') return filtered(<TasksView studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'contacts') return filtered(<ListView label="operational contacts" empty="Operational contacts" actionHref={routePath('profile', scope)} actionLabel="Configure operational contacts" queryHook="contacts" studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'projections') return filtered(<ProjectionsView studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'reports') return filtered(<ReportView studyId={scope.studyId ?? ''} reportType={reportType} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'exports') return filtered(<ListView label="operational exports" empty="Operational exports" actionHref={routePath('overview', scope)} actionLabel="Open study operations" queryHook="exports" studyId={scope.studyId ?? ''} context={context} filters={filters} onPageChange={onPageChange} />)
  if (view === 'failed-events') return filtered(<RemediationView kind="failed" studyId={scope.studyId ?? ''} context={context} />)
  return filtered(<RemediationView kind="conflict" studyId={scope.studyId ?? ''} context={context} />)
}

function HealthView({ context }: { context: CTMSQueryContext }) {
  const health = useCTMSHealth(context)
  return <QueryState query={health} label="CTMS health" workerStatus={health.data?.worker_status}><Card title="Worker and coordination health"><DefinitionList value={health.data ?? {}} /></Card></QueryState>
}
function ActivationView({ studyId, siteId, context }: { studyId?: string; siteId: string; context: CTMSQueryContext }) {
  const siteProfile = useCTMSSiteProfile(siteId, context)
  const activation = useCTMSActivation(siteId, context)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT, studyId, siteId)
  const statusOptions = activation.data?.status_options ?? []
  const [drawer, setDrawer] = useState<'profile' | 'activation' | null>(null)
  return <QueryState query={siteProfile} label="site profile"><div className="space-y-4"><OwnershipCard title="Canonical site reference" identifiers={{ studyId, siteId }}><p className="text-sm text-muted-foreground">CTMS creates the Site identity and synchronizes the same ID to the shared platform for EDC use.</p><ModuleBadge module="CTMS" state="authoritative" /></OwnershipCard><div className="flex flex-wrap justify-end gap-2">{canManage ? <><Button type="button" variant="outline" onClick={() => setDrawer('profile')}>{siteProfile.data ? 'Edit site profile' : 'Create site profile'}</Button><Button type="button" onClick={() => setDrawer('activation')}>Add activation action</Button></> : null}</div><Card title="Site operational profile"><DefinitionList value={siteProfile.data ?? {}} />{siteProfile.data?.status && <div className="mt-4"><StatusPresentation kind="operational" status={String(siteProfile.data.status)} owner="CTMS" readOnly={false} /></div>}</Card><QueryState query={activation} label="activation actions"><RecordTable rows={activation.data?.items ?? []} empty="Activation" actionHref={`/sites/${encodeURIComponent(siteId)}/ctms/activation`} actionLabel="Review site activation" /></QueryState><CreateDrawer open={drawer === 'profile'} onOpenChange={(open) => setDrawer(open ? 'profile' : null)} title={siteProfile.data ? 'Edit site profile' : 'Create site profile'} description="Configure the CTMS-owned operational profile for this site."><OperationalSiteForm siteId={siteId} studyId={studyId} initialValue={siteProfile.data} onSaved={() => { setDrawer(null); void siteProfile.refetch() }} onCancel={() => setDrawer(null)} /></CreateDrawer><CreateDrawer open={drawer === 'activation'} onOpenChange={(open) => setDrawer(open ? 'activation' : null)} title="Add activation action" description="Create an operational activation action for this site."><ActivationActionForm siteId={siteId} studyId={studyId} statusOptions={statusOptions} onSaved={() => { setDrawer(null); void activation.refetch() }} onCancel={() => setDrawer(null)} /></CreateDrawer></div></QueryState>
}
function ProfileView({ studyId, context }: { studyId: string; context: CTMSQueryContext }) {
  const profile = useCTMSStudyProfile(studyId, context)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, studyId)
  const [drawerOpen, setDrawerOpen] = useState(false)
  if (profile.error && normalizeCTMSError(profile.error).category === 'not-found') {
    return <div className="space-y-4"><OwnershipCard title="Platform study reference" identifiers={{ studyId }}><p className="text-sm text-muted-foreground">Study name and sponsor are synchronized from Aurinara Platform and cannot be changed by CTMS.</p><ModuleBadge module="Shared" state="authoritative" /></OwnershipCard>{canManage ? <div className="flex justify-end"><Button type="button" onClick={() => setDrawerOpen(true)}>Create study details</Button></div> : null}<EmptyState label="Study Details" /><CreateDrawer open={drawerOpen} onOpenChange={setDrawerOpen} title="Create study details" description="Configure CTMS-owned study details for this study."><OperationalStudyForm studyId={studyId} onSaved={() => { setDrawerOpen(false); void profile.refetch() }} onCancel={() => setDrawerOpen(false)} /></CreateDrawer></div>
  }
  return <QueryState query={profile} label="study details"><div className="space-y-4"><OwnershipCard title="Platform study reference" identifiers={{ studyId }}><p className="text-sm text-muted-foreground">Study name and sponsor are synchronized from Aurinara Platform and cannot be changed by CTMS.</p><ModuleBadge module="Shared" state="authoritative" /></OwnershipCard>{canManage ? <div className="flex justify-end"><Button type="button" onClick={() => setDrawerOpen(true)}>{profile.data ? 'Edit study details' : 'Create study details'}</Button></div> : null}<Card title="Study Details"><DefinitionList value={profile.data ?? {}} />{profile.data?.status && <div className="mt-4"><StatusPresentation kind="operational" status={String(profile.data.status)} owner="CTMS" readOnly={false} /></div>} {!profile.data && <EmptyState label="Study Details" />}</Card><CreateDrawer open={drawerOpen} onOpenChange={setDrawerOpen} title={profile.data ? 'Edit study details' : 'Create study details'} description="Configure CTMS-owned study details while preserving the shared study identity."><OperationalStudyForm studyId={studyId} initialValue={profile.data} onSaved={() => { setDrawerOpen(false); void profile.refetch() }} onCancel={() => setDrawerOpen(false)} /></CreateDrawer></div></QueryState>
}
function DashboardMetricSection({ title, value }: { title: string; value?: Record<string, unknown> }) {
  if (!value || Object.keys(value).length === 0) return null
  return <Card title={title}><dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(value).map(([key, item]) => <div key={key}><dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{key.replaceAll('_', ' ')}</dt><dd className="mt-1 break-words text-lg font-semibold text-foreground">{typeof item === 'object' ? JSON.stringify(item) : String(item ?? '—')}</dd></div>)}</dl></Card>
}

function DashboardContent({ dashboard, scopeLabel, onRefresh, refreshing }: { dashboard: CTMSDashboard; scopeLabel: string; onRefresh?: () => void; refreshing?: boolean }) {
  const operational = dashboard.operational ?? {}
  return <div className="space-y-4"><p className="text-sm text-muted-foreground">Server-generated CTMS operational metrics for the {scopeLabel}. Totals are authoritative and are not reconstructed from rendered records.</p><DashboardMetricSection title="Enrollment" value={operational.enrollment} /><DashboardMetricSection title="Monitoring" value={operational.monitoring} /><DashboardMetricSection title="Tasks" value={operational.tasks} /><DashboardMetricSection title="Readiness" value={operational.readiness} /><DashboardMetricSection title="Activation" value={operational.activation} /><Card title="Approved quality signals"><QualitySignals value={dashboard.projected_clinical ?? []} onRefresh={onRefresh} refreshing={refreshing} /></Card><p className="text-xs text-muted-foreground">Generated at: {dashboard.generated_at ? formatServerTimestamp(dashboard.generated_at) : 'Not provided by the server'}</p></div>
}

function OverviewView({ studyId, context }: { studyId: string; context: CTMSQueryContext }) {
  const dashboard = useCTMSDashboard(studyId, context)
  const lastValid = useLastValidResult(dashboard)
  return <QueryStateWithFallback query={dashboard} label="operational dashboard" lastValid={lastValid}>{(data) => <DashboardContent dashboard={data} scopeLabel="study" onRefresh={() => void dashboard.refetch()} refreshing={dashboard.isFetching} />}</QueryStateWithFallback>
}

function SiteDashboardView({ studyId, siteId, context }: { studyId?: string; siteId: string; context: CTMSQueryContext }) {
  const dashboard = useCTMSSiteDashboard(siteId, studyId, context)
  const lastValid = useLastValidResult(dashboard)
  return <QueryStateWithFallback query={dashboard} label="site operational dashboard" lastValid={lastValid}>{(data) => <DashboardContent dashboard={data} scopeLabel="site" onRefresh={() => void dashboard.refetch()} refreshing={dashboard.isFetching} />}</QueryStateWithFallback>
}

type ListHook = 'plans' | 'targets' | 'milestones' | 'monitoringPlans' | 'contacts' | 'exports'
type ListViewProps = { label: string; empty: string; actionHref?: string | null; actionLabel: string; studyId: string; context: CTMSQueryContext; filters: CTMSQueryContext['filters']; onPageChange: (page: number) => void }
function ListView(props: ListViewProps & { queryHook: ListHook }) {
  if (props.queryHook === 'plans') return <PlansList {...props} />
  if (props.queryHook === 'targets') return <TargetsList {...props} />
  if (props.queryHook === 'milestones') return <PlansList {...props} />
  if (props.queryHook === 'monitoringPlans') return <MonitoringPlansList {...props} />
  if (props.queryHook === 'contacts') return <ContactsList {...props} />
  return <ExportsList {...props} />
}
function PlansList(props: ListViewProps) {
  const projectContext = { ...props.context, filters: {}, pagination: { page: 1, pageSize: 100 } }
  const query = useCTMSPlans(props.studyId, projectContext)
  const milestones = useCTMSProjectMilestones(props.studyId, projectContext)
  const options = useCTMSProjectOptions(props.studyId)
  const statuses = useCTMSReferenceValues('project_status')
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, props.studyId)
  const [activityDrawerOpen, setActivityDrawerOpen] = useState(false)
  const [milestoneDrawerOpen, setMilestoneDrawerOpen] = useState(false)
  const [editingActivity, setEditingActivity] = useState<CTMSStudyPlan | undefined>()
  const [editingMilestone, setEditingMilestone] = useState<CTMSProjectMilestone | undefined>()
  const [view, setView] = useState<'board' | 'timeline' | 'list' | 'milestones'>('board')
  const [searchText, setSearchText] = useState('')
  const [scopeFilter, setScopeFilter] = useState('all')
  const [assigneeFilter, setAssigneeFilter] = useState('all')
  const move = useCTMSMutation<CTMSStudyPlan, unknown, { activity: CTMSStudyPlan; status: string }>({
    method: 'PATCH',
    mutationFn: ({ activity, status }) => ctmsApi.updatePlan(activity.id, { status, reason: `Moved from ${activity.status ?? 'DRAFT'} to ${status} on the Kanban board` }),
    onSuccess: () => void query.refetch(),
  })
  const activities = query.data?.items ?? []
  const milestoneItems = milestones.data?.items ?? []
  const workflowStatuses = (statuses.data?.items ?? []).map((status) => ({ code: status.code, label: status.label }))
  const normalizedSearch = searchText.trim().toLowerCase()
  const visibleActivities = activities.filter((activity) => {
    const matchesSearch = !normalizedSearch || [activity.title, activity.objective].some((value) => value?.toLowerCase().includes(normalizedSearch))
    const matchesScope = scopeFilter === 'all' || activity.scope_level === scopeFilter
    const matchesAssignee = assigneeFilter === 'all'
      || (assigneeFilter === 'unassigned' && !activity.assignee_role_id && !activity.assignee_user_id)
      || (assigneeFilter.startsWith('role:') && activity.assignee_role_id === assigneeFilter.slice(5))
      || (assigneeFilter.startsWith('user:') && activity.assignee_user_id === assigneeFilter.slice(5))
    return matchesSearch && matchesScope && matchesAssignee
  })
  const visibleMilestones = milestoneItems.filter((milestone) => {
    const matchesSearch = !normalizedSearch || [milestone.title, milestone.description, milestone.milestone_type].some((value) => value?.toLowerCase().includes(normalizedSearch))
    return matchesSearch && (scopeFilter === 'all' || milestone.scope_level === scopeFilter)
  })
  const visibleMilestoneIds = new Set(visibleMilestones.map((milestone) => milestone.id))
  const timelineActivities = visibleActivities.filter((activity) => !activity.milestone_id || visibleMilestoneIds.has(activity.milestone_id))
  const openCreateActivity = () => { setEditingActivity(undefined); setActivityDrawerOpen(true) }
  const openCreateMilestone = () => { setEditingMilestone(undefined); setMilestoneDrawerOpen(true) }
  const completedCodes = new Set(['COMPLETED', 'COMPLETE', 'DONE'])
  const workspaceQuery = { isLoading: query.isLoading || milestones.isLoading || options.isLoading || statuses.isLoading, isFetching: query.isFetching || milestones.isFetching || options.isFetching || statuses.isFetching, error: query.error ?? milestones.error ?? options.error ?? statuses.error, data: query.data, refetch: async () => { await Promise.all([query.refetch(), milestones.refetch(), options.refetch(), statuses.refetch()]) } }
  return <QueryState query={workspaceQuery} label={props.label} unframed><div className="space-y-5">
    <ProjectWorkspaceHeader activityCount={activities.length} milestoneCount={milestoneItems.length} completedCount={activities.filter((activity) => completedCodes.has(activity.status ?? '')).length} canManage={canManage} onCreateActivity={openCreateActivity} onCreateMilestone={openCreateMilestone} />
    <ProjectToolbar search={searchText} onSearchChange={setSearchText} scope={scopeFilter} onScopeChange={setScopeFilter} assignee={assigneeFilter} onAssigneeChange={setAssigneeFilter} options={options.data} view={view} onViewChange={setView} resultCount={view === 'milestones' ? visibleMilestones.length : visibleActivities.length} showAssignee={view !== 'milestones'} />
    {move.error ? <Alert variant="destructive"><AlertTitle>Activity could not be moved</AlertTitle><AlertDescription>{getCTMSErrorMessage(move.error)}</AlertDescription></Alert> : null}
    {view === 'milestones'
      ? !milestoneItems.length ? <EmptyState label="Milestones" actionHref={props.actionHref ?? undefined} actionLabel={props.actionLabel} /> : !visibleMilestones.length ? <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">No milestones match the current filters.</div> : <MilestoneHierarchy milestones={visibleMilestones} activities={activities} options={options.data} workflowStatuses={workflowStatuses} canManage={canManage} onEdit={(milestone) => { setEditingMilestone(milestone); setMilestoneDrawerOpen(true) }} />
      : !activities.length ? <EmptyState label="Master Activities" actionHref={props.actionHref ?? undefined} actionLabel={props.actionLabel} /> : !visibleActivities.length ? <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">No work items match the current filters.</div> : view === 'board' ? <ProjectKanban activities={visibleActivities} milestones={milestoneItems} options={options.data} workflowStatuses={workflowStatuses} canManage={canManage} movingId={move.isPending ? move.variables?.activity.id : undefined} onMove={(activity, status) => move.mutate({ activity, status })} onEdit={(activity) => { setEditingActivity(activity); setActivityDrawerOpen(true) }} onCreate={openCreateActivity} /> : view === 'timeline' ? <ProjectGantt activities={timelineActivities} milestones={visibleMilestones} options={options.data} /> : <ProjectIssueList activities={visibleActivities} options={options.data} workflowStatuses={workflowStatuses} canManage={canManage} onEdit={(activity) => { setEditingActivity(activity); setActivityDrawerOpen(true) }} />}
    <CreateDrawer open={activityDrawerOpen} onOpenChange={setActivityDrawerOpen} title={editingActivity ? 'Edit master activity' : 'Add master activity'} description="Create or update a scoped Jira-style work item for this study."><StudyPlanForm studyId={props.studyId} initialValue={editingActivity} onSaved={() => { setActivityDrawerOpen(false); setEditingActivity(undefined); void query.refetch() }} onCancel={() => { setActivityDrawerOpen(false); setEditingActivity(undefined) }} /></CreateDrawer>
    <CreateDrawer open={milestoneDrawerOpen} onOpenChange={setMilestoneDrawerOpen} title={editingMilestone ? 'Edit milestone' : 'Add milestone'} description="Milestones group master activities at the same study, country, or site level."><ProjectMilestoneForm studyId={props.studyId} initialValue={editingMilestone} onSaved={() => { setMilestoneDrawerOpen(false); setEditingMilestone(undefined); void Promise.all([milestones.refetch(), query.refetch()]) }} onCancel={() => { setMilestoneDrawerOpen(false); setEditingMilestone(undefined) }} /></CreateDrawer>
  </div></QueryState>
}
function TargetsList(props: ListViewProps) {
  const query = useCTMSTargets(props.studyId, props.context)
  const canManage = usePermission(PERMISSIONS.CTMS_ENROLLMENT_MANAGEMENT, props.studyId)
  const [drawerOpen, setDrawerOpen] = useState(false)
  return <ListQuery {...props} query={query}>{canManage ? <div className="flex justify-end"><Button type="button" onClick={() => setDrawerOpen(true)}>Add enrollment target</Button></div> : null}<CreateDrawer open={drawerOpen} onOpenChange={setDrawerOpen} title="Add enrollment target" description="Create a study- or site-scoped operational enrollment target."><EnrollmentTargetForm studyId={props.studyId} statusOptions={query.data?.status_options ?? []} onSaved={() => { setDrawerOpen(false); void query.refetch() }} onCancel={() => setDrawerOpen(false)} /></CreateDrawer></ListQuery>
}
function MonitoringPlansList(props: ListViewProps) {
  const query = useCTMSMonitoringPlans(props.studyId, props.context)
  const canManage = usePermission(PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT, props.studyId)
  const [showCreate, setShowCreate] = useState(false)
  return <ListQuery {...props} query={query} hideTable>
    {canManage ? <div className="flex justify-end"><Button type="button" onClick={() => setShowCreate(true)}>Create monitoring plan</Button></div> : null}
    <CreateDrawer open={showCreate} onOpenChange={setShowCreate} title="Create monitoring plan" description="Configure a CTMS-owned monitoring plan for this study."><MonitoringPlanForm studyId={props.studyId} onSaved={() => { setShowCreate(false); void query.refetch() }} onCancel={() => setShowCreate(false)} /></CreateDrawer>
    <div className="space-y-3">{query.data?.items?.map((raw) => { const plan = raw as CTMSMonitoringPlan; return <MonitoringPlanDetail key={plan.id} plan={plan} studyId={props.studyId} canManage={canManage} onChanged={() => void query.refetch()} /> })}</div>
  </ListQuery>
}

function MonitoringPlanDetail({ plan, studyId, canManage, onChanged }: { plan: CTMSMonitoringPlan; studyId: string; canManage: boolean; onChanged: () => void }) {
  const versions = useCTMSMonitoringPlanVersions(plan.id, { studyId })
  const [showEdit, setShowEdit] = useState(false)
  return <OwnershipCard title={plan.name} identifiers={{ studyId: plan.study_id, siteId: plan.site_id }}><div className="space-y-3"><StatusPresentation kind="operational" status={plan.status} owner="CTMS" readOnly={!canManage} /><p className="text-sm text-muted-foreground">Monitoring plan configuration is CTMS-authoritative. Protocol visits and clinical records remain EDC-owned.</p>{canManage ? <div className="flex flex-wrap gap-2"><button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setShowEdit((value) => !value)}>{showEdit ? 'Close plan editor' : 'Edit plan'}</button><MonitoringPlanVersionActions planId={plan.id} onChanged={onChanged} /></div> : null}{showEdit ? <MonitoringPlanForm studyId={studyId} initial={plan} onSaved={() => { setShowEdit(false); onChanged() }} onCancel={() => setShowEdit(false)} /> : null}<div><h3 className="text-sm font-semibold">Versions</h3>{versions.isLoading ? <p className="text-sm text-muted-foreground">Loading plan versions…</p> : versions.error ? <p role="alert" className="text-sm text-destructive">Unable to load plan versions.</p> : versions.data?.items?.length ? <ul className="mt-2 space-y-1 text-sm">{versions.data.items.map((version) => <li key={version.id} className="rounded border p-2"><span className="font-medium">Version {version.version_number}</span><span className="ml-2 text-muted-foreground">{version.status}</span>{version.correlation_id ? <span className="ml-2 font-mono text-xs text-muted-foreground">Correlation ID: {version.correlation_id}</span> : null}</li>)}</ul> : <p className="text-sm text-muted-foreground">No versions returned by the server.</p>}</div></div></OwnershipCard>
}

function ContactsList(props: ListViewProps) {
  const query = useCTMSContacts(props.studyId, props.context)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, props.studyId)
  const [showCreate, setShowCreate] = useState(false)
  const [editingContactId, setEditingContactId] = useState<string | null>(null)
  const [transitionContactId, setTransitionContactId] = useState<string | null>(null)
  return <ListQuery {...props} query={query} hideTable>
    {canManage ? <div className="flex justify-end"><Button type="button" onClick={() => setShowCreate(true)}>Create operational contact</Button></div> : null}
    <CreateDrawer open={showCreate} onOpenChange={setShowCreate} title="Create operational contact" description="Add a CTMS operational contact for this study."><OperationalContactForm studyId={props.studyId} onSaved={() => { setShowCreate(false); void query.refetch() }} onCancel={() => setShowCreate(false)} /></CreateDrawer>
    <div className="space-y-3">{query.data?.items?.map((raw) => { const contact = raw as import('./api').CTMSContact; const transitionOptions = contact.allowed_transitions ?? []; return <OwnershipCard key={contact.id} title={contact.name} identifiers={{ studyId: contact.study_id, siteId: contact.site_id }}><DefinitionList value={Object.fromEntries(Object.entries(contact).filter(([key]) => key !== 'name'))} /><StatusPresentation kind="operational" status={contact.status} owner="CTMS" readOnly={!canManage} />{contact.correlation_id ? <p className="font-mono text-xs text-muted-foreground">Correlation ID: {contact.correlation_id}</p> : null}{canManage ? <div className="flex flex-wrap gap-2"><button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setEditingContactId(editingContactId === contact.id ? null : contact.id)}>{editingContactId === contact.id ? 'Close contact editor' : 'Edit contact'}</button>{transitionOptions.length ? <button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setTransitionContactId(transitionContactId === contact.id ? null : contact.id)}>{transitionContactId === contact.id ? 'Close status form' : 'Change contact status'}</button> : null}</div> : null}{editingContactId === contact.id ? <OperationalContactForm studyId={props.studyId} initial={contact} onSaved={() => { setEditingContactId(null); void query.refetch() }} onCancel={() => setEditingContactId(null)} /> : null}{transitionContactId === contact.id ? <OperationalContactStatusForm contact={contact} transitionOptions={transitionOptions} onSaved={() => void query.refetch()} onCancel={() => setTransitionContactId(null)} /> : null}</OwnershipCard> })}</div>
  </ListQuery>
}
function ExportsList(props: ListViewProps) {
  const query = useCTMSExports(props.studyId, props.context)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, props.studyId)
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, props.studyId)
  return <QueryState query={query} label="operational exports"><OperationalExportPanel studyId={props.studyId} siteId={props.context.siteId} context={props.context} jobs={(query.data?.items ?? []) as import('./api').CTMSExport[]} isLoading={query.isFetching} canManage={canManage} canRead={canRead} onRefresh={() => void query.refetch()} /></QueryState>
}
function ListQuery({ query, label, empty, actionHref, actionLabel, filters, onPageChange, children, hideTable }: ListViewProps & { query: { isLoading: boolean; error: unknown; refetch: () => unknown; isFetching?: boolean; data?: { items?: object[]; page?: number; page_size?: number; total?: number; status_options?: unknown[] } }; children?: React.ReactNode; hideTable?: boolean }) {
  return <QueryState query={query} label={label}><div className="space-y-4">{children}{(!hideTable || !query.data?.items?.length) && <RecordTable rows={query.data?.items ?? []} empty={empty} actionHref={actionHref} actionLabel={actionLabel} filters={filters} pagination={query.data?.page !== undefined && query.data.page_size !== undefined && query.data.total !== undefined ? { page: query.data.page, pageSize: query.data.page_size, total: query.data.total, onPageChange, isLoading: query.isFetching } : undefined} />}</div></QueryState>
}
function ActivitiesView({ studyId, context, filters, onPageChange }: { studyId: string; context: CTMSQueryContext; filters: CTMSQueryContext['filters']; onPageChange: (page: number) => void }) {
  const activities = useCTMSMonitoringActivities(studyId, context)
  const canManage = usePermission(PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT, studyId)
  const [showCreate, setShowCreate] = useState(false)
  const pagination = activities.data?.page !== undefined && activities.data.page_size !== undefined && activities.data.total !== undefined ? { page: activities.data.page, pageSize: activities.data.page_size, total: activities.data.total, onPageChange, isLoading: activities.isFetching } : undefined
  return <QueryState query={activities} label="monitoring visits"><div className="space-y-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm text-muted-foreground">Monitoring visits are CTMS operational records and never protocol Visit_Instances.</p>{canManage ? <Button type="button" onClick={() => setShowCreate(true)}>Schedule monitoring visit</Button> : null}</div><CreateDrawer open={showCreate} onOpenChange={setShowCreate} title="Schedule monitoring visit" description="Create a CTMS operational monitoring visit."><MonitoringActivityForm studyId={studyId} onSaved={() => { setShowCreate(false); void activities.refetch() }} onCancel={() => setShowCreate(false)} /></CreateDrawer>{activities.data?.items?.length ? activities.data.items.map((raw) => { const activity = raw as CTMSMonitoringActivity; return <OwnershipCard key={activity.id} title={activity.visit_code ? `${activity.visit_code} · ${activity.activity_type}` : activity.activity_type} identifiers={{ studyId: activity.study_id, siteId: activity.site_id, visitInstanceId: activity.edc_visit_instance_id }}><p className="text-sm font-medium">{activity.modality}</p><MonitoringActivitySummary activityType={activity.activity_type} operationalStatus={activity.status} assignedCra={activity.assigned_cra_id} plannedDate={activity.planned_date} completionEvidence={activity.completion_evidence ? JSON.stringify(activity.completion_evidence) : null} lastChangedAt={activity.updated_at} edcVisitInstanceId={activity.edc_visit_instance_id} />{activity.correlation_id ? <p className="font-mono text-xs text-muted-foreground">Correlation ID: {activity.correlation_id}</p> : null}<MonitoringVisitWorkspace visit={activity} canManage={canManage} onVisitChanged={() => void activities.refetch()} />{canManage ? <MonitoringActivityActions activity={activity} onChanged={() => void activities.refetch()} /> : null}{activity.attachment_constraints ? <OperationalAttachmentPanel studyId={studyId} siteId={activity.site_id} objectType="monitoring_activity" objectId={activity.id} parentLabel="monitoring visit" attachments={activity.attachments} constraints={activity.attachment_constraints} /> : null}</OwnershipCard> }) : <RecordTable rows={[]} empty="Monitoring Visits" actionHref={routePath('monitoring-plans', { studyId }) ?? undefined} actionLabel="Configure monitoring plan" filters={filters} pagination={pagination} />}{pagination && <ServerPagination label="monitoring visits" pagination={pagination} />}</div></QueryState>
}
function TasksView({ studyId, context, filters, onPageChange }: { studyId: string; context: CTMSQueryContext; filters: CTMSQueryContext['filters']; onPageChange: (page: number) => void }) {
  const tasks = useCTMSTasks(studyId, context)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, studyId)
  const [showCreate, setShowCreate] = useState(false)
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null)
  const [followUpQueryId, setFollowUpQueryId] = useState<string | null>(null)
  const [transitionTaskId, setTransitionTaskId] = useState<string | null>(null)
  const pagination = tasks.data?.page !== undefined && tasks.data.page_size !== undefined && tasks.data.total !== undefined ? { page: tasks.data.page, pageSize: tasks.data.page_size, total: tasks.data.total, onPageChange, isLoading: tasks.isFetching } : undefined
  return <QueryState query={tasks} label="operational tasks"><div className="space-y-3">{canManage ? <div className="flex justify-end"><Button type="button" onClick={() => setShowCreate(true)}>Create operational task</Button></div> : null}<CreateDrawer open={showCreate} onOpenChange={setShowCreate} title="Create operational task" description="Add a CTMS-owned operational task for this study."><OperationalTaskForm studyId={studyId} onSaved={() => { setShowCreate(false); void tasks.refetch() }} onCancel={() => setShowCreate(false)} /></CreateDrawer>{tasks.data?.items?.length ? tasks.data.items.map((raw) => { const task = raw as import('./api').CTMSTask; const transitionOptions = task.allowed_transitions ?? []; return <OwnershipCard key={task.id} title={task.title} identifiers={{ studyId: task.study_id, siteId: task.site_id }}><DefinitionList value={task} />{task.query_id ? <QueryFollowUpSummary queryId={task.query_id} taskStatus={task.status} queryStatus="EDC query lifecycle remains EDC-owned" /> : <StatusPresentation kind="operational" status={task.status} owner="CTMS" readOnly={!canManage} />}{task.correlation_id ? <p className="font-mono text-xs text-muted-foreground">Correlation ID: {task.correlation_id}</p> : null}{canManage ? <div className="flex flex-wrap gap-2"><button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setEditingTaskId(editingTaskId === task.id ? null : task.id)}>{editingTaskId === task.id ? 'Close task editor' : 'Edit task'}</button>{transitionOptions.length ? <button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setTransitionTaskId(transitionTaskId === task.id ? null : task.id)}>{transitionTaskId === task.id ? 'Close status form' : 'Change task status'}</button> : null}{task.query_id ? <button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setFollowUpQueryId(followUpQueryId === task.query_id ? null : task.query_id ?? null)}>{followUpQueryId === task.query_id ? 'Close follow-up form' : 'Create query follow-up'}</button> : null}</div> : null}{editingTaskId === task.id ? <OperationalTaskForm studyId={studyId} initial={task} onSaved={() => { setEditingTaskId(null); void tasks.refetch() }} onCancel={() => setEditingTaskId(null)} /> : null}{transitionTaskId === task.id ? <OperationalTaskStatusForm task={task} transitionOptions={transitionOptions} onSaved={() => void tasks.refetch()} onCancel={() => setTransitionTaskId(null)} /> : null}{followUpQueryId === task.query_id && task.query_id ? <QueryFollowUpForm queryId={task.query_id} studyId={studyId} onSaved={() => { setFollowUpQueryId(null); void tasks.refetch() }} onCancel={() => setFollowUpQueryId(null)} /> : null}{task.attachment_constraints ? <OperationalAttachmentPanel studyId={studyId} siteId={task.site_id} objectType="operational_task" objectId={task.id} parentLabel="operational task" attachments={task.attachments} constraints={task.attachment_constraints} /> : null}</OwnershipCard> }) : <RecordTable rows={[]} empty="Operational tasks" actionHref={routePath('overview', { studyId }) ?? undefined} actionLabel="Open study operations" filters={filters} pagination={pagination} />}{pagination && <ServerPagination label="operational tasks" pagination={pagination} />}</div></QueryState>
}
function ProjectionsView({ studyId, context, filters, onPageChange }: { studyId: string; context: CTMSQueryContext; filters: CTMSQueryContext['filters']; onPageChange: (page: number) => void }) {
  const projections = useCTMSProjections(studyId, context)
  const pagination = projections.data?.page !== undefined && projections.data.page_size !== undefined && projections.data.total !== undefined ? { page: projections.data.page, pageSize: projections.data.page_size, total: projections.data.total, onPageChange, isLoading: projections.isFetching } : undefined
  return <QueryState query={projections} label="read-only projections"><div className="space-y-3"><p className="text-sm text-muted-foreground">Projected clinical metrics are read-only and do not authorize EDC mutations.</p>{projections.data?.items?.length ? projections.data.items.map((projection) => <OwnershipCard key={projection.id} title={projection.projection_type} identifiers={{ studyId: projection.study_id, siteId: projection.site_id, subjectId: projection.subject_id, visitInstanceId: projection.visit_instance_id }} projection={{ sourceModule: projection.source_module, sourceRecordId: projection.source_record_id, sourceTimestamp: projection.source_timestamp, projectedAt: projection.projected_at, sourceVersion: projection.source_version, ruleVersion: projection.rule_version, freshness: projection.freshness, status: projection.status, readOnly: true }} onProjectionRefresh={() => void projections.refetch()} projectionRefreshing={projections.isFetching}><div className="space-y-2"><ModuleBadge module={projection.source_module} state="projected" /><DefinitionList value={projection.payload} /></div></OwnershipCard>) : <RecordTable rows={[]} empty="Projections" actionHref={routePath('overview', { studyId }) ?? undefined} actionLabel="Open study operations" filters={filters} pagination={pagination} />}{pagination && <ServerPagination label="projections" pagination={pagination} />}</div></QueryState>
}
function ReportView({ studyId, reportType, context, filters, onPageChange }: { studyId: string; reportType: string; context: CTMSQueryContext; filters: CTMSQueryContext['filters']; onPageChange: (page: number) => void }) {
  const report = useCTMSReport(studyId, reportType, { ...context, filters: { ...context.filters, reportType: context.filters?.reportType ?? reportType } })
  const lastValid = useLastValidResult(report)
  return <QueryStateWithFallback query={report} label={`${reportType} operational report`} lastValid={lastValid}>{(data) => {
    const items = data.items ?? data.rows ?? []
    const pagination = data.page !== undefined && data.page_size !== undefined && data.total !== undefined ? { page: data.page, pageSize: data.page_size, total: data.total, onPageChange, isLoading: report.isFetching } : undefined
    return <div className="space-y-4"><Card title={`${titleFor('reports')} · ${reportType}`}><p className="text-sm text-muted-foreground">CTMS operational report for the server-authorized study scope. Rendered rows do not determine totals.</p>{data.generated_at && <p className="mt-2 text-xs text-muted-foreground">Generated at: {formatServerTimestamp(data.generated_at)}</p>}</Card><ServerReportTotals totals={data.totals} /><RecordTable rows={items} empty="Report" actionHref={routePath('overview', { studyId }) ?? undefined} actionLabel="Open study operations" filters={filters} pagination={pagination} /></div>
  }}</QueryStateWithFallback>
}

function ServerReportTotals({ totals }: { totals?: Record<string, unknown> }) {
  if (!totals || Object.keys(totals).length === 0) return null
  return <Card title="Server-reported totals"><dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(totals).map(([label, value]) => <div key={label}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{label.replaceAll('_', ' ')}</dt><dd className="mt-1 break-words text-lg font-semibold text-foreground">{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl><p className="mt-3 text-xs text-muted-foreground">Totals and row order are provided by the CTMS server for the active scope and filters.</p></Card>
}
function ServerPagination({ label, pagination }: { label: string; pagination: ResponsiveRecordPagination }) {
  const totalPages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize))
  if (pagination.total <= pagination.pageSize && pagination.page <= 1) return null
  return <nav aria-label={`${label} pagination`} className="flex flex-wrap items-center justify-between gap-3 border-t bg-gray-50 px-3 py-3" role="navigation"><p className="text-sm text-muted-foreground" aria-live="polite">Page {pagination.page} of {totalPages} ({pagination.total} total)</p><div className="flex gap-2"><button type="button" className="rounded border px-3 py-1.5 text-sm disabled:opacity-50" onClick={() => pagination.onPageChange(pagination.page - 1)} disabled={pagination.page <= 1 || pagination.isLoading}>Previous</button><button type="button" className="rounded border px-3 py-1.5 text-sm disabled:opacity-50" onClick={() => pagination.onPageChange(pagination.page + 1)} disabled={pagination.page >= totalPages || pagination.isLoading}>Next</button></div></nav>
}
function RemediationView({ kind, studyId, context }: { kind: 'failed' | 'conflict'; studyId: string; context: CTMSQueryContext }) {
  return kind === 'failed' ? <FailedEventsView studyId={studyId} context={context} /> : <ConflictsView studyId={studyId} context={context} />
}

function FailedEventsView({ studyId, context }: { studyId: string; context: CTMSQueryContext }) {
  const queryClient = useQueryClient()
  const failedEvents = useCTMSFailedEvents(studyId, context)
  const replay = useCTMSMutation<CTMSCoordinationEvent, unknown, { record: CTMSFailedEvent; reason: string }>({
    mutationFn: ({ record, reason }) => ctmsApi.replayEvent(record.event_id, reason),
    onSuccess: async (_, variables) => {
      await invalidateCTMSCoordinationRemediation(queryClient, studyId, variables.record)
    },
  })
  return <QueryState query={failedEvents} label="failed events"><CTMSMutationFeedback status={replay.status} action="Replay failed event" data={replay.data} error={replay.error} /><RemediationList kind="failed" rows={(failedEvents.data?.items ?? []) as CTMSFailedEvent[]} studyId={studyId} mutation={replay} onReplay={(record, reason) => replay.mutate({ record, reason })} /></QueryState>
}

function ConflictsView({ studyId, context }: { studyId: string; context: CTMSQueryContext }) {
  const queryClient = useQueryClient()
  const conflicts = useCTMSConflicts(studyId, context)
  const resolve = useCTMSMutation<CTMSConflict, unknown, { record: CTMSConflict; policy: string; reason: string }>({
    mutationFn: ({ record, policy, reason }) => ctmsApi.resolveConflict(record.id, policy, reason),
    onSuccess: async (_, variables) => {
      await invalidateCTMSCoordinationRemediation(queryClient, studyId, variables.record)
    },
  })
  return <QueryState query={conflicts} label="coordination conflicts"><CTMSMutationFeedback status={resolve.status} action="Resolve conflict" data={resolve.data} error={resolve.error} /><RemediationList kind="conflict" rows={(conflicts.data?.items ?? []) as CTMSConflict[]} studyId={studyId} mutation={resolve} onResolve={(record, policy, reason) => resolve.mutate({ record, policy, reason })} /></QueryState>
}

export function CTMSWorkspacePage({ view, studyId: requestedStudyId, siteId: requestedSiteId, reportType = 'dashboard' }: WorkspaceProps) {
  const navigate = useNavigate()
  const routeSearch = useSearch({ strict: false }) as Record<string, unknown>
  const search = parseCTMSSearch(routeSearch)
  const updateSearch = (next: CTMSSearchState) => void navigate({ search: serializeCTMSSearch(next) } as never)
  const onFilterChange = (change: Partial<CTMSSearchState>) => updateSearch({ ...search, ...change, page: 1, cursor: undefined })
  const onPageChange = (page: number) => updateSearch({ ...search, page, cursor: undefined })
  const onClearFilters = () => updateSearch({ page: undefined, pageSize: search.pageSize, cursor: undefined })
  const state = useCTMSCapabilityState()
  const selectedStudyId = useStudyContext((context) => context.selectedStudyId)
  const selectedSiteId = useStudyContext((context) => context.selectedSiteId)
  const studyId = requestedStudyId ?? selectedStudyId ?? undefined
  const siteId = requestedSiteId ?? selectedSiteId ?? undefined
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, studyId, siteId)

  if (state.status === 'disabled') return <DirectRouteState kind="disabled" title="CTMS is disabled or unavailable" message="CTMS is disabled. EDC clinical navigation and indicators remain available." />
  if (state.status === 'unavailable') return <DirectRouteState kind="unavailable" title="CTMS is unavailable" message="The CTMS capability manifest could not be loaded. Retry later or continue working in EDC." />
  if (!canRead) return <AccessDeniedPage />
  if (!hasCapability(state, view)) return <DirectRouteState kind="unavailable" title="CTMS view unavailable" message="This CTMS view is not delivered by the current server capability phase or manifest." />
  if (view !== 'health' && view !== 'activation' && view !== 'site-dashboard' && !studyId) return <section className="space-y-3 rounded-lg border bg-background p-6"><h1 className="text-2xl font-bold text-foreground">CTMS workspace</h1><p className="text-muted-foreground">Select a study to open its operational workspace.</p><a className="inline-flex rounded border border-info/40 bg-info/10 px-3 py-1.5 text-sm font-medium text-info-foreground hover:bg-info/20" href="/studies">Choose a study</a></section>

  const scope = { studyId, siteId }
  return <CTMSWorkspaceLayout view={view} scope={scope}><ViewContent view={view} scope={scope} reportType={reportType} search={search} onPageChange={onPageChange} onFilterChange={onFilterChange} onClearFilters={onClearFilters} /></CTMSWorkspaceLayout>
}

function DefinitionList({ value }: { value: object }) { const entries = Object.entries(value).filter(([key]) => !['payload', 'readiness_criteria'].includes(key)); if (!entries.length) return <EmptyState label="Operational data" actionHref="/studies" actionLabel="Choose an operational workspace" />; return <dl className="grid gap-3 sm:grid-cols-2">{entries.map(([key, item]) => <div key={key}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{key.replaceAll('_', ' ')}</dt><dd className="mt-1 break-words text-sm text-foreground">{typeof item === 'object' ? JSON.stringify(item) : String(item ?? '—')}</dd></div>)}</dl> }
function QualitySignals({ value, onRefresh, refreshing }: { value: CTMSQualitySignal[]; onRefresh?: () => void; refreshing?: boolean }) {
  if (!value.length) return <EmptyState label="Approved quality signals" actionHref="/studies" actionLabel="Choose an operational workspace" />
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{value.map((signal, index) => <QualitySignalPresentation key={signal.projection_id ?? index} signalType={String(signal.signal_type ?? 'Approved quality signal')} value={signal.value} metadata={{ sourceModule: signal.source_module ?? 'EDC', sourceRecordId: signal.source_record_id ?? signal.projection_id, sourceTimestamp: signal.source_timestamp, projectedAt: signal.projected_at, sourceVersion: signal.source_version, ruleVersion: signal.rule_version, freshness: signal.freshness, readOnly: true }} onRefresh={onRefresh} refreshing={refreshing} />)}</div>
}
function RemediationList({
  kind,
  rows,
  studyId,
  mutation,
  onReplay,
  onResolve,
}: {
  kind: 'failed' | 'conflict'
  rows: CTMSFailedEvent[] | CTMSConflict[]
  studyId: string
  mutation: { status: 'idle' | 'pending' | 'success' | 'error'; data?: unknown; error?: unknown; canMutate?: boolean }
  onReplay?: (record: CTMSFailedEvent, reason: string) => void
  onResolve?: (record: CTMSConflict, policy: string, reason: string) => void
}) {
  if (!rows.length) return <EmptyState label={kind === 'failed' ? 'Failed events' : 'Coordination conflicts'} actionHref={routePath('overview', { studyId }) ?? undefined} actionLabel="Open study operations" />
  return <div className="space-y-3">{kind === 'failed'
    ? (rows as CTMSFailedEvent[]).map((record) => <CoordinationRemediationPanel key={record.id} kind="failed" record={record} studyId={studyId} mutation={mutation} onReplay={(eventId, reason) => onReplay?.({ ...record, event_id: eventId }, reason)} />)
    : (rows as CTMSConflict[]).map((record) => <CoordinationRemediationPanel key={record.id} kind="conflict" record={record} studyId={studyId} mutation={mutation} onResolve={(conflictId, policy, reason) => onResolve?.({ ...record, id: conflictId }, policy, reason)} />)}</div>
}

function RecordTable({ rows, empty, actionHref, actionLabel, filters, pagination }: { rows: object[]; empty: string; actionHref?: string | null; actionLabel?: string; filters?: CTMSQueryContext['filters']; pagination?: ResponsiveRecordPagination }) {
  const activeFilters = activeCTMSFilters(filters ?? {})
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((key) => !['payload', 'sanitized_details'].includes(key)).slice(0, 7)
  const columns: ResponsiveRecordColumn<object>[] = keys.map((key) => ({
    key,
    label: key.replaceAll('_', ' '),
    status: key === 'status',
    date: key.endsWith('_at'),
  }))
  const emptyDescription = activeFilters.length > 0
    ? <>No {empty.toLowerCase()} match the active filters. <span className="block text-xs text-muted-foreground">Active filters: {activeFilters.map((filter) => `${filter.label}: ${String(filter.value)}`).join(', ')}</span></>
    : `${empty} has no records configured yet.`
  const emptyAction = actionHref && actionLabel ? <a className="inline-flex rounded border border-border bg-muted px-3 py-1.5 font-medium text-foreground hover:bg-accent" href={actionHref}>{actionLabel}</a> : undefined
  return (
    <DataTableShell
      label={empty}
      empty={rows.length === 0}
      emptyTitle={empty}
      emptyDescription={emptyDescription}
      emptyAction={emptyAction}
    >
      {rows.length > 0 ? <ResponsiveRecordList label={empty} rows={rows} columns={columns} emptyLabel={empty} rowKey={(row, index) => String((row as Record<string, unknown>).id ?? index)} filters={activeFilters} pagination={pagination} /> : null}
    </DataTableShell>
  )
}
