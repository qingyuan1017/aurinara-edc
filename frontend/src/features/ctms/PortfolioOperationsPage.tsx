import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, AlertTriangle, CalendarDays, CheckCircle2, Clock, DollarSign, FileText, RefreshCw, WalletCards } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { EmptyState, MetricCard, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { ctmsApi } from './api'
import { useCTMSCapabilityState } from './capabilities'
import { ResponsiveRecordList, type ResponsiveRecordColumn } from './components/ResponsiveRecordList'
import {
  type PortfolioContract,
  type PortfolioInvoice,
  type PortfolioMonitoringActivity,
  type PortfolioMonitoringFinding,
  type PortfolioPayable,
  type PortfolioPayment,
  usePortfolioContracts,
  usePortfolioContractSummary,
  usePortfolioFinancialReport,
  usePortfolioFinancialSummary,
  usePortfolioInvoices,
  usePortfolioMonitoringActivities,
  usePortfolioMonitoringFindings,
  usePortfolioMonitoringSummary,
  usePortfolioMonitoringWorkload,
  usePortfolioPayables,
  usePortfolioPayments,
} from './portfolio-api'

export type PortfolioOperationsView =
  | 'monitoring-visits'
  | 'monitoring-calendar'
  | 'monitoring-overdue'
  | 'monitoring-findings'
  | 'contracts'
  | 'contract-approvals'
  | 'contract-expiring'
  | 'financial-dashboard'
  | 'financial-payments'
  | 'financial-invoices'
  | 'financial-reports'

const PAGE_SIZE = 25
const contractTransitions: Record<string, string[]> = {
  draft: ['internal_review'],
  internal_review: ['negotiation', 'approved'],
  negotiation: ['internal_review', 'approved'],
  approved: ['executed'],
  executed: ['active'],
  active: ['closed'],
}

function money(value: string | number | null | undefined, currency: string) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value ?? 0))
}

function dateTime(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString()
}

function dateOnly(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleDateString()
}

function studyLabel(row: { study_code: string; study_title: string }) {
  return <span><span className="block font-semibold">{row.study_code}</span><span className="block max-w-52 truncate text-xs text-muted-foreground">{row.study_title}</span></span>
}

function siteLabel(row: { site_number?: string | null; site_name?: string | null }) {
  return row.site_number || row.site_name ? `${row.site_number ?? ''}${row.site_number && row.site_name ? ' · ' : ''}${row.site_name ?? ''}` : 'Study level'
}

function QueryState({ query, empty }: { query: { isLoading: boolean; isError: boolean; refetch: () => unknown }; empty: string }) {
  if (query.isLoading) return <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground" role="status">Loading {empty.toLowerCase()}…</div>
  if (query.isError) return <EmptyState title={`${empty} could not be loaded`} description="The portfolio service did not return data for the current authorized scope." action={<Button variant="outline" onClick={() => void query.refetch()}><RefreshCw className="mr-2 size-4" />Retry</Button>} />
  return null
}

function PortfolioBoundary({ children }: { children: React.ReactNode }) {
  const capability = useCTMSCapabilityState()
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)
  if (!canRead) return <AccessDeniedPage />
  if (capability.status !== 'ready') return <PageContainer><EmptyState title="CTMS portfolio operations are unavailable" description="The CTMS capability service is not ready. EDC workflows remain available." /></PageContainer>
  return <>{children}</>
}

function FilterBar({ search, setSearch, status, setStatus, options, placeholder = 'Search study or record…' }: { search: string; setSearch: (value: string) => void; status: string; setStatus: (value: string) => void; options: string[]; placeholder?: string }) {
  return <div className="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:flex-row">
    <Input aria-label="Search portfolio records" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={placeholder} className="sm:max-w-md" />
    <Select value={status} onValueChange={setStatus}>
      <SelectTrigger className="sm:w-56" aria-label="Filter by status"><SelectValue placeholder="All statuses" /></SelectTrigger>
      <SelectContent><SelectItem value="all">All statuses</SelectItem>{options.map((option) => <SelectItem key={option} value={option}>{option.replaceAll('_', ' ')}</SelectItem>)}</SelectContent>
    </Select>
  </div>
}

