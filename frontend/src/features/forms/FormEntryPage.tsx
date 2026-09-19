import * as React from 'react'
import { useForm, FormProvider } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageContainer, PageHeader, StatusBadge, OwnershipBadge, LoadingState, ErrorState, MutationFeedback } from '@/components/patterns'
import { FormField, type FieldDefinition } from './components/FormField'
import { ReasonForChangeDialog } from './components/ReasonForChangeDialog'
import { AuditPanel } from './components/AuditPanel'
import { LockControls } from './components/LockControls'
import { FileUpload } from './components/FileUpload'
import { SignatureDialog } from '@/features/signatures'

interface FormSection { id: string; title: string; order: number; fields: FieldDefinition[] }
type FormInstanceStatus = string
interface FormInstanceData { id: string; form_definition_id: string; form_name: string; subject_id: string; subject_number: string; visit_name: string; status: FormInstanceStatus; is_frozen: boolean; is_locked: boolean; sections: FormSection[]; data: Record<string, unknown>; validation_errors?: Record<string, string> }

/** Builds the existing dynamic Zod schema without changing clinical validation rules. */
function buildZodSchema(sections: FormSection[]) {
  const shape: Record<string, z.ZodTypeAny> = {}
  for (const section of sections) {
    for (const field of section.fields) {
      let fieldSchema: z.ZodTypeAny
      switch (field.control_type) {
        case 'integer':
        case 'decimal':
          fieldSchema = field.is_required ? z.number({ error: `${field.label} must be a number` }) : z.union([z.number(), z.nan()]).optional()
          break
        case 'boolean': fieldSchema = z.boolean().optional(); break
        case 'checkbox': fieldSchema = field.is_required ? z.array(z.string()).min(1, `${field.label} is required`) : z.array(z.string()).optional(); break
        default: fieldSchema = field.is_required ? z.string().min(1, `${field.label} is required`) : z.string().optional()
      }
      shape[field.id] = fieldSchema
    }
  }
  return z.object(shape)
}

interface FormEntryPageProps { formInstanceId: string }

