import { describe, expect, it } from 'vitest'
import { router } from '@/lib/router'
import { EDC_NAVIGATION_DEFINITIONS, getEDCLandingPath, getEDCStudyIdFromPath } from '@/features/edc'

const studyParams = { studyId: 'study-1' }

describe('study-scoped EDC routes', () => {
  it('registers the shared workspace outside study scope', () => {
    expect(router.buildLocation({ to: '/workspace' }).pathname).toBe('/workspace')
  })

  it('registers every first-class EDC navigation destination', () => {
    const routes = EDC_NAVIGATION_DEFINITIONS.flatMap((section) => section.items.map((item) => (
      `/studies/$studyId/edc${item.path}`
    )))

    expect(routes.map((to) => router.buildLocation({ to, params: studyParams }).pathname)).toEqual(
      routes.map((to) => to.replace('$studyId', 'study-1')),
    )
  })

  it('registers subject-centric profile, visits, form, and query deep links', () => {
    expect(router.buildLocation({
      to: '/studies/$studyId/edc/subjects/$subjectId',
      params: { studyId: 'study-1', subjectId: 'subject-1' },
    }).pathname).toBe('/studies/study-1/edc/subjects/subject-1')

    expect(router.buildLocation({
      to: '/studies/$studyId/edc/subjects/$subjectId/visits/$visitId/forms/$formId',
      params: { studyId: 'study-1', subjectId: 'subject-1', visitId: 'visit-1', formId: 'form-1' },
    }).pathname).toBe('/studies/study-1/edc/subjects/subject-1/visits/visit-1/forms/form-1')

    expect(router.buildLocation({
      to: '/studies/$studyId/edc/queries/$queryId',
      params: { studyId: 'study-1', queryId: 'query-1' },
    }).pathname).toBe('/studies/study-1/edc/queries/query-1')
  })

  it('derives and encodes the study context for direct links and module switching', () => {
    expect(getEDCStudyIdFromPath('/studies/study%2Fone/edc/subjects')).toBe('study/one')
    expect(getEDCStudyIdFromPath('/subjects')).toBeNull()
    expect(getEDCLandingPath('study/one')).toBe('/studies/study%2Fone/edc/overview')
  })
})
