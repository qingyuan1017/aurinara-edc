import { useRef, useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FormActions, FormField, ConfirmDialog, MutationFeedback } from '@/components/patterns'
import { Input } from '@/components/ui/input'

function ConfirmHarness({ onConfirm = vi.fn(), onCancel = vi.fn() }: { onConfirm?: (reason?: string) => void; onCancel?: () => void }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>Open confirmation</button>
      <ConfirmDialog
        open={open}
        title="Delete record"
        description="This action requires confirmation."
        requireReason
        onConfirm={onConfirm}
        onCancel={onCancel}
        onOpenChange={setOpen}
        returnFocusRef={triggerRef}
      />
    </>
  )
}

describe('shared migrated form and dialog patterns', () => {
  it('associates labels, descriptions, and RHF/Zod-style errors with a control', () => {
    render(
      <FormField name="email" label="Email" description="Use your work email." error={{ type: 'required', message: 'Email is required' }} required>
        <Input type="email" />
      </FormField>,
    )

    const input = screen.getByRole('textbox', { name: /email/i })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-required', 'true')
    expect(input).toHaveAttribute('aria-describedby', expect.stringContaining('description'))
    expect(input).toHaveAttribute('aria-describedby', expect.stringContaining('error'))
    expect(screen.getByRole('alert')).toHaveTextContent('Email is required')
  })

  it('prevents duplicate submit activation while pending and exposes a status', async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <FormActions pending submitLabel="Save" pendingLabel="Saving record…" />
      </form>,
    )

    const submit = screen.getByRole('button', { name: 'Saving record…' })
    expect(submit).toBeDisabled()
    fireEvent.click(submit)
    fireEvent.click(submit)
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Do not submit again')
  })

  it('validates a required confirmation reason and submits only the trimmed value', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(<ConfirmHarness onConfirm={onConfirm} />)

    const trigger = screen.getByRole('button', { name: 'Open confirmation' })
    await user.click(trigger)
    const reason = await screen.findByRole('textbox', { name: /reason/i })
    expect(reason).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(screen.getByRole('alert')).toHaveTextContent('A reason is required')
    expect(onConfirm).not.toHaveBeenCalled()

    await user.type(reason, '  Approved by reviewer  ')
    await user.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(onConfirm).toHaveBeenCalledWith('Approved by reviewer')
  })

  it('keeps confirmation blocked for permission and re-authentication requirements', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    function BlockedDialog() {
      const [open, setOpen] = useState(true)
      return (
        <ConfirmDialog
          open={open}
          title="Lock form"
          permissionAllowed={false}
          permissionMessage="Permission is required."
          requiresReauthentication
          reauthenticationMessage="Sign in again to continue."
          onConfirm={onConfirm}
          onOpenChange={setOpen}
        />
      )
    }

    render(<BlockedDialog />)
    expect(screen.getByRole('status')).toHaveTextContent('Permission is required')
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()
    await user.click(confirm)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it.each([
    ['403', { response: { status: 403, data: { detail: 'You are not authorized for this action.' } } }, 'You are not authorized for this action.'],
    ['409', { response: { status: 409, data: { error: { code: 'CONFLICT', message: 'The record changed on the server.' } } } }, 'The record changed on the server.'],
    ['422', { response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: 'Review the highlighted fields.' } } } }, 'Review the highlighted fields.'],
    ['network', new Error('The CTMS service is unavailable.'), 'The CTMS service is unavailable.'],
  ])('renders sanitized %s mutation errors', (_label, error, expected) => {
    render(<MutationFeedback status="error" action="Save record" error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent(expected)
    expect(screen.getByRole('alert')).not.toHaveTextContent('stack')
  })

  it('announces pending and successful outcomes without changing mutation ownership', () => {
    const { rerender } = render(<MutationFeedback status="pending" action="Save record" />)
    expect(screen.getByRole('status')).toHaveTextContent('Do not submit it again')

    rerender(<MutationFeedback status="success" action="Save record" data={{ request_id: 'req-123' }} />)
    expect(screen.getByRole('status')).toHaveTextContent('Save record completed successfully')
    expect(screen.getByRole('status')).toHaveTextContent('Request ID req-123')
  })

  it('returns focus to the invoking control after cancellation', async () => {
    const user = userEvent.setup()
    render(<ConfirmHarness />)
    const trigger = screen.getByRole('button', { name: 'Open confirmation' })
    await user.click(trigger)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(trigger).toHaveFocus())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
