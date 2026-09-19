import { describe, expect, it } from 'vitest'
import { activeCTMSFilters, filtersFromSearch, parseCTMSSearch, paginationFromSearch, serializeCTMSSearch } from '@/features/ctms/filters'

describe('CTMS route filter search state', () => {
  it('normalizes supported URL values and preserves filters and pagination through serialization', () => {
    const search = parseCTMSSearch({ status: 'Open,Blocked', siteId: 'site-1', ownerId: 'user-1', from: '2026-03-01', to: '2026-03-31', priority: 'high', dueCategory: 'overdue', reportType: 'tasks', page: '2', pageSize: '25', cursor: 'cursor-2', ignored: 'not-sent' })
    expect(search).toEqual({ status: ['Open', 'Blocked'], siteId: 'site-1', ownerId: 'user-1', from: '2026-03-01', to: '2026-03-31', priority: 'high', dueCategory: 'overdue', reportType: 'tasks', page: 2, pageSize: 25, cursor: 'cursor-2' })
    expect(parseCTMSSearch(serializeCTMSSearch(search))).toEqual(search)
    expect(filtersFromSearch(search)).toEqual({ status: ['Open', 'Blocked'], siteId: 'site-1', ownerId: 'user-1', from: '2026-03-01', to: '2026-03-31', priority: 'high', dueCategory: 'overdue', reportType: 'tasks' })
    expect(paginationFromSearch(search)).toEqual({ page: 2, pageSize: 25, cursor: 'cursor-2' })
  })

  it('drops invalid pagination and produces an explicit active-filter summary', () => {
    const search = parseCTMSSearch({ page: '0', pageSize: '-1', status: '', ownerId: 'owner-1' })
    expect(search).toEqual({ ownerId: 'owner-1' })
    expect(activeCTMSFilters(search)).toEqual([{ label: 'Owner', value: 'owner-1' }])
  })
})
