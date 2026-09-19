import * as React from 'react'
import { cn } from '@/lib/utils'

export interface PageToolbarProps extends React.HTMLAttributes<HTMLDivElement> {
  label?: string
  actions?: React.ReactNode
}

export const PageToolbar = React.forwardRef<HTMLDivElement, PageToolbarProps>(
  ({ className, label = 'Page controls', actions, children, ...props }, ref) => (
    <div ref={ref} role="toolbar" aria-label={label} className={cn('mb-4 flex flex-col gap-3 rounded-lg border bg-card p-3 sm:flex-row sm:items-center sm:justify-between', className)} {...props}>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{children}</div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  ),
)
PageToolbar.displayName = 'PageToolbar'
