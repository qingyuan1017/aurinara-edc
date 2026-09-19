import { useQuery } from '@tanstack/react-query'
import { ctmsApi, ctmsKeys, type CTMSCapabilityManifest } from './api'

export type Module = 'EDC' | 'CTMS'
export type OwnershipState = 'authoritative' | 'projected' | 'coordinated' | 'archived'
export type CTMSPhase = 0 | 1 | 2 | 3
export type CTMSCapabilityStatus = 'ready' | 'disabled' | 'unavailable'

export type CTMSEnvironmentMetadata = NonNullable<CTMSCapabilityManifest['environment']>
export type CTMSPlatformCapabilities = NonNullable<CTMSCapabilityManifest['platform_capabilities']>
export type CTMSPlatformCapability = keyof CTMSPlatformCapabilities

export type { CTMSCapabilityManifest }

/** Server capability codes. These are metadata identifiers, not permissions. */
export const CTMS_CAPABILITY_CODES = {
  canonicalStudyReferences: 'canonical_study_references',
  canonicalSiteReferences: 'canonical_site_references',
  operationalStudies: 'operational_studies',
  operationalSites: 'operational_sites',
  enrollmentPlanning: 'enrollment_planning',
  operationalMilestones: 'operational_milestones',
  ctmsRoles: 'ctms_roles',
  scopedAuthorization: 'scoped_authorization',
  sharedAudit: 'shared_audit',
  operationalDashboards: 'operational_dashboards',
  monitoring: 'monitoring',
  operationalTasks: 'operational_tasks',
  operationalContacts: 'operational_contacts',
  operationalAttachments: 'operational_attachments',
  ctmsOperationalProjections: 'ctms_operational_projections',
  coordinationEvents: 'coordination_events',
  notifications: 'notifications',
  approvedQuerySummaries: 'approved_query_summaries',
  dataQualitySignals: 'data_quality_signals',
  coordinationRetries: 'coordination_retries',
  failedEvents: 'failed_events',
  coordinationConflicts: 'coordination_conflicts',
  advancedOperationalReports: 'advanced_operational_reports',
  operationalExports: 'operational_exports',
  qualificationEvidence: 'qualification_evidence',
} as const

export type CTMSCapabilityCode = (typeof CTMS_CAPABILITY_CODES)[keyof typeof CTMS_CAPABILITY_CODES]

/**
 * Cumulative phase metadata mirrors the server manifest. It is a convenience
 * lookup only; the API remains authoritative for capability delivery.
 */
