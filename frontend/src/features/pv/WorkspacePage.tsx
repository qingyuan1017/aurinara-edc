import * as React from 'react'
import { createColumnHelper, type ColumnDef } from '@tanstack/react-table'
import { useStudyContext } from '@/lib/study-context'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useAuthStore } from '@/lib/auth'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import {
  DataTableShell,
  DetailCard,
  ErrorState,
  MetricCard,
  PageContainer,
  PageHeader,
  PageToolbar,
} from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { usePVCapabilityState, isPVActionAvailable, PV_ACTION_ROUTE_MAP, type PVCapabilityState } from './capabilities'
import { resolvePVNavigation } from './navigation'
import {
  isPVCaseClosed,
  usePVAdverseEvents,
  usePVAudit,
  usePVCase,
  usePVCaseAudit,
  usePVCases,
  usePVDashboard,
  usePVExports,
  usePVMedDraCoding,
  usePVNarratives,
  usePVNarrativeVersions,
  usePVReconciliation,
  usePVReports,
  usePVSeriousness,
  usePVSiteDashboard,
  usePVVersions,
  usePVWhoDrugCoding,
  type PVAdverseEventRecord,
  type PVAuditEvent,
  type PVCaseNarrative,
  type PVExportJob,
  type PVReconciliationRun,
  type PVRegulatoryReport,
  type PVSafetyCase,
} from './api'
import { PVDataTable, PVHistoryDialog, PVSourceLabel, PVStatus } from './components'
import {
  AdverseEventForm,
  CaseIntakeForm,
  NarrativeForm,
  NarrativeRevisionForm,
  SeriousnessForm,
} from './forms/PVForms'

export type PVView =
  | 'dashboard'
  | 'site-dashboard'
  | 'cases'
  | 'case-detail'
  | 'assessments'
  | 'coding'
  | 'narratives'
  | 'reports'
  | 'reconciliation'
  | 'exports'
  | 'audit'

interface WorkspaceProps {
  view: PVView
  studyId?: string
  siteId?: string
  caseId?: string
}

interface Scope {
  studyId?: string
  siteId?: string
  caseId?: string
}

/** Route/capability descriptor used to gate whether a view may render. */
const VIEW_DESCRIPTOR: Record<PVView, keyof typeof PV_ACTION_ROUTE_MAP> = {
  dashboard: 'dashboard',
  'site-dashboard': 'siteDashboard',
  cases: 'cases',
  'case-detail': 'cases',
  assessments: 'assessments',
  coding: 'coding',
  narratives: 'narratives',
  reports: 'reports',
  reconciliation: 'reconciliation',
  exports: 'exports',
  audit: 'audit',
}

function titleFor(view: PVView): string {
  return {
    dashboard: 'Safety dashboard',
    'site-dashboard': 'Site safety dashboard',
    cases: 'Safety cases',
    'case-detail': 'Safety case',
    assessments: 'Assessments',
    coding: 'Coding',
    narratives: 'Narratives',
    reports: 'Regulatory reports',
    reconciliation: 'EDC reconciliation',
    exports: 'Safety exports',
    audit: 'Safety audit',
  }[view]
}

