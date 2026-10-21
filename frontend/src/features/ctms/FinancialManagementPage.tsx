import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowUpRight, Banknote, Download, FileText, Landmark, Plus, ReceiptText, Upload } from 'lucide-react'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { DataTableShell, PageContainer } from '@/components/patterns'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import {
  ctmsApi,
  ctmsKeys,
  useCTMSContractVersions,
  useCTMSContractAudit,
  useCTMSContractDocuments,
  useCTMSFinancialBudgets,
  useCTMSFinancialConfigurationOptions,
  useCTMSFinancialContracts,
  useCTMSFinancialInvoices,
  useCTMSFinancialOverview,
  useCTMSFinancialPayables,
  useCTMSFinancialPayments,
  useCTMSFinancialReport,
  useCTMSPaymentTerms,
  useCTMSStudyEntities,
  useCTMSStudyProfile,
  type CTMSContractType,
  type CTMSFinancialBudget,
  type CTMSFinancialContract,
  type CTMSFinancialDirection,
  type CTMSPaymentTerm,
} from './api'

type FinancialTab = 'overview' | 'contracts' | 'budgets' | 'payments' | 'invoices' | 'reporting'
type FinancialDrawer = 'contract' | 'budget' | 'event' | 'invoice' | 'payment'
type ContractTab = 'details' | 'documents' | 'budget' | 'payment-terms' | 'amendments' | 'audit-trail'

function money(value: string | number | null | undefined, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value ?? 0))
}

function compactMoney(value: string | number | null | undefined, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, notation: 'compact', minimumFractionDigits: 0, maximumFractionDigits: 1 }).format(Number(value ?? 0)).replace(/\.0([KMBT])$/, '$1')
}

function percent(value: number, total: number) {
  return total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0
}

function displayCode(value: unknown, fallback = 'Payment request') {
  const code = String(value ?? '').trim()
  if (!code) return fallback
  return code.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function parseDimensions(value: string) {
  return Object.fromEntries(value.split(',').map((item) => item.trim()).filter(Boolean).map((item) => {
    const [key, ...rest] = item.split('=')
    return [key.trim(), rest.join('=').trim()]
  }).filter(([key, value]) => key && value))
}

function Field({ label, value, onChange, type = 'text', required = false }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean }) {
  const id = `financial-${label.toLowerCase().replaceAll(' ', '-')}`
  return <div className="space-y-2"><Label htmlFor={id}>{label}{required ? ' *' : ''}</Label><Input id={id} type={type} value={value} required={required} onChange={(event) => onChange(event.target.value)} /></div>
}

function FinancialMetric({ label, value, note }: { label: string; value: string; note: string }) {
  return <Card className="border-border/70 shadow-sm"><CardContent className="p-5"><p className="text-sm font-medium text-muted-foreground">{label}</p><p className="mt-2 text-3xl font-semibold tracking-tight text-foreground">{value}</p><p className="mt-2 text-xs text-muted-foreground">{note}</p></CardContent></Card>
}

function Status({ value }: { value: string }) {
  const variant = value === 'paid' || value === 'executed' || value === 'settled' ? 'success' : value === 'approved' || value.includes('partial') ? 'warning' : 'outline'
  return <Badge variant={variant} className="capitalize">{value.replaceAll('_', ' ')}</Badge>
}

const emptyContract = {
  contractNumber: '', title: '', contractType: 'clinical_trial_agreement' as CTMSContractType,
  direction: 'payable' as CTMSFinancialDirection, partyName: '', organizationId: '', siteId: '', currency: 'USD',
  effectiveFrom: '', totalValue: '', holdback: '0', termCode: '', termDescription: '',
  paymentMethod: 'visit_based' as CTMSPaymentTerm['payment_method'], triggerCode: '', unitRate: '', costCategory: '', billingUnit: '', visitDefinitionId: '', formDefinitionId: '', labCode: '', invoiceCategory: '', dimensions: '',
  executeNow: false, executionReason: '',
}

function ContractForm({ studyId, onSaved }: { studyId: string; onSaved: () => void }) {
  const [draft, setDraft] = useState(emptyContract)
  const organizations = (useCTMSStudyEntities(studyId).data?.items ?? []).filter((assignment) => assignment.entity.entity_type === 'participating_organization' && assignment.entity.active)
  const configuration = useCTMSFinancialConfigurationOptions(studyId)
  const mutation = useMutation({
    mutationFn: async () => {
      const contract = await ctmsApi.createFinancialContract(studyId, {
        contract_number: draft.contractNumber.trim(), title: draft.title.trim(), contract_type: draft.contractType,
        direction: draft.direction, party_name: draft.partyName.trim(), organization_id: draft.organizationId || undefined, site_id: draft.siteId.trim() || undefined,
        currency: draft.currency.trim().toUpperCase(),
      })
      const version = await ctmsApi.createContractVersion(studyId, contract.id, {
        effective_from: draft.effectiveFrom, total_value: Number(draft.totalValue), holdback_percent: Number(draft.holdback),
      })
      await ctmsApi.createPaymentTerm(studyId, version.id, {
        code: draft.termCode, description: draft.termDescription, payment_method: draft.paymentMethod,
        trigger_code: draft.triggerCode, unit_rate: Number(draft.unitRate), cost_category: draft.costCategory || undefined,
        billing_unit: draft.billingUnit || undefined, visit_definition_id: draft.visitDefinitionId || undefined,
        form_definition_id: draft.formDefinitionId || undefined, lab_code: draft.labCode || undefined,
        invoice_category: draft.invoiceCategory || undefined, dimensions_json: parseDimensions(draft.dimensions),
      })
      if (draft.executeNow) await ctmsApi.executeContractVersion(studyId, version.id, draft.executionReason)
      return contract
    },
    onSuccess: () => { setDraft(emptyContract); onSaved() },
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((current) => ({ ...current, [key]: value }))
  return <form className="space-y-5" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Contract number" value={draft.contractNumber} onChange={(value) => set('contractNumber', value)} required />
      <Field label="Title" value={draft.title} onChange={(value) => set('title', value)} required />
      <div className="space-y-2"><Label>Contract type</Label><select className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.contractType} onChange={(event) => set('contractType', event.target.value as CTMSContractType)}><option value="sponsor_agreement">Sponsor agreement</option><option value="clinical_trial_agreement">Clinical trial agreement</option><option value="vendor_agreement">Vendor agreement</option></select></div>
      <div className="space-y-2"><Label>Direction</Label><select className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.direction} onChange={(event) => set('direction', event.target.value as CTMSFinancialDirection)}><option value="payable">Accounts payable</option><option value="receivable">Accounts receivable</option></select></div>
      <div className="space-y-2 sm:col-span-2"><Label>Participating organization</Label><select className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.organizationId} onChange={(event) => { const organization = organizations.find((item) => item.entity_id === event.target.value); setDraft((current) => ({ ...current, organizationId: event.target.value, partyName: organization?.entity.name ?? current.partyName })) }}><option value="">No organization link</option>{organizations.map((item) => <option key={item.entity_id} value={item.entity_id}>{item.entity.code} · {item.entity.name}</option>)}</select><p className="text-xs text-muted-foreground">Links the agreement to CTMS organization master data assigned to this study.</p></div>
      <Field label="Party name" value={draft.partyName} onChange={(value) => set('partyName', value)} required />
      <Field label="Site ID" value={draft.siteId} onChange={(value) => set('siteId', value)} />
      <Field label="Currency" value={draft.currency} onChange={(value) => set('currency', value)} required />
      <Field label="Effective from" type="date" value={draft.effectiveFrom} onChange={(value) => set('effectiveFrom', value)} required />
      <Field label="Contract value" type="number" value={draft.totalValue} onChange={(value) => set('totalValue', value)} required />
      <Field label="Holdback percent" type="number" value={draft.holdback} onChange={(value) => set('holdback', value)} required />
    </div>
    <div className="rounded-lg border p-4"><h3 className="mb-1 font-medium">Initial charge item</h3><p className="mb-4 text-xs text-muted-foreground">Add more configurable charge items from the contract Payment Terms tab.</p><div className="grid gap-4 sm:grid-cols-2">
      <Field label="Term code" value={draft.termCode} onChange={(value) => set('termCode', value)} required />
      <Field label="Term description" value={draft.termDescription} onChange={(value) => set('termDescription', value)} required />
      <div className="space-y-2"><Label htmlFor="initial-charge-method">Calculation method</Label><select id="initial-charge-method" className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.paymentMethod} onChange={(event) => setDraft((current) => ({ ...current, paymentMethod: event.target.value as CTMSPaymentTerm['payment_method'], visitDefinitionId: '', formDefinitionId: '', labCode: '', invoiceCategory: '' }))}><option value="fixed">Fixed amount</option><option value="visit_based">By visit</option><option value="crf_based">By CRF</option><option value="invoice_based">By invoice</option><option value="lab_based">By lab</option><option value="quantity_based">By quantity</option><option value="procedure_based">By procedure</option><option value="milestone_based">By milestone</option><option value="recurring">Recurring</option><option value="pass_through">Pass-through</option><option value="manual_adjustment">Manual adjustment</option></select></div>
      <Field label="Payment rule code" value={draft.triggerCode} onChange={(value) => set('triggerCode', value)} required />
      <Field label="Unit rate" type="number" value={draft.unitRate} onChange={(value) => set('unitRate', value)} required />
      <Field label="Cost category" value={draft.costCategory} onChange={(value) => set('costCategory', value)} />
      <Field label="Billing unit" value={draft.billingUnit} onChange={(value) => set('billingUnit', value)} required={draft.paymentMethod === 'quantity_based'} />
      {draft.paymentMethod === 'visit_based' ? <div className="space-y-2 sm:col-span-2"><Label htmlFor="initial-charge-visit">EDC visit definition</Label><select id="initial-charge-visit" className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.visitDefinitionId} onChange={(event) => set('visitDefinitionId', event.target.value)}><option value="">Any completed visit matching the rule</option>{(configuration.data?.visits ?? []).map((item) => <option key={item.id} value={item.id}>{item.code} · {item.label} · design v{item.version}</option>)}</select></div> : null}
      {draft.paymentMethod === 'crf_based' || draft.paymentMethod === 'lab_based' ? <div className="space-y-2 sm:col-span-2"><Label htmlFor="initial-charge-form">EDC CRF definition{draft.paymentMethod === 'crf_based' ? ' *' : ''}</Label><select id="initial-charge-form" required={draft.paymentMethod === 'crf_based'} className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.formDefinitionId} onChange={(event) => set('formDefinitionId', event.target.value)}><option value="">{draft.paymentMethod === 'lab_based' ? 'No CRF restriction' : 'Select a published CRF'}</option>{(configuration.data?.forms ?? []).map((item) => <option key={item.id} value={item.id}>{item.code} · {item.label} · design v{item.version}</option>)}</select></div> : null}
      {draft.paymentMethod === 'lab_based' ? <Field label="Lab code" value={draft.labCode} onChange={(value) => set('labCode', value)} required={!draft.formDefinitionId} /> : null}
      {draft.paymentMethod === 'invoice_based' ? <Field label="Invoice category" value={draft.invoiceCategory} onChange={(value) => set('invoiceCategory', value)} /> : null}
      <div className="sm:col-span-2"><Field label="Additional dimensions (key=value, comma separated)" value={draft.dimensions} onChange={(value) => set('dimensions', value)} /></div>
    </div></div>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.executeNow} onChange={(event) => set('executeNow', event.target.checked)} />Lock and execute this version now</label>
    {draft.executeNow ? <Field label="Execution reason" value={draft.executionReason} onChange={(value) => set('executionReason', value)} required /> : null}
    <Button type="submit" pending={mutation.isPending}>Create contract</Button>
    {mutation.isError ? <p role="alert" className="text-sm text-destructive">The contract workflow could not be saved. Review its identifiers, dates, and unique contract number.</p> : null}
  </form>
}

