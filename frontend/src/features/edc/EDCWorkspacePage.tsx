import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertCircle, ArrowRight, Database, FileClock, ShieldCheck } from 'lucide-react'
import { AuditViewerPage } from '@/features/admin'
import { StudyDashboardPage } from '@/features/dashboards'
import { ExportCenterPage } from '@/features/exports'
import { QueryHistoryPage, QueryListPage } from '@/features/queries'
import { ReviewWorklistPage, SDVWorklistPage } from '@/features/quality'
import { SubjectListPage } from '@/features/subjects'
import { ClinicalControlPage, DataEntryNavigatorPage, DataListingsPage, IncompleteFormsPage } from './EDCOperationsPages'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ErrorState,
  LoadingState,
  MetricCard,
  OwnershipBadge,
  PageContainer,
  PageHeader,
  StatusBadge,
} from '@/components/patterns'

interface StudyMetrics {
  subject_counts_by_status: Record<string, number>
  total_form_instances: number
  submitted_form_instances: number
  open_query_count: number
}

interface QueryMetrics {
  open_count: number
  answered_count: number
  closed_count: number
  overdue_count: number
  average_days_open: number
}

interface ProgressMetrics {
  verified?: number
  not_verified?: number
  reviewed?: number
  not_reviewed?: number
}

export type EDCWorkspaceView =
  | 'overview-dashboard'
  | 'overview-progress'
  | 'overview-activities'
  | 'subject-list'
  | 'subject-profile'
  | 'subject-visits-forms'
  | 'data-entry'
  | 'incomplete-forms'
  | 'change-history'
  | 'review-dashboard'
  | 'forms-review'
  | 'sdv-sdr'
  | 'data-listings'
  | 'query-dashboard'
  | 'open-queries'
  | 'query-history'
  | 'coding-dashboard'
  | 'meddra-coding'
  | 'whodrug-coding'
  | 'coding-review'
  | 'dataset-exports'
  | 'export-history'
  | 'lock-readiness'
  | 'data-freeze'
  | 'database-lock'
  | 'lock-history'

export function EDCWorkspacePage({ studyId, view }: { studyId: string; view: EDCWorkspaceView }) {
  switch (view) {
    case 'overview-dashboard':
      return <StudyDashboardPage studyId={studyId} />
    case 'overview-progress':
      return <DataCollectionProgressPage studyId={studyId} />
    case 'overview-activities':
      return <OutstandingActivitiesPage studyId={studyId} />
    case 'subject-list':
    case 'subject-profile':
    case 'subject-visits-forms':
      return <SubjectListPage studyId={studyId} />
    case 'data-entry':
      return <DataEntryNavigatorPage studyId={studyId} />
    case 'incomplete-forms':
      return <IncompleteFormsPage studyId={studyId} />
    case 'change-history':
      return <AuditViewerPage />
    case 'review-dashboard':
      return <StudyDashboardPage studyId={studyId} dataCleaning />
    case 'forms-review':
      return <ReviewWorklistPage studyId={studyId} />
    case 'sdv-sdr':
      return <SDVWorklistPage studyId={studyId} />
    case 'data-listings':
      return <DataListingsPage studyId={studyId} />
    case 'query-dashboard':
      return <QueryDashboardPage studyId={studyId} />
    case 'open-queries':
      return <QueryListPage studyId={studyId} />
    case 'query-history':
      return <QueryHistoryPage studyId={studyId} />
    case 'dataset-exports':
    case 'export-history':
      return <ExportCenterPage studyId={studyId} />
    case 'lock-readiness':
    case 'database-lock':
      return <ClinicalControlPage studyId={studyId} defaultAction="lock" />
    case 'data-freeze':
      return <ClinicalControlPage studyId={studyId} defaultAction="freeze" />
    case 'lock-history':
      return <ClinicalControlPage studyId={studyId} historyOnly />
    default:
      return <CapabilityGapPage studyId={studyId} view={view} />
  }
}

