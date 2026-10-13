import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useForm, type SubmitHandler } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { PERMISSIONS } from '@/lib/permissions'
import {
  ctmsApi,
  ctmsKeys,
  type CTMSContact,
  type CTMSContactPayload,
  type CTMSMonitoringActivity,
  type CTMSMonitoringActivityPayload,
  type CTMSMonitoringPlan,
  type CTMSMonitoringPlanAmendPayload,
  type CTMSMonitoringPlanPayload,
  type CTMSMonitoringPlanVersionPayload,
  type CTMSTask,
  type CTMSTaskPayload,
  type CTMSTaskUpdatePayload,
  type CTMSTransitionOption,
  useCTMSMonitoringPlans,
  useCTMSProjectOptions,
} from '../api'
import { useCTMSMutation } from '../offline'
import { useCTMSStatusTransition } from '../hooks'
import { CTMSMutationFeedback } from '../components/CTMSMutationFeedback'
import { getCTMSMutationMetadata } from '../components/feedbackMessage'
import { GuardedCTMSAction, ReadOnlyIndicator } from '../components/OwnershipPresentation'
import { CTMSFormField } from './CTMSFormField'
import { CTMSFormShell } from './CTMSFormShell'
import { CTMSStatusTransitionForm } from './StatusTransitionForm'
import {
  applyCTMSServerErrors,
  optionalOwnedStringSchema,
  ownedQuantitySchema,
  ownedStringSchema,
  transitionReasonSchema,
} from './schemas'

const optionalId = optionalOwnedStringSchema({ label: 'Identifier', maxLength: 200 })
const dateTime = ownedStringSchema({ label: 'Date and time', minLength: 1, maxLength: 80 })
const optionalDateTime = optionalOwnedStringSchema({ label: 'Date and time', maxLength: 80 })

const planSchema = z.object({
  name: ownedStringSchema({ label: 'Plan name', maxLength: 255 }),
  description: optionalOwnedStringSchema({ label: 'Description', maxLength: 4000 }),
  site_id: optionalId,
  objectives: optionalOwnedStringSchema({ label: 'Objectives', maxLength: 4000 }),
  frequency: optionalOwnedStringSchema({ label: 'Frequency', maxLength: 100 }),
  frequency_value: z.preprocess((value) => value === '' ? undefined : value, ownedQuantitySchema({ label: 'Frequency value', min: 1, integer: true }).optional()),
  frequency_unit: optionalOwnedStringSchema({ label: 'Frequency unit', maxLength: 50 }),
  completion_criteria: optionalOwnedStringSchema({ label: 'Completion criteria', maxLength: 4000 }),
  risk_level: optionalOwnedStringSchema({ label: 'Risk level', maxLength: 100 }),
  monitoring_strategy: optionalOwnedStringSchema({ label: 'Monitoring strategy', maxLength: 4000 }),
  visit_type: optionalOwnedStringSchema({ label: 'Visit type', maxLength: 100 }),
  modality: optionalOwnedStringSchema({ label: 'Modality', maxLength: 30 }),
  required_activities: optionalOwnedStringSchema({ label: 'Required activities', maxLength: 4000 }),
})
type PlanValues = z.infer<typeof planSchema>
type PlanInput = z.input<typeof planSchema>

const versionSchema = z.object({
  reason: transitionReasonSchema,
  objectives: optionalOwnedStringSchema({ label: 'Objectives', maxLength: 4000 }),
  activity_types: optionalOwnedStringSchema({ label: 'Activity types', maxLength: 1000 }),
  frequency: optionalOwnedStringSchema({ label: 'Frequency', maxLength: 100 }),
  frequency_value: z.preprocess((value) => value === '' ? undefined : value, ownedQuantitySchema({ label: 'Frequency value', min: 1, integer: true }).optional()),
  frequency_unit: optionalOwnedStringSchema({ label: 'Frequency unit', maxLength: 50 }),
  completion_criteria: optionalOwnedStringSchema({ label: 'Completion criteria', maxLength: 4000 }),
  risk_level: optionalOwnedStringSchema({ label: 'Risk level', maxLength: 100 }),
  monitoring_strategy: optionalOwnedStringSchema({ label: 'Monitoring strategy', maxLength: 4000 }),
  visit_type: optionalOwnedStringSchema({ label: 'Visit type', maxLength: 100 }),
  modality: optionalOwnedStringSchema({ label: 'Modality', maxLength: 30 }),
  required_activities: optionalOwnedStringSchema({ label: 'Required activities', maxLength: 4000 }),
})
type VersionValues = z.infer<typeof versionSchema>
type VersionInput = z.input<typeof versionSchema>

