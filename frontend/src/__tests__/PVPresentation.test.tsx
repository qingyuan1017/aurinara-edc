import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import {
  AdverseEventForm,
  CaseIntakeForm,
  NarrativeRevisionForm,
  SeriousnessForm,
} from '@/features/pv/forms/PVForms'
import { reasonForChangeSchema } from '@/features/pv/forms/schemas'
import { PVHistoryDialog, PVSourceLabel, PVStatus } from '@/features/pv/components'
import type { PVCaseNarrative } from '@/features/pv/api'

/**
 * Complements PVForms/PVWorkspace/PVRoutes/PVCapabilities tests for task 7.5.
 * Focus: consistent status labels across list AND detail views (PVStatus),
 * Reason_For_Change enforcement, disabled controls on Closed cases across the
 * full form set, and audit/narrative history dialogs keeping the originating
 * status view mounted (PVHistoryDialog).
 * Validates: Requirements 19.1, 19.3, 19.4, 19.5, 23.10.
 */

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('PVStatus renders one textual status value identically (19.1)', () => {
  it('emits the exact server status text and an accessible label wherever it is used', () => {
    // Same component drives list cells and detail cards, so the visible text and
    // the data-status carry the identical value regardless of the view.
    render(
      <div>
        <span data-testid="list">
          <PVStatus status="In Review" label="Case status" />
        </span>
        <span data-testid="detail">
          <PVStatus status="In Review" label="Case status" />
        </span>
      </div>,
    )
    const badges = screen.getAllByRole('status')
    expect(badges).toHaveLength(2)
    for (const badge of badges) {
      expect(badge).toHaveTextContent('In Review')
      expect(badge).toHaveAttribute('data-status', 'In Review')
      expect(badge).toHaveAttribute('aria-label', 'Case status: In Review')
    }
    // The two renderings are textually identical (list == detail).
    const [list, detail] = badges
    expect(list.textContent).toBe(detail.textContent)
  })

  it.each([
    ['Serious', 'Seriousness'],
    ['Superseded', 'Coding status'],
    ['Pending', 'Report status'],
    ['Discrepancy', 'Reconciliation status'],
  ])('passes through the "%s" state verbatim without normalization', (status, label) => {
    render(<PVStatus status={status} label={label} />)
    const badge = screen.getByRole('status')
    expect(badge).toHaveTextContent(status)
    expect(badge).toHaveAttribute('data-status', status)
  })

  it('marks a projected field as read-only source content, never PV-authoritative', () => {
    render(<PVSourceLabel source="EDC" />)
    expect(screen.getByText(/EDC · read-only/i)).toBeInTheDocument()
  })
})

describe('Reason_For_Change enforcement before edits reach the API (19.3)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('bounds the reason to non-empty and at most 4,000 characters', () => {
    expect(reasonForChangeSchema.safeParse({ reason: '' }).success).toBe(false)
    expect(reasonForChangeSchema.safeParse({ reason: '   ' }).success).toBe(false)
    expect(reasonForChangeSchema.safeParse({ reason: 'x'.repeat(4000) }).success).toBe(true)
    expect(reasonForChangeSchema.safeParse({ reason: 'x'.repeat(4001) }).success).toBe(false)
  })

  it('sends no revision request when the reason for change is blank', async () => {
    const put = vi.spyOn(api, 'put')
    const patch = vi.spyOn(api, 'patch')
    const post = vi.spyOn(api, 'post')
    const narrative: PVCaseNarrative = {
      id: 'nar-1',
      case_id: 'case-1',
      text: 'Original narrative text.',
    } as PVCaseNarrative

    renderWithClient(<NarrativeRevisionForm caseId="case-1" narrative={narrative} />)

    // Change the narrative text but leave the reason empty, then submit.
    const textarea = screen.getByRole('textbox', { name: /Narrative/i })
    fireEvent.change(textarea, { target: { value: 'Revised narrative text.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save revision' }))

    await waitFor(() =>
      expect(screen.getByText('A reason for change is required')).toBeInTheDocument(),
    )
    expect(put).not.toHaveBeenCalled()
    expect(patch).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })
})

describe('Closed cases render input controls disabled (19.4)', () => {
  const narrative: PVCaseNarrative = {
    id: 'nar-1',
    case_id: 'case-1',
    text: 'Original narrative text.',
  } as PVCaseNarrative

  it('disables case intake controls when disabled is set', () => {
    renderWithClient(<CaseIntakeForm studyId="study-1" disabled />)
    for (const control of document.querySelectorAll('[data-pv-form-control]')) {
      expect(control).toBeDisabled()
    }
    expect(screen.getByRole('button', { name: 'Create case' })).toBeDisabled()
  })

  it('disables adverse-event controls on a Closed case', () => {
    renderWithClient(<AdverseEventForm caseId="case-1" disabled />)
    for (const control of document.querySelectorAll('[data-pv-form-control]')) {
      expect(control).toBeDisabled()
    }
    expect(screen.getByRole('button', { name: 'Save adverse event' })).toBeDisabled()
  })

  it('disables the seriousness assessment controls on a Closed case', () => {
    renderWithClient(<SeriousnessForm aeId="ae-1" caseId="case-1" disabled />)
    expect(screen.getByRole('checkbox', { name: 'Serious' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'death' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save assessment' })).toBeDisabled()
  })

  it('disables the narrative revision controls (text and reason) on a Closed case', () => {
    renderWithClient(<NarrativeRevisionForm caseId="case-1" narrative={narrative} disabled />)
    for (const control of document.querySelectorAll('[data-pv-form-control]')) {
      expect(control).toBeDisabled()
    }
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled()
  })
})

describe('History dialogs keep the originating status view mounted (19.5)', () => {
  it('does not unmount the surrounding status view when the dialog opens or closes', async () => {
    render(
      <section>
        <div data-testid="status-view">
          <PVStatus status="Reported" label="Case status" />
          <PVHistoryDialog
            title="Case audit history"
            description="Immutable PV safety audit events for this case."
            triggerLabel="View audit history"
          >
            <p>Audit event content</p>
          </PVHistoryDialog>
        </div>
      </section>,
    )

    // Status view + trigger are visible before opening; dialog content is not.
    expect(screen.getByTestId('status-view')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Reported')
    const trigger = screen.getByRole('button', { name: 'View audit history' })
    expect(screen.queryByText('Audit event content')).not.toBeInTheDocument()

    // Open the dialog: the status view and trigger remain mounted alongside it.
    fireEvent.click(trigger)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Audit event content')).toBeInTheDocument()
    expect(screen.getByTestId('status-view')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Reported')
    expect(screen.getByRole('button', { name: 'View audit history' })).toBeInTheDocument()

    // Close the dialog: the status view is still mounted and visible.
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByTestId('status-view')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Reported')
  })

  it('never renders history content before the dialog is opened', () => {
    render(
      <PVHistoryDialog title="Narrative history" triggerLabel="View history">
        <p>Prior narrative version</p>
      </PVHistoryDialog>,
    )
    expect(screen.queryByText('Prior narrative version')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View history' })).toBeInTheDocument()
  })
})