function BudgetForm({ studyId, onSaved }: { studyId: string; onSaved: () => void }) {
  const [draft, setDraft] = useState({ name: '', scope: 'study' as 'study' | 'site' | 'vendor', currency: 'USD', effectiveFrom: '', reason: '', approveNow: false, approvalReason: '' })
  const [lines, setLines] = useState([{ category: '', description: '', quantity: '1', unitCost: '' }])
  const mutation = useMutation({
    mutationFn: async () => {
      const budget = await ctmsApi.createFinancialBudget(studyId, {
        name: draft.name.trim(), scope: draft.scope, currency: draft.currency.trim().toUpperCase(), effective_from: draft.effectiveFrom,
        reason: draft.reason.trim() || undefined,
        lines: lines.map((line) => ({ category: line.category.trim(), description: line.description.trim(), quantity: Number(line.quantity), unit_cost: Number(line.unitCost) })),
      })
      if (draft.approveNow && budget.current_version) await ctmsApi.approveFinancialBudgetVersion(studyId, budget.current_version.id, draft.approvalReason)
      return budget
    },
    onSuccess: onSaved,
  })
  const updateLine = (index: number, key: keyof (typeof lines)[number], value: string) => setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, [key]: value } : line))
  return <form className="space-y-5" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Budget name" value={draft.name} onChange={(value) => setDraft((current) => ({ ...current, name: value }))} required />
      <div className="space-y-2"><Label>Scope</Label><select className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.scope} onChange={(event) => setDraft((current) => ({ ...current, scope: event.target.value as typeof draft.scope }))}><option value="study">Study</option><option value="site">Site</option><option value="vendor">Vendor</option></select></div>
      <Field label="Currency" value={draft.currency} onChange={(value) => setDraft((current) => ({ ...current, currency: value }))} required />
      <Field label="Effective from" type="date" value={draft.effectiveFrom} onChange={(value) => setDraft((current) => ({ ...current, effectiveFrom: value }))} required />
      <div className="sm:col-span-2"><Field label="Version reason" value={draft.reason} onChange={(value) => setDraft((current) => ({ ...current, reason: value }))} /></div>
    </div>
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between"><h3 className="font-medium">Budget lines</h3><Button type="button" variant="outline" size="sm" onClick={() => setLines((current) => [...current, { category: '', description: '', quantity: '1', unitCost: '' }])}><Plus className="size-4" />Add line</Button></div>
      {lines.map((line, index) => <div key={index} className="grid gap-3 rounded-lg bg-muted/35 p-3 sm:grid-cols-2">
        <Field label={`Category ${index + 1}`} value={line.category} onChange={(value) => updateLine(index, 'category', value)} required />
        <Field label={`Description ${index + 1}`} value={line.description} onChange={(value) => updateLine(index, 'description', value)} required />
        <Field label={`Quantity ${index + 1}`} type="number" value={line.quantity} onChange={(value) => updateLine(index, 'quantity', value)} required />
        <Field label={`Unit cost ${index + 1}`} type="number" value={line.unitCost} onChange={(value) => updateLine(index, 'unitCost', value)} required />
        {lines.length > 1 ? <Button type="button" variant="ghost" size="sm" className="justify-self-start text-destructive" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>Remove line</Button> : null}
      </div>)}
    </div>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.approveNow} onChange={(event) => setDraft((current) => ({ ...current, approveNow: event.target.checked }))} />Approve as the current baseline</label>
    {draft.approveNow ? <Field label="Approval reason" value={draft.approvalReason} onChange={(value) => setDraft((current) => ({ ...current, approvalReason: value }))} required /> : null}
    <Button type="submit" pending={mutation.isPending}>Create budget</Button>
    {mutation.isError ? <p role="alert" className="text-sm text-destructive">The budget could not be saved. Check the currency, effective date, and line values.</p> : null}
  </form>
}

function BudgetRevisionForm({ studyId, budget, onSaved }: { studyId: string; budget: CTMSFinancialBudget; onSaved: () => void }) {
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [reason, setReason] = useState('')
  const [lines, setLines] = useState(() => (budget.current_version?.lines ?? []).map((line) => ({ category: line.category, description: line.description, quantity: String(line.quantity), unitCost: String(line.unit_cost) })))
  const mutation = useMutation({ mutationFn: () => ctmsApi.createFinancialBudgetVersion(studyId, budget.id, { effective_from: effectiveFrom, reason, lines: lines.map((line) => ({ category: line.category, description: line.description, quantity: Number(line.quantity), unit_cost: Number(line.unitCost) })) }), onSuccess: onSaved })
  const updateLine = (index: number, key: keyof (typeof lines)[number], value: string) => setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, [key]: value } : line))
  return <form className="mt-4 space-y-4 rounded-lg border bg-muted/25 p-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
    <div className="grid gap-4 sm:grid-cols-2"><Field label={`Revision effective date ${budget.id}`} type="date" value={effectiveFrom} onChange={setEffectiveFrom} required /><Field label={`Revision reason ${budget.id}`} value={reason} onChange={setReason} required /></div>
    {lines.map((line, index) => <div key={index} className="grid gap-3 sm:grid-cols-4"><Field label={`Revision category ${index + 1}`} value={line.category} onChange={(value) => updateLine(index, 'category', value)} required /><Field label={`Revision description ${index + 1}`} value={line.description} onChange={(value) => updateLine(index, 'description', value)} required /><Field label={`Revision quantity ${index + 1}`} type="number" value={line.quantity} onChange={(value) => updateLine(index, 'quantity', value)} required /><Field label={`Revision unit cost ${index + 1}`} type="number" value={line.unitCost} onChange={(value) => updateLine(index, 'unitCost', value)} required /></div>)}
    <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => setLines((current) => [...current, { category: '', description: '', quantity: '1', unitCost: '' }])}><Plus className="size-4" />Add line</Button><Button type="submit" size="sm" pending={mutation.isPending}>Save draft revision</Button></div>
    {mutation.isError ? <p role="alert" className="text-sm text-destructive">The revision could not be created. Approve the current draft before adding another version.</p> : null}
  </form>
}

