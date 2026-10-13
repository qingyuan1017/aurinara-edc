import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { useForm, type DefaultValues, type FieldValues } from 'react-hook-form'
import { z } from 'zod'
import {
  ctmsApi,
  useCTMSProjectMilestones,
  useCTMSProjectOptions,
  useCTMSReferenceValues,
  type CTMSActivationAction,
  type CTMSEnrollmentTarget,
  type CTMSOperationalMilestone,
  type CTMSOperationalSite,
  type CTMSOperationalStudy,
  type CTMSProjectMilestone,
  type CTMSProjectScopeLevel,
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
  ownedStringSchema,
} from './schemas'

const optionalText = (value: string | undefined) => value?.trim() ? value.trim() : undefined
const toUtcDate = (value: string) => `${value}T00:00:00.000Z`

function statusChoices(options: readonly (CTMSStatusOption | string)[] | undefined): CTMSSelectOption[] {
  return (options ?? []).map((option) => typeof option === 'string' ? { value: option, label: option } : { value: option.value, label: option.label ?? option.value })
}

function referenceChoices(
  items: readonly { category: string; code: string; label: string }[] | undefined,
  category: string,
  current?: string | null,
): CTMSSelectOption[] {
  const options = (items ?? []).filter((item) => item.category === category).map((item) => ({ value: item.code, label: item.label }))
  if (current && !options.some((option) => option.value === current)) options.unshift({ value: current, label: `${current} (legacy value)` })
  return options
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
  phase: ownedStringSchema({ label: 'Study phase', minLength: 1, maxLength: 50 }),
  studyType: ownedStringSchema({ label: 'Study type', minLength: 1, maxLength: 100 }),
  mainPurpose: ownedStringSchema({ label: 'Main purpose', minLength: 1, maxLength: 100 }),
  therapeuticArea: optionalOwnedStringSchema({ label: 'Therapeutic area', maxLength: 255 }),
  program: optionalOwnedStringSchema({ label: 'Program', maxLength: 255 }),
  indication: optionalOwnedStringSchema({ label: 'Indication', maxLength: 255 }),
  studyDescription: optionalOwnedStringSchema({ label: 'Study description' }),
  investigationalProduct: optionalOwnedStringSchema({ label: 'Investigational product', maxLength: 500 }),
  blindMethod: ownedStringSchema({ label: 'Blind method', minLength: 1, maxLength: 100 }),
  randomized: z.enum(['true', 'false'], { error: 'Randomized is required' }),
  expectedSubjectCount: ownedQuantitySchema({ label: 'Expected number of subjects', min: 0, integer: true }),
  language: ownedStringSchema({ label: 'Language', minLength: 1, maxLength: 50 }),
  expectedSiteCount: ownedQuantitySchema({ label: 'Expected number of sites', min: 0, integer: true }),
  constructionPeriod: ownedStringSchema({ label: 'Construction period', minLength: 1, maxLength: 100 }),
  plannedStartDate: ownedDateSchema,
  plannedEndDate: ownedDateSchema,
  actualStartDate: optionalOwnedStringSchema({ label: 'Actual start date' }),
  actualEndDate: optionalOwnedStringSchema({ label: 'Actual end date' }),
  studyCurrency: ownedStringSchema({ label: 'Study currency', minLength: 3, maxLength: 3 }),
  exchangeDate: optionalOwnedStringSchema({ label: 'Exchange date' }),
  queryExpectedDays: z.preprocess((value) => value === '' ? undefined : value, ownedQuantitySchema({ label: 'Query expected days', min: 0, integer: true }).optional()),
  operationalOwnerId: optionalOwnedStringSchema({ label: 'Operational owner ID', maxLength: 200 }),
  status: optionalOwnedStringSchema({ label: 'Operational status', maxLength: 100 }),
}).refine((value) => value.plannedEndDate >= value.plannedStartDate, { path: ['plannedEndDate'], message: 'Planned end date must be on or after planned start date' })
type StudyFormValues = {
  phase: string
  studyType: string
  mainPurpose: string
  therapeuticArea?: string
  program?: string
  indication?: string
  studyDescription?: string
  investigationalProduct?: string
  blindMethod: string
  randomized: 'true' | 'false'
  expectedSubjectCount: number
  language: string
  expectedSiteCount: number
  constructionPeriod: string
  plannedStartDate: string
  plannedEndDate: string
  actualStartDate?: string
  actualEndDate?: string
  studyCurrency: string
  exchangeDate?: string
  queryExpectedDays?: number
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
  const references = useCTMSReferenceValues()
  const therapeuticAreaChoices = referenceChoices(references.data?.items, 'therapeutic_area', initialValue?.therapeutic_area)
  const indicationChoices = referenceChoices(references.data?.items, 'indication', initialValue?.indication)
  const state = useOperationalForm<StudyFormValues>(
    {
      phase: initialValue?.phase ?? '', studyType: initialValue?.study_type ?? '', mainPurpose: initialValue?.main_purpose ?? '', therapeuticArea: initialValue?.therapeutic_area ?? '', program: initialValue?.program ?? '', indication: initialValue?.indication ?? '', studyDescription: initialValue?.study_description ?? '', investigationalProduct: initialValue?.investigational_product ?? '', blindMethod: initialValue?.blind_method ?? '', randomized: initialValue?.randomized === false ? 'false' : 'true', expectedSubjectCount: initialValue?.expected_subject_count ?? 0, language: initialValue?.language ?? '', expectedSiteCount: initialValue?.expected_site_count ?? 0, constructionPeriod: initialValue?.construction_period ?? '', plannedStartDate: initialValue?.planned_start_date ?? '', plannedEndDate: initialValue?.planned_end_date ?? '', actualStartDate: initialValue?.actual_start_date ?? '', actualEndDate: initialValue?.actual_end_date ?? '', studyCurrency: initialValue?.study_currency ?? '', exchangeDate: initialValue?.exchange_date ?? '', queryExpectedDays: initialValue?.query_expected_days ?? undefined, operationalOwnerId: initialValue?.operational_owner_id ?? '', status: initialValue?.status ?? '',
    },
    studySchema,
    isUpdate ? 'Update operational study profile' : 'Create operational study profile',
    'study-profile',
    { studyId },
    async (values) => {
      const payload = {
        phase: values.phase.trim(), study_type: values.studyType.trim(), main_purpose: values.mainPurpose.trim(), therapeutic_area: optionalText(values.therapeuticArea), program: optionalText(values.program), indication: optionalText(values.indication), study_description: optionalText(values.studyDescription), investigational_product: optionalText(values.investigationalProduct), blind_method: values.blindMethod.trim(), randomized: values.randomized === 'true', expected_subject_count: Number(values.expectedSubjectCount), language: values.language.trim(), expected_site_count: Number(values.expectedSiteCount), construction_period: values.constructionPeriod.trim(), planned_start_date: values.plannedStartDate, planned_end_date: values.plannedEndDate, actual_start_date: optionalText(values.actualStartDate), actual_end_date: optionalText(values.actualEndDate), study_currency: values.studyCurrency.trim().toUpperCase(), exchange_date: optionalText(values.exchangeDate), query_expected_days: values.queryExpectedDays === undefined ? undefined : Number(values.queryExpectedDays), operational_owner_id: optionalText(values.operationalOwnerId),
        ...(values.status && !isUpdate ? { status: values.status } : {}),
      }
      return isUpdate ? ctmsApi.updateStudyProfile(initialValue!.id, payload) : ctmsApi.createStudyProfile(studyId, payload)
    },
    (value) => onSaved?.(value as CTMSOperationalStudy),
  )
  return <CTMSFormShell methods={state.methods} title={state.action} description="Configure CTMS-owned study attributes. Study name and sponsor are synchronized from Aurinara Platform and cannot be edited here." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update profile' : 'Create profile'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Study" id={studyId} note={initialValue ? `Platform study: ${initialValue.study_name ?? 'not supplied'} · Sponsor: ${initialValue.sponsor ?? 'not supplied'}. These values are read-only.` : 'Study name and sponsor will be read from the canonical platform study when this CTMS profile is saved; they cannot be changed here.'} />
    <div className="grid gap-4 sm:grid-cols-2">
      <CTMSFormField control={state.methods.control} name="phase" label="Study phase" required />
      <CTMSFormField control={state.methods.control} name="studyType" label="Study type" required />
      <CTMSFormField control={state.methods.control} name="mainPurpose" label="Main purpose" required />
      <CTMSFormField control={state.methods.control} name="therapeuticArea" label="Therapeutic area" type="select" options={therapeuticAreaChoices} />
      <CTMSFormField control={state.methods.control} name="program" label="Program" />
      <CTMSFormField control={state.methods.control} name="indication" label="Indication" type="select" options={indicationChoices} />
      <CTMSFormField control={state.methods.control} name="studyDescription" label="Study description" type="textarea" className="sm:col-span-2" />
      <CTMSFormField control={state.methods.control} name="investigationalProduct" label="Investigational product" />
      <CTMSFormField control={state.methods.control} name="blindMethod" label="Blind method" required />
      <CTMSFormField control={state.methods.control} name="randomized" label="Randomized" type="select" options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} required />
      <CTMSFormField control={state.methods.control} name="expectedSubjectCount" label="Expected no. of subjects" type="number" required />
      <CTMSFormField control={state.methods.control} name="language" label="Language" required />
      <CTMSFormField control={state.methods.control} name="expectedSiteCount" label="Expected no. of sites" type="number" required />
      <CTMSFormField control={state.methods.control} name="constructionPeriod" label="Construction period" required />
      <CTMSFormField control={state.methods.control} name="plannedStartDate" label="Planned start date" type="date" required />
      <CTMSFormField control={state.methods.control} name="plannedEndDate" label="Planned end date" type="date" required />
      <CTMSFormField control={state.methods.control} name="actualStartDate" label="Actual start date" type="date" />
      <CTMSFormField control={state.methods.control} name="actualEndDate" label="Actual end date" type="date" />
      <CTMSFormField control={state.methods.control} name="studyCurrency" label="Study currency" placeholder="USD" required />
      <CTMSFormField control={state.methods.control} name="exchangeDate" label="Exchange date" type="date" />
      <CTMSFormField control={state.methods.control} name="queryExpectedDays" label="Query expected days" type="number" />
      <CTMSFormField control={state.methods.control} name="operationalOwnerId" label="Operational owner ID" description="A CTMS owner reference, not a clinical identity." />
      {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Operational status" type="select" options={choices} /> : null}
    </div>
  </CTMSFormShell>
}

