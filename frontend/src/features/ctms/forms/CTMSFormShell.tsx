import * as React from 'react'
import { FormProvider, type FieldErrors, type FieldValues, type Path, type SubmitHandler, type UseFormReturn } from 'react-hook-form'
import { Button } from '@/components/ui/button'
import { CTMSMutationFeedback, type CTMSMutationFeedbackStatus } from '../components/CTMSMutationFeedback'
import { cn } from '@/lib/utils'

export interface CTMSFormShellProps<T extends FieldValues> {
  methods: UseFormReturn<T>
  title: string
  children: React.ReactNode
  onSubmit: SubmitHandler<T>
  onCancel?: () => void
  open?: boolean
  description?: string
  submitLabel?: string
  cancelLabel?: string
  submitDisabled?: boolean
  className?: string
  initialFocusName?: Path<T>
  returnFocusRef?: React.RefObject<HTMLElement | null>
  formMessage?: string
  mutation?: {
    status: CTMSMutationFeedbackStatus
    action: string
    data?: unknown
    error?: unknown
    requestId?: string
    correlationId?: string
  }
}

function firstErrorPath(errors: FieldErrors, prefix = ''): string | undefined {
  for (const [key, value] of Object.entries(errors)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && 'message' in value && typeof value.message === 'string') return path
    if (value && typeof value === 'object') {
      const nested = firstErrorPath(value as FieldErrors, path)
      if (nested) return nested
    }
  }
  return undefined
}

/**
 * Accessible CTMS form/dialog shell. It deliberately keeps drafts in RHF
 * memory only; no localStorage or other client persistence is used.
 */
export function CTMSFormShell<T extends FieldValues>({
  methods,
  title,
  children,
  onSubmit,
  onCancel,
  open = true,
  description,
  submitLabel = 'Save',
  cancelLabel = 'Cancel',
  submitDisabled = false,
  className,
  initialFocusName,
  returnFocusRef,
  formMessage,
  mutation,
}: CTMSFormShellProps<T>) {
  const dialogRef = React.useRef<HTMLDivElement>(null)
  const previousFocusRef = React.useRef<HTMLElement | null>(null)

  React.useEffect(() => {
    if (!open) return undefined
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const initialReturnFocus = returnFocusRef?.current
    const focusTimer = window.setTimeout(() => {
      if (initialFocusName) {
        methods.setFocus(initialFocusName)
      } else {
        dialogRef.current?.querySelector<HTMLElement>('[data-ctms-form-control]:not([disabled])')?.focus()
      }
    }, 0)
    return () => {
      window.clearTimeout(focusTimer)
      const focusTarget = initialReturnFocus ?? previousFocusRef.current
      if (focusTarget && document.contains(focusTarget)) focusTarget.focus()
    }
  }, [initialFocusName, methods, open, returnFocusRef])

  React.useEffect(() => {
    if (!open || methods.formState.submitCount === 0) return
    const errorPath = firstErrorPath(methods.formState.errors)
    if (errorPath) methods.setFocus(errorPath as Path<T>)
  }, [methods, methods.formState.errors, methods.formState.submitCount, open])

  if (!open) return null

  const handleCancel = () => {
    onCancel?.()
    const focusTarget = returnFocusRef?.current ?? previousFocusRef.current
    if (focusTarget && document.contains(focusTarget)) focusTarget.focus()
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && onCancel) {
      event.preventDefault()
      handleCancel()
    }
  }

  const rootError = methods.formState.errors.root as { server?: { message?: unknown } } | undefined
  const rhfFormMessage = typeof rootError?.server?.message === 'string' ? rootError.server.message : undefined
  const displayedFormMessage = formMessage ?? rhfFormMessage

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="ctms-form-title"
      aria-describedby={description ? 'ctms-form-description' : undefined}
      tabIndex={-1}
      onKeyDown={handleKeyDown}
      className={cn('rounded-lg border bg-background p-6 shadow-sm', className)}
    >
      <FormProvider {...methods}>
        <form onSubmit={methods.handleSubmit(onSubmit)} noValidate className="space-y-5">
          <div>
            <h2 id="ctms-form-title" className="text-lg font-semibold">{title}</h2>
            {description ? <p id="ctms-form-description" className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
          </div>
          {displayedFormMessage ? <p role="alert" className="text-sm text-destructive">{displayedFormMessage}</p> : null}
          {children}
          {mutation ? <CTMSMutationFeedback {...mutation} /> : null}
          {mutation?.status === 'pending' ? <p role="status" aria-live="polite">Saving…</p> : null}
          <div className="flex justify-end gap-2 border-t pt-4">
            {onCancel ? <Button type="button" variant="outline" onClick={handleCancel}> {cancelLabel} </Button> : null}
            <Button type="submit" disabled={submitDisabled || mutation?.status === 'pending'}>{submitLabel}</Button>
          </div>
        </form>
      </FormProvider>
    </div>
  )
}
