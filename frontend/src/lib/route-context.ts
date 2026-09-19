import { useLocation } from '@tanstack/react-router'
import type { SearchState, SearchPreserver } from './navigation-model'

export interface RouteLocation {
  readonly pathname: string
  readonly search: SearchState
  readonly hash?: string
}

export interface BreadcrumbItem {
  readonly label: string
  readonly to?: string
  readonly search?: SearchPreserver
  readonly current?: boolean
}

export interface SearchPreservingLink {
  readonly to: string
  readonly search: SearchPreserver
}

export type ShellLink = SearchPreservingLink

/**
 * Shell interactions kept separate from route and data state. Navigation
 * actions are included so callers can assert that their search adapter
 * preserves route state even when the pathname changes.
 */
export type ShellActionType =
  | 'sidebar-navigation'
  | 'mobile-navigation'
  | 'breadcrumb-navigation'
  | 'notification-navigation'
  | 'sidebar-toggle'
  | 'mobile-drawer'
  | 'study-selector-open'
  | 'site-selector-open'
  | 'study-context-change'
  | 'theme-change'
  | 'user-menu'

export type ShellAction = ShellActionType | { readonly type: ShellActionType }
export type ShellActionClassification = 'presentation-only' | 'route-navigation' | 'context-selection'

const PRESENTATION_ONLY_ACTIONS: ReadonlySet<ShellActionType> = new Set([
  'sidebar-toggle',
  'mobile-drawer',
  'study-selector-open',
  'site-selector-open',
  'theme-change',
  'user-menu',
])

const ROUTE_NAVIGATION_ACTIONS: ReadonlySet<ShellActionType> = new Set([
  'sidebar-navigation',
  'mobile-navigation',
  'breadcrumb-navigation',
  'notification-navigation',
])

function shellActionType(action: ShellAction): ShellActionType {
  return typeof action === 'string' ? action : action.type
}

/**
 * Classifies a shell action without performing navigation or state changes.
 * This is a presentation contract; it does not grant permissions or alter
 * route, query, authentication, or Study_Context state.
 */
export function classifyShellAction(action: ShellAction): ShellActionClassification {
  const type = shellActionType(action)
  if (PRESENTATION_ONLY_ACTIONS.has(type)) return 'presentation-only'
  if (ROUTE_NAVIGATION_ACTIONS.has(type)) return 'route-navigation'
  return 'context-selection'
}

/** Returns true when an action must not change route or query state. */
export function isPresentationOnlyAction(action: ShellAction): boolean {
  return classifyShellAction(action) === 'presentation-only'
}

export interface RouteContextViewModel {
  readonly pathname: string
  readonly breadcrumbs: readonly BreadcrumbItem[]
  readonly search: SearchState
}

const STATIC_LABELS: Readonly<Record<string, string>> = {
  '': 'Dashboard',
  studies: 'Studies',
  sites: 'Sites',
  subjects: 'Subjects',
  forms: 'Forms',
  queries: 'Queries',
  'data-cleaning': 'Data Cleaning',
  sdv: 'SDV Worklist',
  review: 'Clinical Review',
  'edit-checks': 'Edit Checks',
  ai: 'AI Assistant',
  notifications: 'Notifications',
  exports: 'Exports',
  admin: 'Admin',
  audit: 'Audit Trail',
  dashboard: 'Dashboard',
  casebook: 'Casebook',
  visits: 'Visits',
  signatures: 'Signatures',
  versions: 'Versions',
  ctms: 'CTMS',
  profile: 'Operational profile',
  plans: 'Plans',
  enrollment: 'Enrollment',
  milestones: 'Milestones',
  'monitoring-plans': 'Monitoring plans',
  'monitoring-activities': 'Monitoring activities',
  tasks: 'Tasks',
  contacts: 'Contacts',
  projections: 'Projections',
  reports: 'Reports & dashboards',
  'coordination': 'Coordination',
  'failed-events': 'Failed events',
  conflicts: 'Conflicts',
  health: 'Health',
  activation: 'Site activation',
}

