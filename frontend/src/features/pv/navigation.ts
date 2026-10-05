import {
  PV_ACTION_ROUTE_MAP,
  isPVActionAvailable,
  type PVActionRouteId,
  type PVCapabilityState,
} from './capabilities'
import { PERMISSIONS } from '@/lib/permissions'

export interface PVNavigationItem {
  readonly id: PVActionRouteId
  readonly label: string
  readonly to: string
}

export interface PVNavigationSection {
  readonly id: 'case-management' | 'reporting' | 'oversight'
  readonly label: string
  readonly items: readonly PVNavigationItem[]
}

interface PVNavigationScope {
  readonly studyId?: string | null
  readonly siteId?: string | null
  readonly caseId?: string | null
}

type NavigationDefinition = {
  readonly id: PVActionRouteId
  readonly label: string
  readonly scope: 'study' | 'site' | 'case'
  readonly path?: string
}

type NavigationSectionDefinition = Omit<PVNavigationSection, 'items'> & {
  readonly items: readonly NavigationDefinition[]
}

const SECTION_DEFINITIONS: readonly NavigationSectionDefinition[] = [
  {
    id: 'case-management',
    label: 'Case management',
    items: [
      { id: 'dashboard', label: 'Dashboard', scope: 'study', path: '/dashboard' },
      { id: 'cases', label: 'Cases', scope: 'study', path: '/cases' },
    ],
  },
  {
    id: 'reporting',
    label: 'Reporting',
    items: [
      { id: 'reconciliation', label: 'Reconciliation', scope: 'study', path: '/reconciliation' },
      { id: 'exports', label: 'Exports', scope: 'study', path: '/exports' },
    ],
  },
  {
    id: 'oversight',
    label: 'Oversight',
    items: [
      { id: 'audit', label: 'Audit', scope: 'study', path: '/audit' },
      { id: 'siteDashboard', label: 'Site dashboard', scope: 'site', path: '/dashboard' },
    ],
  },
]

function scopedPath(definition: NavigationDefinition, scope: PVNavigationScope): string | null {
  if (definition.scope === 'site') {
    return scope.siteId ? `/sites/${encodeURIComponent(scope.siteId)}/pv${definition.path ?? ''}` : null
  }
  if (!scope.studyId) return null
  return `/studies/${encodeURIComponent(scope.studyId)}/pv${definition.path ?? ''}`
}

/**
 * Resolves PV navigation as a convenience affordance only. The API remains
 * authoritative for object scope, and every direct route stays available to
 * render its server-authorized state or an access-denied view. When PV is
 * disabled, empty, or unavailable this returns an empty list so EDC/CTMS
 * navigation is never altered (Requirements 19.6, 23.10).
 */
export function resolvePVNavigation(
  state: PVCapabilityState,
  permissions: readonly string[],
  scope: PVNavigationScope = {},
): readonly PVNavigationSection[] {
  if (state.status !== 'ready') return []
  if (!permissions.includes(PERMISSIONS.PV_SAFETY_CASE_READ)) return []

  return SECTION_DEFINITIONS.map((section) => ({
    ...section,
    items: section.items.flatMap((definition) => {
      const path = scopedPath(definition, scope)
      if (!path || !isPVActionAvailable(state, PV_ACTION_ROUTE_MAP[definition.id], permissions)) {
        return []
      }
      return [{ id: definition.id, label: definition.label, to: path }]
    }),
  })).filter((section) => section.items.length > 0)
}
