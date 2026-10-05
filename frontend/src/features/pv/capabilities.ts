/**
 * PV/Safety capability metadata.
 *
 * This mirrors the server manifest as a convenience lookup only; the API
 * remains authoritative for capability delivery and authorization. A disabled
 * or unavailable PV module must never alter or hide EDC/CTMS navigation.
 */

import { useQuery } from '@tanstack/react-query'
import { pvApi, pvKeys, type PVCapabilityManifest, type PVPhase } from './api'

export type Module = 'EDC' | 'CTMS' | 'PV'
export type PVCapabilityStatus = 'ready' | 'disabled' | 'unavailable'

export type PVEnvironmentMetadata = NonNullable<PVCapabilityManifest['environment']>
export type PVPlatformCapabilities = NonNullable<PVCapabilityManifest['platform_capabilities']>
export type PVPlatformCapability = keyof PVPlatformCapabilities

export type { PVCapabilityManifest, PVPhase }

/** Server capability codes. These are metadata identifiers, not permissions. */
export const PV_CAPABILITY_CODES = {
  canonicalStudyReferences: 'canonical_study_references',
  canonicalSiteReferences: 'canonical_site_references',
  subjectReferences: 'subject_references',
  safetyCaseIntake: 'safety_case_intake',
  adverseEventCapture: 'adverse_event_capture',
  caseLifecycle: 'case_lifecycle',
  caseVersions: 'case_versions',
  seriousnessAssessment: 'seriousness_assessment',
  pvRoles: 'pv_roles',
  scopedAuthorization: 'scoped_authorization',
  sharedAudit: 'shared_audit',
  safetyExports: 'safety_exports',
  meddraCoding: 'meddra_coding',
  whodrugCoding: 'whodrug_coding',
  causalityAssessment: 'causality_assessment',
  expectednessAssessment: 'expectedness_assessment',
  severityGrade: 'severity_grade',
  caseNarratives: 'case_narratives',
  edcAeReconciliation: 'edc_ae_reconciliation',
  safetyOperationalProjection: 'safety_operational_projection',
  coordinationEvents: 'coordination_events',
  safetyNotifications: 'safety_notifications',
  safetyAttachments: 'safety_attachments',
  regulatoryReporting: 'regulatory_reporting',
  regulatoryClocks: 'regulatory_clocks',
  icsrE2b: 'icsr_e2b',
  advancedSafetyExports: 'advanced_safety_exports',
  safetyDashboards: 'safety_dashboards',
  qualificationEvidence: 'qualification_evidence',
} as const

export type PVCapabilityCode = (typeof PV_CAPABILITY_CODES)[keyof typeof PV_CAPABILITY_CODES]

/**
 * One descriptor map is the source for PV route and action affordances. It
 * mirrors the CTMS convention: a route/action is available only when the
 * module is ready, the phase is met, the required capability is present, any
 * required platform capability is enabled, and the user holds the permission.
 * The server remains authoritative — this only hides affordances the user
 * lacks (Requirement 19.6). No PV descriptor mutates EDC clinical or CTMS
 * operational state.
 */
export interface PVActionRouteDescriptor {
  readonly kind: 'route' | 'action'
  readonly route: string
  readonly phase: Exclude<PVPhase, 0>
  readonly capability: PVCapabilityCode
  readonly permission?: string
  readonly platformCapability?: PVPlatformCapability
  readonly owner: 'PV'
  readonly clinicalMutation: false
}

