import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import {
  ctmsApi,
  ctmsKeys,
  serializeCTMSFilters,
  type CTMSFilterState,
  type CTMSPagination,
  type CTMSPhase,
  type CTMSQueryContext,
} from '@/features/ctms/api'

type ParsedSearchState = {
  filters: CTMSFilterState
  pagination: CTMSPagination
}

const generatedWord = (seed: number, prefix: string) => `${prefix}-${seed}`

function generatedContext(seed: number): CTMSQueryContext {
  const status = seed % 3 === 0
    ? [generatedWord(seed, 'open'), generatedWord(seed + 1, 'blocked')]
    : generatedWord(seed, seed % 2 ? 'open' : 'closed')
  const recordType = seed % 4 === 0
    ? [generatedWord(seed, 'task'), generatedWord(seed + 1, 'milestone')]
    : generatedWord(seed, 'task')
  const filters: CTMSFilterState = {
    status,
    siteId: generatedWord(seed, 'site'),
    ownerId: seed % 2 === 0 ? generatedWord(seed, 'owner') : undefined,
    from: `2026-${String((seed % 12) + 1).padStart(2, '0')}-01`,
    to: `2026-${String((seed % 12) + 1).padStart(2, '0')}-28`,
    priority: seed % 3 === 0 ? 'high' : 'normal',
    dueCategory: seed % 2 === 0 ? 'overdue' : 'upcoming',
    reportType: seed % 2 === 0 ? 'monitoring' : 'enrollment',
    recordType,
    includeArchived: seed % 2 === 0,
  }
  const pagination: CTMSPagination = {
    page: (seed % 7) + 1,
    pageSize: [10, 25, 50][seed % 3],
    cursor: seed % 2 === 0 ? generatedWord(seed, 'cursor') : null,
  }

  return {
    routeScope: seed % 2 === 0 ? 'study-workspace' : 'site-workspace',
    studyId: generatedWord(seed, 'study'),
    siteId: generatedWord(seed, 'site'),
    filters,
    pagination,
    phase: (seed % 4) as CTMSPhase,
  }
}

function parseSearchState(search: string): ParsedSearchState {
  const params = new URLSearchParams(search)
  const list = (name: string): string | string[] | undefined => {
    const value = params.get(name)
    if (!value) return undefined
    return value.includes(',') ? value.split(',') : value
  }
  const optionalNumber = (name: string): number | undefined => {
    const value = params.get(name)
    return value === null ? undefined : Number(value)
  }
  const optionalBoolean = (name: string): boolean | undefined => {
    const value = params.get(name)
    return value === null ? undefined : value === 'true'
  }

  return {
    filters: {
      status: list('status'),
      siteId: params.get('site_id') ?? undefined,
      ownerId: params.get('owner_id') ?? undefined,
      from: params.get('date_from') ?? undefined,
      to: params.get('date_to') ?? undefined,
      priority: params.get('priority') ?? undefined,
      dueCategory: params.get('due_category') ?? undefined,
      reportType: params.get('report_type') ?? undefined,
      recordType: list('record_type'),
      includeArchived: optionalBoolean('include_archived'),
    },
    pagination: {
      page: optionalNumber('page'),
      pageSize: optionalNumber('page_size'),
      cursor: params.get('cursor'),
    },
  }
}

function withoutUndefined<T extends Record<string, unknown>>(value: T): Partial<T> {
  return Object.fromEntries(Object.entries(value).filter(([, entry]) => entry !== undefined)) as Partial<T>
}

describe('CTMS scoped filter property', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('round-trips scope, filters, pagination, and phase across request search state and query keys', async () => {
    // Feature: ctms-frontend, Property 2: Scope and filters round-trip without ambiguity
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: { items: [], page: 1, page_size: 25, total: 0 },
    } as never)

    for (let seed = 1; seed <= 128; seed += 1) {
      const context = generatedContext(seed)
      const expectedParams = serializeCTMSFilters(context.filters, context.pagination)

      await ctmsApi.tasks(context.studyId!, context)

      const requestPath = get.mock.calls[seed - 1]?.[0]
      expect(requestPath).toBeTypeOf('string')
      const requestUrl = new URL(requestPath as string, 'https://ctms.test')
      const actualParams = Object.fromEntries(requestUrl.searchParams.entries())
      expect(actualParams).toEqual(expectedParams)

      const parsed = parseSearchState(requestUrl.search)
      expect(withoutUndefined(parsed.filters)).toEqual(withoutUndefined({
        status: context.filters?.status,
        siteId: context.filters?.siteId,
        ownerId: context.filters?.ownerId,
        from: context.filters?.from,
        to: context.filters?.to,
        priority: context.filters?.priority,
        dueCategory: context.filters?.dueCategory,
        reportType: context.filters?.reportType,
        recordType: context.filters?.recordType,
        includeArchived: context.filters?.includeArchived,
      }))
      expect(parsed.pagination).toEqual(context.pagination)

      expect(ctmsKeys.list('tasks', context)).toEqual([
        'ctms',
        'list',
        'tasks',
        {
          routeScope: context.routeScope,
          studyId: context.studyId,
          siteId: context.siteId,
          filters: context.filters,
          pagination: context.pagination,
          phase: context.phase,
        },
      ])
    }
  })
})
