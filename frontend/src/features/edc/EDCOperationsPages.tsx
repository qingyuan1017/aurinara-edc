import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api, getApiErrorMessage, type PaginatedResponse } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, ErrorState, LoadingState, OwnershipBadge, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { AddVisitDialog } from '@/features/visits/AddVisitDialog'
import { PERMISSIONS, usePermission } from '@/lib/permissions'

interface OperationalStatus {
  data_entry: string
  review: string
  sdv: string
  sdr: string
  freeze: string
  lock: string
  signature: string
  active_query_count: number
}

interface FormWorkItem {
  form_instance_id: string
  subject_id: string
  subject_number: string
  site_name?: string
  visit_name?: string
  form_name: string
  status: OperationalStatus
  updated_at?: string
}

interface FormWorklistFilters {
  site: string
  subject: string
  visit: string
  form: string
  entry: string
  review: string
  sdv: string
  sdr: string
  queries: string
}

const EMPTY_FORM_WORKLIST_FILTERS: FormWorklistFilters = {
  site: '',
  subject: '',
  visit: '',
  form: '',
  entry: '',
  review: '',
  sdv: '',
  sdr: '',
  queries: '',
}

interface SiteOption { id: string; site_number: string; name: string }
interface SubjectOption { id: string; subject_number: string }
interface CasebookForm { form_instance_id?: string | null; name?: string | null; status: string }
interface CasebookVisit { visit_instance_id?: string | null; name?: string | null; forms: CasebookForm[] }
interface Casebook { visits: CasebookVisit[] }

export function DataEntryNavigatorPage({ studyId }: { studyId: string }) {
  const canEnter = usePermission(PERMISSIONS.FORM_ENTER, studyId)
  const [siteId, setSiteId] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [visitId, setVisitId] = useState('')
  const sites = useQuery({ queryKey: ['data-entry-sites', studyId], queryFn: async () => (await api.get<PaginatedResponse<SiteOption>>(`/studies/${studyId}/sites`, { params: { page: 1, page_size: 100 } })).data })
  const subjects = useQuery({ queryKey: ['data-entry-subjects', studyId, siteId], enabled: Boolean(siteId), queryFn: async () => (await api.get<PaginatedResponse<SubjectOption>>(`/studies/${studyId}/subjects`, { params: { page: 1, page_size: 100, site_id: siteId } })).data })
  const casebook = useQuery({ queryKey: ['data-entry-casebook', subjectId], enabled: Boolean(subjectId), queryFn: async () => (await api.get<Casebook>(`/subjects/${subjectId}/casebook`)).data })
  const visits = casebook.data?.visits ?? []
  const selectedVisit = visits.find((visit) => (visit.visit_instance_id ?? visit.name) === visitId)
  return <PageContainer><PageHeader title="Clinical Data Entry" description="Choose an authorized site, subject, visit, and form in sequence." ownership={<OwnershipBadge owner="EDC" />} /><Card><CardContent className="grid gap-5 p-6 md:grid-cols-3"><label className="space-y-1"><Label htmlFor="entry-site">1. Site</Label><select id="entry-site" value={siteId} onChange={(event) => { setSiteId(event.target.value); setSubjectId(''); setVisitId('') }} className="h-10 w-full rounded-md border border-input bg-background px-3"><option value="">Select site</option>{(sites.data?.items ?? []).map((site) => <option key={site.id} value={site.id}>{site.site_number} — {site.name}</option>)}</select></label><label className="space-y-1"><Label htmlFor="entry-subject">2. Subject</Label><select id="entry-subject" disabled={!siteId} value={subjectId} onChange={(event) => { setSubjectId(event.target.value); setVisitId('') }} className="h-10 w-full rounded-md border border-input bg-background px-3 disabled:opacity-50"><option value="">Select subject</option>{(subjects.data?.items ?? []).map((subject) => <option key={subject.id} value={subject.id}>{subject.subject_number}</option>)}</select></label><label className="space-y-1"><Label htmlFor="entry-visit">3. Visit</Label><select id="entry-visit" disabled={!subjectId} value={visitId} onChange={(event) => setVisitId(event.target.value)} className="h-10 w-full rounded-md border border-input bg-background px-3 disabled:opacity-50"><option value="">Select visit</option>{visits.map((visit) => <option key={visit.visit_instance_id ?? visit.name} value={visit.visit_instance_id ?? visit.name ?? ''}>{visit.name ?? 'Visit'}</option>)}</select></label>{canEnter && subjectId ? <div className="md:col-span-3"><AddVisitDialog subjectId={subjectId} onCreated={(visit) => setVisitId(visit.id)} /></div> : null}</CardContent></Card>{selectedVisit ? <div className="mt-6 grid gap-3">{selectedVisit.forms.map((form) => <Card key={form.form_instance_id ?? form.name}><CardContent className="flex items-center justify-between p-4"><div><p className="font-medium">{form.name ?? 'Form'}</p><StatusBadge status={form.status} label="Entry status" /></div>{form.form_instance_id ? <Button asChild><Link to="/subjects/$subjectId/forms/$formInstanceId" params={{ subjectId, formInstanceId: form.form_instance_id }}>Open form</Link></Button> : null}</CardContent></Card>)}</div> : null}</PageContainer>
}

