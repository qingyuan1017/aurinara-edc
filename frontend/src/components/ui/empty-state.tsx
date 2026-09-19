import * as React from 'react'
import { Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> { title: string; description?: React.ReactNode; action?: React.ReactNode; icon?: React.ReactNode }
const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(({ className, title, description, action, icon, ...props }, ref) => <div ref={ref} role="status" className={cn('flex min-h-40 flex-col items-center justify-center rounded-lg border border-dashed p-8 text-center', className)} {...props}><div className="mb-3 text-muted-foreground" aria-hidden="true">{icon ?? <Inbox className="size-8" />}</div><h3 className="font-semibold">{title}</h3>{description ? <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p> : null}{action ? <div className="mt-4">{action}</div> : null}</div>)
EmptyState.displayName = 'EmptyState'
export { EmptyState }
