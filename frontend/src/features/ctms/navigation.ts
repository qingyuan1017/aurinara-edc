import {
  CTMS_ACTION_ROUTE_MAP,
  isCTMSActionAvailable,
  type CTMSActionRouteId,
  type CTMSCapabilityState,
} from './capabilities'
import { PERMISSIONS } from '@/lib/permissions'

export interface CTMSNavigationItem {
  readonly id: CTMSActionRouteId
  readonly label: string
  readonly to: string
}

export interface CTMSNavigationSection {
  readonly id: 'study-operations' | 'site-operations' | 'reporting-exports' | 'coordination-health'
  readonly label: string
  readonly items: readonly CTMSNavigationItem[]
}

interface CTMSNavigationScope {
  readonly studyId?: string | null
  readonly siteId?: string | null
}

type NavigationDefinition = {
  readonly id: CTMSActionRouteId
  readonly label: string
  readonly scope: 'study' | 'site'
  readonly path?: string
}

type NavigationSectionDefinition = Omit<CTMSNavigationSection, 'items'> & {
  readonly items: readonly NavigationDefinition[]
}

const SECTION_DEFINITIONS: readonly NavigationSectionDefinition[] = [
  {
    id: 'study-operations',
    label: 'Study operations',
    items: [
      { id: 'studyWorkspace', label: 'Overview', scope: 'study', path: '' },
      { id: 'studyProfile', label: 'Operational profile', scope: 'study', path: '/profile' },
      { id: 'studyPlans', label: 'Plans', scope: 'study', path: '/plans' },
      { id: 'enrollment', label: 'Enrollment', scope: 'study', path: '/enrollment' },
      { id: 'milestones', label: 'Milestones', scope: 'study', path: '/milestones' },
      { id: 'monitoringPlans', label: 'Monitoring plans', scope: 'study', path: '/monitoring-plans' },
      { id: 'monitoringActivities', label: 'Monitoring activities', scope: 'study', path: '/monitoring-activities' },
      { id: 'tasks', label: 'Tasks', scope: 'study', path: '/tasks' },
      { id: 'contacts', label: 'Contacts', scope: 'study', path: '/contacts' },
      { id: 'projections', label: 'Projections', scope: 'study', path: '/projections' },
    ],
  },
  {
    id: 'site-operations',
    label: 'Site operations',
    items: [
      { id: 'siteActivation', label: 'Site activation', scope: 'site' },
    ],
  },
  {
    id: 'reporting-exports',
    label: 'Reporting & exports',
    items: [
      { id: 'reports', label: 'Reports & dashboards', scope: 'study', path: '/reports/dashboard' },
      { id: 'exports', label: 'Exports', scope: 'study', path: '/exports' },
    ],
  },
  {
    id: 'coordination-health',
    label: 'Coordination & health',
    items: [
      { id: 'failedEvents', label: 'Failed events', scope: 'study', path: '/coordination/failed-events' },
      { id: 'conflicts', label: 'Conflicts', scope: 'study', path: '/coordination/conflicts' },
      { id: 'health', label: 'Health', scope: 'study', path: '/health' },
    ],
  },
]

function scopedPath(definition: NavigationDefinition, scope: CTMSNavigationScope): string | null {
  if (definition.scope === 'site') {
    return scope.siteId ? `/sites/${encodeURIComponent(scope.siteId)}/ctms/activation` : null
  }

  if (definition.id === 'studyWorkspace' && !scope.studyId) return '/ctms'
  if (!scope.studyId) return null
  return `/studies/${encodeURIComponent(scope.studyId)}/ctms${definition.path ?? ''}`
}

/**
 * Resolves CTMS navigation as a convenience affordance only. The API remains
 * authoritative for object scope and every direct route remains available to
 * render its server-authorized state.
 */
export function resolveCTMSNavigation(
  state: CTMSCapabilityState,
  permissions: readonly string[],
  scope: CTMSNavigationScope = {},
): readonly CTMSNavigationSection[] {
  if (state.status !== 'ready') return []
  if (!permissions.includes(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)) return []

  return SECTION_DEFINITIONS.map((section) => ({
    ...section,
    items: section.items.flatMap((definition) => {
      const path = scopedPath(definition, scope)
      if (!path || !isCTMSActionAvailable(state, CTMS_ACTION_ROUTE_MAP[definition.id], permissions)) return []
      return [{ id: definition.id, label: definition.label, to: path }]
    }),
  })).filter((section) => section.items.length > 0)
}
