import { describe, expect, it } from 'vitest'
import {
  EDC_NAVIGATION_SECTIONS,
  EDC_NAV_ITEMS,
  preserveCurrentSearch,
  resolveNavigationModel,
} from '@/lib/navigation-model'
import {
  CTMS_CAPABILITY_CODES,
  CTMS_PHASE_CAPABILITIES,
  normalizeCTMSCapabilities,
  unavailableCTMSCapabilities,
} from '@/features/ctms'
import { PERMISSIONS } from '@/lib/permissions'

const allPermissions = Object.values(PERMISSIONS)
const readyState = normalizeCTMSCapabilities({
  module: 'CTMS',
  enabled: true,
  phase: 3,
  capabilities: [...CTMS_PHASE_CAPABILITIES[3]],
  platform_capabilities: { health_observability: true },
})

describe('navigation model adapter', () => {
  it('groups every existing EDC target without changing its route', () => {
    const groupedItems = EDC_NAVIGATION_SECTIONS.flatMap((section) => section.items)

    expect(groupedItems).toHaveLength(EDC_NAV_ITEMS.length)
    expect(groupedItems.map((item) => item.to)).toEqual(EDC_NAV_ITEMS.map((item) => item.to))
    expect(new Set(EDC_NAVIGATION_SECTIONS.map((section) => section.id))).toEqual(new Set([
      'workspace',
      'study-data',
      'data-quality',
      'operations',
      'administration',
    ]))
  })

  it('delegates CTMS filtering and preserves section IDs, item IDs, and descendant matching', () => {
    const model = resolveNavigationModel(readyState, allPermissions, {
      studyId: 'study/one',
      siteId: 'site one',
    })
    const items = model.ctmsSections.flatMap((section) => section.items)

    expect(model.ctmsSections.map((section) => section.id)).toEqual([
      'study-operations',
      'site-operations',
      'reporting-exports',
      'coordination-health',
    ])
    expect(items.map((item) => item.id)).toEqual([
      'studyWorkspace', 'studyProfile', 'studyPlans', 'enrollment', 'milestones',
      'monitoringPlans', 'monitoringActivities', 'tasks', 'contacts', 'projections',
      'siteActivation', 'reports', 'exports', 'failedEvents', 'conflicts', 'health',
    ])
    expect(items.every((item) => item.activeOptions.exact === false)).toBe(true)
    expect(items.every((item) => item.search === preserveCurrentSearch)).toBe(true)
    expect(items.find((item) => item.id === 'studyWorkspace')?.to).toBe('/studies/study%2Fone/ctms')
    expect(items.find((item) => item.id === 'siteActivation')?.to).toBe('/sites/site%20one/ctms/activation')
  })

  it.each([
    ['disabled', normalizeCTMSCapabilities({ module: 'CTMS', enabled: false, phase: 0, capabilities: [] })],
    ['unavailable', unavailableCTMSCapabilities(new Error('offline'))],
  ] as const)('keeps EDC navigation while hiding CTMS when capability state is %s', (_name, state) => {
    const model = resolveNavigationModel(state, [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ], {
      studyId: 'study-1',
      siteId: 'site-1',
    })

    expect(model.edcSections.flatMap((section) => section.items)).toHaveLength(EDC_NAV_ITEMS.length)
    expect(model.ctmsSections).toEqual([])
  })

  it('provides identity search propagation for shell navigation links', () => {
    const search = { filter: 'open', page: 2 }
    expect(preserveCurrentSearch(search)).toBe(search)
  })

  it('does not infer CTMS policy from unrelated capability codes', () => {
    const state = normalizeCTMSCapabilities({
      module: 'CTMS',
      enabled: true,
      phase: 3,
      capabilities: [CTMS_CAPABILITY_CODES.operationalDashboards],
    })
    const model = resolveNavigationModel(state, [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ], { studyId: 'study-1' })

    expect(model.ctmsSections.flatMap((section) => section.items).map((item) => item.id)).toEqual(['studyWorkspace'])
  })
})