export function IncompleteFormsPage({ studyId }: { studyId: string }) {
  const [state, setState] = useState('incomplete')
  const [filters, setFilters] = useState<FormWorklistFilters>(EMPTY_FORM_WORKLIST_FILTERS)
  const query = useQuery({
    queryKey: ['form-worklist', studyId, state],
    queryFn: async () => (await api.get<PaginatedResponse<FormWorkItem>>(`/studies/${studyId}/form-worklist`, { params: { page: 1, page_size: 100, state } })).data,
  })
  const items = useMemo(() => query.data?.items ?? [], [query.data?.items])
  const filteredItems = useMemo(() => {
    const includes = (value: string | undefined, filter: string) => !filter || (value ?? '').toLocaleLowerCase().includes(filter.trim().toLocaleLowerCase())
    return items.filter((item) =>
      includes(item.site_name, filters.site)
      && includes(item.subject_number, filters.subject)
      && includes(item.visit_name, filters.visit)
      && includes(item.form_name, filters.form)
      && (!filters.entry || item.status.data_entry === filters.entry)
      && (!filters.review || item.status.review === filters.review)
      && (!filters.sdv || item.status.sdv === filters.sdv)
      && (!filters.sdr || item.status.sdr === filters.sdr)
      && (!filters.queries || item.status.active_query_count === Number(filters.queries)),
    )
  }, [filters, items])
  const statusOptions = (key: 'data_entry' | 'review' | 'sdv' | 'sdr') => [...new Set(items.map((item) => item.status[key]))].sort()
  const statusFilterLabels: Record<'entry' | 'review' | 'sdv' | 'sdr', string> = { entry: 'entry', review: 'review', sdv: 'SDV', sdr: 'SDR' }
  const hasColumnFilters = Object.values(filters).some(Boolean)
  const updateFilter = (key: keyof FormWorklistFilters, value: string) => setFilters((current) => ({ ...current, [key]: value }))
  const filterClassName = 'h-9 min-w-28 rounded-md border border-input bg-background px-2 text-sm font-normal'

  return <PageContainer wide><PageHeader title="Form Worklist" description="Authorized, server-filtered incomplete and data-cleaning work." ownership={<OwnershipBadge owner="EDC" />} /><PageToolbar label="Form filters"><label className="flex items-center gap-2 text-sm">State<select aria-label="Form state" value={state} onChange={(event) => setState(event.target.value)} className="h-10 rounded-md border border-input bg-background px-3"><option value="incomplete">Incomplete</option><option value="submitted">Submitted</option><option value="queried">Queried</option><option value="changed_since_review">Changed since review</option></select></label><Button type="button" variant="outline" disabled={!hasColumnFilters} onClick={() => setFilters(EMPTY_FORM_WORKLIST_FILTERS)}>Clear column filters</Button></PageToolbar><DataTableShell label="Form worklist" loading={query.isLoading} error={Boolean(query.error)} errorMessage="Unable to load the form worklist." empty={!query.isLoading && items.length === 0} emptyTitle="No matching forms" emptyDescription="No authorized forms match this state."><Table><TableHeader><TableRow>{['Site', 'Subject', 'Visit', 'Form', 'Entry', 'Review', 'SDV', 'SDR', 'Queries'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow><TableRow className="hover:bg-transparent"><TableHead><Input className={filterClassName} aria-label="Filter by site" value={filters.site} onChange={(event) => updateFilter('site', event.target.value)} placeholder="Filter site" /></TableHead><TableHead><Input className={filterClassName} aria-label="Filter by subject" value={filters.subject} onChange={(event) => updateFilter('subject', event.target.value)} placeholder="Filter subject" /></TableHead><TableHead><Input className={filterClassName} aria-label="Filter by visit" value={filters.visit} onChange={(event) => updateFilter('visit', event.target.value)} placeholder="Filter visit" /></TableHead><TableHead><Input className={filterClassName} aria-label="Filter by form" value={filters.form} onChange={(event) => updateFilter('form', event.target.value)} placeholder="Filter form" /></TableHead>{(['entry', 'review', 'sdv', 'sdr'] as const).map((key) => <TableHead key={key}><select className={filterClassName} aria-label={`Filter by ${statusFilterLabels[key]}`} value={filters[key]} onChange={(event) => updateFilter(key, event.target.value)}><option value="">All</option>{statusOptions(key === 'entry' ? 'data_entry' : key).map((value) => <option key={value} value={value}>{value}</option>)}</select></TableHead>)}<TableHead><Input className={filterClassName} aria-label="Filter by queries" type="number" min="0" value={filters.queries} onChange={(event) => updateFilter('queries', event.target.value)} placeholder="Exact count" /></TableHead></TableRow></TableHeader><TableBody>{filteredItems.length === 0 && hasColumnFilters ? <TableRow><TableCell colSpan={9} className="py-8 text-center text-muted-foreground">No forms match the current column filters.</TableCell></TableRow> : filteredItems.map((item) => <TableRow key={item.form_instance_id}><TableCell>{item.site_name ?? '—'}</TableCell><TableCell>{item.subject_number}</TableCell><TableCell>{item.visit_name ?? '—'}</TableCell><TableCell><Link className="text-primary hover:underline" to="/subjects/$subjectId/forms/$formInstanceId" params={{ subjectId: item.subject_id, formInstanceId: item.form_instance_id }}>{item.form_name}</Link></TableCell><TableCell><StatusBadge status={item.status.data_entry} label="Entry" /></TableCell><TableCell><StatusBadge status={item.status.review} label="Review" /></TableCell><TableCell><StatusBadge status={item.status.sdv} label="SDV" /></TableCell><TableCell><StatusBadge status={item.status.sdr} label="SDR" /></TableCell><TableCell>{item.status.active_query_count}</TableCell></TableRow>)}</TableBody></Table></DataTableShell></PageContainer>
}

interface ListingCatalogItem { dataset: string; label: string; columns: Array<{ key: string; label: string }> }
interface ListingRow { source_form_url: string; values: Record<string, unknown> }

export function DataListingsPage({ studyId }: { studyId: string }) {
  const [dataset, setDataset] = useState('')
  const catalog = useQuery({ queryKey: ['listing-catalog', studyId], queryFn: async () => (await api.get<ListingCatalogItem[]>(`/studies/${studyId}/listings/catalog`)).data })
  const selected = dataset || catalog.data?.[0]?.dataset || ''
  const rows = useQuery({ queryKey: ['listing-rows', studyId, selected], enabled: Boolean(selected), queryFn: async () => (await api.get<PaginatedResponse<ListingRow>>(`/studies/${studyId}/listings/${selected}/rows`, { params: { page: 1, page_size: 100 } })).data })
  const definition = catalog.data?.find((item) => item.dataset === selected)
  return <PageContainer wide><PageHeader title="Data Listings" description="Metadata-driven clinical listings from published form definitions." ownership={<OwnershipBadge owner="EDC" />} /><PageToolbar label="Listing dataset"><label className="flex items-center gap-2 text-sm">Dataset<select aria-label="Listing dataset" value={selected} onChange={(event) => setDataset(event.target.value)} className="h-10 min-w-56 rounded-md border border-input bg-background px-3">{(catalog.data ?? []).map((item) => <option key={item.dataset} value={item.dataset}>{item.label}</option>)}</select></label></PageToolbar>{catalog.isLoading || rows.isLoading ? <LoadingState label="data listing" /> : catalog.error || rows.error ? <ErrorState message="Unable to load the authorized data listing." onRetry={() => void Promise.all([catalog.refetch(), rows.refetch()])} /> : <DataTableShell label="Clinical listing" empty={(rows.data?.items.length ?? 0) === 0} emptyTitle="No listing rows" emptyDescription="No authorized captured data exists for this dataset."><Table><TableHeader><TableRow><TableHead>Source</TableHead>{(definition?.columns ?? []).map((column) => <TableHead key={column.key}>{column.label}</TableHead>)}</TableRow></TableHeader><TableBody>{(rows.data?.items ?? []).map((row, index) => <TableRow key={`${row.source_form_url}-${index}`}><TableCell><a className="text-primary hover:underline" href={row.source_form_url}>Open eCRF</a></TableCell>{(definition?.columns ?? []).map((column) => <TableCell key={column.key}>{String(row.values[column.key] ?? '—')}</TableCell>)}</TableRow>)}</TableBody></Table></DataTableShell>}</PageContainer>
}

interface ReadinessBlocker { code: string; count: number; message: string; drilldown: string }
interface LockReadiness { ready: boolean; evaluated_at: string; snapshot_hash: string; blockers: ReadinessBlocker[] }
interface ControlRequest { id: string; scope_type: string; scope_id: string; action: string; status: string; reason: string; requested_at: string; requested_by: string; approved_by?: string; executed_by?: string; failure_details?: Record<string, unknown> }

export function ClinicalControlPage({ studyId, defaultAction = 'lock', historyOnly = false }: { studyId: string; defaultAction?: 'freeze' | 'unfreeze' | 'lock' | 'unlock'; historyOnly?: boolean }) {
  const client = useQueryClient()
  const [action, setAction] = useState(defaultAction)
  const [reason, setReason] = useState('')
  const readiness = useQuery({ queryKey: ['lock-readiness', studyId], enabled: !historyOnly, queryFn: async () => (await api.get<LockReadiness>(`/studies/${studyId}/lock-readiness`)).data })
  const requests = useQuery({ queryKey: ['clinical-controls', studyId], queryFn: async () => (await api.get<PaginatedResponse<ControlRequest>>(`/studies/${studyId}/${historyOnly ? 'lock-history' : 'clinical-control-requests'}`, { params: { page: 1, page_size: 100 } })).data })
  const refresh = () => { void client.invalidateQueries({ queryKey: ['clinical-controls', studyId] }); void client.invalidateQueries({ queryKey: ['lock-readiness', studyId] }) }
  const create = useMutation({ mutationFn: () => api.post(`/studies/${studyId}/clinical-control-requests`, { scope_type: 'study', scope_id: studyId, action, reason }), onSuccess: () => { setReason(''); refresh() } })
  const transition = useMutation({ mutationFn: ({ id, verb }: { id: string; verb: 'approve' | 'reject' | 'cancel' | 'execute' }) => api.post(`/clinical-control-requests/${id}/${verb}`, verb === 'reject' ? { reason: 'Rejected during review' } : undefined), onSuccess: refresh })
  const items = requests.data?.items ?? []
  const mutationError = create.error ?? transition.error
  return <PageContainer wide><PageHeader title={historyOnly ? 'Lock History' : defaultAction.includes('freeze') ? 'Data Freeze Control' : 'Database Lock Control'} description="Maker-checker clinical controls with readiness revalidation at execution." ownership={<OwnershipBadge owner="EDC" />} />{mutationError ? <Alert variant="destructive" className="mb-6"><AlertDescription>{getApiErrorMessage(mutationError, 'The clinical control action could not be completed.')}</AlertDescription></Alert> : null}{!historyOnly ? readiness.isLoading ? <LoadingState label="lock readiness" /> : readiness.error ? <ErrorState message="Unable to evaluate lock readiness." onRetry={() => void readiness.refetch()} /> : readiness.data ? <Card className="mb-6"><CardHeader><CardTitle className="flex items-center gap-3">Readiness <StatusBadge status={readiness.data.ready ? 'Ready' : 'Blocked'} label="Lock readiness" /></CardTitle></CardHeader><CardContent><p className="text-sm text-muted-foreground">Evaluated {new Date(readiness.data.evaluated_at).toLocaleString()}</p>{readiness.data.blockers.length ? <ul className="mt-3 space-y-2">{readiness.data.blockers.map((blocker) => <li key={blocker.code} className="text-sm"><strong>{blocker.count}</strong> — {blocker.message}</li>)}</ul> : <p className="mt-3 text-sm">No readiness blockers.</p>}</CardContent></Card> : null : null}{!historyOnly ? <Card className="mb-6"><CardHeader><CardTitle>Request a study control</CardTitle></CardHeader><CardContent className="grid gap-4 md:grid-cols-[12rem_1fr_auto]"><label className="space-y-1"><Label htmlFor="control-action">Action</Label><select id="control-action" value={action} onChange={(event) => setAction(event.target.value as typeof action)} className="h-10 w-full rounded-md border border-input bg-background px-3"><option value="freeze">Freeze</option><option value="unfreeze">Unfreeze</option><option value="lock">Lock</option><option value="unlock">Unlock</option></select></label><label className="space-y-1"><Label htmlFor="control-reason">Reason</Label><Input id="control-reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Required justification" /></label><Button className="self-end" disabled={!reason.trim() || create.isPending} onClick={() => create.mutate()}>Request</Button></CardContent></Card> : null}<DataTableShell label="Clinical control history" loading={requests.isLoading} error={Boolean(requests.error)} errorMessage="Unable to load clinical control requests." empty={!requests.isLoading && items.length === 0} emptyTitle="No control requests" emptyDescription="No scoped freeze or lock requests have been recorded."><Table><TableHeader><TableRow>{['Requested', 'Action', 'Scope', 'Status', 'Reason', 'Actions'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader><TableBody>{items.map((item) => <TableRow key={item.id}><TableCell>{new Date(item.requested_at).toLocaleString()}</TableCell><TableCell>{item.action}</TableCell><TableCell>{item.scope_type}</TableCell><TableCell><StatusBadge status={item.status} label="Control status" /></TableCell><TableCell className="max-w-80">{item.reason}</TableCell><TableCell><div className="flex gap-2">{item.status === 'Pending Approval' ? <><Button size="sm" onClick={() => transition.mutate({ id: item.id, verb: 'approve' })}>Approve</Button><Button size="sm" variant="outline" onClick={() => transition.mutate({ id: item.id, verb: 'reject' })}>Reject</Button></> : null}{item.status === 'Approved' ? <Button size="sm" onClick={() => transition.mutate({ id: item.id, verb: 'execute' })}>Execute</Button> : null}</div></TableCell></TableRow>)}</TableBody></Table></DataTableShell></PageContainer>
}
