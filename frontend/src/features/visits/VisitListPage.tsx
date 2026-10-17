import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, getApiErrorMessage } from '@/lib/api'
import { ConfirmDialog, DataTableShell, OwnershipBadge, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { AddVisitDialog } from './AddVisitDialog'

interface Visit { id: string; name: string; visit_date: string | null; window_status: string | null; status: string; is_user_added: boolean }

export function VisitListPage({ subjectId }: { subjectId: string }) {
  const client = useQueryClient(); const canEnter = usePermission(PERMISSIONS.FORM_ENTER); const [recordingVisit, setRecordingVisit] = useState<Visit | null>(null); const [recordedDate, setRecordedDate] = useState(''); const [incorrectVisit, setIncorrectVisit] = useState<Visit | null>(null)
  const visits = useQuery({ queryKey: ['visits', subjectId], queryFn: async () => (await api.get<Visit[]>(`/subjects/${subjectId}/visits`)).data })
  const update = useMutation({ mutationFn: ({ id, action, body }: { id: string; action: string; body?: object }) => action === 'missed' ? api.post(`/visits/${id}/mark-missed`) : api.patch(`/visits/${id}`, body), onSuccess: () => client.invalidateQueries({ queryKey: ['visits', subjectId] }) })
  const markAddedInError = useMutation({ mutationFn: ({ id, reason }: { id: string; reason: string }) => api.post(`/visits/${id}/mark-added-in-error`, { reason }), onSuccess: async () => { setIncorrectVisit(null); await Promise.all([client.invalidateQueries({ queryKey: ['visits', subjectId] }), client.invalidateQueries({ queryKey: ['casebook', subjectId] })]) } })
  const items = visits.data ?? []
  return <PageContainer><PageHeader title="Visits" description="Visit instances for this subject." ownership={<OwnershipBadge owner="EDC" />} actions={canEnter ? <AddVisitDialog subjectId={subjectId} /> : undefined} />
    <DataTableShell label="visits" loading={visits.isLoading} error={Boolean(visits.error)} errorMessage="Visits could not be loaded." empty={items.length === 0} emptyTitle="No visits found" emptyDescription="No visit instances are available for this subject." onRetry={() => void visits.refetch()}>
      <Table><TableHeader><TableRow>{['Visit', 'Date', 'Window', 'Status', 'Actions'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{items.map((item) => <TableRow key={item.id}><TableCell className="font-medium">{item.name}</TableCell><TableCell>{item.visit_date ?? '—'}</TableCell><TableCell>{item.window_status ?? '—'}</TableCell><TableCell><StatusBadge status={item.status} label="visit status" /></TableCell><TableCell><div className="flex flex-wrap gap-2">{canEnter && item.status !== 'missed' && item.status !== 'completed' && item.status !== 'added_in_error' ? <><Button size="sm" variant="outline" onClick={() => { setRecordingVisit(item); setRecordedDate(item.visit_date ?? '') }}>Record date</Button><Button size="sm" variant="destructive" onClick={() => update.mutate({ id: item.id, action: 'missed' })} disabled={update.isPending}>Mark missed</Button>{item.is_user_added ? <Button size="sm" variant="outline" onClick={() => setIncorrectVisit(item)}>Added in error</Button> : null}</> : null}</div></TableCell></TableRow>)}</TableBody></Table>
    </DataTableShell>
    <Dialog open={Boolean(recordingVisit)} onOpenChange={(open) => { if (!open) setRecordingVisit(null) }}><DialogContent><DialogHeader><DialogTitle>Record visit date</DialogTitle><DialogDescription>Record the date for {recordingVisit?.name}.</DialogDescription></DialogHeader><div className="space-y-1.5"><Label htmlFor="recorded-visit-date">Visit date</Label><Input id="recorded-visit-date" type="date" autoFocus value={recordedDate} onChange={(event) => setRecordedDate(event.target.value)} /></div><DialogFooter><Button type="button" variant="outline" onClick={() => setRecordingVisit(null)}>Cancel</Button><Button type="button" onClick={() => { if (recordingVisit && recordedDate) { update.mutate({ id: recordingVisit.id, action: 'date', body: { visit_date: recordedDate } }); setRecordingVisit(null) } }} disabled={!recordedDate || update.isPending} pending={update.isPending} loadingText="Recording…">Record date</Button></DialogFooter></DialogContent></Dialog>
    <ConfirmDialog open={Boolean(incorrectVisit)} title="Mark visit as added in error?" description={<>This keeps <strong>{incorrectVisit?.name}</strong> in the audit history but prevents further data entry. Visits with clinical data cannot be marked this way.</>} confirmLabel="Mark added in error" pending={markAddedInError.isPending} reason={{ label: 'Reason', required: true, maxLength: 1000, placeholder: 'Explain why this visit was added by mistake…' }} onConfirm={(reason) => { if (incorrectVisit && reason) markAddedInError.mutate({ id: incorrectVisit.id, reason }) }} onOpenChange={(open) => { if (!open) { setIncorrectVisit(null); markAddedInError.reset() } }}>
      {markAddedInError.isError ? <Alert variant="destructive" role="alert"><AlertDescription>{getApiErrorMessage(markAddedInError.error, 'The visit could not be marked as added in error.')}</AlertDescription></Alert> : null}
    </ConfirmDialog>
  </PageContainer>
}
