import { useRef, useState } from 'react'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { Button } from '@/components/ui/button'
import { ConfirmDialog, DetailCard, StatusBadge } from '@/components/patterns'
import { getCTMSMutationMetadata } from './CTMSMutationFeedback'
import {
  sanitizeCTMSRemediationDetails,
  type CTMSConflict,
  type CTMSFailedEvent,
} from '../api'

export type CoordinationRemediationKind = 'failed' | 'conflict'
type RemediationStatus = 'idle' | 'pending' | 'success' | 'error'

interface MutationState {
  status: RemediationStatus
  data?: unknown
  error?: unknown
  canMutate?: boolean
}

interface BaseProps {
  studyId: string
  mutation: MutationState
}

export interface FailedEventRemediationPanelProps extends BaseProps {
  kind: 'failed'
  record: CTMSFailedEvent
  onReplay: (eventId: string, reason: string) => void
}

export interface ConflictRemediationPanelProps extends BaseProps {
  kind: 'conflict'
  record: CTMSConflict
  onResolve: (conflictId: string, policy: string, reason: string) => void
}

export type CoordinationRemediationPanelProps = FailedEventRemediationPanelProps | ConflictRemediationPanelProps

function hasServerAction(actions: string[] | undefined, expected: string): boolean {
  return actions === undefined || actions.some((action) => action.toLowerCase() === expected)
}

function safeText(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return 'Not available'
}

function formatTimestamp(value?: string | null): string {
  if (!value) return 'Not available'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Not available' : parsed.toLocaleString()
}