function DataCollectionProgressPage({ studyId }: { studyId: string }) {
  const dashboard = useQuery({
    queryKey: ['study-dashboard', studyId],
    queryFn: async () => (await api.get<StudyMetrics>(`/studies/${studyId}/dashboard`)).data,
  })

  if (dashboard.isLoading) return <PageContainer><LoadingState label="data collection progress" /></PageContainer>
  if (dashboard.error || !dashboard.data) return <PageContainer><ErrorState message="Unable to load data collection progress." onRetry={() => void dashboard.refetch()} /></PageContainer>

  const totalSubjects = Object.values(dashboard.data.subject_counts_by_status ?? {}).reduce((sum, value) => sum + value, 0)
  const completed = dashboard.data.submitted_form_instances ?? 0
  const total = dashboard.data.total_form_instances ?? 0
  const percentage = total ? Math.round((completed / total) * 100) : 0

  return (
    <PageContainer>
      <PageHeader
        title="Data Collection Progress"
        description="Study-scoped subject and form completion derived from the EDC dashboard service."
        ownership={<OwnershipBadge owner="EDC" />}
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Total subjects" value={totalSubjects} />
        <MetricCard label="Form completion" value={`${percentage}%`} description={`${completed} of ${total} submitted`} />
        <MetricCard label="Incomplete forms" value={Math.max(total - completed, 0)} />
        <MetricCard label="Open queries" value={dashboard.data.open_query_count ?? 0} />
      </div>
      <Card className="mt-6">
        <CardHeader><CardTitle className="text-lg">Continue clinical data collection</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button asChild><Link to="/studies/$studyId/edc/subjects" params={{ studyId }}>Open subject list <ArrowRight className="size-4" /></Link></Button>
          <Button asChild variant="outline"><Link to="/studies/$studyId/edc/data-entry" params={{ studyId }}>Open data entry</Link></Button>
        </CardContent>
      </Card>
    </PageContainer>
  )
}

function OutstandingActivitiesPage({ studyId }: { studyId: string }) {
  const dashboard = useQuery({ queryKey: ['study-dashboard', studyId], queryFn: async () => (await api.get<StudyMetrics>(`/studies/${studyId}/dashboard`)).data })
  const queries = useQuery({ queryKey: ['query-metrics', studyId], queryFn: async () => (await api.get<QueryMetrics>(`/studies/${studyId}/query-metrics`)).data })
  const sdv = useQuery({ queryKey: ['sdv-progress', studyId], queryFn: async () => (await api.get<ProgressMetrics>(`/studies/${studyId}/sdv-progress`)).data })
  const review = useQuery({ queryKey: ['review-progress', studyId], queryFn: async () => (await api.get<ProgressMetrics>(`/studies/${studyId}/review-progress`)).data })
  const readiness = useQuery({ queryKey: ['lock-readiness', studyId], retry: false, queryFn: async () => (await api.get<{ ready: boolean; blockers: Array<{ code: string; count: number }> }>(`/studies/${studyId}/lock-readiness`)).data })
  const loading = dashboard.isLoading || queries.isLoading || sdv.isLoading || review.isLoading
  const failed = dashboard.error || queries.error || sdv.error || review.error

  if (loading) return <PageContainer><LoadingState label="outstanding EDC activities" /></PageContainer>
  if (failed || !dashboard.data) return <PageContainer><ErrorState message="Unable to load outstanding EDC activities." onRetry={() => void Promise.all([dashboard.refetch(), queries.refetch(), sdv.refetch(), review.refetch()])} /></PageContainer>

  const incomplete = Math.max((dashboard.data.total_form_instances ?? 0) - (dashboard.data.submitted_form_instances ?? 0), 0)
  const blockerCount = (code: string) => readiness.data?.blockers.find((item) => item.code === code)?.count ?? 0
  return (
    <PageContainer>
      <PageHeader title="Outstanding Activities" description="Actionable clinical work calculated from current, authorized EDC records." ownership={<OwnershipBadge owner="EDC" />} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard label="Incomplete forms" value={incomplete} status={<StatusBadge status={incomplete ? 'Needs attention' : 'Complete'} label="Form workload" />} />
        <MetricCard label="Open queries" value={queries.data?.open_count ?? dashboard.data.open_query_count ?? 0} status={<StatusBadge status={(queries.data?.overdue_count ?? 0) > 0 ? 'Overdue' : 'Current'} label="Query workload" />} />
        <MetricCard label="Pending SDV" value={sdv.data?.not_verified ?? 0} />
        <MetricCard label="Pending review" value={review.data?.not_reviewed ?? 0} />
        <MetricCard label="Pending SDR" value={blockerCount('PENDING_SDR')} />
        <MetricCard label="Validation findings" value={blockerCount('VALIDATION_FINDINGS')} />
        <MetricCard label="Lock readiness" value={readiness.data ? (readiness.data.ready ? 'Ready' : 'Blocked') : 'Restricted'} status={readiness.data ? <StatusBadge status={readiness.data.ready ? 'Ready' : 'Blocked'} label="Database lock readiness" /> : undefined} />
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        <WorkspaceLink title="Incomplete forms" description="Locate subjects and open the affected eCRF." to="/studies/$studyId/edc/data-entry/incomplete-forms" studyId={studyId} />
        <WorkspaceLink title="Query inbox" description={`${queries.data?.overdue_count ?? 0} queries are overdue.`} to="/studies/$studyId/edc/queries/open" studyId={studyId} />
        <WorkspaceLink title="Review worklists" description="Continue SDV and clinical review." to="/studies/$studyId/edc/data-review" studyId={studyId} />
        <WorkspaceLink title="Lock readiness" description="Resolve validation, quality, query, and signature blockers." to="/studies/$studyId/edc/database-lock" studyId={studyId} />
      </div>
    </PageContainer>
  )
}

