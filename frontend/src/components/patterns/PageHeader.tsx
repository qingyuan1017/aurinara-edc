import * as React from 'react'
import { cn } from '@/lib/utils'

export interface PageHeaderProps extends React.HTMLAttributes<HTMLElement> {
  title: string
  description?: React.ReactNode
  breadcrumbs?: React.ReactNode
  actions?: React.ReactNode
  status?: React.ReactNode
  ownership?: React.ReactNode
  freshness?: React.ReactNode
}

export const PageHeader = React.forwardRef<HTMLElement, PageHeaderProps>(
  ({ className, title, description, breadcrumbs, actions, status, ownership, freshness, ...props }, ref) => (
    <header ref={ref} className={cn('mb-6 space-y-4', className)} {...props}>
      {breadcrumbs ? <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">{breadcrumbs}</nav> : null}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{title}</h1>
          {description ? <p className="max-w-3xl text-sm text-muted-foreground">{description}</p> : null}
          {status || ownership || freshness ? (
            <div className="flex flex-wrap items-center gap-2 pt-2" aria-label="Page context">
              {status}
              {ownership}
              {freshness}
            </div>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  ),
)
PageHeader.displayName = 'PageHeader'
