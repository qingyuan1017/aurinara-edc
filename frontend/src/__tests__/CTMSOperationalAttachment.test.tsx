import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import {
  isCTMSOperationalAttachmentParent,
  validateCTMSAttachmentMetadata,
  type CTMSAttachment,
  type CTMSAttachmentConstraints,
} from '@/features/ctms/api'
import { OperationalAttachmentPanel } from '@/features/ctms/components'

const constraints: CTMSAttachmentConstraints = {
  max_size_bytes: 10_000,
  allowed_content_types: ['application/pdf'],
  allowed_object_types: ['operational_task'],
  ownership: 'CTMS',
  attachment_type: 'Operational_Attachment',
}

const attachment: CTMSAttachment = {
  id: 'attachment-1',
  module: 'CTMS',
  attachment_type: 'Operational_Attachment',
  object_type: 'operational_task',
  object_id: 'task-1',
  study_id: 'study-1',
  filename: 'evidence.pdf',
  content_type: 'application/pdf',
  size_bytes: 100,
  uploaded_at: '2026-03-01T10:00:00Z',
  retention_until: '2027-03-01T10:00:00Z',
}

function setUser(permissions: string[]) {
  useAuthStore.setState({
    user: { id: 'user-1', email: 'user@example.com', first_name: 'CTMS', last_name: 'User', roles: [], permissions },
    isAuthenticated: true,
  })
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof OperationalAttachmentPanel>> = {}) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <OperationalAttachmentPanel studyId="study-1" objectType="operational_task" objectId="task-1" constraints={constraints} {...overrides} />
    </QueryClientProvider>,
  )
}

describe('CTMS operational attachment lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setUser([PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT])
  })

  it('validates server-provided type and size constraints and rejects clinical parents', () => {
    expect(validateCTMSAttachmentMetadata(new File(['x'], 'evidence.pdf', { type: 'application/pdf' }), constraints)).toBeUndefined()
    expect(validateCTMSAttachmentMetadata(new File(['x'], 'evidence.txt', { type: 'text/plain' }), constraints)).toContain('not permitted')
    expect(validateCTMSAttachmentMetadata(new File(['12345678901'], 'evidence.pdf', { type: 'application/pdf' }), { ...constraints, max_size_bytes: 10 })).toContain('exceeds')
    expect(isCTMSOperationalAttachmentParent('operational_task')).toBe(true)
    expect(isCTMSOperationalAttachmentParent('clinical_attachment')).toBe(false)
    expect(isCTMSOperationalAttachmentParent('study')).toBe(false)
  })

  it('keeps clinical attachment controls unavailable and renders only safe operational metadata', () => {
    renderPanel({ objectType: 'study', attachments: [{ ...attachment, object_type: 'study', attachment_type: 'Clinical_Attachment', module: 'EDC' }] })
    expect(screen.getByRole('note')).toHaveTextContent(/not available for this record type/i)
    expect(screen.queryByLabelText(/choose an operational attachment/i)).not.toBeInTheDocument()
    expect(screen.queryByText('evidence.pdf')).not.toBeInTheDocument()
  })

  it('requires an audited reason in the shared confirmation dialog before lifecycle changes', async () => {
    const remove = vi.spyOn(api, 'delete').mockResolvedValue({ data: { ...attachment, deleted_at: '2026-03-02T10:00:00Z', retention_state: 'soft_deleted' } } as never)
    renderPanel({ attachments: [attachment] })

    fireEvent.click(screen.getByRole('button', { name: 'Delete operational attachment' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm delete' })).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))
    expect(screen.getByRole('alert')).toHaveTextContent('A reason is required')
    fireEvent.change(screen.getByRole('textbox', { name: /Delete reason/ }), { target: { value: 'Retention review completed.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))

    await waitFor(() => expect(remove).toHaveBeenCalledWith('/files/attachment-1', { data: { reason: 'Retention review completed.' } }))
    expect(screen.getByText('Update operational attachment completed successfully.')).toBeInTheDocument()
  })

  it('uploads with progress and renders retention state without caching file bytes', async () => {
    const post = vi.spyOn(api, 'post').mockImplementation(async (path, _body, config) => {
      if (String(path).includes('/files')) {
        const progress = config as { onUploadProgress?: (event: { loaded: number; total?: number }) => void }
        progress.onUploadProgress?.({ loaded: 50, total: 100 })
        return { data: attachment } as never
      }
      return { data: attachment } as never
    })
    renderPanel({ attachments: [attachment] })
    const file = new File(['evidence'], 'evidence.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText(/choose an operational attachment/i), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload operational attachment' }))
    expect(await screen.findByText(/Retained until/)).toBeInTheDocument()
    await waitFor(() => expect(post).toHaveBeenCalledWith('/objects/operational_task/task-1/files', expect.any(FormData), expect.objectContaining({ onUploadProgress: expect.any(Function) })))
    expect(screen.getByText(/CTMS Operational_Attachment/)).toBeInTheDocument()
    expect(screen.queryByText('evidence')).not.toBeInTheDocument()
  })
})