function ActivityActions({ activity }: { activity: PortfolioMonitoringActivity }) {
  const client = useQueryClient()
  const [mode, setMode] = useState<'assign' | 'reschedule' | null>(null)
  const [craId, setCraId] = useState(activity.assigned_cra_id ?? '')
  const [plannedDate, setPlannedDate] = useState(activity.planned_date.slice(0, 16))
  const [reason, setReason] = useState('')
  const mutation = useMutation({
    mutationFn: () => mode === 'assign'
      ? ctmsApi.assignMonitoringActivity(activity.id, { assigned_cra_id: craId })
      : ctmsApi.rescheduleMonitoringActivity(activity.id, { planned_date: new Date(plannedDate).toISOString(), reason }),
    onSuccess: async () => {
      setMode(null)
      setReason('')
      await client.invalidateQueries({ queryKey: ['ctms', 'portfolio', 'monitoring'] })
    },
  })
  const valid = mode === 'assign' ? Boolean(craId.trim()) : Boolean(plannedDate && reason.trim())
  return <div className="flex flex-wrap gap-2">
    <Button size="sm" variant="outline" onClick={() => setMode('assign')}>Assign</Button>
    <Button size="sm" variant="outline" onClick={() => setMode('reschedule')}>Reschedule</Button>
    <Button size="sm" asChild><Link to="/studies/$studyId/ctms/monitoring/visits" params={{ studyId: activity.study_id }}>Open</Link></Button>
    <Dialog open={mode !== null} onOpenChange={(open) => { if (!open) setMode(null) }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{mode === 'assign' ? 'Assign monitoring visit' : 'Reschedule monitoring visit'}</DialogTitle><DialogDescription>{activity.study_code} · {activity.activity_type}. The existing audited monitoring workflow will apply.</DialogDescription></DialogHeader>
        {mode === 'assign' ? <div className="space-y-2"><Label htmlFor={`cra-${activity.id}`}>CRA user ID</Label><Input id={`cra-${activity.id}`} value={craId} onChange={(event) => setCraId(event.target.value)} placeholder="Canonical user UUID" /></div> : <div className="space-y-4"><div className="space-y-2"><Label htmlFor={`date-${activity.id}`}>New planned date</Label><Input id={`date-${activity.id}`} type="datetime-local" value={plannedDate} onChange={(event) => setPlannedDate(event.target.value)} /></div><div className="space-y-2"><Label htmlFor={`reason-${activity.id}`}>Reason</Label><Textarea id={`reason-${activity.id}`} value={reason} onChange={(event) => setReason(event.target.value)} /></div></div>}
        {mutation.isError ? <p className="text-sm text-destructive">The action could not be completed. Confirm the record scope and lifecycle state.</p> : null}
        <DialogFooter><Button variant="outline" onClick={() => setMode(null)}>Cancel</Button><Button disabled={!valid || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Saving…' : 'Confirm'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
}

function ContractActions({ contract }: { contract: PortfolioContract }) {
  const client = useQueryClient()
  const allowed = contractTransitions[contract.status] ?? []
  const [open, setOpen] = useState(false)
  const [targetStatus, setTargetStatus] = useState(allowed[0] ?? '')
  const [reason, setReason] = useState('')
  const mutation = useMutation({
    mutationFn: () => ctmsApi.transitionFinancialContract(contract.study_id, contract.id, targetStatus, reason),
    onSuccess: async () => { setOpen(false); setReason(''); await client.invalidateQueries({ queryKey: ['ctms', 'portfolio', 'contracts'] }) },
  })
  return <div className="flex flex-wrap gap-2">
    {allowed.length ? <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Advance lifecycle</Button> : null}
    <Button size="sm" asChild><Link to="/studies/$studyId/ctms/financial-management/contracts" params={{ studyId: contract.study_id }}>Open</Link></Button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>Advance contract</DialogTitle><DialogDescription>{contract.contract_number} is currently {contract.status.replaceAll('_', ' ')}. Only lifecycle transitions already allowed by the study contract service are available.</DialogDescription></DialogHeader><div className="space-y-4"><div className="space-y-2"><Label htmlFor={`contract-target-${contract.id}`}>Next status</Label><Select value={targetStatus} onValueChange={setTargetStatus}><SelectTrigger id={`contract-target-${contract.id}`}><SelectValue /></SelectTrigger><SelectContent>{allowed.map((value) => <SelectItem key={value} value={value}>{value.replaceAll('_', ' ')}</SelectItem>)}</SelectContent></Select></div><div className="space-y-2"><Label htmlFor={`contract-reason-${contract.id}`}>Reason</Label><Textarea id={`contract-reason-${contract.id}`} value={reason} onChange={(event) => setReason(event.target.value)} /></div></div>{mutation.isError ? <p className="text-sm text-destructive">The transition is not allowed or the record is outside your mutation scope.</p> : null}<DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={!targetStatus || !reason.trim() || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Saving…' : 'Confirm transition'}</Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function PayableActions({ payable }: { payable: PortfolioPayable }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const mutation = useMutation({ mutationFn: () => ctmsApi.approvePayable(payable.study_id, payable.id, reason), onSuccess: async () => { setOpen(false); setReason(''); await client.invalidateQueries({ queryKey: ['ctms', 'portfolio', 'financials'] }) } })
  return <div className="flex flex-wrap gap-2">
    {payable.status === 'calculated' ? <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Approve</Button> : null}
    <Button size="sm" asChild><Link to="/studies/$studyId/ctms/financial-management/payments" params={{ studyId: payable.study_id }}>Open</Link></Button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>Approve payable</DialogTitle><DialogDescription>Approve {money(payable.net_amount, payable.currency)} for {payable.contract_number}. This action is audited.</DialogDescription></DialogHeader><div className="space-y-2"><Label htmlFor={`payable-reason-${payable.id}`}>Approval reason</Label><Textarea id={`payable-reason-${payable.id}`} value={reason} onChange={(event) => setReason(event.target.value)} /></div>{mutation.isError ? <p className="text-sm text-destructive">The payable could not be approved.</p> : null}<DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={!reason.trim() || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Approving…' : 'Approve'}</Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function ReconcilePaymentAction({ invoices }: { invoices: PortfolioInvoice[] }) {
  const client = useQueryClient()
  const outstanding = invoices.filter((invoice) => Number(invoice.outstanding_amount) > 0)
  const [open, setOpen] = useState(false)
  const [invoiceId, setInvoiceId] = useState('')
  const [paymentDate, setPaymentDate] = useState('')
  const [reference, setReference] = useState('')
  const [amount, setAmount] = useState('')
  const invoice = outstanding.find((item) => item.id === invoiceId)
  const mutation = useMutation({
    mutationFn: () => {
      if (!invoice) throw new Error('Select an invoice')
      const allocatedAmount = Number(amount)
      return ctmsApi.reconcileFinancialPayment(invoice.study_id, {
        party_name: invoice.party_name,
        direction: invoice.direction as 'payable' | 'receivable',
        payment_date: paymentDate,
        amount: allocatedAmount,
        currency: invoice.currency,
        reference,
        allocations: [{ invoice_id: invoice.id, allocated_amount: allocatedAmount }],
      })
    },
    onSuccess: async () => {
      setOpen(false)
      setInvoiceId('')
      setReference('')
      setAmount('')
      await client.invalidateQueries({ queryKey: ['ctms', 'portfolio', 'financials'] })
    },
  })
  const validAmount = Number(amount) > 0 && Boolean(invoice) && Number(amount) <= Number(invoice?.outstanding_amount ?? 0)
  return <><Button onClick={() => setOpen(true)}>Reconcile payment</Button><Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>Reconcile portfolio payment</DialogTitle><DialogDescription>Select an outstanding invoice. The existing study-scoped allocation service rejects cross-currency, overpayment, duplicate allocation, and party mismatches.</DialogDescription></DialogHeader><div className="space-y-4"><div className="space-y-2"><Label htmlFor="portfolio-payment-invoice">Invoice</Label><Select value={invoiceId} onValueChange={(value) => { const selected = outstanding.find((item) => item.id === value); setInvoiceId(value); setAmount(selected ? String(selected.outstanding_amount) : '') }}><SelectTrigger id="portfolio-payment-invoice"><SelectValue placeholder="Select an outstanding invoice" /></SelectTrigger><SelectContent>{outstanding.map((item) => <SelectItem key={item.id} value={item.id}>{item.study_code} · {item.invoice_number} · {money(item.outstanding_amount, item.currency)}</SelectItem>)}</SelectContent></Select></div><div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="portfolio-payment-date">Payment date</Label><Input id="portfolio-payment-date" type="date" value={paymentDate} onChange={(event) => setPaymentDate(event.target.value)} /></div><div className="space-y-2"><Label htmlFor="portfolio-payment-reference">Settlement reference</Label><Input id="portfolio-payment-reference" value={reference} onChange={(event) => setReference(event.target.value)} /></div><div className="space-y-2"><Label htmlFor="portfolio-payment-amount">Allocated amount</Label><Input id="portfolio-payment-amount" type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} /></div><div className="rounded-md border bg-muted/30 p-3 text-sm"><span className="block font-medium">{invoice?.party_name ?? 'No invoice selected'}</span><span className="text-muted-foreground">{invoice ? `${invoice.currency} · ${invoice.direction}` : 'Party, currency, and direction come from the invoice.'}</span></div></div></div>{mutation.isError ? <p className="text-sm text-destructive">Reconciliation failed. Confirm the settlement reference, amount, and current invoice balance.</p> : null}<DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={!invoice || !paymentDate || !reference.trim() || !validAmount || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Reconciling…' : 'Record settlement'}</Button></DialogFooter></DialogContent></Dialog></>
}

function FindingActions({ finding }: { finding: PortfolioMonitoringFinding }) {
  const client = useQueryClient()
  const [mode, setMode] = useState<'assign' | 'transition' | null>(null)
  const [ownerId, setOwnerId] = useState(finding.owner_id ?? '')
  const [reason, setReason] = useState('')
  const [resolution, setResolution] = useState('')
  const nextStatus = ({ Open: 'In Progress', 'Action Assigned': 'In Progress', 'In Progress': 'Pending Verification', 'Pending Verification': 'Closed' } as const)[finding.status as 'Open' | 'Action Assigned' | 'In Progress' | 'Pending Verification']
  const mutation = useMutation({
    mutationFn: () => mode === 'assign'
      ? ctmsApi.assignMonitoringFinding(finding.id, ownerId, reason)
      : ctmsApi.transitionMonitoringFinding(finding.id, nextStatus, reason, resolution || undefined),
    onSuccess: async () => { setMode(null); setReason(''); setResolution(''); await client.invalidateQueries({ queryKey: ['ctms', 'portfolio', 'monitoring', 'findings'] }) },
  })
  return <div className="flex flex-wrap gap-2">
    <Button size="sm" variant="outline" onClick={() => setMode('assign')}>Assign owner</Button>
    {nextStatus ? <Button size="sm" variant="outline" onClick={() => setMode('transition')}>Move to {nextStatus}</Button> : null}
    <Button size="sm" asChild><Link to="/studies/$studyId/ctms/monitoring/findings" params={{ studyId: finding.study_id }}>Open</Link></Button>
    <Dialog open={mode !== null} onOpenChange={(open) => { if (!open) setMode(null) }}><DialogContent><DialogHeader><DialogTitle>{mode === 'assign' ? 'Assign finding owner' : 'Advance finding'}</DialogTitle><DialogDescription>{mode === 'assign' ? `Assign ${finding.finding_code} to an active canonical user. Open findings move to Action Assigned.` : `${finding.finding_code} will move from ${finding.status} to ${nextStatus}.`}</DialogDescription></DialogHeader><div className="space-y-4">{mode === 'assign' ? <div className="space-y-2"><Label htmlFor={`finding-owner-${finding.id}`}>Owner user ID</Label><Input id={`finding-owner-${finding.id}`} value={ownerId} onChange={(event) => setOwnerId(event.target.value)} placeholder="Canonical user UUID" /></div> : null}<div className="space-y-2"><Label htmlFor={`finding-reason-${finding.id}`}>Reason</Label><Textarea id={`finding-reason-${finding.id}`} value={reason} onChange={(event) => setReason(event.target.value)} /></div>{mode === 'transition' && nextStatus === 'Closed' ? <div className="space-y-2"><Label htmlFor={`finding-resolution-${finding.id}`}>Resolution</Label><Textarea id={`finding-resolution-${finding.id}`} value={resolution} onChange={(event) => setResolution(event.target.value)} /></div> : null}</div>{mutation.isError ? <p className="text-sm text-destructive">The action could not be completed. Confirm the owner, scope, and lifecycle state.</p> : null}<DialogFooter><Button variant="outline" onClick={() => setMode(null)}>Cancel</Button><Button disabled={!reason.trim() || (mode === 'assign' && !ownerId.trim()) || (mode === 'transition' && nextStatus === 'Closed' && !resolution.trim()) || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? 'Saving…' : 'Confirm'}</Button></DialogFooter></DialogContent></Dialog>
  </div>
}

function MonitoringMetrics() {
  const summary = usePortfolioMonitoringSummary()
  const data = summary.data
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
    <MetricCard label="Upcoming" value={data?.upcoming ?? '—'} description="Scheduled future monitoring work" icon={<CalendarDays className="size-4" />} loading={summary.isLoading} />
    <MetricCard label="Overdue" value={data?.overdue ?? '—'} description="Past planned date and still open" icon={<Clock className="size-4" />} loading={summary.isLoading} />
    <MetricCard label="Unassigned" value={data?.unassigned ?? '—'} description="Visits without a CRA" icon={<Activity className="size-4" />} loading={summary.isLoading} />
    <MetricCard label="Open findings" value={data?.open_findings ?? '—'} description="Findings requiring follow-up" icon={<AlertTriangle className="size-4" />} loading={summary.isLoading} />
  </div>
}

function MonitoringVisitsPage({ overdueOnly = false }: { overdueOnly?: boolean }) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [activityType, setActivityType] = useState('all')
  const [modality, setModality] = useState('all')
  const [assignment, setAssignment] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const params = useMemo(() => ({
    page,
    page_size: PAGE_SIZE,
    search: search || undefined,
    status: status === 'all' ? undefined : status,
    activity_type: activityType === 'all' ? undefined : activityType,
    modality: modality === 'all' ? undefined : modality,
    unassigned: assignment === 'unassigned' ? true : undefined,
    date_from: dateFrom ? new Date(`${dateFrom}T00:00:00`).toISOString() : undefined,
    date_to: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
    overdue: overdueOnly || undefined,
  }), [page, search, status, activityType, modality, assignment, dateFrom, dateTo, overdueOnly])
  const query = usePortfolioMonitoringActivities(params)
  const columns: ResponsiveRecordColumn<PortfolioMonitoringActivity>[] = [
    { key: 'study', label: 'Study', render: studyLabel },
    { key: 'site', label: 'Site', render: siteLabel },
    { key: 'activity_type', label: 'Visit type' },
    { key: 'modality', label: 'Modality' },
    { key: 'planned_date', label: 'Planned', render: (row) => <span className={row.is_overdue ? 'font-semibold text-destructive' : ''}>{dateTime(row.planned_date)}{row.is_overdue ? ` · ${row.overdue_days}d overdue` : ''}</span> },
    { key: 'assigned_cra_name', label: 'CRA', render: (row) => row.assigned_cra_name ?? 'Unassigned' },
    { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.is_overdue ? 'Overdue' : row.status} /> },
    { key: 'open_findings', label: 'Open findings' },
    { key: 'report_status', label: 'Report', render: (row) => row.report_status ?? 'Not started' },
    { key: 'reschedule_count', label: 'Reschedules', render: (row) => row.reschedule_count },
    ...(overdueOnly ? [{ key: 'escalation_reference', label: 'Escalation', render: (row: PortfolioMonitoringActivity) => row.escalation_reference ?? '—' }] : []),
  ]
  const resetPage = () => setPage(1)
  return <PageContainer wide className="space-y-6"><PageHeader title={overdueOnly ? 'Overdue Visits' : 'All Monitoring Visits'} description={overdueOnly ? 'Monitoring activities past their planned date that are not completed or cancelled.' : 'Cross-study monitoring work for the current authorized scope.'} /><MonitoringMetrics /><FilterBar search={search} setSearch={(value) => { setSearch(value); resetPage() }} status={status} setStatus={(value) => { setStatus(value); resetPage() }} options={['Planned', 'Scheduled', 'In Progress', 'Rescheduled', 'Overdue', 'Completed', 'Cancelled']} /><div className="grid gap-3 rounded-lg border bg-card p-4 sm:grid-cols-2 xl:grid-cols-5"><Select value={activityType} onValueChange={(value) => { setActivityType(value); resetPage() }}><SelectTrigger aria-label="Filter by activity type"><SelectValue placeholder="All visit types" /></SelectTrigger><SelectContent><SelectItem value="all">All visit types</SelectItem>{['Qualification', 'Initiation', 'Routine', 'Close-out', 'Remote'].map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select><Select value={modality} onValueChange={(value) => { setModality(value); resetPage() }}><SelectTrigger aria-label="Filter by modality"><SelectValue placeholder="All modalities" /></SelectTrigger><SelectContent><SelectItem value="all">All modalities</SelectItem><SelectItem value="On-site">On-site</SelectItem><SelectItem value="Remote">Remote</SelectItem><SelectItem value="Hybrid">Hybrid</SelectItem></SelectContent></Select><Select value={assignment} onValueChange={(value) => { setAssignment(value); resetPage() }}><SelectTrigger aria-label="Filter by assignment"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All assignments</SelectItem><SelectItem value="unassigned">Unassigned only</SelectItem></SelectContent></Select><Input aria-label="Planned from" type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); resetPage() }} /><Input aria-label="Planned through" type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); resetPage() }} /></div><QueryState query={query} empty="Monitoring visits" />{query.data ? <ResponsiveRecordList label="Monitoring visits" rows={query.data.items} columns={columns} emptyLabel="Monitoring visits" rowKey={(row) => row.id} renderActions={(row) => <ActivityActions activity={row} />} pagination={{ page, pageSize: PAGE_SIZE, total: query.data.total, onPageChange: setPage, isLoading: query.isFetching }} /> : null}</PageContainer>
}

