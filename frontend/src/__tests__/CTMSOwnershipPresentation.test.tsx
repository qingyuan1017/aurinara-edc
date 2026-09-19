import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import {
  CanonicalIdentifierList,
  GuardedCTMSAction,
  MonitoringActivitySummary,
  ProjectionFreshness,
  QualitySignalPresentation,
  QueryFollowUpSummary,
  SanitizedRemediationActions,
  StatusPresentation,
  SubjectStatusSummary,
  getProjectionFreshness,
} from '@/features/ctms/components'

describe('CTMS ownership presentation', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('renders canonical EDC identifiers and authoritative ownership', () => {
    render(<CanonicalIdentifierList identifiers={{ studyId: 'study-1', siteId: 'site-2', subjectId: 'subject-3', visitInstanceId: 'visit-4' }} />)
    expect(screen.getByText('EDC Study ID')).toBeInTheDocument()
    expect(screen.getByText('study-1')).toBeInTheDocument()
    expect(screen.getByText('EDC Visit Instance ID')).toBeInTheDocument()

    render(<StatusPresentation kind="operational" status="Enrolled" owner="CTMS" readOnly={false} />)
    expect(screen.getByLabelText(/authoritative module: CTMS/i)).toBeInTheDocument()
    expect(screen.getByTestId('module-badge')).toHaveAttribute('data-owner', 'CTMS')
    expect(screen.getByText('Operational status:')).toBeInTheDocument()
  })

  it('keeps operational subject status separate from EDC clinical access state', () => {
    render(<SubjectStatusSummary subjectId="subject-1" operationalStatus="Withdrawn" clinicalAccessState="Read only" />)
    expect(screen.getByText('Operational status:')).toBeInTheDocument()
    expect(screen.getByText('Clinical access state:')).toBeInTheDocument()
    expect(screen.getByText('Operational enrollment status does not grant or revoke EDC clinical access.')).toBeInTheDocument()
    expect(screen.getAllByLabelText(/authoritative module:/i)).toHaveLength(2)
  })

  it('keeps monitoring activities distinct from linked protocol visits', () => {
    render(<MonitoringActivitySummary activityType="Routine Monitoring" operationalStatus="Scheduled" assignedCra="cra-1" plannedDate="2026-02-01T10:00:00Z" edcVisitInstanceId="visit-1" />)
    expect(screen.getByText('Monitoring activity · CTMS operational record')).toBeInTheDocument()
    expect(screen.getByText('Linked protocol visit · EDC clinical record')).toBeInTheDocument()
    expect(screen.getByText('The CTMS activity references this visit but cannot reschedule, complete, freeze, or lock it.')).toBeInTheDocument()
  })

  it('reports projection freshness and handles invalid timestamps', () => {
    const now = new Date('2026-02-01T12:00:00Z')
    expect(getProjectionFreshness('2026-02-01T11:30:00Z', now)).toBe('current')
    expect(getProjectionFreshness('2026-02-01T09:00:00Z', now)).toBe('stale')
    expect(getProjectionFreshness('not-a-date', now)).toBe('unknown')

    render(<ProjectionFreshness metadata={{ sourceModule: 'EDC', sourceTimestamp: '2026-02-01T09:00:00Z', projectedAt: '2026-02-01T09:05:00Z', readOnly: true }} now={now} />)
    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.getByTestId('projection-freshness')).toHaveAttribute('data-freshness', 'stale')
    expect(screen.getByRole('status', { name: 'Projection freshness: Stale' })).toBeInTheDocument()
    expect(screen.getByText('Source timestamp:')).toBeInTheDocument()
    expect(screen.getByLabelText('read-only')).toBeInTheDocument()
  })

  it('renders complete projection metadata and exposes refresh-only actions', () => {
    const onRefresh = vi.fn()
    const now = new Date('2026-02-01T12:00:00Z')
    const { rerender } = render(
      <ProjectionFreshness
        metadata={{
          sourceModule: 'EDC',
          sourceRecordId: 'signal-1',
          sourceTimestamp: '2026-02-01T11:55:00Z',
          projectedAt: '2026-02-01T11:56:00Z',
          sourceVersion: 8,
          ruleVersion: 'quality-v2',
          freshness: 'stale',
          readOnly: true,
        }}
        now={now}
        onRefresh={onRefresh}
      />,
    )
    expect(screen.getByText('signal-1')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
    expect(screen.getByText('quality-v2')).toBeInTheDocument()
    expect(screen.getByTestId('projection-freshness')).toHaveAttribute('data-freshness', 'stale')
    fireEvent.click(screen.getByRole('button', { name: 'Refresh projection' }))
    expect(onRefresh).toHaveBeenCalledOnce()

    rerender(<ProjectionFreshness metadata={{ sourceModule: 'EDC', sourceTimestamp: '2026-02-01T11:55:00Z', freshness: 'current' }} onRefresh={onRefresh} />)
    expect(screen.queryByRole('button', { name: 'Refresh projection' })).not.toBeInTheDocument()
  })

  it('uses aggregate quality-signal wording and blocks clinical mutation actions in linked summaries', () => {
    const onRefresh = vi.fn()
    render(
      <div>
        <QualitySignalPresentation
          signalType="Open query count"
          value={2}
          metadata={{ sourceModule: 'EDC', sourceRecordId: 'signal-1', sourceTimestamp: '2026-02-01T09:00:00Z', freshness: 'stale', readOnly: true }}
          onRefresh={onRefresh}
        />
        <SubjectStatusSummary subjectId="subject-1" operationalStatus="Enrolled" clinicalAccessState="Accessible" />
        <MonitoringActivitySummary activityType="Routine Monitoring" operationalStatus="Scheduled" edcVisitInstanceId="visit-1" />
        <QueryFollowUpSummary queryId="query-1" taskStatus="Open" queryStatus="Open" />
      </div>,
    )
    expect(screen.getByText('Approved aggregate quality signal · read-only projection')).toBeInTheDocument()
    expect(screen.getByText(/does not expose individual clinical records or authorize EDC clinical changes/)).toBeInTheDocument()
    expect(screen.getAllByTestId('projection-freshness')).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Refresh projection' })).toHaveLength(1)
    expect(screen.getAllByTestId('monitoring-activity-summary')[0]).toHaveAttribute('data-clinical-mutation-actions', 'none')
    expect(screen.getAllByTestId('quality-signal')[0]).toHaveAttribute('data-clinical-mutation-actions', 'none')
    expect(screen.getAllByTestId('projection-freshness')[0]).toHaveAttribute('data-clinical-mutation-actions', 'none')
  })

  it('hides unauthorized actions while allowing the server-authoritative action for permissioned users', () => {
    const onClick = vi.fn()
    const { rerender } = render(<GuardedCTMSAction permission={PERMISSIONS.CTMS_COORDINATION_REPLAY} onClick={onClick}>Replay</GuardedCTMSAction>)
    expect(screen.queryByRole('button', { name: 'Replay' })).not.toBeInTheDocument()

    useAuthStore.setState({ user: { id: 'admin', email: 'admin@example.com', first_name: 'CTMS', last_name: 'Admin', roles: [], permissions: [PERMISSIONS.CTMS_COORDINATION_REPLAY] }, isAuthenticated: true })
    rerender(<GuardedCTMSAction permission={PERMISSIONS.CTMS_COORDINATION_REPLAY} onClick={onClick}>Replay</GuardedCTMSAction>)
    fireEvent.click(screen.getByRole('button', { name: 'Replay' }))
    expect(onClick).toHaveBeenCalledOnce()
    expect(screen.getByTitle('The CTMS API remains authoritative for this action.')).toBeInTheDocument()
  })

  it('shows only sanitized remediation details and permissioned actions', () => {
    const onAction = vi.fn()
    render(<SanitizedRemediationActions details={{ code: 'RECORD_NOT_FOUND', message: 'The event could not be applied.' }} actions={[{ label: 'Replay', permission: PERMISSIONS.CTMS_COORDINATION_REPLAY, onAction }]} />)
    expect(screen.getByText(/RECORD_NOT_FOUND/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Replay' })).not.toBeInTheDocument()
    expect(screen.queryByText(/raw|payload|secret/i)).not.toBeInTheDocument()
  })
})
