import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * Status color mappings for different clinical entity statuses.
 * Each domain (subject, form, query, SDV, review, lock, signature) has
 * its own set of statuses and corresponding visual treatments.
 */

type StatusDomain =
  | 'subject'
  | 'form'
  | 'query'
  | 'sdv'
  | 'review'
  | 'lock'
  | 'signature'

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      color: {
        blue: 'bg-blue-100 text-blue-800',
        green: 'bg-green-100 text-green-800',
        yellow: 'bg-yellow-100 text-yellow-800',
        red: 'bg-red-100 text-red-800',
        gray: 'bg-gray-100 text-gray-800',
        purple: 'bg-purple-100 text-purple-800',
        orange: 'bg-orange-100 text-orange-800',
        indigo: 'bg-indigo-100 text-indigo-800',
      },
    },
    defaultVariants: {
      color: 'gray',
    },
  },
)

type BadgeColor = NonNullable<VariantProps<typeof badgeVariants>['color']>

/**
 * Map from (domain, status) → color.
 */
const STATUS_COLORS: Record<StatusDomain, Record<string, BadgeColor>> = {
  subject: {
    screening: 'blue',
    enrolled: 'green',
    completed: 'indigo',
    withdrawn: 'red',
    'screen-failed': 'gray',
  },
  form: {
    'not started': 'gray',
    'in progress': 'yellow',
    submitted: 'green',
    frozen: 'purple',
    locked: 'red',
  },
  query: {
    open: 'red',
    answered: 'orange',
    closed: 'green',
    cancelled: 'gray',
  },
  sdv: {
    pending: 'yellow',
    verified: 'green',
    'not required': 'gray',
  },
  review: {
    pending: 'yellow',
    reviewed: 'green',
    'not required': 'gray',
  },
  lock: {
    unlocked: 'gray',
    locked: 'red',
  },
  signature: {
    unsigned: 'gray',
    signed: 'green',
    invalidated: 'red',
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
 * StatusBadge renders a colored pill for clinical entity statuses.
 * Supports subjects, forms, queries, SDV, review, lock, and signature domains.
 */
export function StatusBadge({ domain, status, className }: StatusBadgeProps) {
  const normalizedStatus = status.toLowerCase()
  const domainColors = STATUS_COLORS[domain]
  const color: BadgeColor = domainColors?.[normalizedStatus] ?? 'gray'

  return (
    <span
      className={cn(badgeVariants({ color }), className)}
      role="status"
      aria-label={`${domain} status: ${status}`}
    >
      {status}
    </span>
  )
}
