import * as React from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type PresentationState = 'error' | 'unauthorized' | 'offline' | 'disabled' | 'unavailable' | 'worker-unavailable'

export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  state?: PresentationState
  title?: string
  message?: React.ReactNode
  onRetry?: () => void
  retryLabel?: string
  actions?: React.ReactNode
}

const defaultCopy: Record<PresentationState, { title: string; message: string }> = {
  error: { title: 'Unable to load this content', message: 'Something went wrong. Please try again.' },
  unauthorized: { title: 'Access denied', message: 'You do not have permission to view this content.' },
  offline: { title: 'You are offline', message: 'Reconnect to continue. Cached content may be stale.' },
  disabled: { title: 'This capability is disabled', message: 'This area is not enabled for the current workspace.' },
  unavailable: { title: 'This capability is unavailable', message: 'The service is temporarily unavailable. Existing data and workflows are unchanged.' },
  'worker-unavailable': { title: 'Coordination worker unavailable', message: 'Operational coordination is temporarily unavailable. EDC clinical workflows remain available.' },
}

export function ErrorState({ className, state = 'error', title, message, onRetry, retryLabel = 'Retry', actions, ...props }: ErrorStateProps) {
  const copy = defaultCopy[state]
  const canRetry = Boolean(onRetry) && state !== 'unauthorized' && state !== 'disabled'
  return (
    <div {...props} data-state={state} className={cn('space-y-3', className)}>
      <Alert variant={state === 'error' ? 'destructive' : 'warning'} role={state === 'error' ? 'alert' : 'status'}>
        <AlertTitle>{title ?? copy.title}</AlertTitle>
        <AlertDescription>{message ?? copy.message}</AlertDescription>
      </Alert>
      {canRetry || actions ? <div className="flex flex-wrap gap-2">{canRetry ? <Button type="button" variant="outline" onClick={onRetry}>{retryLabel}</Button> : null}{actions}</div> : null}
    </div>
  )
}
