import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ConfirmDialog, DetailCard, EmptyState, StatusBadge } from '@/components/patterns'
import {
  ctmsApi,
  getCTMSErrorMessage,
  isCTMSOperationalAttachment,
  isCTMSOperationalAttachmentParent,
  validateCTMSAttachmentMetadata,
  type CTMSAttachment,
  type CTMSAttachmentConstraints,
} from '../api'
import { invalidateCTMSMutation } from '../cache'
import { useCTMSMutation } from '../offline'
import { CTMSMutationFeedback } from './CTMSMutationFeedback'

export interface OperationalAttachmentPanelProps {
  studyId: string
  siteId?: string | null
  objectType: string
  objectId: string
  parentLabel?: string
  attachments?: CTMSAttachment[]
  constraints: CTMSAttachmentConstraints
  className?: string
}

function formatDate(value?: string | null): string {
  if (!value) return 'Not provided'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

function retentionLabel(attachment: CTMSAttachment): string {
  if (attachment.archived_at || attachment.retention_state === 'archived') return 'Archived after retention'
  if (attachment.deleted_at || attachment.retention_state === 'soft_deleted') return 'Deleted and retained for audit'
  if (attachment.retention_state === 'expired') return 'Retention expired'
  if (!attachment.retention_until) return 'Retention period not provided'
  const expiry = new Date(attachment.retention_until)
  if (!Number.isNaN(expiry.getTime()) && expiry.getTime() < Date.now()) return `Retention expired on ${formatDate(attachment.retention_until)}`
  return `Retained until ${formatDate(attachment.retention_until)}`
}

function safeDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/**
 * CTMS-only attachment controls. File bytes never enter React Query: uploads
 * are transient mutation variables and downloads are handled as a Blob.
 */
export function OperationalAttachmentPanel({
  studyId,
  siteId,
  objectType,
  objectId,
  parentLabel = 'operational record',
  attachments = [],
  constraints,
  className,
}: OperationalAttachmentPanelProps) {
  const queryClient = useQueryClient()
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, studyId, siteId ?? undefined)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, studyId, siteId ?? undefined)
  const normalizedObjectType = objectType.trim().replaceAll('-', '_').toLowerCase()
  const parentAllowed = isCTMSOperationalAttachmentParent(objectType) && constraints.allowed_object_types.some((type) => type.trim().replaceAll('-', '_').toLowerCase() === normalizedObjectType)
  const [records, setRecords] = useState<CTMSAttachment[]>(() => attachments.filter(isCTMSOperationalAttachment))
  const [selectedFile, setSelectedFile] = useState<File | undefined>()
  const [validationMessage, setValidationMessage] = useState<string>()
  const [progress, setProgress] = useState(0)
  const [activeAction, setActiveAction] = useState<string>()
  const [confirming, setConfirming] = useState<{ action: 'delete' | 'restore'; attachment: CTMSAttachment }>()
  const lifecycleTriggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    queueMicrotask(() => setRecords(attachments.filter(isCTMSOperationalAttachment)))
  }, [attachments])

  const hiddenMetadataCount = attachments.length - records.length
  const upload = useCTMSMutation<CTMSAttachment, unknown, File>({
    method: 'POST',
    mutationFn: async (file) => {
      setProgress(0)
      const result = await ctmsApi.uploadAttachment({
        studyId,
        objectType,
        objectId,
        file,
        filename: file.name,
        contentType: file.type,
        onProgress: (value) => setProgress(value.percentage),
      })
      if (!isCTMSOperationalAttachment(result) || result.study_id !== studyId || result.object_type !== objectType || result.object_id !== objectId) {
        throw new Error('The server returned an attachment outside the requested CTMS operational record.')
      }
      return result
    },
    onSuccess: async (attachment) => {
      setRecords((current) => current.some((item) => item.id === attachment.id) ? current.map((item) => item.id === attachment.id ? attachment : item) : [...current, attachment])
      setSelectedFile(undefined)
      setValidationMessage(undefined)
      setProgress(100)
      await invalidateCTMSMutation(queryClient, 'attachment', { studyId, siteId: siteId ?? undefined, objectType, objectId })
    },
  })

  const lifecycle = useCTMSMutation<CTMSAttachment, unknown, { action: 'delete' | 'restore'; attachment: CTMSAttachment; reason: string }>({
    method: 'POST',
    mutationFn: ({ action, attachment, reason }) => action === 'delete'
      ? ctmsApi.deleteAttachment(attachment.id, { reason })
      : ctmsApi.restoreAttachment(attachment.id, { reason }),
    onSuccess: async (attachment) => {
      if (isCTMSOperationalAttachment(attachment)) setRecords((current) => current.map((item) => item.id === attachment.id ? attachment : item))
      await invalidateCTMSMutation(queryClient, 'attachment', { studyId, siteId: siteId ?? undefined, objectType, objectId })
      setActiveAction(undefined)
    },
  })

  const validAttachments = useMemo(() => records.filter((attachment) => attachment.study_id === studyId && attachment.object_type === objectType && attachment.object_id === objectId), [objectId, objectType, records, studyId])

  const selectFile = (file: File | undefined) => {
    setSelectedFile(file)
    setProgress(0)
    upload.reset()
    if (!file) {
      setValidationMessage(undefined)
      return
    }
    setValidationMessage(validateCTMSAttachmentMetadata(file, constraints))
  }

  const submitUpload = () => {
    if (!selectedFile || validationMessage || !parentAllowed || !canManage) return
    upload.mutate(selectedFile)
  }

  const runLifecycle = (action: 'delete' | 'restore', attachment: CTMSAttachment) => {
    if (!canManage || lifecycle.isPending) return
    setConfirming({ action, attachment })
  }

  const confirmLifecycle = (reason?: string) => {
    if (!confirming || !reason || !canManage) return
    setActiveAction(`${confirming.action}:${confirming.attachment.id}`)
    lifecycle.mutate({ action: confirming.action, attachment: confirming.attachment, reason })
    setConfirming(undefined)
  }

  const download = async (attachment: CTMSAttachment) => {
    if (!canRead || !isCTMSOperationalAttachment(attachment) || attachment.deleted_at || attachment.archived_at) return
    setActiveAction(`download:${attachment.id}`)
    try {
      const blob = await ctmsApi.downloadAttachment(attachment.id)
      safeDownload(blob, attachment.filename)
    } catch (error) {
      setValidationMessage(getCTMSErrorMessage(error))
    } finally {
      setActiveAction(undefined)
    }
  }

  if (!parentAllowed) {
    return <section className={className} role="note" aria-label="Operational attachments unavailable"><p className="text-sm text-muted-foreground">Operational attachments are not available for this record type. EDC clinical attachments remain outside CTMS.</p></section>
  }

  return (
    <>
      <DetailCard
        title="Operational attachments"
        description={`CTMS-owned evidence associated with this ${parentLabel}. File content is not cached by the frontend.`}
        className={`border-border bg-card ${className ?? ''}`}
        data-testid="operational-attachments"
      >
        <div className="space-y-4">
          {!canRead ? <p role="note" className="text-sm text-warning-foreground">You do not have permission to view attachment metadata for this CTMS record.</p> : null}
          {canRead && hiddenMetadataCount > 0 ? <p role="note" className="text-sm text-warning-foreground">Some attachments are unavailable because their ownership or parent scope could not be verified.</p> : null}
          {canManage ? <div className="space-y-2 rounded-md border border-dashed p-3">
            <label htmlFor={`attachment-file-${objectId}`} className="block text-sm font-medium">Choose an operational attachment</label>
            <Input id={`attachment-file-${objectId}`} type="file" accept={constraints.allowed_content_types.join(',')} onChange={(event) => selectFile(event.target.files?.[0])} aria-describedby={`attachment-help-${objectId}`} />
            <p id={`attachment-help-${objectId}`} className="text-xs text-muted-foreground">Allowed types: {constraints.allowed_content_types.join(', ')}. Maximum size: {Math.ceil(constraints.max_size_bytes / 1024 / 1024)} MB.</p>
            {validationMessage ? <p role="alert" className="text-sm text-destructive">{validationMessage}</p> : null}
            {selectedFile && !validationMessage ? <p className="text-sm text-muted-foreground">Ready to upload: {selectedFile.name} ({selectedFile.size.toLocaleString()} bytes)</p> : null}
            {upload.isPending ? <div role="status" aria-live="polite"><p className="text-sm text-muted-foreground">Uploading… {progress}%</p><progress max="100" value={progress} aria-label="Operational attachment upload progress" className="w-full" /></div> : null}
            <Button type="button" pending={upload.isPending} loadingText="Uploading…" disabled={!selectedFile || Boolean(validationMessage)} onClick={submitUpload}>{upload.isError ? 'Retry upload' : 'Upload operational attachment'}</Button>
            <CTMSMutationFeedback status={upload.status === 'pending' ? 'pending' : upload.isError ? 'error' : upload.isSuccess ? 'success' : 'idle'} action="Upload operational attachment" data={upload.data} error={upload.error} />
          </div> : <p className="text-sm text-muted-foreground">Read-only CTMS access: upload and lifecycle controls are hidden.</p>}
          {canRead && <div className="space-y-3" aria-live="polite">
            {validAttachments.length === 0 ? <EmptyState title="No operational attachments" description="No operational attachments are associated with this record." /> : validAttachments.map((attachment) => {
              const deleted = Boolean(attachment.deleted_at || attachment.archived_at || attachment.retention_state === 'soft_deleted' || attachment.retention_state === 'archived')
              return <article key={attachment.id} className="rounded-md border bg-background p-3" aria-label={`Operational attachment ${attachment.filename}`}>
                <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-medium text-foreground">{attachment.filename}</p><p className="text-xs text-muted-foreground">{attachment.content_type} · {attachment.size_bytes.toLocaleString()} bytes · CTMS Operational_Attachment</p><p className="text-xs text-muted-foreground">Uploaded {formatDate(attachment.uploaded_at)} · {retentionLabel(attachment)}</p></div><StatusBadge status={deleted ? 'Unavailable' : 'Available'} label="Attachment status" /></div>
                <div className="mt-3 flex flex-wrap gap-2">{!deleted && <Button type="button" variant="outline" size="sm" pending={activeAction === `download:${attachment.id}`} loadingText="Downloading…" onClick={() => void download(attachment)}>Download operational attachment</Button>}{canManage ? <Button ref={lifecycleTriggerRef} type="button" variant="outline" size="sm" disabled={lifecycle.isPending} onClick={() => runLifecycle(deleted ? 'restore' : 'delete', attachment)}>{deleted ? 'Restore operational attachment' : 'Delete operational attachment'}</Button> : null}</div>
              </article>
            })}
          </div>}
          <CTMSMutationFeedback status={lifecycle.status === 'pending' ? 'pending' : lifecycle.isError ? 'error' : lifecycle.isSuccess ? 'success' : 'idle'} action="Update operational attachment" data={lifecycle.data} error={lifecycle.error} />
        </div>
      </DetailCard>
      <ConfirmDialog
        open={Boolean(confirming)}
        title={confirming?.action === 'restore' ? 'Confirm operational attachment restore' : 'Confirm operational attachment deletion'}
        description="This CTMS-owned attachment action is recorded for audit. EDC clinical attachments remain outside CTMS."
        confirmLabel={confirming?.action === 'restore' ? 'Confirm restore' : 'Confirm delete'}
        pending={lifecycle.isPending}
        requireReason
        reason={{ label: confirming?.action === 'restore' ? 'Restore reason' : 'Delete reason', description: 'A reason is required and is sent to the CTMS API for audit.', maxLength: 2000 }}
        onConfirm={confirmLifecycle}
        onCancel={() => setConfirming(undefined)}
        onOpenChange={(open) => { if (!open) setConfirming(undefined) }}
        returnFocusRef={lifecycleTriggerRef}
      />
    </>
  )
}
