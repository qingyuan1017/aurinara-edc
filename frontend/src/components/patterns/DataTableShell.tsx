import * as React from 'react'
import { EmptyState } from './EmptyState'
import { ErrorState, type PresentationState } from './ErrorState'
import { LoadingState } from './LoadingState'
import { cn } from '@/lib/utils'

export type DataTablePresentationState = PresentationState | 'loading' | 'refreshing' | 'empty'
export type DataTableStateSlots = Partial<Record<DataTablePresentationState, React.ReactNode>>

export interface DataTableShellProps extends React.HTMLAttributes<HTMLElement> {
  label: string
  children?: React.ReactNode
  state?: DataTablePresentationState
  loading?: boolean
  refreshing?: boolean
  empty?: boolean
  error?: boolean
  errorMessage?: React.ReactNode
  onRetry?: () => void
  emptyTitle?: string
  emptyDescription?: React.ReactNode
  emptyAction?: React.ReactNode
  requiresStudy?: boolean
  hasSelectedStudy?: boolean
  stateSlots?: DataTableStateSlots
}

export function DataTableShell({
  className,
  label,
  children,
  state,
  loading = false,
  refreshing = false,
  empty = false,
  error = false,
  errorMessage,
  onRetry,
  emptyTitle,
  emptyDescription,
  emptyAction,
  requiresStudy = false,
  hasSelectedStudy = true,
  stateSlots,
  ...props
}: DataTableShellProps) {
  const resolvedState: DataTablePresentationState | undefined = state ?? (loading ? 'loading' : error ? 'error' : empty ? 'empty' : refreshing ? 'refreshing' : undefined)
  const customState = resolvedState ? stateSlots?.[resolvedState] : undefined

  if (customState) return <section {...props} aria-label={label} data-state={resolvedState} className={cn('min-w-0 space-y-3', className)}>{customState}</section>
  if (resolvedState === 'loading') return <section {...props} aria-label={label} data-state="loading" className={cn('min-w-0', className)}><LoadingState label={label} /></section>
  if (resolvedState === 'refreshing') {
    return <section {...props} aria-label={label} data-state="refreshing" className={cn('min-w-0 space-y-3', className)}><LoadingState label={label} refreshing className="shadow-none" />{children}</section>
  }
  if (resolvedState === 'empty') return <section {...props} aria-label={label} data-state="empty" className={cn('min-w-0', className)}><EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} requiresStudy={requiresStudy} hasSelectedStudy={hasSelectedStudy} /></section>
  if (resolvedState && ['error', 'unauthorized', 'offline', 'disabled', 'unavailable', 'worker-unavailable'].includes(resolvedState)) {
    return <section {...props} aria-label={label} data-state={resolvedState} className={cn('min-w-0', className)}><ErrorState state={resolvedState} message={errorMessage} onRetry={onRetry} /></section>
  }

  return (
    <section {...props} aria-label={label} data-state="success" className={cn('min-w-0 space-y-3', className)}>
      <div className="w-full overflow-x-auto rounded-lg border" tabIndex={0} aria-label={`Scrollable ${label} table`}>
        {children}
      </div>
    </section>
  )
}
