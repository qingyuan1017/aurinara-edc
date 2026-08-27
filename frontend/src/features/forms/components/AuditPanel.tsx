import * as React from 'react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

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

/**
 * Side panel showing the audit trail for a form instance.
 * Displayed as a sheet overlay so primary clinical status remains visible (Requirement 24.5).
 */
export function AuditPanel({ formInstanceId, open, onClose }: AuditPanelProps) {
  const [entries, setEntries] = React.useState<AuditEntry[]>([])
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    if (!open || !formInstanceId) return

    let cancelled = false
    setLoading(true)
    setError('')

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

    return () => { cancelled = true }
  }, [open, formInstanceId])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-labelledby="audit-panel-title"
      onKeyDown={handleKeyDown}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Side panel */}
      <div className="relative z-10 w-full max-w-md bg-white shadow-xl flex flex-col h-full overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 id="audit-panel-title" className="text-lg font-semibold text-gray-900">
            Audit Trail
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
            aria-label="Close audit panel"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading && (
            <div className="text-center text-sm text-gray-500 py-8">Loading audit trail...</div>
          )}

          {error && (
            <div className="text-center text-sm text-red-600 py-8">{error}</div>
          )}

          {!loading && !error && entries.length === 0 && (
            <div className="text-center text-sm text-gray-500 py-8">No audit entries yet.</div>
          )}

          {!loading && !error && entries.map((entry) => (
            <AuditEntryCard key={entry.id} entry={entry} />
          ))}
        </div>
      </div>
    </div>
  )
}

function AuditEntryCard({ entry }: { entry: AuditEntry }) {
  const ts = new Date(entry.timestamp)
  const formattedTime = ts.toLocaleString()

  return (
    <div className="border rounded-md p-3 text-sm space-y-1.5 bg-gray-50">
      <div className="flex items-center justify-between">
        <span className={cn(
          'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
          entry.action === 'create' && 'bg-green-100 text-green-800',
          entry.action === 'update' && 'bg-blue-100 text-blue-800',
          entry.action === 'submit' && 'bg-purple-100 text-purple-800',
          entry.action === 'reopen' && 'bg-yellow-100 text-yellow-800',
          !['create', 'update', 'submit', 'reopen'].includes(entry.action) && 'bg-gray-100 text-gray-800',
        )}>
          {entry.action}
        </span>
        <span className="text-xs text-gray-500">{formattedTime}</span>
      </div>

      <div className="text-xs text-gray-600">
        by <span className="font-medium">{entry.actor_email}</span>
      </div>

      {entry.field_name && (
        <div className="text-xs">
          <span className="text-gray-500">Field:</span>{' '}
          <span className="font-medium">{entry.field_name}</span>
        </div>
      )}

      {(entry.old_value !== undefined || entry.new_value !== undefined) && (
        <div className="text-xs space-x-2">
          {entry.old_value !== undefined && (
            <span>
              <span className="text-gray-500">From:</span>{' '}
              <span className="line-through text-red-700">{entry.old_value || '(empty)'}</span>
            </span>
          )}
          {entry.new_value !== undefined && (
            <span>
              <span className="text-gray-500">To:</span>{' '}
              <span className="text-green-700">{entry.new_value || '(empty)'}</span>
            </span>
          )}
        </div>
      )}

      {entry.reason && (
        <div className="text-xs">
          <span className="text-gray-500">Reason:</span>{' '}
          <span className="italic">{entry.reason}</span>
        </div>
      )}
    </div>
  )
}
