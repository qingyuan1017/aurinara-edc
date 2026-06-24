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
  _studyId?: string,
  _siteId?: string,
): boolean {
  const user = useAuthStore.getState().user
  if (!user) return false

  // Simple flat permission check for now.
  // The server handles study/site scoping authoritatively.
  return user.permissions.includes(permission)
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
  return user.permissions.includes(permission)
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
