import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { DataTableShell, DetailCard, PageContainer, PageHeader } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { ctmsApi, ctmsKeys } from './api'
import { useStudyWorkspaceHealth, useStudyWorkspaceList, useStudyWorkspaceSummary, useStudyWorkspaceTransition, type StudyWorkspaceRow, type StudyWorkspaceView } from './study-workspace-api'

const meta: Record<StudyWorkspaceView, { title: string; description: string }> = {
  summary: { title: 'Study Dashboard', description: 'Server-generated operational signals, with financial values kept separate by currency.' },
  health: { title: 'Study Health', description: 'Explainable operational health with source dates and direct links to contributing work.' },
  activity: { title: 'Recent Activity', description: 'Sanitized CTMS audit activity for this study.' },
  team: { title: 'Study Team', description: 'Effective-dated platform user and managed staff assignments.' },
  amendments: { title: 'Study Amendments', description: 'Operational amendment impact assessment and implementation.' },
  sites: { title: 'Study Site List', description: 'Canonical sites and their current operational profiles.' },
  feasibility: { title: 'Site Selection & Feasibility', description: 'Questionnaires, scoring, review, and final site decisions.' },
  startup: { title: 'Site Startup & Activation', description: 'Study-wide activation actions and readiness work.' },
  performance: { title: 'Site Performance', description: 'Versioned scorecards with component provenance and trends.' },
  closeout: { title: 'Site Closeout', description: 'Evidence-backed site closeout plans and blockers.' },
  'action-items': { title: 'Action Items', description: 'A normalized queue over authoritative study work sources.' },
  issues: { title: 'Issues & Escalations', description: 'Open findings, blockers, breaches, and follow-up.' },
  escalations: { title: 'Escalations', description: 'Reasoned operational task escalations.' },
  capas: { title: 'CAPA', description: 'Corrective and preventive action plans scoped to this study.' },
  ract: { title: 'RACT', description: 'Versioned Risk Assessment and Categorization Tool assessments.' },
  kris: { title: 'Key Risk Indicators', description: 'Versioned KRI definitions, thresholds, observations, and breach levels.' },
  'protocol-deviations': { title: 'Protocol Deviations', description: 'Operational follow-up linked to approved read-only EDC projections.' },
  'icf-rollouts': { title: 'ICF Rollout', description: 'Site distribution, acknowledgement, training, and effective-use tracking.' },
  'tracking-logs': { title: 'Tracking Logs', description: 'Controlled log definitions and immutable entry revisions.' },
}

const transitions: Partial<Record<StudyWorkspaceView, string[]>> = {
  amendments: ['Impact Assessment','Approved for Implementation','In Progress','Completed','Cancelled'],
  closeout: ['In Progress','Ready for Review','Approved','Closed'],
  ract: ['Under Review','Approved','Retired'], kris: ['Active','Paused','Retired'],
  'protocol-deviations': ['Under Review','Action Required','Resolved','Closed'],
  'icf-rollouts': ['Distributed','Site Acknowledged','Training Complete','Effective','Superseded','Withdrawn'],
}

