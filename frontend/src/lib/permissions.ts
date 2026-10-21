import { useAuthStore, type UserRoleAssignment } from './auth'

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
  SUBJECT_DELETE: 'subject.delete',
  SUBJECT_READ: 'subject.read',
  SUBJECT_RESTORE: 'subject.restore',
  SUBJECT_TRANSFER: 'subject.transfer',
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

  // Designer module (design-time authoring; Designer_Role only).
  // Replace the study.configure/version.publish/form.configure/
  // editcheck.configure placeholders for authoring after the Designer/EDC
  // refactor. The operational codes above remain for the EDC surface.
  DESIGNER_STUDY_VERSION_READ: 'designer.study_version.read',
  DESIGNER_STUDY_VERSION_CREATE: 'designer.study_version.create',
  DESIGNER_STUDY_VERSION_AMEND: 'designer.study_version.amend',
  DESIGNER_VERSION_PUBLISH: 'designer.version.publish',
  DESIGNER_FORM_READ: 'designer.form.read',
  DESIGNER_FORM_CONFIGURE: 'designer.form.configure',
  DESIGNER_FIELD_CONFIGURE: 'designer.field.configure',
  DESIGNER_EDITCHECK_CONFIGURE: 'designer.editcheck.configure',
  DESIGNER_EDITCHECK_TEST: 'designer.editcheck.test',
  DESIGNER_CUSTOM_FUNCTION_AUTHOR: 'designer.custom_function.author',
  DESIGNER_CUSTOM_FUNCTION_APPROVE: 'designer.custom_function.approve',
  DESIGNER_CUSTOM_FUNCTION_EXECUTE: 'designer.custom_function.execute',
  DESIGNER_VISIT_READ: 'designer.visit.read',
  DESIGNER_VISIT_CONFIGURE: 'designer.visit.configure',
  DESIGNER_CODELIST_READ: 'designer.codelist.read',
  DESIGNER_CODELIST_CONFIGURE: 'designer.codelist.configure',
  DESIGNER_SUBJECT_PHASE_READ: 'designer.subject_phase.read',
  DESIGNER_SUBJECT_PHASE_CONFIGURE: 'designer.subject_phase.configure',
  DESIGNER_SOA_READ: 'designer.soa.read',
  DESIGNER_SOA_CONFIGURE: 'designer.soa.configure',
  DESIGNER_ARM_READ: 'designer.arm.read',
  DESIGNER_ARM_CONFIGURE: 'designer.arm.configure',
  DESIGNER_CRF_ACCESS_CONFIGURE: 'designer.crf_access.configure',
  DESIGNER_RAW_DATA_VARIABLE_CONFIGURE: 'designer.raw_data_variable.configure',
  DESIGNER_CODING_SETTING_CONFIGURE: 'designer.coding_setting.configure',
  DESIGNER_SDR_CONFIGURE: 'designer.sdr.configure',
  DESIGNER_ODM_IMPORT: 'designer.odm.import',
  DESIGNER_ODM_EXPORT: 'designer.odm.export',

  // SDV & Review
  SDV_MANAGE: 'sdv.manage',
  REVIEW_MANAGE: 'review.manage',
  LISTING_READ: 'listing.read',
  REVIEW_READ: 'review.read',
  SDV_READ: 'sdv.read',
  SDR_READ: 'sdr.read',
  SDR_MANAGE: 'sdr.manage',

  // Lock
  LOCK_MANAGE: 'lock.manage',
  LOCK_READ: 'lock.read',
  LOCK_REQUEST: 'lock.request',
  LOCK_APPROVE: 'lock.approve',
  LOCK_EXECUTE: 'lock.execute',

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
  CTMS_TEMPLATE_RULE_MANAGEMENT: 'ctms.template_rule_management',
  CTMS_CAPA_MANAGEMENT: 'ctms.capa_management',
  CTMS_CAPACITY_OVERRIDE: 'ctms.capacity_override',

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
  // Flat permissions are system-wide grants, so they apply at every scope.
  if ((user.permissions ?? []).includes(permission)) return true
  return user.roles.some((role) => roleAllows(role, permission, studyId, siteId))
}

function roleAllows(
  role: UserRoleAssignment,
  permission: PermissionCode,
  studyId?: string,
  siteId?: string,
): boolean {
  if (!(role.permissions ?? []).includes(permission)) return false
  if (!role.study_id && !role.site_id) return true
  if (!studyId || role.study_id !== studyId) return false
  if (!role.site_id) return true
  return !!siteId && role.site_id === siteId
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
  // Flat permissions are system-wide grants, so they apply at every scope.
  if ((user.permissions ?? []).includes(permission)) return true
  return user.roles.some((role) => roleAllows(role, permission, studyId, siteId))
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