/** Main eCRF data-entry surface. Presentation is shared; clinical behavior stays local and authoritative. */
export function FormEntryPage({ formInstanceId }: FormEntryPageProps) {
  const [formInstance, setFormInstance] = React.useState<FormInstanceData | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [fetchError, setFetchError] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)
  const [toast, setToast] = React.useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const [serverErrors, setServerErrors] = React.useState<Record<string, string>>({})
  const [rfcOpen, setRfcOpen] = React.useState(false)
  const [rfcFieldId, setRfcFieldId] = React.useState<string | null>(null)
  const [pendingChange, setPendingChange] = React.useState<{ fieldId: string; value: unknown } | null>(null)
  const [auditPanelOpen, setAuditPanelOpen] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFetchError('')
    api.get<FormInstanceData>(`/form-instances/${formInstanceId}`)
      .then(({ data }) => { if (!cancelled) { setFormInstance(data); if (data.validation_errors) setServerErrors(data.validation_errors) } })
      .catch(() => { if (!cancelled) setFetchError('Failed to load form data.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [formInstanceId])

  const schema = React.useMemo(() => (formInstance ? buildZodSchema(formInstance.sections) : z.object({})), [formInstance])
  const methods = useForm<Record<string, unknown>>({ resolver: zodResolver(schema) as never, defaultValues: formInstance?.data ?? {}, values: formInstance?.data as Record<string, unknown> | undefined, mode: 'onBlur' })
  const normalizedStatus = formInstance?.status.toLowerCase().replaceAll(' ', '_')
  const isSubmitted = normalizedStatus === 'submitted' || normalizedStatus === 'reviewed'
  const isDisabled = formInstance?.is_frozen || formInstance?.is_locked || false
  const fieldLabelMap = React.useMemo(() => {
    const map: Record<string, string> = {}
    formInstance?.sections.forEach((section) => section.fields.forEach((field) => { map[field.id] = field.label }))
    return map
  }, [formInstance])

  React.useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(timer)
  }, [toast])

  const handleFieldFocus = (fieldId: string) => {
    if (isSubmitted && !isDisabled) setRfcFieldId(fieldId)
  }

  const handleSave = async () => {
    const values = methods.getValues()
    setSaving(true); setServerErrors({})
    try { await api.patch(`/form-instances/${formInstanceId}/data`, { values }); setToast({ type: 'success', message: 'Form saved successfully.' }) }
    catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { errors?: Record<string, string> } } }
      if (axiosErr.response?.data?.errors) setServerErrors(axiosErr.response.data.errors)
      setToast({ type: 'error', message: 'Failed to save form.' })
    } finally { setSaving(false) }
  }

  const handleSubmit = async () => {
    const valid = await methods.trigger()
    if (!valid) { setToast({ type: 'error', message: 'Please fix validation errors before submitting.' }); return }
    const values = methods.getValues()
    setSubmitting(true); setServerErrors({})
    try {
      await api.patch(`/form-instances/${formInstanceId}/data`, { values })
      const { data } = await api.post<FormInstanceData>(`/form-instances/${formInstanceId}/submit`)
      setFormInstance(data); setToast({ type: 'success', message: 'Form submitted successfully.' })
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { errors?: Record<string, string>; detail?: string } } }
      if (axiosErr.response?.data?.errors) { setServerErrors(axiosErr.response.data.errors); setToast({ type: 'error', message: 'Validation errors found. Please review.' }) }
      else setToast({ type: 'error', message: axiosErr.response?.data?.detail ?? 'Failed to submit form.' })
    } finally { setSubmitting(false) }
  }

  const handleRfcConfirm = async (reason: string) => {
    if (!pendingChange) { setRfcOpen(false); return }
    try {
      await api.post(`/form-instances/${formInstanceId}/change-value`, { field_id: pendingChange.fieldId, value: pendingChange.value, reason })
      setToast({ type: 'success', message: 'Change recorded with reason.' })
    } catch {
      setToast({ type: 'error', message: 'Failed to record change.' })
      if (formInstance?.data) methods.setValue(pendingChange.fieldId, formInstance.data[pendingChange.fieldId])
    } finally { setRfcOpen(false); setPendingChange(null); setRfcFieldId(null) }
  }

  const handleRfcCancel = () => {
    if (pendingChange && formInstance?.data) methods.setValue(pendingChange.fieldId, formInstance.data[pendingChange.fieldId])
    setRfcOpen(false); setPendingChange(null); setRfcFieldId(null)
  }

  React.useEffect(() => {
    if (!isSubmitted || isDisabled || !formInstance) return
    const subscription = methods.watch((values, { name }) => {
      if (!name) return
      const originalValue = formInstance.data[name]
      const newValue = values[name]
      if (newValue !== originalValue && newValue !== undefined) { setPendingChange({ fieldId: name, value: newValue }); setRfcFieldId(name); setRfcOpen(true) }
    })
    return () => subscription.unsubscribe()
  }, [isSubmitted, isDisabled, formInstance, methods])

  if (loading) return <PageContainer><LoadingState label="form" /></PageContainer>
  if (fetchError || !formInstance) return <PageContainer><ErrorState message={fetchError || 'Form not found.'} /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader
        title={formInstance.form_name}
        description={<><span>Subject: <strong>{formInstance.subject_number}</strong></span>{' · '}<span>Visit: <strong>{formInstance.visit_name}</strong></span></>}
        status={<StatusBadge status={formInstance.status} label="Form status" />}
        ownership={<OwnershipBadge owner="EDC" />}
        actions={<div className="flex flex-wrap items-center gap-2">
          {normalizedStatus !== 'signed' && !isDisabled ? <SignatureDialog objectType="form" objectId={formInstanceId} onSigned={() => setFormInstance((current) => current ? { ...current, status: 'Signed' } : current)} /> : null}
          <Button type="button" variant="outline" onClick={() => setAuditPanelOpen(true)} aria-label="Open audit trail">View audit trail</Button>
        </div>}
      />

      {isDisabled ? <Alert variant="warning"><AlertDescription>{formInstance.is_locked ? 'This form is locked and cannot be edited.' : 'This form is frozen and cannot be edited.'}</AlertDescription></Alert> : null}
      <div className="mt-6 space-y-6">
        <LockControls formInstanceId={formInstanceId} isFrozen={Boolean(formInstance.is_frozen)} isLocked={Boolean(formInstance.is_locked)} onChanged={(state) => setFormInstance((current) => current ? { ...current, is_frozen: state.isFrozen, is_locked: state.isLocked } : current)} />
        <FormProvider {...methods}>
          <form onSubmit={(event) => event.preventDefault()} className="space-y-6">
            {formInstance.sections.map((section) => (
              <Card key={section.id}>
                <CardHeader><CardTitle className="text-lg">{section.title}</CardTitle></CardHeader>
                <CardContent><fieldset className="grid grid-cols-1 gap-5 md:grid-cols-2"><legend className="sr-only">{section.title}</legend>
                  {section.fields.map((field) => <div key={field.id} className={field.control_type === 'textarea' ? 'md:col-span-2' : ''}><FormField field={field} disabled={isDisabled} onFieldFocus={handleFieldFocus} />{serverErrors[field.id] ? <p className="mt-1 text-xs text-destructive" role="alert">{serverErrors[field.id]}</p> : null}</div>)}
                </fieldset></CardContent>
              </Card>
            ))}
          </form>
        </FormProvider>
        <FileUpload objectType="form_instance" objectId={formInstanceId} disabled={isDisabled} />
        {!isDisabled && (normalizedStatus === 'draft' || normalizedStatus === 'not_started' || normalizedStatus === 'in_progress') ? <div className="flex flex-wrap gap-3 border-t pt-4">
          <Button type="button" variant="outline" pending={saving} loadingText="Saving…" onClick={handleSave}>Save Draft</Button>
          <Button type="button" pending={submitting} loadingText="Submitting…" onClick={handleSubmit}>Submit</Button>
        </div> : null}
        {toast ? <MutationFeedback status={toast.type === 'success' ? 'success' : 'error'} action="Form" successMessage={toast.message} errorMessage={toast.message} /> : null}
      </div>
      <ReasonForChangeDialog open={rfcOpen} fieldLabel={rfcFieldId ? (fieldLabelMap[rfcFieldId] ?? rfcFieldId) : ''} onConfirm={handleRfcConfirm} onCancel={handleRfcCancel} />
      <AuditPanel formInstanceId={formInstanceId} open={auditPanelOpen} onClose={() => setAuditPanelOpen(false)} />
    </PageContainer>
  )
}
