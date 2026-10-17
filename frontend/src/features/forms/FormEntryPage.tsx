import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm, FormProvider } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api, type PaginatedResponse } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { PageContainer, PageHeader, StatusBadge, OwnershipBadge, LoadingState, ErrorState, MutationFeedback } from '@/components/patterns'
import { FormField, type FieldDefinition } from './components/FormField'
import { ReasonForChangeDialog } from './components/ReasonForChangeDialog'
import { AuditPanel } from './components/AuditPanel'
import { LockControls } from './components/LockControls'
import { FileUpload } from './components/FileUpload'
import { SignatureDialog } from '@/features/signatures'
import { FormStatusStrip } from '@/features/edc/components/FormStatusStrip'
import { normalizeDataEntryStatus } from '@/features/edc/status'
import { RepeatingRecordsTable } from './components/RepeatingRecordsTable'
import { PERMISSIONS, usePermission } from '@/lib/permissions'

interface FormSection { id: string; title: string; order: number; fields: Array<FieldDefinition & { is_visible?: boolean }> }
type FormInstanceStatus = string
interface FieldValueData { id: string; field_definition_id: string; value: string | null }
interface FormInstanceData { id: string; study_id: string; form_definition_id: string; form_name: string; is_repeating: boolean; subject_id: string; subject_number: string; visit_name: string; status: FormInstanceStatus; data_entry_status?: string; operational_status?: { review: string; sdv: string; sdr: string; signature: string; active_query_count: number }; is_frozen: boolean; is_locked: boolean; is_reviewed?: boolean; sdv_status?: string; open_query_count?: number; signature_status?: string; sections: FormSection[]; data: Record<string, unknown>; field_values?: FieldValueData[]; validation_errors?: Record<string, string> }
interface QueryField { fieldDefinitionId: string; label: string; value: unknown }
interface FieldQueryItem { id: string; text: string; status: string; assigned_role?: string | null; created_at: string }

function formatSavedValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'No value entered'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : 'No value entered'
  if (typeof value !== 'string') return JSON.stringify(value)
  if (!value.startsWith('__edc_json__:')) return value
  try {
    const parsed: unknown = JSON.parse(value.slice('__edc_json__:'.length))
    if (typeof parsed === 'boolean') return parsed ? 'Yes' : 'No'
    if (Array.isArray(parsed)) return parsed.length ? parsed.map(String).join(', ') : 'No value entered'
    return JSON.stringify(parsed)
  } catch {
    return value
  }
}

