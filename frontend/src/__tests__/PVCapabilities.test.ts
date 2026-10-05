import { describe, expect, it } from 'vitest'
import {
  PV_ACTION_ROUTE_MAP,
  PV_CAPABILITY_CODES,
  PV_DISABLED_MANIFEST,
  isPVActionAvailable,
  normalizePVCapabilities,
  unavailablePVCapabilities,
  resolvePVNavigation,
  type PVCapabilityManifest,
} from '@/features/pv'
import { PERMISSIONS } from '@/lib/permissions'

const READ = PERMISSIONS.PV_SAFETY_CASE_READ

function readyManifest(overrides: Partial<PVCapabilityManifest> = {}): PVCapabilityManifest {
  return {
    module: 'PV',
    enabled: true,
    phase: 3,
    capabilities: Object.values(PV_CAPABILITY_CODES),
    ...overrides,
  }
}

describe('PV capability boundary', () => {
  it('keeps PV disabled by default without altering EDC/CTMS', () => {
    expect(PV_DISABLED_MANIFEST).toEqual({ module: 'PV', enabled: false, phase: 0, capabilities: [] })
  })

  it('treats a failed capability request as unavailable and denies every affordance', () => {
    const state = unavailablePVCapabilities(new Error('network failure'))
    expect(state.status).toBe('unavailable')
    expect(isPVActionAvailable(state, PV_ACTION_ROUTE_MAP.cases, [READ])).toBe(false)
  })

  it('requires ready status, phase, capability, and convenience permission', () => {
    const state = normalizePVCapabilities(readyManifest())
    expect(state.status).toBe('ready')
    expect(isPVActionAvailable(state, PV_ACTION_ROUTE_MAP.cases, [READ])).toBe(true)
    // Missing permission hides the affordance.
    expect(isPVActionAvailable(state, PV_ACTION_ROUTE_MAP.cases, [])).toBe(false)
    // A phase-3 capability is denied on a phase-1 manifest.
    const phase1 = normalizePVCapabilities(
      readyManifest({ phase: 1, capabilities: [PV_CAPABILITY_CODES.safetyCaseIntake] }),
    )
    expect(isPVActionAvailable(phase1, PV_ACTION_ROUTE_MAP.coding, [READ])).toBe(false)
  })

  it('resolves navigation only when ready and the user can read PV', () => {
    const state = normalizePVCapabilities(readyManifest())
    const permissions = [READ, PERMISSIONS.PV_SAFETY_EXPORT_CREATE, PERMISSIONS.PV_SAFETY_AUDIT_READ]
    const sections = resolvePVNavigation(state, permissions, { studyId: 'study-1', siteId: 'site-1' })
    const labels = sections.flatMap((section) => section.items.map((item) => item.label))
    expect(labels).toEqual(
      expect.arrayContaining(['Dashboard', 'Cases', 'Reconciliation', 'Exports', 'Audit', 'Site dashboard']),
    )
    const casesItem = sections.flatMap((s) => s.items).find((item) => item.id === 'cases')
    expect(casesItem?.to).toBe('/studies/study-1/pv/cases')
  })

  it('hides export and audit affordances when the user lacks their permissions', () => {
    const state = normalizePVCapabilities(readyManifest())
    const sections = resolvePVNavigation(state, [READ], { studyId: 'study-1', siteId: 'site-1' })
    const labels = sections.flatMap((section) => section.items.map((item) => item.label))
    expect(labels).toContain('Cases')
    expect(labels).not.toContain('Exports')
    expect(labels).not.toContain('Audit')
  })

  it('returns no PV navigation when the module is disabled, keeping EDC/CTMS untouched', () => {
    const disabled = normalizePVCapabilities(PV_DISABLED_MANIFEST)
    expect(resolvePVNavigation(disabled, [READ], { studyId: 'study-1' })).toEqual([])
  })

  it('returns no PV navigation when the user lacks the read permission', () => {
    const state = normalizePVCapabilities(readyManifest())
    expect(resolvePVNavigation(state, [], { studyId: 'study-1' })).toEqual([])
  })
})