function QueryDashboardPage({ studyId }: { studyId: string }) {
  const query = useQuery({
    queryKey: ['query-metrics', studyId],
    queryFn: async () => (await api.get<QueryMetrics>(`/studies/${studyId}/query-metrics`)).data,
  })
  if (query.isLoading) return <PageContainer><LoadingState label="query dashboard" /></PageContainer>
  if (query.error || !query.data) return <PageContainer><ErrorState message="Unable to load query metrics." onRetry={() => void query.refetch()} /></PageContainer>

  return (
    <PageContainer>
      <PageHeader title="Query Dashboard" description="Study-scoped query workload and aging from the EDC query service." ownership={<OwnershipBadge owner="EDC" />} actions={<Button asChild><Link to="/studies/$studyId/edc/queries/open" params={{ studyId }}>Open query inbox</Link></Button>} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard label="Open" value={query.data.open_count} />
        <MetricCard label="Answered" value={query.data.answered_count} />
        <MetricCard label="Closed" value={query.data.closed_count} />
        <MetricCard label="Overdue" value={query.data.overdue_count} />
        <MetricCard label="Average days open" value={query.data.average_days_open.toFixed(1)} />
      </div>
    </PageContainer>
  )
}

function WorkspaceLink({ title, description, to, studyId }: { title: string; description: string; to: string; studyId: string }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent>
        <p className="mb-4 text-sm text-muted-foreground">{description}</p>
        <Button asChild variant="outline" size="sm"><Link to={to} params={{ studyId }}>Open <ArrowRight className="size-4" /></Link></Button>
      </CardContent>
    </Card>
  )
}

const GAP_COPY: Partial<Record<EDCWorkspaceView, { title: string; description: string; requirement: string }>> = {
  'coding-dashboard': { title: 'Coding Dashboard', description: 'The repository does not currently expose an EDC medical-coding service.', requirement: 'Licensed dictionary integration, coding queues, permissions, and audit contracts' },
  'meddra-coding': { title: 'MedDRA Coding', description: 'No licensed MedDRA dictionary endpoint is configured. Terminology mappings are intentionally not fabricated.', requirement: 'Licensed MedDRA lookup, dictionary versioning, candidate selection, and approval API' },
  'whodrug-coding': { title: 'WHODrug Coding', description: 'No licensed WHODrug dictionary endpoint is configured. Medication mappings are intentionally not fabricated.', requirement: 'Licensed WHODrug lookup, dictionary versioning, indication/route context, and approval API' },
  'coding-review': { title: 'Coding Review', description: 'Coding review cannot be enabled until coded-term proposals and reviewer permissions exist on the backend.', requirement: 'Coding proposal lifecycle, review history, recoding rules, and reviewer authorization' },
}

function CapabilityGapPage({ studyId, view }: { studyId: string; view: EDCWorkspaceView }) {
  const copy = GAP_COPY[view] ?? { title: 'EDC Workspace', description: 'This workflow is not available through the current backend contracts.', requirement: 'Backend capability required' }
  return (
    <PageContainer>
      <PageHeader title={copy.title} description={copy.description} ownership={<OwnershipBadge owner="EDC" />} status={<StatusBadge status="Capability required" label="Availability" tone="warning" />} />
      <Card>
        <CardContent className="flex flex-col gap-5 p-6 sm:flex-row sm:items-start">
          <div className="rounded-lg bg-warning/10 p-3 text-warning-foreground"><AlertCircle className="size-6" aria-hidden="true" /></div>
          <div className="min-w-0 flex-1 space-y-2">
            <h2 className="text-lg font-semibold">Backend capability required</h2>
            <p className="text-sm text-muted-foreground">{copy.requirement}</p>
            <div className="flex flex-wrap gap-2 pt-2">
              <Button asChild variant="outline"><Link to="/studies/$studyId/edc/subjects" params={{ studyId }}><FileClock className="size-4" />Open subjects</Link></Button>
              <Button asChild variant="outline"><Link to="/studies/$studyId/edc/overview/outstanding-activities" params={{ studyId }}><ShieldCheck className="size-4" />Outstanding activities</Link></Button>
              <Button asChild variant="ghost"><Link to="/studies/$studyId/edc/overview" params={{ studyId }}><Database className="size-4" />EDC dashboard</Link></Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