function value(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function RowActions({ row, studyId, view }: { row: StudyWorkspaceRow; studyId: string; view: StudyWorkspaceView }) {
  const transition = useStudyWorkspaceTransition(studyId)
  const actions = transitions[view] ?? []
  const id = String(row.id ?? row.source_id ?? '')
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState(actions[0] ?? '')
  const [reason, setReason] = useState('')
  const apply = () => {
    if (!reason.trim() || !status || !id) return
    transition.mutate(
      { view, id, status, reason: reason.trim(), expectedVersion: typeof row.version === 'number' ? row.version : undefined },
      { onSuccess: () => { setOpen(false); setReason('') } },
    )
  }
  return <><div className="flex flex-wrap gap-2">
    {row.destination_path ? <Button asChild variant="outline" size="sm"><Link to={String(row.destination_path)}>Open source</Link></Button> : null}
    {actions.length ? <Button type="button" size="sm" variant="secondary" disabled={transition.isPending} onClick={() => setOpen(true)}>Change status</Button> : null}
  </div><Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>Change operational status</DialogTitle><DialogDescription>Current status: {value(row.status)}. A reason is retained in the audit history.</DialogDescription></DialogHeader><label className="grid gap-2 text-sm font-medium">New status<select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={status} onChange={(event) => setStatus(event.target.value)}>{actions.map((option) => <option key={option} value={option}>{option}</option>)}</select></label><label className="grid gap-2 text-sm font-medium">Reason<textarea className="min-h-24 rounded-md border border-input bg-background px-3 py-2 text-sm" value={reason} onChange={(event) => setReason(event.target.value)} required /></label>{transition.error ? <p className="text-sm text-destructive" role="alert">The transition was rejected. Refresh the record and verify the lifecycle requirements.</p> : null}<DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="button" disabled={!reason.trim() || !status || transition.isPending} onClick={apply}>{transition.isPending ? 'Applying…' : 'Apply transition'}</Button></DialogFooter></DialogContent></Dialog></>
}

function RowCard({ row, studyId, view }: { row: StudyWorkspaceRow; studyId: string; view: StudyWorkspaceView }) {
  const title = String(row.title ?? row.name ?? row.site_name ?? row.dimension ?? row.entity_type ?? 'Operational record')
  const entries = Object.entries(row).filter(([key]) => !['id','source_id','title','name','destination_path','permitted_actions'].includes(key)).slice(0, 10)
  return <DetailCard title={title} description={row.source_type ? String(row.source_type).replaceAll('_',' ') : undefined} status={row.status ? <span className="text-xs text-muted-foreground">{String(row.status)}</span> : undefined}>
    <dl className="grid gap-2 sm:grid-cols-2">{entries.map(([key,item]) => <div key={key}><dt className="text-xs uppercase tracking-wide text-muted-foreground">{key.replaceAll('_',' ')}</dt><dd className="mt-1 break-words text-sm">{value(item)}</dd></div>)}</dl>
    <div className="mt-4"><RowActions row={row} studyId={studyId} view={view} /></div>
  </DetailCard>
}

const column = createColumnHelper<StudyWorkspaceRow>()

function WorkspaceTable({ rows, studyId, view }: { rows: StudyWorkspaceRow[]; studyId: string; view: StudyWorkspaceView }) {
  const columns = useMemo(() => [
    column.display({ id: 'record', header: 'Record', cell: ({ row }) => String(row.original.title ?? row.original.name ?? row.original.site_name ?? row.original.dimension ?? row.original.entity_type ?? row.original.source_type ?? 'Operational record') }),
    column.accessor((row) => row.status, { id: 'status', header: 'Status', cell: ({ getValue }) => value(getValue()) }),
    column.accessor((row) => row.site_label ?? row.site_name ?? row.site_id, { id: 'site', header: 'Site', cell: ({ getValue }) => value(getValue()) }),
    column.accessor((row) => row.owner_name ?? row.owner_id ?? row.actor_name, { id: 'owner', header: 'Owner / Actor', cell: ({ getValue }) => value(getValue()) }),
    column.accessor((row) => row.due_at ?? row.due_date ?? row.updated_at ?? row.created_at ?? row.source_date, { id: 'date', header: 'Date', cell: ({ getValue }) => value(getValue()) }),
    column.display({ id: 'source', header: 'Actions', cell: ({ row }) => <RowActions row={row.original} studyId={studyId} view={view} /> }),
  ], [studyId, view])
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() })
  return <>
    <div className="hidden overflow-x-auto md:block"><table className="w-full text-sm"><thead className="border-b bg-muted/40">{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id} className="px-4 py-3 text-left font-medium">{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map((row) => <tr key={row.id} className="border-b last:border-0">{row.getVisibleCells().map((cell) => <td key={cell.id} className="px-4 py-3 align-top">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody></table></div>
    <div className="grid gap-4 p-4 md:hidden">{rows.map((row,index) => <RowCard key={String(row.id ?? row.source_id ?? index)} row={row} studyId={studyId} view={view} />)}</div>
  </>
}

export function CTMSStudyCompletionPage({ studyId, view }: { studyId: string; view: StudyWorkspaceView }) {
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, studyId)
  const canManageSites = usePermission(PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT, studyId)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState(() => new URLSearchParams(window.location.search).get('search') ?? '')
  const [addSiteOpen, setAddSiteOpen] = useState(false)
  const [availableSiteId, setAvailableSiteId] = useState('')
  const [studySiteId, setStudySiteId] = useState('')
  const queryClient = useQueryClient()
  const summary = useStudyWorkspaceSummary(studyId, view === 'summary')
  const health = useStudyWorkspaceHealth(studyId, view === 'health')
  const listView = view !== 'summary' && view !== 'health' ? view : 'activity'
  const list = useStudyWorkspaceList(studyId, listView, page, search, view !== 'summary' && view !== 'health')
  const availableSites = useQuery({
    queryKey: [...ctmsKeys.entities(studyId), 'site', 'study-site-list'],
    queryFn: () => ctmsApi.availableEntities(studyId, 'site', { pagination: { pageSize: 100 } }),
    enabled: view === 'sites' && addSiteOpen,
  })
  const addSite = useMutation({
    mutationFn: () => ctmsApi.createStudySite(studyId, { entity_id: availableSiteId, site_number: studySiteId.trim() }),
    onSuccess: async () => {
      setAddSiteOpen(false)
      setAvailableSiteId('')
      setStudySiteId('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ctms', 'study-workspace', studyId, 'sites'] }),
        queryClient.invalidateQueries({ queryKey: ctmsKeys.all }),
      ])
    },
  })
  const config = meta[view]
  const rows = useMemo(() => {
    const items = list.data?.items ?? []
    const term = search.trim().toLowerCase()
    return term ? items.filter((item) => JSON.stringify(item).toLowerCase().includes(term)) : items
  }, [list.data, search])
  const changeSearch = (next: string) => {
    setSearch(next)
    setPage(1)
    const url = new URL(window.location.href)
    if (next) url.searchParams.set('search', next)
    else url.searchParams.delete('search')
    window.history.replaceState(null, '', url)
  }
  if (!canRead) return <AccessDeniedPage />
  if (view === 'summary') return <PageContainer wide><PageHeader title={config.title} description={config.description} /><DataTableShell label="Study operational summary" loading={summary.isLoading} error={Boolean(summary.error)} onRetry={() => void summary.refetch()} empty={!summary.data}>{summary.data ? <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">{Object.entries(summary.data).filter(([key]) => !['study_id','generated_at'].includes(key)).map(([key,item]) => <DetailCard key={key} title={key.replaceAll('_',' ')}><p className="break-words text-sm">{value(item)}</p></DetailCard>)}</div> : null}</DataTableShell></PageContainer>
  if (view === 'health') return <PageContainer wide><PageHeader title={config.title} description={config.description} /><DataTableShell label="Operational health" loading={health.isLoading} error={Boolean(health.error)} onRetry={() => void health.refetch()} empty={!health.data?.length}><div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">{health.data?.map((signal) => <DetailCard key={signal.dimension} title={signal.dimension} description={signal.summary} status={<span className="text-xs font-semibold">{signal.status}</span>}><p className="text-xs text-muted-foreground">Source: {signal.source_date ?? 'Not available'}</p><Button asChild className="mt-3" size="sm" variant="outline"><Link to={signal.destination_path}>Review signals</Link></Button></DetailCard>)}</div></DataTableShell></PageContainer>
  const siteActions = view === 'sites' && canManageSites ? <div className="flex gap-2"><Button asChild variant="outline"><Link to="/ctms/sites">Site Directory</Link></Button><Button type="button" onClick={() => { addSite.reset(); setAddSiteOpen(true) }}>Add Site</Button></div> : undefined
  return <PageContainer wide><PageHeader title={config.title} description={config.description} actions={siteActions} /><div className="mb-4 max-w-md"><Input aria-label={`Search ${config.title}`} placeholder="Filter this workspace" value={search} onChange={(event) => changeSearch(event.target.value)} /></div><DataTableShell label={config.title} loading={list.isLoading} error={Boolean(list.error)} onRetry={() => void list.refetch()} empty={rows.length === 0} emptyTitle={`No ${config.title.toLowerCase()} records`} emptyDescription="No authorized records match the current filters."><WorkspaceTable rows={rows} studyId={studyId} view={view} /></DataTableShell>{(list.data?.total ?? 0) > 25 ? <div className="mt-4 flex items-center justify-end gap-2"><Button variant="outline" disabled={page===1} onClick={() => setPage((p)=>Math.max(1,p-1))}>Previous</Button><span className="text-sm">Page {page}</span><Button variant="outline" disabled={page*25 >= (list.data?.total ?? 0)} onClick={() => setPage((p)=>p+1)}>Next</Button></div> : null}<Dialog open={addSiteOpen} onOpenChange={setAddSiteOpen}><DialogContent><DialogHeader><DialogTitle>Add Site</DialogTitle><DialogDescription>Select an available site and enter the site number used in this study.</DialogDescription></DialogHeader><div className="grid gap-4"><div className="grid gap-2"><Label htmlFor="available-site">Available site</Label><select id="available-site" aria-label="Available site" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={availableSiteId} onChange={(event) => setAvailableSiteId(event.target.value)} required><option value="">{availableSites.isLoading ? 'Loading sites…' : 'Select an available site'}</option>{(availableSites.data?.items ?? []).map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}</select>{!availableSites.isLoading && (availableSites.data?.items.length ?? 0) === 0 ? <p className="text-sm text-muted-foreground">No unassigned sites are available. Create one in the Site Directory first.</p> : null}</div><div className="grid gap-2"><Label htmlFor="study-site-id">Site number</Label><Input id="study-site-id" aria-label="Site number" value={studySiteId} onChange={(event) => setStudySiteId(event.target.value)} placeholder="For example, 101" required /></div>{addSite.error ? <p className="text-sm text-destructive" role="alert">The site could not be added. Confirm that the site and site number are not already in use.</p> : null}</div><DialogFooter><Button type="button" variant="outline" onClick={() => setAddSiteOpen(false)}>Cancel</Button><Button type="button" disabled={!availableSiteId || !studySiteId.trim() || addSite.isPending} onClick={() => addSite.mutate()}>{addSite.isPending ? 'Adding…' : 'Add Site'}</Button></DialogFooter></DialogContent></Dialog></PageContainer>
}
