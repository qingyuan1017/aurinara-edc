import type { ReactNode } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { DetailCard, OwnershipBadge, StatusBadge } from '@/components/patterns'
import { usePermission, type PermissionCode } from '@/lib/permissions'
import type { Module, OwnershipState } from '../capabilities'
import { resolveProjectionFreshness } from './freshness'

export type StatusKind = 'operational' | 'clinical'

export interface CanonicalIdentifiers {
  studyId?: string | null
  siteId?: string | null
  subjectId?: string | null
  visitInstanceId?: string | null
}

export interface ProjectionMetadata {
  sourceModule: Module | string
  sourceRecordId?: string | null
  sourceTimestamp?: string | null
  projectedAt?: string | null
  sourceVersion?: string | number | null
  ruleVersion?: string | number | null
  freshness?: string | null
  status?: string | null
  readOnly?: boolean
}

function displayModule(module: Module | string): string {
  return module.toUpperCase() === 'EDC' ? 'EDC' : module.toUpperCase() === 'CTMS' ? 'CTMS' : module
}

function formatDate(value?: string | null): string {
  if (!value) return 'Not available'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Not available' : parsed.toLocaleString()
}

export function ModuleBadge({
  module,
  state = 'authoritative',
}: {
  module: Module | string
  state?: OwnershipState | string
}) {
  return <OwnershipBadge owner={displayModule(module)} state={state} readOnly={state === 'projected' || displayModule(module) === 'EDC'} data-testid="module-badge" />
}

export function ReadOnlyIndicator({ reason = 'This view is read-only.' }: { reason?: string }) {
  return (
    <Badge variant="outline" role="status" aria-label="read-only" title={reason} data-testid="read-only-indicator" className="border-border bg-muted/50 text-muted-foreground">
      Read only
    </Badge>
  )
}

export function CanonicalIdentifierList({ identifiers }: { identifiers: CanonicalIdentifiers }) {
  const entries = [
    ['EDC Study ID', identifiers.studyId],
    ['EDC Site ID', identifiers.siteId],
    ['EDC Subject ID', identifiers.subjectId],
    ['EDC Visit Instance ID', identifiers.visitInstanceId],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]))

  if (entries.length === 0) return null
  return (
    <dl className="grid gap-2 sm:grid-cols-2" data-testid="canonical-identifiers">
      {entries.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
          <dd className="break-all font-mono text-sm text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function StatusPresentation({
  kind,
  status,
  owner,
  readOnly = owner !== 'CTMS',
}: {
  kind: StatusKind
  status: string
  owner: Module | string
  readOnly?: boolean
}) {
  const label = kind === 'operational' ? 'Operational status' : 'Clinical access state'
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`${kind}-status`}>
      <span className="text-sm font-medium text-muted-foreground">{label}:<span className="sr-only"> {status}</span></span>
      <StatusBadge status={status} label={label} />
      <ModuleBadge module={owner} />
      {readOnly && <ReadOnlyIndicator reason={`${label} is owned by ${displayModule(owner)}.`} />}
    </div>
  )
}

