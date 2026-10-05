import * as React from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

export interface PVHistoryDialogProps {
  title: string
  description?: string
  triggerLabel: string
  children: React.ReactNode
  triggerDisabled?: boolean
}

/**
 * Renders PV audit or narrative history inside a dialog while the originating
 * safety status view stays mounted and visible (Requirement 19.5). The trigger
 * button and the status view it belongs to are never unmounted when the dialog
 * opens.
 */
export function PVHistoryDialog({
  title,
  description,
  triggerLabel,
  children,
  triggerDisabled,
}: PVHistoryDialogProps) {
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <Button type="button" variant="outline" size="sm" disabled={triggerDisabled} onClick={() => setOpen(true)}>
        {triggerLabel}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description ? <DialogDescription>{description}</DialogDescription> : null}
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto">{children}</div>
        </DialogContent>
      </Dialog>
    </>
  )
}
