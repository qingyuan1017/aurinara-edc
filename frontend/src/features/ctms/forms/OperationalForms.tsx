import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { useForm, type DefaultValues, type FieldValues } from 'react-hook-form'
import { z } from 'zod'
import {
  ctmsApi,
  type CTMSActivationAction,
  type CTMSEnrollmentTarget,
  type CTMSOperationalMilestone,
  type CTMSOperationalSite,
  type CTMSOperationalStudy,
  type CTMSStatusOption,
  type CTMSStudyPlan,
} from '../api'
import { invalidateCTMSMutation, type CTMSMutationResource } from '../cache'
import { useCTMSMutation } from '../offline'
import { CTMSFormField, type CTMSSelectOption } from './CTMSFormField'
import { CTMSFormShell } from './CTMSFormShell'
import {
  mapCTMSServerErrors,
  optionalOwnedStringSchema,
  ownedDateSchema,
  ownedQuantitySchema,
} from './schemas'

const optionalText = (value: string | undefined) => value?.trim() ? value.trim() : undefined
const toUtcDate = (value: string) => `${value}T00:00:00.000Z`

function statusChoices(options: readonly (CTMSStatusOption | string)[] | undefined): CTMSSelectOption[] {
  return (options ?? []).map((option) => typeof option === 'string' ? { value: option, label: option } : { value: option.value, label: option.label ?? option.value })
}

function useOperationalForm<T extends FieldValues>(
  defaults: DefaultValues<T>,
  schema: z.ZodType,
  action: string,
  resource: CTMSMutationResource,
  scope: { studyId?: string; siteId?: string },
  mutate: (values: T) => Promise<unknown>,
  onSaved?: (value: unknown) => void,
) {
  const methods = useForm<T>({ defaultValues: defaults, resolver: zodResolver(schema as never) as never })
  const [formMessage, setFormMessage] = useState<string | undefined>()
  const client = useQueryClient()
  const mutation = useCTMSMutation({
    mutationFn: mutate,
    onSuccess: async (value) => {
      setFormMessage(undefined)
      await invalidateCTMSMutation(client, resource, scope)
      onSaved?.(value)
    },
    onError: (error) => {
      const mapped = mapCTMSServerErrors(error, methods.setError)
      setFormMessage(mapped.formMessage)
    },
  })
  return { methods, mutation, formMessage, action }
}

function FormIdentity({ label, id, note }: { label: string; id: string; note: string }) {
  return <Alert><AlertTitle>Canonical {label} ID: <span className="font-mono">{id}</span></AlertTitle><AlertDescription>{note}</AlertDescription></Alert>
}

const studySchema = z.object({
  sponsor: optionalOwnedStringSchema({ label: 'Sponsor', maxLength: 255 }),
  phase: optionalOwnedStringSchema({ label: 'Operational phase', maxLength: 50 }),
  therapeuticArea: optionalOwnedStringSchema({ label: 'Therapeutic area', maxLength: 255 }),
  indication: optionalOwnedStringSchema({ label: 'Operational indication', maxLength: 255 }),
  operationalOwnerId: optionalOwnedStringSchema({ label: 'Operational owner ID', maxLength: 200 }),
  status: optionalOwnedStringSchema({ label: 'Operational status', maxLength: 100 }),
})
type StudyFormValues = {
  sponsor?: string
  phase?: string
  therapeuticArea?: string
  indication?: string
  operationalOwnerId?: string
  status?: string
}

export interface OperationalStudyFormProps {
  studyId: string
  initialValue?: CTMSOperationalStudy
  statusOptions?: readonly (CTMSStatusOption | string)[]
  onSaved?: (value: CTMSOperationalStudy) => void
  onCancel?: () => void
}