function formatTimestamp(value?: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function DirectRouteState({ kind, title }: { kind: 'disabled' | 'unavailable'; title: string }) {
  const message =
    kind === 'disabled'
      ? 'The PV/Safety module is disabled for this environment. EDC and CTMS navigation are unaffected.'
      : 'PV safety data is temporarily unavailable. This does not change EDC or CTMS authorization or navigation.'
  return (
    <PageContainer>
      <DataTableShell
        label={title}
        state={kind}
        stateSlots={{
          [kind]: (
            <ErrorState
              state={kind}
              title={title}
              message={message}
              actions={
                <Button asChild variant="outline" size="sm">
                  <a href="/">Return to EDC dashboard</a>
                </Button>
              }
            />
          ),
        }}
      />
    </PageContainer>
  )
}

function WorkspaceNavigation({
  view,
  scope,
  state,
  permissions,
}: {
  view: PVView
  scope: Scope
  state: PVCapabilityState
  permissions: readonly string[]
}) {
  const sections = resolvePVNavigation(state, permissions, scope)
  if (sections.length === 0) return null
  const currentPath = PV_ACTION_ROUTE_MAP[VIEW_DESCRIPTOR[view]].route
  return (
    <nav aria-label="PV workspace sections" className="flex flex-wrap gap-2">
      {sections.flatMap((section) =>
        section.items.map((item) => {
          const active = PV_ACTION_ROUTE_MAP[item.id].route === currentPath
          return (
            <Button key={`${section.id}-${item.id}`} asChild variant={active ? 'default' : 'outline'} size="sm">
              <a href={item.to} aria-current={active ? 'page' : undefined}>
                {item.label}
              </a>
            </Button>
          )
        }),
      )}
    </nav>
  )
}

/* ----------------------------------------------------------------------- */
/* Table column helpers                                                     */
/* ----------------------------------------------------------------------- */

const caseColumnHelper = createColumnHelper<PVSafetyCase>()
const reportColumnHelper = createColumnHelper<PVRegulatoryReport>()
const reconColumnHelper = createColumnHelper<PVReconciliationRun>()

function caseColumns(studyId: string): ColumnDef<PVSafetyCase, unknown>[] {
  return [
    caseColumnHelper.accessor('case_identifier', {
      header: 'Case ID',
      cell: (ctx) => (
        <a className="font-medium text-primary underline-offset-2 hover:underline" href={`/studies/${studyId}/pv/cases/${ctx.row.original.id}`}>
          {ctx.getValue()}
        </a>
      ),
    }),
    caseColumnHelper.accessor('subject_reference', { header: 'Subject', cell: (ctx) => ctx.getValue() }),
    caseColumnHelper.accessor('case_type', { header: 'Type', cell: (ctx) => ctx.getValue() }),
    caseColumnHelper.accessor('lifecycle_state', {
      header: 'Status',
      cell: (ctx) => <PVStatus status={ctx.getValue()} label="Case status" />,
    }),
    caseColumnHelper.accessor('created_at', { header: 'Created', cell: (ctx) => formatTimestamp(ctx.getValue()) }),
  ] as ColumnDef<PVSafetyCase, unknown>[]
}

const reportColumns: ColumnDef<PVRegulatoryReport, unknown>[] = [
  reportColumnHelper.accessor('report_type', { header: 'Report type', cell: (ctx) => ctx.getValue() }),
  reportColumnHelper.accessor('destination', { header: 'Destination', cell: (ctx) => ctx.getValue() }),
  reportColumnHelper.accessor('status', {
    header: 'Status',
    cell: (ctx) => <PVStatus status={ctx.getValue()} label="Report status" />,
  }),
  reportColumnHelper.accessor('due_date', { header: 'Due', cell: (ctx) => formatTimestamp(ctx.getValue()) }),
  reportColumnHelper.accessor('overdue', {
    header: 'Overdue',
    cell: (ctx) => (ctx.getValue() ? 'Yes' : 'No'),
  }),
] as ColumnDef<PVRegulatoryReport, unknown>[]

const reconColumns: ColumnDef<PVReconciliationRun, unknown>[] = [
  reconColumnHelper.accessor('created_at', { header: 'Run', cell: (ctx) => formatTimestamp(ctx.getValue()) }),
  reconColumnHelper.accessor('match_count', { header: 'Matches', cell: (ctx) => ctx.getValue() }),
  reconColumnHelper.accessor('discrepancy_count', { header: 'Discrepancies', cell: (ctx) => ctx.getValue() }),
  reconColumnHelper.accessor('status', {
    header: 'Status',
    cell: (ctx) => <PVStatus status={ctx.getValue()} label="Reconciliation status" />,
  }),
] as ColumnDef<PVReconciliationRun, unknown>[]

const exportColumnHelper = createColumnHelper<PVExportJob>()
const exportColumns: ColumnDef<PVExportJob, unknown>[] = [
  exportColumnHelper.accessor('export_type', { header: 'Format', cell: (ctx) => ctx.getValue() }),
  exportColumnHelper.accessor('status', {
    header: 'Status',
    cell: (ctx) => <PVStatus status={ctx.getValue()} label="Export status" />,
  }),
  exportColumnHelper.accessor('created_at', { header: 'Created', cell: (ctx) => formatTimestamp(ctx.getValue()) }),
  exportColumnHelper.accessor('completed_at', { header: 'Completed', cell: (ctx) => formatTimestamp(ctx.getValue()) }),
] as ColumnDef<PVExportJob, unknown>[]

const auditColumnHelper = createColumnHelper<PVAuditEvent>()
const auditColumns: ColumnDef<PVAuditEvent, unknown>[] = [
  auditColumnHelper.accessor('timestamp', { header: 'Timestamp (UTC)', cell: (ctx) => formatTimestamp(ctx.getValue()) }),
  auditColumnHelper.accessor('entity_type', { header: 'Entity', cell: (ctx) => ctx.getValue() }),
  auditColumnHelper.accessor('action', { header: 'Action', cell: (ctx) => ctx.getValue() }),
  auditColumnHelper.accessor('actor_id', { header: 'Actor', cell: (ctx) => ctx.getValue() ?? '—' }),
  auditColumnHelper.accessor('reason', { header: 'Reason', cell: (ctx) => ctx.getValue() ?? '—' }),
] as ColumnDef<PVAuditEvent, unknown>[]

/* ----------------------------------------------------------------------- */
/* Views                                                                    */
/* ----------------------------------------------------------------------- */

function metricEntries(record: Record<string, number> | undefined): [string, number][] {
  return Object.entries(record ?? {})
}

function DashboardView({ studyId }: { studyId: string }) {
  const dashboard = usePVDashboard(studyId)
  if (dashboard.isLoading) return <DataTableShell label="safety dashboard" state="loading" />
  if (dashboard.error) {
    return (
      <DataTableShell
        label="safety dashboard"
        state="error"
        onRetry={() => void dashboard.refetch()}
        errorMessage="Unable to load the safety dashboard."
      />
    )
  }
  const data = dashboard.data
  if (!data) return null
  const compliance = data.reporting_compliance
  return (
    <div className="space-y-4">
      <DetailCard title="Cases by status">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metricEntries(data.case_counts_by_status).map(([status, count]) => (
            <MetricCard key={status} label={status} value={count} />
          ))}
        </div>
      </DetailCard>
      <DetailCard title="Adverse events by seriousness">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metricEntries(data.adverse_event_counts_by_seriousness).map(([status, count]) => (
            <MetricCard key={status} label={status} value={count} />
          ))}
        </div>
      </DetailCard>
      <DetailCard title="Reporting compliance">
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricCard label="Submitted" value={compliance?.submitted ?? 0} />
          <MetricCard label="Overdue" value={compliance?.overdue ?? 0} />
          <MetricCard label="On time" value={compliance?.on_time ?? 0} />
        </div>
      </DetailCard>
      {data.projected_fields.length > 0 ? (
        <DetailCard title="Read-only projections" description="Approved EDC/CTMS projections shown for reference; excluded from PV metrics.">
          <ul className="space-y-1 text-sm">
            {data.projected_fields.map((projection) => (
              <li key={projection.projection_id} className="flex items-center gap-2">
                <PVSourceLabel source={projection.source_module} />
                <span>{projection.field_name}</span>
              </li>
            ))}
          </ul>
        </DetailCard>
      ) : null}
      <p className="text-xs text-muted-foreground">Generated at: {formatTimestamp(data.generated_at)}</p>
    </div>
  )
}