/** Builds the existing dynamic Zod schema without changing clinical validation rules. */
function buildZodSchema(sections: FormSection[]) {
  const shape: Record<string, z.ZodTypeAny> = {}
  for (const section of sections) {
    for (const field of section.fields) {
      if (field.is_visible === false) continue
      let fieldSchema: z.ZodTypeAny
      switch (field.control_type) {
        case 'integer':
        case 'decimal':
        case 'float':
        case 'slider':
          fieldSchema = field.is_required ? z.number({ error: `${field.label} must be a number` }) : z.union([z.number(), z.nan()]).optional()
          break
        case 'boolean': fieldSchema = z.boolean().optional(); break
        case 'checkbox':
          fieldSchema = field.codelist_items?.length
            ? (field.is_required ? z.array(z.string()).min(1, `${field.label} is required`) : z.array(z.string()).optional())
            : z.boolean().optional()
          break
        case 'multi-select':
        case 'repeating_table':
          fieldSchema = field.is_required ? z.array(z.string()).min(1, `${field.label} is required`) : z.array(z.string()).optional()
          break
        case 'label':
        case 'calculated':
          fieldSchema = z.unknown().optional()
          break
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
  const queryClient = useQueryClient()
  const canCreateQuery = usePermission(PERMISSIONS.QUERY_CREATE)
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
  const [queryField, setQueryField] = React.useState<QueryField | null>(null)
  const [queryText, setQueryText] = React.useState('')
  const [queryAssignedRole, setQueryAssignedRole] = React.useState('')
  const [queryError, setQueryError] = React.useState('')
  const [creatingQuery, setCreatingQuery] = React.useState(false)

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
  const entryStatus = formInstance?.data_entry_status ?? formInstance?.status ?? ''
  const normalizedStatus = entryStatus.toLowerCase().replaceAll(' ', '_')
  const isSubmitted = normalizedStatus === 'submitted' || normalizedStatus === 'reviewed'
  const isDisabled = formInstance?.is_frozen || formInstance?.is_locked || false
  const fieldLabelMap = React.useMemo(() => {
    const map: Record<string, string> = {}
    formInstance?.sections.forEach((section) => section.fields.forEach((field) => { map[field.id] = field.label }))
    return map
  }, [formInstance])
  const fieldValueMap = React.useMemo(() => new Map(
    (formInstance?.field_values ?? []).map((fieldValue) => [fieldValue.field_definition_id, fieldValue]),
  ), [formInstance])
  const assignmentRoles = useQuery({
    queryKey: ['query-assignment-roles', formInstance?.study_id, formInstanceId],
    queryFn: async () => (await api.get<string[]>(`/studies/${formInstance?.study_id}/queries/assignment-roles`, {
      params: { target_type: 'Form_Instance', target_id: formInstanceId },
    })).data,
    enabled: Boolean(formInstance?.study_id && queryField),
  })
  const fieldQueries = useQuery({
    queryKey: ['field-queries', formInstanceId, queryField?.fieldDefinitionId],
    queryFn: async () => (await api.get<PaginatedResponse<FieldQueryItem>>(`/form-instances/${formInstanceId}/fields/${queryField?.fieldDefinitionId}/queries`, {
      params: { page: 1, page_size: 100 },
    })).data,
    enabled: Boolean(queryField?.fieldDefinitionId),
  })

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
    try {
      const { data } = await api.patch<FormInstanceData>(`/form-instances/${formInstanceId}/data`, { values })
      setFormInstance(data)
      setToast({ type: 'success', message: 'Form saved successfully.' })
    }
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
      const { data } = await api.post<FormInstanceData>(`/form-instances/${formInstanceId}/change-value`, { field_id: pendingChange.fieldId, value: pendingChange.value, reason })
      setFormInstance(data)
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

  const closeQueryDialog = () => {
    setQueryField(null)
    setQueryText('')
    setQueryAssignedRole('')
    setQueryError('')
  }

  const handleCreateQuery = async () => {
    const text = queryText.trim()
    if (!queryField || !formInstance || !text) return
    setCreatingQuery(true)
    setQueryError('')
    try {
      await api.post(`/form-instances/${formInstanceId}/fields/${queryField.fieldDefinitionId}/queries`, {
        text,
        assigned_role: queryAssignedRole.trim() || null,
      })
      setFormInstance((current) => current ? {
        ...current,
        operational_status: current.operational_status ? {
          ...current.operational_status,
          active_query_count: current.operational_status.active_query_count + 1,
        } : current.operational_status,
        open_query_count: (current.open_query_count ?? 0) + 1,
      } : current)
      await queryClient.invalidateQueries({ queryKey: ['field-queries', formInstanceId] })
      setToast({ type: 'success', message: `Query created for ${queryField.label}.` })
      closeQueryDialog()
    } catch (error: unknown) {
      const response = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } }).response
      setQueryError(response?.data?.error?.message ?? response?.data?.detail ?? 'Could not create the query.')
    } finally {
      setCreatingQuery(false)
    }
  }

  if (loading) return <PageContainer><LoadingState label="form" /></PageContainer>
  if (fetchError || !formInstance) return <PageContainer><ErrorState message={fetchError || 'Form not found.'} /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader
        title={formInstance.form_name}
        description={<><span>Subject: <strong>{formInstance.subject_number}</strong></span>{' · '}<span>Visit: <strong>{formInstance.visit_name}</strong></span></>}
        status={<StatusBadge status={entryStatus} label="Form status" />}
        ownership={<OwnershipBadge owner="EDC" />}
        actions={<div className="flex flex-wrap items-center gap-2">
          {normalizedStatus !== 'signed' && !isDisabled ? <SignatureDialog objectType="form" objectId={formInstanceId} onSigned={() => setFormInstance((current) => current ? { ...current, status: 'Signed' } : current)} /> : null}
          <Button type="button" variant="outline" onClick={() => setAuditPanelOpen(true)} aria-label="Open audit trail">View audit trail</Button>
        </div>}
      />

      <FormStatusStrip status={{
        dataEntry: normalizeDataEntryStatus(entryStatus),
        queries: (formInstance.operational_status?.active_query_count ?? formInstance.open_query_count ?? 0) > 0 ? 'Open' : 'Closed',
        review: formInstance.operational_status?.review ?? (formInstance.is_reviewed === undefined ? undefined : formInstance.is_reviewed ? 'Reviewed' : 'Not Reviewed'),
        sdv: formInstance.operational_status?.sdv ?? formInstance.sdv_status,
        sdr: formInstance.operational_status?.sdr,
        signature: formInstance.operational_status?.signature ?? formInstance.signature_status,
        lock: formInstance.is_locked ? 'Locked' : formInstance.is_frozen ? 'Frozen' : 'Unlocked',
      }} />

      {isDisabled ? <Alert variant="warning"><AlertDescription>{formInstance.is_locked ? 'This form is locked and cannot be edited.' : 'This form is frozen and cannot be edited.'}</AlertDescription></Alert> : null}
      <div className="mt-6 space-y-6">
        <LockControls formInstanceId={formInstanceId} isFrozen={Boolean(formInstance.is_frozen)} isLocked={Boolean(formInstance.is_locked)} onChanged={(state) => setFormInstance((current) => current ? { ...current, is_frozen: state.isFrozen, is_locked: state.isLocked } : current)} />
        <FormProvider {...methods}>
          <form onSubmit={(event) => event.preventDefault()} className="space-y-6">
            {formInstance.sections.map((section) => (
              <Card key={section.id}>
                <CardHeader><CardTitle className="text-lg">{section.title}</CardTitle></CardHeader>
                <CardContent><fieldset className="grid grid-cols-1 gap-5 md:grid-cols-2"><legend className="sr-only">{section.title}</legend>
                  {section.fields.filter((field) => field.is_visible !== false).map((field) => {
                    const fieldValue = fieldValueMap.get(field.id)
                    const canTargetField = Boolean(formInstance.study_id && !isDisabled)
                    return <div key={field.id} className={['textarea', 'label', 'body_image', 'repeating_table'].includes(field.control_type) ? 'md:col-span-2' : ''}><FormField field={field} disabled={isDisabled} onFieldFocus={handleFieldFocus} labelAction={canCreateQuery && field.control_type !== 'label' ? <Button type="button" size="sm" variant="ghost" disabled={!canTargetField} title={`Create a query for ${field.label}`} aria-label={`Add query for ${field.label}`} onClick={() => setQueryField({ fieldDefinitionId: field.id, label: field.label, value: fieldValue?.value ?? formInstance.data[field.id] ?? null })}>Add query</Button> : undefined} />{serverErrors[field.id] ? <p className="mt-1 text-xs text-destructive" role="alert">{serverErrors[field.id]}</p> : null}</div>
                  })}
                </fieldset></CardContent>
              </Card>
            ))}
          </form>
        </FormProvider>
        {formInstance.is_repeating ? <RepeatingRecordsTable formInstanceId={formInstanceId} submitted={isSubmitted} disabled={isDisabled} /> : null}
        <FileUpload objectType="form_instance" objectId={formInstanceId} disabled={isDisabled} />
        {!isDisabled && (normalizedStatus === 'draft' || normalizedStatus === 'not_started' || normalizedStatus === 'in_progress') ? <div className="flex flex-wrap gap-3 border-t pt-4">
          <Button type="button" variant="outline" pending={saving} loadingText="Saving…" onClick={handleSave}>Save Draft</Button>
          <Button type="button" pending={submitting} loadingText="Submitting…" onClick={handleSubmit}>Submit</Button>
        </div> : null}
        {toast ? <MutationFeedback status={toast.type === 'success' ? 'success' : 'error'} action="Form" successMessage={toast.message} errorMessage={toast.message} /> : null}
      </div>
      <ReasonForChangeDialog open={rfcOpen} fieldLabel={rfcFieldId ? (fieldLabelMap[rfcFieldId] ?? rfcFieldId) : ''} onConfirm={handleRfcConfirm} onCancel={handleRfcCancel} />
      <AuditPanel formInstanceId={formInstanceId} open={auditPanelOpen} onClose={() => setAuditPanelOpen(false)} />
      <Dialog open={queryField !== null} onOpenChange={(open) => { if (!open && !creatingQuery) closeQueryDialog() }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add query for {queryField?.label}</DialogTitle><DialogDescription>Create a query linked to this specific field, whether it is answered or unanswered.</DialogDescription></DialogHeader>
          <form onSubmit={(event) => { event.preventDefault(); void handleCreateQuery() }} className="space-y-4">
            {queryError ? <Alert variant="destructive"><AlertDescription>{queryError}</AlertDescription></Alert> : null}
            <div className="rounded-md border bg-muted/40 p-3"><p className="text-xs font-medium text-muted-foreground">Current saved value</p><p className="mt-1 break-words text-sm">{formatSavedValue(queryField?.value ?? null)}</p></div>
            <section className="space-y-2" aria-labelledby="field-query-history-heading"><div className="flex items-center justify-between gap-3"><h3 id="field-query-history-heading" className="text-sm font-medium">Previous queries</h3>{fieldQueries.data ? <span className="text-xs text-muted-foreground">{fieldQueries.data.total}</span> : null}</div>{fieldQueries.isLoading ? <p className="text-sm text-muted-foreground">Loading previous queries…</p> : fieldQueries.isError ? <p className="text-sm text-destructive" role="alert">Previous queries could not be loaded.</p> : fieldQueries.data?.items.length ? <div className="max-h-48 space-y-2 overflow-y-auto">{fieldQueries.data.items.map((item) => <article key={item.id} className="rounded-md border p-3"><div className="flex items-start justify-between gap-3"><p className="text-sm">{item.text}</p><StatusBadge label="query status" status={item.status} /></div><p className="mt-1 text-xs text-muted-foreground">{item.assigned_role ? `Assigned to ${item.assigned_role} · ` : ''}{new Date(item.created_at).toLocaleString()}</p></article>)}</div> : <p className="text-sm text-muted-foreground">No previous queries for this field.</p>}</section>
            <div className="space-y-1.5"><Label htmlFor="field-query-assigned-role">Assigned role (optional)</Label><select id="field-query-assigned-role" value={queryAssignedRole} onChange={(event) => setQueryAssignedRole(event.target.value)} disabled={assignmentRoles.isLoading || assignmentRoles.isError} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"><option value="">{assignmentRoles.isLoading ? 'Loading roles…' : 'Unassigned'}</option>{(assignmentRoles.data ?? []).map((role) => <option key={role} value={role}>{role}</option>)}</select>{assignmentRoles.isError ? <p className="text-xs text-destructive" role="alert">Assignment roles could not be loaded.</p> : null}{!assignmentRoles.isLoading && !assignmentRoles.isError && assignmentRoles.data?.length === 0 ? <p className="text-xs text-muted-foreground">No active roles are assigned in this field&apos;s scope.</p> : null}</div>
            <div className="space-y-1.5"><Label htmlFor="field-query-text">Describe the issue</Label><Textarea id="field-query-text" required maxLength={4000} value={queryText} onChange={(event) => setQueryText(event.target.value)} className="min-h-28" /></div>
            <DialogFooter><Button type="button" variant="outline" disabled={creatingQuery} onClick={closeQueryDialog}>Cancel</Button><Button type="submit" pending={creatingQuery} loadingText="Creating…" disabled={!queryText.trim()}>Create query</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
