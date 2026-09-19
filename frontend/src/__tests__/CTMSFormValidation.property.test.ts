import { describe, expect, it, vi } from 'vitest'
import {
  CTMSClientError,
  type CTMSTransitionOption,
} from '@/features/ctms/api'
import {
  createStatusTransitionSchema,
  mapCTMSServerErrors,
} from '@/features/ctms/forms'

interface GeneratedFormValidationCase {
  options: CTMSTransitionOption[]
  selectedStatus: string
  invalidStatus: string
  requiredReason: string
  safeReason: string
  form: {
    status: string
    reason: string
    name: string
    ownerId: string
    notes: string
  }
  errorField: 'name' | 'ownerId' | 'notes'
  errorMessage: string
}

/**
 * fast-check is not installed in this repository. Keep the generated-example
 * coverage deterministic and local while exercising varied transition shapes,
 * reason requirements, field errors, and unrelated draft values.
 */
function generatedFormValidationCases(count: number): GeneratedFormValidationCase[] {
  return Array.from({ length: count }, (_, index) => {
    const optionCount = (index % 3) + 1
    const options = Array.from({ length: optionCount }, (_, optionIndex) => ({
      status: `status-${index}-${optionIndex}`,
      requires_reason: (index + optionIndex) % 2 === 0,
      reason_label: `Reason for status ${index}-${optionIndex}`,
    }))
    const selectedOption = options[index % options.length]
    const errorFields: GeneratedFormValidationCase['errorField'][] = ['name', 'ownerId', 'notes']

    return {
      options,
      selectedStatus: selectedOption.status,
      invalidStatus: `unavailable-status-${index}`,
      requiredReason: index % 2 === 0 ? '' : '   ',
      safeReason: `Reviewed by operations ${index}`,
      form: {
        status: selectedOption.status,
        reason: `Draft reason ${index}`,
        name: `Operational record ${index}`,
        ownerId: `owner-${index}`,
        notes: `Unrelated draft value ${index}`,
      },
      errorField: errorFields[index % errorFields.length],
      errorMessage: `Review ${errorFields[index % errorFields.length]} ${index}`,
    }
  })
}

describe('CTMS form validation property', () => {
  // Feature: ctms-frontend, Property 5: Form validation follows server transition metadata
  // **Validates: Requirements 5.5–5.6, 5.9**
  it('blocks invalid transitions and preserves safe unrelated values across 128 generated cases', () => {
    for (const scenario of generatedFormValidationCases(128)) {
      const schema = createStatusTransitionSchema(scenario.options)
      const originalForm = { ...scenario.form }

      const invalidTransition = schema.safeParse({
        ...scenario.form,
        status: scenario.invalidStatus,
        reason: scenario.safeReason,
      })
      expect(invalidTransition.success).toBe(false)
      if (!invalidTransition.success) {
        expect(invalidTransition.error.issues.some((issue) => issue.path[0] === 'status')).toBe(true)
      }

      const missingReason = schema.safeParse({
        ...scenario.form,
        status: scenario.selectedStatus,
        reason: scenario.requiredReason,
      })
      const selectedOption = scenario.options.find((option) => option.status === scenario.selectedStatus)
      if (selectedOption?.requires_reason) {
        expect(missingReason.success).toBe(false)
        if (!missingReason.success) {
          expect(missingReason.error.issues.some((issue) => issue.path[0] === 'reason')).toBe(true)
        }
      } else {
        expect(missingReason.success).toBe(true)
      }

      const validTransition = schema.safeParse({
        ...scenario.form,
        status: scenario.selectedStatus,
        reason: selectedOption?.requires_reason ? scenario.safeReason : '',
      })
      expect(validTransition.success).toBe(true)
      expect(scenario.form).toEqual(originalForm)

      const setError = vi.fn()
      const mapping = mapCTMSServerErrors(new CTMSClientError('Review the highlighted fields.', {
        code: 'VALIDATION_ERROR',
        status: 422,
        requestId: `request-${scenario.errorField}-${scenario.errorMessage}`,
        details: {
          fields: { [scenario.errorField]: [scenario.errorMessage] },
          unrelated: { stack: 'must not be rendered' },
        },
      }), setError)

      expect(mapping.fieldErrors[scenario.errorField]).toEqual({
        type: 'server',
        message: scenario.errorMessage,
      })
      expect(setError).toHaveBeenCalledWith(scenario.errorField, {
        type: 'server',
        message: scenario.errorMessage,
      })
      expect(scenario.form).toEqual(originalForm)
    }
  })
})
