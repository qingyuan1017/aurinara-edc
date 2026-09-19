import { zodResolver } from '@hookform/resolvers/zod'
import * as React from 'react'
import { useEffect, useMemo, useState } from 'react'
import { useForm, type SubmitHandler } from 'react-hook-form'
import type { CTMSMutationFeedbackStatus } from '../components/CTMSMutationFeedback'
import type { CTMSStatusTransitionPayload, CTMSTransitionOption, CTMSTransitionResult } from '../api'
import { mapCTMSServerErrors, createStatusTransitionSchema } from './schemas'
import { CTMSFormField } from './CTMSFormField'
import { CTMSFormShell } from './CTMSFormShell'

export interface CTMSStatusTransitionValues {
  status: string
  reason?: string
}

export interface CTMSStatusTransitionMutation<T = unknown> {
  status: CTMSMutationFeedbackStatus
  data?: CTMSTransitionResult<T>
  error?: unknown
  mutateAsync: (variables: CTMSStatusTransitionPayload) => Promise<CTMSTransitionResult<T>>
}

export interface CTMSStatusTransitionFormProps<T = unknown> {
  currentStatus: string
  allowedTransitions: readonly CTMSTransitionOption[]
  mutation?: CTMSStatusTransitionMutation<T>
  onTransition?: (payload: CTMSStatusTransitionPayload) => Promise<CTMSTransitionResult<T>> | CTMSTransitionResult<T>
  onSuccess?: (result: CTMSTransitionResult<T>) => void
  title?: string
  description?: string
  open?: boolean
  onCancel?: () => void
  submitLabel?: string
}

/**
 * Renders only the transition options supplied by the server. The displayed
 * current status is never derived from the selected option; it changes only
 * after a committed transition response returns current_status.
 */
export function CTMSStatusTransitionForm<T = unknown>({
  currentStatus,
  allowedTransitions,
  mutation,
  onTransition,
  onSuccess,
  title = 'Change operational status',
  description = 'Choose an allowed CTMS status transition. The server remains authoritative.',
  open = true,
  onCancel,
  submitLabel = 'Apply status transition',
}: CTMSStatusTransitionFormProps<T>) {
  const [localResult, setLocalResult] = useState<CTMSTransitionResult<T>>()
  const serverResult = mutation?.data ?? localResult
  const availableTransitions = serverResult?.allowed_transitions ?? allowedTransitions
  const schema = useMemo(() => createStatusTransitionSchema(availableTransitions), [availableTransitions])
  const methods = useForm<CTMSStatusTransitionValues>({
    resolver: zodResolver(schema),
    defaultValues: { status: '', reason: '' },
  })
  const selectedStatus = methods.watch('status')
  const selectedOption = availableTransitions.find((option) => option.status === selectedStatus)
  const statusLabel = serverResult?.current_status ?? currentStatus
  const mutationError = mutation?.error

  useEffect(() => {
    if (!selectedStatus || availableTransitions.some((option) => option.status === selectedStatus)) return
    methods.setValue('status', '', { shouldValidate: true })
    methods.setValue('reason', '')
  }, [availableTransitions, methods, selectedStatus])

  useEffect(() => {
    if (!serverResult) return
    methods.reset({ status: '', reason: '' })
    onSuccess?.(serverResult)
  }, [methods, onSuccess, serverResult])

  const handleSubmit: SubmitHandler<CTMSStatusTransitionValues> = async (values) => {
    const payload: CTMSStatusTransitionPayload = {
      status: values.status,
      ...(values.reason?.trim() ? { reason: values.reason.trim() } : {}),
    }
    try {
      const result = mutation ? await mutation.mutateAsync(payload) : await onTransition?.(payload)
      if (result && !mutation) setLocalResult(result)
    } catch (error) {
      mapCTMSServerErrors(error, methods.setError)
    }
  }

  const mutationStatus = mutation?.status ?? 'idle'
  const formMessage = !mutation ? undefined : undefined

  return (
    <CTMSFormShell
      methods={methods}
      title={title}
      description={description}
      onSubmit={handleSubmit}
      onCancel={onCancel}
      open={open}
      submitLabel={submitLabel}
      submitDisabled={!availableTransitions.length || !onTransition && !mutation}
      initialFocusName="status"
      formMessage={formMessage}
      mutation={{
        status: mutationStatus,
        action: 'Status transition',
        data: serverResult,
        error: mutationError,
      }}
    >
      <div className="rounded-md border bg-muted/20 p-3" aria-live="polite">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Current server status</p>
        <p className="mt-1 text-sm font-semibold" data-testid="ctms-current-status">{statusLabel}</p>
        <p className="mt-1 text-xs text-muted-foreground">The selected status is a requested transition, not the current status.</p>
      </div>
      {availableTransitions.length ? (
        <>
          <CTMSFormField
            control={methods.control}
            name="status"
            label="New status"
            type="select"
            required
            options={availableTransitions.map((option) => ({ value: option.status, label: option.status }))}
            description="Only statuses returned by the CTMS API are available."
          />
          <CTMSFormField
            control={methods.control}
            name="reason"
            label={selectedOption?.reason_label ?? 'Reason'}
            type="textarea"
            required={Boolean(selectedOption?.requires_reason)}
            description={selectedOption?.requires_reason ? 'A reason is required for this server-defined transition.' : 'Optional unless required by the selected transition.'}
          />
        </>
      ) : (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground" role="status">No status transitions are currently allowed.</p>
      )}
    </CTMSFormShell>
  )
}

/** Dialog naming alias for callers that render the form as a modal. */
export const CTMSStatusTransitionDialog = CTMSStatusTransitionForm

/** Compatibility alias for resource screens that call this a transition form. */
export const StatusTransitionForm = CTMSStatusTransitionForm

/** Keep the form's public ref type available to modal wrappers. */
export type CTMSStatusTransitionFormRef = React.RefObject<HTMLDivElement | null>