export function OperationalStudyForm({ studyId, initialValue, statusOptions, onSaved, onCancel }: OperationalStudyFormProps) {
  const isUpdate = Boolean(initialValue?.id)
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<StudyFormValues>(
    {
      sponsor: initialValue?.sponsor ?? '', phase: initialValue?.phase ?? '', therapeuticArea: initialValue?.therapeutic_area ?? '', indication: initialValue?.indication ?? '', operationalOwnerId: initialValue?.operational_owner_id ?? '', status: initialValue?.status ?? '',
    },
    studySchema,
    isUpdate ? 'Update operational study profile' : 'Create operational study profile',
    'study-profile',
    { studyId },
    async (values) => {
      const payload = {
        sponsor: optionalText(values.sponsor), phase: optionalText(values.phase), therapeutic_area: optionalText(values.therapeuticArea), indication: optionalText(values.indication), operational_owner_id: optionalText(values.operationalOwnerId),
        ...(values.status && !isUpdate ? { status: values.status } : {}),
      }
      return isUpdate ? ctmsApi.updateStudyProfile(initialValue!.id, payload) : ctmsApi.createStudyProfile(studyId, payload)
    },
    (value) => onSaved?.(value as CTMSOperationalStudy),
  )
  return <CTMSFormShell methods={state.methods} title={state.action} description="Only CTMS-owned operational profile fields can be changed. The EDC Study identity remains canonical and read-only." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update profile' : 'Create profile'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Study" id={studyId} note="This reference scopes the CTMS request; it does not replace EDC Study identity or clinical configuration." />
    <div className="grid gap-4 sm:grid-cols-2">
      <CTMSFormField control={state.methods.control} name="sponsor" label="Operational sponsor" />
      <CTMSFormField control={state.methods.control} name="phase" label="Operational phase" />
      <CTMSFormField control={state.methods.control} name="therapeuticArea" label="Therapeutic area" />
      <CTMSFormField control={state.methods.control} name="indication" label="Operational indication" />
      <CTMSFormField control={state.methods.control} name="operationalOwnerId" label="Operational owner ID" description="A CTMS owner reference, not a clinical identity." />
      {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Operational status" type="select" options={choices} /> : null}
    </div>
  </CTMSFormShell>
}

const planSchema = z.object({ title: z.string().trim().min(1, 'Plan title is required').max(255), objective: optionalOwnedStringSchema({ label: 'Objective' }), ownerId: optionalOwnedStringSchema({ label: 'Owner ID', maxLength: 200 }), status: optionalOwnedStringSchema({ label: 'Plan status', maxLength: 100 }) })
type PlanFormValues = { title: string; objective?: string; ownerId?: string; status?: string }

export interface StudyPlanFormProps {
  studyId: string
  initialValue?: CTMSStudyPlan
  statusOptions?: readonly (CTMSStatusOption | string)[]
  onSaved?: (value: CTMSStudyPlan) => void
  onCancel?: () => void
}

export function StudyPlanForm({ studyId, initialValue, statusOptions, onSaved, onCancel }: StudyPlanFormProps) {
  const isUpdate = Boolean(initialValue?.id)
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<PlanFormValues>({ title: initialValue?.title ?? '', objective: initialValue?.objective ?? '', ownerId: initialValue?.owner_id ?? '', status: initialValue?.status ?? '' }, planSchema, isUpdate ? 'Update study plan' : 'Create study plan', 'plan', { studyId }, async (values) => {
    const payload = { title: values.title.trim(), objective: optionalText(values.objective), owner_id: optionalText(values.ownerId), ...(values.status ? { status: values.status } : {}) }
    return isUpdate ? ctmsApi.updatePlan(initialValue!.id, payload) : ctmsApi.createPlan(studyId, payload)
  }, (value) => onSaved?.(value as CTMSStudyPlan))
  return <CTMSFormShell methods={state.methods} title={state.action} description="This plan contains CTMS operational planning only; it cannot change EDC study versions or clinical data." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update plan' : 'Create plan'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Study" id={studyId} note="The canonical EDC Study is referenced for scope; this form creates or updates a CTMS plan." />
    <CTMSFormField control={state.methods.control} name="title" label="Plan title" required />
    <CTMSFormField control={state.methods.control} name="objective" label="Operational objective" type="textarea" />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="ownerId" label="Operational owner ID" />{choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Plan status" type="select" options={choices} /> : null}</div>
  </CTMSFormShell>
}

const siteSchema = z.object({ studyId: optionalOwnedStringSchema({ label: 'Study ID', maxLength: 200 }), monitoringReadiness: optionalOwnedStringSchema({ label: 'Monitoring readiness', maxLength: 30 }), responsibleRole: optionalOwnedStringSchema({ label: 'Responsible role', maxLength: 150 }), plannedActivationDate: z.preprocess((value) => value === '' ? undefined : value, ownedDateSchema.optional()), status: optionalOwnedStringSchema({ label: 'Operational site status', maxLength: 100 }) })
type SiteFormValues = { studyId?: string; monitoringReadiness?: string; responsibleRole?: string; plannedActivationDate?: string; status?: string }

export interface OperationalSiteFormProps {
  siteId: string
  studyId?: string
  initialValue?: CTMSOperationalSite
  statusOptions?: readonly (CTMSStatusOption | string)[]
  onSaved?: (value: CTMSOperationalSite) => void
  onCancel?: () => void
}

export function OperationalSiteForm({ siteId, studyId, initialValue, statusOptions, onSaved, onCancel }: OperationalSiteFormProps) {
  const isUpdate = Boolean(initialValue?.id)
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<SiteFormValues>({ studyId: studyId ?? initialValue?.study_id ?? '', monitoringReadiness: initialValue?.monitoring_readiness ?? '', responsibleRole: initialValue?.responsible_role ?? '', plannedActivationDate: initialValue?.planned_activation_date?.slice(0, 10) ?? '', status: initialValue?.status ?? '' }, siteSchema, isUpdate ? 'Update operational site profile' : 'Create operational site profile', 'site-profile', { studyId, siteId }, async (values) => {
    const payload = { monitoring_readiness: optionalText(values.monitoringReadiness), responsible_role: optionalText(values.responsibleRole), planned_activation_date: values.plannedActivationDate ? toUtcDate(values.plannedActivationDate) : undefined, ...(values.studyId ? { study_id: values.studyId } : {}), ...(values.status && !isUpdate ? { status: values.status } : {}) }
    return isUpdate ? ctmsApi.updateSiteProfile(initialValue!.id, { monitoring_readiness: payload.monitoring_readiness, responsible_role: payload.responsible_role, planned_activation_date: payload.planned_activation_date }) : ctmsApi.createSiteProfile(siteId, payload)
  }, (value) => onSaved?.(value as CTMSOperationalSite))
  return <CTMSFormShell methods={state.methods} title={state.action} description="Site readiness is operational CTMS data. The EDC Site identity and clinical site configuration remain authoritative elsewhere." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update site profile' : 'Create site profile'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Site" id={siteId} note="The canonical EDC Site ID scopes this request and cannot be replaced by this form." />
    {studyId ? <FormIdentity label="Study" id={studyId} note="The study reference is used only for CTMS scope." /> : null}
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="monitoringReadiness" label="Monitoring readiness" /><CTMSFormField control={state.methods.control} name="responsibleRole" label="Responsible operational role" /><CTMSFormField control={state.methods.control} name="plannedActivationDate" label="Planned activation date" type="date" />{choices.length && !isUpdate ? <CTMSFormField control={state.methods.control} name="status" label="Operational site status" type="select" options={choices} /> : null}</div>
  </CTMSFormShell>
}

const activationSchema = z.object({ studyId: optionalOwnedStringSchema({ label: 'Study ID', maxLength: 200 }), actionType: z.string().trim().min(1, 'Action type is required').max(100), responsibleRole: optionalOwnedStringSchema({ label: 'Responsible role', maxLength: 150 }), responsibleUserId: optionalOwnedStringSchema({ label: 'Responsible user ID', maxLength: 200 }), plannedDate: z.preprocess((value) => value === '' ? undefined : value, ownedDateSchema.optional()), completionCriteria: optionalOwnedStringSchema({ label: 'Completion criteria' }), status: optionalOwnedStringSchema({ label: 'Activation status', maxLength: 100 }) })
type ActivationFormValues = { studyId?: string; actionType: string; responsibleRole?: string; responsibleUserId?: string; plannedDate?: string; completionCriteria?: string; status?: string }

export interface ActivationActionFormProps {
  siteId: string
  studyId?: string
  initialValue?: CTMSActivationAction
  statusOptions?: readonly (CTMSStatusOption | string)[]
  onSaved?: (value: CTMSActivationAction) => void
  onCancel?: () => void
}

export function ActivationActionForm({ siteId, studyId, initialValue, statusOptions, onSaved, onCancel }: ActivationActionFormProps) {
  const isUpdate = Boolean(initialValue?.id)
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<ActivationFormValues>({ studyId: studyId ?? initialValue?.study_id ?? '', actionType: initialValue?.action_type ?? '', responsibleRole: initialValue?.responsible_role ?? '', responsibleUserId: initialValue?.responsible_user_id ?? '', plannedDate: initialValue?.planned_date?.slice(0, 10) ?? '', completionCriteria: initialValue?.completion_criteria ?? '', status: initialValue?.status ?? '' }, activationSchema, isUpdate ? 'Update activation action' : 'Create activation action', 'activation', { studyId, siteId }, async (values) => {
    const payload = { action_type: values.actionType.trim(), responsible_role: optionalText(values.responsibleRole), responsible_user_id: optionalText(values.responsibleUserId), planned_date: values.plannedDate ? toUtcDate(values.plannedDate) : undefined, completion_criteria: optionalText(values.completionCriteria), ...(values.studyId ? { study_id: values.studyId } : {}), ...(values.status ? { status: values.status } : {}) }
    return isUpdate ? ctmsApi.updateActivationAction(initialValue!.id, payload) : ctmsApi.createActivationAction(siteId, payload)
  }, (value) => onSaved?.(value as CTMSActivationAction))
  return <CTMSFormShell methods={state.methods} title={state.action} description="Activation actions are CTMS readiness work. They cannot activate, complete, reschedule, or modify an EDC clinical Visit_Instance." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update action' : 'Create action'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Site" id={siteId} note="This canonical EDC Site reference scopes the operational action." />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="actionType" label="Action type" required /><CTMSFormField control={state.methods.control} name="responsibleRole" label="Responsible operational role" /><CTMSFormField control={state.methods.control} name="responsibleUserId" label="Responsible user ID" /><CTMSFormField control={state.methods.control} name="plannedDate" label="Planned date" type="date" /></div>
    <CTMSFormField control={state.methods.control} name="completionCriteria" label="Completion criteria" type="textarea" />
    {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Activation status" type="select" options={choices} /> : null}
  </CTMSFormShell>
}

const targetTypeOptions: CTMSSelectOption[] = [{ value: 'Recruitment', label: 'Recruitment' }, { value: 'Screening', label: 'Screening' }, { value: 'Enrollment', label: 'Enrollment' }]
const targetSchema = z.object({ siteId: optionalOwnedStringSchema({ label: 'Site ID', maxLength: 200 }), targetType: z.enum(['Recruitment', 'Screening', 'Enrollment'], { error: 'Target type is required' }), targetQuantity: ownedQuantitySchema({ label: 'Target quantity', min: 1, integer: true }), planningPeriodStart: ownedDateSchema, planningPeriodEnd: ownedDateSchema, ownerId: optionalOwnedStringSchema({ label: 'Owner ID', maxLength: 200 }), status: optionalOwnedStringSchema({ label: 'Target status', maxLength: 100 }) })
type TargetFormValues = { siteId?: string; targetType: 'Recruitment' | 'Screening' | 'Enrollment'; targetQuantity: string | number; planningPeriodStart: string; planningPeriodEnd: string; ownerId?: string; status?: string }

export interface EnrollmentTargetFormProps {
  studyId: string
  siteId?: string
  initialValue?: CTMSEnrollmentTarget
  statusOptions?: readonly (CTMSStatusOption | string)[]
  onSaved?: (value: CTMSEnrollmentTarget) => void
  onCancel?: () => void
}

export function EnrollmentTargetForm({ studyId, siteId, initialValue, statusOptions, onSaved, onCancel }: EnrollmentTargetFormProps) {
  const isUpdate = Boolean(initialValue?.id)
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<TargetFormValues>({ siteId: initialValue?.site_id ?? siteId ?? '', targetType: (initialValue?.target_type as TargetFormValues['targetType']) ?? 'Enrollment', targetQuantity: initialValue?.target_quantity ?? '', planningPeriodStart: initialValue?.planning_period_start?.slice(0, 10) ?? '', planningPeriodEnd: initialValue?.planning_period_end?.slice(0, 10) ?? '', ownerId: initialValue?.owner_id ?? '', status: initialValue?.status ?? '' }, targetSchema, isUpdate ? 'Update enrollment target' : 'Create enrollment target', 'enrollment-target', { studyId, siteId }, async (values) => {
    const parsed = targetSchema.parse(values)
    const payload = { study_id: studyId, ...(values.siteId ? { site_id: values.siteId } : {}), target_type: parsed.targetType, target_quantity: parsed.targetQuantity, planning_period_start: toUtcDate(parsed.planningPeriodStart), planning_period_end: toUtcDate(parsed.planningPeriodEnd), owner_id: optionalText(values.ownerId), ...(values.status ? { status: values.status } : {}) }
    return isUpdate ? ctmsApi.updateTarget(initialValue!.id, { target_quantity: payload.target_quantity, planning_period_start: payload.planning_period_start, planning_period_end: payload.planning_period_end, owner_id: payload.owner_id, ...(payload.status ? { status: payload.status } : {}) }) : ctmsApi.createTarget(studyId, payload)
  }, (value) => onSaved?.(value as CTMSEnrollmentTarget))
  return <CTMSFormShell methods={state.methods} title={state.action} description="Enrollment targets are operational quantities only; this form never creates subjects or changes clinical enrollment data." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update target' : 'Create target'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Study" id={studyId} note="The canonical EDC Study scopes the operational target." />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="siteId" label="Canonical Site ID (optional)" description="A reference only; it does not replace the EDC Site identity." /><CTMSFormField control={state.methods.control} name="targetType" label="Target type" type="select" options={targetTypeOptions} required /><CTMSFormField control={state.methods.control} name="targetQuantity" label="Target quantity" type="number" required /><CTMSFormField control={state.methods.control} name="ownerId" label="Operational owner ID" /><CTMSFormField control={state.methods.control} name="planningPeriodStart" label="Planning period start" type="date" required /><CTMSFormField control={state.methods.control} name="planningPeriodEnd" label="Planning period end" type="date" required /></div>
    {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Target status" type="select" options={choices} /> : null}
  </CTMSFormShell>
}

const milestoneSchema = z.object({ siteId: optionalOwnedStringSchema({ label: 'Site ID', maxLength: 200 }), subjectId: z.string().trim().min(1, 'Canonical Subject ID is required').max(200), approvedPseudonym: optionalOwnedStringSchema({ label: 'Approved operational pseudonym', maxLength: 255 }), approvedReference: optionalOwnedStringSchema({ label: 'Approved operational reference', maxLength: 255 }), milestoneType: z.string().trim().min(1, 'Milestone type is required').max(100), milestoneDate: ownedDateSchema, status: z.string().trim().min(1, 'Select a server-provided status') })
type MilestoneFormValues = { siteId?: string; subjectId: string; approvedPseudonym?: string; approvedReference?: string; milestoneType: string; milestoneDate: string; status: string }

export interface OperationalMilestoneFormProps {
  studyId: string
  subjectId: string
  siteId?: string
  statusOptions: readonly (CTMSStatusOption | string)[]
  initialValue?: CTMSOperationalMilestone
  onSaved?: (value: CTMSOperationalMilestone) => void
  onCancel?: () => void
}

export function OperationalMilestoneForm({ studyId, subjectId, siteId, statusOptions, initialValue, onSaved, onCancel }: OperationalMilestoneFormProps) {
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<MilestoneFormValues>({ siteId: initialValue?.site_id ?? siteId ?? '', subjectId: initialValue?.subject_id ?? subjectId, approvedPseudonym: initialValue?.approved_pseudonym ?? '', approvedReference: initialValue?.approved_reference ?? '', milestoneType: initialValue?.milestone_type ?? '', milestoneDate: initialValue?.milestone_date?.slice(0, 10) ?? '', status: initialValue?.status ?? '' }, milestoneSchema, 'Record operational milestone', 'milestone', { studyId, siteId }, async (values) => {
    const parsed = milestoneSchema.parse(values)
    return ctmsApi.createMilestone(subjectId, { study_id: studyId, site_id: optionalText(values.siteId), approved_pseudonym: optionalText(values.approvedPseudonym), approved_reference: optionalText(values.approvedReference), milestone_type: parsed.milestoneType, milestone_date: toUtcDate(parsed.milestoneDate), status: parsed.status })
  }, (value) => onSaved?.(value as CTMSOperationalMilestone))
  const noStatusOptions = choices.length === 0
  return <CTMSFormShell methods={state.methods} title={state.action} description="Milestones are CTMS operational records linked to a canonical EDC Subject. Approved references are not replacements for the clinical identity and no clinical values are accepted." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel="Record milestone" submitDisabled={noStatusOptions} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Study" id={studyId} note="The canonical EDC Study scopes this operational record." />
    <FormIdentity label="Subject" id={subjectId} note="The EDC Subject ID is a read-only reference. CTMS cannot replace or modify the clinical subject." />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="siteId" label="Canonical Site ID (optional)" /><CTMSFormField control={state.methods.control} name="milestoneType" label="Milestone type" required /><CTMSFormField control={state.methods.control} name="milestoneDate" label="Milestone date" type="date" required /><CTMSFormField control={state.methods.control} name="approvedPseudonym" label="Approved operational pseudonym" /><CTMSFormField control={state.methods.control} name="approvedReference" label="Approved operational reference" /></div>
    {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Operational subject status" type="select" options={choices} required /> : <p role="status" className="text-sm text-muted-foreground">Status choices are not available from the server yet. The milestone cannot be submitted until they are returned.</p>}
  </CTMSFormShell>
}
