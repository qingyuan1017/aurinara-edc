import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import { DataTableShell, MetricCard, OwnershipBadge, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

interface Subject { id: string; subject_number: string; site_id: string; status: string }
interface CasebookForm { form_instance_id: string | null; name: string | null; status: string }
interface CasebookVisit { name: string | null; forms: CasebookForm[] }
interface Casebook { visits: CasebookVisit[] }
interface WorkItem extends CasebookForm { subject_id: string; subject_number: string; visit_name: string; is_verified?: boolean; is_reviewed?: boolean }

async function loadWorkItems(studyId: string): Promise<WorkItem[]> {
  const subjects = (await api.get<PaginatedResponse<Subject>>(`/studies/${studyId}/subjects`, { params: { page: 1, page_size: 100 } })).data.items
  const casebooks = await Promise.all(subjects.map(async (subject) => ({ subject, casebook: (await api.get<Casebook>(`/subjects/${subject.id}/casebook`)).data })))
  return casebooks.flatMap(({ subject, casebook }) => casebook.visits.flatMap((visit) => visit.forms.filter((form) => form.form_instance_id).map((form) => ({ ...form, subject_id: subject.id, subject_number: subject.subject_number, visit_name: visit.name ?? 'Visit' }))))
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const percentage = total ? Math.round((done / total) * 100) : 0
  return <div aria-label={`${done} of ${total} complete`} role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}><div className="flex justify-between text-xs text-muted-foreground"><span>{done} of {total} complete</span><span>{percentage}%</span></div><div className="mt-2 h-2 rounded-full bg-muted"><div className="h-2 rounded-full bg-primary" style={{ width: `${percentage}%` }} /></div></div>
}