function MonitoringCalendarPage() {
  const workload = usePortfolioMonitoringWorkload({ page_size: 100 })
  const calendar = usePortfolioMonitoringActivities({ page_size: 100 })
  const columns = [
    { key: 'cra_name', label: 'CRA' }, { key: 'total', label: 'Total visits' }, { key: 'upcoming', label: 'Upcoming' }, { key: 'overdue', label: 'Overdue' }, { key: 'in_progress', label: 'In progress' }, { key: 'completed', label: 'Completed' },
  ]
  const calendarColumns: ResponsiveRecordColumn<PortfolioMonitoringActivity>[] = [
    { key: 'planned_date', label: 'Date', render: (row) => dateTime(row.planned_date) }, { key: 'study', label: 'Study', render: studyLabel }, { key: 'site', label: 'Site', render: siteLabel }, { key: 'activity_type', label: 'Visit type' }, { key: 'assigned_cra_name', label: 'CRA', render: (row) => row.assigned_cra_name ?? 'Unassigned' }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.is_overdue ? 'Overdue' : row.status} /> },
  ]
  return <PageContainer wide className="space-y-6"><PageHeader title="CRA Calendar & Workload" description="Visit-based workload across accessible studies. Counts represent assigned monitoring visits, not staff capacity hours." /><MonitoringMetrics /><Tabs defaultValue="calendar"><TabsList><TabsTrigger value="calendar">Calendar</TabsTrigger><TabsTrigger value="workload">Workload</TabsTrigger></TabsList><TabsContent value="calendar" className="mt-4"><QueryState query={calendar} empty="Monitoring calendar" />{calendar.data ? <ResponsiveRecordList label="Monitoring calendar" rows={calendar.data.items} columns={calendarColumns} emptyLabel="Monitoring calendar" rowKey={(row) => row.id} renderActions={(row) => <ActivityActions activity={row} />} /> : null}</TabsContent><TabsContent value="workload" className="mt-4"><QueryState query={workload} empty="CRA workload" />{workload.data ? <ResponsiveRecordList label="CRA workload" rows={workload.data.items} columns={columns} emptyLabel="CRA workload" rowKey={(row) => row.cra_id ?? 'unassigned'} /> : null}</TabsContent></Tabs></PageContainer>
}

function MonitoringFindingsPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [severity, setSeverity] = useState('all')
  const [dueView, setDueView] = useState('all')
  const query = usePortfolioMonitoringFindings({ page, page_size: PAGE_SIZE, search: search || undefined, status: status === 'all' ? undefined : status, severity: severity === 'all' ? undefined : severity, overdue: dueView === 'overdue' ? true : undefined })
  const columns: ResponsiveRecordColumn<PortfolioMonitoringFinding>[] = [
    { key: 'finding_code', label: 'Finding', render: (row) => <span><span className="block font-semibold">{row.finding_code}</span><span className="block text-xs text-muted-foreground">{row.category}</span></span> },
    { key: 'study', label: 'Study', render: studyLabel }, { key: 'site', label: 'Site', render: siteLabel },
    { key: 'severity', label: 'Severity', render: (row) => <StatusBadge status={row.severity} /> },
    { key: 'owner_name', label: 'Owner', render: (row) => row.owner_name ?? row.responsible_party ?? 'Unassigned' },
    { key: 'due_date', label: 'Due', render: (row) => <span className={row.is_overdue ? 'font-semibold text-destructive' : ''}>{dateTime(row.due_date)}</span> },
    { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> }, { key: 'open_actions', label: 'Open actions' },
  ]
  return <PageContainer wide className="space-y-6"><PageHeader title="Cross-Study Findings" description="Monitoring findings and follow-up actions across the current authorized scope." /><MonitoringMetrics /><FilterBar search={search} setSearch={(value) => { setSearch(value); setPage(1) }} status={status} setStatus={(value) => { setStatus(value); setPage(1) }} options={['Open', 'Action Assigned', 'In Progress', 'Pending Verification', 'Closed', 'Cancelled']} /><div className="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:flex-row"><Select value={severity} onValueChange={(value) => { setSeverity(value); setPage(1) }}><SelectTrigger className="sm:w-56" aria-label="Filter by severity"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All severities</SelectItem>{['Critical', 'Major', 'Minor'].map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select><Select value={dueView} onValueChange={(value) => { setDueView(value); setPage(1) }}><SelectTrigger className="sm:w-56" aria-label="Filter findings by due date"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All due dates</SelectItem><SelectItem value="overdue">Overdue only</SelectItem></SelectContent></Select></div><QueryState query={query} empty="Monitoring findings" />{query.data ? <ResponsiveRecordList label="Monitoring findings" rows={query.data.items} columns={columns} emptyLabel="Monitoring findings" rowKey={(row) => row.id} renderActions={(row) => <FindingActions finding={row} />} pagination={{ page, pageSize: PAGE_SIZE, total: query.data.total, onPageChange: setPage, isLoading: query.isFetching }} /> : null}</PageContainer>
}