function EventForm({ studyId, onSaved }: { studyId: string; onSaved: () => void }) {
  const [draft, setDraft] = useState(() => ({ siteId: '', subjectId: '', visitId: '', sourceType: 'ctms_operational_event', sourceId: '', triggerCode: '', eventDate: '', quantity: '1', idempotencyKey: `manual:${crypto.randomUUID()}` }))
  const configuration = useCTMSFinancialConfigurationOptions(studyId, draft.eventDate || undefined)
  const sourceIdentity = draft.sourceId || draft.visitId || draft.subjectId || draft.siteId
  const requestKey = sourceIdentity && draft.triggerCode ? `${draft.sourceType}:${sourceIdentity}:${draft.triggerCode}` : draft.idempotencyKey
  const mutation = useMutation({ mutationFn: () => ctmsApi.calculateFinancialEvent(studyId, { site_id: draft.siteId || undefined, subject_id: draft.subjectId || undefined, visit_instance_id: draft.visitId || undefined, source_type: draft.sourceType, source_id: draft.sourceId || undefined, trigger_code: draft.triggerCode, event_date: draft.eventDate, quantity: Number(draft.quantity), idempotency_key: requestKey, verification_status: 'verified', evidence: { entered_via: 'ctms_financial_workspace' } }), onSuccess: onSaved })
  const set = (key: keyof typeof draft, value: string) => setDraft((current) => ({ ...current, [key]: value }))
  return <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><p className="rounded-lg bg-muted/60 p-3 text-sm text-muted-foreground">Payment requests are normally created automatically from verified study activity. Use this form for an authorized manual calculation or replay.</p><div className="grid gap-4 sm:grid-cols-2">
    <Field label="Activity date" type="date" value={draft.eventDate} onChange={(value) => { setDraft((current) => ({ ...current, eventDate: value, triggerCode: '' })) }} required /><div className="space-y-2"><Label htmlFor="financial-payment-rule">Payment rule *</Label><select id="financial-payment-rule" required className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.triggerCode} onChange={(event) => set('triggerCode', event.target.value)}><option value="">Select an executed contract rule</option>{(configuration.data?.payment_rules ?? []).map((rule) => <option key={rule.code} value={rule.code}>{rule.label || displayCode(rule.code)} · {rule.charge_item_count} charge item{rule.charge_item_count === 1 ? '' : 's'}</option>)}</select>{!configuration.isLoading && !(configuration.data?.payment_rules ?? []).length ? <p className="text-xs text-amber-700">{draft.eventDate ? `No executed contract rule is effective on ${draft.eventDate}. Check the contract version effective dates.` : 'No executed contract payment rules are configured.'}</p> : null}</div>
    <Field label="Quantity" type="number" value={draft.quantity} onChange={(value) => set('quantity', value)} required /><div className="rounded-md border bg-background p-3 text-xs text-muted-foreground"><p className="font-medium text-foreground">Duplicate protection is automatic</p><p className="mt-1">CTMS derives a stable request key from the source record. Manual requests retain one generated key for safe retry.</p></div>
    <Field label="Source system" value={draft.sourceType} onChange={(value) => set('sourceType', value)} required /><Field label="Source record ID" value={draft.sourceId} onChange={(value) => set('sourceId', value)} />
    <Field label="Site ID" value={draft.siteId} onChange={(value) => set('siteId', value)} /><Field label="Subject ID" value={draft.subjectId} onChange={(value) => set('subjectId', value)} /><Field label="Visit instance ID" value={draft.visitId} onChange={(value) => set('visitId', value)} />
  </div><Button type="submit" pending={mutation.isPending}>Create payment request</Button>{mutation.isError ? <p role="alert" className="text-sm text-destructive">No eligible executed payment term matched this activity, or its source reference was invalid.</p> : null}</form>
}

function InvoiceForm({ studyId, onSaved }: { studyId: string; onSaved: () => void }) {
  const contracts = useCTMSFinancialContracts(studyId).data?.items ?? []
  const payables = (useCTMSFinancialPayables(studyId).data?.items ?? []).filter((item) => ['approved', 'partially_invoiced'].includes(item.status))
  const [draft, setDraft] = useState({ contractId: '', partyName: '', invoiceNumber: '', direction: 'payable' as CTMSFinancialDirection, invoiceDate: '', dueDate: '', currency: 'USD' })
  const [lineAmounts, setLineAmounts] = useState<Record<string, string>>({})
  const eligiblePayables = payables.filter((item) => item.contract_id === draft.contractId)
  const lines = Object.entries(lineAmounts).filter(([, amount]) => Number(amount) > 0).map(([payable_item_id, amount]) => ({ payable_item_id, amount: Number(amount) }))
  const amount = lines.reduce((total, line) => total + line.amount, 0)
  const mutation = useMutation({ mutationFn: () => ctmsApi.createFinancialInvoice(studyId, { contract_id: draft.contractId, party_name: draft.partyName, invoice_number: draft.invoiceNumber, direction: draft.direction, invoice_date: draft.invoiceDate, due_date: draft.dueDate, amount, currency: draft.currency, lines }), onSuccess: onSaved })
  const set = (key: keyof typeof draft, value: string) => setDraft((current) => ({ ...current, [key]: value }))
  return <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><div className="grid gap-4 sm:grid-cols-2">
    <div className="space-y-2 sm:col-span-2"><Label>Contract</Label><select required className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={draft.contractId} onChange={(event) => { const contract = contracts.find((item) => item.id === event.target.value); setLineAmounts({}); setDraft((current) => ({ ...current, contractId: event.target.value, partyName: contract?.party_name ?? current.partyName, direction: contract?.direction ?? current.direction, currency: contract?.currency ?? current.currency })) }}><option value="">Select contract</option>{contracts.map((item) => <option key={item.id} value={item.id}>{item.contract_number} · {item.party_name}</option>)}</select></div>
    <Field label="Party name" value={draft.partyName} onChange={(value) => set('partyName', value)} required /><Field label="Invoice number" value={draft.invoiceNumber} onChange={(value) => set('invoiceNumber', value)} required />
    <Field label="Invoice date" type="date" value={draft.invoiceDate} onChange={(value) => set('invoiceDate', value)} required /><Field label="Due date" type="date" value={draft.dueDate} onChange={(value) => set('dueDate', value)} required />
    <Field label="Currency" value={draft.currency} onChange={(value) => set('currency', value)} required />
  </div><div className="space-y-2 rounded-lg border p-4"><div className="flex items-center justify-between"><Label>Approved payment requests</Label><span className="text-sm font-semibold">Invoice total {money(amount, draft.currency)}</span></div>{eligiblePayables.length ? eligiblePayables.map((payable) => { const selected = payable.id in lineAmounts; return <div key={payable.id} className="grid gap-3 rounded-md bg-muted/35 p-3 sm:grid-cols-[1fr_10rem]"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected} onChange={(event) => setLineAmounts((current) => { const next = { ...current }; if (event.target.checked) next[payable.id] = String(payable.net_amount); else delete next[payable.id]; return next })} /><span>{displayCode(payable.calculation_snapshot.term_code)} · {money(payable.net_amount, payable.currency)}</span></label>{selected ? <Input aria-label={`Matched amount ${payable.id}`} type="number" value={lineAmounts[payable.id]} onChange={(event) => setLineAmounts((current) => ({ ...current, [payable.id]: event.target.value }))} /> : null}</div> }) : <p className="text-sm text-muted-foreground">Select a contract with approved, uninvoiced payment requests.</p>}</div><Button type="submit" pending={mutation.isPending} disabled={!lines.length}>Match invoice</Button>{mutation.isError ? <p role="alert" className="text-sm text-destructive">Invoice matching failed. Each line must be within the approved unmatched amount and use the contract currency.</p> : null}</form>
}

function PaymentForm({ studyId, onSaved }: { studyId: string; onSaved: () => void }) {
  const invoices = (useCTMSFinancialInvoices(studyId).data?.items ?? []).filter((item) => item.status !== 'paid')
  const [draft, setDraft] = useState({ partyName: '', direction: 'payable' as CTMSFinancialDirection, paymentDate: '', currency: 'USD', reference: '' })
  const [allocationAmounts, setAllocationAmounts] = useState<Record<string, string>>({})
  const allocations = Object.entries(allocationAmounts).filter(([, amount]) => Number(amount) > 0).map(([invoice_id, allocated_amount]) => ({ invoice_id, allocated_amount: Number(allocated_amount) }))
  const amount = allocations.reduce((total, allocation) => total + allocation.allocated_amount, 0)
  const compatibleInvoices = invoices.filter((invoice) => !draft.partyName || (invoice.party_name === draft.partyName && invoice.direction === draft.direction && invoice.currency === draft.currency))
  const mutation = useMutation({ mutationFn: () => ctmsApi.reconcileFinancialPayment(studyId, { party_name: draft.partyName, direction: draft.direction, payment_date: draft.paymentDate, amount, currency: draft.currency, reference: draft.reference, allocations }), onSuccess: onSaved })
  const set = (key: keyof typeof draft, value: string) => setDraft((current) => ({ ...current, [key]: value }))
  return <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><div className="grid gap-4 sm:grid-cols-2">
    <Field label="Settlement reference" value={draft.reference} onChange={(value) => set('reference', value)} required /><Field label="Payment date" type="date" value={draft.paymentDate} onChange={(value) => set('paymentDate', value)} required /><Field label="Party name" value={draft.partyName} onChange={(value) => set('partyName', value)} required /><Field label="Currency" value={draft.currency} onChange={(value) => set('currency', value)} required />
  </div><div className="space-y-2 rounded-lg border p-4"><div className="flex items-center justify-between"><Label>Invoice allocations</Label><span className="text-sm font-semibold">Settlement total {money(amount, draft.currency)}</span></div>{compatibleInvoices.map((invoice) => { const selected = invoice.id in allocationAmounts; return <div key={invoice.id} className="grid gap-3 rounded-md bg-muted/35 p-3 sm:grid-cols-[1fr_10rem]"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected} onChange={(event) => { if (event.target.checked && !draft.partyName) setDraft((current) => ({ ...current, partyName: invoice.party_name, direction: invoice.direction, currency: invoice.currency })); setAllocationAmounts((current) => { const next = { ...current }; if (event.target.checked) next[invoice.id] = String(invoice.amount); else delete next[invoice.id]; return next }) }} /><span>{invoice.invoice_number} · {money(invoice.amount, invoice.currency)}</span></label>{selected ? <Input aria-label={`Allocation amount ${invoice.invoice_number}`} type="number" value={allocationAmounts[invoice.id]} onChange={(event) => setAllocationAmounts((current) => ({ ...current, [invoice.id]: event.target.value }))} /> : null}</div> })}{!compatibleInvoices.length ? <p className="text-sm text-muted-foreground">No compatible outstanding invoices are available.</p> : null}</div><Button type="submit" pending={mutation.isPending} disabled={!allocations.length}>Record settlement</Button>{mutation.isError ? <p role="alert" className="text-sm text-destructive">Reconciliation failed. Allocations cannot exceed invoice balances and must share the party, direction, and currency.</p> : null}</form>
}