function SiteDashboardView({ siteId, studyId }: { siteId: string; studyId?: string }) {
  const dashboard = usePVSiteDashboard(siteId, studyId)
  if (dashboard.isLoading) return <DataTableShell label="site safety dashboard" state="loading" />
  if (dashboard.error) {
    return (
      <DataTableShell
        label="site safety dashboard"
        state="error"
        onRetry={() => void dashboard.refetch()}
        errorMessage="Unable to load the site safety dashboard."
      />
    )
  }
  const data = dashboard.data
  if (!data) return null
  return (
    <div className="space-y-4">
      <DetailCard title="Cases by status">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metricEntries(data.case_counts_by_status).map(([status, count]) => (
            <MetricCard key={status} label={status} value={count} />
          ))}
        </div>
      </DetailCard>
      <p className="text-xs text-muted-foreground">Generated at: {formatTimestamp(data.generated_at)}</p>
    </div>
  )
}

function CaseListView({ studyId }: { studyId: string }) {
  const cases = usePVCases(studyId)
  const canEnter = usePermission(PERMISSIONS.PV_SAFETY_CASE_ENTER, studyId)
  const [showForm, setShowForm] = React.useState(false)
  return (
    <div className="space-y-4">
      {canEnter ? (
        <div className="flex justify-end">
          <Button type="button" size="sm" onClick={() => setShowForm((prev) => !prev)}>
            {showForm ? 'Close' : 'New case'}
          </Button>
        </div>
      ) : null}
      {canEnter && showForm ? (
        <CaseIntakeForm studyId={studyId} onSaved={() => setShowForm(false)} onCancel={() => setShowForm(false)} />
      ) : null}
      <PVDataTable
        label="safety cases"
        columns={caseColumns(studyId)}
        data={cases.data?.items ?? []}
        isLoading={cases.isLoading}
        isFetching={cases.isFetching}
        error={cases.error}
        onRetry={() => void cases.refetch()}
        errorMessage="Unable to load safety cases."
        emptyDescription="No safety cases match the current scope."
      />
    </div>
  )
}