function ContractMetrics() {
  const query = usePortfolioContractSummary()
  const data = query.data
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="All contracts" value={data?.total ?? '—'} description="Authorized contract register" icon={<FileText className="size-4" />} loading={query.isLoading} /><MetricCard label="In review" value={(data?.internal_review ?? 0) + (data?.negotiation ?? 0)} description="Internal review or negotiation" icon={<Clock className="size-4" />} loading={query.isLoading} /><MetricCard label="Awaiting execution" value={data?.approved_awaiting_execution ?? '—'} description="Approved contracts" icon={<CheckCircle2 className="size-4" />} loading={query.isLoading} /><MetricCard label="Expiring in 30 days" value={data?.expiring_30_days ?? '—'} description={`${data?.expired ?? 0} already expired`} icon={<AlertTriangle className="size-4" />} loading={query.isLoading} /></div>
}

function ContractsPage({ mode = 'all' }: { mode?: 'all' | 'approvals' | 'expiring' }) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState(mode === 'approvals' ? 'internal_review' : 'all')
  const [expiryView, setExpiryView] = useState('30')
  const [direction, setDirection] = useState('all')
  const [currency, setCurrency] = useState('')
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: search || undefined,
    status: status === 'all' ? undefined : status,
    direction: direction === 'all' ? undefined : direction,
    currency: currency.trim().length === 3 ? currency.trim().toUpperCase() : undefined,
    expires_within_days: mode === 'expiring' && expiryView !== 'expired' ? Number(expiryView) : undefined,
    expired: mode === 'expiring' && expiryView === 'expired' ? true : undefined,
  }
  const query = usePortfolioContracts(params)
  const title = mode === 'all' ? 'All Contracts' : mode === 'approvals' ? 'Reviews & Approvals' : 'Expiring Contracts'
  const columns: ResponsiveRecordColumn<PortfolioContract>[] = [
    { key: 'contract_number', label: 'Contract', render: (row) => <span><span className="block font-semibold">{row.contract_number}</span><span className="block max-w-52 truncate text-xs text-muted-foreground">{row.title}</span></span> },
    { key: 'study', label: 'Study', render: studyLabel }, { key: 'site', label: 'Site', render: siteLabel }, { key: 'party_name', label: 'Party' },
    { key: 'contract_type', label: 'Type', render: (row) => row.contract_type.replaceAll('_', ' ') }, { key: 'direction', label: 'Direction' }, { key: 'owner_name', label: 'Owner', render: (row) => row.owner_name ?? 'Unassigned' }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> },
    { key: 'total_value', label: 'Value', render: (row) => row.total_value == null ? '—' : money(row.total_value, row.currency) },
    { key: 'effective_to', label: 'Expires', render: (row) => <span className={(row.days_to_expiry ?? 999) < 0 ? 'font-semibold text-destructive' : ''}>{dateOnly(row.effective_to)}{row.days_to_expiry != null ? ` · ${row.days_to_expiry}d` : ''}</span> },
  ]
  return <PageContainer wide className="space-y-6"><PageHeader title={title} description={mode === 'approvals' ? 'Contracts requiring review, negotiation, approval, or execution.' : mode === 'expiring' ? 'Active or executed agreement versions grouped by their applicable expiration date.' : 'Cross-study contract register with current applicable version details.'} /><ContractMetrics />{mode === 'approvals' ? <Tabs value={status} onValueChange={(value) => { setStatus(value); setPage(1) }}><TabsList><TabsTrigger value="internal_review">Internal Review</TabsTrigger><TabsTrigger value="negotiation">Negotiation</TabsTrigger><TabsTrigger value="approved">Approved Awaiting Execution</TabsTrigger></TabsList></Tabs> : null}{mode === 'expiring' ? <Tabs value={expiryView} onValueChange={(value) => { setExpiryView(value); setPage(1) }}><TabsList><TabsTrigger value="expired">Expired</TabsTrigger><TabsTrigger value="30">Within 30 days</TabsTrigger><TabsTrigger value="60">Within 60 days</TabsTrigger><TabsTrigger value="90">Within 90 days</TabsTrigger></TabsList></Tabs> : null}<FilterBar search={search} setSearch={(value) => { setSearch(value); setPage(1) }} status={status} setStatus={(value) => { setStatus(value); setPage(1) }} options={['draft', 'internal_review', 'negotiation', 'approved', 'executed', 'active', 'closed']} placeholder="Search contract, party, or study…" /><div className="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:flex-row"><Select value={direction} onValueChange={(value) => { setDirection(value); setPage(1) }}><SelectTrigger className="sm:w-56" aria-label="Filter by contract direction"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All directions</SelectItem><SelectItem value="payable">Payable</SelectItem><SelectItem value="receivable">Receivable</SelectItem></SelectContent></Select><Input className="sm:w-40" aria-label="Filter by currency" value={currency} maxLength={3} onChange={(event) => { setCurrency(event.target.value); setPage(1) }} placeholder="Currency (USD)" /></div><QueryState query={query} empty="Contracts" />{query.data ? <ResponsiveRecordList label="Contracts" rows={query.data.items} columns={columns} emptyLabel="Contracts" rowKey={(row) => row.id} renderActions={(row) => <ContractActions contract={row} />} pagination={{ page, pageSize: PAGE_SIZE, total: query.data.total, onPageChange: setPage, isLoading: query.isFetching }} /> : null}</PageContainer>
}

