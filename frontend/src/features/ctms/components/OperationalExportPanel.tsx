import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  ctmsApi,
  parseCTMSExportFilters,
  useCTMSExportJob,
  type CTMSExport,
  type CTMSExportFilters,
  type CTMSExportFormat,
  type CTMSExportRequest,
  type CTMSOperationalRecordType,
  type CTMSQueryContext,
} from '../api'
import { invalidateCTMSExportMutation } from '../cache'
import { useCTMSMutation, useCTMSOfflineState } from '../offline'
import { CTMSMutationFeedback } from './CTMSMutationFeedback'
import { ModuleBadge, ReadOnlyIndicator } from './OwnershipPresentation'

const EXPORT_FORMATS: readonly { value: CTMSExportFormat; label: string }[] = [
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' },
  { value: 'excel', label: 'Excel' },
]

const OPERATIONAL_RECORD_TYPES: readonly { value: CTMSOperationalRecordType; label: string }[] = [
  { value: 'operational_study', label: 'Operational study' },
  { value: 'study_plan', label: 'Study plan' },
  { value: 'enrollment_plan', label: 'Enrollment plan' },
  { value: 'readiness_criterion', label: 'Readiness criterion' },
  { value: 'study_milestone', label: 'Study milestone' },
  { value: 'operational_site', label: 'Operational site' },
  { value: 'activation_action', label: 'Activation action' },
  { value: 'enrollment_target', label: 'Enrollment target' },
  { value: 'operational_milestone', label: 'Operational milestone' },
  { value: 'monitoring_plan', label: 'Monitoring plan' },
  { value: 'monitoring_plan_version', label: 'Monitoring plan version' },
  { value: 'monitoring_activity', label: 'Monitoring activity' },
  { value: 'operational_task', label: 'Operational task' },
  { value: 'operational_contact', label: 'Operational contact' },
]

interface OperationalExportPanelProps {
  studyId: string
  siteId?: string
  context?: CTMSQueryContext
  jobs: readonly CTMSExport[]
  isLoading?: boolean
  canManage: boolean
  canRead: boolean
  onRefresh: () => void
}

interface ExportFormState {
  exportType: CTMSExportFormat
  siteId: string
  recordTypes: CTMSOperationalRecordType[]
  statuses: string
  dateFrom: string
  dateTo: string
  includeArchived: boolean
  includeProjections: boolean
  projectionTypes: string
  pageSize: string
}

const initialForm = (siteId?: string): ExportFormState => ({
  exportType: 'csv',
  siteId: siteId ?? '',
  recordTypes: [],
  statuses: '',
  dateFrom: '',
  dateTo: '',
  includeArchived: false,
  includeProjections: false,
  projectionTypes: '',
  pageSize: '100',
})

function splitValues(value: string): string[] | undefined {
  const values = value.split(',').map((item) => item.trim()).filter(Boolean)
  return values.length ? values : undefined
}

function dateToIso(value: string): string | undefined {
  if (!value) return undefined
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
}

function formToRequest(form: ExportFormState): CTMSExportRequest {
  const filters: CTMSExportFilters = {
    siteId: form.siteId.trim() || undefined,
    recordTypes: form.recordTypes.length ? form.recordTypes : undefined,
    statuses: splitValues(form.statuses),
    dateFrom: dateToIso(form.dateFrom),
    dateTo: dateToIso(form.dateTo),
    includeArchived: form.includeArchived,
    includeProjections: form.includeProjections,
    projectionTypes: form.includeProjections ? splitValues(form.projectionTypes) : undefined,
    pageSize: form.pageSize ? Number(form.pageSize) : undefined,
  }
  return { exportType: form.exportType, filters }
}

function safeFilterSummary(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '—'
  const allowed = new Set(['site_id', 'record_types', 'statuses', 'status', 'date_from', 'date_to', 'include_archived', 'include_projections', 'projection_types', 'page', 'page_size'])
  const safe = Object.fromEntries(Object.entries(value as Record<string, unknown>).filter(([key]) => allowed.has(key)))
  return Object.keys(safe).length ? JSON.stringify(safe) : '—'
}

