import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ReasonForChangeDialog } from '@/features/forms/components/ReasonForChangeDialog'

describe('ReasonForChangeDialog', () => {
  const defaultProps = {
    open: true,
    fieldLabel: 'Systolic Blood Pressure',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  }

  it('renders nothing when open is false', () => {
    const { container } = render(
      <ReasonForChangeDialog {...defaultProps} open={false} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders the dialog with the field label when open', () => {
    render(<ReasonForChangeDialog {...defaultProps} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/Systolic Blood Pressure/)).toBeInTheDocument()
  })

  it('shows an error when confirming with an empty reason', () => {
    render(<ReasonForChangeDialog {...defaultProps} />)
    fireEvent.click(screen.getByText('Confirm Change'))
    expect(screen.getByRole('alert')).toHaveTextContent('A reason for change is required.')
    expect(defaultProps.onConfirm).not.toHaveBeenCalled()
  })

  it('shows an error when reason is too short (less than 3 chars)', () => {
    render(<ReasonForChangeDialog {...defaultProps} />)
    const textarea = screen.getByPlaceholderText(/Enter your reason/)
    fireEvent.change(textarea, { target: { value: 'ab' } })
    fireEvent.click(screen.getByText('Confirm Change'))
    expect(screen.getByRole('alert')).toHaveTextContent('Reason must be at least 3 characters.')
    expect(defaultProps.onConfirm).not.toHaveBeenCalled()
  })

  it('calls onConfirm with the trimmed reason when valid', () => {
    const onConfirm = vi.fn()
    render(<ReasonForChangeDialog {...defaultProps} onConfirm={onConfirm} />)
    const textarea = screen.getByPlaceholderText(/Enter your reason/)
    fireEvent.change(textarea, { target: { value: '  Data entry error  ' } })
    fireEvent.click(screen.getByText('Confirm Change'))
    expect(onConfirm).toHaveBeenCalledWith('Data entry error')
  })

  it('calls onCancel when Cancel button is clicked', () => {
    const onCancel = vi.fn()
    render(<ReasonForChangeDialog {...defaultProps} onCancel={onCancel} />)
    fireEvent.click(screen.getByText('Cancel'))
    expect(onCancel).toHaveBeenCalled()
  })

  it('calls onCancel when Escape key is pressed', () => {
    const onCancel = vi.fn()
    render(<ReasonForChangeDialog {...defaultProps} onCancel={onCancel} />)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onCancel).toHaveBeenCalled()
  })
})
