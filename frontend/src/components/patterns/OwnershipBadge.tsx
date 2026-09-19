import { Badge, type BadgeProps } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export type OwnershipModule = 'EDC' | 'CTMS' | (string & {})
export type OwnershipState = 'authoritative' | 'projected' | 'coordinated' | 'archived' | (string & {})

export interface OwnershipBadgeProps extends Omit<BadgeProps, 'children'> {
  owner: OwnershipModule
  state?: OwnershipState
  readOnly?: boolean
}

function displayState(state: OwnershipState): string {
  return state === 'projected' ? 'Projected' : state === 'coordinated' ? 'Coordinated' : state === 'archived' ? 'Archived' : 'Authoritative'
}

export function OwnershipBadge({ owner, state = 'authoritative', readOnly = owner !== 'CTMS', className, ...props }: OwnershipBadgeProps) {
  const normalizedOwner = owner.toUpperCase() === 'EDC' ? 'EDC' : owner.toUpperCase() === 'CTMS' ? 'CTMS' : owner
  const ownership = displayState(state)
  const readOnlyLabel = readOnly ? ' · Read only' : ''
  return (
    <Badge
      {...props}
      role="status"
      variant="outline"
      aria-label={`authoritative module: ${normalizedOwner}; ownership: ${ownership}${readOnlyLabel}`}
      data-owner={normalizedOwner}
      data-ownership={state}
      className={cn('gap-1.5 border-border bg-muted/50', className)}
    >
      <span aria-hidden="true" className="text-[0.65em]">◆</span>
      <span>{normalizedOwner} · {ownership}{readOnly ? ' · Read only' : ''}</span>
    </Badge>
  )
}
