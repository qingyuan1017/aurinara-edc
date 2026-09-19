import * as React from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export interface LoadingStateProps extends React.HTMLAttributes<HTMLDivElement> {
  label?: string
  refreshing?: boolean
  children?: React.ReactNode
}

export function LoadingState({ className, label = 'content', refreshing = false, children, ...props }: LoadingStateProps) {
  const message = refreshing ? `Refreshing ${label}…` : `Loading ${label}…`
  return (
    <div
      {...props}
      role="status"
      aria-live="polite"
      aria-label={message}
      data-state={refreshing ? 'refreshing' : 'loading'}
      className={cn('space-y-3 rounded-lg border bg-card p-6', refreshing && 'border-info/50 bg-info/10 p-3', className)}
    >
      <p className="text-sm font-medium text-muted-foreground">{message}</p>
      {children ?? <div className="space-y-2" aria-hidden="true"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>}
    </div>
  )
}