function CaseAuditHistory({ caseId }: { caseId: string }) {
  const audit = usePVCaseAudit(caseId)
  if (audit.isLoading) return <p className="text-sm text-muted-foreground">Loading audit history…</p>
  if (audit.error) {
    return <p className="text-sm text-destructive">Unable to load the case audit history.</p>
  }
  const items = audit.data?.items ?? []
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No audit events recorded for this case.</p>
  return (
    <ol className="space-y-2">
      {items.map((event) => (
        <li key={event.id} className="rounded-md border p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{event.action}</span>
            <span className="text-xs text-muted-foreground">{event.entity_type}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {formatTimestamp(event.timestamp)} · {event.actor_id ?? 'system'}
            {event.reason ? ` · ${event.reason}` : ''}
          </p>
        </li>
      ))}
    </ol>
  )
}

function CaseHeader({ safetyCase, studyId }: { safetyCase: PVSafetyCase; studyId: string }) {
  const closed = isPVCaseClosed(safetyCase.lifecycle_state)
  return (
    <DetailCard
      title={`Case ${safetyCase.case_identifier}`}
      description={
        <span className="flex flex-wrap items-center gap-2">
          <PVStatus status={safetyCase.lifecycle_state} label="Case status" />
          <span className="text-xs text-muted-foreground">Subject reference</span>
          <PVSourceLabel source="EDC" />
          <span>{safetyCase.subject_reference}</span>
        </span>
      }
    >
      <nav aria-label="Case sections" className="flex flex-wrap gap-2">
        {[
          { label: 'Overview', path: '' },
          { label: 'Assessments', path: '/assessments' },
          { label: 'Coding', path: '/coding' },
          { label: 'Narratives', path: '/narratives' },
          { label: 'Reports', path: '/reports' },
        ].map((tab) => (
          <Button key={tab.label} asChild variant="outline" size="sm">
            <a href={`/studies/${studyId}/pv/cases/${safetyCase.id}${tab.path}`}>{tab.label}</a>
          </Button>
        ))}
        {/* Audit history opens in a dialog while this status view stays mounted (19.5). */}
        <PVHistoryDialog
          title="Case audit history"
          description="Immutable PV safety audit events for this case, ordered by UTC timestamp."
          triggerLabel="View audit history"
        >
          <CaseAuditHistory caseId={safetyCase.id} />
        </PVHistoryDialog>
      </nav>
      {closed ? (
        <p className="mt-3 text-xs text-muted-foreground" role="note">
          This case is Closed. Input controls are disabled; the server enforces the same restriction.
        </p>
      ) : null}
    </DetailCard>
  )
}

