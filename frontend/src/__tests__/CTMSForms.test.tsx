import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { describe, expect, it, vi } from 'vitest'
import {
  CTMSFormField,
  CTMSFormShell,
  fileMetadataSchema,
  mapCTMSServerErrors,
  ownedDateSchema,
  ownedQuantitySchema,
  transitionReasonSchema,
} from '@/features/ctms/forms'

describe('CTMS convenience schemas', () => {
  it('validates calendar dates and non-negative quantities without authorization rules', () => {
    expect(ownedDateSchema.safeParse('2026-02-28').success).toBe(true)
    expect(ownedDateSchema.safeParse('2026-02-30').success).toBe(false)
    expect(ownedQuantitySchema({ integer: true, min: 0 }).safeParse('4').success).toBe(true)
    expect(ownedQuantitySchema({ integer: true, min: 0 }).safeParse('-1').success).toBe(false)
  })

  it('validates operational file metadata and transition reasons', () => {
    expect(fileMetadataSchema.safeParse({ fileName: 'plan.pdf', contentType: 'application/pdf', sizeBytes: 10 }).success).toBe(true)
    expect(fileMetadataSchema.safeParse({ fileName: '../secret', contentType: 'text/plain', sizeBytes: 10 }).success).toBe(false)
    expect(transitionReasonSchema.safeParse('Updated after review').success).toBe(true)
    expect(transitionReasonSchema.safeParse('no').success).toBe(false)
  })
})

describe('CTMS server error mapping', () => {
  it('maps safe field errors without changing form values', () => {
    const setError = vi.fn()
    const result = mapCTMSServerErrors({
      response: {
        status: 422,
        data: {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Review the highlighted fields.',
            details: { fields: { name: ['Name is required'] }, stack: 'not rendered' },
          },
          request_id: 'req-123',
        },
      },
    }, setError)

    expect(setError).toHaveBeenCalledWith('name', { type: 'server', message: 'Name is required' })
    expect(result.error.requestId).toBe('req-123')
    expect(result.formMessage).toBeUndefined()
  })
})

function ExampleForm({ onCancel }: { onCancel: () => void }) {
  const methods = useForm<{ name: string }>({ defaultValues: { name: '' } })
  return (
    <CTMSFormShell
      methods={methods}
      title="Operational record"
      description="Only CTMS-owned values are submitted."
      onSubmit={vi.fn()}
      onCancel={onCancel}
      mutation={{ status: 'success', action: 'Save record' }}
    >
      <CTMSFormField control={methods.control} name="name" label="Name" required description="A CTMS-owned name." />
    </CTMSFormShell>
  )
}

describe('CTMS form components', () => {
  it('provides accessible field errors, focus, cancel, and mutation feedback', async () => {
    const onCancel = vi.fn()
    render(<ExampleForm onCancel={onCancel} />)

    const input = screen.getByRole('textbox', { name: 'Name' })
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(input).toHaveAccessibleDescription('A CTMS-owned name.')
    expect(input).toHaveAttribute('data-ctms-form-control', 'true')
    expect(input).toHaveClass('focus-visible:ring-ring')
    await waitFor(() => expect(input).toHaveFocus())

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(screen.getByRole('status')).toHaveTextContent('Save record completed successfully.')
  })

  it('focuses the first invalid field after submit', async () => {
    function RequiredForm() {
      const methods = useForm<{ name: string }>({
        defaultValues: { name: '' },
        resolver: zodResolver(z.object({ name: z.string().min(1, 'Name is required') })),
      })
      return (
        <CTMSFormShell methods={methods} title="Required form" onSubmit={vi.fn()}>
          <CTMSFormField control={methods.control} name="name" label="Name" required />
        </CTMSFormShell>
      )
    }
    render(<RequiredForm />)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Name' })).toHaveAttribute('aria-invalid', 'true'))
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveFocus()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