export function SDVWorklistPage({ studyId }: { studyId: string }) {
  const client = useQueryClient(); const [filter, setFilter] = useState('all'); const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const progress = useQuery({ queryKey: ['sdv-progress', studyId], queryFn: async () => (await api.get<{ verified: number; not_verified: number }>(`/studies/${studyId}/sdv-progress`)).data })
  const items = useQuery({ queryKey: ['sdv-worklist', studyId], queryFn: () => loadWorkItems(studyId) })
  const action = useMutation({ mutationFn: ({ id, verified }: { id: string; verified: boolean }) => api.post(`/form-instances/${id}/${verified ? 'unsdv' : 'sdv'}`), onSuccess: (_data, variables) => { setOverrides((current) => ({ ...current, [variables.id]: !variables.verified })); client.invalidateQueries({ queryKey: ['sdv-progress', studyId] }) } })
  const rows = useMemo(() => (items.data ?? []).map((item) => ({ ...item, is_verified: overrides[item.form_instance_id ?? ''] ?? item.is_verified })).filter((item) => filter === 'all' || (filter === 'pending' ? !item.is_verified : item.is_verified)), [items.data, filter, overrides])
  return <PermissionGuard permission={PERMISSIONS.SDV_MANAGE} studyId={studyId}><PageContainer><PageHeader title="SDV worklist" description="Track source-data verification across form instances." ownership={<OwnershipBadge owner="EDC" />} /><div className="grid gap-4 md:grid-cols-3"><MetricCard label="Verified" value={progress.data?.verified ?? 0} status={<StatusBadge status="verified" label="SDV status" />} /><MetricCard label="Not verified" value={progress.data?.not_verified ?? 0} status={<StatusBadge status="pending" label="SDV status" />} /><MetricCard label="Worklist" value={<ProgressBar done={items.data?.filter((item) => item.is_verified).length ?? 0} total={items.data?.length ?? 0} />} /></div><PageToolbar label="SDV filters"><label className="flex items-center gap-2 text-sm">Filter<select aria-label="SDV filter" value={filter} onChange={(event) => setFilter(event.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="all">All forms</option><option value="pending">Not verified</option><option value="verified">Verified</option></select></label></PageToolbar><WorklistTable items={rows} kind="sdv" onToggle={(item) => action.mutate({ id: item.form_instance_id!, verified: Boolean(item.is_verified) })} isPending={action.isPending} loading={items.isLoading} error={Boolean(items.error)} /></PageContainer></PermissionGuard>
}

export function ReviewWorklistPage({ studyId }: { studyId: string }) {
  const client = useQueryClient(); const [filter, setFilter] = useState('all'); const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const progress = useQuery({ queryKey: ['review-progress', studyId], queryFn: async () => (await api.get<{ reviewed: number; not_reviewed: number }>(`/studies/${studyId}/review-progress`)).data })
  const items = useQuery({ queryKey: ['review-worklist', studyId], queryFn: () => loadWorkItems(studyId) })
  const action = useMutation({ mutationFn: ({ id, reviewed }: { id: string; reviewed: boolean }) => api.post(`/form-instances/${id}/${reviewed ? 'unreview' : 'review'}`), onSuccess: (_data, variables) => { setOverrides((current) => ({ ...current, [variables.id]: !variables.reviewed })); client.invalidateQueries({ queryKey: ['review-progress', studyId] }) } })
  const rows = useMemo(() => (items.data ?? []).map((item) => ({ ...item, is_reviewed: overrides[item.form_instance_id ?? ''] ?? item.is_reviewed })).filter((item) => filter === 'all' || (filter === 'pending' ? !item.is_reviewed : item.is_reviewed)), [items.data, filter, overrides])
  return <PermissionGuard permission={PERMISSIONS.REVIEW_MANAGE} studyId={studyId}><PageContainer><PageHeader title="Clinical review worklist" description="Review submitted forms and track outstanding clinical review." ownership={<OwnershipBadge owner="EDC" />} /><div className="grid gap-4 md:grid-cols-3"><MetricCard label="Reviewed" value={progress.data?.reviewed ?? 0} status={<StatusBadge status="reviewed" label="Review status" />} /><MetricCard label="Not reviewed" value={progress.data?.not_reviewed ?? 0} status={<StatusBadge status="pending" label="Review status" />} /><MetricCard label="Worklist" value={<ProgressBar done={items.data?.filter((item) => item.is_reviewed).length ?? 0} total={items.data?.length ?? 0} />} /></div><PageToolbar label="Review filters"><label className="flex items-center gap-2 text-sm">Filter<select aria-label="Review filter" value={filter} onChange={(event) => setFilter(event.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="all">All forms</option><option value="pending">Not reviewed</option><option value="reviewed">Reviewed</option></select></label></PageToolbar><WorklistTable items={rows} kind="review" onToggle={(item) => action.mutate({ id: item.form_instance_id!, reviewed: Boolean(item.is_reviewed) })} isPending={action.isPending} loading={items.isLoading} error={Boolean(items.error)} /></PageContainer></PermissionGuard>
}

function WorklistTable({ items, kind, onToggle, isPending, loading, error }: { items: WorkItem[]; kind: 'sdv' | 'review'; onToggle: (item: WorkItem) => void; isPending: boolean; loading: boolean; error: boolean }) {
  return <DataTableShell label={`${kind} worklist`} loading={loading} error={error} errorMessage={`Unable to load the ${kind} worklist.`} empty={items.length === 0} emptyTitle={`No ${kind} forms`} emptyDescription="No forms match this worklist filter."><Table><TableHeader><TableRow>{['Subject', 'Visit', 'Form', 'Form status', 'Workflow', 'Action'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{items.map((item) => { const done = kind === 'sdv' ? item.is_verified : item.is_reviewed; return <TableRow key={item.form_instance_id}><TableCell><a className="font-medium text-primary hover:underline" href={`/subjects/${item.subject_id}/casebook`}>{item.subject_number}</a></TableCell><TableCell>{item.visit_name}</TableCell><TableCell><a className="text-primary hover:underline" href={`/subjects/${item.subject_id}/forms/${item.form_instance_id}`}>{item.name ?? 'Form'}</a></TableCell><TableCell><StatusBadge status={item.status} label="form status" /></TableCell><TableCell><StatusBadge status={done ? (kind === 'sdv' ? 'verified' : 'reviewed') : 'pending'} label={`${kind} status`} /></TableCell><TableCell><Button size="sm" variant={done ? 'outline' : 'default'} onClick={() => onToggle(item)} disabled={isPending}>{done ? `Clear ${kind === 'sdv' ? 'SDV' : 'review'}` : `Mark ${kind === 'sdv' ? 'verified' : 'reviewed'}`}</Button></TableCell></TableRow> })}</TableBody></Table></DataTableShell>
}
