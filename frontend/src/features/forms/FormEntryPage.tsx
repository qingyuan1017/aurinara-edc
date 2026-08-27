import * as React from 'react'
import { useForm, FormProvider } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { FormField, type FieldDefinition } from './components/FormField'
import { ReasonForChangeDialog } from './components/ReasonForChangeDialog'
import { AuditPanel } from './components/AuditPanel'

// ---------- Types ----------

interface FormSection {
  id: string
  title: string
  order: number
  fields: FieldDefinition[]
}

type FormInstanceStatus = string

interface FormInstanceData {
  id: string
  form_definition_id: string
  form_name: string
  subject_id: string
  subject_number: string
  visit_name: string
  status: FormInstanceStatus
  is_frozen: boolean
  is_locked: boolean
  sections: FormSection[]
  data: Record<string, unknown>
  validation_errors?: Record<string, string>
}

// ---------- Helpers ----------

/**
 * Builds a Zod schema dynamically from field definitions.
 * Required fields get a non-empty check; numeric fields get coercion.
 */
function buildZodSchema(sections: FormSection[]) {
  const shape: Record<string, z.ZodTypeAny> = {}

  for (const section of sections) {
    for (const field of section.fields) {
      let fieldSchema: z.ZodTypeAny

      switch (field.control_type) {
        case 'integer':
          fieldSchema = field.is_required
            ? z.number({ error: `${field.label} must be a number` })
            : z.union([z.number(), z.nan()]).optional()
          break
        case 'decimal':
          fieldSchema = field.is_required
            ? z.number({ error: `${field.label} must be a number` })
            : z.union([z.number(), z.nan()]).optional()
          break
        case 'boolean':
          fieldSchema = z.boolean().optional()
          break
        case 'checkbox':
          fieldSchema = field.is_required
            ? z.array(z.string()).min(1, `${field.label} is required`)
            : z.array(z.string()).optional()
          break
        default:
          fieldSchema = field.is_required
            ? z.string().min(1, `${field.label} is required`)
            : z.string().optional()
      }

      shape[field.id] = fieldSchema
    }
  }

  return z.object(shape)
}

// ---------- Component ----------

interface FormEntryPageProps {
  formInstanceId: string
}

/**
 * Main eCRF data entry page (Requirement 24.2, 24.3, 24.5).
 *
 * - Fetches form instance data and renders fields dynamically
 * - Uses React Hook Form + Zod for client validation
 * - Required fields highlighted with asterisk and red border when empty
 * - Save (draft), Submit, and Reopen actions
 * - Reason_For_Change dialog on post-submit edits
 * - Audit trail side panel
 */
