import * as React from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface FormActionsProps extends React.HTMLAttributes<HTMLDivElement> {
  pending?: boolean
  submitDisabled?: boolean
  submitLabel?: string
  pendingLabel?: string
  cancelLabel?: string
  onCancel?: () => void
  cancelDisabled?: boolean
  disableCancelWhilePending?: boolean
}

/**
 * Presentation-only form actions. A pending submit button is disabled so the
 * caller's mutation cannot be triggered twice; mutation and cache behavior
 * remain owned by the containing feature.
 */
export function FormActions({
  pending = false,
  submitDisabled = false,
  submitLabel = 'Save',
  pendingLabel = 'Saving…',
  cancelLabel = 'Cancel',
  onCancel,
  cancelDisabled = false,
  disableCancelWhilePending = false,
  className,
  ...props
}: FormActionsProps) {
  const cancelIsDisabled = cancelDisabled || (disableCancelWhilePending && pending)

  return (
    <div className={cn('flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end', className)} {...props}>
      {onCancel ? (
        <Button type="button" variant="outline" onClick={onCancel} disabled={cancelIsDisabled}>
          {cancelLabel}
        </Button>
      ) : null}
      <Button
        type="submit"
        pending={pending}
        loadingText={pendingLabel}
        disabled={submitDisabled}
        aria-busy={pending || undefined}
      >
        {submitLabel}
      </Button>
      {pending ? <span role="status" aria-live="polite" className="sr-only">{pendingLabel} Do not submit again.</span> : null}
    </div>
  )
}