const activitySchema = z.object({
  plan_id: ownedStringSchema({ label: 'Monitoring plan', maxLength: 200 }),
  activity_type: ownedStringSchema({ label: 'Activity type', maxLength: 100 }),
  modality: ownedStringSchema({ label: 'Modality', maxLength: 30 }),
  planned_date: dateTime,
  site_id: optionalId,
  assigned_cra_id: optionalId,
  edc_visit_instance_id: optionalId,
})
type ActivityValues = z.infer<typeof activitySchema>
type ActivityInput = z.input<typeof activitySchema>

const taskSchema = z.object({
  title: ownedStringSchema({ label: 'Task title', maxLength: 255 }),
  description: optionalOwnedStringSchema({ label: 'Description', maxLength: 4000 }),
  site_id: optionalId,
  owner_id: optionalId,
  due_date: optionalDateTime,
  priority: optionalOwnedStringSchema({ label: 'Priority', maxLength: 50 }),
})
type TaskValues = z.infer<typeof taskSchema>
type TaskInput = z.input<typeof taskSchema>

const followUpSchema = z.object({
  title: optionalOwnedStringSchema({ label: 'Follow-up title', maxLength: 255 }),
  approved_summary: optionalOwnedStringSchema({ label: 'Approved operational summary', maxLength: 512 }),
  owner_id: optionalId,
  due_date: optionalDateTime,
  priority: optionalOwnedStringSchema({ label: 'Priority', maxLength: 50 }),
})
type FollowUpValues = z.infer<typeof followUpSchema>
type FollowUpInput = z.input<typeof followUpSchema>

const contactSchema = z.object({
  name: ownedStringSchema({ label: 'Contact name', maxLength: 255 }),
  site_id: optionalId,
  role: optionalOwnedStringSchema({ label: 'Role', maxLength: 150 }),
  organization: optionalOwnedStringSchema({ label: 'Organization', maxLength: 255 }),
  owner_id: optionalId,
})
type ContactValues = z.infer<typeof contactSchema>
type ContactInput = z.input<typeof contactSchema>

const actionSchema = z.object({
  assigned_cra_id: optionalId,
  planned_date: optionalDateTime,
  reason: optionalOwnedStringSchema({ label: 'Reason', maxLength: 2000 }),
  evidence: optionalOwnedStringSchema({ label: 'Completion evidence', maxLength: 4000 }),
  notes: optionalOwnedStringSchema({ label: 'Completion notes', maxLength: 4000 }),
})
type ActionValues = z.infer<typeof actionSchema>
type ActionInput = z.input<typeof actionSchema>

function toIso(value: string | undefined): string | undefined {
  if (!value) return undefined
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toISOString()
}

function optional(value: string | undefined): string | undefined {
  return value && value.trim() ? value.trim() : undefined
}

function projectOptionLabel(option: { label: string; secondary_label?: string | null }) {
  return option.secondary_label ? `${option.label} · ${option.secondary_label}` : option.label
}

function withCurrentOption(options: Array<{ value: string; label: string }>, current?: string | null) {
  if (!current || options.some((option) => option.value === current)) return options
  return [{ value: current, label: 'Current selection (no longer available)' }, ...options]
}

function versionPayload(values: { objectives?: string; activity_types?: string; frequency?: string; frequency_value?: number; frequency_unit?: string; completion_criteria?: string; risk_level?: string; monitoring_strategy?: string; visit_type?: string; modality?: string; required_activities?: string }): CTMSMonitoringPlanVersionPayload {
  const visitType = optional(values.visit_type)
  return {
    objectives: optional(values.objectives),
    activity_types: values.activity_types?.split(',').map((item) => item.trim()).filter(Boolean) ?? (visitType ? [visitType] : []),
    frequency: optional(values.frequency),
    frequency_value: values.frequency_value,
    frequency_unit: optional(values.frequency_unit),
    completion_criteria: optional(values.completion_criteria),
    risk_level: optional(values.risk_level),
    monitoring_strategy: optional(values.monitoring_strategy),
    visit_rules: visitType ? [{ visit_type: visitType, frequency_value: values.frequency_value, frequency_unit: optional(values.frequency_unit), allowed_modalities: optional(values.modality) ? [values.modality!.trim()] : ['On-site'], required_activities: values.required_activities?.split('\n').map((item) => item.trim()).filter(Boolean) ?? [], report_due_days: 10 }] : [],
  }
}