export function FormEntryPage({ formInstanceId }: FormEntryPageProps) {
  // --- State ---
  const [formInstance, setFormInstance] = React.useState<FormInstanceData | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [fetchError, setFetchError] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)
  const [toast, setToast] = React.useState<{ type: 'success' | 'error'; message: string } | null>(null)

  // Server-side validation errors
  const [serverErrors, setServerErrors] = React.useState<Record<string, string>>({})

  // Reason for Change state
  const [rfcOpen, setRfcOpen] = React.useState(false)
  const [rfcFieldId, setRfcFieldId] = React.useState<string | null>(null)
  const [pendingChange, setPendingChange] = React.useState<{ fieldId: string; value: unknown } | null>(null)

  // Side panels
  const [auditPanelOpen, setAuditPanelOpen] = React.useState(false)

  // --- Load form instance ---
  React.useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFetchError('')

    api
      .get<FormInstanceData>(`/form-instances/${formInstanceId}`)
      .then(({ data }) => {
        if (!cancelled) {
          setFormInstance(data)
          if (data.validation_errors) {
            setServerErrors(data.validation_errors)
          }
        }
      })
      .catch(() => {
        if (!cancelled) setFetchError('Failed to load form data.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [formInstanceId])

  // --- Build schema and form ---
  const schema = React.useMemo(
    () => (formInstance ? buildZodSchema(formInstance.sections) : z.object({})),
    [formInstance],
  )

  const methods = useForm<Record<string, unknown>>({
    resolver: zodResolver(schema) as never,
    defaultValues: formInstance?.data ?? {},
    values: formInstance?.data as Record<string, unknown> | undefined,
    mode: 'onBlur',
  })

  // --- Derived state ---
  const normalizedStatus = formInstance?.status.toLowerCase().replaceAll(' ', '_')
  const isSubmitted = normalizedStatus === 'submitted' || normalizedStatus === 'reviewed'
  const isDisabled = formInstance?.is_frozen || formInstance?.is_locked || false

  // --- Field labels lookup ---
  const fieldLabelMap = React.useMemo(() => {
    const map: Record<string, string> = {}
    if (formInstance) {
      for (const section of formInstance.sections) {
        for (const field of section.fields) {
          map[field.id] = field.label
        }
      }
    }
    return map
  }, [formInstance])

  // --- Toast auto-dismiss ---
  React.useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 4000)
      return () => clearTimeout(t)
    }
  }, [toast])

  // --- Handlers ---

  const handleFieldFocus = (fieldId: string) => {
    // If form is submitted, intercept edit to require Reason for Change
    if (isSubmitted && !isDisabled) {
      setRfcFieldId(fieldId)
      // We'll capture the change on blur via a watch, but the dialog opens when they start editing
    }
  }

  /**
   * Save form data as draft (no submission).
   */
  const handleSave = async () => {
    const values = methods.getValues()
    setSaving(true)
    setServerErrors({})
    try {
      await api.patch(`/form-instances/${formInstanceId}/data`, { values })
      setToast({ type: 'success', message: 'Form saved successfully.' })
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { errors?: Record<string, string> } } }
      if (axiosErr.response?.data?.errors) {
        setServerErrors(axiosErr.response.data.errors)
      }
      setToast({ type: 'error', message: 'Failed to save form.' })
    } finally {
      setSaving(false)
    }
  }

  /**
   * Submit form — triggers server-side validation.
   */
  const handleSubmit = async () => {
    // Run client validation first
    const valid = await methods.trigger()
    if (!valid) {
      setToast({ type: 'error', message: 'Please fix validation errors before submitting.' })
      return
    }

    const values = methods.getValues()
    setSubmitting(true)
    setServerErrors({})
    try {
      // Save data first, then submit
      await api.patch(`/form-instances/${formInstanceId}/data`, { values })
      const { data } = await api.post<FormInstanceData>(`/form-instances/${formInstanceId}/submit`)
      setFormInstance(data)
      setToast({ type: 'success', message: 'Form submitted successfully.' })
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { errors?: Record<string, string>; detail?: string } } }
      if (axiosErr.response?.data?.errors) {
        setServerErrors(axiosErr.response.data.errors)
        setToast({ type: 'error', message: 'Validation errors found. Please review.' })
      } else {
        setToast({ type: 'error', message: axiosErr.response?.data?.detail ?? 'Failed to submit form.' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  /**
   * Handle Reason for Change confirmation — sends change-value request.
   */
  const handleRfcConfirm = async (reason: string) => {
    if (!pendingChange) {
      setRfcOpen(false)
      return
    }

    try {
      await api.post(`/form-instances/${formInstanceId}/change-value`, {
        field_id: pendingChange.fieldId,
        value: pendingChange.value,
        reason,
      })
      setToast({ type: 'success', message: 'Change recorded with reason.' })
    } catch {
      setToast({ type: 'error', message: 'Failed to record change.' })
      // Revert the value in the form
      if (formInstance?.data) {
        methods.setValue(pendingChange.fieldId, formInstance.data[pendingChange.fieldId])
      }
    } finally {
      setRfcOpen(false)
      setPendingChange(null)
      setRfcFieldId(null)
    }
  }

  const handleRfcCancel = () => {
    // Revert the field to original value
    if (pendingChange && formInstance?.data) {
      methods.setValue(pendingChange.fieldId, formInstance.data[pendingChange.fieldId])
    }
    setRfcOpen(false)
    setPendingChange(null)
    setRfcFieldId(null)
  }

  // Watch for changes on submitted forms to trigger RFC dialog
  React.useEffect(() => {
    if (!isSubmitted || isDisabled || !formInstance) return

    const subscription = methods.watch((values, { name }) => {
      if (!name) return
      const originalValue = formInstance.data[name]
      const newValue = values[name]
      // Only trigger RFC if value actually changed
      if (newValue !== originalValue && newValue !== undefined) {
        setPendingChange({ fieldId: name, value: newValue })
        setRfcFieldId(name)
        setRfcOpen(true)
      }
    })

    return () => subscription.unsubscribe()
  }, [isSubmitted, isDisabled, formInstance, methods])

  // --- Render ---

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="text-sm text-gray-500">Loading form...</div>
      </div>
    )
  }

  if (fetchError || !formInstance) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="text-sm text-red-600">{fetchError || 'Form not found.'}</div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto py-6 px-4 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{formInstance.form_name}</h1>
          <p className="text-sm text-gray-600 mt-1">
            Subject: <span className="font-medium">{formInstance.subject_number}</span>
            {' · '}
            Visit: <span className="font-medium">{formInstance.visit_name}</span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <StatusBadge status={formInstance.status} />
          <button
            onClick={() => setAuditPanelOpen(true)}
            className="p-2 rounded hover:bg-gray-100 text-gray-600"
            title="View audit trail"
            aria-label="Open audit trail"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Frozen/Locked banner */}
      {isDisabled && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3 text-sm text-yellow-800">
          {formInstance.is_locked
            ? 'This form is locked and cannot be edited.'
            : 'This form is frozen and cannot be edited.'}
        </div>
      )}

      {/* Form */}
      <FormProvider {...methods}>
        <form onSubmit={(e) => e.preventDefault()} className="space-y-8">
          {formInstance.sections.map((section) => (
            <fieldset key={section.id} className="border rounded-lg p-5 space-y-5 bg-white shadow-sm">
              <legend className="text-base font-semibold text-gray-800 px-2">
                {section.title}
              </legend>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {section.fields.map((field) => (
                  <div key={field.id} className={field.control_type === 'textarea' ? 'md:col-span-2' : ''}>
                    <FormField
                      field={field}
                      disabled={isDisabled}
                      onFieldFocus={handleFieldFocus}
                    />
                    {/* Server-side validation errors */}
                    {serverErrors[field.id] && (
                      <p className="text-xs text-red-600 mt-1" role="alert">
                        {serverErrors[field.id]}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </fieldset>
          ))}
        </form>
      </FormProvider>

      {/* Action buttons */}
      {!isDisabled && (
        <div className="flex items-center gap-3 pt-2 border-t">
          {(normalizedStatus === 'draft' || normalizedStatus === 'not_started' || normalizedStatus === 'in_progress') && (
            <>
              <Button
                onClick={handleSave}
                variant="outline"
                disabled={saving}
              >
                {saving ? 'Saving...' : 'Save Draft'}
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Submit'}
              </Button>
            </>
          )}

        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 px-4 py-3 rounded-md shadow-lg text-sm font-medium ${
            toast.type === 'success'
              ? 'bg-green-50 text-green-800 border border-green-200'
              : 'bg-red-50 text-red-800 border border-red-200'
          }`}
          role="status"
          aria-live="polite"
        >
          {toast.message}
        </div>
      )}

      {/* Reason for Change Dialog */}
      <ReasonForChangeDialog
        open={rfcOpen}
        fieldLabel={rfcFieldId ? (fieldLabelMap[rfcFieldId] ?? rfcFieldId) : ''}
        onConfirm={handleRfcConfirm}
        onCancel={handleRfcCancel}
      />

      {/* Audit Panel */}
      <AuditPanel
        formInstanceId={formInstanceId}
        open={auditPanelOpen}
        onClose={() => setAuditPanelOpen(false)}
      />
    </div>
  )
}

// ---------- Status Badge ----------

function StatusBadge({ status }: { status: FormInstanceStatus }) {
  const styles: Record<FormInstanceStatus, string> = {
    draft: 'bg-gray-100 text-gray-700',
    submitted: 'bg-blue-100 text-blue-700',
    reviewed: 'bg-purple-100 text-purple-700',
    frozen: 'bg-cyan-100 text-cyan-700',
    locked: 'bg-red-100 text-red-700',
  }

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize ${styles[status] ?? 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  )
}