function FinancialDashboard() {
  const query = usePortfolioFinancialSummary()
  return <PageContainer wide className="space-y-6"><PageHeader title="Portfolio Financial Dashboard" description="Ledger-derived financial position by currency. Unlike currencies are never combined." /><QueryState query={query} empty="Financial summary" />{query.data?.currencies.length ? <div className="space-y-5">{query.data.currencies.map((row) => <Card key={row.currency}><CardHeader><CardTitle>{row.currency}</CardTitle></CardHeader><CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Approved budget" value={money(row.approved_budget, row.currency)} description="Approved budget versions" icon={<WalletCards className="size-4" />} /><MetricCard label="Contracted value" value={money(row.contracted, row.currency)} description="Executed contract versions" icon={<FileText className="size-4" />} /><MetricCard label="Calculated payables" value={money(row.calculated_payables, row.currency)} description="Awaiting approval" icon={<Clock className="size-4" />} /><MetricCard label="Approved payables" value={money(row.approved_payables, row.currency)} description="Approved obligations" icon={<CheckCircle2 className="size-4" />} /><MetricCard label="Invoiced" value={money(row.invoiced, row.currency)} description="Matched invoice value" icon={<FileText className="size-4" />} /><MetricCard label="Paid" value={money(row.paid, row.currency)} description="Settled payment value" icon={<DollarSign className="size-4" />} /><MetricCard label="Outstanding" value={money(row.outstanding, row.currency)} description={`${money(row.overdue, row.currency)} overdue`} icon={<AlertTriangle className="size-4" />} /><MetricCard label="Budget variance" value={money(row.budget_variance, row.currency)} description="Approved budget less contracted" icon={<Activity className="size-4" />} /></CardContent></Card>)}</div> : !query.isLoading && !query.isError ? <EmptyState title="No financial ledger activity" description="No approved budgets, executed contracts, payables, invoices, or payments are visible in the current scope." /> : null}</PageContainer>
}

function PayablesAndSettlementPage() {
  const [page, setPage] = useState(1)
  const [payableStatus, setPayableStatus] = useState('calculated')
  const payables = usePortfolioPayables({ page, page_size: PAGE_SIZE, status: payableStatus })
  const payments = usePortfolioPayments({ page, page_size: PAGE_SIZE })
  const invoices = usePortfolioInvoices({ page_size: 100 })
  const payableColumns: ResponsiveRecordColumn<PortfolioPayable>[] = [
    { key: 'study', label: 'Study', render: studyLabel }, { key: 'contract_number', label: 'Contract' }, { key: 'party_name', label: 'Party' },
    { key: 'net_amount', label: 'Net payable', render: (row) => money(row.net_amount, row.currency) }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> }, { key: 'created_at', label: 'Created', render: (row) => dateTime(row.created_at) },
  ]
  const paymentColumns: ResponsiveRecordColumn<PortfolioPayment>[] = [
    { key: 'study', label: 'Study', render: studyLabel }, { key: 'reference', label: 'Reference' }, { key: 'party_name', label: 'Party' },
    { key: 'payment_date', label: 'Payment date', render: (row) => dateOnly(row.payment_date) }, { key: 'amount', label: 'Amount', render: (row) => money(row.amount, row.currency) }, { key: 'allocated_amount', label: 'Allocated', render: (row) => money(row.allocated_amount, row.currency) }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> },
  ]
  return <PageContainer wide className="space-y-6"><PageHeader title="Payables & Settlement" description="Approve calculated obligations and review payment settlement and allocation across studies." actions={<ReconcilePaymentAction invoices={invoices.data?.items ?? []} />} /><Tabs defaultValue="payables"><TabsList><TabsTrigger value="payables">Payables</TabsTrigger><TabsTrigger value="settlement">Settlement</TabsTrigger></TabsList><TabsContent value="payables" className="mt-4 space-y-4"><Tabs value={payableStatus} onValueChange={(value) => { setPayableStatus(value); setPage(1) }}><TabsList><TabsTrigger value="calculated">Awaiting Approval</TabsTrigger><TabsTrigger value="approved">Approved</TabsTrigger><TabsTrigger value="partially_invoiced">Partially Invoiced</TabsTrigger></TabsList></Tabs><QueryState query={payables} empty="Payables" />{payables.data ? <ResponsiveRecordList label="Portfolio payables" rows={payables.data.items} columns={payableColumns} emptyLabel="Payables" rowKey={(row) => row.id} renderActions={(row) => <PayableActions payable={row} />} pagination={{ page, pageSize: PAGE_SIZE, total: payables.data.total, onPageChange: setPage, isLoading: payables.isFetching }} /> : null}</TabsContent><TabsContent value="settlement" className="mt-4"><QueryState query={payments} empty="Payments" />{payments.data ? <ResponsiveRecordList label="Portfolio payments" rows={payments.data.items} columns={paymentColumns} emptyLabel="Payments" rowKey={(row) => row.id} renderActions={(row) => <Button size="sm" asChild><Link to="/studies/$studyId/ctms/financial-management/payments" params={{ studyId: row.study_id }}>Open reconciliation</Link></Button>} pagination={{ page, pageSize: PAGE_SIZE, total: payments.data.total, onPageChange: setPage, isLoading: payments.isFetching }} /> : null}</TabsContent></Tabs></PageContainer>
}

function InvoicesPage() {
  const [page, setPage] = useState(1)
  const [view, setView] = useState('all')
  const query = usePortfolioInvoices({ page, page_size: PAGE_SIZE, overdue: view === 'overdue' ? true : undefined, due_within_days: view === 'due_soon' ? 30 : undefined, status: view !== 'all' && view !== 'overdue' && view !== 'due_soon' ? view : undefined })
  const columns: ResponsiveRecordColumn<PortfolioInvoice>[] = [
    { key: 'study', label: 'Study', render: studyLabel }, { key: 'invoice_number', label: 'Invoice' }, { key: 'contract_number', label: 'Contract' }, { key: 'party_name', label: 'Party' },
    { key: 'due_date', label: 'Due', render: (row) => <span className={row.is_overdue ? 'font-semibold text-destructive' : ''}>{dateOnly(row.due_date)}{row.is_overdue ? ` · ${row.days_overdue}d overdue` : ''}</span> },
    { key: 'amount', label: 'Amount', render: (row) => money(row.amount, row.currency) }, { key: 'outstanding_amount', label: 'Outstanding', render: (row) => money(row.outstanding_amount, row.currency) }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> },
  ]
  return <PageContainer wide className="space-y-6"><PageHeader title="Invoice Queue" description="Cross-study invoice coverage, due dates, and settlement status." /><Tabs value={view} onValueChange={(value) => { setView(value); setPage(1) }}><TabsList><TabsTrigger value="matched">Matched</TabsTrigger><TabsTrigger value="partially_paid">Partially Paid</TabsTrigger><TabsTrigger value="paid">Paid</TabsTrigger><TabsTrigger value="due_soon">Due Soon</TabsTrigger><TabsTrigger value="overdue">Overdue</TabsTrigger><TabsTrigger value="all">All</TabsTrigger></TabsList></Tabs><QueryState query={query} empty="Invoices" />{query.data ? <ResponsiveRecordList label="Portfolio invoices" rows={query.data.items} columns={columns} emptyLabel="Invoices" rowKey={(row) => row.id} renderActions={(row) => <Button size="sm" asChild><Link to="/studies/$studyId/ctms/financial-management/invoices" params={{ studyId: row.study_id }}>Open</Link></Button>} pagination={{ page, pageSize: PAGE_SIZE, total: query.data.total, onPageChange: setPage, isLoading: query.isFetching }} /> : null}</PageContainer>
}