const scopeOptions: CTMSSelectOption[] = [{ value: 'study', label: 'Study' }, { value: 'country', label: 'Country' }, { value: 'site', label: 'Site' }]
const planSchema = z.object({ title: z.string().trim().min(1, 'Name is required').max(255), objective: optionalOwnedStringSchema({ label: 'Description' }), milestoneId: optionalOwnedStringSchema({ label: 'Milestone', maxLength: 200 }), scopeLevel: z.enum(['study', 'country', 'site']), countryCode: optionalOwnedStringSchema({ label: 'Country', maxLength: 100 }), siteId: optionalOwnedStringSchema({ label: 'Site', maxLength: 200 }), assigneeRoleId: optionalOwnedStringSchema({ label: 'Assigned role', maxLength: 200 }), assigneeUserId: optionalOwnedStringSchema({ label: 'Assigned user', maxLength: 200 }), startAt: z.preprocess((value) => value === '' ? undefined : value, ownedDateSchema.optional()), dueAt: z.preprocess((value) => value === '' ? undefined : value, ownedDateSchema.optional()), status: optionalOwnedStringSchema({ label: 'Activity status', maxLength: 100 }), reason: optionalOwnedStringSchema({ label: 'Reason', maxLength: 500 }) }).refine((value) => !value.startAt || !value.dueAt || value.dueAt >= value.startAt, { path: ['dueAt'], message: 'Due date must be on or after start date' })
type PlanFormValues = { title: string; objective?: string; milestoneId?: string; scopeLevel: CTMSProjectScopeLevel; countryCode?: string; siteId?: string; assigneeRoleId?: string; assigneeUserId?: string; startAt?: string; dueAt?: string; status?: string; reason?: string }