function formatStatus(status: string): string {
  return status.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

function isExpired(job: CTMSExport): boolean {
  if (String(job.status ?? '').toLowerCase() === 'expired') return true
  return Boolean(job.expires_at && new Date(job.expires_at).getTime() <= Date.now())
}

function progressFor(status: string): number | undefined {
  switch (status.toLowerCase()) {
    case 'queued': return 10
    case 'running': return 60
    case 'completed': return 100
    default: return undefined
  }
}

function safeExportType(value: string): CTMSExportFormat {
  return value === 'json' || value === 'excel' ? value : 'csv'
}

function downloadBlob(blob: Blob, job: CTMSExport): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `ctms_operational_export_${job.id}.${safeExportType(job.export_type)}`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function ExportRequestForm({ studyId, siteId, canManage, onCreated }: { studyId: string; siteId?: string; canManage: boolean; onCreated: (job: CTMSExport) => void }) {
  const queryClient = useQueryClient()
  const { isOffline } = useCTMSOfflineState()
  const [form, setForm] = useState<ExportFormState>(() => initialForm(siteId))
  const [formError, setFormError] = useState<string>()
  const create = useCTMSMutation<CTMSExport, unknown, CTMSExportRequest>({
    method: 'POST',
    mutationFn: (request) => ctmsApi.createExport(studyId, request),
    onSuccess: async (job) => {
      await invalidateCTMSExportMutation(queryClient, studyId, job.id)
      onCreated(job)
      setForm(initialForm(siteId))
    },
  })

  if (!canManage) return <ReadOnlyIndicator reason="Export creation is available only to authorized CTMS operations users; the API remains authoritative." />

  const update = <K extends keyof ExportFormState>(key: K, value: ExportFormState[K]) => setForm((current) => ({ ...current, [key]: value }))
  const toggleRecordType = (type: CTMSOperationalRecordType) => setForm((current) => ({
    ...current,
    recordTypes: current.recordTypes.includes(type) ? current.recordTypes.filter((item) => item !== type) : [...current.recordTypes, type],
  }))
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const request = formToRequest(form)
    if ((form.dateFrom && !request.filters?.dateFrom) || (form.dateTo && !request.filters?.dateTo)) {
      setFormError('Enter valid export dates.')
      return
    }
    if (!Number.isInteger(request.filters?.pageSize) || Number(request.filters?.pageSize) < 1 || Number(request.filters?.pageSize) > 1000) {
      setFormError('Page size must be a whole number between 1 and 1000.')
      return
    }
    if (request.filters?.dateFrom && request.filters.dateTo && request.filters.dateFrom > request.filters.dateTo) {
      setFormError('The start date must be earlier than or equal to the end date.')
      return
    }
    if (form.projectionTypes.trim() && !form.includeProjections) {
      setFormError('Select Include approved projections before entering projection types.')
      return
    }
    setFormError(undefined)
    create.mutate(request)
  }

  return <form className="space-y-4 rounded-lg border border-border bg-muted/20 p-4" onSubmit={submit} aria-label="Create operational export">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold text-foreground">Request operational export</h3><p className="text-xs text-muted-foreground">Only CTMS-owned operational records and approved projections can be included.</p></div><ModuleBadge module="CTMS" state="authoritative" /></div>
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1.5"><Label htmlFor="export-format">Format</Label><select id="export-format" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={form.exportType} onChange={(event) => update('exportType', event.target.value as CTMSExportFormat)}>{EXPORT_FORMATS.map((format) => <option key={format.value} value={format.value}>{format.label}</option>)}</select></div>
      <div className="space-y-1.5"><Label htmlFor="export-site-id">Site ID (optional)</Label><Input id="export-site-id" value={form.siteId} onChange={(event) => update('siteId', event.target.value)} placeholder="Canonical EDC Site ID" /></div>
      <div className="space-y-1.5"><Label htmlFor="export-date-from">Date from</Label><Input id="export-date-from" type="datetime-local" value={form.dateFrom} onChange={(event) => update('dateFrom', event.target.value)} /></div>
      <div className="space-y-1.5"><Label htmlFor="export-date-to">Date to</Label><Input id="export-date-to" type="datetime-local" value={form.dateTo} onChange={(event) => update('dateTo', event.target.value)} /></div>
      <div className="space-y-1.5 sm:col-span-2"><Label htmlFor="export-statuses">Statuses (comma separated)</Label><Input id="export-statuses" value={form.statuses} onChange={(event) => update('statuses', event.target.value)} placeholder="Active, Pending" /></div>
      <div className="space-y-1.5 sm:col-span-2"><Label htmlFor="export-page-size">Page size</Label><Input id="export-page-size" type="number" min={1} max={1000} value={form.pageSize} onChange={(event) => update('pageSize', event.target.value)} /></div>
    </div>
    <fieldset><legend className="text-sm font-medium text-foreground">Operational record types (optional)</legend><div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{OPERATIONAL_RECORD_TYPES.map((type) => <label key={type.value} className="flex items-center gap-2 text-sm text-foreground"><Checkbox checked={form.recordTypes.includes(type.value)} onChange={() => toggleRecordType(type.value)} />{type.label}</label>)}</div></fieldset>
    <div className="space-y-2 text-sm text-foreground"><label className="flex items-center gap-2"><Checkbox checked={form.includeArchived} onChange={(event) => update('includeArchived', event.target.checked)} />Include archived operational records</label><label className="flex items-center gap-2"><Checkbox checked={form.includeProjections} onChange={(event) => update('includeProjections', event.target.checked)} />Include approved read-only projections</label><div className="space-y-1.5"><Label htmlFor="export-projection-types">Projection types (optional)</Label><Input id="export-projection-types" disabled={!form.includeProjections} value={form.projectionTypes} onChange={(event) => update('projectionTypes', event.target.value)} placeholder="Approved projection types, comma separated" /></div></div>
    {formError && <p role="alert" className="text-sm text-destructive">{formError}</p>}
    {isOffline && <p role="status" className="text-sm text-warning">You are offline. Export requests are disabled until the connection returns.</p>}
    <Button type="submit" disabled={create.isPending || create.isOffline} loading={create.isPending} loadingText="Submitting export request…">Request operational export</Button>
    <CTMSMutationFeedback status={create.status} action="Operational export request" data={create.data} error={create.error} />
  </form>
}

