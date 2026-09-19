import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { DataTableShell, ErrorState, LoadingState, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'

interface StudySummary {
  id: string
  study_code: string
  title: string
  phase?: string | null
}

export interface StudyVersion {
  id: string
  study_id: string
  version_number: string
  status: 'draft' | 'published' | string
  amendment_reason?: string | null
  amended_from_version_id?: string | null
  published_at?: string | null
  published_by?: string | null
  created_at: string
}

function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string } } } })?.response
  return response?.data?.error?.message ?? response?.data?.detail ?? fallback
}

function formatDate(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

/**
 * Study version history and amendment workflow.
 *
 * Published versions are presented as retained, read-only history. New
 * amendments are created only through the Study_Version_Service amendment
 * endpoint, which assigns the next version number and records the source
 * version and reason server-side.
 */
export function StudyVersioningPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.STUDY_CONFIGURE, studyId)
  const canPublish = usePermission(PERMISSIONS.VERSION_PUBLISH, studyId)
  const [showAmendmentForm, setShowAmendmentForm] = useState(false)
  const [reason, setReason] = useState('')
  const [validationError, setValidationError] = useState('')
  const [message, setMessage] = useState('')

  const studyQuery = useQuery({
    queryKey: ['study', studyId],
    queryFn: async () => (await api.get<StudySummary>(`/studies/${studyId}`)).data,
  })

  const versionsQuery = useQuery({
    queryKey: ['study-versions', studyId],
    queryFn: async () => (await api.get<StudyVersion[]>(`/studies/${studyId}/versions`)).data,
  })

  const versions = versionsQuery.data ?? []
  const versionsById = useMemo(() => new Map((versionsQuery.data ?? []).map((version) => [version.id, version])), [versionsQuery.data])
  const latestPublished = [...versions].reverse().find((version) => version.status === 'published')
  const openDraft = versions.find((version) => version.status === 'draft')

  const amendment = useMutation({
    mutationFn: async () => {
      const trimmedReason = reason.trim()
      if (!trimmedReason) throw new Error('An amendment reason is required.')
      return api.post<StudyVersion>(`/studies/${studyId}/amend`, { reason: trimmedReason })
    },
    onSuccess: ({ data }) => {
      queryClient.invalidateQueries({ queryKey: ['study-versions', studyId] })
      queryClient.invalidateQueries({ queryKey: ['study', studyId] })
      setShowAmendmentForm(false)
      setReason('')
      setValidationError('')
      setMessage(`Draft version ${data.version_number} created.`)
    },
    onError: (error: unknown) => {
      setValidationError(getApiErrorMessage(error, 'Could not create the amendment.'))
      setMessage('')
    },
  })

  const publish = useMutation({
    mutationFn: (versionId: string) => api.post<StudyVersion>(`/versions/${versionId}/publish`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['study-versions', studyId] })
      queryClient.invalidateQueries({ queryKey: ['study', studyId] })
      setMessage('Study version published. Its metadata is now read-only.')
      setValidationError('')
    },
    onError: (error: unknown) => {
      setValidationError(getApiErrorMessage(error, 'Could not publish the study version.'))
      setMessage('')
    },
  })

  if (studyQuery.isLoading || versionsQuery.isLoading) return <PageContainer><LoadingState label="study versions" /></PageContainer>
  if (studyQuery.error || versionsQuery.error || !studyQuery.data) return <PageContainer><ErrorState message="Study versions are unavailable." /></PageContainer>

  const study = studyQuery.data

  return (
    <PageContainer wide>
      <PageHeader
        title="Study versioning"
        description={`${study.study_code} · ${study.title}${study.phase ? ` · Phase ${study.phase}` : ''}`}
        breadcrumbs={<a href={`/studies/${studyId}`} className="text-primary hover:underline">← Back to study</a>}
        actions={canConfigure ? (
          <Button
            type="button"
            onClick={() => { setShowAmendmentForm(true); setValidationError(''); setMessage('') }}
            disabled={Boolean(openDraft) || amendment.isPending}
            title={openDraft ? 'Resolve the existing draft before creating another amendment.' : undefined}
          >
            Create amendment
          </Button>
        ) : null}
      />

      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {validationError ? <Alert variant="destructive" className="mb-4"><AlertDescription>{validationError}</AlertDescription></Alert> : null}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Version history</CardTitle>
              <CardDescription>Published versions remain available for traceability and cannot be edited.</CardDescription>
            </div>
            {latestPublished ? <p className="text-sm text-muted-foreground">Latest published: <span className="font-medium">v{latestPublished.version_number}</span></p> : null}
          </div>
        </CardHeader>
        <CardContent>
          <DataTableShell label="Study version history" empty={!versions.length} emptyTitle="No study versions found." emptyDescription="Study versions will appear here after the study is configured.">
            <Table>
              <caption className="sr-only">Study version history</caption>
              <TableHeader><TableRow>{['Version', 'Status', 'Amendment reason', 'Based on', 'Created', 'Published', 'Actions'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
              <TableBody>{versions.map((version) => {
                const source = version.amended_from_version_id ? versionsById.get(version.amended_from_version_id) : undefined
                return <TableRow key={version.id}>
                  <TableCell className="whitespace-nowrap font-medium">v{version.version_number}</TableCell>
                  <TableCell><StatusBadge status={version.status} label="Version status" /></TableCell>
                  <TableCell className="max-w-xs">{version.amendment_reason || 'Initial study version'}</TableCell>
                  <TableCell>{source ? `v${source.version_number}` : version.amended_from_version_id ? 'Previous published version' : '—'}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatDate(version.created_at)}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatDate(version.published_at)}</TableCell>
                  <TableCell>{canPublish && version.status === 'draft' ? <Button type="button" variant="link" size="sm" pending={publish.isPending} onClick={() => publish.mutate(version.id)}>{publish.isPending ? 'Publishing…' : 'Publish'}</Button> : version.status === 'published' ? <span className="text-sm text-muted-foreground">Read-only</span> : null}</TableCell>
                </TableRow>
              })}</TableBody>
            </Table>
          </DataTableShell>
        </CardContent>
      </Card>

      <Dialog open={showAmendmentForm} onOpenChange={(open) => { setShowAmendmentForm(open); if (!open) { setReason(''); setValidationError('') } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create study amendment</DialogTitle>
            <DialogDescription>A new draft will be created from {latestPublished ? `published version ${latestPublished.version_number}` : 'the latest published version'}. Prior versions are retained.</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setValidationError(''); amendment.mutate() }}>
            <div className="space-y-2"><Label htmlFor="amendment-reason">Amendment reason</Label><Textarea id="amendment-reason" required minLength={1} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Describe the protocol or study configuration change." /></div>
            <DialogFooter><Button type="button" variant="outline" onClick={() => setShowAmendmentForm(false)}>Cancel</Button><Button type="submit" pending={amendment.isPending} loadingText="Creating…">Create draft amendment</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