export function ProjectionFreshness({
  metadata,
  now,
  staleAfterMinutes = 60,
  onRefresh,
  refreshing = false,
}: {
  metadata: ProjectionMetadata
  now?: Date
  staleAfterMinutes?: number
  /** Refreshes the projection read model only; it cannot mutate the source record. */
  onRefresh?: () => void
  refreshing?: boolean
}) {
  const freshness = resolveProjectionFreshness({
    freshness: metadata.freshness,
    sourceTimestamp: metadata.sourceTimestamp,
    now,
    staleAfterMinutes,
  })
  const label = freshness === 'current' ? 'Current' : freshness === 'stale' ? 'Stale' : 'Unknown'
  return (
    <div className="space-y-2 text-sm" data-testid="projection-freshness" data-freshness={freshness} data-clinical-mutation-actions="none">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-muted-foreground">Projection source:</span>
        <ModuleBadge module={metadata.sourceModule} state="projected" />
        <StatusBadge status={label} label="Projection freshness" />
        <ReadOnlyIndicator reason="Projections cannot be used to mutate the authoritative record." />
        {onRefresh && freshness !== 'current' ? (
          <Button type="button" variant="outline" size="sm" pending={refreshing} loadingText="Refreshing projection…" onClick={onRefresh} aria-label="Refresh projection">
            Refresh projection
          </Button>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">Only this CTMS projection is refreshed; the {displayModule(metadata.sourceModule)} source record and clinical workflow are unchanged.</p>
      <dl className="grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
        {metadata.sourceRecordId && <div><dt className="inline font-medium">Source record: </dt><dd className="inline font-mono">{metadata.sourceRecordId}</dd></div>}
        <div><dt className="inline font-medium">Source timestamp: </dt><dd className="inline">{formatDate(metadata.sourceTimestamp)}</dd></div>
        <div><dt className="inline font-medium">Projected at: </dt><dd className="inline">{formatDate(metadata.projectedAt)}</dd></div>
        {metadata.sourceVersion !== undefined && metadata.sourceVersion !== null && <div><dt className="inline font-medium">Source version: </dt><dd className="inline">{String(metadata.sourceVersion)}</dd></div>}
        {metadata.ruleVersion !== undefined && metadata.ruleVersion !== null && <div><dt className="inline font-medium">Rule version: </dt><dd className="inline">{String(metadata.ruleVersion)}</dd></div>}
      </dl>
    </div>
  )
}

export function QualitySignalPresentation({
  signalType,
  value,
  metadata,
  onRefresh,
  refreshing = false,
}: {
  signalType: string
  value: number | string | null | undefined
  metadata: ProjectionMetadata
  onRefresh?: () => void
  refreshing?: boolean
}) {
  return (
    <article className="space-y-2 rounded-md border bg-card p-3" data-testid="quality-signal" data-clinical-mutation-actions="none">
      <p className="font-medium text-foreground">{signalType}</p>
      <p className="text-xl font-bold text-foreground">{String(value ?? '—')}</p>
      <p className="text-xs text-muted-foreground">Approved aggregate quality signal · read-only projection</p>
      <p className="text-xs text-muted-foreground">This minimized aggregate does not expose individual clinical records or authorize EDC clinical changes.</p>
      <ProjectionFreshness metadata={metadata} onRefresh={onRefresh} refreshing={refreshing} />
    </article>
  )
}

export function OwnershipCard({
  title,
  identifiers,
  children,
  projection,
  onProjectionRefresh,
  projectionRefreshing,
}: {
  title: string
  identifiers?: CanonicalIdentifiers
  children: ReactNode
  projection?: ProjectionMetadata
  onProjectionRefresh?: () => void
  projectionRefreshing?: boolean
}) {
  return (
    <DetailCard
      title={title}
      className="border-border bg-card"
      data-clinical-mutation-actions={projection ? 'none' : undefined}
      ownership={projection ? <ReadOnlyIndicator reason="This data is an approved cross-module projection." /> : undefined}
    >
      {identifiers ? <CanonicalIdentifierList identifiers={identifiers} /> : null}
      {children}
      {projection ? <ProjectionFreshness metadata={projection} onRefresh={onProjectionRefresh} refreshing={projectionRefreshing} /> : null}
    </DetailCard>
  )
}

export function MonitoringActivitySummary({
  activityType,
  operationalStatus,
  assignedCra,
  plannedDate,
  completionEvidence,
  lastChangedAt,
  edcVisitInstanceId,
}: {
  activityType: string
  operationalStatus: string
  assignedCra?: string | null
  plannedDate?: string | null
  completionEvidence?: string | null
  lastChangedAt?: string | null
  edcVisitInstanceId?: string | null
}) {
  return (
    <div className="space-y-2" data-testid="monitoring-activity-summary" data-clinical-mutation-actions="none">
      <p className="text-sm font-semibold text-foreground">Monitoring activity · CTMS operational record</p>
      <p className="text-sm text-muted-foreground">Type: {activityType}</p>
      <StatusPresentation kind="operational" status={operationalStatus} owner="CTMS" readOnly={false} />
      <dl className="grid gap-x-4 gap-y-1 text-sm text-muted-foreground sm:grid-cols-2">
        <div><dt className="inline font-medium">Assigned CRA: </dt><dd className="inline">{assignedCra ?? 'Unassigned'}</dd></div>
        <div><dt className="inline font-medium">Planned date: </dt><dd className="inline">{formatDate(plannedDate)}</dd></div>
        <div><dt className="inline font-medium">Completion evidence: </dt><dd className="inline">{completionEvidence ?? 'Not completed'}</dd></div>
        <div><dt className="inline font-medium">Last change: </dt><dd className="inline">{formatDate(lastChangedAt)}</dd></div>
      </dl>
      {edcVisitInstanceId ? (
        <Alert variant="default" data-clinical-mutation-actions="none">
          <AlertTitle>Linked protocol visit · EDC clinical record</AlertTitle>
          <AlertDescription className="space-y-1">
            <p className="font-mono">EDC Visit Instance ID: {edcVisitInstanceId}</p>
            <ReadOnlyIndicator reason="The CTMS activity references this visit but cannot reschedule, complete, freeze, or lock it." />
            <p className="text-xs">The CTMS activity references this visit but cannot reschedule, complete, freeze, or lock it.</p>
          </AlertDescription>
        </Alert>
      ) : (
        <p className="text-sm text-muted-foreground">No EDC protocol visit linked. Monitoring activity remains operational.</p>
      )}
    </div>
  )
}

export function SubjectStatusSummary({
  subjectId,
  operationalStatus,
  clinicalAccessState,
}: {
  subjectId: string
  operationalStatus: string
  clinicalAccessState: string
}) {
  return (
    <div data-clinical-mutation-actions="none">
      <OwnershipCard title="Subject status" identifiers={{ subjectId }}>
        <StatusPresentation kind="operational" status={operationalStatus} owner="CTMS" readOnly={false} />
        <StatusPresentation kind="clinical" status={clinicalAccessState} owner="EDC" />
        <p className="text-xs text-muted-foreground">Operational enrollment status does not grant or revoke EDC clinical access.</p>
      </OwnershipCard>
    </div>
  )
}

export function QueryFollowUpSummary({
  queryId,
  taskStatus,
  queryStatus,
}: {
  queryId: string
  taskStatus: string
  queryStatus: string
}) {
  return (
    <div data-clinical-mutation-actions="none">
      <OwnershipCard title="Query follow-up" identifiers={{}}>
        <p className="text-sm font-semibold text-foreground">Operational follow-up task · CTMS</p>
        <p className="font-mono text-sm text-muted-foreground">EDC Query ID: {queryId}</p>
        <StatusPresentation kind="operational" status={taskStatus} owner="CTMS" readOnly={false} />
        <StatusPresentation kind="clinical" status={queryStatus} owner="EDC" />
        <p className="text-xs text-muted-foreground">Follow-up actions coordinate work only; query lifecycle actions remain in EDC.</p>
      </OwnershipCard>
    </div>
  )
}

export interface GuardedActionProps {
  permission: PermissionCode
  studyId?: string
  siteId?: string
  children: ReactNode
  onClick?: () => void
  className?: string
  type?: 'button' | 'submit' | 'reset'
  title?: string
  deniedView?: 'hide' | 'message'
}

export function GuardedCTMSAction({
  permission,
  studyId,
  siteId,
  children,
  onClick,
  className,
  type = 'button',
  title,
  deniedView = 'hide',
}: GuardedActionProps) {
  const allowed = usePermission(permission, studyId, siteId)
  if (!allowed && deniedView === 'hide') return null
  if (!allowed) {
    return <Alert variant="warning" role="note" data-testid="ctms-access-denied"><AlertDescription>Access denied for this CTMS action.</AlertDescription></Alert>
  }
  return <Button type={type} onClick={onClick} className={cn('bg-primary text-primary-foreground', className)} title={title ?? 'The CTMS API remains authoritative for this action.'} data-permission={permission}>{children}</Button>
}

export interface SanitizedRemediationAction {
  label: string
  permission: PermissionCode
  onAction: () => void
}

export function SanitizedRemediationActions({
  details,
  actions,
  studyId,
  siteId,
}: {
  details: { code: string; message: string }
  actions: SanitizedRemediationAction[]
  studyId?: string
  siteId?: string
}) {
  return (
    <Alert variant="warning" data-testid="sanitized-remediation">
      <AlertTitle>Remediation required</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>{details.message}</p>
        <p className="font-mono text-xs">Code: {details.code}</p>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => <GuardedCTMSAction key={action.label} permission={action.permission} studyId={studyId} siteId={siteId} onClick={action.onAction}>{action.label}</GuardedCTMSAction>)}
        </div>
        <p className="text-xs">Only sanitized details are shown. Authorization is enforced again by the CTMS API.</p>
      </AlertDescription>
    </Alert>
  )
}