export interface StudyPlanFormProps {
  studyId: string
  initialValue?: CTMSStudyPlan
  statusOptions?: readonly (CTMSStatusOption | string)[]
  onSaved?: (value: CTMSStudyPlan) => void
  onCancel?: () => void
}

export function StudyPlanForm({ studyId, initialValue, statusOptions, onSaved, onCancel }: StudyPlanFormProps) {
  const isUpdate = Boolean(initialValue?.id)
  const references = useCTMSReferenceValues()
  const options = useCTMSProjectOptions(studyId)
  const milestones = useCTMSProjectMilestones(studyId)
  const configuredStatuses = referenceChoices(references.data?.items, 'project_status', initialValue?.status)
  const choices = statusOptions?.length ? statusChoices(statusOptions) : configuredStatuses.length ? configuredStatuses : statusChoices([{ value: 'DRAFT', label: 'Draft' }, { value: 'ACTIVE', label: 'Active' }, { value: 'BLOCKED', label: 'Blocked' }, { value: 'COMPLETED', label: 'Complete' }])
  const state = useOperationalForm<PlanFormValues>({ title: initialValue?.title ?? '', objective: initialValue?.objective ?? '', milestoneId: initialValue?.milestone_id ?? '', scopeLevel: initialValue?.scope_level ?? 'study', countryCode: initialValue?.country_code ?? '', siteId: initialValue?.site_id ?? '', assigneeRoleId: initialValue?.assignee_role_id ?? '', assigneeUserId: initialValue?.assignee_user_id ?? '', startAt: initialValue?.start_at?.slice(0, 10) ?? '', dueAt: initialValue?.due_at?.slice(0, 10) ?? '', status: initialValue?.status ?? 'DRAFT', reason: '' }, planSchema, isUpdate ? 'Update master activity' : 'Create master activity', 'plan', { studyId }, async (values) => {
    const payload = { title: values.title.trim(), objective: optionalText(values.objective), milestone_id: optionalText(values.milestoneId), scope_level: values.scopeLevel, country_code: values.scopeLevel === 'country' ? optionalText(values.countryCode) : undefined, site_id: values.scopeLevel === 'site' ? optionalText(values.siteId) : undefined, assignee_role_id: optionalText(values.assigneeRoleId), assignee_user_id: optionalText(values.assigneeUserId), start_at: values.startAt ? toUtcDate(values.startAt) : undefined, due_at: values.dueAt ? toUtcDate(values.dueAt) : undefined, ...(values.status ? { status: values.status } : {}) }
    return isUpdate ? ctmsApi.updatePlan(initialValue!.id, { ...payload, reason: values.reason?.trim() || 'Updated from CTMS project management' }) : ctmsApi.createPlan(studyId, payload)
  }, (value) => onSaved?.(value as CTMSStudyPlan))
  useEffect(() => {
    if (isUpdate || !configuredStatuses.length) return
    const current = state.methods.getValues('status')
    if (!configuredStatuses.some((option) => option.value === current)) {
      state.methods.setValue('status', configuredStatuses[0].value)
    }
  }, [configuredStatuses, isUpdate, state.methods])
  const scopeLevel = state.methods.watch('scopeLevel')
  const countryCode = state.methods.watch('countryCode')
  const siteId = state.methods.watch('siteId')
  const milestoneId = state.methods.watch('milestoneId')
  const milestoneOptions = (milestones.data?.items ?? []).filter((milestone) => milestone.scope_level === scopeLevel && (scopeLevel !== 'country' || (milestone.country_code ?? '') === (countryCode ?? '')) && (scopeLevel !== 'site' || (milestone.site_id ?? '') === (siteId ?? ''))).map((milestone) => ({ value: milestone.id, label: milestone.title }))
  useEffect(() => {
    if (milestones.isLoading || !milestoneId) return
    if (!milestoneOptions.some((option) => option.value === milestoneId)) state.methods.setValue('milestoneId', '', { shouldDirty: true })
  }, [milestoneId, milestoneOptions, milestones.isLoading, state.methods])
  return <CTMSFormShell methods={state.methods} title={state.action} description="Master activities behave like Jira work items and must use the same study, country, or site scope as their milestone." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update activity' : 'Create activity'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <CTMSFormField control={state.methods.control} name="title" label="Name" required />
    <CTMSFormField control={state.methods.control} name="objective" label="Description" type="textarea" />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="scopeLevel" label="Level" type="select" options={scopeOptions} required />{scopeLevel === 'country' ? <CTMSFormField control={state.methods.control} name="countryCode" label="Country" type="select" options={[{ value: '', label: 'All countries' }, ...referenceChoices(references.data?.items, 'country', initialValue?.country_code)]} /> : null}{scopeLevel === 'site' ? <CTMSFormField control={state.methods.control} name="siteId" label="Site" type="select" options={[{ value: '', label: 'All sites' }, ...(options.data?.sites ?? []).map((site) => ({ value: site.id, label: site.label }))]} /> : null}<CTMSFormField control={state.methods.control} name="milestoneId" label="Milestone" type="select" options={[{ value: '', label: 'No milestone' }, ...milestoneOptions]} /><CTMSFormField control={state.methods.control} name="assigneeRoleId" label="Assigned role" type="select" options={[{ value: '', label: 'No role' }, ...(options.data?.roles ?? []).map((role) => ({ value: role.id, label: role.label }))]} /><CTMSFormField control={state.methods.control} name="assigneeUserId" label="Assigned user" type="select" options={[{ value: '', label: 'No user' }, ...(options.data?.users ?? []).map((user) => ({ value: user.id, label: user.label }))]} /><CTMSFormField control={state.methods.control} name="startAt" label="Start date" type="date" /><CTMSFormField control={state.methods.control} name="dueAt" label="Due date" type="date" /><CTMSFormField control={state.methods.control} name="status" label="Status" type="select" options={choices} required /></div>
    {isUpdate ? <CTMSFormField control={state.methods.control} name="reason" label="Reason for change" type="textarea" /> : null}
  </CTMSFormShell>
}