function CaseVersionsSection({ caseId }: { caseId: string }) {
  const versions = usePVVersions(caseId)
  const items = versions.data?.items ?? []
  return (
    <DetailCard title="Case versions" description="Initial and follow-up reports; submitted versions are immutable.">
      {versions.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading versions…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No case versions submitted yet.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((version) => (
            <li key={version.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm">
              <span className="font-medium">
                {version.version_kind} · v{version.sequence_number}
              </span>
              {/* Same textual status value as any list view (19.1). */}
              <PVStatus status={version.status} label="Version status" />
              <span className="text-xs text-muted-foreground">
                {version.submitted_at ? `Submitted ${formatTimestamp(version.submitted_at)}` : 'Draft'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </DetailCard>
  )
}

function CaseDetailView({ studyId, caseId }: { studyId: string; caseId: string }) {
  const safetyCase = usePVCase(caseId)
  const adverseEvents = usePVAdverseEvents(caseId)
  const canEnter = usePermission(PERMISSIONS.PV_SAFETY_CASE_ENTER, studyId)
  if (safetyCase.isLoading) return <DataTableShell label="safety case" state="loading" />
  if (safetyCase.error || !safetyCase.data) {
    return (
      <DataTableShell
        label="safety case"
        state="error"
        onRetry={() => void safetyCase.refetch()}
        errorMessage="Unable to load the safety case."
      />
    )
  }
  const closed = isPVCaseClosed(safetyCase.data.lifecycle_state)
  const aeColumns: ColumnDef<PVAdverseEventRecord, unknown>[] = [
    { accessorKey: 'verbatim_term', header: 'Verbatim term' },
    { accessorKey: 'onset_date', header: 'Onset' },
    { accessorKey: 'outcome', header: 'Outcome' },
    { accessorKey: 'resolution_date', header: 'Resolution', cell: (ctx) => (ctx.getValue() as string) ?? '—' },
  ]
  return (
    <div className="space-y-4">
      <CaseHeader safetyCase={safetyCase.data} studyId={studyId} />
      <CaseVersionsSection caseId={caseId} />
      {canEnter ? (
        <AdverseEventForm caseId={caseId} disabled={closed} />
      ) : null}
      <PVDataTable
        label="adverse events"
        columns={aeColumns as ColumnDef<PVAdverseEventRecord, unknown>[]}
        data={adverseEvents.data?.items ?? []}
        isLoading={adverseEvents.isLoading}
        isFetching={adverseEvents.isFetching}
        error={adverseEvents.error}
        onRetry={() => void adverseEvents.refetch()}
        emptyDescription="No adverse events captured for this case."
      />
    </div>
  )
}

function AssessmentsView({ studyId, caseId }: { studyId: string; caseId: string }) {
  const safetyCase = usePVCase(caseId)
  const adverseEvents = usePVAdverseEvents(caseId)
  const canAssess = usePermission(PERMISSIONS.PV_SAFETY_ASSESSMENT_RECORD, studyId)
  const closed = isPVCaseClosed(safetyCase.data?.lifecycle_state)
  const events = adverseEvents.data?.items ?? []
  return (
    <div className="space-y-4">
      {safetyCase.data ? <CaseHeader safetyCase={safetyCase.data} studyId={studyId} /> : null}
      {adverseEvents.isLoading ? <DataTableShell label="assessments" state="loading" /> : null}
      {!adverseEvents.isLoading && events.length === 0 ? (
        <DataTableShell label="assessments" state="empty" emptyDescription="Capture an adverse event before recording assessments." />
      ) : null}
      {events.map((event) => (
        <DetailCard
          key={event.id}
          title={`Assessment · ${event.verbatim_term}`}
          description={<SeriousnessStatus aeId={event.id} />}
        >
          {canAssess ? (
            <SeriousnessForm aeId={event.id} caseId={caseId} disabled={closed} />
          ) : (
            <p className="text-sm text-muted-foreground">You have read-only access to safety assessments.</p>
          )}
        </DetailCard>
      ))}
    </div>
  )
}

/**
 * Renders the persisted seriousness determination as the same textual status
 * value used across list and detail views (19.1). Serious/Not serious is a
 * safety assessment state.
 */
function SeriousnessStatus({ aeId }: { aeId: string }) {
  const assessments = usePVSeriousness(aeId)
  if (assessments.isLoading) {
    return <span className="text-xs text-muted-foreground">Loading assessment…</span>
  }
  const latest = assessments.data?.items?.[0]
  if (!latest) {
    return <span className="text-xs text-muted-foreground">No seriousness assessment recorded.</span>
  }
  const status = latest.serious ? 'Serious' : 'Not serious'
  return (
    <span className="flex flex-wrap items-center gap-2">
      <PVStatus status={status} label="Seriousness" />
      {latest.serious && latest.criteria.length > 0 ? (
        <span className="text-xs text-muted-foreground">{latest.criteria.join(', ')}</span>
      ) : null}
    </span>
  )
}

function CodingView({ studyId, caseId }: { studyId: string; caseId: string }) {
  const safetyCase = usePVCase(caseId)
  const meddra = usePVMedDraCoding(caseId)
  const whodrug = usePVWhoDrugCoding(caseId)
  const meddraItems = meddra.data?.items ?? []
  const whodrugItems = whodrug.data?.items ?? []
  return (
    <div className="space-y-4">
      {safetyCase.data ? <CaseHeader safetyCase={safetyCase.data} studyId={studyId} /> : null}
      <DetailCard title="MedDRA coding" description="Coding assignments retain their dictionary versions immutably.">
        {meddra.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading MedDRA coding…</p>
        ) : meddraItems.length === 0 ? (
          <p className="text-sm text-muted-foreground">No MedDRA coding assigned for this case.</p>
        ) : (
          <ul className="space-y-2">
            {meddraItems.map((coding) => (
              <li key={coding.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm">
                <span className="font-medium">{coding.term}</span>
                <span className="text-xs text-muted-foreground">Dictionary {coding.dictionary_version}</span>
                {/* Superseded/current is a coding state shown identically wherever coding appears (19.1). */}
                <PVStatus status={coding.superseded_by_id ? 'Superseded' : 'Current'} label="Coding status" />
              </li>
            ))}
          </ul>
        )}
      </DetailCard>
      <DetailCard title="WHODrug coding" description="Product coding retains its dictionary version immutably.">
        {whodrug.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading WHODrug coding…</p>
        ) : whodrugItems.length === 0 ? (
          <p className="text-sm text-muted-foreground">No WHODrug coding assigned for this case.</p>
        ) : (
          <ul className="space-y-2">
            {whodrugItems.map((coding) => (
              <li key={coding.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm">
                <span className="font-medium">{coding.product}</span>
                <span className="text-xs text-muted-foreground">Dictionary {coding.dictionary_version}</span>
                <PVStatus status={coding.superseded_by_id ? 'Superseded' : 'Current'} label="Coding status" />
              </li>
            ))}
          </ul>
        )}
      </DetailCard>
    </div>
  )
}

function NarrativesView({ studyId, caseId }: { studyId: string; caseId: string }) {
  const safetyCase = usePVCase(caseId)
  const narratives = usePVNarratives(caseId)
  const canWrite = usePermission(PERMISSIONS.PV_SAFETY_NARRATIVE_WRITE, studyId)
  const closed = isPVCaseClosed(safetyCase.data?.lifecycle_state)
  const items = narratives.data?.items ?? []
  return (
    <div className="space-y-4">
      {safetyCase.data ? <CaseHeader safetyCase={safetyCase.data} studyId={studyId} /> : null}
      {canWrite ? <NarrativeForm caseId={caseId} disabled={closed} /> : null}
      {narratives.isLoading ? <DataTableShell label="narratives" state="loading" /> : null}
      {!narratives.isLoading && items.length === 0 ? (
        <DataTableShell label="narratives" state="empty" emptyDescription="No narratives authored for this case." />
      ) : null}
      {items.map((narrative: PVCaseNarrative) => (
        <DetailCard key={narrative.id} title="Case narrative">
          <p className="whitespace-pre-wrap text-sm">{narrative.text}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <PVHistoryDialog
              title="Narrative history"
              description="Prior narrative versions with revising actor and reason."
              triggerLabel="View history"
            >
              <NarrativeHistory narrativeId={narrative.id} />
            </PVHistoryDialog>
          </div>
          {canWrite ? <div className="mt-3"><NarrativeRevisionForm caseId={caseId} narrative={narrative} disabled={closed} /></div> : null}
        </DetailCard>
      ))}
    </div>
  )
}

function NarrativeHistory({ narrativeId }: { narrativeId: string }) {
  const versions = usePVNarrativeVersions(narrativeId)
  if (versions.isLoading) return <p className="text-sm text-muted-foreground">Loading history…</p>
  const items = versions.data?.items ?? []
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No prior versions.</p>
  return (
    <ol className="space-y-3">
      {items.map((version) => (
        <li key={version.id} className="rounded-md border p-3 text-sm">
          <p className="whitespace-pre-wrap">{version.text}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {formatTimestamp(version.revised_at)} · {version.reason ?? 'No reason recorded'}
          </p>
        </li>
      ))}
    </ol>
  )
}

function ReportsView({ studyId, caseId }: { studyId: string; caseId?: string }) {
  const reports = usePVReports(studyId, caseId ? { case_id: caseId } : undefined)
  return (
    <PVDataTable
      label="regulatory reports"
      columns={reportColumns}
      data={reports.data?.items ?? []}
      isLoading={reports.isLoading}
      isFetching={reports.isFetching}
      error={reports.error}
      onRetry={() => void reports.refetch()}
      errorMessage="Unable to load regulatory reports."
      emptyDescription="No regulatory reports match the current scope."
    />
  )
}

function ReconciliationView({ studyId }: { studyId: string }) {
  const runs = usePVReconciliation(studyId)
  const canRun = usePermission(PERMISSIONS.PV_SAFETY_RECONCILIATION_RUN, studyId)
  const items = runs.data?.items ?? []
  const discrepancies = items.flatMap((run) => run.discrepancies ?? [])
  return (
    <div className="space-y-4">
      {canRun ? (
        <div className="flex justify-end">
          <Button type="button" size="sm" disabled>
            Run reconciliation
          </Button>
        </div>
      ) : null}
      <PVDataTable
        label="reconciliation runs"
        columns={reconColumns}
        data={items}
        isLoading={runs.isLoading}
        isFetching={runs.isFetching}
        error={runs.error}
        onRetry={() => void runs.refetch()}
        errorMessage="Unable to load reconciliation runs. The EDC projection may be unavailable."
        emptyDescription="No reconciliation runs recorded for this study."
      />
      {discrepancies.length > 0 ? (
        <DetailCard title="Discrepancies" description="One-way, read-only differences against the approved EDC projection.">
          <ul className="space-y-2">
            {discrepancies.map((discrepancy) => (
              <li key={discrepancy.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm">
                <PVSourceLabel source="EDC" />
                <span className="font-medium">{discrepancy.edc_reference}</span>
                <span className="text-xs text-muted-foreground">{discrepancy.differing_fields.join(', ')}</span>
                {/* Same textual discrepancy status value used everywhere (19.1). */}
                <PVStatus status={discrepancy.status} label="Discrepancy status" />
              </li>
            ))}
          </ul>
        </DetailCard>
      ) : null}
    </div>
  )
}

function ExportsView({ studyId }: { studyId: string }) {
  const exports = usePVExports(studyId)
  return (
    <PVDataTable
      label="safety exports"
      columns={exportColumns}
      data={exports.data?.items ?? []}
      isLoading={exports.isLoading}
      isFetching={exports.isFetching}
      error={exports.error}
      onRetry={() => void exports.refetch()}
      errorMessage="Unable to load safety exports."
      emptyDescription="No safety export jobs for this study."
    />
  )
}

function AuditView({ studyId }: { studyId: string }) {
  const audit = usePVAudit(studyId)
  return (
    <div className="space-y-4">
      <PageToolbar label="Audit history">
        <PVHistoryDialog title="Safety audit history" description="Immutable PV safety audit events, ordered by UTC timestamp." triggerLabel="Open audit history">
          <PVDataTable
            label="safety audit events"
            columns={auditColumns}
            data={audit.data?.items ?? []}
            isLoading={audit.isLoading}
            isFetching={audit.isFetching}
            error={audit.error}
            onRetry={() => void audit.refetch()}
            emptyDescription="No audit events match the current scope."
          />
        </PVHistoryDialog>
      </PageToolbar>
      <PVDataTable
        label="safety audit events"
        columns={auditColumns}
        data={audit.data?.items ?? []}
        isLoading={audit.isLoading}
        isFetching={audit.isFetching}
        error={audit.error}
        onRetry={() => void audit.refetch()}
        errorMessage="Unable to load safety audit events."
        emptyDescription="No audit events match the current scope."
      />
    </div>
  )
}

/* ----------------------------------------------------------------------- */
/* Content router                                                           */
/* ----------------------------------------------------------------------- */

function ViewContent({ view, scope }: { view: PVView; scope: Scope }) {
  if (view === 'site-dashboard') return <SiteDashboardView siteId={scope.siteId ?? ''} studyId={scope.studyId} />
  const studyId = scope.studyId ?? ''
  const caseId = scope.caseId ?? ''
  if (view === 'dashboard') return <DashboardView studyId={studyId} />
  if (view === 'cases') return <CaseListView studyId={studyId} />
  if (view === 'case-detail') return <CaseDetailView studyId={studyId} caseId={caseId} />
  if (view === 'assessments') return <AssessmentsView studyId={studyId} caseId={caseId} />
  if (view === 'coding') return <CodingView studyId={studyId} caseId={caseId} />
  if (view === 'narratives') return <NarrativesView studyId={studyId} caseId={caseId} />
  if (view === 'reports') return <ReportsView studyId={studyId} caseId={scope.caseId} />
  if (view === 'reconciliation') return <ReconciliationView studyId={studyId} />
  if (view === 'exports') return <ExportsView studyId={studyId} />
  return <AuditView studyId={studyId} />
}

/* ----------------------------------------------------------------------- */
/* Workspace shell                                                          */
/* ----------------------------------------------------------------------- */

export function PVWorkspacePage({ view, studyId, siteId, caseId }: WorkspaceProps) {
  const state = usePVCapabilityState()
  const permissions = useAuthStore((s) => s.user?.permissions ?? [])
  const selectedStudyId = useStudyContext((s) => s.selectedStudyId)
  const selectedSiteId = useStudyContext((s) => s.selectedSiteId)
  const canRead = usePermission(PERMISSIONS.PV_SAFETY_CASE_READ)

  const scope: Scope = {
    studyId: studyId ?? selectedStudyId ?? undefined,
    siteId: siteId ?? selectedSiteId ?? undefined,
    caseId,
  }

  // Disabled/unavailable PV never alters EDC/CTMS routes (Requirement 23.10).
  if (state.status === 'disabled') return <DirectRouteState kind="disabled" title={titleFor(view)} />
  if (state.status === 'unavailable') return <DirectRouteState kind="unavailable" title={titleFor(view)} />

  // The API enforces authorization; the client renders access-denied when the
  // user lacks the baseline read permission or the view's capability (19.6).
  const descriptor = PV_ACTION_ROUTE_MAP[VIEW_DESCRIPTOR[view]]
  if (!canRead || !isPVActionAvailable(state, descriptor, permissions)) {
    return <AccessDeniedPage />
  }

  const needsStudy = view !== 'site-dashboard'
  const needsSite = view === 'site-dashboard'
  if ((needsStudy && !scope.studyId) || (needsSite && !scope.siteId)) {
    return (
      <PageContainer>
        <PageHeader title={titleFor(view)} description="Safety workspace" />
        <p className="text-muted-foreground">
          {needsSite ? 'Select a site to view its safety dashboard.' : 'Select a study to view PV safety data.'}
        </p>
      </PageContainer>
    )
  }

  return (
    <PageContainer wide data-testid="pv-workspace">
      <PageHeader
        title={titleFor(view)}
        description={
          <span>
            <span className="block text-xs font-semibold uppercase tracking-wide text-primary">PV safety workspace</span>
            <span className="block">PV references canonical identity read-only and never mutates EDC or CTMS records.</span>
          </span>
        }
      />
      <PageToolbar label="PV workspace sections">
        <WorkspaceNavigation view={view} scope={scope} state={state} permissions={permissions} />
      </PageToolbar>
      <ViewContent view={view} scope={scope} />
    </PageContainer>
  )
}
