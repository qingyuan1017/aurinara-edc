import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  ctmsApi,
  type CTMSChecklistResult,
  type CTMSMonitoringActivity,
  type CTMSMonitoringChecklistItem,
  type CTMSMonitoringReport,
  useCTMSMonitoringChecklist,
  useCTMSMonitoringReports,
} from '../api'
import { useCTMSMutation } from '../offline'

const REPORT_SECTIONS = [
  ['visit_summary', 'Visit summary'],
  ['subject_enrollment', 'Subject enrollment'],
  ['informed_consent', 'Informed consent'],
  ['safety_review', 'Safety review'],
  ['data_review', 'Data review'],
  ['protocol_compliance', 'Protocol compliance'],
  ['ip_accountability', 'IP accountability'],
  ['essential_documents', 'Essential documents'],
  ['previous_findings', 'Previous findings'],
  ['new_findings', 'New findings'],
  ['follow_up_actions', 'Follow-up actions'],
  ['final_assessment', 'Final assessment'],
] as const

function ChecklistRow({ item, disabled, onChanged }: { item: CTMSMonitoringChecklistItem; disabled: boolean; onChanged: () => void }) {
  const [details, setDetails] = useState(item.review_details ?? '')
  const [observations, setObservations] = useState(item.observations ?? '')
  const mutation = useCTMSMutation({
    mutationFn: (result: CTMSChecklistResult) => ctmsApi.updateMonitoringChecklistItem(item.id, { result, review_details: details || undefined, observations: observations || undefined, evidence_references: item.evidence_references ?? [] }),
    onSuccess: onChanged,
  })
  return <li className="space-y-3 rounded-md border p-3">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium">{item.requirement}</p><p className="text-xs text-muted-foreground">{item.plan_reference ?? item.requirement_key}</p></div><span className="rounded-full border px-2 py-0.5 text-xs">{item.result}</span></div>
    <div className="grid gap-2 sm:grid-cols-2"><Textarea aria-label={`${item.requirement} review details`} value={details} onChange={(event) => setDetails(event.target.value)} placeholder="What records or evidence were reviewed?" disabled={disabled} /><Textarea aria-label={`${item.requirement} observations`} value={observations} onChange={(event) => setObservations(event.target.value)} placeholder="Observations" disabled={disabled} /></div>
    {!disabled ? <div className="flex flex-wrap gap-2"><Button size="sm" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate('Completed')}>Completed</Button><Button size="sm" type="button" variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate('Not Completed')}>Not completed</Button><Button size="sm" type="button" variant="outline" disabled={mutation.isPending || !details.trim()} onClick={() => mutation.mutate('Not Applicable')}>Not applicable</Button></div> : null}
    {mutation.error ? <p role="alert" className="text-sm text-destructive">Checklist result could not be saved.</p> : null}
  </li>
}