const projectMilestoneSchema = z.object({ title: z.string().trim().min(1, 'Name is required').max(255), description: optionalOwnedStringSchema({ label: 'Description' }), milestoneType: z.string().trim().min(1, 'Milestone type is required'), scopeLevel: z.enum(['study', 'country', 'site']), countryCode: optionalOwnedStringSchema({ label: 'Country', maxLength: 100 }), siteId: optionalOwnedStringSchema({ label: 'Site', maxLength: 200 }), plannedAt: z.preprocess((value) => value === '' ? undefined : value, ownedDateSchema.optional()), status: z.string().trim().min(1, 'Status is required'), reason: optionalOwnedStringSchema({ label: 'Reason', maxLength: 500 }) })
type ProjectMilestoneValues = { title: string; description?: string; milestoneType: string; scopeLevel: CTMSProjectScopeLevel; countryCode?: string; siteId?: string; plannedAt?: string; status: string; reason?: string }

export interface ProjectMilestoneFormProps {
  studyId: string
  initialValue?: CTMSProjectMilestone
  onSaved?: (value: CTMSProjectMilestone) => void
  onCancel?: () => void
}

export function ProjectMilestoneForm({ studyId, initialValue, onSaved, onCancel }: ProjectMilestoneFormProps) {
  const references = useCTMSReferenceValues()
  const options = useCTMSProjectOptions(studyId)
  const isUpdate = Boolean(initialValue?.id)
  const state = useOperationalForm<ProjectMilestoneValues>({ title: initialValue?.title ?? '', description: initialValue?.description ?? '', milestoneType: initialValue?.milestone_type ?? '', scopeLevel: initialValue?.scope_level ?? 'study', countryCode: initialValue?.country_code ?? '', siteId: initialValue?.site_id ?? '', plannedAt: initialValue?.planned_at?.slice(0, 10) ?? '', status: initialValue?.status ?? 'Planned', reason: '' }, projectMilestoneSchema, isUpdate ? 'Update project milestone' : 'Create project milestone', 'milestone', { studyId }, async (values) => {
    const payload = { title: values.title.trim(), description: optionalText(values.description), milestone_type: values.milestoneType, scope_level: values.scopeLevel, country_code: values.scopeLevel === 'country' ? optionalText(values.countryCode) : undefined, site_id: values.scopeLevel === 'site' ? optionalText(values.siteId) : undefined, planned_at: values.plannedAt ? toUtcDate(values.plannedAt) : undefined, status: values.status }
    return isUpdate ? ctmsApi.updateProjectMilestone(initialValue!.id, { ...payload, reason: values.reason?.trim() || 'Updated from CTMS project management' }) : ctmsApi.createProjectMilestone(studyId, payload)
  }, (value) => onSaved?.(value as CTMSProjectMilestone))
  const scopeLevel = state.methods.watch('scopeLevel')
  const typeOptions = referenceChoices(references.data?.items, 'milestone_type', initialValue?.milestone_type)
  return <CTMSFormShell methods={state.methods} title={state.action} description="Project milestones group master activities at the study, country, or site level." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update milestone' : 'Create milestone'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <CTMSFormField control={state.methods.control} name="title" label="Name" required />
    <CTMSFormField control={state.methods.control} name="description" label="Description" type="textarea" />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="milestoneType" label="Milestone type" type="select" options={typeOptions} required /><CTMSFormField control={state.methods.control} name="scopeLevel" label="Level" type="select" options={scopeOptions} required />{scopeLevel === 'country' ? <CTMSFormField control={state.methods.control} name="countryCode" label="Country" type="select" options={[{ value: '', label: 'All countries' }, ...referenceChoices(references.data?.items, 'country', initialValue?.country_code)]} /> : null}{scopeLevel === 'site' ? <CTMSFormField control={state.methods.control} name="siteId" label="Site" type="select" options={[{ value: '', label: 'All sites' }, ...(options.data?.sites ?? []).map((site) => ({ value: site.id, label: site.label }))]} /> : null}<CTMSFormField control={state.methods.control} name="plannedAt" label="Target date" type="date" /><CTMSFormField control={state.methods.control} name="status" label="Status" type="select" options={statusChoices(['Planned', 'In Progress', 'Delayed', 'Completed', 'Cancelled'])} required /></div>
    {isUpdate ? <CTMSFormField control={state.methods.control} name="reason" label="Reason for change" type="textarea" /> : null}
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
  return <CTMSFormShell methods={state.methods} title={state.action} description="Site readiness is operational CTMS data. CTMS creates the shared Site identity; EDC remains authoritative for clinical site configuration." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel={isUpdate ? 'Update site profile' : 'Create site profile'} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
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
    <FormIdentity label="Study" id={studyId} note="The platform-managed canonical Study scopes the operational target." />
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="siteId" label="Site ID (optional)" description="Use the ID generated when the Site was created in CTMS." /><CTMSFormField control={state.methods.control} name="targetType" label="Target type" type="select" options={targetTypeOptions} required /><CTMSFormField control={state.methods.control} name="targetQuantity" label="Target quantity" type="number" required /><CTMSFormField control={state.methods.control} name="ownerId" label="Operational owner ID" /><CTMSFormField control={state.methods.control} name="planningPeriodStart" label="Planning period start" type="date" required /><CTMSFormField control={state.methods.control} name="planningPeriodEnd" label="Planning period end" type="date" required /></div>
    {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Target status" type="select" options={choices} /> : null}
  </CTMSFormShell>
}

const milestoneSchema = z.object({ siteId: optionalOwnedStringSchema({ label: 'Site ID', maxLength: 200 }), subjectId: z.string().trim().min(1, 'Canonical Subject ID is required').max(200), approvedPseudonym: optionalOwnedStringSchema({ label: 'Approved operational pseudonym', maxLength: 255 }), approvedReference: optionalOwnedStringSchema({ label: 'Approved operational reference', maxLength: 255 }), milestoneType: z.string().trim().min(1, 'Milestone type is required').max(100), milestoneDate: ownedDateSchema, status: z.string().trim().min(1, 'Select a server-provided status') })
type MilestoneFormValues = { siteId?: string; subjectId: string; approvedPseudonym?: string; approvedReference?: string; milestoneType: string; milestoneDate: string; status: string }

export interface OperationalMilestoneFormProps {
  studyId: string
  subjectId?: string
  siteId?: string
  statusOptions: readonly (CTMSStatusOption | string)[]
  initialValue?: CTMSOperationalMilestone
  onSaved?: (value: CTMSOperationalMilestone) => void
  onCancel?: () => void
}

export function OperationalMilestoneForm({ studyId, subjectId, siteId, statusOptions, initialValue, onSaved, onCancel }: OperationalMilestoneFormProps) {
  const choices = statusChoices(statusOptions)
  const state = useOperationalForm<MilestoneFormValues>({ siteId: initialValue?.site_id ?? siteId ?? '', subjectId: initialValue?.subject_id ?? subjectId ?? '', approvedPseudonym: initialValue?.approved_pseudonym ?? '', approvedReference: initialValue?.approved_reference ?? '', milestoneType: initialValue?.milestone_type ?? '', milestoneDate: initialValue?.milestone_date?.slice(0, 10) ?? '', status: initialValue?.status ?? '' }, milestoneSchema, 'Record operational milestone', 'milestone', { studyId, siteId }, async (values) => {
    const parsed = milestoneSchema.parse(values)
    return ctmsApi.createMilestone(parsed.subjectId, { study_id: studyId, site_id: optionalText(values.siteId), approved_pseudonym: optionalText(values.approvedPseudonym), approved_reference: optionalText(values.approvedReference), milestone_type: parsed.milestoneType, milestone_date: toUtcDate(parsed.milestoneDate), status: parsed.status })
  }, (value) => onSaved?.(value as CTMSOperationalMilestone))
  const noStatusOptions = choices.length === 0
  return <CTMSFormShell methods={state.methods} title={state.action} description="Milestones are CTMS operational records linked to a canonical EDC Subject. Approved references are not replacements for the clinical identity and no clinical values are accepted." onSubmit={(values) => state.mutation.mutate(values)} onCancel={onCancel} submitLabel="Record milestone" submitDisabled={noStatusOptions} formMessage={state.formMessage} mutation={{ status: state.mutation.status, action: state.action, data: state.mutation.data, error: state.mutation.error }}>
    <FormIdentity label="Study" id={studyId} note="The platform-managed canonical Study scopes this operational record." />
    {subjectId ? <FormIdentity label="Subject" id={subjectId} note="The EDC Subject ID is a read-only reference. CTMS cannot replace or modify the clinical subject." /> : <CTMSFormField control={state.methods.control} name="subjectId" label="Canonical Subject ID" description="Enter the existing EDC Subject ID to link this operational record." required />}
    <div className="grid gap-4 sm:grid-cols-2"><CTMSFormField control={state.methods.control} name="siteId" label="Site ID (optional)" description="Use the ID generated when the Site was created in CTMS." /><CTMSFormField control={state.methods.control} name="milestoneType" label="Milestone type" required /><CTMSFormField control={state.methods.control} name="milestoneDate" label="Milestone date" type="date" required /><CTMSFormField control={state.methods.control} name="approvedPseudonym" label="Approved operational pseudonym" /><CTMSFormField control={state.methods.control} name="approvedReference" label="Approved operational reference" /></div>
    {choices.length ? <CTMSFormField control={state.methods.control} name="status" label="Operational subject status" type="select" options={choices} required /> : <p role="status" className="text-sm text-muted-foreground">Status choices are not available from the server yet. The milestone cannot be submitted until they are returned.</p>}
  </CTMSFormShell>
}