function DetailList({ details }: { details: Record<string, string | number | boolean> }) {
  const entries = Object.entries(details)
  if (!entries.length) return <p className="text-sm text-muted-foreground">No additional sanitized details were provided by the server.</p>
  return (
    <dl className="grid gap-2 sm:grid-cols-2" data-testid="sanitized-remediation-details">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{key.replaceAll('_', ' ')}</dt>
          <dd className="mt-1 break-words text-sm text-foreground">{safeText(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function MetadataList({ values }: { values: Array<[string, unknown]> }) {
  return (
    <dl className="grid gap-2 sm:grid-cols-2" data-testid="coordination-metadata">
      {values.filter(([, value]) => value !== undefined && value !== null && value !== '').map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
          <dd className="mt-1 break-all font-mono text-sm text-foreground">{safeText(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function OutcomeNotice({ mutation, active }: { mutation: MutationState; active: boolean }) {
  if (!active || mutation.status === 'idle' || mutation.status === 'error') return null
  if (mutation.status === 'pending') {
    return <p className="rounded-md border border-info/30 bg-info/10 p-3 text-sm text-foreground" role="status" aria-live="polite">Request accepted by the workspace and pending a server outcome. Do not submit it again.</p>
  }
  const metadata = getCTMSMutationMetadata(mutation.data)
  const record = mutation.data && typeof mutation.data === 'object' ? mutation.data as Record<string, unknown> : undefined
  const status = typeof record?.status === 'string' ? record.status : 'accepted'
  return (
    <p className="rounded-md border border-success/30 bg-success/10 p-3 text-sm text-foreground" role="status" aria-live="polite">
      Server outcome: {status}. {metadata.correlationId ? `Correlation ID ${metadata.correlationId}.` : 'The server did not return a correlation ID.'}
    </p>
  )
}

export function CoordinationRemediationPanel(props: CoordinationRemediationPanelProps) {
  const { record, studyId, mutation } = props
  const [policy, setPolicy] = useState(props.kind === 'conflict' ? props.record.policy_choices?.[0] ?? '' : '')
  const [submitted, setSubmitted] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const permission = props.kind === 'failed' ? PERMISSIONS.CTMS_COORDINATION_REPLAY : PERMISSIONS.CTMS_CONFLICT_MANAGEMENT
  const permitted = usePermission(permission, studyId)
  const action = props.kind === 'failed' ? 'replay' : 'resolve'
  const serverAllowsAction = hasServerAction(record.available_actions, action)
  const active = submitted && mutation.status !== 'idle'
  const disabled = mutation.status === 'pending' || mutation.canMutate === false
  const details = sanitizeCTMSRemediationDetails(record.sanitized_details)
  const failedRecord = props.kind === 'failed' ? props.record : undefined
  const conflictRecord = props.kind === 'conflict' ? props.record : undefined

  const confirm = (reason?: string) => {
    if (!reason || disabled || !permitted || !serverAllowsAction) return
    setSubmitted(true)
    setConfirmOpen(false)
    if (props.kind === 'failed') props.onReplay(record.event_id, reason)
    else props.onResolve(record.id, policy, reason)
  }

  const openConfirmation = () => {
    if (!disabled && permitted && serverAllowsAction) setConfirmOpen(true)
  }

  return (
    <>
      <DetailCard
        title={props.kind === 'failed' ? 'Failed coordination event' : 'Coordination conflict'}
        description="CTMS coordination remediation is subject to a fresh server authorization and scope check."
        status={<StatusBadge status={safeText(record.status)} label="Coordination status" />}
        className="border-warning/40 bg-card"
        data-testid={`${props.kind}-remediation-panel`}
      >
        <div className="space-y-4">
          <MetadataList
            values={failedRecord
              ? [
                  ['Event ID', failedRecord.event_id],
                  ['Event type', failedRecord.event_type],
                  ['Source module', failedRecord.source_module],
                  ['Reason code', failedRecord.reason_code],
                  ['Correlation ID', failedRecord.correlation_id],
                  ['Source version', failedRecord.source_version],
                  ['Current version', failedRecord.current_version],
                  ['Created', formatTimestamp(failedRecord.created_at)],
                  ['Updated', formatTimestamp(failedRecord.updated_at)],
                ]
              : [
                  ['Conflict ID', record.id],
                  ['Event ID', record.event_id],
                  ['Entity type', conflictRecord!.entity_type],
                  ['Field path', conflictRecord!.field_path],
                  ['Conflict type', conflictRecord!.conflict_type],
                  ['Correlation ID', record.correlation_id],
                  ['Source version', conflictRecord!.source_version],
                  ['Current version', conflictRecord!.current_version],
                  ['Created', formatTimestamp(conflictRecord!.created_at)],
                  ['Resolved', formatTimestamp(conflictRecord!.resolved_at)],
                ]}
          />

          <section className="space-y-2 border-t pt-3">
            <h4 className="text-sm font-semibold text-foreground">Sanitized server details</h4>
            <DetailList details={details} />
          </section>

          {permitted && serverAllowsAction ? (
            <div className="space-y-3 border-t pt-3">
              <p className="text-sm text-muted-foreground">Review the server-provided record and confirm the remediation reason before sending this CTMS action.</p>
              <Button ref={triggerRef} type="button" variant="default" disabled={disabled} onClick={openConfirmation}>
                {mutation.status === 'pending' && submitted ? 'Waiting for server outcome…' : props.kind === 'failed' ? 'Replay failed event' : 'Resolve conflict'}
              </Button>
              {mutation.canMutate === false ? <p className="text-sm text-warning-foreground" role="status">Reconnect before submitting this CTMS change.</p> : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground" role="note">The remediation action is not available for this user or current server policy. Raw event content is never shown.</p>
          )}
          <OutcomeNotice mutation={mutation} active={active} />
          <p className="text-xs text-muted-foreground">Only allowlisted sanitized coordination metadata is shown. Raw event bodies, credentials, clinical values, unrestricted query messages, stack traces, and unrestricted audit data are not rendered.</p>
        </div>
      </DetailCard>
      <ConfirmDialog
        open={confirmOpen}
        title={props.kind === 'failed' ? 'Confirm failed-event replay' : 'Confirm conflict resolution'}
        description="This CTMS action is sent to the server for authorization and audit. It does not mutate EDC clinical records."
        confirmLabel={props.kind === 'failed' ? 'Replay failed event' : 'Resolve conflict'}
        pending={mutation.status === 'pending'}
        permissionAllowed={permitted && serverAllowsAction}
        confirmDisabled={disabled}
        requireReason
        reasonLabel={props.kind === 'failed' ? 'Replay reason' : 'Resolution reason'}
        reason={{ description: 'A reason is required and is recorded by the CTMS service.', maxLength: 2000 }}
        onConfirm={confirm}
        onCancel={() => setConfirmOpen(false)}
        onOpenChange={setConfirmOpen}
        returnFocusRef={triggerRef}
      >
        {props.kind === 'conflict' && props.record.policy_choices?.length ? (
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor={`policy-${record.id}`}>Server-provided resolution policy</label>
            <select id={`policy-${record.id}`} value={policy} onChange={(event) => setPolicy(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" disabled={disabled}>
              {props.record.policy_choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
            </select>
          </div>
        ) : null}
      </ConfirmDialog>
    </>
  )
}
