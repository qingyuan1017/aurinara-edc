import { useQuery } from '@tanstack/react-query'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  DataTableShell,
  LoadingState,
  ErrorState,
  MetricCard,
  PageContainer,
  PageHeader,
  PageToolbar,
  StatusBadge,
} from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useStudyContext } from '@/lib/study-context'

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
  cancelled_count: number
  overdue_count: number
  average_days_open: number
}

interface Progress {
  verified?: number
  not_verified?: number
  reviewed?: number
  not_reviewed?: number
}

function ProgressMetricCard({ label, done, total }: { label: string; done: number; total: number }) {
  const percentage = total ? Math.round((done / total) * 100) : 0

  return (
    <MetricCard
      label={label}
      value={`${percentage}%`}
      description={`${done} of ${total} complete`}
      status={(
        <div
          aria-label={`${label}: ${percentage}% complete`}
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={percentage}
          className="h-2 w-full rounded-full bg-muted"
          role="progressbar"
        >
          <div className="h-2 rounded-full bg-primary" style={{ width: `${percentage}%` }} />
        </div>
      )}
    />
  )
}

export function StudyDashboardPage({ studyId, dataCleaning = false }: { studyId: string; dataCleaning?: boolean }) {
  const siteId = useStudyContext((state) => state.selectedSiteId)
  const study = useQuery({
    queryKey: ['study-dashboard', studyId],
    queryFn: async () => (await api.get<StudyMetrics>(`/studies/${studyId}/dashboard`)).data,
  })
  const queries = useQuery({
    queryKey: ['query-metrics', studyId],
    queryFn: async () => (await api.get<QueryMetrics>(`/studies/${studyId}/query-metrics`)).data,
  })
  const sdv = useQuery({
    queryKey: ['sdv-progress', studyId],
    queryFn: async () => (await api.get<Progress>(`/studies/${studyId}/sdv-progress`)).data,
  })
  const review = useQuery({
    queryKey: ['review-progress', studyId],
    queryFn: async () => (await api.get<Progress>(`/studies/${studyId}/review-progress`)).data,
  })
  const site = useQuery({
    queryKey: ['site-dashboard', siteId],
    enabled: Boolean(siteId),
    queryFn: async () => (await api.get<StudyMetrics>(`/sites/${siteId}/dashboard`)).data,
  })

  if (study.isLoading) {
    return (
      <PageContainer>
        <PageHeader
          title={dataCleaning ? 'Data-cleaning dashboard' : 'Study dashboard'}
          description="Operational quality metrics scoped to your study permissions."
        />
        <LoadingState label="dashboard metrics" />
      </PageContainer>
    )
  }

  if (study.error || !study.data) {
    return (
      <PageContainer>
        <PageHeader
          title={dataCleaning ? 'Data-cleaning dashboard' : 'Study dashboard'}
          description="Operational quality metrics scoped to your study permissions."
        />
        <ErrorState state="error" title="Failed to load dashboard metrics." message="Please try again or return to the study." onRetry={() => void study.refetch()} />
      </PageContainer>
    )
  }

  const data = study.data
  const subjectCounts = data.subject_counts_by_status ?? {}
  const subjectStatuses = Object.entries(subjectCounts)
  const totalSubjects = Object.values(subjectCounts).reduce((sum, count) => sum + count, 0)
  const formTotal = data.total_form_instances ?? 0
  const siteData = site.data

  return (
    <PageContainer>
      <PageHeader
        title={dataCleaning ? 'Data-cleaning dashboard' : 'Study dashboard'}
        description="Operational quality metrics scoped to your study permissions."
        actions={(
          <Button asChild variant="link" size="sm">
            <a href={`/studies/${studyId}`}>← Back to study</a>
          </Button>
        )}
      />

      <PageToolbar label="Dashboard scope">
        <span className="text-sm text-muted-foreground">Study scope: {studyId}</span>
        {siteId ? <StatusBadge status="Selected site" label="Study context" /> : null}
      </PageToolbar>

      <section aria-labelledby="study-progress-heading" className="space-y-3">
        <h2 id="study-progress-heading" className="text-lg font-semibold tracking-tight">Study progress</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <MetricCard label="Subjects" value={totalSubjects} />
          <MetricCard label="Forms" value={formTotal} />
          <MetricCard label="Submitted forms" value={data.submitted_form_instances} />
          <MetricCard label="Open queries" value={data.open_query_count} />
          <MetricCard label="Overdue queries" value={queries.data?.overdue_count ?? '—'} />
        </div>
      </section>

      <section aria-labelledby="data-cleaning-progress-heading" className="mt-8 space-y-3">
        <h2 id="data-cleaning-progress-heading" className="text-lg font-semibold tracking-tight">Data-cleaning progress</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <ProgressMetricCard
            label="Source data verification"
            done={sdv.data?.verified ?? 0}
            total={(sdv.data?.verified ?? 0) + (sdv.data?.not_verified ?? 0)}
          />
          <ProgressMetricCard
            label="Clinical review"
            done={review.data?.reviewed ?? 0}
            total={(review.data?.reviewed ?? 0) + (review.data?.not_reviewed ?? 0)}
          />
        </div>
      </section>

      <section className="mt-8 grid gap-6 lg:grid-cols-2">
        <DataTableShell
          label="Subjects by status"
          empty={subjectStatuses.length === 0}
          emptyTitle="No subject data available."
          emptyDescription="Status counts will appear when subject records are available."
        >
          <Table>
            <caption className="sr-only">Subjects by status</caption>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Subjects</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {subjectStatuses.map(([status, count]) => (
                <TableRow key={status}>
                  <TableCell><StatusBadge status={status} label="Subject status" /></TableCell>
                  <TableCell className="text-right font-semibold">{count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableShell>

        <section aria-labelledby="query-aging-heading" className="space-y-3">
          <h2 id="query-aging-heading" className="text-lg font-semibold tracking-tight">Query aging</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard label="Open" value={queries.data?.open_count ?? '—'} />
            <MetricCard label="Answered" value={queries.data?.answered_count ?? '—'} />
            <MetricCard label="Closed" value={queries.data?.closed_count ?? '—'} />
            <MetricCard label="Avg days open" value={queries.data?.average_days_open?.toFixed(1) ?? '—'} />
          </div>
        </section>
      </section>

      {siteId ? (
        <section aria-labelledby="selected-site-heading" className="mt-8 space-y-3 rounded-lg border bg-primary/5 p-5">
          <h2 id="selected-site-heading" className="text-lg font-semibold tracking-tight">Selected site progress</h2>
          {siteData ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <MetricCard label="Site subjects" value={Object.values(siteData.subject_counts_by_status ?? {}).reduce((sum, count) => sum + count, 0)} />
              <MetricCard label="Site forms" value={siteData.total_form_instances} />
              <MetricCard label="Site submitted" value={siteData.submitted_form_instances} />
              <MetricCard label="Site open queries" value={siteData.open_query_count} />
            </div>
          ) : (
            <LoadingState label="selected site metrics" className="border-0 bg-transparent p-0" />
          )}
        </section>
      ) : null}
    </PageContainer>
  )
}

export function DataCleaningDashboardPage({ studyId }: { studyId: string }) {
  return <StudyDashboardPage studyId={studyId} dataCleaning />
}