/** Encode dynamic route identifiers without changing route path semantics. */
export function encodeRouteIdentifier(identifier: string): string {
  return encodeURIComponent(identifier)
}

/** Decode a route identifier for display while tolerating malformed external URLs. */
export function decodeRouteIdentifier(identifier: string): string {
  try {
    return decodeURIComponent(identifier)
  } catch {
    return identifier
  }
}

/** Captures the current search values for a breadcrumb parent link. */
export function preserveSearch(search: SearchState): SearchPreserver {
  const snapshot = { ...search }
  return () => ({ ...snapshot })
}

/** Builds a breadcrumb parent link while retaining every search key/value. */
export function createBreadcrumbParentLink(
  to: string,
  search: SearchState,
): SearchPreservingLink {
  return { to, search: preserveSearch(search) }
}

/** Builds a shell navigation link without changing the current search state. */
export function createShellSearchPreservingLink(
  to: string,
  search: SearchState,
): SearchPreservingLink {
  return { to, search: preserveSearch(search) }
}

/** Alias following the parent-link naming convention. */
export const createSearchPreservingShellLink = createShellSearchPreservingLink
/** Concise alias for shell consumers that need a search-preserving link. */
export const createShellLink = createShellSearchPreservingLink
/** Concise alias for breadcrumb consumers that need a parent link. */
export const createBreadcrumbLink = createBreadcrumbParentLink

/** Builds a TanStack Router link that preserves the current route search state. */
export function createSearchPreservingParentLink(
  to: string,
  search: SearchState,
): SearchPreservingLink {
  return createBreadcrumbParentLink(to, search)
}

function humanizeSegment(segment: string): string {
  return segment
    .split('-')
    .map((word) => word ? `${word[0].toUpperCase()}${word.slice(1)}` : word)
    .join(' ')
}

function segmentLabel(segments: readonly string[], index: number): string {
  const segment = segments[index]
  const decoded = decodeRouteIdentifier(segment)
  const parent = segments[index - 1]
  const grandparent = segments[index - 2]

  if (parent === 'studies') return `Study ${decoded}`
  if (parent === 'sites') return `Site ${decoded}`
  if (parent === 'subjects') return `Subject ${decoded}`
  if (parent === 'queries') return `Query ${decoded}`
  if (grandparent === 'reports' || parent === 'reports') return `Report ${decoded}`
  if (parent === 'forms') return `Form ${decoded}`
  if (STATIC_LABELS[decoded]) return STATIC_LABELS[decoded]
  return humanizeSegment(decoded)
}

/**
 * Derives readable, encoded-path breadcrumbs from TanStack Router location data.
 * Parent links retain the current search keys; the current item is not a link.
 */
export function getRouteBreadcrumbs(location: Pick<RouteLocation, 'pathname' | 'search'>): readonly BreadcrumbItem[] {
  const encodedSegments = location.pathname.split('/').filter(Boolean)

  if (encodedSegments.length === 0) {
    return [{ label: STATIC_LABELS[''], current: true }]
  }

  return encodedSegments.map((_, index) => {
    const to = `/${encodedSegments.slice(0, index + 1).join('/')}`
    const current = index === encodedSegments.length - 1
    if (current) return { label: segmentLabel(encodedSegments, index), current: true }

    const parent = createBreadcrumbParentLink(to, location.search)
    return { label: segmentLabel(encodedSegments, index), ...parent }
  })
}

/** Derives the current route context without mutating route, query, or study state. */
export function getRouteContext(location: RouteLocation): RouteContextViewModel {
  return {
    pathname: location.pathname,
    breadcrumbs: getRouteBreadcrumbs(location),
    search: location.search,
  }
}

/** Hook adapter for shell components; all behavior remains in the pure helpers above. */
export function useRouteContext(): RouteContextViewModel {
  const location = useLocation()
  return getRouteContext({
    pathname: location.pathname,
    search: location.search as SearchState,
    hash: location.hash,
  })
}

export const buildBreadcrumbs = getRouteBreadcrumbs
export const createParentLink = createSearchPreservingParentLink
