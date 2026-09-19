import { describe, expect, it } from 'vitest'
import {
  CTMS_ACTION_ROUTE_MAP,
  CTMS_CAPABILITY_CODES,
  CTMS_DISABLED_MANIFEST,
  CTMS_PHASE_CAPABILITIES,
  isCTMSActionAvailable,
  normalizeCTMSCapabilities,
  unavailableCTMSCapabilities,
} from '@/features/ctms'

describe('CTMS capability boundary', () => {
  it('keeps CTMS hidden by default while leaving EDC independent', () => {
    expect(CTMS_DISABLED_MANIFEST).toEqual({
      module: 'CTMS',
      enabled: false,
      phase: 0,
      capabilities: [],
    })
  })

  it('exposes cumulative server capability metadata by delivery phase', () => {
    expect(CTMS_PHASE_CAPABILITIES[1]).toContain(CTMS_CAPABILITY_CODES.operationalStudies)
    expect(CTMS_PHASE_CAPABILITIES[2]).toContain(CTMS_CAPABILITY_CODES.monitoring)
    expect(CTMS_PHASE_CAPABILITIES[3]).toEqual(expect.arrayContaining([...CTMS_PHASE_CAPABILITIES[2]]))
    expect(CTMS_PHASE_CAPABILITIES[3]).toContain(CTMS_CAPABILITY_CODES.operationalExports)
  })

  it('normalizes server environment and platform availability without treating it as authorization', () => {
    const state = normalizeCTMSCapabilities({
      module: 'CTMS',
      enabled: true,
      phase: 3,
      capabilities: [CTMS_CAPABILITY_CODES.operationalDashboards],
      environment: { deployment: 'test' },
      platform_capabilities: { health_observability: true },
    })

    expect(state.status).toBe('ready')
    expect(state.environment).toEqual({ deployment: 'test' })
    expect(state.platformCapabilities.health_observability).toBe(true)
    expect(isCTMSActionAvailable(state, CTMS_ACTION_ROUTE_MAP.studyWorkspace)).toBe(true)
  })

  it('represents a failed capability request as unavailable and denies all affordances', () => {
    const state = unavailableCTMSCapabilities(new Error('network failure'))

    expect(state.status).toBe('unavailable')
    expect(state.manifest).toEqual(CTMS_DISABLED_MANIFEST)
    expect(isCTMSActionAvailable(state, CTMS_ACTION_ROUTE_MAP.studyWorkspace)).toBe(false)
  })

  it('requires the declared phase, capability, platform availability, and convenience permission', () => {
    const state = normalizeCTMSCapabilities({
      module: 'CTMS',
      enabled: true,
      phase: 3,
      capabilities: [CTMS_CAPABILITY_CODES.qualificationEvidence],
      platform_capabilities: { health_observability: true },
    })
    const health = CTMS_ACTION_ROUTE_MAP.health

    expect(isCTMSActionAvailable(state, health)).toBe(true)
    expect(isCTMSActionAvailable({ ...state, platformCapabilities: {} }, health)).toBe(false)
    expect(isCTMSActionAvailable(state, CTMS_ACTION_ROUTE_MAP.replayFailedEvent, [])).toBe(false)
  })
})
