import { describe, expect, it } from 'vitest'
import { router } from '@/lib/router'
import {
  CTMS_PHASE_CAPABILITIES,
  normalizeCTMSCapabilities,
} from '@/features/ctms'
import {
  PV_DISABLED_MANIFEST,
  normalizePVCapabilities,
  resolvePVNavigation,
  unavailablePVCapabilities,
} from '@/features/pv'
import { resolveNavigationModel } from '@/lib/navigation-model'
import { PERMISSIONS } from '@/lib/permissions'

const studyParams = { studyId: 'study-1' }
const siteParams = { siteId: 'site-1' }
const caseParams = { studyId: 'study-1', caseId: 'case-1' }
const search = { tab: 'cases', page: 2 }
const allPermissions = Object.values(PERMISSIONS)
const baselineCTMSState = normalizeCTMSCapabilities({
  module: 'CTMS',
  enabled: true,
  phase: 3,
  capabilities: [...CTMS_PHASE_CAPABILITIES[3]],
  platform_capabilities: { health_observability: true },
})

describe('PV route registration and deep-link preservation', () => {
  it('keeps EDC and CTMS navigation unchanged when PV is disabled, empty, or unavailable', () => {
    const baseline = resolveNavigationModel(baselineCTMSState, allPermissions, {
      studyId: 'study-1',
      siteId: 'site-1',
    })
    const pvStates = [
      normalizePVCapabilities(PV_DISABLED_MANIFEST),
      normalizePVCapabilities({ module: 'PV', enabled: true, phase: 1, capabilities: [] }),
      unavailablePVCapabilities(new Error('worker unavailable')),
    ]

    for (const pvState of pvStates) {
      expect(resolvePVNavigation(pvState, allPermissions, { studyId: 'study-1', siteId: 'site-1' })).toEqual([])
      expect(resolveNavigationModel(baselineCTMSState, allPermissions, {
        studyId: 'study-1',
        siteId: 'site-1',
      })).toEqual(baseline)
    }

    expect(baseline.edcSections.flatMap((section) => section.items).map((item) => item.to)).toContain('/')
    expect(baseline.ctmsSections.flatMap((section) => section.items).map((item) => item.to)).toContain('/studies/study-1/ctms')
  })

  it('registers every authenticated PV study, case, site, and oversight route', () => {
    const paths = [
      router.buildLocation({ to: '/pv' }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/dashboard', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/cases', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/cases/$caseId', params: caseParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/cases/$caseId/assessments', params: caseParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/cases/$caseId/coding', params: caseParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/cases/$caseId/narratives', params: caseParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/cases/$caseId/reports', params: caseParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/reconciliation', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/exports', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/pv/audit', params: studyParams }).pathname,
      router.buildLocation({ to: '/sites/$siteId/pv/dashboard', params: siteParams }).pathname,
    ]

    expect(paths).toEqual([
      '/pv',
      '/studies/study-1/pv/dashboard',
      '/studies/study-1/pv/cases',
      '/studies/study-1/pv/cases/case-1',
      '/studies/study-1/pv/cases/case-1/assessments',
      '/studies/study-1/pv/cases/case-1/coding',
      '/studies/study-1/pv/cases/case-1/narratives',
      '/studies/study-1/pv/cases/case-1/reports',
      '/studies/study-1/pv/reconciliation',
      '/studies/study-1/pv/exports',
      '/studies/study-1/pv/audit',
      '/sites/site-1/pv/dashboard',
    ])
  })

  it('preserves representative search parameters on PV deep links', () => {
    const location = router.buildLocation({
      to: '/studies/$studyId/pv/cases',
      params: studyParams,
      search,
    })
    expect(location.pathname).toBe('/studies/study-1/pv/cases')
    expect(location.search).toEqual(search)
  })

  it('leaves baseline EDC navigation unchanged when PV routes are present', () => {
    const paths = [
      router.buildLocation({ to: '/' }).pathname,
      router.buildLocation({ to: '/studies' }).pathname,
      router.buildLocation({ to: '/subjects' }).pathname,
      router.buildLocation({ to: '/queries' }).pathname,
      router.buildLocation({ to: '/exports' }).pathname,
      router.buildLocation({ to: '/audit' }).pathname,
    ]
    expect(paths).toEqual(['/', '/studies', '/subjects', '/queries', '/exports', '/audit'])
  })

  it('leaves CTMS study and site routes unchanged when PV routes are present', () => {
    const paths = [
      router.buildLocation({ to: '/ctms' }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/exports', params: studyParams }).pathname,
      router.buildLocation({ to: '/sites/$siteId/ctms', params: siteParams }).pathname,
      router.buildLocation({ to: '/sites/$siteId/ctms/activation', params: siteParams }).pathname,
    ]
    expect(paths).toEqual([
      '/ctms',
      '/studies/study-1/ctms',
      '/studies/study-1/ctms/exports',
      '/sites/site-1/ctms',
      '/sites/site-1/ctms/activation',
    ])
  })
})