function FinancialReportsPage() {
  const [page, setPage] = useState(1)
  const [groupBy, setGroupBy] = useState('study')
  const [groupKey, setGroupKey] = useState('')
  const [studyId, setStudyId] = useState('')
  const [currency, setCurrency] = useState('')
  const query = usePortfolioFinancialReport({ page, page_size: PAGE_SIZE, group_by: groupBy, group_key: groupKey || undefined, study_id: /^[0-9a-f-]{36}$/i.test(studyId) ? studyId : undefined, currency: currency.trim().length === 3 ? currency.trim().toUpperCase() : undefined })
  const columns = [
    { key: 'study', label: 'Study', render: studyLabel }, { key: 'currency', label: 'Currency' },
    ...(groupBy === 'study' ? [] : [{ key: 'group_label', label: groupBy.replaceAll('_', ' '), render: (row: NonNullable<typeof query.data>['items'][number]) => row.group_label }]),
    { key: 'approved_budget', label: 'Approved budget', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.approved_budget, row.currency) },
    { key: 'contracted', label: 'Contracted', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.contracted, row.currency) },
    { key: 'approved_payables', label: 'Approved', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.approved_payables, row.currency) },
    { key: 'invoiced', label: 'Invoiced', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.invoiced, row.currency) },
    { key: 'paid', label: 'Paid', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.paid, row.currency) },
    { key: 'outstanding', label: 'Outstanding', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.outstanding, row.currency) },
    { key: 'budget_variance', label: 'Variance', render: (row: NonNullable<typeof query.data>['items'][number]) => money(row.budget_variance, row.currency) },
  ]
  return <PageContainer wide className="space-y-6"><PageHeader title="Budget & Financial Reports" description="Compare attributable portfolio ledger values by study, organization, site, direction, or cost category. Currency values remain separate." /><div className="grid gap-3 rounded-lg border bg-card p-4 sm:grid-cols-2 xl:grid-cols-4"><Select value={groupBy} onValueChange={(value) => { setGroupBy(value); setGroupKey(''); setPage(1) }}><SelectTrigger aria-label="Group financial report"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="study">Group by study</SelectItem><SelectItem value="organization">Group by organization</SelectItem><SelectItem value="site">Group by site</SelectItem><SelectItem value="direction">Group by direction</SelectItem><SelectItem value="cost_category">Group by cost category</SelectItem></SelectContent></Select><Input aria-label="Filter report by study ID" value={studyId} onChange={(event) => { setStudyId(event.target.value); setPage(1) }} placeholder="Study UUID" /><Input aria-label="Filter report by currency" value={currency} maxLength={3} onChange={(event) => { setCurrency(event.target.value); setPage(1) }} placeholder="Currency (USD)" />{groupBy !== 'study' ? <Input aria-label="Filter report by group key" value={groupKey} onChange={(event) => { setGroupKey(event.target.value); setPage(1) }} placeholder={groupBy === 'direction' ? 'payable or receivable' : groupBy === 'cost_category' ? 'Cost category' : `${groupBy} UUID`} /> : null}</div><QueryState query={query} empty="Financial reports" />{query.data ? <ResponsiveRecordList label="Portfolio financial report" rows={query.data.items} columns={columns} emptyLabel="Financial reports" rowKey={(row) => `${row.study_id}-${row.currency}-${row.group_key}`} renderActions={(row) => <Button size="sm" asChild><Link to="/studies/$studyId/ctms/financial-management/reports" params={{ studyId: row.study_id }}>Open report</Link></Button>} pagination={{ page, pageSize: PAGE_SIZE, total: query.data.total, onPageChange: setPage, isLoading: query.isFetching }} /> : null}</PageContainer>
}

export function PortfolioOperationsPage({ view }: { view: PortfolioOperationsView }) {
  let content: React.ReactNode
  switch (view) {
    case 'monitoring-visits': content = <MonitoringVisitsPage />; break
    case 'monitoring-calendar': content = <MonitoringCalendarPage />; break
    case 'monitoring-overdue': content = <MonitoringVisitsPage overdueOnly />; break
    case 'monitoring-findings': content = <MonitoringFindingsPage />; break
    case 'contracts': content = <ContractsPage />; break
    case 'contract-approvals': content = <ContractsPage mode="approvals" />; break
    case 'contract-expiring': content = <ContractsPage mode="expiring" />; break
    case 'financial-dashboard': content = <FinancialDashboard />; break
    case 'financial-payments': content = <PayablesAndSettlementPage />; break
    case 'financial-invoices': content = <InvoicesPage />; break
    case 'financial-reports': content = <FinancialReportsPage />; break
  }
  return <PortfolioBoundary>{content}</PortfolioBoundary>
}