function PaymentTermForm({ studyId, versionId, onSaved }: { studyId: string; versionId: string; onSaved: () => void }) {
  const configuration = useCTMSFinancialConfigurationOptions(studyId)
  const [draft, setDraft] = useState({ code: '', description: '', paymentMethod: 'visit_based' as CTMSPaymentTerm['payment_method'], triggerCode: '', unitRate: '', costCategory: '', billingUnit: '', visitDefinitionId: '', formDefinitionId: '', labCode: '', invoiceCategory: '', dimensions: '', frequency: '', quantityCap: '', amountCap: '', holdback: '' })
  const mutation = useMutation({ mutationFn: () => ctmsApi.createPaymentTerm(studyId, versionId, { code: draft.code, description: draft.description, payment_method: draft.paymentMethod, trigger_code: draft.triggerCode, unit_rate: Number(draft.unitRate), cost_category: draft.costCategory || undefined, billing_unit: draft.billingUnit || undefined, visit_definition_id: draft.visitDefinitionId || undefined, form_definition_id: draft.formDefinitionId || undefined, lab_code: draft.labCode || undefined, invoice_category: draft.invoiceCategory || undefined, dimensions_json: parseDimensions(draft.dimensions), frequency: draft.frequency || undefined, quantity_cap: draft.quantityCap ? Number(draft.quantityCap) : undefined, amount_cap: draft.amountCap ? Number(draft.amountCap) : undefined, holdback_percent: draft.holdback ? Number(draft.holdback) : undefined }), onSuccess: onSaved })
  const selectClass = 'flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm'
  return <form className="mb-5 grid gap-4 rounded-xl border bg-muted/25 p-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
    <div className="sm:col-span-2"><p className="font-medium">Add contract charge item</p><p className="mt-1 text-xs text-muted-foreground">Each item can use a different rate basis, EDC source, cap, holdback, and reporting dimension.</p></div>
    <Field label="Item code" value={draft.code} onChange={(value) => setDraft((current) => ({ ...current, code: value }))} required />
    <Field label="Description" value={draft.description} onChange={(value) => setDraft((current) => ({ ...current, description: value }))} required />
    <div className="space-y-2"><Label htmlFor={`charge-method-${versionId}`}>Calculation method</Label><select id={`charge-method-${versionId}`} className={selectClass} value={draft.paymentMethod} onChange={(event) => setDraft((current) => ({ ...current, paymentMethod: event.target.value as CTMSPaymentTerm['payment_method'], visitDefinitionId: '', formDefinitionId: '', labCode: '', invoiceCategory: '' }))}><option value="fixed">Fixed amount</option><option value="visit_based">By visit</option><option value="crf_based">By CRF</option><option value="invoice_based">By invoice</option><option value="lab_based">By lab</option><option value="quantity_based">By quantity</option><option value="procedure_based">By procedure</option><option value="milestone_based">By milestone</option><option value="recurring">Recurring</option><option value="pass_through">Pass-through</option><option value="manual_adjustment">Manual adjustment</option></select></div>
    <Field label="Payment rule code" value={draft.triggerCode} onChange={(value) => setDraft((current) => ({ ...current, triggerCode: value }))} required />
    <Field label="Unit rate" type="number" value={draft.unitRate} onChange={(value) => setDraft((current) => ({ ...current, unitRate: value }))} required />
    <Field label="Cost category" value={draft.costCategory} onChange={(value) => setDraft((current) => ({ ...current, costCategory: value }))} />
    <Field label="Billing unit" value={draft.billingUnit} onChange={(value) => setDraft((current) => ({ ...current, billingUnit: value }))} required={draft.paymentMethod === 'quantity_based'} />
    {draft.paymentMethod === 'visit_based' ? <div className="space-y-2 sm:col-span-2"><Label htmlFor={`charge-visit-${versionId}`}>EDC visit definition</Label><select id={`charge-visit-${versionId}`} className={selectClass} value={draft.visitDefinitionId} onChange={(event) => setDraft((current) => ({ ...current, visitDefinitionId: event.target.value }))}><option value="">Any completed visit matching the rule</option>{(configuration.data?.visits ?? []).map((item) => <option key={item.id} value={item.id}>{item.code} · {item.label} · design v{item.version}</option>)}</select></div> : null}
    {draft.paymentMethod === 'crf_based' || draft.paymentMethod === 'lab_based' ? <div className="space-y-2 sm:col-span-2"><Label htmlFor={`charge-form-${versionId}`}>EDC CRF definition{draft.paymentMethod === 'crf_based' ? ' *' : ''}</Label><select id={`charge-form-${versionId}`} required={draft.paymentMethod === 'crf_based'} className={selectClass} value={draft.formDefinitionId} onChange={(event) => setDraft((current) => ({ ...current, formDefinitionId: event.target.value }))}><option value="">{draft.paymentMethod === 'lab_based' ? 'No CRF restriction' : 'Select a published CRF'}</option>{(configuration.data?.forms ?? []).map((item) => <option key={item.id} value={item.id}>{item.code} · {item.label} · design v{item.version}</option>)}</select></div> : null}
    {draft.paymentMethod === 'lab_based' ? <Field label="Lab code" value={draft.labCode} onChange={(value) => setDraft((current) => ({ ...current, labCode: value }))} required={!draft.formDefinitionId} /> : null}
    {draft.paymentMethod === 'invoice_based' ? <Field label="Invoice category" value={draft.invoiceCategory} onChange={(value) => setDraft((current) => ({ ...current, invoiceCategory: value }))} /> : null}
    <div className="sm:col-span-2"><Field label="Additional dimensions (key=value, comma separated)" value={draft.dimensions} onChange={(value) => setDraft((current) => ({ ...current, dimensions: value }))} /></div>
    <Field label="Frequency" value={draft.frequency} onChange={(value) => setDraft((current) => ({ ...current, frequency: value }))} />
    <Field label="Quantity cap" type="number" value={draft.quantityCap} onChange={(value) => setDraft((current) => ({ ...current, quantityCap: value }))} />
    <Field label="Amount cap" type="number" value={draft.amountCap} onChange={(value) => setDraft((current) => ({ ...current, amountCap: value }))} />
    <Field label="Holdback percent" type="number" value={draft.holdback} onChange={(value) => setDraft((current) => ({ ...current, holdback: value }))} />
    <div className="sm:col-span-2"><Button type="submit" size="sm" pending={mutation.isPending}>Add charge item</Button>{mutation.isError ? <p role="alert" className="mt-2 text-sm text-destructive">The charge item could not be added. Check required EDC links and confirm the version is still a draft.</p> : null}</div>
  </form>
}

function AmendmentForm({ studyId, contract, version, onSaved }: { studyId: string; contract: CTMSFinancialContract; version?: { effective_from: string; total_value: string | number; holdback_percent: string | number; payment_window_days: number; invoice_required: boolean; tax_treatment?: string | null }; onSaved: () => void }) {
  const [draft, setDraft] = useState({ effectiveFrom: '', totalValue: String(version?.total_value ?? ''), holdback: String(version?.holdback_percent ?? 0), paymentWindow: String(version?.payment_window_days ?? 30), taxTreatment: version?.tax_treatment ?? '', reason: '' })
  const mutation = useMutation({ mutationFn: () => ctmsApi.createContractVersion(studyId, contract.id, { effective_from: draft.effectiveFrom, total_value: Number(draft.totalValue), holdback_percent: Number(draft.holdback), payment_window_days: Number(draft.paymentWindow), invoice_required: version?.invoice_required ?? true, tax_treatment: draft.taxTreatment || undefined, amendment_reason: draft.reason }), onSuccess: onSaved })
  return <form className="mb-5 grid gap-4 rounded-xl border bg-muted/25 p-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}>
    <Field label="Amendment effective date" type="date" value={draft.effectiveFrom} onChange={(value) => setDraft((current) => ({ ...current, effectiveFrom: value }))} required />
    <Field label="Amended contract value" type="number" value={draft.totalValue} onChange={(value) => setDraft((current) => ({ ...current, totalValue: value }))} required />
    <Field label="Holdback percent" type="number" value={draft.holdback} onChange={(value) => setDraft((current) => ({ ...current, holdback: value }))} required />
    <Field label="Payment window days" type="number" value={draft.paymentWindow} onChange={(value) => setDraft((current) => ({ ...current, paymentWindow: value }))} required />
    <Field label="Tax treatment" value={draft.taxTreatment} onChange={(value) => setDraft((current) => ({ ...current, taxTreatment: value }))} />
    <Field label="Reason for amendment" value={draft.reason} onChange={(value) => setDraft((current) => ({ ...current, reason: value }))} required />
    <div className="sm:col-span-2"><Button type="submit" size="sm" pending={mutation.isPending}>Create amendment version</Button>{mutation.isError ? <p role="alert" className="mt-2 text-sm text-destructive">The amendment could not be created. Resolve any existing draft version first.</p> : null}</div>
  </form>
}