export const CTMS_PHASE_CAPABILITIES: Readonly<Record<CTMSPhase, readonly CTMSCapabilityCode[]>> = {
  0: [],
  1: [
    CTMS_CAPABILITY_CODES.canonicalStudyReferences,
    CTMS_CAPABILITY_CODES.canonicalSiteReferences,
    CTMS_CAPABILITY_CODES.operationalStudies,
    CTMS_CAPABILITY_CODES.operationalSites,
    CTMS_CAPABILITY_CODES.enrollmentPlanning,
    CTMS_CAPABILITY_CODES.operationalMilestones,
    CTMS_CAPABILITY_CODES.ctmsRoles,
    CTMS_CAPABILITY_CODES.scopedAuthorization,
    CTMS_CAPABILITY_CODES.sharedAudit,
    CTMS_CAPABILITY_CODES.operationalDashboards,
  ],
  2: [
    CTMS_CAPABILITY_CODES.canonicalStudyReferences,
    CTMS_CAPABILITY_CODES.canonicalSiteReferences,
    CTMS_CAPABILITY_CODES.operationalStudies,
    CTMS_CAPABILITY_CODES.operationalSites,
    CTMS_CAPABILITY_CODES.enrollmentPlanning,
    CTMS_CAPABILITY_CODES.operationalMilestones,
    CTMS_CAPABILITY_CODES.ctmsRoles,
    CTMS_CAPABILITY_CODES.scopedAuthorization,
    CTMS_CAPABILITY_CODES.sharedAudit,
    CTMS_CAPABILITY_CODES.operationalDashboards,
    CTMS_CAPABILITY_CODES.monitoring,
    CTMS_CAPABILITY_CODES.operationalTasks,
    CTMS_CAPABILITY_CODES.operationalContacts,
    CTMS_CAPABILITY_CODES.operationalAttachments,
    CTMS_CAPABILITY_CODES.ctmsOperationalProjections,
    CTMS_CAPABILITY_CODES.coordinationEvents,
    CTMS_CAPABILITY_CODES.notifications,
  ],
  3: [
    CTMS_CAPABILITY_CODES.canonicalStudyReferences,
    CTMS_CAPABILITY_CODES.canonicalSiteReferences,
    CTMS_CAPABILITY_CODES.operationalStudies,
    CTMS_CAPABILITY_CODES.operationalSites,
    CTMS_CAPABILITY_CODES.enrollmentPlanning,
    CTMS_CAPABILITY_CODES.operationalMilestones,
    CTMS_CAPABILITY_CODES.ctmsRoles,
    CTMS_CAPABILITY_CODES.scopedAuthorization,
    CTMS_CAPABILITY_CODES.sharedAudit,
    CTMS_CAPABILITY_CODES.operationalDashboards,
    CTMS_CAPABILITY_CODES.monitoring,
    CTMS_CAPABILITY_CODES.operationalTasks,
    CTMS_CAPABILITY_CODES.operationalContacts,
    CTMS_CAPABILITY_CODES.operationalAttachments,
    CTMS_CAPABILITY_CODES.ctmsOperationalProjections,
    CTMS_CAPABILITY_CODES.coordinationEvents,
    CTMS_CAPABILITY_CODES.notifications,
    CTMS_CAPABILITY_CODES.approvedQuerySummaries,
    CTMS_CAPABILITY_CODES.dataQualitySignals,
    CTMS_CAPABILITY_CODES.coordinationRetries,
    CTMS_CAPABILITY_CODES.failedEvents,
    CTMS_CAPABILITY_CODES.coordinationConflicts,
    CTMS_CAPABILITY_CODES.advancedOperationalReports,
    CTMS_CAPABILITY_CODES.operationalExports,
    CTMS_CAPABILITY_CODES.qualificationEvidence,
  ],
}

export interface CTMSPhaseMetadata {
  readonly phase: CTMSPhase
  readonly capabilities: readonly CTMSCapabilityCode[]
}

export const CTMS_PHASE_METADATA: Readonly<Record<CTMSPhase, CTMSPhaseMetadata>> = {
  0: { phase: 0, capabilities: CTMS_PHASE_CAPABILITIES[0] },
  1: { phase: 1, capabilities: CTMS_PHASE_CAPABILITIES[1] },
  2: { phase: 2, capabilities: CTMS_PHASE_CAPABILITIES[2] },
  3: { phase: 3, capabilities: CTMS_PHASE_CAPABILITIES[3] },
}

export interface CTMSCapabilityState {
  readonly status: CTMSCapabilityStatus
  readonly manifest: CTMSCapabilityManifest
  readonly environment: CTMSEnvironmentMetadata
  readonly platformCapabilities: CTMSPlatformCapabilities
  readonly error?: unknown
}

/** One descriptor map is the source for CTMS route and action affordances. */
export interface CTMSActionRouteDescriptor {
  readonly kind: 'route' | 'action'
  readonly route: string
  readonly phase: Exclude<CTMSPhase, 0>
  readonly capability: CTMSCapabilityCode
  readonly permission?: string
  readonly platformCapability?: CTMSPlatformCapability
  readonly owner: 'CTMS'
  readonly clinicalMutation: false
}

