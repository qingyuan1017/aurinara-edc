import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { DataTableShell, DetailCard, PageContainer, PageHeader } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import {
  ctmsApi,
  useCTMSCatalogReport,
  useCTMSStudyOperations,
  type CTMSStudyOperationCreate,
  type CTMSStudyOperationResource,
} from './api'

interface StudyAreaPageProps {
  studyId: string
  title: string
  description: string
  resource?: CTMSStudyOperationResource
  eyebrow?: string
  emptyTitle?: string
  emptyDescription?: string
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function RecordDetails({ value }: { value: object }) {
  const entries = Object.entries(value).filter(([key]) => !['id', 'title', 'status'].includes(key))
  return <dl className="grid gap-3 sm:grid-cols-2">
    {entries.map(([key, item]) => <div key={key}>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{key.replaceAll('_', ' ')}</dt>
      <dd className="mt-1 break-words text-sm text-foreground">{displayValue(item)}</dd>
    </div>)}
  </dl>
}

type OperationDraft = {
  title: string
  recordSubtype: string
  status: string
  siteId: string
  subjectId: string
  ownerId: string
  startAt: string
  endAt: string
  amount: string
  currency: string
}

const emptyOperationDraft = (): OperationDraft => ({ title: '', recordSubtype: '', status: 'Draft', siteId: '', subjectId: '', ownerId: '', startAt: '', endAt: '', amount: '', currency: '' })

function optional(value: string): string | undefined { return value.trim() || undefined }
function toUtc(value: string): string | undefined { return value ? new Date(value).toISOString() : undefined }

function OperationField({ label, name, value, onChange, type = 'text', required = false }: { label: string; name: keyof OperationDraft; value: string; onChange: (name: keyof OperationDraft, value: string) => void; type?: string; required?: boolean }) {
  return <div className="space-y-2"><Label htmlFor={`study-operation-${name}`}>{label}{required ? ' *' : ''}</Label><Input id={`study-operation-${name}`} name={name} value={value} onChange={(event) => onChange(name, event.target.value)} type={type} required={required} /></div>
}

function StudyOperationForm({ resource, draft, onChange, onSubmit, pending, error }: { resource: CTMSStudyOperationResource; draft: OperationDraft; onChange: (name: keyof OperationDraft, value: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; pending: boolean; error: boolean }) {
  return <form className="space-y-5" onSubmit={onSubmit}>
    <OperationField label="Title" name="title" value={draft.title} onChange={onChange} required />
    <div className="grid gap-4 sm:grid-cols-2">
      {resource === 'payment' ? <div className="space-y-2"><Label htmlFor="study-operation-recordSubtype">Payment type</Label><select id="study-operation-recordSubtype" className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={draft.recordSubtype} onChange={(event) => onChange('recordSubtype', event.target.value)}><option value="">Select payment type</option><option value="Trigger">Trigger</option><option value="Request">Request</option></select></div> : <OperationField label="Subtype" name="recordSubtype" value={draft.recordSubtype} onChange={onChange} />}
      <OperationField label="Status" name="status" value={draft.status} onChange={onChange} required />
      <OperationField label="Site ID" name="siteId" value={draft.siteId} onChange={onChange} />
      <OperationField label="Subject ID" name="subjectId" value={draft.subjectId} onChange={onChange} />
      <OperationField label="Owner ID" name="ownerId" value={draft.ownerId} onChange={onChange} />
      <OperationField label="Start" name="startAt" value={draft.startAt} onChange={onChange} type="datetime-local" />
      <OperationField label="End" name="endAt" value={draft.endAt} onChange={onChange} type="datetime-local" />
      <OperationField label="Amount" name="amount" value={draft.amount} onChange={onChange} type="number" />
      <OperationField label="Currency" name="currency" value={draft.currency} onChange={onChange} />
    </div>
    <Button type="submit" pending={pending}>Add record</Button>
    {error ? <p role="alert" className="text-sm text-destructive">The record could not be created. Check the required fields and identifiers.</p> : null}
  </form>
}

export function CTMSStudyAreaPage({ studyId, title, description, resource, eyebrow = 'CTMS study operations', emptyTitle, emptyDescription }: StudyAreaPageProps) {
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, studyId)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, studyId)
  const query = useCTMSStudyOperations(studyId, resource)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [draft, setDraft] = useState<OperationDraft>(emptyOperationDraft)
  const create = useMutation({
    mutationFn: (payload: CTMSStudyOperationCreate) => ctmsApi.createStudyOperation(studyId, resource as CTMSStudyOperationResource, payload),
    onSuccess: async () => {
      setDraft(emptyOperationDraft())
      setDrawerOpen(false)
      await query.refetch()
    },
  })
  if (!canRead) return <AccessDeniedPage />
  const records = query.data?.items ?? []
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    create.mutate({ title: draft.title.trim(), record_subtype: optional(draft.recordSubtype), status: draft.status.trim(), site_id: optional(draft.siteId), subject_id: optional(draft.subjectId), owner_id: optional(draft.ownerId), start_at: toUtc(draft.startAt), end_at: toUtc(draft.endAt), amount: draft.amount ? Number(draft.amount) : undefined, currency: optional(draft.currency)?.toUpperCase(), details: {} })
  }

  return <PageContainer wide>
    <PageHeader
      title={title}
      description={<span><span className="block text-xs font-semibold uppercase tracking-wide text-primary">{eyebrow}</span><span className="block">{description}</span></span>}
      actions={resource && canManage ? <Button type="button" onClick={() => setDrawerOpen(true)}>Add item</Button> : undefined}
    />
    <DataTableShell label={`${title} records`} loading={query.isLoading} error={Boolean(query.error)} errorMessage={`${title} records could not be loaded.`} onRetry={() => void query.refetch()} empty={records.length === 0} emptyTitle={emptyTitle ?? `No ${title.toLowerCase()} records configured yet`} emptyDescription={emptyDescription ?? `Study-scoped ${title.toLowerCase()} records will appear here when this CTMS capability is configured.`}>
      <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
        {records.map((record) => <DetailCard key={record.id} title={record.title} description={record.record_subtype ?? record.resource_type} status={<span className="text-xs text-muted-foreground">{record.status}</span>}>
          <RecordDetails value={record} />
        </DetailCard>)}
      </div>
    </DataTableShell>
    {resource ? <Sheet open={drawerOpen} onOpenChange={(open) => { setDrawerOpen(open); if (!open) create.reset() }}><SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl"><SheetHeader className="pr-8"><SheetTitle>{`Add ${title}`}</SheetTitle><SheetDescription>{`Create a study-scoped ${title.toLowerCase()} record. The main panel remains focused on existing items.`}</SheetDescription></SheetHeader><div className="mt-2 pt-4"><StudyOperationForm resource={resource} draft={draft} onChange={(name, value) => setDraft((current) => ({ ...current, [name]: value }))} onSubmit={submit} pending={create.isPending} error={Boolean(create.error)} /></div></SheetContent></Sheet> : null}
  </PageContainer>
}

