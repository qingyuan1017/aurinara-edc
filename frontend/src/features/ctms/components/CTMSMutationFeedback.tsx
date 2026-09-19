import { useEffect, useMemo, useState } from 'react'
import { getCTMSErrorMessage } from '../api'

export type CTMSMutationFeedbackStatus = 'idle' | 'pending' | 'success' | 'error'

export interface CTMSMutationMetadata {
  requestId?: string
  correlationId?: string
}

export interface CTMSMutationFeedbackProps {
  status: CTMSMutationFeedbackStatus
  action: string
  data?: unknown
  error?: unknown
  requestId?: string
  correlationId?: string
}

function safeIdentifier(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  return normalized && normalized.length <= 200 && /^[\w:.\-/]+$/.test(normalized) ? normalized : undefined
}

function metadataFrom(value: unknown): CTMSMutationMetadata {
  if (!value || typeof value !== 'object') return {}
  const record = value as Record<string, unknown>
  const response = record.response && typeof record.response === 'object' ? record.response as Record<string, unknown> : undefined
  const responseData = response?.data && typeof response.data === 'object' ? response.data as Record<string, unknown> : undefined
  const headers = response?.headers && typeof response.headers === 'object' ? response.headers as Record<string, unknown> : undefined
  const envelope = record.error && typeof record.error === 'object' ? record.error as Record<string, unknown> : undefined
  return {
    requestId: safeIdentifier(record.requestId ?? record.request_id ?? headers?.['x-request-id'] ?? responseData?.request_id ?? envelope?.request_id),
    correlationId: safeIdentifier(record.correlationId ?? record.correlation_id ?? responseData?.correlation_id ?? envelope?.correlation_id),
  }
}

export function getCTMSMutationMetadata(value: unknown): CTMSMutationMetadata {
  return metadataFrom(value)
}

export function formatCTMSMutationMessage(action: string, status: 'success' | 'error', value?: unknown, requestId?: string, correlationId?: string): string {
  const metadata = metadataFrom(value)
  const safeRequestId = safeIdentifier(requestId) ?? metadata.requestId
  const safeCorrelationId = safeIdentifier(correlationId) ?? metadata.correlationId
  const details = [safeRequestId && `Request ID ${safeRequestId}`, safeCorrelationId && `Correlation ID ${safeCorrelationId}`].filter(Boolean).join('. ')
  const message = status === 'success' ? `${action} completed successfully.` : `${action} could not be completed.`
  return details ? `${message} ${details}.` : message
}

export function CTMSMutationFeedback({ status, action, data, error, requestId, correlationId }: CTMSMutationFeedbackProps) {
  const [announcement, setAnnouncement] = useState('')
  const message = useMemo(() => {
    if (status === 'success') return formatCTMSMutationMessage(action, 'success', data, requestId, correlationId)
    if (status === 'error') return `${formatCTMSMutationMessage(action, 'error', error, requestId, correlationId)} ${getCTMSErrorMessage(error)}`
    return ''
  }, [action, correlationId, data, error, requestId, status])

  useEffect(() => {
    if (message) setAnnouncement(message)
  }, [message])

  if (!announcement || status === 'idle' || status === 'pending') return null
  return <p role={status === 'error' ? 'alert' : 'status'} aria-live={status === 'error' ? 'assertive' : 'polite'}>{announcement}</p>
}
