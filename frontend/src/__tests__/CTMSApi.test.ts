import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { ctmsApi, ctmsKeys, normalizeCTMSError, serializeCTMSFilters } from '@/features/ctms/api'

describe('CTMS typed data access', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uses the authenticated CTMS namespace and preserves paginated list envelopes', async () => {
    const response = { items: [], page: 1, page_size: 50, total: 0 }
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: response } as never)

    await expect(ctmsApi.plans('study-1')).resolves.toEqual(response)
    expect(get).toHaveBeenCalledWith('/ctms/studies/study-1/plans')
    expect(ctmsKeys.plans('study-1')).toEqual(['ctms', 'plans', 'study-1'])
  })

  it('serializes supported filters and scopes response-affecting query keys', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [], page: 2, page_size: 25, total: 0, next_cursor: 'next-1' } } as never)
    const context = {
      routeScope: 'study-workspace',
      studyId: 'study-1',
      siteId: 'site-1',
      filters: { status: ['Open', 'Blocked'], ownerId: 'user-1' },
      pagination: { page: 2, pageSize: 25, cursor: 'cursor-1' },
      phase: 2 as const,
    }

    expect(serializeCTMSFilters(context.filters, context.pagination)).toEqual({
      status: 'Open,Blocked',
      owner_id: 'user-1',
      page: '2',
      page_size: '25',
      cursor: 'cursor-1',
    })
    expect(ctmsKeys.list('tasks', context)).toEqual([
      'ctms',
      'list',
      'tasks',
      expect.objectContaining({ routeScope: 'study-workspace', studyId: 'study-1', siteId: 'site-1', phase: 2 }),
    ])

    await ctmsApi.tasks('study-1', context)
    expect(get).toHaveBeenCalledWith('/ctms/studies/study-1/tasks?status=Open%2CBlocked&owner_id=user-1&page=2&page_size=25&cursor=cursor-1')
  })

  it('normalizes baseline errors and removes unsafe remediation details', () => {
    const error = normalizeCTMSError({
      response: {
        status: 409,
        headers: { 'X-Request-ID': 'request-1', 'X-Correlation-ID': 'corr-1' },
        data: {
          error: {
            code: 'COORDINATION_CONFLICT',
            message: 'The record requires remediation.',
            details: { field: 'status', raw_event: { secret: 'hidden' }, stack: 'trace hidden' },
          },
        },
      },
    })

    expect(error).toMatchObject({
      code: 'COORDINATION_CONFLICT',
      category: 'conflict',
      requestId: 'request-1',
      correlationId: 'corr-1',
      retryable: false,
    })
    expect(error.details).toEqual({ field: 'status' })
  })

  it('keeps report and health models on their dedicated CTMS endpoints', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: {} } as never)

    await ctmsApi.report('study-1', 'monitoring')
    await ctmsApi.health()

    expect(get).toHaveBeenNthCalledWith(1, '/ctms/studies/study-1/reports/monitoring')
    expect(get).toHaveBeenNthCalledWith(2, '/ctms/health')
  })
})
