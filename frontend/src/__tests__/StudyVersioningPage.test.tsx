import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StudyVersioningPage } from '@/features/studies/StudyVersioningPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StudyVersioningPage studyId="study-1" />
    </QueryClientProvider>,
  )
}

describe('StudyVersioningPage shared composition', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      user: {
        id: 'user-1',
        email: 'manager@example.com',
        first_name: 'Study',
        last_name: 'Manager',
        roles: [],
        permissions: ['study.configure', 'version.publish'],
      },
      isAuthenticated: true,
    })
  })

  it('uses the shared loading state while study and versions are pending', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined) as never)
    renderPage()
    expect(screen.getByRole('status', { name: 'Loading study versions…' })).toBeInTheDocument()
  })

  it('renders the shared empty table state and accessible amendment dialog', async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'EDC-001', title: 'Example study', phase: 'II' } })
      return Promise.resolve({ data: [] })
    })
    renderPage()

    expect(await screen.findByText('No study versions found.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create amendment' }))
    expect(screen.getByRole('dialog', { name: 'Create study amendment' })).toBeInTheDocument()
    expect(screen.getByLabelText('Amendment reason')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Create study amendment' })).not.toBeInTheDocument())
  })
})
