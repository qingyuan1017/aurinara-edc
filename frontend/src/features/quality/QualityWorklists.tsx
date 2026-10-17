import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import { DataTableShell, OwnershipBadge, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

interface OperationalStatus {
  data_entry: string
  review: string
  sdv: string
  sdr: string
  active_query_count: number
}

interface WorkItem {
  form_instance_id: string
  subject_id: string
  subject_number: string
  site_name?: string
  visit_name?: string
  form_name: string
  status: OperationalStatus
  workflow: 'review' | 'sdv' | 'sdr'
  workflow_status: string
  sdr_selection_id?: string
}

function useWorklist(studyId: string, workflow: WorkItem['workflow'], status: string) {
  return useQuery({
    queryKey: ['quality-worklist', studyId, workflow, status],
    queryFn: async () => (await api.get<PaginatedResponse<WorkItem>>(`/studies/${studyId}/quality-worklist`, {
      params: { workflow, page: 1, page_size: 100, ...(status !== 'all' ? { status } : {}) },
    })).data,
  })
}

export function SDVWorklistPage({ studyId }: { studyId: string }) {
  const [workflow, setWorkflow] = useState<'sdv' | 'sdr'>('sdv')
  return <QualityWorklist studyId={studyId} workflow={workflow} onWorkflowChange={setWorkflow} />
}

export function ReviewWorklistPage({ studyId }: { studyId: string }) {
  return <QualityWorklist studyId={studyId} workflow="review" />
}

function QualityWorklist({ studyId, workflow, onWorkflowChange }: { studyId: string; workflow: WorkItem['workflow']; onWorkflowChange?: (workflow: 'sdv' | 'sdr') => void }) {
  const client = useQueryClient()
  const [status, setStatus] = useState('all')
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const query = useWorklist(studyId, workflow, status)
  const action = useMutation({
    mutationFn: async (item: WorkItem) => {
      if (workflow === 'review') return api.post(`/form-instances/${item.form_instance_id}/${item.workflow_status === 'Reviewed' ? 'unreview' : 'review'}`)
      if (workflow === 'sdv') return api.post(`/form-instances/${item.form_instance_id}/${item.workflow_status === 'Verified' ? 'unsdv' : 'sdv'}`)
      if (!item.sdr_selection_id) throw new Error('SDR selection is unavailable')
      return api.post(`/sdr-selections/${item.sdr_selection_id}/review`, { status: 'Complete', outcome: 'Reviewed' })
    },
    onSuccess: (_data, item) => {
      const next = workflow === 'review'
        ? (item.workflow_status === 'Reviewed' ? 'Not Reviewed' : 'Reviewed')
        : workflow === 'sdv'
          ? (item.workflow_status === 'Verified' ? 'Not Verified' : 'Verified')
          : 'Complete'
      setOverrides((current) => ({ ...current, [item.form_instance_id]: next }))
      void client.invalidateQueries({ queryKey: ['quality-worklist', studyId] })
    },
  })
  const title = workflow === 'review' ? 'Clinical review worklist' : workflow === 'sdv' ? 'SDV worklist' : 'SDR worklist'
  const managePermission = workflow === 'review' ? PERMISSIONS.REVIEW_MANAGE : workflow === 'sdv' ? PERMISSIONS.SDV_MANAGE : PERMISSIONS.SDR_MANAGE
  const items = (query.data?.items ?? []).map((item) => ({ ...item, workflow_status: overrides[item.form_instance_id] ?? item.workflow_status }))
  const pendingStatus = workflow === 'review' ? 'Not Reviewed' : workflow === 'sdv' ? 'Not Verified' : 'Pending'
  const completeStatus = workflow === 'review' ? 'Reviewed' : workflow === 'sdv' ? 'Verified' : 'Complete'
  return (
    <PermissionGuard permission={managePermission} studyId={studyId}>
      <PageContainer wide>
        <PageHeader title={title} description="Server-filtered quality work, including revision-aware stale decisions." ownership={<OwnershipBadge owner="EDC" />} />
        <PageToolbar label="Quality worklist filters">
          {onWorkflowChange ? <label className="flex items-center gap-2 text-sm">Workflow<select aria-label="Quality workflow" value={workflow} onChange={(event) => onWorkflowChange(event.target.value as 'sdv' | 'sdr')} className="h-10 rounded-md border border-input bg-background px-3"><option value="sdv">SDV</option><option value="sdr">SDR</option></select></label> : null}
          <label className="flex items-center gap-2 text-sm">Status<select aria-label="Quality status" value={status} onChange={(event) => setStatus(event.target.value)} className="h-10 rounded-md border border-input bg-background px-3"><option value="all">All</option><option value={pendingStatus}>Pending</option><option value={completeStatus}>Complete</option><option value="Stale">Stale</option></select></label>
        </PageToolbar>
        <DataTableShell label={title} loading={query.isLoading} error={Boolean(query.error)} errorMessage={`Unable to load ${title.toLowerCase()}.`} empty={!query.isLoading && items.length === 0} emptyTitle="No matching forms" emptyDescription="No authorized forms match the selected workflow status.">
          <Table><TableHeader><TableRow>{['Site', 'Subject', 'Visit', 'Form', 'Entry', 'Workflow', 'Queries', 'Action'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{items.map((item) => <TableRow key={item.form_instance_id}><TableCell>{item.site_name ?? '—'}</TableCell><TableCell>{item.subject_number}</TableCell><TableCell>{item.visit_name ?? '—'}</TableCell><TableCell><a className="text-primary hover:underline" href={`/subjects/${item.subject_id}/forms/${item.form_instance_id}`}>{item.form_name}</a></TableCell><TableCell><StatusBadge status={item.status.data_entry} label="Entry status" /></TableCell><TableCell><StatusBadge status={item.workflow_status} label={`${workflow} status`} /></TableCell><TableCell>{item.status.active_query_count}</TableCell><TableCell><Button size="sm" variant={item.workflow_status === completeStatus ? 'outline' : 'default'} disabled={action.isPending || (workflow === 'sdr' && !item.sdr_selection_id)} onClick={() => action.mutate(item)}>{workflow === 'sdr' ? 'Complete SDR' : item.workflow_status === completeStatus ? `Clear ${workflow === 'sdv' ? 'SDV' : 'review'}` : `Mark ${workflow === 'sdv' ? 'verified' : 'reviewed'}`}</Button></TableCell></TableRow>)}</TableBody></Table>
        </DataTableShell>
      </PageContainer>
    </PermissionGuard>
  )
}
