import { Badge } from '@/components/ui/badge'

/**
 * Status color mappings for different clinical entity statuses.
 * Each domain (subject, form, query, SDV, review, lock, signature) has
 * its own set of statuses and corresponding semantic visual treatments.
 */

type StatusDomain =
  | 'subject'
  | 'form'
  | 'query'
  | 'sdv'
  | 'review'
  | 'lock'
  | 'signature'

type StatusVariant = 'info' | 'success' | 'warning' | 'destructive' | 'secondary'

/**
 * Map from (domain, status) to a semantic Badge variant.
 * Semantic variants keep clinical status meaning while supporting both themes.
 */
const STATUS_VARIANTS: Record<StatusDomain, Record<string, StatusVariant>> = {
  subject: {
    screening: 'info',
    enrolled: 'success',
    completed: 'info',
    withdrawn: 'destructive',
    'screen-failed': 'secondary',
  },
  form: {
    'not started': 'secondary',
    'in progress': 'warning',
    submitted: 'success',
    frozen: 'secondary',
    locked: 'destructive',
  },
  query: {
    open: 'destructive',
    answered: 'warning',
    closed: 'success',
    cancelled: 'secondary',
  },
  sdv: {
    pending: 'warning',
    verified: 'success',
    'not required': 'secondary',
  },
  review: {
    pending: 'warning',
    reviewed: 'success',
    'not required': 'secondary',
  },
  lock: {
    unlocked: 'secondary',
    locked: 'destructive',
  },
  signature: {
    unsigned: 'secondary',
    valid: 'success',
    signed: 'success',
    stale: 'warning',
    invalidated: 'destructive',
  },
}

export interface StatusBadgeProps {
  /** The clinical domain this status belongs to */
  domain: StatusDomain
  /** The status value to display */
  status: string
  /** Optional additional className */
  className?: string
}

/**
 * StatusBadge renders a semantic pill for clinical entity statuses.
 * Supports subjects, forms, queries, SDV, review, lock, and signature domains.
 */
export function StatusBadge({ domain, status, className }: StatusBadgeProps) {
  const normalizedStatus = status.toLowerCase()
  const variant = STATUS_VARIANTS[domain]?.[normalizedStatus] ?? 'secondary'

  return (
    <Badge
      variant={variant}
      className={className}
      role="status"
      aria-label={`${domain} status: ${status}`}
    >
      {status}
    </Badge>
  )
}