export const CTMS_ACTION_ROUTE_MAP = {
  studyWorkspace: {
    kind: 'route', route: '/studies/$studyId/ctms', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalDashboards, owner: 'CTMS', clinicalMutation: false,
  },
  studyProfile: {
    kind: 'route', route: '/studies/$studyId/ctms/profile', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalStudies, owner: 'CTMS', clinicalMutation: false,
  },
  studyPlans: {
    kind: 'route', route: '/studies/$studyId/ctms/plans', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalStudies, owner: 'CTMS', clinicalMutation: false,
  },
  enrollment: {
    kind: 'route', route: '/studies/$studyId/ctms/enrollment', phase: 1, capability: CTMS_CAPABILITY_CODES.enrollmentPlanning, owner: 'CTMS', clinicalMutation: false,
  },
  milestones: {
    kind: 'route', route: '/studies/$studyId/ctms/milestones', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalMilestones, owner: 'CTMS', clinicalMutation: false,
  },
  siteActivation: {
    kind: 'route', route: '/sites/$siteId/ctms/activation', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalSites, owner: 'CTMS', clinicalMutation: false,
  },
  monitoringPlans: {
    kind: 'route', route: '/studies/$studyId/ctms/monitoring-plans', phase: 2, capability: CTMS_CAPABILITY_CODES.monitoring, permission: 'ctms.monitoring_activity_management', owner: 'CTMS', clinicalMutation: false,
  },
  monitoringActivities: {
    kind: 'route', route: '/studies/$studyId/ctms/monitoring-activities', phase: 2, capability: CTMS_CAPABILITY_CODES.monitoring, permission: 'ctms.monitoring_activity_management', owner: 'CTMS', clinicalMutation: false,
  },
  tasks: {
    kind: 'route', route: '/studies/$studyId/ctms/tasks', phase: 2, capability: CTMS_CAPABILITY_CODES.operationalTasks, permission: 'ctms.operational_study_management', owner: 'CTMS', clinicalMutation: false,
  },
  contacts: {
    kind: 'route', route: '/studies/$studyId/ctms/contacts', phase: 2, capability: CTMS_CAPABILITY_CODES.operationalContacts, permission: 'ctms.operational_study_management', owner: 'CTMS', clinicalMutation: false,
  },
  projections: {
    kind: 'route', route: '/studies/$studyId/ctms/projections', phase: 2, capability: CTMS_CAPABILITY_CODES.ctmsOperationalProjections, owner: 'CTMS', clinicalMutation: false,
  },
  reports: {
    kind: 'route', route: '/studies/$studyId/ctms/reports/$type', phase: 3, capability: CTMS_CAPABILITY_CODES.advancedOperationalReports, owner: 'CTMS', clinicalMutation: false,
  },
  exports: {
    kind: 'route', route: '/studies/$studyId/ctms/exports', phase: 3, capability: CTMS_CAPABILITY_CODES.operationalExports, permission: 'data.export', owner: 'CTMS', clinicalMutation: false,
  },
  health: {
    kind: 'route', route: '/studies/$studyId/ctms/health', phase: 3, capability: CTMS_CAPABILITY_CODES.qualificationEvidence, platformCapability: 'health_observability', owner: 'CTMS', clinicalMutation: false,
  },
  failedEvents: {
    kind: 'route', route: '/studies/$studyId/ctms/coordination/failed-events', phase: 3, capability: CTMS_CAPABILITY_CODES.failedEvents, permission: 'ctms.coordination_replay', owner: 'CTMS', clinicalMutation: false,
  },
  conflicts: {
    kind: 'route', route: '/studies/$studyId/ctms/coordination/conflicts', phase: 3, capability: CTMS_CAPABILITY_CODES.coordinationConflicts, permission: 'ctms.conflict_management', owner: 'CTMS', clinicalMutation: false,
  },
  createStudyProfile: {
    kind: 'action', route: '/studies/$studyId/ctms/profile', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalStudies, permission: 'ctms.operational_study_management', owner: 'CTMS', clinicalMutation: false,
  },
  manageSiteActivation: {
    kind: 'action', route: '/sites/$siteId/ctms/activation', phase: 1, capability: CTMS_CAPABILITY_CODES.operationalSites, permission: 'ctms.operational_site_management', owner: 'CTMS', clinicalMutation: false,
  },
  manageEnrollment: {
    kind: 'action', route: '/studies/$studyId/ctms/enrollment', phase: 1, capability: CTMS_CAPABILITY_CODES.enrollmentPlanning, permission: 'ctms.enrollment_management', owner: 'CTMS', clinicalMutation: false,
  },
  replayFailedEvent: {
    kind: 'action', route: '/studies/$studyId/ctms/coordination/failed-events', phase: 3, capability: CTMS_CAPABILITY_CODES.coordinationRetries, permission: 'ctms.coordination_replay', owner: 'CTMS', clinicalMutation: false,
  },
  resolveConflict: {
    kind: 'action', route: '/studies/$studyId/ctms/coordination/conflicts', phase: 3, capability: CTMS_CAPABILITY_CODES.coordinationConflicts, permission: 'ctms.conflict_management', owner: 'CTMS', clinicalMutation: false,
  },
} as const satisfies Record<string, CTMSActionRouteDescriptor>

