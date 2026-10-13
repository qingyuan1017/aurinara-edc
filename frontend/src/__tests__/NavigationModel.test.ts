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
import { PV_DISABLED_MANIFEST, normalizePVCapabilities } from '@/features/pv'
import { PERMISSIONS } from '@/lib/permissions'
import { getDesignerLandingPath } from '@/features/designer/navigation'

const allPermissions = Object.values(PERMISSIONS)
const readyState = normalizeCTMSCapabilities({
  module: 'CTMS',
  enabled: true,
  phase: 3,
  capabilities: [...CTMS_PHASE_CAPABILITIES[3]],
  platform_capabilities: { health_observability: true },
})
const disabledPVState = normalizePVCapabilities(PV_DISABLED_MANIFEST)

describe('navigation model adapter', () => {
  it('groups the eight study-scoped EDC workspaces and their submenus', () => {
    const groupedItems = EDC_NAVIGATION_SECTIONS.flatMap((section) => section.items)

    expect(groupedItems).toHaveLength(EDC_NAV_ITEMS.length)
    expect(groupedItems.map((item) => item.to)).toEqual(EDC_NAV_ITEMS.map((item) => item.to))
    expect(new Set(EDC_NAVIGATION_SECTIONS.map((section) => section.id))).toEqual(new Set([
      'overview',
      'subjects',
      'data-entry',
      'data-review',
      'queries',
      'medical-coding',
      'exports',
      'database-lock',
    ]))

    const model = resolveNavigationModel(readyState, disabledPVState, allPermissions, { studyId: 'study/one' })
    const edcItems = model.edcSections.flatMap((section) => section.items)
    expect(edcItems.find((item) => item.id === 'edc-dashboard')?.to).toBe('/studies/study%2Fone/edc/overview')
    expect(edcItems.find((item) => item.id === 'subject-list')?.to).toBe('/studies/study%2Fone/edc/subjects')
    expect(edcItems.find((item) => item.id === 'database-lock-unlock')?.to).toBe('/studies/study%2Fone/edc/database-lock/manage')
  })

  it('keeps Designer navigation in its own permission-filtered module', () => {
    const model = resolveNavigationModel(readyState, disabledPVState, allPermissions)
    const designerItems = model.designerSections.flatMap((section) => section.items)

    expect(model.edcSections.flatMap((section) => section.items).some((item) => item.to.startsWith('/designer'))).toBe(false)
    expect(model.designerSections.map((section) => section.id)).toEqual([
      'lifecycle',
      'crf-design',
      'rules-and-standards',
    ])
    expect(designerItems.map((item) => item.to)).toContain('/designer/forms')
    expect(designerItems.map((item) => item.to)).toContain('/designer/versions')
    expect(designerItems.every((item) => item.activeOptions.exact === false)).toBe(true)

    const noDesignerAccess = resolveNavigationModel(readyState, disabledPVState, [])
    expect(noDesignerAccess.designerSections).toEqual([])
    expect(getDesignerLandingPath([PERMISSIONS.DESIGNER_FORM_READ])).toBe('/designer/forms')
    expect(getDesignerLandingPath([PERMISSIONS.DESIGNER_STUDY_VERSION_READ])).toBe('/designer/versions')
    expect(getDesignerLandingPath([])).toBeNull()
  })

  it('delegates CTMS filtering and uses exact matching for the Overview parent route', () => {
    const model = resolveNavigationModel(readyState, disabledPVState, allPermissions, {
      studyId: 'study/one',
      siteId: 'site one',
    })
    const items = model.ctmsSections.flatMap((section) => section.items)

    expect(model.ctmsSections.map((section) => section.id)).toEqual([
      'overview',
      'study-management',
      'sites',
      'monitoring',
      'contracts',
      'financials',
      'tasks-issues',
      'documents',
      'reports',
    ])
    expect(items.map((item) => item.id)).toContain('studyDashboard')
    expect(items.map((item) => item.id)).toContain('monitoringVisits')
    expect(items.map((item) => item.id)).toContain('studyContracts')
    expect(items.map((item) => item.id)).toContain('financialReports')
    expect(items.find((item) => item.id === 'studyDashboard')?.activeOptions.exact).toBe(true)
    expect(items.every((item) => item.search === preserveCurrentSearch)).toBe(true)
    expect(items.find((item) => item.id === 'studyDashboard')?.to).toBe('/studies/study%2Fone/ctms')
    expect(items.find((item) => item.id === 'studyInformation')?.to).toBe('/studies/study%2Fone/ctms/details')
    expect(items.find((item) => item.id === 'studyPlans')?.to).toBe('/studies/study%2Fone/ctms/project-management')
    expect(items.find((item) => item.id === 'studyFinancialOverview')?.to).toBe('/studies/study%2Fone/ctms/financial-management')
    expect(items.find((item) => item.id === 'monitoringOverview')?.to).toBe('/studies/study%2Fone/ctms/monitoring')
  })

  it.each([
    ['disabled', normalizeCTMSCapabilities({ module: 'CTMS', enabled: false, phase: 0, capabilities: [] })],
    ['unavailable', unavailableCTMSCapabilities(new Error('offline'))],
  ] as const)('keeps EDC navigation while hiding CTMS when capability state is %s', (_name, state) => {
    const model = resolveNavigationModel(state, disabledPVState, [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ], {
      studyId: 'study-1',
      siteId: 'site-1',
    })

    expect(model.edcSections.flatMap((section) => section.items)).toHaveLength(EDC_NAV_ITEMS.length)
    expect(model.ctmsSections).toEqual([])
    expect(model.pvSections).toEqual([])
  })

  it('resolves PV sections with view-model adapters when PV is ready and the user may read safety cases', () => {
    const pvReadyState = normalizePVCapabilities({
      module: 'PV',
      enabled: true,
      phase: 1,
      capabilities: ['safety_case_intake', 'safety_dashboards', 'safety_exports', 'shared_audit'],
    })
    const model = resolveNavigationModel(readyState, pvReadyState, allPermissions, {
      studyId: 'study-1',
      siteId: 'site-1',
    })
    const pvItems = model.pvSections.flatMap((section) => section.items)

    expect(pvItems.map((item) => item.id)).toEqual(['dashboard', 'cases', 'exports', 'audit', 'siteDashboard'])
    expect(pvItems.every((item) => item.activeOptions.exact === false)).toBe(true)
    expect(pvItems.every((item) => item.search === preserveCurrentSearch)).toBe(true)
    expect(pvItems.find((item) => item.id === 'dashboard')?.to).toBe('/studies/study-1/pv/dashboard')
    expect(pvItems.find((item) => item.id === 'siteDashboard')?.to).toBe('/sites/site-1/pv/dashboard')
    // PV is purely additive: EDC and CTMS navigation are unchanged.
    expect(model.edcSections.flatMap((section) => section.items)).toHaveLength(EDC_NAV_ITEMS.length)
    expect(model.ctmsSections.flatMap((section) => section.items).length).toBeGreaterThan(0)
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
    const model = resolveNavigationModel(state, disabledPVState, [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ], { studyId: 'study-1' })

    expect(model.ctmsSections.flatMap((section) => section.items).map((item) => item.id)).toEqual(['studyDashboard'])
  })
})
