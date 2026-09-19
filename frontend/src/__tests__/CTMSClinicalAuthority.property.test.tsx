import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import {
  CTMS_ACTION_ROUTE_MAP,
  CTMS_CAPABILITY_CODES,
  isCTMSActionAvailable,
  normalizeCTMSCapabilities,
  type CTMSActionRouteDescriptor,
  type CTMSCapabilityCode,
  type CTMSPhase,
} from '@/features/ctms'
import {
  MonitoringActivitySummary,
  ProjectionFreshness,
  QueryFollowUpSummary,
  QualitySignalPresentation,
  SubjectStatusSummary,
} from '@/features/ctms/components'

const phases = [1, 2, 3] as const satisfies readonly CTMSPhase[]
const capabilityCodes = Object.values(CTMS_CAPABILITY_CODES) as CTMSCapabilityCode[]
const permissions = [
  'ctms.operational_study_management',
  'ctms.operational_site_management',
  'ctms.monitoring_activity_management',
  'ctms.coordination_replay',
  'ctms.conflict_management',
  'data.export',
  'edc.subject.update',
  'edc.visit.complete',
  'edc.query.resolve',
  'clinical_attachments.download',
  'clinical_exports.create',
] as const
const clinicalActionNames = /clinical|edc|subject|visit|query|form|field|attachment|export/i

function generator(seed: number) {
  let state = seed >>> 0
  return {
    next() {
      state = (Math.imul(state, 1_664_525) + 1_013_904_223) >>> 0
      return state
    },
    integer(maxExclusive: number) {
      return this.next() % maxExclusive
    },
    pick<T>(values: readonly T[]): T {
      return values[this.integer(values.length)] as T
    },
    boolean() {
      return this.integer(2) === 0
    },
  }
}

function clinicalDescriptors(index: number): CTMSActionRouteDescriptor[] {
  const capability = CTMS_CAPABILITY_CODES.ctmsOperationalProjections
  return [
    {
      kind: 'action',
      route: `/edc/subjects/subject-${index}/clinical-status`,
      phase: 1,
      capability,
      owner: 'EDC',
      clinicalMutation: true,
    },
    {
      kind: 'action',
      route: `/edc/visits/visit-${index}/complete`,
      phase: 1,
      capability,
      owner: 'EDC',
      clinicalMutation: true,
    },
    {
      kind: 'action',
      route: `/edc/queries/query-${index}/resolve`,
      phase: 1,
      capability,
      owner: 'EDC',
      clinicalMutation: true,
    },
    {
      kind: 'action',
      route: `/edc/clinical-exports/${index}`,
      phase: 1,
      capability,
      owner: 'EDC',
      clinicalMutation: true,
    },
  ]
}

afterEach(() => {
  cleanup()
})

describe('CTMS projection clinical-authority property', () => {
  // Feature: ctms-frontend, Property 11: Projection and operational status never grant clinical authority.
  // **Validates: Requirements 1.5, 7.3–7.4, 8.6, 12.2–12.6**
  it('emits only CTMS actions and never clinical authority actions across 256 generated cases', () => {
    for (let example = 0; example < 256; example += 1) {
      const random = generator(0xC11A + example)
      const phase = random.pick(phases)
      const manifestCapabilities = capabilityCodes.filter(() => random.boolean())
      const permissionsForCase = permissions.filter(() => random.boolean())
      const state = normalizeCTMSCapabilities({
        module: 'CTMS',
        enabled: random.boolean(),
        phase,
        capabilities: manifestCapabilities,
      })
      const sourceRecordId = `edc-record-${example}-${random.integer(10_000)}`
      const subjectId = `subject-${example}-${random.integer(10_000)}`
      const visitInstanceId = `visit-${example}-${random.integer(10_000)}`
      const queryId = `query-${example}-${random.integer(10_000)}`
      const operationalStatus = random.pick(['Planned', 'Active', 'At risk', 'Completed', 'Withdrawn'])
      const clinicalAccessState = random.pick(['Accessible', 'Read only', 'Restricted', 'Not available'])
      const freshness = random.pick(['current', 'stale', 'unknown'] as const)
      const sourceModule = random.boolean() ? 'EDC' : 'EDC-Projection'
      const metadata = {
        sourceModule,
        sourceRecordId,
        sourceTimestamp: freshness === 'unknown' ? 'not-a-timestamp' : '2026-02-01T09:00:00Z',
        projectedAt: '2026-02-01T09:05:00Z',
        sourceVersion: random.integer(10),
        ruleVersion: `quality-rule-${random.integer(5)}`,
        freshness,
        readOnly: true,
      } as const

      const descriptors = [
        ...Object.values(CTMS_ACTION_ROUTE_MAP),
        ...clinicalDescriptors(example),
      ]
      const emittedActions = descriptors.filter((descriptor) =>
        isCTMSActionAvailable(state, descriptor, permissionsForCase),
      )

      expect(emittedActions.every((action) => (
        action.owner === 'CTMS'
        && action.clinicalMutation === false
        && action.route.includes('/ctms')
        && !clinicalActionNames.test(action.route)
      ))).toBe(true)
      expect(emittedActions.some((action) => action.owner !== 'CTMS' || action.clinicalMutation)).toBe(false)
      expect(emittedActions.some((action) => action.route.startsWith('/edc/'))).toBe(false)

      const { container, unmount } = render(
        <div>
          <QualitySignalPresentation
            signalType="Approved query summary"
            value={random.integer(100)}
            metadata={metadata}
          />
          <SubjectStatusSummary
            subjectId={subjectId}
            operationalStatus={operationalStatus}
            clinicalAccessState={clinicalAccessState}
          />
          <MonitoringActivitySummary
            activityType="Routine monitoring"
            operationalStatus={operationalStatus}
            edcVisitInstanceId={visitInstanceId}
          />
          <QueryFollowUpSummary
            queryId={queryId}
            taskStatus={operationalStatus}
            queryStatus={clinicalAccessState}
          />
          <ProjectionFreshness metadata={metadata} now={new Date('2026-02-01T12:00:00Z')} onRefresh={() => undefined} />
        </div>,
      )

      const buttons = [...container.querySelectorAll('button')]
      expect(buttons.every((button) => button.textContent?.toLowerCase().includes('refresh projection'))).toBe(true)
      expect(buttons.some((button) => clinicalActionNames.test(button.textContent ?? '') || clinicalActionNames.test(button.getAttribute('aria-label') ?? ''))).toBe(false)
      expect(container.querySelectorAll('[data-clinical-mutation-actions="none"]').length).toBeGreaterThan(0)
      expect(container.textContent).toContain('Operational status:')
      expect(container.textContent).toContain('Clinical access state:')
      expect(container.textContent).toContain(subjectId)
      expect(container.textContent).toContain(visitInstanceId)
      expect(container.textContent).toContain(queryId)
      expect(container.textContent).toContain('read-only')

      unmount()
    }
  })
})
