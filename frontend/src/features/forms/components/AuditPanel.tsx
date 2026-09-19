import * as React from 'react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { EmptyState, ErrorState, LoadingState } from '@/components/patterns'

export interface AuditEntry {
  id: string
  actor_email: string
  action: string
  field_name?: string
  old_value?: string
  new_value?: string
  reason?: string
  timestamp: string
  request_id?: string
}

interface AuditPanelProps {
  formInstanceId: string
  open: boolean
  onClose: () => void
}

/** Side panel showing the audit trail for a form instance. */
export function AuditPanel({ formInstanceId, open, onClose }: AuditPanelProps) {
  const [entries, setEntries] = React.useState<AuditEntry[]>([])
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (!open || !formInstanceId) return

    let cancelled = false
    const resetTimer = window.setTimeout(() => {
      if (!cancelled) {
        setLoading(true)
        setError('')
      }
    }, 0)

    api
      .get<{ items: AuditEntry[] }>(`/form-instances/${formInstanceId}/audit`)
      .then(({ data }) => {
        if (!cancelled) setEntries(data.items ?? [])
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load audit trail.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      window.clearTimeout(resetTimer)
    }
  }, [open, formInstanceId])

  if (!open) return null

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <SheetContent side="right" className="w-full overflow-hidden sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Audit Trail</SheetTitle>
          <SheetDescription>Immutable activity recorded for this form instance.</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-2">
          {loading ? <LoadingState label="audit trail" className="border-0 p-0 shadow-none" /> : null}
          {error ? <ErrorState message={error} /> : null}
          {!loading && !error && entries.length === 0 ? <EmptyState title="No audit entries yet." description="Recorded form activity will appear here." /> : null}
          {!loading && !error ? entries.map((entry) => <AuditEntryCard key={entry.id} entry={entry} />) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function AuditEntryCard({ entry }: { entry: AuditEntry }) {
  const formattedTime = new Date(entry.timestamp).toLocaleString()
  const variant = entry.action === 'create' || entry.action === 'submit' ? 'success' : entry.action === 'reopen' ? 'warning' : entry.action === 'update' ? 'info' : 'secondary'

  return (
    <Card>
      <CardContent className="space-y-1.5 p-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <Badge variant={variant}>{entry.action}</Badge>
          <span className="text-xs text-muted-foreground">{formattedTime}</span>
        </div>
        <div className="text-xs text-muted-foreground">by <span className="font-medium text-foreground">{entry.actor_email}</span></div>
        {entry.field_name ? <div className="text-xs"><span className="text-muted-foreground">Field:</span>{' '}<span className="font-medium">{entry.field_name}</span></div> : null}
        {(entry.old_value !== undefined || entry.new_value !== undefined) ? <div className="space-x-2 text-xs">
          {entry.old_value !== undefined ? <span><span className="text-muted-foreground">From:</span>{' '}<span className="line-through text-destructive">{entry.old_value || '(empty)'}</span></span> : null}
          {entry.new_value !== undefined ? <span><span className="text-muted-foreground">To:</span>{' '}<span className="text-success">{entry.new_value || '(empty)'}</span></span> : null}
        </div> : null}
        {entry.reason ? <div className="text-xs"><span className="text-muted-foreground">Reason:</span>{' '}<span className="italic">{entry.reason}</span></div> : null}
      </CardContent>
    </Card>
  )
}
