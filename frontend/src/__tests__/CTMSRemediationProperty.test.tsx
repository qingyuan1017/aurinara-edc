import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import {
  CTMSClientError,
  normalizeCTMSError,
  sanitizeCTMSRemediationDetails,
  type CTMSConflict,
  type CTMSFailedEvent,
} from '@/features/ctms/api'
import { CoordinationRemediationPanel } from '@/features/ctms/components'

const prohibitedKeys = [
  'raw_event',
  'event_body',
  'payload',
  'clinical_data',
  'source_document',
  'credentials',
  'password',
  'token',
  'stack',
  'traceback',
  'query_message',
] as const

type GeneratedRemediationCase = {
  index: number
  kind: 'failed' | 'conflict'
  permissionGranted: boolean
  serverActionGranted: boolean
  safeMarker: string
  prohibitedMarker: string
  error: {
    code: string
    message: string
    requestId: string
    correlationId: string
  }
  record: CTMSFailedEvent | CTMSConflict
}

/**
 * fast-check is not installed in this repository. These deterministic cases
 * provide generated-example coverage without adding an unpinned dependency.
 */
function generatedRemediationCases(count: number): GeneratedRemediationCase[] {
  return Array.from({ length: count }, (_, index) => {
    const kind: GeneratedRemediationCase['kind'] = index % 2 === 0 ? 'failed' : 'conflict'
    const safeMarker = `safe-remediation-${index}`
    const prohibitedMarker = `must-not-render-${index}`
    const permissionGranted = index % 3 !== 0
    const serverActionGranted = index % 4 !== 0
    const availableAction = kind === 'failed' ? 'replay' : 'resolve'

    const sanitizedDetails = {
      guidance: safeMarker,
      source_version: String(index + 1),
      current_version: String(index + 2),
      raw_event: prohibitedMarker,
      clinical_data: { subject_status: prohibitedMarker },
      query_message: prohibitedMarker,
      stack: prohibitedMarker,
      arbitrary_detail: prohibitedMarker,
    }
    const availableActions = serverActionGranted ? [availableAction] : []
    const common = {
      id: `${kind}-${index}`,
      event_id: `event-${index}`,
      status: 'open',
      correlation_id: `correlation-${index}`,
      sanitized_details: sanitizedDetails,
      available_actions: availableActions,
    }

    const record: CTMSFailedEvent | CTMSConflict = kind === 'failed'
      ? {
          ...common,
          event_type: 'OperationalTaskUpdated',
          reason_code: `REASON_${index}`,
          source_module: 'CTMS',
          created_at: '2026-03-01T10:00:00Z',
        }
      : {
          ...common,
          entity_type: 'OperationalTask',
          conflict_type: `VERSION_MISMATCH_${index}`,
          field_path: 'status',
          policy_choices: ['keep_current', 'apply_source'],
          created_at: '2026-03-01T10:00:00Z',
        }

    return {
      index,
      kind,
      permissionGranted,
      serverActionGranted,
      safeMarker,
      prohibitedMarker,
      error: {
        code: `CTMS_REMEDIATION_${index}`,
        message: `Review server remediation guidance ${safeMarker}.`,
        requestId: `request-${index}`,
        correlationId: `error-correlation-${index}`,
      },
      record,
    }
  })
}

function setPermissions(permissions: readonly string[]) {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'user@example.com',
      first_name: 'CTMS',
      last_name: 'Operator',
      roles: [{ role_name: 'CTMS_Operations_User' }],
      permissions: [...permissions],
    },
    isAuthenticated: true,
  })
}

describe('CTMS sanitized remediation property', () => {
  afterEach(() => {
    cleanup()
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  // Feature: ctms-frontend, Property 7: Error and remediation view models are sanitized
  // **Validates: Requirements 9.1–9.2, 9.6–9.7, 10.2, 11.6**
  it('preserves safe error metadata while removing prohibited error details across 128 generated cases', () => {
    for (const scenario of generatedRemediationCases(128)) {
      const normalized = normalizeCTMSError({
        response: {
          status: 409,
          data: {
            error: {
              code: scenario.error.code,
              message: scenario.error.message,
              request_id: scenario.error.requestId,
              correlation_id: scenario.error.correlationId,
              details: {
                guidance: scenario.safeMarker,
                source_version: String(scenario.index + 1),
                current_version: String(scenario.index + 2),
                raw_event: scenario.prohibitedMarker,
                clinical_data: { subject_status: scenario.prohibitedMarker },
                query_message: scenario.prohibitedMarker,
                stack: scenario.prohibitedMarker,
              },
            },
          },
        },
      })

      expect(normalized).toBeInstanceOf(CTMSClientError)
      expect(normalized).toMatchObject({
        code: scenario.error.code,
        message: scenario.error.message,
        requestId: scenario.error.requestId,
        correlationId: scenario.error.correlationId,
        category: 'conflict',
      })
      expect(normalized.details).toMatchObject({ guidance: scenario.safeMarker })
      const normalizedText = JSON.stringify(normalized.details)
      expect(prohibitedKeys.every((key) => !normalizedText.toLowerCase().includes(key))).toBe(true)
      expect(normalizedText).not.toContain(scenario.prohibitedMarker)
    }
  })

  it('keeps only allowlisted coordination details and exposes remediation actions only when permitted', () => {
    for (const scenario of generatedRemediationCases(128)) {
      const details = sanitizeCTMSRemediationDetails(scenario.record.sanitized_details)
      expect(details).toEqual({
        guidance: scenario.safeMarker,
        source_version: String(scenario.index + 1),
        current_version: String(scenario.index + 2),
      })
      const detailsText = JSON.stringify(details)
      expect(prohibitedKeys.every((key) => !detailsText.toLowerCase().includes(key))).toBe(true)
      expect(detailsText).not.toContain(scenario.prohibitedMarker)

      setPermissions([
        PERMISSIONS.CTMS_OPERATIONAL_DATA_READ,
        ...(scenario.permissionGranted
          ? [scenario.kind === 'failed' ? PERMISSIONS.CTMS_COORDINATION_REPLAY : PERMISSIONS.CTMS_CONFLICT_MANAGEMENT]
          : []),
      ])
      const mutation = { status: 'idle' as const, canMutate: true }
      const result = scenario.kind === 'failed'
        ? render(<CoordinationRemediationPanel kind="failed" record={scenario.record as CTMSFailedEvent} studyId="study-1" mutation={mutation} onReplay={() => undefined} />)
        : render(<CoordinationRemediationPanel kind="conflict" record={scenario.record as CTMSConflict} studyId="study-1" mutation={mutation} onResolve={() => undefined} />)

      const renderedText = result.container.textContent ?? ''
      expect(renderedText).toContain(scenario.safeMarker)
      expect(renderedText).not.toContain(scenario.prohibitedMarker)

      const actionLabel = scenario.kind === 'failed' ? 'Replay failed event' : 'Resolve conflict'
      const actionIsVisible = scenario.permissionGranted && scenario.serverActionGranted
      if (actionIsVisible) {
        expect(result.queryByRole('button', { name: actionLabel })).toBeInTheDocument()
      } else {
        expect(result.queryByRole('button', { name: actionLabel })).not.toBeInTheDocument()
      }
      result.unmount()
    }
  })
})
