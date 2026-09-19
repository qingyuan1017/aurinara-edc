import { describe, expect, it } from 'vitest'
import { router } from '@/lib/router'

const studyParams = { studyId: 'study-1' }
const siteParams = { siteId: 'site-1' }
const queryParams = { queryId: 'query-1' }
const subjectParams = { subjectId: 'subject-1' }
const formParams = { subjectId: 'subject-1', formInstanceId: 'form-1' }
const search = { tab: 'quality', page: 2, filter: 'open' }

describe('route registration and deep-link preservation', () => {
  it('registers every public and EDC route family without changing path parameters', () => {
    const paths = [
      router.buildLocation({ to: '/login' }).pathname,
      router.buildLocation({ to: '/forgot-password' }).pathname,
      router.buildLocation({ to: '/reset-password' }).pathname,
      router.buildLocation({ to: '/accept-invitation' }).pathname,
      router.buildLocation({ to: '/access-denied' }).pathname,
      router.buildLocation({ to: '/' }).pathname,
      router.buildLocation({ to: '/studies' }).pathname,
      router.buildLocation({ to: '/studies/$studyId', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/dashboard', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/forms', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/versions', params: studyParams }).pathname,
      router.buildLocation({ to: '/sites' }).pathname,
      router.buildLocation({ to: '/subjects' }).pathname,
      router.buildLocation({ to: '/subjects/$subjectId/forms/$formInstanceId', params: formParams }).pathname,
      router.buildLocation({ to: '/subjects/$subjectId/casebook', params: subjectParams }).pathname,
      router.buildLocation({ to: '/subjects/$subjectId/visits', params: subjectParams }).pathname,
      router.buildLocation({ to: '/subjects/$subjectId/signatures', params: subjectParams }).pathname,
      router.buildLocation({ to: '/forms' }).pathname,
      router.buildLocation({ to: '/queries' }).pathname,
      router.buildLocation({ to: '/queries/$queryId', params: queryParams }).pathname,
      router.buildLocation({ to: '/exports' }).pathname,
      router.buildLocation({ to: '/edit-checks' }).pathname,
      router.buildLocation({ to: '/studies/$studyId/edit-checks', params: studyParams }).pathname,
      router.buildLocation({ to: '/data-cleaning' }).pathname,
      router.buildLocation({ to: '/sdv' }).pathname,
      router.buildLocation({ to: '/review' }).pathname,
      router.buildLocation({ to: '/ai' }).pathname,
      router.buildLocation({ to: '/notifications' }).pathname,
      router.buildLocation({ to: '/admin' }).pathname,
      router.buildLocation({ to: '/audit' }).pathname,
    ]

    expect(paths).toEqual([
      '/login',
      '/forgot-password',
      '/reset-password',
      '/accept-invitation',
      '/access-denied',
      '/',
      '/studies',
      '/studies/study-1',
      '/studies/study-1/dashboard',
      '/studies/study-1/forms',
      '/studies/study-1/versions',
      '/sites',
      '/subjects',
      '/subjects/subject-1/forms/form-1',
      '/subjects/subject-1/casebook',
      '/subjects/subject-1/visits',
      '/subjects/subject-1/signatures',
      '/forms',
      '/queries',
      '/queries/query-1',
      '/exports',
      '/edit-checks',
      '/studies/study-1/edit-checks',
      '/data-cleaning',
      '/sdv',
      '/review',
      '/ai',
      '/notifications',
      '/admin',
      '/audit',
    ])
  })

  it('preserves representative search parameters on EDC and direct access-denied deep links', () => {
    const edcLocation = router.buildLocation({ to: '/subjects', search })
    const deniedLocation = router.buildLocation({ to: '/access-denied', search })

    expect(edcLocation.pathname).toBe('/subjects')
    expect(edcLocation.search).toEqual(search)
    expect(deniedLocation.pathname).toBe('/access-denied')
    expect(deniedLocation.search).toEqual(search)
  })

  it('registers every CTMS study, site, reporting, coordination, and health route', () => {
    const paths = [
      router.buildLocation({ to: '/ctms' }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/profile', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/plans', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/enrollment', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/milestones', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/tasks', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/contacts', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/monitoring-plans', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/monitoring-activities', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/projections', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/reports/$type', params: { ...studyParams, type: 'monitoring' } }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/exports', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/coordination/failed-events', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/coordination/conflicts', params: studyParams }).pathname,
      router.buildLocation({ to: '/studies/$studyId/ctms/health', params: studyParams }).pathname,
      router.buildLocation({ to: '/sites/$siteId/ctms', params: siteParams }).pathname,
      router.buildLocation({ to: '/sites/$siteId/ctms/activation', params: siteParams }).pathname,
    ]

    expect(paths).toEqual([
      '/ctms',
      '/studies/study-1/ctms',
      '/studies/study-1/ctms/profile',
      '/studies/study-1/ctms/plans',
      '/studies/study-1/ctms/enrollment',
      '/studies/study-1/ctms/milestones',
      '/studies/study-1/ctms/tasks',
      '/studies/study-1/ctms/contacts',
      '/studies/study-1/ctms/monitoring-plans',
      '/studies/study-1/ctms/monitoring-activities',
      '/studies/study-1/ctms/projections',
      '/studies/study-1/ctms/reports/monitoring',
      '/studies/study-1/ctms/exports',
      '/studies/study-1/ctms/coordination/failed-events',
      '/studies/study-1/ctms/coordination/conflicts',
      '/studies/study-1/ctms/health',
      '/sites/site-1/ctms',
      '/sites/site-1/ctms/activation',
    ])
  })

  it('preserves search parameters on representative CTMS deep links', () => {
    const location = router.buildLocation({
      to: '/studies/$studyId/ctms/reports/$type',
      params: { ...studyParams, type: 'monitoring' },
      search,
    })

    expect(location.pathname).toBe('/studies/study-1/ctms/reports/monitoring')
    expect(location.search).toEqual(search)
  })
})