interface CatalogReportPageProps {
  studyId: string
  category: string
  reportType: string
  title: string
  description: string
}

export function CTMSCatalogReportPage({ studyId, category, reportType, title, description }: CatalogReportPageProps) {
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, studyId)
  const query = useCTMSCatalogReport(studyId, category, reportType)
  if (!canRead) return <AccessDeniedPage />
  const report = query.data
  const items = report?.items ?? report?.rows ?? []

  return <PageContainer wide>
    <PageHeader title={title} description={<span><span className="block text-xs font-semibold uppercase tracking-wide text-primary">CTMS Report</span><span className="block">{description}</span></span>} />
    {report ? <DetailCard title="Report summary" description={report.data_source === 'approved_projection' ? 'Approved read-only EDC projection' : 'CTMS operational records'}>
      <RecordDetails value={report.totals} />
    </DetailCard> : null}
    <DataTableShell label={`${title} report`} loading={query.isLoading} error={Boolean(query.error)} errorMessage={`${title} report could not be loaded.`} onRetry={() => void query.refetch()} empty={items.length === 0} emptyTitle={`No ${title.toLowerCase()} data available yet`} emptyDescription={report?.data_source === 'approved_projection' ? 'No approved clinical projection is currently available for this study.' : 'No study-scoped operational data is currently available for this report.'}>
      <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item, index) => <DetailCard key={String(item.id ?? item.projection_id ?? index)} title={String(item.title ?? item.activity ?? item.activity_type ?? item.query_id ?? `Record ${index + 1}`)} status={item.status ? <span className="text-xs text-muted-foreground">{String(item.status)}</span> : undefined}>
          <RecordDetails value={item} />
        </DetailCard>)}
      </div>
    </DataTableShell>
  </PageContainer>
}
