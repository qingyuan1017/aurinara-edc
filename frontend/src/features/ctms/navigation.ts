import {
  CTMS_ACTION_ROUTE_MAP,
  isCTMSActionAvailable,
  type CTMSActionRouteId,
  type CTMSCapabilityState,
} from './capabilities'
import { CTMS_REPORT_DEFINITIONS } from './reportCatalog'
import { PERMISSIONS } from '@/lib/permissions'

export interface CTMSNavigationItem {
  readonly id: string
  readonly label: string
  readonly to: string
  readonly group?: string
}

export interface CTMSNavigationSection {
  readonly id: 'entity-management' | 'study-operations' | 'project-management' | 'financial-management' | 'rbm' | 'monitoring' | 'study-records' | 'site-operations' | 'reports' | 'reporting-exports' | 'coordination-health'
  readonly label: string
  readonly items: readonly CTMSNavigationItem[]
}

interface CTMSNavigationScope {
  readonly studyId?: string | null
  readonly siteId?: string | null
}

type NavigationDefinition = {
  readonly id: string
  readonly label: string
  readonly scope: 'global' | 'study' | 'site'
  readonly path?: string
  readonly group?: string
  readonly actionId?: CTMSActionRouteId
}

type NavigationSectionDefinition = Omit<CTMSNavigationSection, 'items'> & {
  readonly items: readonly NavigationDefinition[]
}

const SECTION_DEFINITIONS: readonly NavigationSectionDefinition[] = [
  {
    id: 'entity-management',
    label: 'Configuration',
    items: [
      { id: 'referenceData', label: 'Reference data', scope: 'global', path: '/ctms/references' },
      { id: 'entityManagement', label: 'Entity management', scope: 'global', path: '/ctms/entities' },
    ],
  },
  {
    id: 'study-operations',
    label: 'Study Operations',
    items: [
      { id: 'studyWorkspace', label: 'Overview', scope: 'study', path: '' },
      { id: 'studyProfile', label: 'Study Details', scope: 'study', path: '/details' },
    ],
  },
  {
    id: 'project-management',
    label: '',
    items: [
      { id: 'projectManagement', label: 'Project Management', scope: 'study', path: '/project-management', actionId: 'studyPlans' },
    ],
  },
  {
    id: 'financial-management',
    label: 'Financial Management',
    items: [
      { id: 'financialOverview', label: 'Study Financials', scope: 'study', path: '/financial-management', actionId: 'contracts' },
    ],
  },
  {
    id: 'rbm',
    label: 'RBM',
    items: [
      { id: 'ract', label: 'RACT', scope: 'study', path: '/rbm/ract' },
      { id: 'kri', label: 'KRI', scope: 'study', path: '/rbm/kri' },
    ],
  },
  {
    id: 'monitoring',
    label: 'Monitoring',
    items: [
      { id: 'monitoringOverview', label: 'Monitoring', scope: 'study', path: '/monitoring', actionId: 'monitoringPlans' },
    ],
  },
  {
    id: 'study-records',
    label: '',
    items: [
      { id: 'protocolDeviations', label: 'Protocol Deviation', scope: 'study', path: '/protocol-deviations' },
      { id: 'icf', label: 'ICF', scope: 'study', path: '/icf' },
      { id: 'trackLogs', label: 'Track Logs', scope: 'study', path: '/track-logs' },
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
    id: 'reports',
    label: 'Report',
    items: CTMS_REPORT_DEFINITIONS.map((report) => ({
      id: report.id,
      label: report.label,
      group: report.group,
      scope: 'study' as const,
      path: `/reports/${report.category}/${report.slug}`,
      actionId: 'reports' as const,
    })),
  },
  {
    id: 'reporting-exports',
    label: 'Exports',
    items: [{ id: 'exports', label: 'Exports', scope: 'study', path: '/exports' }],
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
  if (definition.scope === 'global') return definition.path ?? null
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
      const actionId = definition.actionId ?? definition.id as CTMSActionRouteId
      if (!path || !isCTMSActionAvailable(state, CTMS_ACTION_ROUTE_MAP[actionId], permissions)) return []
      return [{ id: definition.id, label: definition.label, to: path, ...(definition.group ? { group: definition.group } : {}) }]
    }),
  })).filter((section) => section.items.length > 0)
}
