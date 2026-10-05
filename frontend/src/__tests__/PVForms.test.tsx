import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { api } from '@/lib/api'
import {
  adverseEventSchema,
  caseIntakeSchema,
  narrativeRevisionSchema,
  narrativeSchema,
  reasonForChangeSchema,
  seriousnessSchema,
} from '@/features/pv/forms/schemas'
import { CaseIntakeForm, NarrativeForm } from '@/features/pv/forms/PVForms'

describe('PV Zod pre-submission schemas', () => {
  it('requires a subject reference and case type for intake', () => {
    expect(caseIntakeSchema.safeParse({ subject_reference: 'S-1', case_type: 'AE' }).success).toBe(true)
    expect(caseIntakeSchema.safeParse({ subject_reference: '', case_type: 'AE' }).success).toBe(false)
  })

  it('bounds the verbatim term to 1-200 chars and rejects resolution before onset', () => {
    expect(
      adverseEventSchema.safeParse({ verbatim_term: 'Headache', onset_date: '2026-01-02', outcome: 'Recovered' })
        .success,
    ).toBe(true)
    expect(
      adverseEventSchema.safeParse({ verbatim_term: '', onset_date: '2026-01-02', outcome: 'Recovered' }).success,
    ).toBe(false)
    expect(
      adverseEventSchema.safeParse({ verbatim_term: 'x'.repeat(201), onset_date: '2026-01-02', outcome: 'Recovered' })
        .success,
    ).toBe(false)
    expect(
      adverseEventSchema.safeParse({
        verbatim_term: 'Headache',
        onset_date: '2026-01-10',
        outcome: 'Recovered',
        resolution_date: '2026-01-01',
      }).success,
    ).toBe(false)
  })

  it('requires at least one criterion when serious', () => {
    expect(seriousnessSchema.safeParse({ serious: false, criteria: [] }).success).toBe(true)
    expect(seriousnessSchema.safeParse({ serious: true, criteria: [] }).success).toBe(false)
    expect(seriousnessSchema.safeParse({ serious: true, criteria: ['death'] }).success).toBe(true)
  })

  it('bounds narrative text and requires a reason for change on revision', () => {
    expect(narrativeSchema.safeParse({ text: 'A narrative.' }).success).toBe(true)
    expect(narrativeSchema.safeParse({ text: '   ' }).success).toBe(false)
    expect(narrativeSchema.safeParse({ text: 'x'.repeat(20001) }).success).toBe(false)
    expect(reasonForChangeSchema.safeParse({ reason: '' }).success).toBe(false)
    expect(reasonForChangeSchema.safeParse({ reason: 'Corrected typo' }).success).toBe(true)
    expect(narrativeRevisionSchema.safeParse({ text: 'Updated', reason: 'Corrected typo' }).success).toBe(true)
    expect(narrativeRevisionSchema.safeParse({ text: 'Updated', reason: '' }).success).toBe(false)
  })
})

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('PV forms — API stays authoritative, no request on invalid input', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('does not send a create request when intake fails Zod validation', async () => {
    const post = vi.spyOn(api, 'post')
    renderWithClient(<CaseIntakeForm studyId="study-1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Create case' }))

    await waitFor(() => expect(screen.getByText('Subject reference is required')).toBeInTheDocument())
    expect(post).not.toHaveBeenCalled()
  })

  it('renders narrative controls disabled for a Closed case', () => {
    renderWithClient(<NarrativeForm caseId="case-1" disabled />)
    const textarea = screen.getByRole('textbox', { name: /Narrative/i })
    expect(textarea).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save narrative' })).toBeDisabled()
  })
})
