import { z } from 'zod'

/**
 * PV client-side Zod schemas run before submission (Requirement 19.2). If
 * client validation fails, no request is sent. The API_Layer remains
 * authoritative for every rule; these mirror the design's documented bounds
 * for a fast, accessible first line of feedback.
 */

const trimmed = (label: string) => z.string({ error: `${label} is required` }).trim()

/** Safety case intake: study/site/subject reference and a case type. */
export const caseIntakeSchema = z.object({
  subject_reference: trimmed('Subject reference').min(1, 'Subject reference is required'),
  case_type: trimmed('Case type').min(1, 'Case type is required'),
  site_id: z.preprocess((v) => (v === '' ? undefined : v), z.string().trim().optional()),
})
export type CaseIntakeValues = z.infer<typeof caseIntakeSchema>

function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

const dateField = (label: string) =>
  trimmed(label).refine(isCalendarDate, `Enter a valid ${label.toLowerCase()} (YYYY-MM-DD)`)
const optionalDateField = (label: string) =>
  z.preprocess(
    (v) => (v === '' ? undefined : v),
    trimmed(label).refine(isCalendarDate, `Enter a valid ${label.toLowerCase()} (YYYY-MM-DD)`).optional(),
  )

/**
 * Adverse-event capture: verbatim term 1–200 chars, onset date, outcome, and
 * an optional resolution date that must not be earlier than onset.
 */
export const adverseEventSchema = z
  .object({
    verbatim_term: trimmed('Verbatim term')
      .min(1, 'Verbatim term is required')
      .max(200, 'Verbatim term must be at most 200 characters'),
    onset_date: dateField('Onset date'),
    outcome: trimmed('Outcome').min(1, 'Outcome is required'),
    resolution_date: optionalDateField('Resolution date'),
  })
  .refine(
    (value) => !value.resolution_date || value.resolution_date >= value.onset_date,
    { path: ['resolution_date'], message: 'Resolution date cannot be earlier than the onset date' },
  )
export type AdverseEventValues = z.infer<typeof adverseEventSchema>

export const SERIOUSNESS_CRITERIA = [
  'death',
  'life-threatening',
  'hospitalization',
  'disability',
  'congenital anomaly',
  'other medically important',
] as const

/** Seriousness assessment: a serious determination requires ≥1 criterion. */
export const seriousnessSchema = z
  .object({
    serious: z.boolean(),
    criteria: z.array(z.enum(SERIOUSNESS_CRITERIA)).default([]),
  })
  .refine((value) => !value.serious || value.criteria.length >= 1, {
    path: ['criteria'],
    message: 'A serious determination requires at least one criterion',
  })
export type SeriousnessValues = z.infer<typeof seriousnessSchema>

/** Case narrative: non-empty after trimming, at most 20,000 characters. */
export const narrativeSchema = z.object({
  text: trimmed('Narrative')
    .min(1, 'Narrative text is required')
    .max(20000, 'Narrative must be at most 20,000 characters'),
})
export type NarrativeValues = z.infer<typeof narrativeSchema>

/**
 * Reason_For_Change: non-empty after trimming, at most 4,000 characters
 * (Requirement 19.3). Required before sending edits to submitted safety data
 * or revising a narrative.
 */
export const reasonForChangeSchema = z.object({
  reason: trimmed('Reason for change')
    .min(1, 'A reason for change is required')
    .max(4000, 'The reason for change must be at most 4,000 characters'),
})
export type ReasonForChangeValues = z.infer<typeof reasonForChangeSchema>

/** Narrative revision requires new text plus a Reason_For_Change. */
export const narrativeRevisionSchema = narrativeSchema.merge(reasonForChangeSchema)
export type NarrativeRevisionValues = z.infer<typeof narrativeRevisionSchema>
