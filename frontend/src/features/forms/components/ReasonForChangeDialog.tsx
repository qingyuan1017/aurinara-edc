import * as React from 'react'
import { Button } from '@/components/ui/button'

interface ReasonForChangeDialogProps {
  open: boolean
  fieldLabel: string
  onConfirm: (reason: string) => void
  onCancel: () => void
}

/**
 * Modal dialog that collects a Reason_For_Change before allowing
 * post-submission edits to clinical data (Requirement 24.3).
 *
 * After a form has been submitted, any field modification must include
 * a textual justification that is recorded in the audit trail.
 */
export function ReasonForChangeDialog({
  open,
  fieldLabel,
  onConfirm,
  onCancel,
}: ReasonForChangeDialogProps) {
  const [reason, setReason] = React.useState('')
  const [error, setError] = React.useState('')
  const textareaRef = React.useRef<HTMLTextAreaElement>(null)

  React.useEffect(() => {
    if (open) {
      setReason('')
      setError('')
      // Focus the textarea when dialog opens
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [open])

  const handleConfirm = () => {
    const trimmed = reason.trim()
    if (!trimmed) {
      setError('A reason for change is required.')
      return
    }
    if (trimmed.length < 3) {
      setError('Reason must be at least 3 characters.')
      return
    }
    onConfirm(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onCancel()
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rfc-title"
      onKeyDown={handleKeyDown}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onCancel}
        aria-hidden="true"
      />

      {/* Dialog content */}
      <div className="relative z-10 w-full max-w-md bg-white rounded-lg shadow-xl p-6 space-y-4 mx-4">
        <h2 id="rfc-title" className="text-lg font-semibold text-gray-900">
          Reason for Change
        </h2>

        <p className="text-sm text-gray-600">
          You are editing <span className="font-medium">{fieldLabel}</span> after submission.
          Please provide a reason for this change.
        </p>

        <div className="space-y-1.5">
          <textarea
            ref={textareaRef}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value)
              if (error) setError('')
            }}
            className={`w-full px-3 py-2 border rounded-md text-sm min-h-[100px] resize-y
              focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
              ${error ? 'border-red-500' : 'border-gray-300'}`}
            placeholder="Enter your reason for making this change..."
            aria-describedby={error ? 'rfc-error' : undefined}
          />
          {error && (
            <p id="rfc-error" className="text-xs text-red-600" role="alert">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <Button variant="outline" onClick={onCancel} type="button">
            Cancel
          </Button>
          <Button onClick={handleConfirm} type="button">
            Confirm Change
          </Button>
        </div>
      </div>
    </div>
  )
}
