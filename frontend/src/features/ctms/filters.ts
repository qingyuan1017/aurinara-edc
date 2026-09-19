import type { CTMSFilterState, CTMSPagination } from './api'

/** Search parameters supported by CTMS dashboard, report, and list routes. */
export interface CTMSSearchState extends CTMSFilterState, CTMSPagination {}

const SEARCH_KEYS = [
  'status',
  'siteId',
  'ownerId',
  'from',
  'to',
  'priority',
  'dueCategory',
  'reportType',
  'page',
  'pageSize',
  'cursor',
] as const

function stringValue(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return undefined
}

function stringListValue(value: unknown): string | string[] | undefined {
  if (Array.isArray(value)) {
    const values = value.map(stringValue).filter((item): item is string => Boolean(item))
    return values.length > 1 ? values : values[0]
  }
  const string = stringValue(value)
  if (!string) return undefined
  const values = string.split(',').map((item) => item.trim()).filter(Boolean)
  return values.length > 1 ? values : values[0]
}

function positiveInteger(value: unknown): number | undefined {
  const string = stringValue(value)
  if (!string) return undefined
  const parsed = Number.parseInt(string, 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
}

/** Normalize TanStack Router's decoded search object into the supported CTMS model. */
export function parseCTMSSearch(search: Record<string, unknown> | null | undefined): CTMSSearchState {
  const source = search ?? {}
  const result: CTMSSearchState = {}
  const status = stringListValue(source.status)
  const recordType = stringListValue(source.recordType)
  if (status) result.status = status
  if (recordType) result.recordType = recordType
  if (stringValue(source.siteId)) result.siteId = stringValue(source.siteId)
  if (stringValue(source.ownerId)) result.ownerId = stringValue(source.ownerId)
  if (stringValue(source.from)) result.from = stringValue(source.from)
  if (stringValue(source.to)) result.to = stringValue(source.to)
  if (stringValue(source.priority)) result.priority = stringValue(source.priority)
  if (stringValue(source.dueCategory)) result.dueCategory = stringValue(source.dueCategory)
  if (stringValue(source.reportType)) result.reportType = stringValue(source.reportType)
  if (positiveInteger(source.page)) result.page = positiveInteger(source.page)
  if (positiveInteger(source.pageSize)) result.pageSize = positiveInteger(source.pageSize)
  if (stringValue(source.cursor)) result.cursor = stringValue(source.cursor)
  return result
}

/** Return only supported, URL-safe search keys for TanStack Router navigation. */
export function serializeCTMSSearch(state: CTMSSearchState): Record<string, string | undefined> {
  const result: Record<string, string | undefined> = {}
  for (const key of SEARCH_KEYS) {
    const value = state[key]
    if (Array.isArray(value)) result[key] = value.length ? value.join(',') : undefined
    else if (value !== undefined && value !== null && value !== '') result[key] = String(value)
    else result[key] = undefined
  }
  return result
}

export function filtersFromSearch(search: CTMSSearchState): CTMSFilterState {
  const { page: _page, pageSize: _pageSize, cursor: _cursor, ...filters } = search
  return filters
}

export function paginationFromSearch(search: CTMSSearchState): CTMSPagination {
  return { page: search.page, pageSize: search.pageSize, cursor: search.cursor }
}

export function activeCTMSFilters(filters: CTMSFilterState): Array<{ label: string; value: string }> {
  const values: Array<{ label: string; value: string }> = []
  const add = (label: string, value: string | string[] | number | boolean | undefined) => {
    if (value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) return
    values.push({ label, value: Array.isArray(value) ? value.join(', ') : String(value) })
  }
  add('Status', filters.status)
  add('Site', filters.siteId)
  add('Owner', filters.ownerId)
  add('From', filters.from)
  add('To', filters.to)
  add('Priority', filters.priority)
  add('Due date', filters.dueCategory)
  add('Report type', filters.reportType)
  return values
}

export function hasActiveCTMSFilters(filters: CTMSFilterState): boolean {
  return activeCTMSFilters(filters).length > 0
}
