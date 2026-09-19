import * as React from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export interface ConfirmReasonConfig {
  label?: string
  description?: React.ReactNode
  placeholder?: string
  required?: boolean
  minLength?: number
  maxLength?: number
  defaultValue?: string
  value?: string
  onChange?: (value: string) => void
}

export interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: React.ReactNode
  children?: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  pending?: boolean
  confirmDisabled?: boolean
  permissionAllowed?: boolean
  permissionMessage?: React.ReactNode
  requiresReauthentication?: boolean
  reauthenticationMessage?: React.ReactNode
  reason?: ConfirmReasonConfig | boolean
  requireReason?: boolean
  reasonLabel?: string
  reasonPlaceholder?: string
  onConfirm: (reason?: string) => void | Promise<void>
  onCancel?: () => void
  onOpenChange?: (open: boolean) => void
  returnFocusRef?: React.RefObject<HTMLElement | null>
  className?: string
}

function validationMessage(reason: string, config: ConfirmReasonConfig | undefined, required: boolean): string | undefined {
  const trimmed = reason.trim()
  if (required && !trimmed) return 'A reason is required.'
  if (config?.minLength !== undefined && trimmed.length > 0 && trimmed.length < config.minLength) {
    return `Reason must be at least ${config.minLength} characters.`
  }
  if (config?.maxLength !== undefined && trimmed.length > config.maxLength) {
    return `Reason must be at most ${config.maxLength} characters.`
  }
  return undefined
}

/**
 * A presentation-only confirmation surface. Permission checks,
 * re-authentication, mutation handlers, and cache invalidation are supplied by
 * the feature and are never performed by this component.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  children,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  pending = false,
  confirmDisabled = false,
  permissionAllowed = true,
  permissionMessage = 'You are not authorized to perform this action.',
  requiresReauthentication = false,
  reauthenticationMessage = 'Re-authentication is required before this action can be confirmed.',
  reason,
  requireReason = false,
  reasonLabel = 'Reason',
  reasonPlaceholder = 'Enter a reason…',
  onConfirm,
  onCancel,
  onOpenChange,
  returnFocusRef,
  className,
}: ConfirmDialogProps) {
  const reasonConfig = typeof reason === 'object' ? reason : undefined
  const showReason = reason !== undefined || requireReason
  const reasonRequired = requireReason || Boolean(reasonConfig?.required) || reason === true
  const [localReason, setLocalReason] = React.useState(reasonConfig?.defaultValue ?? '')
  const [reasonError, setReasonError] = React.useState<string>()
  const previousFocusRef = React.useRef<HTMLElement | null>(null)
  const reasonId = React.useId()
  const controlId = `confirm-reason-${reasonId.replace(/:/g, '-')}`
  const errorId = reasonError ? `${controlId}-error` : undefined
  const hintId = reasonConfig?.description ? `${controlId}-hint` : undefined
  const currentReason = reasonConfig?.value ?? localReason

  React.useEffect(() => {
    if (open) {
      previousFocusRef.current = returnFocusRef?.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
      return
    }
    const target = returnFocusRef?.current ?? previousFocusRef.current
    if (target && document.contains(target)) target.focus()
  }, [open, returnFocusRef])

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setLocalReason(reasonConfig?.defaultValue ?? '')
      setReasonError(undefined)
      onCancel?.()
    }
    onOpenChange?.(nextOpen)
  }

  const handleReasonChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value
    if (reasonConfig?.value === undefined) setLocalReason(value)
    reasonConfig?.onChange?.(value)
    if (reasonError) setReasonError(undefined)
  }

  const handleConfirm = () => {
    if (!permissionAllowed || requiresReauthentication || pending || confirmDisabled) return
    const error = showReason ? validationMessage(currentReason, reasonConfig, reasonRequired) : undefined
    if (error) {
      setReasonError(error)
      return
    }
    const trimmed = currentReason.trim()
    void onConfirm(showReason ? (trimmed || undefined) : undefined)
  }

  const blockedMessage = !permissionAllowed ? permissionMessage : requiresReauthentication ? reauthenticationMessage : undefined
  const disabled = pending || confirmDisabled || !permissionAllowed || requiresReauthentication

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className={cn('max-h-[min(90vh,44rem)] overflow-y-auto', className)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description ?? 'Review the action before confirming it.'}</DialogDescription>
        </DialogHeader>
        {children}
        {blockedMessage ? (
          <Alert variant="warning" role="status">
            <AlertDescription>{blockedMessage}</AlertDescription>
          </Alert>
        ) : null}
        {showReason ? (
          <div className="space-y-1.5">
            <Label htmlFor={controlId}>
              {reasonConfig?.label ?? reasonLabel}{reasonRequired ? <span aria-hidden="true"> *</span> : null}
            </Label>
            {reasonConfig?.description ? <p id={hintId} className="text-xs text-muted-foreground">{reasonConfig.description}</p> : null}
            <Textarea
              id={controlId}
              value={currentReason}
              onChange={handleReasonChange}
              placeholder={reasonConfig?.placeholder ?? reasonPlaceholder}
              required={reasonRequired}
              minLength={reasonConfig?.minLength}
              maxLength={reasonConfig?.maxLength}
              autoFocus
              aria-invalid={reasonError ? true : undefined}
              aria-describedby={[hintId, errorId].filter(Boolean).join(' ') || undefined}
            />
            {reasonError ? <p id={errorId} role="alert" className="text-xs text-destructive">{reasonError}</p> : null}
          </div>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button type="button" variant="destructive" pending={pending} loadingText="Confirming…" disabled={disabled} onClick={handleConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
