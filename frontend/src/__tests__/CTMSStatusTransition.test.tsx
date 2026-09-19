import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  CTMSStatusTransitionForm,
  createStatusTransitionSchema,
} from '@/features/ctms/forms'
import { getCTMSStatusTransitionInvalidationKeys } from '@/features/ctms/hooks'

describe('CTMS status transition flow', () => {
  const options = [
    { status: 'active', requires_reason: true, reason_label: 'Explain activation' },
    { status: 'paused', requires_reason: false },
  ] as const

  it('renders only server-returned statuses and requires a declared reason', async () => {
    const onTransition = vi.fn().mockResolvedValue({
      resource: { id: 'task-1' },
      current_status: 'active',
      allowed_transitions: [{ status: 'closed', requires_reason: true }],
    })
    render(<CTMSStatusTransitionForm currentStatus="draft" allowedTransitions={options} onTransition={onTransition} />)

    const select = screen.getByRole('combobox', { name: 'New status' })
    expect(screen.getByRole('option', { name: 'active' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'paused' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'closed' })).not.toBeInTheDocument()

    fireEvent.change(select, { target: { value: 'active' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status transition' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Explain activation' })).toHaveAttribute('aria-invalid', 'true'))
    expect(onTransition).not.toHaveBeenCalled()

    fireEvent.change(screen.getByRole('textbox', { name: 'Explain activation' }), { target: { value: 'Reviewed by operations' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status transition' }))
    await waitFor(() => expect(onTransition).toHaveBeenCalledWith({ status: 'active', reason: 'Reviewed by operations' }))
  })

  it('shows the committed current status and next server choices only after success', async () => {
    let resolveTransition: ((value: unknown) => void) | undefined
    const onTransition = vi.fn().mockImplementation(() => new Promise((resolve) => { resolveTransition = resolve }))
    render(<CTMSStatusTransitionForm currentStatus="draft" allowedTransitions={[{ status: 'active' }]} onTransition={onTransition} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'New status' }), { target: { value: 'active' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status transition' }))
    await waitFor(() => expect(onTransition).toHaveBeenCalled())
    expect(screen.getByTestId('ctms-current-status')).toHaveTextContent('draft')

    resolveTransition?.({
      resource: { id: 'task-1' },
      current_status: 'active',
      allowed_transitions: [{ status: 'closed' }],
    })
    await waitFor(() => expect(screen.getByTestId('ctms-current-status')).toHaveTextContent('active'))
    expect(screen.getByRole('option', { name: 'closed' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'active' })).not.toBeInTheDocument()
  })
})

describe('CTMS transition invalidation policy', () => {
  it('returns only affected CTMS resource keys', () => {
    const keys = getCTMSStatusTransitionInvalidationKeys('tasks', 'task-1', { studyId: 'study-1' })
    expect(keys).toEqual(expect.arrayContaining([
      ['ctms', 'tasks', 'detail', 'task-1', expect.anything()],
      ['ctms', 'tasks', 'study-1', expect.anything()],
      ['ctms', 'dashboard', 'study-1', expect.anything()],
    ]))
    expect(keys.some((key) => key[0] === 'edc')).toBe(false)
    expect(keys.some((key) => key[0] === 'ctms' && key[1] === 'projections')).toBe(false)
  })

  it('validates status against the server transition list', () => {
    const schema = createStatusTransitionSchema([{ status: 'active', requires_reason: false }])
    expect(schema.safeParse({ status: 'closed' }).success).toBe(false)
    expect(schema.safeParse({ status: 'active' }).success).toBe(true)
  })
})