function ContractWorkspace({ studyId, studyLabel, siteLabel, organizationLabel, contract, canManage, onBack, onChanged }: { studyId: string; studyLabel: string; siteLabel?: string; organizationLabel?: string; contract: CTMSFinancialContract; canManage: boolean; onBack: () => void; onChanged: () => void }) {
  const [tab, setTab] = useState<ContractTab>('details')
  const versions = useCTMSContractVersions(studyId, contract.id)
  const currentVersion = versions.data?.[0]
  const terms = useCTMSPaymentTerms(studyId, currentVersion?.id ?? '')
  const configuration = useCTMSFinancialConfigurationOptions(studyId)
  const documents = useCTMSContractDocuments(studyId, contract.id)
  const audit = useCTMSContractAudit(studyId, contract.id)
  const documentItems = Array.isArray(documents.data) ? documents.data : []
  const auditItems = Array.isArray(audit.data) ? audit.data : []
  const amendments = (versions.data ?? []).filter((version) => version.version_number > 1 || version.amendment_reason)
  const uploadDocument = useMutation({ mutationFn: (file: File) => ctmsApi.uploadContractDocument(studyId, contract.id, file), onSuccess: () => { void documents.refetch(); onChanged() } })
  const executeVersion = useMutation({ mutationFn: () => ctmsApi.executeContractVersion(studyId, currentVersion?.id ?? '', 'Executed agreement confirmed in CTMS financial workspace'), onSuccess: () => { void versions.refetch(); onChanged() } })
  const transitions: Record<string, string[]> = { draft: ['internal_review'], internal_review: ['negotiation', 'approved'], negotiation: ['internal_review', 'approved'], approved: ['executed'], executed: ['active', 'closed'], active: ['closed'] }
  const nextStatuses = transitions[contract.status] ?? []
  const definitionLabel = (term: CTMSPaymentTerm) => {
    if (term.visit_definition_id) return configuration.data?.visits?.find((item) => item.id === term.visit_definition_id)?.label ?? `EDC visit ${term.visit_definition_id}`
    if (term.form_definition_id) return configuration.data?.forms?.find((item) => item.id === term.form_definition_id)?.label ?? `EDC CRF ${term.form_definition_id}`
    if (term.lab_code) return `Lab ${term.lab_code}`
    if (term.invoice_category) return `Invoice ${term.invoice_category}`
    return 'All matching activity'
  }
  const transition = useMutation({ mutationFn: (status: string) => ctmsApi.transitionFinancialContract(studyId, contract.id, status, `Contract advanced to ${displayCode(status)} in CTMS financial workspace`), onSuccess: onChanged })

  return <section className="rounded-xl border bg-card shadow-sm">
    <div className="border-b p-5 sm:p-6">
      <Button variant="ghost" size="sm" className="-ml-3 mb-4" onClick={onBack}>← Back to contracts</Button>
      <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
        <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Contract · {contract.contract_number}</p><h2 className="mt-2 text-2xl font-semibold">{contract.party_name}</h2><p className="mt-1 text-sm text-muted-foreground">{siteLabel ? `${siteLabel} · ` : ''}{studyLabel}</p></div>
        <div className="flex flex-wrap items-center gap-2"><Status value={contract.status} />{canManage && nextStatuses.map((status) => <Button key={status} size="sm" variant="outline" pending={transition.isPending} onClick={() => transition.mutate(status)}>{status === 'executed' ? 'Execute and lock contract' : `Move to ${displayCode(status)}`}</Button>)}</div>
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div><p className="text-xs text-muted-foreground">Contract Value</p><p className="mt-1 text-xl font-semibold">{currentVersion ? money(currentVersion.total_value, contract.currency) : '—'}</p></div>
        <div><p className="text-xs text-muted-foreground">Effective Date</p><p className="mt-1 text-xl font-semibold">{currentVersion?.effective_from ?? '—'}</p></div>
        <div><p className="text-xs text-muted-foreground">Version</p><p className="mt-1 text-xl font-semibold">{currentVersion ? `v${currentVersion.version_number}.0` : '—'}</p></div>
      </div>
    </div>

    <Tabs value={tab} onValueChange={(value) => setTab(value as ContractTab)} className="p-5 sm:p-6">
      <TabsList className="h-auto w-full justify-start gap-6 overflow-x-auto rounded-none border-b bg-transparent p-0">
        {([{ value: 'details', label: 'Details' }, { value: 'documents', label: 'Documents' }, { value: 'budget', label: 'Budget' }, { value: 'payment-terms', label: 'Payment Terms' }, { value: 'amendments', label: 'Amendments' }, { value: 'audit-trail', label: 'Audit Trail' }] as const).map((item) => <TabsTrigger key={item.value} value={item.value} className="rounded-none border-b-2 border-transparent bg-transparent px-0 pb-3 pt-0 shadow-none aria-selected:border-primary aria-selected:bg-transparent aria-selected:text-foreground aria-selected:shadow-none">{item.label}</TabsTrigger>)}
      </TabsList>

      <TabsContent value="details" className="mt-6"><dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
        {[['Contract number', contract.contract_number], ['Title', contract.title], ['Contract type', displayCode(contract.contract_type)], ['Party', contract.party_name], ['Organization', organizationLabel ?? 'Unlinked'], ['Direction', contract.direction === 'payable' ? 'Accounts payable' : 'Accounts receivable'], ['Country', contract.country_code ?? '—'], ['Currency', contract.currency], ['Owner', contract.owner_id ? 'Assigned' : 'Unassigned'], ['Status', displayCode(contract.status)]].map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-sm font-medium">{value}</dd></div>)}
      </dl></TabsContent>

      <TabsContent value="documents" className="mt-6">
        {canManage ? <label className="mb-4 inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border bg-background px-3 text-sm font-medium shadow-sm hover:bg-accent"><Upload className="size-4" />Upload document<input className="sr-only" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadDocument.mutate(file); event.currentTarget.value = '' }} /></label> : null}
        <DataTableShell label="Contract documents" loading={documents.isLoading || uploadDocument.isPending} error={Boolean(documents.error || uploadDocument.error)} onRetry={() => void documents.refetch()} empty={!documentItems.length} emptyTitle="No contract documents attached" emptyDescription="Upload executed agreements, exhibits, and supporting documents."><div className="space-y-2 p-4">{documentItems.map((document) => <div key={document.id} className="flex items-center justify-between gap-4 rounded-lg border p-4"><div className="min-w-0"><p className="truncate text-sm font-medium">{document.filename}</p><p className="mt-1 text-xs text-muted-foreground">{document.content_type} · {(document.size_bytes / 1024).toFixed(1)} KB · {new Date(document.uploaded_at).toLocaleString()}</p></div><Button variant="outline" size="sm" onClick={() => void ctmsApi.downloadAttachment(document.id).then((blob) => { const url = URL.createObjectURL(blob); const anchor = window.document.createElement('a'); anchor.href = url; anchor.download = document.filename; anchor.click(); URL.revokeObjectURL(url) })}><Download className="size-4" />Download</Button></div>)}</div></DataTableShell>
      </TabsContent>

      <TabsContent value="budget" className="mt-6"><DataTableShell label="Contract budget versions" loading={versions.isLoading} error={Boolean(versions.error)} onRetry={() => void versions.refetch()} empty={!versions.data?.length} emptyTitle="No contract budget versions"><div className="space-y-3 p-4">{versions.data?.map((version) => <div key={version.id} className="grid gap-3 rounded-lg border p-4 sm:grid-cols-[1fr_auto_auto] sm:items-center"><div><p className="font-medium">Version {version.version_number}.0</p><p className="text-sm text-muted-foreground">Effective {version.effective_from}{version.effective_to ? ` – ${version.effective_to}` : ''}</p></div><Status value={version.status} /><p className="font-semibold">{money(version.total_value, contract.currency)}</p></div>)}</div></DataTableShell></TabsContent>

      <TabsContent value="payment-terms" className="mt-6">{canManage && currentVersion?.status === 'draft' ? <PaymentTermForm studyId={studyId} versionId={currentVersion.id} onSaved={() => { void terms.refetch(); onChanged() }} /> : null}<DataTableShell label="Contract charge items / rate card" loading={terms.isLoading || versions.isLoading} error={Boolean(terms.error || versions.error)} onRetry={() => { void versions.refetch(); void terms.refetch() }} empty={!terms.data?.length} emptyTitle="No charge items" emptyDescription="Add fixed, visit, CRF, invoice, lab, or quantity-based rates to this version."><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b bg-muted/40 text-xs text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Charge item</th><th className="px-4 py-3 font-medium">Basis</th><th className="px-4 py-3 font-medium">EDC / dimension slice</th><th className="px-4 py-3 text-right font-medium">Rate</th><th className="px-4 py-3 font-medium">Trigger</th></tr></thead><tbody>{terms.data?.map((term) => <tr key={term.id} className="border-b last:border-0"><td className="px-4 py-4"><p className="font-medium">{term.description}</p><p className="text-xs text-muted-foreground">{term.code}{term.cost_category ? ` · ${term.cost_category}` : ''}</p></td><td className="px-4 py-4"><p>{displayCode(term.payment_method)}</p><p className="text-xs text-muted-foreground">{term.billing_unit || term.frequency || 'per event'}</p></td><td className="px-4 py-4"><p>{definitionLabel(term)}</p>{Object.keys(term.dimensions_json ?? {}).length ? <p className="text-xs text-muted-foreground">{Object.entries(term.dimensions_json ?? {}).map(([key, value]) => `${key}=${value}`).join(' · ')}</p> : null}</td><td className="px-4 py-4 text-right font-medium"><p>{money(term.unit_rate, contract.currency)}</p>{term.quantity_cap || term.amount_cap ? <p className="text-xs font-normal text-muted-foreground">Cap {term.quantity_cap ? `${Number(term.quantity_cap)} units` : money(term.amount_cap, contract.currency)}</p> : null}</td><td className="px-4 py-4">{displayCode(term.trigger_code)}</td></tr>)}</tbody></table></div></DataTableShell>{canManage && currentVersion?.status === 'draft' ? <div className="mt-4 flex justify-end"><Button size="sm" pending={executeVersion.isPending} onClick={() => executeVersion.mutate()}>Execute and lock version</Button></div> : null}</TabsContent>

      <TabsContent value="amendments" className="mt-6">{canManage && currentVersion?.status !== 'draft' ? <AmendmentForm studyId={studyId} contract={contract} version={currentVersion} onSaved={() => { void versions.refetch(); onChanged() }} /> : null}<DataTableShell label="Contract amendments" loading={versions.isLoading} error={Boolean(versions.error)} onRetry={() => void versions.refetch()} empty={!amendments.length} emptyTitle="No amendments" emptyDescription="New effective-dated versions will appear here without overwriting executed terms."><div className="space-y-3 p-4">{amendments.map((version) => <div key={version.id} className="flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4"><div><p className="font-medium">Amendment v{version.version_number}.0</p><p className="mt-1 text-sm text-muted-foreground">{version.amendment_reason || 'No amendment reason provided'} · Effective {version.effective_from}</p></div><Status value={version.status} /></div>)}</div></DataTableShell></TabsContent>

      <TabsContent value="audit-trail" className="mt-6"><DataTableShell label="Immutable financial audit trail" loading={audit.isLoading} error={Boolean(audit.error)} onRetry={() => void audit.refetch()} empty={!auditItems.length} emptyTitle="No audit events"><div className="space-y-0 p-4">{auditItems.map((entry, index) => <div key={entry.id} className="grid grid-cols-[20px_1fr] gap-3"><div className="flex flex-col items-center"><span className="mt-1.5 size-2.5 rounded-full bg-primary" />{index < auditItems.length - 1 ? <span className="w-px flex-1 bg-border" /> : null}</div><div className="pb-6"><p className="text-sm font-medium">{displayCode(entry.action)} · {displayCode(entry.entity_type)}</p><p className="mt-1 text-xs text-muted-foreground">{entry.reason || entry.changed_fields?.join(', ') || 'Recorded system change'}</p><p className="mt-1 text-xs text-muted-foreground">{new Date(entry.timestamp).toLocaleString()} · {entry.actor_id ? 'Authorized user' : 'System'}</p></div></div>)}</div></DataTableShell></TabsContent>
    </Tabs>
  </section>
}