export const PV_ACTION_ROUTE_MAP = {
  workspace: {
    kind: 'route', route: '/studies/$studyId/pv/dashboard', phase: 1, capability: PV_CAPABILITY_CODES.safetyCaseIntake, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  dashboard: {
    kind: 'route', route: '/studies/$studyId/pv/dashboard', phase: 1, capability: PV_CAPABILITY_CODES.safetyDashboards, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  cases: {
    kind: 'route', route: '/studies/$studyId/pv/cases', phase: 1, capability: PV_CAPABILITY_CODES.safetyCaseIntake, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  assessments: {
    kind: 'route', route: '/studies/$studyId/pv/cases/$caseId/assessments', phase: 1, capability: PV_CAPABILITY_CODES.seriousnessAssessment, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  coding: {
    kind: 'route', route: '/studies/$studyId/pv/cases/$caseId/coding', phase: 3, capability: PV_CAPABILITY_CODES.meddraCoding, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  narratives: {
    kind: 'route', route: '/studies/$studyId/pv/cases/$caseId/narratives', phase: 3, capability: PV_CAPABILITY_CODES.caseNarratives, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  reports: {
    kind: 'route', route: '/studies/$studyId/pv/cases/$caseId/reports', phase: 3, capability: PV_CAPABILITY_CODES.regulatoryReporting, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  reconciliation: {
    kind: 'route', route: '/studies/$studyId/pv/reconciliation', phase: 3, capability: PV_CAPABILITY_CODES.edcAeReconciliation, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  exports: {
    kind: 'route', route: '/studies/$studyId/pv/exports', phase: 1, capability: PV_CAPABILITY_CODES.safetyExports, permission: 'safety_export.create', owner: 'PV', clinicalMutation: false,
  },
  audit: {
    kind: 'route', route: '/studies/$studyId/pv/audit', phase: 1, capability: PV_CAPABILITY_CODES.sharedAudit, permission: 'safety_audit.read', owner: 'PV', clinicalMutation: false,
  },
  siteDashboard: {
    kind: 'route', route: '/sites/$siteId/pv/dashboard', phase: 1, capability: PV_CAPABILITY_CODES.safetyDashboards, permission: 'safety_case.read', owner: 'PV', clinicalMutation: false,
  },
  // Mutation affordances gate write actions the user may lack (Requirement 19.6).
  enterCase: {
    kind: 'action', route: '/studies/$studyId/pv/cases', phase: 1, capability: PV_CAPABILITY_CODES.safetyCaseIntake, permission: 'safety_case.enter', owner: 'PV', clinicalMutation: false,
  },
  manageLifecycle: {
    kind: 'action', route: '/studies/$studyId/pv/cases/$caseId', phase: 1, capability: PV_CAPABILITY_CODES.caseLifecycle, permission: 'safety_case.lifecycle', owner: 'PV', clinicalMutation: false,
  },
  recordAssessment: {
    kind: 'action', route: '/studies/$studyId/pv/cases/$caseId/assessments', phase: 1, capability: PV_CAPABILITY_CODES.seriousnessAssessment, permission: 'safety_assessment.record', owner: 'PV', clinicalMutation: false,
  },
  assignCoding: {
    kind: 'action', route: '/studies/$studyId/pv/cases/$caseId/coding', phase: 3, capability: PV_CAPABILITY_CODES.meddraCoding, permission: 'safety_coding.assign', owner: 'PV', clinicalMutation: false,
  },
  writeNarrative: {
    kind: 'action', route: '/studies/$studyId/pv/cases/$caseId/narratives', phase: 3, capability: PV_CAPABILITY_CODES.caseNarratives, permission: 'safety_narrative.write', owner: 'PV', clinicalMutation: false,
  },
  manageReport: {
    kind: 'action', route: '/studies/$studyId/pv/cases/$caseId/reports', phase: 3, capability: PV_CAPABILITY_CODES.regulatoryReporting, permission: 'safety_report.manage', owner: 'PV', clinicalMutation: false,
  },
  runReconciliation: {
    kind: 'action', route: '/studies/$studyId/pv/reconciliation', phase: 3, capability: PV_CAPABILITY_CODES.edcAeReconciliation, permission: 'safety_reconciliation.run', owner: 'PV', clinicalMutation: false,
  },
  createExport: {
    kind: 'action', route: '/studies/$studyId/pv/exports', phase: 1, capability: PV_CAPABILITY_CODES.safetyExports, permission: 'safety_export.create', owner: 'PV', clinicalMutation: false,
  },
} as const satisfies Record<string, PVActionRouteDescriptor>

export type PVActionRouteId = keyof typeof PV_ACTION_ROUTE_MAP

export interface PVCapabilityState {
  readonly status: PVCapabilityStatus
  readonly manifest: PVCapabilityManifest
  readonly environment: PVEnvironmentMetadata
  readonly platformCapabilities: PVPlatformCapabilities
  readonly error?: unknown
}

export const PV_DISABLED_MANIFEST: PVCapabilityManifest = {
  module: 'PV',
  enabled: false,
  phase: 0,
  capabilities: [],
}

const emptyEnvironment: PVEnvironmentMetadata = {}
const emptyPlatformCapabilities: PVPlatformCapabilities = {}

export function normalizePVCapabilities(manifest: PVCapabilityManifest): PVCapabilityState {
  const disabled = !manifest.enabled || manifest.phase === 0
  return {
    status: disabled ? 'disabled' : 'ready',
    manifest: disabled ? PV_DISABLED_MANIFEST : manifest,
    environment: manifest.environment ?? emptyEnvironment,
    platformCapabilities: manifest.platform_capabilities ?? emptyPlatformCapabilities,
  }
}

export function unavailablePVCapabilities(error?: unknown): PVCapabilityState {
  return {
    status: 'unavailable',
    manifest: PV_DISABLED_MANIFEST,
    environment: emptyEnvironment,
    platformCapabilities: emptyPlatformCapabilities,
    error,
  }
}

/**
 * Whether a PV route or action affordance may be shown. This is a convenience
 * check only; the API enforces the same denial (Requirement 19.6). A disabled
 * or unavailable module resolves to false, which keeps PV affordances hidden
 * without touching EDC/CTMS navigation (Requirement 23.10).
 */
export function isPVActionAvailable(
  state: PVCapabilityState | PVCapabilityManifest,
  descriptor: PVActionRouteDescriptor,
  permissions?: readonly string[],
): boolean {
  const normalized = 'status' in state ? state : normalizePVCapabilities(state)
  if (normalized.status !== 'ready') return false
  if (normalized.manifest.phase < descriptor.phase) return false
  if (!normalized.manifest.capabilities.includes(descriptor.capability)) return false
  if (
    descriptor.platformCapability &&
    normalized.platformCapabilities[descriptor.platformCapability] !== true
  ) {
    return false
  }
  if (descriptor.permission && !permissions?.includes(descriptor.permission)) return false
  return descriptor.owner === 'PV' && descriptor.clinicalMutation === false
}

export async function fetchPVCapabilities(): Promise<PVCapabilityManifest> {
  return pvApi.capabilities()
}

/**
 * Normalized capability state. A failed request is unavailable, never an
 * authorization success. The disabled fallback keeps EDC/CTMS navigation intact.
 */
export function usePVCapabilityState(): PVCapabilityState {
  const query = useQuery({
    queryKey: pvKeys.capabilities(),
    queryFn: fetchPVCapabilities,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  if (query.isError) return unavailablePVCapabilities(query.error)
  return normalizePVCapabilities(query.data ?? PV_DISABLED_MANIFEST)
}

/** Manifest hook used by navigation and workspace routes. */
export function usePVCapabilities(): PVCapabilityManifest {
  return usePVCapabilityState().manifest
}
