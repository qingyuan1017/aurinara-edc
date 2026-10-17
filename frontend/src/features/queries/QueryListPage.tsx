import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { DataTableShell, OwnershipBadge, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

interface QueryItem { id: string; target_type: string; target_id: string; text: string; status: string; query_type: string; assigned_role?: string | null; subject_id?: string | null; subject_label?: string | null; site_label?: string | null; age_days: number; created_at: string }
interface QueryHistoryItem { id: string; entity_id: string; action: string; actor_email?: string | null; timestamp: string; old_value?: string | null; new_value?: string | null; reason?: string | null }
const STATUSES = ['Open', 'Answered', 'Closed', 'Reopened', 'Cancelled']

export function QueryListPage({ studyId }: { studyId: string }) {
  const client = useQueryClient()
  const canCreate = usePermission(PERMISSIONS.QUERY_CREATE)
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [text, setText] = useState('')
  const [targetId, setTargetId] = useState('')
  const [targetType, setTargetType] = useState('Subject')
  const [assignedRole, setAssignedRole] = useState('')
  const [error, setError] = useState('')
  const query = useQuery({ queryKey: ['queries', studyId, status, type], queryFn: async () => (await api.get<PaginatedResponse<QueryItem>>(`/studies/${studyId}/queries`, { params: { page: 1, page_size: 50, ...(status ? { status } : {}), ...(type ? { query_type: type } : {}) } })).data })
  const create = useMutation({ mutationFn: () => api.post(`/studies/${studyId}/queries`, { target_type: targetType, target_id: targetId, text, assigned_role: assignedRole || null }), onSuccess: () => { client.invalidateQueries({ queryKey: ['queries', studyId] }); setShowCreate(false); setText(''); setTargetId(''); setAssignedRole('') }, onError: () => setError('Could not create query. Check the target ID and permission.') })
  const action = useMutation({ mutationFn: ({ id, verb }: { id: string; verb: string }) => api.post(`/queries/${id}/${verb}`), onSuccess: () => client.invalidateQueries({ queryKey: ['queries', studyId] }) })
  const items = query.data?.items ?? []

  return <PageContainer>
    <PageHeader title="Query inbox" description="Track, respond to, and resolve data clarification queries." actions={canCreate ? <Button onClick={() => { setError(''); setShowCreate(true) }}>New query</Button> : undefined} ownership={<OwnershipBadge owner="EDC" />} />
    <PageToolbar label="Query filters">
      <Label className="flex items-center gap-2 text-sm">Status<select aria-label="Query status filter" value={status} onChange={(event) => setStatus(event.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="">All statuses</option>{STATUSES.map((item) => <option key={item}>{item}</option>)}</select></Label>
      <Label className="flex items-center gap-2 text-sm">Origin<select aria-label="Query type filter" value={type} onChange={(event) => setType(event.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="">All origins</option><option value="manual">manual</option><option value="system">system</option></select></Label>
    </PageToolbar>
    <DataTableShell label="queries" state={query.isLoading ? 'loading' : query.error ? 'error' : items.length ? undefined : 'empty'} errorMessage="Queries could not be loaded." emptyTitle="No queries found" emptyDescription="No queries match the selected filters." onRetry={() => void query.refetch()}>
      <Table><TableHeader><TableRow>{['Query', 'Context', 'Target', 'Origin', 'Status', 'Assigned role', 'Age', 'Actions'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{items.map((item) => <TableRow key={item.id}><TableCell className="max-w-sm"><a href={`/studies/${encodeURIComponent(studyId)}/edc/queries/${encodeURIComponent(item.id)}`} className="font-medium text-primary hover:underline">{item.text}</a><span className="block text-xs text-muted-foreground">{item.id.slice(0, 8)}</span></TableCell><TableCell>{item.subject_label ?? '—'}<span className="block text-xs text-muted-foreground">{item.site_label ?? '—'}</span></TableCell><TableCell>{item.target_type}<span className="block text-xs text-muted-foreground">{item.target_id.slice(0, 8)}</span></TableCell><TableCell>{item.query_type}</TableCell><TableCell><StatusBadge label="query status" status={item.status} /></TableCell><TableCell className="text-muted-foreground">{item.assigned_role ?? '—'}</TableCell><TableCell>{item.age_days}d</TableCell><TableCell><div className="flex flex-wrap gap-2">{(item.status === 'Open' || item.status === 'Reopened') ? <Button size="sm" variant="outline" onClick={() => action.mutate({ id: item.id, verb: 'close' })} disabled={action.isPending}>Close</Button> : null}{item.status === 'Closed' ? <Button size="sm" variant="outline" onClick={() => action.mutate({ id: item.id, verb: 'reopen' })} disabled={action.isPending}>Reopen</Button> : null}</div></TableCell></TableRow>)}</TableBody></Table>
    </DataTableShell>
    <Dialog open={showCreate} onOpenChange={(open) => { setShowCreate(open); if (!open) setError('') }}>
      <DialogContent><DialogHeader><DialogTitle>New query</DialogTitle><DialogDescription>Create a query against an existing EDC clinical object.</DialogDescription></DialogHeader>
        <form onSubmit={(event) => { event.preventDefault(); create.mutate() }} className="space-y-4">
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <div className="space-y-1.5"><Label htmlFor="query-target-type">Affected object</Label><select id="query-target-type" value={targetType} onChange={(event) => setTargetType(event.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"><option>Subject</option><option>Visit_Instance</option><option>Form_Instance</option><option>Form_Record</option><option>Field</option></select></div>
          <div className="space-y-1.5"><Label htmlFor="query-target-id">Affected object ID</Label><Input id="query-target-id" required value={targetId} onChange={(event) => setTargetId(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="query-assigned-role">Assigned role (optional)</Label><Input id="query-assigned-role" value={assignedRole} onChange={(event) => setAssignedRole(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="query-text">Describe the issue</Label><Textarea id="query-text" required value={text} onChange={(event) => setText(event.target.value)} className="h-28" /></div>
          <DialogFooter><Button type="button" variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button><Button type="submit" pending={create.isPending} loadingText="Creating…">Create</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </PageContainer>
}

export function QueryHistoryPage({ studyId }: { studyId: string }) {
  const query = useQuery({ queryKey: ['query-history', studyId], queryFn: async () => (await api.get<PaginatedResponse<QueryHistoryItem>>(`/studies/${studyId}/queries/history`, { params: { page: 1, page_size: 100 } })).data })
  const items = query.data?.items ?? []
  return <PageContainer wide><PageHeader title="Query History" description="Immutable, paginated query lifecycle history for the authorized study scope." ownership={<OwnershipBadge owner="EDC" />} /><DataTableShell label="query history" state={query.isLoading ? 'loading' : query.error ? 'error' : items.length ? undefined : 'empty'} errorMessage="Query history could not be loaded." emptyTitle="No query history" emptyDescription="No query lifecycle events are available." onRetry={() => void query.refetch()}><Table><TableHeader><TableRow>{['Time', 'Query', 'Action', 'Actor', 'Change', 'Reason'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{items.map((item) => <TableRow key={item.id}><TableCell>{new Date(item.timestamp).toLocaleString()}</TableCell><TableCell>{item.entity_id.slice(0, 8)}</TableCell><TableCell>{item.action}</TableCell><TableCell>{item.actor_email ?? 'System'}</TableCell><TableCell className="max-w-sm">{item.old_value ?? '—'} → {item.new_value ?? '—'}</TableCell><TableCell>{item.reason ?? '—'}</TableCell></TableRow>)}</TableBody></Table></DataTableShell></PageContainer>
}
