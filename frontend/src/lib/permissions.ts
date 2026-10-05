import { useAuthStore } from './auth'

/**
 * Permission codes used by the Clinical EDC system.
 * These mirror the server-side permission codes exactly.
 *
 * Frontend permission checks are convenience only —
 * the server is authoritative (Requirement 2.6).
 */
export const PERMISSIONS = {
  // Users & Roles
  USER_LIST: 'user.list',
  USER_CREATE: 'user.create',
  USER_UPDATE: 'user.update',
  USER_DEACTIVATE: 'user.deactivate',
  USER_ASSIGN: 'user.assign',
  ROLE_LIST: 'role.list',
  ROLE_CREATE: 'role.create',
  ROLE_UPDATE: 'role.update',

  // Studies
  STUDY_CREATE: 'study.create',
  STUDY_CONFIGURE: 'study.configure',
  STUDY_READ: 'study.read',

  // Versions
  VERSION_PUBLISH: 'version.publish',

  // Sites
  SITE_MANAGE: 'site.manage',
  SITE_READ: 'site.read',

  // Subjects
  SUBJECT_CREATE: 'subject.create',
  SUBJECT_READ: 'subject.read',
  SUBJECT_UPDATE: 'subject.update',

  // Forms & Data
  FORM_CONFIGURE: 'form.configure',
  FORM_READ: 'form.read',
  FORM_ENTER: 'form.enter',
  FORM_SUBMIT: 'form.submit',

  // Queries
  QUERY_CREATE: 'query.create',
  QUERY_RESPOND: 'query.respond',
  QUERY_CLOSE: 'query.close',
  QUERY_REOPEN: 'query.reopen',
  QUERY_CANCEL: 'query.cancel',

  // Edit Checks
  EDITCHECK_CONFIGURE: 'editcheck.configure',

  // SDV & Review
  SDV_MANAGE: 'sdv.manage',
  REVIEW_MANAGE: 'review.manage',

  // Lock
  LOCK_MANAGE: 'lock.manage',

  // Signatures
  SIGNATURE_SIGN: 'signature.sign',

  // Audit
  AUDIT_READ: 'audit.read',

  // Export
  DATA_EXPORT: 'data.export',

  // Files
  FILE_UPLOAD: 'file.upload',

  // CTMS operational data and remediation (must match server permission codes)
  CTMS_OPERATIONAL_DATA_READ: 'ctms.operational_data_read',
  CTMS_OPERATIONAL_STUDY_MANAGEMENT: 'ctms.operational_study_management',
  CTMS_OPERATIONAL_SITE_MANAGEMENT: 'ctms.operational_site_management',
  CTMS_MONITORING_ACTIVITY_MANAGEMENT: 'ctms.monitoring_activity_management',
  CTMS_ENROLLMENT_MANAGEMENT: 'ctms.enrollment_management',
  CTMS_CONFLICT_MANAGEMENT: 'ctms.conflict_management',
  CTMS_COORDINATION_REPLAY: 'ctms.coordination_replay',

  // PV/Safety permissions (must match server permission codes)
  PV_SAFETY_CASE_READ: 'safety_case.read',
  PV_SAFETY_CASE_ENTER: 'safety_case.enter',
  PV_SAFETY_CASE_LIFECYCLE: 'safety_case.lifecycle',
  PV_SAFETY_ASSESSMENT_RECORD: 'safety_assessment.record',
  PV_SAFETY_CODING_ASSIGN: 'safety_coding.assign',
  PV_SAFETY_NARRATIVE_WRITE: 'safety_narrative.write',
  PV_SAFETY_REPORT_MANAGE: 'safety_report.manage',
  PV_SAFETY_RECONCILIATION_RUN: 'safety_reconciliation.run',
  PV_SAFETY_EXPORT_CREATE: 'safety_export.create',
  PV_SAFETY_AUDIT_READ: 'safety_audit.read',
} as const

export type PermissionCode = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]

/**
 * Check whether the current user has a specific permission,
 * optionally scoped to a study and/or site.
 *
 * This is a convenience check — server enforces authoritatively.
 */
export function hasPermission(
  permission: PermissionCode,
  studyId?: string,
  siteId?: string,
): boolean {
  const user = useAuthStore.getState().user
  if (!user) return false

  // Frontend checks are convenience only; the server handles study/site scoping.
  void studyId
  void siteId
  return (user.permissions ?? []).includes(permission)
}

/**
 * React hook: returns true if the current user has the given permission.
 */
export function usePermission(
  permission: PermissionCode,
  studyId?: string,
  siteId?: string,
): boolean {
  const user = useAuthStore((state) => state.user)
  if (!user) return false
  // Flat check — scoping delegated to server
  void studyId
  void siteId
  return (user.permissions ?? []).includes(permission)
}

/**
 * Check multiple permissions — returns true if the user has ALL of them.
 */
export function hasAllPermissions(permissions: PermissionCode[]): boolean {
  return permissions.every((p) => hasPermission(p))
}

/**
 * Check multiple permissions — returns true if the user has ANY of them.
 */
export function hasAnyPermission(permissions: PermissionCode[]): boolean {
  return permissions.some((p) => hasPermission(p))
}