function mutationProps(mutation: { status: 'idle' | 'pending' | 'success' | 'error'; data?: unknown; error?: unknown }) {
  const metadata = getCTMSMutationMetadata(mutation.data ?? mutation.error)
  return { status: mutation.status, data: mutation.data, error: mutation.error, requestId: metadata.requestId, correlationId: metadata.correlationId }
}

export interface CTMSFormCallbacks<T> {
  onSaved?: (value: T) => void
  onCancel?: () => void
  correlationId?: string
}

export function MonitoringPlanForm({ studyId, initial, onSaved, onCancel, correlationId }: CTMSFormCallbacks<CTMSMonitoringPlan> & { studyId: string; initial?: CTMSMonitoringPlan }) {
  const client = useQueryClient()
  const projectOptions = useCTMSProjectOptions(studyId)
  const siteOptions = withCurrentOption((projectOptions.data?.sites ?? []).map((site) => ({ value: site.id, label: projectOptionLabel(site) })), initial?.site_id)
  const methods = useForm<PlanInput, unknown, PlanValues>({
    resolver: zodResolver(planSchema),
    defaultValues: {
      name: initial?.name ?? '', description: initial?.description ?? '', site_id: initial?.site_id ?? '',
      objectives: '', frequency: '', frequency_value: undefined, frequency_unit: '', completion_criteria: '', risk_level: '', monitoring_strategy: '', visit_type: 'Routine Monitoring', modality: 'Hybrid', required_activities: 'Review informed consent documentation\nReview subject eligibility\nReview adverse event / SAE reporting\nReview investigational product accountability\nVerify critical source data\nReview protocol deviations\nReview essential site documents',
    },
  })
  const mutation = useCTMSMutation({
    mutationFn: (values: PlanValues) => {
      const payload: CTMSMonitoringPlanPayload = {
        name: values.name, description: optional(values.description), site_id: optional(values.site_id), correlation_id: correlationId,
        ...(initial ? {} : { version: versionPayload(values) }),
      }
      return initial ? ctmsApi.updateMonitoringPlan(initial.id, payload) : ctmsApi.createMonitoringPlan(studyId, payload)
    },
    onSuccess: (value) => { void client.invalidateQueries({ queryKey: ctmsKeys.monitoringPlans(studyId) }); onSaved?.(value) },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  const onSubmit: SubmitHandler<PlanValues> = (values) => mutation.mutate(values)
  return (
    <CTMSFormShell methods={methods} title={initial ? 'Update monitoring plan' : 'Create monitoring plan'} description="Monitoring plans and versions are CTMS-owned operational configuration. EDC Visit Instances remain read-only references." onSubmit={onSubmit} onCancel={onCancel} submitLabel={initial ? 'Update plan' : 'Create plan'} initialFocusName="name" mutation={{ action: initial ? 'Update monitoring plan' : 'Create monitoring plan', ...mutationProps(mutation) }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <CTMSFormField control={methods.control} name="name" label="Plan name" required />
        <CTMSFormField control={methods.control} name="site_id" label="Site scope" type="select" options={siteOptions} description={projectOptions.isLoading ? 'Loading study sites…' : 'Leave blank for a study-level plan.'} disabled={projectOptions.isLoading} />
      </div>
      <CTMSFormField control={methods.control} name="description" label="Description" type="textarea" />
      {!initial ? <div className="space-y-3 rounded border bg-muted/20 p-3"><h3 className="font-medium">Initial plan version</h3><div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={methods.control} name="objectives" label="Objectives" /><CTMSFormField control={methods.control} name="frequency" label="Frequency" /><CTMSFormField control={methods.control} name="frequency_value" label="Frequency value" type="number" /><CTMSFormField control={methods.control} name="frequency_unit" label="Frequency unit" /><CTMSFormField control={methods.control} name="risk_level" label="Risk level" /><CTMSFormField control={methods.control} name="visit_type" label="Visit type" required /><CTMSFormField control={methods.control} name="modality" label="Allowed modality" required /></div><CTMSFormField control={methods.control} name="required_activities" label="Required activities" type="textarea" description="Enter one evidence-bearing checklist requirement per line." /><CTMSFormField control={methods.control} name="monitoring_strategy" label="Monitoring strategy" type="textarea" /><CTMSFormField control={methods.control} name="completion_criteria" label="Completion criteria" type="textarea" /></div> : null}
    </CTMSFormShell>
  )
}

export function MonitoringPlanVersionForm({ planId, onSaved, onCancel, correlationId }: CTMSFormCallbacks<unknown> & { planId: string }) {
  const client = useQueryClient()
  const methods = useForm<VersionInput, unknown, VersionValues>({ resolver: zodResolver(versionSchema), defaultValues: { reason: '', objectives: '', activity_types: '', frequency: '', frequency_value: undefined, frequency_unit: '', completion_criteria: '', risk_level: '', monitoring_strategy: '', visit_type: '', modality: 'Hybrid', required_activities: '' } })
  const mutation = useCTMSMutation({
    mutationFn: (values: VersionValues) => {
      const payload: CTMSMonitoringPlanAmendPayload = { reason: values.reason, changes: versionPayload(values), correlation_id: correlationId }
      return ctmsApi.amendMonitoringPlan(planId, payload)
    },
    onSuccess: (value) => { void client.invalidateQueries({ queryKey: ['ctms', 'monitoring-plans'] }); void client.invalidateQueries({ queryKey: ['ctms', 'monitoring-plan-versions', planId] }); onSaved?.(value) },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  return <CTMSFormShell methods={methods} title="Amend monitoring plan version" description="An amendment creates a new server-controlled version; the prior version is not edited in place." onSubmit={(values) => mutation.mutate(values)} onCancel={onCancel} submitLabel="Amend version" initialFocusName="reason" mutation={{ action: 'Amend monitoring plan version', ...mutationProps(mutation) }}><CTMSFormField control={methods.control} name="reason" label="Amendment reason" type="textarea" required /><div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={methods.control} name="objectives" label="Objectives" /><CTMSFormField control={methods.control} name="activity_types" label="Activity types" description="Comma-separated operational activity types." /><CTMSFormField control={methods.control} name="frequency" label="Frequency" /><CTMSFormField control={methods.control} name="frequency_value" label="Frequency value" type="number" /><CTMSFormField control={methods.control} name="frequency_unit" label="Frequency unit" /><CTMSFormField control={methods.control} name="risk_level" label="Risk level" /><CTMSFormField control={methods.control} name="visit_type" label="Replacement visit rule type" /><CTMSFormField control={methods.control} name="modality" label="Allowed modality" /></div><CTMSFormField control={methods.control} name="required_activities" label="Required activities" type="textarea" description="One requirement per line. Supplying a visit rule replaces inherited rules for this draft." /><CTMSFormField control={methods.control} name="monitoring_strategy" label="Monitoring strategy" type="textarea" /><CTMSFormField control={methods.control} name="completion_criteria" label="Completion criteria" type="textarea" /></CTMSFormShell>
}

export function MonitoringPlanVersionActions({ planId, canManage = true, onChanged }: { planId: string; canManage?: boolean; onChanged?: () => void }) {
  const client = useQueryClient()
  const [showAmend, setShowAmend] = React.useState(false)
  const mutation = useCTMSMutation({ mutationFn: () => ctmsApi.publishMonitoringPlan(planId), onSuccess: () => { void client.invalidateQueries({ queryKey: ['ctms', 'monitoring-plans'] }); onChanged?.() } })
  if (!canManage) return <ReadOnlyIndicator reason="Only authorized CTMS users can publish or amend monitoring plan versions." />
  return <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate()}>Publish current version</Button><Button type="button" variant="outline" onClick={() => setShowAmend((value) => !value)}>{showAmend ? 'Close amendment' : 'Amend version'}</Button>{showAmend ? <div className="basis-full"><MonitoringPlanVersionForm planId={planId} onSaved={() => { setShowAmend(false); onChanged?.() }} onCancel={() => setShowAmend(false)} /></div> : null}<CTMSMutationFeedback action="Publish monitoring plan version" {...mutationProps(mutation)} /></div>
}

export function MonitoringActivityForm({ studyId, initial, onSaved, onCancel, correlationId }: CTMSFormCallbacks<CTMSMonitoringActivity> & { studyId: string; initial?: CTMSMonitoringActivity }) {
  const client = useQueryClient()
  const plans = useCTMSMonitoringPlans(studyId, { pagination: { pageSize: 100 } })
  const projectOptions = useCTMSProjectOptions(studyId)
  const selectedPlanId = (plans.data?.items ?? []).find((plan) => plan.current_version_id === initial?.plan_version_id)?.id ?? ''
  const planOptions = withCurrentOption((plans.data?.items ?? []).map((plan) => ({ value: plan.id, label: `${plan.name} · ${plan.site_id ? projectOptions.data?.sites.find((site) => site.id === plan.site_id)?.label ?? 'Site plan' : 'Study plan'} · ${plan.status}` })), selectedPlanId)
  const siteOptions = withCurrentOption((projectOptions.data?.sites ?? []).map((site) => ({ value: site.id, label: projectOptionLabel(site) })), initial?.site_id)
  const craOptions = withCurrentOption((projectOptions.data?.users ?? []).map((user) => ({ value: user.id, label: projectOptionLabel(user) })), initial?.assigned_cra_id)
  const methods = useForm<ActivityInput, unknown, ActivityValues>({ resolver: zodResolver(activitySchema), defaultValues: { plan_id: '', activity_type: initial?.activity_type ?? 'Routine Monitoring', modality: initial?.modality ?? 'Hybrid', planned_date: initial?.planned_date?.slice(0, 16) ?? '', site_id: initial?.site_id ?? '', assigned_cra_id: initial?.assigned_cra_id ?? '', edc_visit_instance_id: initial?.edc_visit_instance_id ?? '' } })
  React.useEffect(() => {
    if (initial && selectedPlanId && !methods.getValues('plan_id')) methods.setValue('plan_id', selectedPlanId)
  }, [initial, methods, selectedPlanId])
  const mutation = useCTMSMutation({
    mutationFn: (values: ActivityValues) => {
      const payload: CTMSMonitoringActivityPayload = { plan_id: values.plan_id, activity_type: values.activity_type, modality: values.modality, planned_date: toIso(values.planned_date) ?? values.planned_date, site_id: optional(values.site_id), assigned_cra_id: optional(values.assigned_cra_id), edc_visit_instance_id: optional(values.edc_visit_instance_id), correlation_id: correlationId }
      return initial ? ctmsApi.updateMonitoringActivity(initial.id, payload) : ctmsApi.createMonitoringActivity(studyId, payload)
    },
    onSuccess: (value) => { void client.invalidateQueries({ queryKey: ctmsKeys.monitoringActivities(studyId) }); void client.invalidateQueries({ queryKey: ctmsKeys.monitoringPlans(studyId) }); onSaved?.(value) },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  return <CTMSFormShell methods={methods} title={initial ? 'Update monitoring visit' : 'Schedule monitoring visit'} description="Choose configured study records; canonical identifiers are submitted by the application and are never typed by the user." onSubmit={(values) => mutation.mutate(values)} onCancel={onCancel} submitLabel={initial ? 'Update visit' : 'Schedule visit'} initialFocusName="plan_id" mutation={{ action: initial ? 'Update monitoring visit' : 'Schedule monitoring visit', ...mutationProps(mutation) }}><div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={methods.control} name="plan_id" label="Monitoring plan" type="select" options={planOptions} required disabled={plans.isLoading} description={plans.isLoading ? 'Loading monitoring plans…' : plans.data?.items.length ? 'The approved plan version will be captured when scheduled.' : 'Create a monitoring plan before scheduling a visit.'} /><CTMSFormField control={methods.control} name="activity_type" label="Visit type" type="select" options={[{ value: 'Site Qualification Visit', label: 'Site Qualification Visit (SQV / PSV)' }, { value: 'Site Initiation Visit', label: 'Site Initiation Visit (SIV)' }, { value: 'Routine Monitoring', label: 'Interim Monitoring Visit (IMV)' }, { value: 'Remote Monitoring Visit', label: 'Remote Monitoring Visit (RMV)' }, { value: 'Site Close-Out Visit', label: 'Site Close-Out Visit (COV)' }, { value: 'Unscheduled Visit', label: 'Unscheduled Visit' }]} required /><CTMSFormField control={methods.control} name="modality" label="Modality" type="select" options={[{ value: 'On-site', label: 'On-site' }, { value: 'Remote', label: 'Remote' }, { value: 'Hybrid', label: 'Hybrid' }]} required /><CTMSFormField control={methods.control} name="planned_date" label="Planned date and time" type="datetime-local" required /><CTMSFormField control={methods.control} name="site_id" label="Site" type="select" options={siteOptions} disabled={projectOptions.isLoading} description={projectOptions.isLoading ? 'Loading study sites…' : 'Optional for study-level monitoring activities.'} /><CTMSFormField control={methods.control} name="assigned_cra_id" label="Assigned CRA" type="select" options={craOptions} disabled={projectOptions.isLoading} description={projectOptions.isLoading ? 'Loading study team…' : 'Only active users assigned to this study are available.'} /></div>{initial?.edc_visit_instance_id ? <p className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">Linked EDC visit instance is retained as a read-only integration reference.</p> : null}</CTMSFormShell>
}

export function MonitoringActivityActions({ activity, onChanged }: { activity: CTMSMonitoringActivity; onChanged?: () => void }) {
  const client = useQueryClient()
  const projectOptions = useCTMSProjectOptions(activity.study_id)
  const craOptions = withCurrentOption((projectOptions.data?.users ?? []).map((user) => ({ value: user.id, label: projectOptionLabel(user) })), activity.assigned_cra_id)
  const [mode, setMode] = React.useState<'assign' | 'reschedule' | 'complete' | 'cancel' | null>(null)
  const methods = useForm<ActionInput, unknown, ActionValues>({ resolver: zodResolver(actionSchema), defaultValues: { assigned_cra_id: activity.assigned_cra_id ?? '', planned_date: activity.planned_date.slice(0, 16), reason: '', evidence: '', notes: '' } })
  const mutation = useCTMSMutation({
    mutationFn: (values: ActionValues) => {
      if (mode === 'assign') return ctmsApi.assignMonitoringActivity(activity.id, { assigned_cra_id: values.assigned_cra_id ?? '' })
      if (mode === 'reschedule') return ctmsApi.rescheduleMonitoringActivity(activity.id, { planned_date: toIso(values.planned_date) ?? values.planned_date ?? '', reason: values.reason ?? '' })
      if (mode === 'complete') return ctmsApi.completeMonitoringActivity(activity.id, { evidence: values.evidence ?? '', notes: optional(values.notes) })
      return ctmsApi.cancelMonitoringActivity(activity.id, { reason: values.reason ?? '' })
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: ctmsKeys.monitoringActivities(activity.study_id) }); setMode(null); onChanged?.() },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  const submit = (values: ActionValues) => {
    if (mode === 'assign' && !values.assigned_cra_id) { methods.setError('assigned_cra_id', { type: 'required', message: 'Assigned CRA ID is required' }); return }
    if (mode === 'reschedule' && (!values.planned_date || !values.reason)) { if (!values.planned_date) methods.setError('planned_date', { type: 'required', message: 'A new planned date is required' }); if (!values.reason) methods.setError('reason', { type: 'required', message: 'A rescheduling reason is required' }); return }
    if (mode === 'complete' && !values.evidence) { methods.setError('evidence', { type: 'required', message: 'Completion evidence is required' }); return }
    if (mode === 'cancel' && !values.reason) { methods.setError('reason', { type: 'required', message: 'A cancellation reason is required' }); return }
    mutation.mutate(values)
  }
  return <div className="space-y-2"><div className="flex flex-wrap gap-2"><GuardedCTMSAction permission={PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT} studyId={activity.study_id} onClick={() => setMode('assign')}>Assign CRA</GuardedCTMSAction><GuardedCTMSAction permission={PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT} studyId={activity.study_id} onClick={() => setMode('reschedule')}>Reschedule activity</GuardedCTMSAction><GuardedCTMSAction permission={PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT} studyId={activity.study_id} onClick={() => setMode('complete')}>Complete activity</GuardedCTMSAction><GuardedCTMSAction permission={PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT} studyId={activity.study_id} onClick={() => setMode('cancel')}>Cancel activity</GuardedCTMSAction></div>{mode ? <CTMSFormShell methods={methods} title={`${mode[0].toUpperCase()}${mode.slice(1)} monitoring activity`} description="The CTMS API validates current status and allowed transition policy. EDC Visit Instance lifecycle is never changed." onSubmit={submit} onCancel={() => setMode(null)} submitLabel={mode === 'assign' ? 'Assign' : mode === 'reschedule' ? 'Reschedule' : mode === 'complete' ? 'Complete' : 'Cancel'} initialFocusName={mode === 'assign' ? 'assigned_cra_id' : mode === 'complete' ? 'evidence' : mode === 'reschedule' ? 'planned_date' : 'reason'} mutation={{ action: `${mode} monitoring activity`, ...mutationProps(mutation) }}>{mode === 'assign' ? <CTMSFormField control={methods.control} name="assigned_cra_id" label="Assigned CRA" type="select" options={craOptions} disabled={projectOptions.isLoading} required /> : null}{mode === 'reschedule' ? <><CTMSFormField control={methods.control} name="planned_date" label="New planned date and time" type="datetime-local" required /><CTMSFormField control={methods.control} name="reason" label="Rescheduling reason" type="textarea" required /></> : null}{mode === 'complete' ? <><CTMSFormField control={methods.control} name="evidence" label="Completion evidence" type="textarea" required /><CTMSFormField control={methods.control} name="notes" label="Completion notes" type="textarea" /></> : null}{mode === 'cancel' ? <CTMSFormField control={methods.control} name="reason" label="Cancellation reason" type="textarea" required /> : null}</CTMSFormShell> : null}</div>
}

export function OperationalTaskForm({ studyId, initial, onSaved, onCancel, correlationId }: CTMSFormCallbacks<CTMSTask> & { studyId: string; initial?: CTMSTask }) {
  const client = useQueryClient()
  const methods = useForm<TaskInput, unknown, TaskValues>({ resolver: zodResolver(taskSchema), defaultValues: { title: initial?.title ?? '', description: initial?.description ?? '', site_id: initial?.site_id ?? '', owner_id: initial?.owner_id ?? '', due_date: initial?.due_date?.slice(0, 16) ?? '', priority: initial?.priority ?? 'normal' } })
  const mutation = useCTMSMutation({
    mutationFn: (values: TaskValues) => {
      const base = { title: values.title, description: optional(values.description), owner_id: optional(values.owner_id), due_date: toIso(values.due_date), priority: optional(values.priority), correlation_id: correlationId }
      return initial ? ctmsApi.updateTask(initial.id, base satisfies CTMSTaskUpdatePayload) : ctmsApi.createTask(studyId, { ...base, site_id: optional(values.site_id) } satisfies CTMSTaskPayload)
    },
    onSuccess: (value) => { void client.invalidateQueries({ queryKey: ctmsKeys.tasks(studyId) }); void client.invalidateQueries({ queryKey: ctmsKeys.dashboard(studyId) }); onSaved?.(value) },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  return <CTMSFormShell methods={methods} title={initial ? 'Update operational task' : 'Create operational task'} description="Tasks are CTMS operational follow-up records. They do not change EDC Query lifecycle or clinical data." onSubmit={(values) => mutation.mutate(values)} onCancel={onCancel} submitLabel={initial ? 'Update task' : 'Create task'} initialFocusName="title" mutation={{ action: initial ? 'Update operational task' : 'Create operational task', ...mutationProps(mutation) }}><CTMSFormField control={methods.control} name="title" label="Task title" required /><CTMSFormField control={methods.control} name="description" label="Description" type="textarea" /><div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={methods.control} name="site_id" label="Site ID (optional)" /><CTMSFormField control={methods.control} name="owner_id" label="Assigned owner ID" /><CTMSFormField control={methods.control} name="due_date" label="Due date and time" type="datetime-local" /><CTMSFormField control={methods.control} name="priority" label="Priority" /></div></CTMSFormShell>
}

export function QueryFollowUpForm({ queryId, studyId, onSaved, onCancel }: CTMSFormCallbacks<CTMSTask> & { queryId: string; studyId?: string }) {
  const client = useQueryClient()
  const methods = useForm<FollowUpInput, unknown, FollowUpValues>({ resolver: zodResolver(followUpSchema), defaultValues: { title: '', approved_summary: '', owner_id: '', due_date: '', priority: 'normal' } })
  const mutation = useCTMSMutation({
    mutationFn: (values: FollowUpValues) => ctmsApi.createQueryFollowUp(queryId, { title: optional(values.title), approved_summary: optional(values.approved_summary), owner_id: optional(values.owner_id), due_date: toIso(values.due_date), priority: optional(values.priority) }),
    onSuccess: (value) => { if (studyId) { void client.invalidateQueries({ queryKey: ctmsKeys.tasks(studyId) }); void client.invalidateQueries({ queryKey: ctmsKeys.dashboard(studyId) }) } onSaved?.(value) },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  return <CTMSFormShell methods={methods} title="Create operational query follow-up" description="This creates a CTMS task from an approved query reference. Query status, response, closure, and reopening remain EDC-owned." onSubmit={(values) => mutation.mutate(values)} onCancel={onCancel} submitLabel="Create follow-up" initialFocusName="title" mutation={{ action: 'Create operational query follow-up', ...mutationProps(mutation) }}><p className="rounded border border-info/30 bg-info/10 p-3 text-sm text-info-foreground">EDC Query ID: <span className="font-mono">{queryId}</span>. Only the operational follow-up is created.</p><CTMSFormField control={methods.control} name="title" label="Follow-up title" /><CTMSFormField control={methods.control} name="approved_summary" label="Approved operational summary" type="textarea" description="Do not enter unrestricted clinical query text." /><div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={methods.control} name="owner_id" label="Assigned owner ID" /><CTMSFormField control={methods.control} name="due_date" label="Due date and time" type="datetime-local" /><CTMSFormField control={methods.control} name="priority" label="Priority" /></div></CTMSFormShell>
}

export function OperationalTaskStatusForm({ task, transitionOptions, onSaved, onCancel }: { task: CTMSTask; transitionOptions: readonly CTMSTransitionOption[]; onSaved?: (value: CTMSTask) => void; onCancel?: () => void }) {
  const mutation = useCTMSStatusTransition({
    resource: 'tasks',
    recordId: task.id,
    studyId: task.study_id,
    currentStatus: task.status,
    mutationFn: async (payload) => ctmsApi.transitionTask(task.id, { status: payload.status, reason: payload.reason ?? '' }),
  })
  return <CTMSStatusTransitionForm
    currentStatus={mutation.currentStatus ?? task.status}
    allowedTransitions={mutation.allowedTransitions ?? task.allowed_transitions ?? transitionOptions}
    mutation={mutation}
    onSuccess={(result) => onSaved?.(result.resource)}
    onCancel={onCancel}
    title="Transition operational task"
    description="Only statuses returned by the server are available. Query lifecycle actions remain in EDC."
    submitLabel="Transition task"
  />
}

export function OperationalContactForm({ studyId, initial, onSaved, onCancel, correlationId }: CTMSFormCallbacks<CTMSContact> & { studyId: string; initial?: CTMSContact }) {
  const client = useQueryClient()
  const methods = useForm<ContactInput, unknown, ContactValues>({ resolver: zodResolver(contactSchema), defaultValues: { name: initial?.name ?? '', site_id: initial?.site_id ?? '', role: initial?.role ?? '', organization: initial?.organization ?? '', owner_id: initial?.owner_id ?? '' } })
  const mutation = useCTMSMutation({
    mutationFn: (values: ContactValues) => {
      const payload: CTMSContactPayload = { name: values.name, site_id: optional(values.site_id), role: optional(values.role), organization: optional(values.organization), owner_id: optional(values.owner_id), correlation_id: correlationId }
      return initial ? ctmsApi.updateContact(initial.id, payload) : ctmsApi.createContact(studyId, payload)
    },
    onSuccess: (value) => { void client.invalidateQueries({ queryKey: ctmsKeys.contacts(studyId) }); void client.invalidateQueries({ queryKey: ctmsKeys.dashboard(studyId) }); onSaved?.(value) },
    onError: (error) => { applyCTMSServerErrors(error, methods.setError) },
  })
  return <CTMSFormShell methods={methods} title={initial ? 'Update operational contact' : 'Create operational contact'} description="Contacts are CTMS operational records and do not alter EDC user, site, or clinical identities." onSubmit={(values) => mutation.mutate(values)} onCancel={onCancel} submitLabel={initial ? 'Update contact' : 'Create contact'} initialFocusName="name" mutation={{ action: initial ? 'Update operational contact' : 'Create operational contact', ...mutationProps(mutation) }}><div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={methods.control} name="name" label="Name" required /><CTMSFormField control={methods.control} name="role" label="Role" /><CTMSFormField control={methods.control} name="organization" label="Organization" /><CTMSFormField control={methods.control} name="site_id" label="Site ID (optional)" /><CTMSFormField control={methods.control} name="owner_id" label="Assigned owner ID" /></div></CTMSFormShell>
}

export function OperationalContactStatusForm({ contact, transitionOptions, onSaved, onCancel }: { contact: CTMSContact; transitionOptions: readonly CTMSTransitionOption[]; onSaved?: (value: CTMSContact) => void; onCancel?: () => void }) {
  const mutation = useCTMSStatusTransition({
    resource: 'contacts',
    recordId: contact.id,
    studyId: contact.study_id,
    currentStatus: contact.status,
    mutationFn: async (payload) => ctmsApi.transitionContact(contact.id, { status: payload.status, reason: payload.reason ?? '' }),
  })
  return <CTMSStatusTransitionForm
    currentStatus={mutation.currentStatus ?? contact.status}
    allowedTransitions={mutation.allowedTransitions ?? contact.allowed_transitions ?? transitionOptions}
    mutation={mutation}
    onSuccess={(result) => onSaved?.(result.resource)}
    onCancel={onCancel}
    title="Transition operational contact"
    description="Only server-returned contact statuses are available."
    submitLabel="Transition contact"
  />
}

export const StatusTransitionForm = OperationalTaskStatusForm
