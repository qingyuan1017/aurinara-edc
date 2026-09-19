import { Badge, type BadgeProps } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export type StatusTone = 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'secondary'

export interface StatusBadgeProps extends Omit<BadgeProps, 'children'> {
  status: string
  label?: string
  tone?: StatusTone
  freshness?: 'current' | 'stale' | 'unknown'
}

function inferTone(status: string): StatusTone {
  const normalized = status.trim().toLowerCase()
  if (['ready', 'active', 'completed', 'complete', 'submitted', 'enrolled', 'current', 'success', 'closed'].includes(normalized)) return 'success'
  if (['stale', 'pending', 'in progress', 'screening', 'warning', 'refreshing'].includes(normalized)) return 'warning'
  if (['error', 'failed', 'withdrawn', 'locked', 'blocked', 'destructive', 'denied'].includes(normalized)) return 'destructive'
  if (['info', 'informational', 'offline'].includes(normalized)) return 'info'
  return 'secondary'
}

export function StatusBadge({ status, label = 'Status', tone, freshness, className, ...props }: StatusBadgeProps) {
  const visibleStatus = freshness ? `${status} · ${freshness}` : status
  const resolvedTone = tone ?? inferTone(status)
  return (
    <Badge
      {...props}
      role="status"
      variant={resolvedTone}
      aria-label={`${label}: ${visibleStatus}`}
      data-status={status}
      data-freshness={freshness}
      className={cn('gap-1.5', className)}
    >
      <span aria-hidden="true" className="text-[0.65em]">●</span>
      <span>{visibleStatus}</span>
    </Badge>
  )
}