function ExportDetail({ job, context, canManage, canRead, onRetry }: { job: CTMSExport; context?: CTMSQueryContext; canManage: boolean; canRead: boolean; onRetry: (job: CTMSExport) => void }) {
  const detail = useCTMSExportJob(job.id, context)
  const queryJob = detail.data ?? job
  const statusValue = String(queryJob.status ?? '')
  const expired = isExpired(queryJob)
  const status = expired ? 'expired' : statusValue
  const progress = progressFor(status)
  const { isOffline } = useCTMSOfflineState()
  const download = useCTMSMutation<Blob, unknown, string>({ method: 'GET', mutationFn: (id) => ctmsApi.downloadExport(id), onSuccess: (blob) => downloadBlob(blob, queryJob) })
  const canDownload = canRead && status.toLowerCase() === 'completed' && !expired
  return <section className="space-y-3 rounded-lg border bg-card p-4" aria-label={`Export ${queryJob.id} details`}>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold text-foreground">Operational export status</h3><p className="font-mono text-xs text-muted-foreground">Export ID: {queryJob.id}</p></div><span className="rounded-full border bg-muted px-2 py-1 text-sm font-medium" aria-label={`Export status: ${formatStatus(status)}`}>{formatStatus(status)}</span></div>
    <p className="text-sm text-muted-foreground">This is CTMS-owned operational content. Clinical exports and clinical attachments are not available here.</p>
    {progress !== undefined && <div className="space-y-1" aria-label={`Export progress ${progress} percent`}><div className="h-2 overflow-hidden rounded bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} /></div><p className="text-xs text-muted-foreground">{progress}% — {status.toLowerCase() === 'completed' ? 'Ready for download' : 'The export worker is processing this request.'}</p></div>}
    {queryJob.expires_at && <p className={`text-sm ${expired ? 'text-destructive' : 'text-muted-foreground'}`}>{expired ? 'This operational export has expired and is no longer available for download.' : `Download expires ${new Date(queryJob.expires_at).toLocaleString()}.`}</p>}
    {queryJob.error_message && status.toLowerCase() === 'failed' && <p role="alert" className="text-sm text-destructive">{queryJob.error_message}</p>}
    {queryJob.correlation_id && <p className="font-mono text-xs text-muted-foreground">Correlation ID: {queryJob.correlation_id}</p>}
    <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => void detail.refetch()} disabled={detail.isFetching}>Refresh status</Button>{canManage && status.toLowerCase() === 'failed' && <Button type="button" variant="outline" size="sm" onClick={() => onRetry(queryJob)} disabled={isOffline}>Retry export</Button>}{canDownload && <Button type="button" size="sm" onClick={() => download.mutate(queryJob.id)} disabled={download.isPending || download.isOffline} loading={download.isPending} loadingText="Preparing download…">Download operational export</Button>}</div>
    <CTMSMutationFeedback status={download.status} action="Operational export download" data={download.data} error={download.error} />
  </section>
}

