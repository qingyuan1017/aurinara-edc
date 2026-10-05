import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useForm,
  useController,
  type Control,
  type FieldValues,
  type Path,
  type Resolver,
  type SubmitHandler,
  type UseFormReturn,
} from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  pvApi,
  pvKeys,
  type PVAdverseEventRecord,
  type PVCaseNarrative,
  type PVSafetyCase,
  type PVSeriousnessAssessment,
} from '../api'
import {
  SERIOUSNESS_CRITERIA,
  adverseEventSchema,
  caseIntakeSchema,
  narrativeRevisionSchema,
  narrativeSchema,
  seriousnessSchema,
  type AdverseEventValues,
  type CaseIntakeValues,
  type NarrativeRevisionValues,
  type NarrativeValues,
  type SeriousnessValues,
} from './schemas'

export interface PVFormCallbacks<T> {
  onSaved?: (value: T) => void
  onCancel?: () => void
  /** Closed cases render controls disabled (Requirement 19.4). */
  disabled?: boolean
}

function fieldId(name: string): string {
  return `pv-field-${name.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

/** A minimal RHF-controlled text/textarea/date field for PV forms. */
function PVField<T extends FieldValues>({
  control,
  name,
  label,
  type = 'text',
  disabled,
  required,
  placeholder,
}: {
  control: Control<T>
  name: Path<T>
  label: string
  type?: 'text' | 'date' | 'textarea'
  disabled?: boolean
  required?: boolean
  placeholder?: string
}) {
  const { field, fieldState } = useController({ control, name })
  const id = fieldId(String(name))
  const errorId = fieldState.error ? `${id}-error` : undefined
  const invalid = Boolean(fieldState.error)
  const value = typeof field.value === 'string' ? field.value : ''
  const commonProps = {
    id,
    name: field.name,
    ref: field.ref,
    disabled,
    placeholder,
    'aria-invalid': invalid,
    'aria-describedby': errorId,
    'data-pv-form-control': true,
    value,
    onBlur: field.onBlur,
  }
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </Label>
      {type === 'textarea' ? (
        <Textarea
          {...commonProps}
          rows={5}
          onChange={(event) => field.onChange(event.target.value)}
        />
      ) : (
        <Input
          {...commonProps}
          type={type}
          onChange={(event) => field.onChange(event.target.value)}
        />
      )}
      {fieldState.error?.message ? (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {fieldState.error.message}
        </p>
      ) : null}
    </div>
  )
}

function FormShell<T extends FieldValues>({
  title,
  description,
  onSubmit,
  onCancel,
  submitLabel = 'Save',
  submitDisabled,
  error,
  children,
  methods,
}: {
  title: string
  description?: string
  onSubmit: SubmitHandler<T>
  onCancel?: () => void
  submitLabel?: string
  submitDisabled?: boolean
  error?: unknown
  children: React.ReactNode
  methods: UseFormReturn<T>
}) {
  return (
    <form
      onSubmit={methods.handleSubmit(onSubmit)}
      noValidate
      className="space-y-4 rounded-lg border bg-background p-4"
      aria-label={title}
    >
      <div>
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {children}
      {error ? (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{getPVFormError(error)}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex justify-end gap-2 border-t pt-3">
        {onCancel ? (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
        <Button type="submit" disabled={submitDisabled}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}

function getPVFormError(error: unknown): string {
  if (error && typeof error === 'object') {
    const response = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } }).response
    const message = response?.data?.error?.message ?? response?.data?.detail
    if (typeof message === 'string' && message) return message
    if ('message' in error && typeof (error as { message?: unknown }).message === 'string') {
      return (error as { message: string }).message
    }
  }
  return 'The safety operation could not be completed. The server remains authoritative.'
}

/** Safety case intake bound to a study (and optional site) scope. */
export function CaseIntakeForm({
  studyId,
  onSaved,
  onCancel,
  disabled,
}: PVFormCallbacks<PVSafetyCase> & { studyId: string }) {
  const client = useQueryClient()
  const methods = useForm<CaseIntakeValues>({
    resolver: zodResolver(caseIntakeSchema) as Resolver<CaseIntakeValues>,
    defaultValues: { subject_reference: '', case_type: '', site_id: '' },
  })
  const { control, reset } = methods
  const mutation = useMutation({
    mutationFn: (values: CaseIntakeValues) =>
      pvApi.createCase(studyId, {
        study_id: studyId,
        subject_reference: values.subject_reference,
        case_type: values.case_type,
        site_id: values.site_id || null,
      }),
    onSuccess: (created) => {
      void client.invalidateQueries({ queryKey: pvKeys.cases(studyId) })
      reset()
      onSaved?.(created)
    },
  })
  return (
    <FormShell<CaseIntakeValues>
      title="New safety case"
      description="References the canonical study and EDC subject; PV never mutates EDC identity."
      methods={methods}
      onSubmit={(values) => mutation.mutate(values)}
      onCancel={onCancel}
      submitLabel="Create case"
      submitDisabled={disabled || mutation.isPending}
      error={mutation.error}
    >
      <PVField control={control} name="subject_reference" label="Subject reference" required disabled={disabled} />
      <PVField control={control} name="case_type" label="Case type" required disabled={disabled} />
      <PVField control={control} name="site_id" label="Site (optional)" disabled={disabled} />
    </FormShell>
  )
}

/** Adverse-event capture under an existing safety case. */
export function AdverseEventForm({
  caseId,
  onSaved,
  onCancel,
  disabled,
}: PVFormCallbacks<PVAdverseEventRecord> & { caseId: string }) {
  const client = useQueryClient()
  const methods = useForm<AdverseEventValues>({
    resolver: zodResolver(adverseEventSchema) as Resolver<AdverseEventValues>,
    defaultValues: { verbatim_term: '', onset_date: '', outcome: '', resolution_date: '' },
  })
  const { control, reset } = methods
  const mutation = useMutation({
    mutationFn: (values: AdverseEventValues) =>
      pvApi.createAdverseEvent(caseId, {
        verbatim_term: values.verbatim_term,
        onset_date: values.onset_date,
        outcome: values.outcome,
        resolution_date: values.resolution_date || null,
      }),
    onSuccess: (created) => {
      void client.invalidateQueries({ queryKey: pvKeys.adverseEvents(caseId) })
      reset()
      onSaved?.(created)
    },
  })
  return (
    <FormShell<AdverseEventValues>
      title="Capture adverse event"
      methods={methods}
      onSubmit={(values) => mutation.mutate(values)}
      onCancel={onCancel}
      submitLabel="Save adverse event"
      submitDisabled={disabled || mutation.isPending}
      error={mutation.error}
    >
      <PVField control={control} name="verbatim_term" label="Verbatim term" required disabled={disabled} />
      <PVField control={control} name="onset_date" label="Onset date" type="date" required disabled={disabled} />
      <PVField control={control} name="outcome" label="Outcome" required disabled={disabled} />
      <PVField control={control} name="resolution_date" label="Resolution date (optional)" type="date" disabled={disabled} />
    </FormShell>
  )
}

/** Seriousness assessment; a serious determination requires ≥1 criterion. */
export function SeriousnessForm({
  aeId,
  caseId,
  onSaved,
  onCancel,
  disabled,
}: PVFormCallbacks<PVSeriousnessAssessment> & { aeId: string; caseId: string }) {
  const client = useQueryClient()
  const methods = useForm<SeriousnessValues>({
    resolver: zodResolver(seriousnessSchema) as Resolver<SeriousnessValues>,
    defaultValues: { serious: false, criteria: [] },
  })
  const { watch, setValue, formState, reset } = methods
  const serious = watch('serious')
  const criteria = watch('criteria') ?? []
  const mutation = useMutation({
    mutationFn: (values: SeriousnessValues) =>
      pvApi.recordSeriousness(aeId, { serious: values.serious, criteria: values.criteria }),
    onSuccess: (created) => {
      void client.invalidateQueries({ queryKey: pvKeys.adverseEvents(caseId) })
      reset()
      onSaved?.(created)
    },
  })
  const toggleCriterion = (value: (typeof SERIOUSNESS_CRITERIA)[number], checked: boolean) => {
    const next = checked ? [...criteria, value] : criteria.filter((item) => item !== value)
    setValue('criteria', next, { shouldValidate: true })
  }
  return (
    <FormShell<SeriousnessValues>
      title="Seriousness assessment"
      methods={methods}
      onSubmit={(values) => mutation.mutate(values)}
      onCancel={onCancel}
      submitLabel="Save assessment"
      submitDisabled={disabled || mutation.isPending}
      error={mutation.error}
    >
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={serious}
          disabled={disabled}
          data-pv-form-control
          onChange={(event) => setValue('serious', event.target.checked, { shouldValidate: true })}
          aria-label="Serious"
        />
        Serious
      </label>
      <fieldset className="space-y-2" disabled={disabled || !serious}>
        <legend className="text-sm font-medium text-foreground">Seriousness criteria</legend>
        {SERIOUSNESS_CRITERIA.map((criterion) => (
          <label key={criterion} className="flex items-center gap-2 text-sm capitalize">
            <Checkbox
              checked={criteria.includes(criterion)}
              disabled={disabled || !serious}
              onChange={(event) => toggleCriterion(criterion, event.target.checked)}
              aria-label={criterion}
            />
            {criterion}
          </label>
        ))}
        {formState.errors.criteria?.message ? (
          <p role="alert" className="text-xs text-destructive">
            {formState.errors.criteria.message}
          </p>
        ) : null}
      </fieldset>
    </FormShell>
  )
}

/** Author a new case narrative (≤ 20,000 chars). */
export function NarrativeForm({
  caseId,
  onSaved,
  onCancel,
  disabled,
}: PVFormCallbacks<PVCaseNarrative> & { caseId: string }) {
  const client = useQueryClient()
  const methods = useForm<NarrativeValues>({
    resolver: zodResolver(narrativeSchema) as Resolver<NarrativeValues>,
    defaultValues: { text: '' },
  })
  const { control, reset } = methods
  const mutation = useMutation({
    mutationFn: (values: NarrativeValues) => pvApi.createNarrative(caseId, { text: values.text }),
    onSuccess: (created) => {
      void client.invalidateQueries({ queryKey: pvKeys.narratives(caseId) })
      reset()
      onSaved?.(created)
    },
  })
  return (
    <FormShell<NarrativeValues>
      title="New case narrative"
      methods={methods}
      onSubmit={(values) => mutation.mutate(values)}
      onCancel={onCancel}
      submitLabel="Save narrative"
      submitDisabled={disabled || mutation.isPending}
      error={mutation.error}
    >
      <PVField control={control} name="text" label="Narrative" type="textarea" required disabled={disabled} />
    </FormShell>
  )
}

/**
 * Revise a narrative. Editing submitted safety data requires a non-empty
 * Reason_For_Change (≤ 4,000 chars) before any request is sent (19.3).
 */
export function NarrativeRevisionForm({
  caseId,
  narrative,
  onSaved,
  onCancel,
  disabled,
}: PVFormCallbacks<PVCaseNarrative> & { caseId: string; narrative: PVCaseNarrative }) {
  const client = useQueryClient()
  const methods = useForm<NarrativeRevisionValues>({
    resolver: zodResolver(narrativeRevisionSchema) as Resolver<NarrativeRevisionValues>,
    defaultValues: { text: narrative.text, reason: '' },
  })
  const { control, reset } = methods
  const mutation = useMutation({
    mutationFn: (values: NarrativeRevisionValues) =>
      pvApi.reviseNarrative(narrative.id, { text: values.text, reason: values.reason }),
    onSuccess: (updated) => {
      void client.invalidateQueries({ queryKey: pvKeys.narratives(caseId) })
      void client.invalidateQueries({ queryKey: pvKeys.narrativeVersions(narrative.id) })
      reset({ text: updated.text, reason: '' })
      onSaved?.(updated)
    },
  })
  return (
    <FormShell<NarrativeRevisionValues>
      title="Revise narrative"
      description="A reason for change is required before the revision is sent to the server."
      methods={methods}
      onSubmit={(values) => mutation.mutate(values)}
      onCancel={onCancel}
      submitLabel="Save revision"
      submitDisabled={disabled || mutation.isPending}
      error={mutation.error}
    >
      <PVField control={control} name="text" label="Narrative" type="textarea" required disabled={disabled} />
      <PVField control={control} name="reason" label="Reason for change" type="textarea" required disabled={disabled} />
    </FormShell>
  )
}