export type CTMSActionRouteId = keyof typeof CTMS_ACTION_ROUTE_MAP

export const CTMS_DISABLED_MANIFEST: CTMSCapabilityManifest = {
  module: 'CTMS',
  enabled: false,
  phase: 0,
  capabilities: [],
}

const emptyEnvironment: CTMSEnvironmentMetadata = {}
const emptyPlatformCapabilities: CTMSPlatformCapabilities = {}

export function normalizeCTMSCapabilities(manifest: CTMSCapabilityManifest): CTMSCapabilityState {
  const disabled = !manifest.enabled || manifest.phase === 0
  return {
    status: disabled ? 'disabled' : 'ready',
    manifest: disabled ? CTMS_DISABLED_MANIFEST : manifest,
    environment: manifest.environment ?? emptyEnvironment,
    platformCapabilities: manifest.platform_capabilities ?? emptyPlatformCapabilities,
  }
}

export function unavailableCTMSCapabilities(error?: unknown): CTMSCapabilityState {
  return {
    status: 'unavailable',
    manifest: CTMS_DISABLED_MANIFEST,
    environment: emptyEnvironment,
    platformCapabilities: emptyPlatformCapabilities,
    error,
  }
}

export function isCTMSActionAvailable(
  state: CTMSCapabilityState | CTMSCapabilityManifest,
  descriptor: CTMSActionRouteDescriptor,
  permissions?: readonly string[],
): boolean {
  const normalized = 'status' in state ? state : normalizeCTMSCapabilities(state)
  if (normalized.status !== 'ready') return false
  if (normalized.manifest.phase < descriptor.phase) return false
  if (!normalized.manifest.capabilities.includes(descriptor.capability)) return false
  if (descriptor.platformCapability && normalized.platformCapabilities[descriptor.platformCapability] !== true) return false
  if (descriptor.permission && !permissions?.includes(descriptor.permission)) return false
  return descriptor.owner === 'CTMS' && descriptor.clinicalMutation === false
}

export async function fetchCTMSCapabilities(): Promise<CTMSCapabilityManifest> {
  return ctmsApi.capabilities()
}

/**
 * Normalized capability state. A failed request is unavailable, never an
 * authorization success. The disabled fallback keeps EDC navigation intact.
 */
export function useCTMSCapabilityState(): CTMSCapabilityState {
  const query = useQuery({
    queryKey: ctmsKeys.capabilities(),
    queryFn: fetchCTMSCapabilities,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  if (query.isError) return unavailableCTMSCapabilities(query.error)
  return normalizeCTMSCapabilities(query.data ?? CTMS_DISABLED_MANIFEST)
}

/** Backwards-compatible manifest hook used by AppShell and workspace routes. */
export function useCTMSCapabilities(): CTMSCapabilityManifest {
  return useCTMSCapabilityState().manifest
}