export function OperationalExportPanel({ studyId, siteId, context, jobs, isLoading, canManage, canRead, onRefresh }: OperationalExportPanelProps) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string>()
  const [createdJob, setCreatedJob] = useState<CTMSExport>()
  const retry = useCTMSMutation<CTMSExport, unknown, CTMSExport>({
    method: 'POST',
    mutationFn: (job) => ctmsApi.createExport(studyId, {
      exportType: safeExportType(job.export_type),
      filters: parseCTMSExportFilters(job.filters),
    }),
    onSuccess: async (job) => {
      await invalidateCTMSExportMutation(queryClient, studyId, job.id)
      setCreatedJob(job)
      setSelectedId(job.id)
    },
  })
  const selectedJob = useMemo(() => createdJob ?? jobs.find((job) => job.id === selectedId), [createdJob, jobs, selectedId])
  const startRetry = (job: CTMSExport) => retry.mutate(job)
  return <div className="space-y-4">
    <ExportRequestForm studyId={studyId} siteId={siteId} canManage={canManage} onCreated={(job) => { setCreatedJob(job); setSelectedId(job.id); onRefresh() }} />
    <CTMSMutationFeedback status={retry.status} action="Operational export retry" data={retry.data} error={retry.error} />
    {selectedJob && <ExportDetail job={selectedJob} context={context} canManage={canManage} canRead={canRead} onRetry={startRetry} />}
    <section className="space-y-3" aria-label="Operational export jobs"><div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold text-foreground">Operational export jobs</h3><p className="text-sm text-muted-foreground">Statuses and actions are server-authoritative; no clinical export content is rendered.</p></div><Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={isLoading}>Refresh exports</Button></div>{isLoading ? <p role="status" className="rounded border bg-card p-4 text-sm text-muted-foreground">Loading operational export jobs…</p> : jobs.length ? <div className="rounded-lg border"><Table><TableCaption className="sr-only">CTMS operational export jobs</TableCaption><TableHeader className="bg-muted/30"><TableRow><TableHead scope="col">Export</TableHead><TableHead scope="col">Format</TableHead><TableHead scope="col">Filters</TableHead><TableHead scope="col">Status</TableHead><TableHead scope="col">Created</TableHead><TableHead scope="col">Actions</TableHead></TableRow></TableHeader><TableBody>{jobs.map((job) => { const expired = isExpired(job); const status = expired ? 'expired' : job.status; return <TableRow key={job.id}><TableCell><span className="font-mono text-xs">{job.id}</span><span className="ml-2"><ModuleBadge module="CTMS" state="authoritative" /></span></TableCell><TableCell className="uppercase">{safeExportType(job.export_type)}</TableCell><TableCell className="max-w-xs break-words font-mono text-xs">{safeFilterSummary(job.filters)}</TableCell><TableCell>{formatStatus(status)}</TableCell><TableCell>{new Date(job.created_at).toLocaleString()}</TableCell><TableCell><Button type="button" variant="outline" size="sm" onClick={() => { setCreatedJob(undefined); setSelectedId(job.id) }}>View status</Button></TableCell></TableRow> })}</TableBody></Table></div> : <div className="rounded-lg border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground" role="status">No CTMS operational export jobs have been requested for this study.</div>}</section>
  </div>
}
