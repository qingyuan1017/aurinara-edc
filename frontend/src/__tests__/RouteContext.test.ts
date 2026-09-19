import { describe, expect, it } from 'vitest'
import {
  createBreadcrumbParentLink,
  createSearchPreservingParentLink,
  createShellSearchPreservingLink,
  decodeRouteIdentifier,
  encodeRouteIdentifier,
  getRouteBreadcrumbs,
  getRouteContext,
  classifyShellAction,
  isPresentationOnlyAction,
} from '@/lib/route-context'

describe('route context adapter', () => {
  it('encodes dynamic identifiers and decodes them only for display', () => {
    const identifier = 'study/with spaces'
    expect(encodeRouteIdentifier(identifier)).toBe('study%2Fwith%20spaces')
    expect(decodeRouteIdentifier(encodeRouteIdentifier(identifier))).toBe(identifier)
    expect(decodeRouteIdentifier('%E0%A4%A')).toBe('%E0%A4%A')
  })

  it('derives readable breadcrumbs with encoded parent paths', () => {
    const search = { tab: 'overview', page: 3 }
    const breadcrumbs = getRouteBreadcrumbs({
      pathname: '/studies/study%2Fone/ctms/reports/monitoring',
      search,
    })

    expect(breadcrumbs.map((item) => item.label)).toEqual([
      'Studies',
      'Study study/one',
      'CTMS',
      'Reports & dashboards',
      'Report monitoring',
    ])
    expect(breadcrumbs[1].to).toBe('/studies/study%2Fone')
    expect(breadcrumbs[1].search?.({ ignored: true })).toEqual(search)
    expect(breadcrumbs.at(-1)?.current).toBe(true)
    expect(breadcrumbs.at(-1)?.to).toBeUndefined()
  })

  it('preserves route search values in parent links without mutating the source', () => {
    const search = { filter: 'active', query: 'subject/1' }
    const link = createSearchPreservingParentLink('/subjects', search)
    const next = link.search({ unrelated: true })

    expect(link.to).toBe('/subjects')
    expect(next).toEqual(search)
    expect(next).not.toBe(search)
    expect(search).toEqual({ filter: 'active', query: 'subject/1' })
  })

  it('creates breadcrumb and shell links that preserve supported and unknown search values', () => {
    const search = {
      tab: 'overview',
      page: 2,
      unknownFilter: ['server-defined', 'future-key'],
    }

    const breadcrumbLink = createBreadcrumbParentLink('/studies/study%2Fone', search)
    const shellLink = createShellSearchPreservingLink('/notifications', search)

    expect(breadcrumbLink.to).toBe('/studies/study%2Fone')
    expect(shellLink.to).toBe('/notifications')
    expect(breadcrumbLink.search({ ignored: 'value' })).toEqual(search)
    expect(shellLink.search({ ignored: 'value' })).toEqual(search)
    expect(breadcrumbLink.search({})).not.toBe(search)
    expect(shellLink.search({})).not.toBe(search)
  })

  it('classifies shell-only actions without implying route or context changes', () => {
    expect(classifyShellAction('sidebar-toggle')).toBe('presentation-only')
    expect(classifyShellAction({ type: 'theme-change' })).toBe('presentation-only')
    expect(isPresentationOnlyAction('mobile-drawer')).toBe(true)
    expect(isPresentationOnlyAction('breadcrumb-navigation')).toBe(false)
    expect(classifyShellAction('breadcrumb-navigation')).toBe('route-navigation')
    expect(classifyShellAction('study-context-change')).toBe('context-selection')
  })

  it('keeps direct access-denied routes as route context without changing their path', () => {
    const search = { reason: 'missing-permission', unknown: 'preserve-me' }
    const context = getRouteContext({ pathname: '/access-denied', search })

    expect(context.pathname).toBe('/access-denied')
    expect(context.breadcrumbs).toEqual([{ label: 'Access Denied', current: true }])
    expect(context.search).toEqual(search)
  })

  it('keeps the root route and route context search state explicit', () => {
    const context = getRouteContext({ pathname: '/', search: { view: 'summary' } })

    expect(context.pathname).toBe('/')
    expect(context.breadcrumbs).toEqual([{ label: 'Dashboard', current: true }])
    expect(context.search).toEqual({ view: 'summary' })
  })

  it('handles site, subject, and form identifiers using route hierarchy labels', () => {
    const breadcrumbs = getRouteBreadcrumbs({
      pathname: '/sites/site%20one/ctms/activation',
      search: {},
    })

    expect(breadcrumbs.map((item) => item.label)).toEqual([
      'Sites',
      'Site site one',
      'CTMS',
      'Site activation',
    ])
  })
})