function ReportBuilder({ visit, report, onChanged }: { visit: CTMSMonitoringActivity; report?: CTMSMonitoringReport; onChanged: () => void }) {
  const [content, setContent] = useState<Record<string, unknown>>(report?.content ?? {})
  const [comments, setComments] = useState('')
  const mutation = useCTMSMutation({
    mutationFn: ({ action }: { action: 'create' | 'save' | 'submit' | 'start_review' | 'request_revision' | 'approve' | 'finalize' }) => {
      if (action === 'create') return ctmsApi.createMonitoringReport(visit.id, content)
      if (!report) throw new Error('Create the report before continuing')
      if (action === 'save') return ctmsApi.updateMonitoringReport(report.id, content)
      return ctmsApi.transitionMonitoringReport(report.id, action, comments || undefined)
    },
    onSuccess: onChanged,
  })
  const editable = !report || report.status === 'Draft' || report.status === 'Revision Required'
  const actions = !report ? ['create'] as const
    : report.status === 'Draft' || report.status === 'Revision Required' ? ['save', 'submit'] as const
    : report.status === 'Submitted' ? ['start_review'] as const
    : report.status === 'Under Review' ? ['request_revision', 'approve'] as const
    : report.status === 'Approved' ? ['finalize'] as const
    : []
  return <div className="space-y-3">
    <div className="flex items-center justify-between"><h4 className="font-semibold">Monitoring visit report</h4><span className="rounded-full border px-2 py-0.5 text-xs">{report ? `v${report.version_number} · ${report.status}` : 'Not started'}</span></div>
    <div className="grid gap-3 lg:grid-cols-2">{REPORT_SECTIONS.map(([key, label]) => <label key={key} className="space-y-1 text-sm"><span className="font-medium">{label}</span><Textarea value={String(content[key] ?? '')} onChange={(event) => setContent((current) => ({ ...current, [key]: event.target.value }))} disabled={!editable} /></label>)}</div>
    {report?.status === 'Under Review' ? <Textarea value={comments} onChange={(event) => setComments(event.target.value)} placeholder="Reviewer comments (required for revision)" /> : null}
    <div className="flex flex-wrap gap-2">{actions.map((action) => <Button key={action} type="button" variant={action === 'save' || action === 'request_revision' ? 'outline' : 'default'} disabled={mutation.isPending || (action === 'request_revision' && !comments.trim())} onClick={() => mutation.mutate({ action })}>{action.replaceAll('_', ' ')}</Button>)}</div>
    {mutation.error ? <p role="alert" className="text-sm text-destructive">The report action could not be completed.</p> : null}
    {report?.status === 'Finalized' ? <p className="rounded-md border border-success/30 bg-success/10 p-3 text-sm">Controlled snapshot finalized. Open findings remain active until separately verified and closed.</p> : null}
  </div>
}

export function MonitoringVisitWorkspace({ visit, canManage, onVisitChanged }: { visit: CTMSMonitoringActivity; canManage: boolean; onVisitChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const checklist = useCTMSMonitoringChecklist(expanded ? visit.id : '')
  const reports = useCTMSMonitoringReports(expanded ? visit.id : '')
  const start = useCTMSMutation({ mutationFn: () => ctmsApi.startMonitoringActivity(visit.id), onSuccess: onVisitChanged })
  const currentReport = reports.data?.at(-1)
  const closed = visit.status === 'Completed' || visit.status === 'Cancelled'
  return <div className="space-y-4">
    <div className="flex flex-wrap gap-2">{canManage && ['Planned', 'Scheduled', 'Rescheduled', 'Overdue'].includes(visit.status) ? <Button type="button" onClick={() => start.mutate()} disabled={start.isPending}>Start visit</Button> : null}<Button type="button" variant="outline" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Close visit workspace' : 'Open visit workspace'}</Button></div>
    {expanded ? <div className="space-y-5 rounded-lg border bg-muted/10 p-4">
      <section className="space-y-3"><div className="flex items-center justify-between"><h4 className="font-semibold">Monitoring activity checklist</h4><span className="text-xs text-muted-foreground">{checklist.data?.filter((item) => item.result !== 'Pending').length ?? 0}/{checklist.data?.length ?? 0} documented</span></div>{checklist.isLoading ? <p className="text-sm text-muted-foreground">Loading checklist…</p> : checklist.error ? <p role="alert" className="text-sm text-destructive">Checklist could not be loaded.</p> : checklist.data?.length ? <ul className="space-y-2">{checklist.data.map((item) => <ChecklistRow key={item.id} item={item} disabled={!canManage || closed} onChanged={() => void checklist.refetch()} />)}</ul> : <p className="text-sm text-muted-foreground">No checklist requirements were configured for this visit type.</p>}</section>
      <section className="border-t pt-4"><ReportBuilder key={`${currentReport?.id ?? 'new'}:${currentReport?.status ?? 'empty'}`} visit={visit} report={currentReport} onChanged={() => void reports.refetch()} /></section>
    </div> : null}
  </div>
}
