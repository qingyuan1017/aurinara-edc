import { z } from 'zod'
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import { normalizeCTMSError, type CTMSClientError, type CTMSTransitionOption } from '../api'

export interface OwnedStringOptions {
  label?: string
  minLength?: number
  maxLength?: number
}

const emptyToUndefined = (value: unknown) => value === '' ? undefined : value

/**
 * Convenience validation for a CTMS-owned string. It does not make any
 * claims about server permission, study scope, or record ownership.
 */
export function ownedStringSchema(options: OwnedStringOptions = {}) {
  const label = options.label ?? 'Value'
  let schema = z.string({ error: `${label} is required` }).trim()
  if (options.minLength !== undefined) schema = schema.min(options.minLength, `${label} must be at least ${options.minLength} characters`)
  if (options.maxLength !== undefined) schema = schema.max(options.maxLength, `${label} must be at most ${options.maxLength} characters`)
  return schema
}

export function optionalOwnedStringSchema(options: OwnedStringOptions = {}) {
  return z.preprocess(emptyToUndefined, ownedStringSchema(options).optional())
}

function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

/** Validates the HTML/API date shape without applying timezone or scope rules. */
export const ownedDateSchema = z.string({ error: 'Date is required' }).trim().refine(isCalendarDate, 'Enter a valid date in YYYY-MM-DD format')
export const optionalOwnedDateSchema = z.preprocess(emptyToUndefined, ownedDateSchema.optional())

export interface QuantityOptions {
  label?: string
  min?: number
  max?: number
  integer?: boolean
}

/** Coerces an input control's string value for convenience; the API remains authoritative. */
export function ownedQuantitySchema(options: QuantityOptions = {}) {
  const label = options.label ?? 'Quantity'
  let schema = z.coerce.number({ error: `${label} must be a number` }).finite(`${label} must be a finite number`)
  if (options.integer) schema = schema.int(`${label} must be a whole number`)
  if (options.min !== undefined) schema = schema.min(options.min, `${label} must be at least ${options.min}`)
  if (options.max !== undefined) schema = schema.max(options.max, `${label} must be at most ${options.max}`)
  return z.preprocess(emptyToUndefined, schema)
}

export function optionalOwnedQuantitySchema(options: QuantityOptions = {}) {
  return z.preprocess(emptyToUndefined, ownedQuantitySchema(options).optional())
}

export function ownedEnumSchema<const T extends readonly [string, ...string[]]>(values: T, label = 'Value') {
  return z.enum(values, { error: `${label} must be one of the available options` })
}

export function optionalOwnedEnumSchema<const T extends readonly [string, ...string[]]>(values: T, label = 'Value') {
  return z.preprocess(emptyToUndefined, ownedEnumSchema(values, label).optional())
}

/** A canonical reference is an identifier used for context, not a client authorization decision. */
export const canonicalReferenceSchema = z.object({
  id: ownedStringSchema({ label: 'Reference ID', maxLength: 200 }),
  label: optionalOwnedStringSchema({ label: 'Reference label', maxLength: 200 }),
  module: optionalOwnedEnumSchema(['EDC', 'CTMS'] as const, 'Reference module'),
})

export const canonicalReferenceIdSchema = ownedStringSchema({ label: 'Reference ID', maxLength: 200 })

export const fileMetadataSchema = z.object({
  fileName: ownedStringSchema({ label: 'File name', maxLength: 255 }).refine((value) => !/[\\/]/.test(value), 'File name cannot contain path separators'),
  contentType: ownedStringSchema({ label: 'Content type', maxLength: 160 }),
  sizeBytes: ownedQuantitySchema({ label: 'File size', min: 0, integer: true }),
})

export const transitionReasonSchema = ownedStringSchema({ label: 'Transition reason', minLength: 3, maxLength: 2000 })
export const statusTransitionSchema = z.object({
  status: ownedStringSchema({ label: 'Status', maxLength: 100 }),
  reason: optionalOwnedStringSchema({ label: 'Transition reason', maxLength: 2000 }),
})

/**
 * Builds the client-side transition shape from server-returned choices. The
 * server remains authoritative; this only prevents submitting an option that
 * was not rendered and enforces a server-declared reason requirement.
 */
export function createStatusTransitionSchema(options: readonly CTMSTransitionOption[]) {
  const allowedStatuses = new Set(options.map((option) => option.status))
  return statusTransitionSchema.superRefine((value, context) => {
    if (!allowedStatuses.has(value.status)) {
      context.addIssue({ code: 'custom', path: ['status'], message: 'Select an available status transition' })
      return
    }
    const selected = options.find((option) => option.status === value.status)
    if (selected?.requires_reason && !value.reason?.trim()) {
      context.addIssue({ code: 'custom', path: ['reason'], message: selected.reason_label ?? 'A reason is required for this transition' })
    }
  })
}

export const statusTransitionSchemaFor = createStatusTransitionSchema

export interface CTMSServerFieldError {
  message: string
  type?: string
}

export interface CTMSFormErrorMapping {
  fieldErrors: Record<string, CTMSServerFieldError>
  formMessage?: string
  error: CTMSClientError
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function message(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed ? trimmed.slice(0, 1000) : undefined
  }
  if (Array.isArray(value)) return message(value.find((entry) => typeof entry === 'string'))
  return undefined
}

function extractFieldErrors(error: CTMSClientError): Record<string, CTMSServerFieldError> {
  const details = record(error.details)
  const candidates = [details?.fields, details?.field_errors, details?.errors, details]
  const result: Record<string, CTMSServerFieldError> = {}
  for (const candidate of candidates) {
    const fields = record(candidate)
    if (!fields) continue
    for (const [field, value] of Object.entries(fields)) {
      const fieldMessage = message(value)
      if (fieldMessage) result[field] = { type: 'server', message: fieldMessage }
    }
  }
  return result
}

/**
 * Map sanitized server validation errors into React Hook Form without changing
 * values, caching, or authorization state. Unknown server fields become form errors.
 */
export function mapCTMSServerErrors<T extends FieldValues>(
  errorInput: unknown,
  setError: UseFormSetError<T>,
): CTMSFormErrorMapping {
  const error = normalizeCTMSError(errorInput)
  const fieldErrors = extractFieldErrors(error)
  for (const [field, fieldError] of Object.entries(fieldErrors)) {
    setError(field as Path<T>, fieldError)
  }

  const details = record(error.details)
  const formMessage = message(details?.form) ?? message(details?.form_error) ?? (Object.keys(fieldErrors).length === 0 ? error.message : undefined)
  if (formMessage) setError('root.server' as Path<T>, { type: 'server', message: formMessage })
  return { fieldErrors, formMessage, error }
}

export const applyCTMSServerErrors = mapCTMSServerErrors