export function FinancialManagementPage({ studyId, initialTab = 'overview' }: { studyId: string; initialTab?: FinancialTab }) {
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, studyId)
  const canManage = usePermission(PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT, studyId)
  const [tab, setTab] = useState<FinancialTab>(initialTab)
  const [drawer, setDrawer] = useState<FinancialDrawer | null>(null)
  const [selectedContractId, setSelectedContractId] = useState<string | null>(null)
  const [contractSearch, setContractSearch] = useState('')
  const [contractTypeFilter, setContractTypeFilter] = useState('all')
  const [directionFilter, setDirectionFilter] = useState('all')
  const [organizationFilter, setOrganizationFilter] = useState('all')
  const client = useQueryClient()
  const study = useCTMSStudyProfile(studyId)
  const overview = useCTMSFinancialOverview(studyId)
  const contracts = useCTMSFinancialContracts(studyId)
  const studyEntities = useCTMSStudyEntities(studyId)
  const budgets = useCTMSFinancialBudgets(studyId)
  const payables = useCTMSFinancialPayables(studyId)
  const invoices = useCTMSFinancialInvoices(studyId)
  const payments = useCTMSFinancialPayments(studyId)
  const report = useCTMSFinancialReport(studyId)
  const budgetItems = Array.isArray(budgets.data) ? budgets.data : []
  const aging = report.data?.aging && !Array.isArray(report.data.aging) ? report.data.aging : {}
  const cashFlow = Array.isArray(report.data?.cash_flow_forecast) ? report.data.cash_flow_forecast : []
  const contractItems = contracts.data?.items ?? []
  const organizations = (studyEntities.data?.items ?? []).filter((assignment) => assignment.entity.entity_type === 'participating_organization' && assignment.entity.active)
  const organizationNames = new Map(organizations.map((assignment) => [assignment.entity_id, assignment.entity.name]))
  const siteNames = new Map((studyEntities.data?.items ?? []).filter((assignment) => assignment.entity.entity_type === 'site').map((assignment) => [assignment.site_id ?? assignment.entity_id, `${assignment.site_number ? `${assignment.site_number} · ` : ''}${assignment.entity.name}`]))
  const normalizedContractSearch = contractSearch.trim().toLowerCase()
  const filteredContracts = contractItems.filter((contract) => (
    (!normalizedContractSearch || `${contract.contract_number} ${contract.title} ${contract.party_name}`.toLowerCase().includes(normalizedContractSearch))
    && (contractTypeFilter === 'all' || contract.contract_type === contractTypeFilter)
    && (directionFilter === 'all' || contract.direction === directionFilter)
    && (organizationFilter === 'all' || (organizationFilter === 'unlinked' ? !contract.organization_id : contract.organization_id === organizationFilter))
  ))

  if (!canRead) return <AccessDeniedPage />

  const currency = overview.data?.currency ?? study.data?.study_currency ?? 'USD'
  const contracted = Number(overview.data?.contracted ?? 0)
  const paid = Number(overview.data?.paid ?? 0)
  const outstanding = Number(overview.data?.outstanding ?? 0)
  const approvedBudget = Number(overview.data?.approved_budget ?? overview.data?.contracted ?? 0)
  const paidShare = percent(paid, approvedBudget)
  const contractedShare = percent(contracted, approvedBudget)
  const otherContracted = Math.max(contracted - paid, 0)
  const uncommitted = Math.max(approvedBudget - contracted, 0)
  const studyLabel = study.data?.study_name || 'Selected study'
  const phaseLabel = study.data?.phase ? `Phase ${study.data.phase.replace(/^phase\s*/i, '')}` : null
  const refresh = async () => { setDrawer(null); await client.invalidateQueries({ queryKey: ctmsKeys.all }) }
  const reversePayment = async (paymentId: string, reference: string) => {
    const reason = window.prompt('Reason for reversing this settled payment')?.trim()
    if (!reason) return
    await ctmsApi.reverseFinancialPayment(studyId, paymentId, { payment_date: new Date().toISOString().slice(0, 10), reference: `${reference}-REV`, reason })
    await refresh()
  }
  const tabAction = tab === 'contracts' && !selectedContractId
    ? { label: 'Add contract', drawer: 'contract' as const }
    : tab === 'budgets'
      ? { label: 'Add budget', drawer: 'budget' as const }
    : tab === 'payments'
      ? { label: 'New payment request', drawer: 'event' as const }
      : tab === 'invoices'
        ? { label: 'Match invoice', drawer: 'invoice' as const }
        : null
  const drawerTitle = drawer === 'contract' ? 'Add contract' : drawer === 'budget' ? 'Add budget baseline' : drawer === 'event' ? 'New payment request' : drawer === 'invoice' ? 'Match invoice' : 'Record settlement'
  const recentActivity = [
    ...(payables.data?.items ?? []).map((item) => ({
      id: `payable-${item.id}`,
      kind: 'payable' as const,
      title: displayCode(item.calculation_snapshot.term_code),
      detail: `Contract v${String(item.calculation_snapshot.contract_version ?? '—')}`,
      status: item.status,
      amount: Number(item.net_amount),
      currency: item.currency,
      createdAt: item.created_at,
    })),
    ...(invoices.data?.items ?? []).map((item) => ({
      id: `invoice-${item.id}`,
      kind: 'invoice' as const,
      title: item.party_name,
      detail: `Invoice ${item.invoice_number}`,
      status: item.status,
      amount: Number(item.amount),
      currency: item.currency,
      createdAt: item.created_at,
    })),
    ...(payments.data?.items ?? []).map((item) => ({
      id: `payment-${item.id}`,
      kind: 'payment' as const,
      title: item.party_name,
      detail: item.reference,
      status: item.status,
      amount: Number(item.amount),
      currency: item.currency,
      createdAt: item.created_at,
    })),
  ].sort((left, right) => right.createdAt.localeCompare(left.createdAt)).slice(0, 5)
  const selectedContract = contractItems.find((item) => item.id === selectedContractId)
  const contractUtilization = Number(report.data?.contract_utilization_percent ?? 0)
  const invoiceCoverage = Number(report.data?.invoice_coverage_percent ?? 0)

  return <div className="min-h-full bg-muted/20">
    <PageContainer wide className="max-w-[1440px] py-8 lg:py-10">
      <header className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Financial management</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground">Study Financials</h1>
          <p className="mt-2 text-sm text-muted-foreground">{studyLabel}{phaseLabel ? ` · ${phaseLabel}` : ''}</p>
        </div>
        {canManage && tabAction ? <Button onClick={() => setDrawer(tabAction.drawer)}><Plus className="size-4" />{tabAction.label}</Button> : null}
      </header>

      <Tabs value={tab} onValueChange={(value) => setTab(value as FinancialTab)} className="mt-8">
        <TabsList className="h-auto w-full justify-start gap-7 overflow-x-auto rounded-none border-b bg-transparent p-0">
          {([{ value: 'overview', label: 'Overview' }, { value: 'contracts', label: 'Contracts' }, { value: 'budgets', label: 'Budgets' }, { value: 'payments', label: 'Payments' }, { value: 'invoices', label: 'Invoices' }, { value: 'reporting', label: 'Reporting' }] as const).map((item) => <TabsTrigger key={item.value} value={item.value} className="rounded-none border-b-2 border-transparent bg-transparent px-0 pb-3 pt-0 shadow-none aria-selected:border-primary aria-selected:bg-transparent aria-selected:text-foreground aria-selected:shadow-none">{item.label}</TabsTrigger>)}
        </TabsList>

        {tab === 'contracts' && selectedContractId ? null : <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <FinancialMetric label="Approved Budget" value={compactMoney(approvedBudget, currency)} note={approvedBudget > 0 ? 'Current approved baseline' : 'No baseline approved'} />
          <FinancialMetric label="Contracted" value={compactMoney(contracted, currency)} note={`${Math.round(contractedShare)}% of baseline`} />
          <FinancialMetric label="Paid to Date" value={compactMoney(paid, currency)} note={`${Math.round(paidShare)}% of baseline`} />
          <FinancialMetric label="Outstanding" value={compactMoney(outstanding, currency)} note="Approved, unpaid balance" />
        </div>}

        <TabsContent value="overview" className="mt-6">
          <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
            <Card className="border-border/70 shadow-sm">
              <CardHeader className="flex flex-row items-start justify-between gap-4 pb-3">
                <div><CardTitle className="text-lg">Budget utilization</CardTitle><CardDescription className="mt-1">Contract commitments and settled payments</CardDescription></div>
                <Badge variant="outline" className="font-mono">{currency}</Badge>
              </CardHeader>
              <CardContent className="pt-6">
                <div className="flex h-10 w-full overflow-hidden rounded-lg bg-muted" aria-label="Budget utilization">
                  <div className="bg-primary" style={{ width: `${paidShare}%` }} title={`Paid ${money(paid, currency)}`} />
                  <div className="bg-primary/35" style={{ width: `${percent(otherContracted, approvedBudget)}%` }} title={`Other contracted ${money(otherContracted, currency)}`} />
                  <div className="bg-muted" style={{ width: `${percent(uncommitted, approvedBudget)}%` }} title={`Uncommitted ${money(uncommitted, currency)}`} />
                </div>
                <div className="mt-6 grid gap-4 sm:grid-cols-3">
                  <div><div className="flex items-center gap-2 text-sm text-muted-foreground"><span className="size-2.5 rounded-sm bg-primary" />Paid</div><p className="mt-1 font-semibold">{compactMoney(paid, currency)}</p></div>
                  <div><div className="flex items-center gap-2 text-sm text-muted-foreground"><span className="size-2.5 rounded-sm bg-primary/35" />Other contracted</div><p className="mt-1 font-semibold">{compactMoney(otherContracted, currency)}</p></div>
                  <div><div className="flex items-center gap-2 text-sm text-muted-foreground"><span className="size-2.5 rounded-sm bg-muted ring-1 ring-border" />Uncommitted</div><p className="mt-1 font-semibold">{compactMoney(uncommitted, currency)}</p></div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/70 shadow-sm">
              <CardHeader><CardTitle className="text-lg">Recent payment activity</CardTitle><CardDescription>Latest calculated, invoiced, and settled activity</CardDescription></CardHeader>
              <CardContent className="space-y-1">
                {recentActivity.length ? recentActivity.map((item) => <div key={item.id} className="flex items-center gap-3 border-b py-3 last:border-0">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">{item.kind === 'payable' ? <Banknote className="size-4" /> : item.kind === 'invoice' ? <ReceiptText className="size-4" /> : <Landmark className="size-4" />}</div>
                  <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{item.title}</p><div className="mt-1 flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground">{item.detail}</span><Status value={item.status} /></div></div>
                  <p className="shrink-0 text-sm font-semibold">{compactMoney(item.amount, item.currency)}</p>
                </div>) : <div className="flex min-h-44 flex-col items-center justify-center text-center"><Banknote className="size-8 text-muted-foreground/50" /><p className="mt-3 text-sm font-medium">No payment activity yet</p><p className="mt-1 max-w-xs text-xs text-muted-foreground">Calculated payments, matched invoices, and settlements will appear here.</p></div>}
              </CardContent>
            </Card>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">Financial overview · live study data</p>
        </TabsContent>

        <TabsContent value="contracts" className="mt-6">
          {selectedContract ? <ContractWorkspace studyId={studyId} studyLabel={studyLabel} siteLabel={selectedContract.site_id ? siteNames.get(selectedContract.site_id) : undefined} organizationLabel={selectedContract.organization_id ? organizationNames.get(selectedContract.organization_id) : undefined} contract={selectedContract} canManage={canManage} onBack={() => setSelectedContractId(null)} onChanged={() => void client.invalidateQueries({ queryKey: ctmsKeys.all })} /> : <div className="space-y-4"><div className="grid gap-3 rounded-xl border bg-card p-4 md:grid-cols-4"><Input aria-label="Search contracts" placeholder="Search number, title, or party" value={contractSearch} onChange={(event) => setContractSearch(event.target.value)} /><select aria-label="Filter by contract type" className="flex h-10 rounded-md border border-input bg-background px-3 text-sm" value={contractTypeFilter} onChange={(event) => setContractTypeFilter(event.target.value)}><option value="all">All contract types</option><option value="sponsor_agreement">Sponsor agreements</option><option value="clinical_trial_agreement">Clinical trial agreements</option><option value="vendor_agreement">Vendor agreements</option></select><select aria-label="Filter by direction" className="flex h-10 rounded-md border border-input bg-background px-3 text-sm" value={directionFilter} onChange={(event) => setDirectionFilter(event.target.value)}><option value="all">Payables and receivables</option><option value="payable">Accounts payable</option><option value="receivable">Accounts receivable</option></select><select aria-label="Filter by organization" className="flex h-10 rounded-md border border-input bg-background px-3 text-sm" value={organizationFilter} onChange={(event) => setOrganizationFilter(event.target.value)}><option value="all">All organizations</option><option value="unlinked">Unlinked</option>{organizations.map((item) => <option key={item.entity_id} value={item.entity_id}>{item.entity.name}</option>)}</select></div><DataTableShell label={`Contracts (${filteredContracts.length})`} loading={contracts.isLoading} error={Boolean(contracts.error)} onRetry={() => void contracts.refetch()} empty={!filteredContracts.length} emptyTitle={contractItems.length ? 'No contracts match these filters' : 'No structured contracts'} emptyDescription={contractItems.length ? 'Change one or more filters to broaden the result.' : 'Create a contract, effective-dated version, and first charge item.'}><div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">{filteredContracts.map((item) => <Card key={item.id} className="border-border/70 shadow-sm"><CardHeader><div className="flex items-start justify-between gap-4"><div><CardTitle className="text-lg">{item.contract_number}</CardTitle><CardDescription className="mt-1">{item.party_name}</CardDescription></div><Status value={item.status} /></div></CardHeader><CardContent className="grid gap-3 text-sm"><p className="font-medium">{item.title}</p><div className="flex items-center justify-between border-t pt-3 text-muted-foreground"><span className="capitalize">{item.contract_type.replaceAll('_', ' ')}</span><span>{item.currency}</span></div><div className="flex items-center justify-between text-xs text-muted-foreground"><span>{item.direction === 'payable' ? 'Accounts payable' : 'Accounts receivable'}</span>{item.organization_id ? <span>{organizationNames.get(item.organization_id) ?? 'Organization'}</span> : item.site_id ? <span>{siteNames.get(item.site_id) ?? 'Site'}</span> : null}</div><Button variant="outline" className="mt-2 w-full" onClick={() => setSelectedContractId(item.id)}>Open contract <ArrowUpRight className="size-4" /></Button></CardContent></Card>)}</div></DataTableShell></div>}
        </TabsContent>

        <TabsContent value="budgets" className="mt-6">
          <DataTableShell label="Study budgets" loading={budgets.isLoading} error={Boolean(budgets.error)} onRetry={() => void budgets.refetch()} empty={!budgetItems.length} emptyTitle="No study budget" emptyDescription="Create and approve a versioned budget baseline for planned-versus-actual reporting.">
            <div className="space-y-4 p-4">{budgetItems.map((budget) => <Card key={budget.id} className="border-border/70 shadow-sm"><CardHeader><div className="flex items-start justify-between gap-4"><div><CardTitle className="text-lg">{budget.name}</CardTitle><CardDescription className="mt-1 capitalize">{budget.scope} budget · {budget.currency}</CardDescription></div><Status value={budget.current_version?.status ?? budget.status} /></div></CardHeader><CardContent><div className="grid gap-4 sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">Version</p><p className="mt-1 font-semibold">v{budget.current_version?.version_number ?? '—'}.0</p></div><div><p className="text-xs text-muted-foreground">Effective</p><p className="mt-1 font-semibold">{budget.current_version?.effective_from ?? '—'}</p></div><div><p className="text-xs text-muted-foreground">Planned total</p><p className="mt-1 font-semibold">{money(budget.current_version?.total, budget.currency)}</p></div></div>{budget.current_version?.lines.length ? <div className="mt-5 overflow-x-auto rounded-lg border"><table className="w-full text-left text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Category</th><th className="px-4 py-3 font-medium">Description</th><th className="px-4 py-3 text-right font-medium">Qty</th><th className="px-4 py-3 text-right font-medium">Planned</th></tr></thead><tbody>{budget.current_version.lines.map((line) => <tr key={line.id} className="border-t"><td className="px-4 py-3 font-medium">{line.category}</td><td className="px-4 py-3 text-muted-foreground">{line.description}</td><td className="px-4 py-3 text-right">{Number(line.quantity)}</td><td className="px-4 py-3 text-right font-medium">{money(line.planned_amount, budget.currency)}</td></tr>)}</tbody></table></div> : null}{canManage && budget.current_version?.status === 'draft' ? <div className="mt-4 flex justify-end"><Button size="sm" onClick={() => void ctmsApi.approveFinancialBudgetVersion(studyId, budget.current_version!.id, 'Approved in CTMS financial workspace').then(refresh)}>Approve baseline</Button></div> : null}{canManage && budget.current_version?.status === 'approved' ? <details className="mt-4"><summary className="cursor-pointer text-sm font-medium text-primary">Create a new budget version</summary><BudgetRevisionForm studyId={studyId} budget={budget} onSaved={refresh} /></details> : null}</CardContent></Card>)}</div>
          </DataTableShell>
        </TabsContent>

        <TabsContent value="payments" className="mt-6">
          <DataTableShell label="Payment requests" loading={payables.isLoading} error={Boolean(payables.error)} onRetry={() => void payables.refetch()} empty={!payables.data?.items.length} emptyTitle="No calculated payments" emptyDescription="Verified visits, milestones, scheduled dates, or approved costs create traceable payment requests.">
            <div className="space-y-3 p-4">{payables.data?.items.map((item) => <Card key={item.id} className="border-border/70 shadow-sm"><CardContent className="p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-start gap-3"><div className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary"><Banknote className="size-5" /></div><div><p className="font-semibold">{money(item.net_amount, item.currency)} payment request</p><p className="mt-1 text-sm text-muted-foreground">{displayCode(item.calculation_snapshot.term_code)} · Contract v{String(item.calculation_snapshot.contract_version ?? '—')}</p></div></div><div className="flex items-center gap-2"><Status value={item.status} />{canManage && item.status === 'calculated' ? <Button size="sm" onClick={() => void ctmsApi.approvePayable(studyId, item.id, 'Approved in CTMS financial workspace').then(refresh)}>Approve</Button> : null}</div></div><details className="group mt-4 border-t pt-4"><summary className="cursor-pointer text-sm font-medium text-primary">View calculation and source</summary><dl className="mt-4 grid gap-3 rounded-lg bg-muted/50 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4"><div><dt className="text-xs text-muted-foreground">Calculation</dt><dd className="mt-1">{String(item.calculation_snapshot.quantity ?? '—')} × {money(item.calculation_snapshot.unit_rate as string | number | undefined, item.currency)}</dd></div><div><dt className="text-xs text-muted-foreground">Gross / holdback</dt><dd className="mt-1">{money(item.gross_amount, item.currency)} / {money(item.holdback_amount, item.currency)}</dd></div><div><dt className="text-xs text-muted-foreground">Source</dt><dd className="mt-1 break-all">{displayCode(item.calculation_snapshot.source_type, 'Verified activity')}</dd></div><div><dt className="text-xs text-muted-foreground">Source record</dt><dd className="mt-1 break-all font-mono text-xs">{String(item.calculation_snapshot.source_id ?? item.event_id)}</dd></div></dl></details></CardContent></Card>)}</div>
          </DataTableShell>
          {payments.data?.items.length ? <Card className="mt-6 border-border/70 shadow-sm"><CardHeader><CardTitle className="text-lg">Settled payments</CardTitle><CardDescription>Reconciled against ERP or payment-provider settlement records</CardDescription></CardHeader><CardContent className="space-y-1">{payments.data.items.map((item) => <div key={item.id} className="flex items-center justify-between gap-4 border-b py-3 last:border-0"><div><p className="text-sm font-medium">{item.party_name}</p><p className="text-xs text-muted-foreground">{item.reference} · {item.payment_date}</p></div><div className="flex items-center gap-3"><Status value={item.status} /><p className="text-sm font-semibold">{money(item.amount, item.currency)}</p>{canManage && item.status === 'settled' ? <Button size="sm" variant="outline" onClick={() => void reversePayment(item.id, item.reference)}>Reverse</Button> : null}</div></div>)}</CardContent></Card> : null}
        </TabsContent>

        <TabsContent value="invoices" className="mt-6">
          <div className="mb-4 flex justify-end">{canManage ? <Button variant="outline" onClick={() => setDrawer('payment')}><ArrowUpRight className="size-4" />Record settlement</Button> : null}</div>
          <DataTableShell label="Invoices" loading={invoices.isLoading} error={Boolean(invoices.error)} onRetry={() => void invoices.refetch()} empty={!invoices.data?.items.length} emptyTitle="No matched invoices" emptyDescription="Match invoice lines to approved payment requests.">
            <div className="space-y-3 p-4">{invoices.data?.items.map((item) => <Card key={item.id} className="border-border/70 shadow-sm"><CardContent className="flex items-center justify-between gap-4 p-5"><div className="flex items-start gap-3"><div className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground"><FileText className="size-5" /></div><div><p className="font-semibold">{item.invoice_number}</p><p className="mt-1 text-sm text-muted-foreground">{item.party_name} · Due {item.due_date}</p></div></div><div className="flex items-center gap-3"><Status value={item.status} /><p className="font-semibold">{money(item.amount, item.currency)}</p></div></CardContent></Card>)}</div>
          </DataTableShell>
        </TabsContent>

        <TabsContent value="reporting" className="mt-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card className="border-border/70 shadow-sm"><CardHeader><CardTitle>Financial reporting</CardTitle><CardDescription>Live operational indicators from the shared contract-to-payment ledger</CardDescription></CardHeader><CardContent className="grid gap-4 sm:grid-cols-2"><div className="rounded-xl border p-5"><p className="text-sm text-muted-foreground">Contract utilization</p><p className="mt-2 text-2xl font-semibold">{Math.round(contractUtilization)}%</p><p className="mt-1 text-xs text-muted-foreground">Earned against contracted value</p></div><div className="rounded-xl border p-5"><p className="text-sm text-muted-foreground">Invoice coverage</p><p className="mt-2 text-2xl font-semibold">{Math.round(invoiceCoverage)}%</p><p className="mt-1 text-xs text-muted-foreground">Invoiced against approved requests</p></div><div className="rounded-xl border p-5"><p className="text-sm text-muted-foreground">Budget variance</p><p className="mt-2 text-2xl font-semibold">{compactMoney(report.data?.budget_variance, currency)}</p><p className="mt-1 text-xs text-muted-foreground">Approved budget less contracted value</p></div><div className="rounded-xl border p-5"><p className="text-sm text-muted-foreground">Cash exposure</p><p className="mt-2 text-2xl font-semibold">{compactMoney(outstanding, currency)}</p><p className="mt-1 text-xs text-muted-foreground">Approved and unpaid</p></div></CardContent></Card>
            <Card className="border-border/70 shadow-sm"><CardHeader><CardTitle>Payment aging</CardTitle><CardDescription>Outstanding invoice balances by due-date bucket</CardDescription></CardHeader><CardContent className="space-y-3">{Object.entries(aging).map(([bucket, amount]) => <div key={bucket} className="flex items-center justify-between rounded-lg border p-4"><span className="text-sm font-medium">{displayCode(bucket)}</span><span className="font-semibold">{money(amount, currency)}</span></div>)}{!Object.keys(aging).length ? <p className="text-sm text-muted-foreground">No aging data is available.</p> : null}</CardContent></Card>
            <Card className="border-border/70 shadow-sm lg:col-span-2"><CardHeader><CardTitle>Cash flow forecast</CardTitle><CardDescription>Outstanding invoices grouped by expected due month</CardDescription></CardHeader><CardContent>{cashFlow.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b text-xs text-muted-foreground"><tr><th className="py-3 font-medium">Period</th><th className="py-3 text-right font-medium">Expected cash flow</th></tr></thead><tbody>{cashFlow.map((bucket) => <tr key={bucket.period} className="border-b last:border-0"><td className="py-4 font-medium">{bucket.period}</td><td className="py-4 text-right font-semibold">{money(bucket.amount, currency)}</td></tr>)}</tbody></table></div> : <p className="text-sm text-muted-foreground">No outstanding invoice due dates to forecast.</p>}</CardContent></Card>
          </div>
        </TabsContent>
      </Tabs>

      <Sheet open={drawer !== null} onOpenChange={(open) => { if (!open) setDrawer(null) }}><SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl"><SheetHeader className="pr-8"><SheetTitle>{drawerTitle}</SheetTitle><SheetDescription>Financial changes retain source evidence, calculation details, approval context, and audit correlation.</SheetDescription></SheetHeader><div className="mt-6">{drawer === 'contract' ? <ContractForm studyId={studyId} onSaved={refresh} /> : drawer === 'budget' ? <BudgetForm studyId={studyId} onSaved={refresh} /> : drawer === 'event' ? <EventForm studyId={studyId} onSaved={refresh} /> : drawer === 'invoice' ? <InvoiceForm studyId={studyId} onSaved={refresh} /> : drawer === 'payment' ? <PaymentForm studyId={studyId} onSaved={refresh} /> : null}</div></SheetContent></Sheet>
    </PageContainer>
  </div>
}

export type { FinancialTab }
