import * as React from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { getCTMSErrorMessage } from '@/features/ctms/api'
import { formatCTMSMutationMessage } from '@/features/ctms/components/CTMSMutationFeedback'
import { cn } from '@/lib/utils'

export type MutationFeedbackStatus = 'idle' | 'pending' | 'success' | 'error'

export interface MutationFeedbackProps {
  status: MutationFeedbackStatus
  action: string
  data?: unknown
  error?: unknown
  requestId?: string
  correlationId?: string
  successMessage?: React.ReactNode
  pendingMessage?: React.ReactNode
  errorMessage?: React.ReactNode
  className?: string
}

/**
 * Announces mutation outcomes without owning the mutation, authorization, or
 * cache policy. Error text is normalized through the existing sanitized CTMS
 * error contract so raw responses and stack traces are not rendered.
 */
export function MutationFeedback({
  status,
  action,
  data,
  error,
  requestId,
  correlationId,
  successMessage,
  pendingMessage,
  errorMessage,
  className,
}: MutationFeedbackProps) {
  if (status === 'idle') return null

  if (status === 'pending') {
    return (
      <Alert className={cn(className)} role="status" aria-live="polite" data-mutation-status="pending">
        <AlertDescription>{pendingMessage ?? `${action} is being submitted. Do not submit it again.`}</AlertDescription>
      </Alert>
    )
  }

  if (status === 'success') {
    return (
      <Alert variant="success" className={cn(className)} role="status" aria-live="polite" data-mutation-status="success">
        <AlertDescription>{successMessage ?? formatCTMSMutationMessage(action, 'success', data, requestId, correlationId)}</AlertDescription>
      </Alert>
    )
  }

  const safeError = errorMessage ?? getCTMSErrorMessage(error)
  return (
    <Alert variant="destructive" className={cn(className)} role="alert" aria-live="assertive" data-mutation-status="error">
      <AlertDescription>{errorMessage ?? `${formatCTMSMutationMessage(action, 'error', error, requestId, correlationId)} ${safeError}`}</AlertDescription>
    </Alert>
  )
}
