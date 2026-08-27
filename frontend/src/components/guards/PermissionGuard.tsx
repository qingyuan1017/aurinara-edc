import type { ReactNode } from 'react'
import { usePermission, type PermissionCode } from '@/lib/permissions'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'

interface PermissionGuardProps {
  /** The permission required to view the child content. */
  permission: PermissionCode
  /** Optional study scope for the permission check. */
  studyId?: string
  /** Optional site scope for the permission check. */
  siteId?: string
  /** Content to render when the user has the required permission. */
  children: ReactNode
}

/**
 * PermissionGuard — wraps content that requires a specific permission.
 * Renders an Access Denied page if the current user lacks the permission.
 * Frontend check is convenience only; server enforces authoritatively (Req 2.6).
 */
export function PermissionGuard({ permission, studyId, siteId, children }: PermissionGuardProps) {
  const hasAccess = usePermission(permission, studyId, siteId)

  if (!hasAccess) {
    return <AccessDeniedPage />
  }

  return <>{children}</>
}
