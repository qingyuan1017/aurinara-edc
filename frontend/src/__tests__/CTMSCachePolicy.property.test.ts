import { QueryClient, type QueryKey } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import {
  invalidateCTMSMutation,
  type CTMSMutationResource,
  type CTMSMutationScope,
} from '@/features/ctms/cache'
import { ctmsKeys } from '@/features/ctms/api'

const mutationResources: CTMSMutationResource[] = [
  'study-profile',
  'plan',
  'site-profile',
  'activation',
  'enrollment-target',
  'milestone',
]

type MutationOutcome = 'succeeded' | 'failed'

interface GeneratedMutationCase {
  resource: CTMSMutationResource
  scope: CTMSMutationScope
  recordId: string
  outcome: MutationOutcome
  expectedKeys: QueryKey[]
  unaffectedCTMSKey: QueryKey
  edcKey: QueryKey
}

function generatedMutationCases(count: number): GeneratedMutationCase[] {
  return Array.from({ length: count }, (_, index) => {
    const resource = mutationResources[index % mutationResources.length]
    const studyId = `study-${index}`
    const siteId = `site-${index}`
    const recordId = `${resource}-${index}`
    const scope = resource === 'site-profile' || resource === 'activation'
      ? { studyId, siteId }
      : { studyId }
    const expectedKeys = (() => {
      switch (resource) {
        case 'study-profile':
          return [
            ctmsKeys.studyProfile(studyId),
            ctmsKeys.dashboard(studyId),
            ctmsKeys.report(studyId, 'operational'),
          ]
        case 'plan':
          return [ctmsKeys.plans(studyId), ctmsKeys.dashboard(studyId)]
        case 'site-profile':
          return [
            ctmsKeys.siteProfile(siteId),
            ctmsKeys.siteDashboard(siteId, { studyId }),
          ]
        case 'activation':
          return [
            ctmsKeys.activation(siteId),
            ctmsKeys.siteProfile(siteId),
            ctmsKeys.siteDashboard(siteId, { studyId }),
          ]
        case 'enrollment-target':
          return [
            ctmsKeys.targets(studyId),
            ctmsKeys.dashboard(studyId),
            ctmsKeys.report(studyId, 'operational'),
          ]
        case 'milestone':
          return [
            ctmsKeys.milestones(studyId),
            ctmsKeys.dashboard(studyId),
            ctmsKeys.report(studyId, 'operational'),
          ]
      }
    })()
    const unaffectedCTMSKey = resource === 'site-profile' || resource === 'activation'
      ? ctmsKeys.projections(studyId)
      : ctmsKeys.siteProfile(`other-site-${index}`)

    return {
      resource,
      scope,
      recordId,
      outcome: index % 3 === 0 ? 'failed' : 'succeeded',
      expectedKeys,
      unaffectedCTMSKey,
      edcKey: ['edc', 'clinical', 'study', studyId, 'authoritative', index],
    }
  })
}

function seedQuery(client: QueryClient, queryKey: QueryKey, marker: string): void {
  client.setQueryData(queryKey, { marker })
}

function isInvalidated(client: QueryClient, queryKey: QueryKey): boolean {
  return client.getQueryState(queryKey)?.isInvalidated ?? false
}

describe('CTMS mutation cache-policy properties', () => {
  // Feature: ctms-frontend, Property 6: Mutation outcomes produce minimal cache effects
  // **Validates: Requirements 5.7–5.8, 9.5, 10.6, 11.4–11.5**
  it('invalidates only affected CTMS families after success and preserves failed outcomes across 128 generated cases', async () => {
    for (const [index, mutation] of generatedMutationCases(128).entries()) {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { gcTime: Infinity, retry: false } },
      })
      const existingKeys = [
        ...mutation.expectedKeys,
        mutation.unaffectedCTMSKey,
        mutation.edcKey,
      ]

      existingKeys.forEach((queryKey, keyIndex) => seedQuery(queryClient, queryKey, `authoritative-${index}-${keyIndex}`))

      if (mutation.outcome === 'succeeded') {
        await invalidateCTMSMutation(queryClient, mutation.resource, mutation.scope)
      }

      for (const queryKey of mutation.expectedKeys) {
        expect(isInvalidated(queryClient, queryKey)).toBe(mutation.outcome === 'succeeded')
        expect(queryClient.getQueryData(queryKey)).toEqual(expect.objectContaining({ marker: expect.stringContaining(`authoritative-${index}-`) }))
      }

      expect(isInvalidated(queryClient, mutation.unaffectedCTMSKey)).toBe(false)
      expect(isInvalidated(queryClient, mutation.edcKey)).toBe(false)
      expect(queryClient.getQueryData(mutation.unaffectedCTMSKey)).toEqual(expect.objectContaining({ marker: expect.stringContaining(`authoritative-${index}-`) }))
      expect(queryClient.getQueryData(mutation.edcKey)).toEqual(expect.objectContaining({ marker: expect.stringContaining(`authoritative-${index}-`) }))

      queryClient.clear()
    }
  })
})
