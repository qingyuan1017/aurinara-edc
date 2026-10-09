import { useMemo } from 'react'
import {
  ctmsMutationFeedbackMessage,
  type CTMSMutationFeedbackStatus,
  type CTMSMutationMetadata,
} from './feedbackMessage'

export type { CTMSMutationFeedbackStatus, CTMSMutationMetadata }

export interface CTMSMutationFeedbackProps {
  status: CTMSMutationFeedbackStatus
  action: string
  data?: unknown
  error?: unknown
  requestId?: string
  correlationId?: string
}

export function CTMSMutationFeedback({ status, action, data, error, requestId, correlationId }: CTMSMutationFeedbackProps) {
  const message = useMemo(
    () => ctmsMutationFeedbackMessage(status, action, { data, error, requestId, correlationId }),
    [action, correlationId, data, error, requestId, status],
  )

  if (!message || status === 'idle' || status === 'pending') return null
  return <p role={status === 'error' ? 'alert' : 'status'} aria-live={status === 'error' ? 'assertive' : 'polite'}>{message}</p>
}
