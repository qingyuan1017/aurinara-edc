import * as React from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

interface ReasonForChangeDialogProps { open: boolean; fieldLabel: string; onConfirm: (reason: string) => void; onCancel: () => void }

/** Accessible shared dialog for the required EDC Reason_For_Change audit value. */
export function ReasonForChangeDialog({ open, fieldLabel, onConfirm, onCancel }: ReasonForChangeDialogProps) {
  const [reason, setReason] = React.useState('')
  const [error, setError] = React.useState('')
  const reasonId = React.useId()
  const errorId = `${reasonId}-error`

  const handleCancel = () => {
    setReason('')
    setError('')
    onCancel()
  }

  const handleConfirm = () => {
    const trimmed = reason.trim()
    if (!trimmed) { setError('A reason for change is required.'); return }
    if (trimmed.length < 3) { setError('Reason must be at least 3 characters.'); return }
    onConfirm(trimmed)
    setReason('')
    setError('')
  }

  return <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) handleCancel() }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Reason for Change</DialogTitle>
        <DialogDescription>You are editing <span className="font-medium text-foreground">{fieldLabel}</span> after submission. Please provide a reason for this change.</DialogDescription>
      </DialogHeader>
      <div className="space-y-1.5">
        <Label htmlFor={reasonId}>Reason for change</Label>
        <Textarea id={reasonId} value={reason} onChange={(event) => { setReason(event.target.value); if (error) setError('') }} placeholder="Enter your reason for making this change..." autoFocus aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} />
        {error ? <Alert variant="destructive" className="p-3" role="alert"><AlertDescription id={errorId}>{error}</AlertDescription></Alert> : null}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={handleCancel} type="button">Cancel</Button>
        <Button onClick={handleConfirm} type="button">Confirm Change</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
