import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { SignatureDialog, SignatureHistory } from '@/features/signatures'

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('electronic signature workflow', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({
      user: { id: 'user-1', email: 'pi@example.com', first_name: 'Principal', last_name: 'Investigator', roles: [], permissions: ['signature.sign', 'form.read'] },
      isAuthenticated: true,
    })
  })

  it('requires re-authentication and posts the form signature', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 'signature-1', object_type: 'form', object_id: 'form-1', status: 'valid', signed_by: 'user-1', signed_at: '2026-01-01T10:00:00Z', signature_meaning: 'I attest.', data_hash: 'a'.repeat(64) },
    } as never)
    const onSigned = vi.fn()

    renderWithQueryClient(<SignatureDialog objectType="form" objectId="form-1" onSigned={onSigned} />)
    fireEvent.click(screen.getByRole('button', { name: 'Sign form' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm signature' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Signature meaning is required')
    expect(post).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('Signature meaning'), { target: { value: 'I attest.' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'current-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm signature' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/form-instances/form-1/sign', {
      meaning: 'I attest.', password: 'current-password',
    }))
    expect(onSigned).toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('hides signing when the current user lacks signature permission', () => {
    useAuthStore.setState({ user: { id: 'user-1', email: 'reader@example.com', first_name: 'Read', last_name: 'Only', roles: [], permissions: ['form.read'] } })
    renderWithQueryClient(<SignatureDialog objectType="subject" objectId="subject-1" />)
    expect(screen.queryByRole('button', { name: 'Sign subject' })).not.toBeInTheDocument()
  })

  it('renders valid and stale signatures from the subject history endpoint', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: {
      items: [
        { id: 'signature-1', object_type: 'subject', object_id: 'subject-1', signed_by: 'user-1', signed_at: '2026-01-01T10:00:00Z', signature_meaning: 'Subject attestation', data_hash: 'a'.repeat(64), status: 'valid' },
        { id: 'signature-2', object_type: 'form', object_id: 'form-1', signed_by: 'user-1', signed_at: '2026-01-02T10:00:00Z', signature_meaning: 'Stale attestation', data_hash: 'b'.repeat(64), status: 'stale', stale_reason: 'Data corrected' },
      ], page: 1, page_size: 25, total: 2,
    } } as never)

    renderWithQueryClient(<SignatureHistory subjectId="subject-1" />)
    expect(await screen.findByText('Subject attestation')).toBeInTheDocument()
    expect(screen.getByText('Stale: Data corrected')).toBeInTheDocument()
    expect(screen.getByLabelText('signature status: valid')).toBeInTheDocument()
    expect(screen.getByLabelText('signature status: stale')).toBeInTheDocument()
  })
})
