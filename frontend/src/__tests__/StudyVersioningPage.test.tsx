import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StudyVersioningPage } from '@/features/studies/StudyVersioningPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, params, search, children, ...props }: { to: string; params?: Record<string, string>; search?: Record<string, string>; children: React.ReactNode; [key: string]: unknown }) => {
    const path = Object.entries(params ?? {}).reduce((value, [key, replacement]) => value.replace(`$${key}`, replacement), to)
    const query = search && Object.keys(search).length ? `?${new URLSearchParams(search).toString()}` : ''
    return <a href={`${path}${query}`} {...props}>{children}</a>
  },
}))

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
        permissions: ['designer.study_version.create', 'designer.study_version.amend', 'designer.study_version.read', 'designer.version.publish'],
      },
      isAuthenticated: true,
    })
  })

  it('uses the shared loading state while study and versions are pending', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined) as never)
    renderPage()
    expect(screen.getByRole('status', { name: 'Loading study versions…' })).toBeInTheDocument()
  })

  it('creates the initial EDC draft from the empty version state', async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'EDC-001', title: 'Example study', phase: 'II' } })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockResolvedValue({
      data: {
        id: 'version-1',
        study_id: 'study-1',
        version_number: '1.0',
        status: 'draft',
        created_at: '2026-10-10T12:00:00Z',
      },
    })
    renderPage()

    expect(await screen.findByText('No study versions found.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create amendment' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create initial draft' }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/designer/studies/study-1/versions', {
        version_number: '1.0',
      })
    })
    expect(await screen.findByText('Initial draft version 1.0 created.')).toBeInTheDocument()
  })

  it('does not offer initial draft creation without the required permission', async () => {
    useAuthStore.setState((state) => ({
      ...state,
      user: state.user ? { ...state.user, permissions: ['designer.study_version.read'] } : null,
    }))
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'EDC-001', title: 'Example study' } })
      return Promise.resolve({ data: [] })
    })

    renderPage()

    expect(await screen.findByText('A user with study-version creation permission must create the initial EDC draft.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create initial draft' })).not.toBeInTheDocument()
  })

  it('shows a sanitized error when initial draft creation fails', async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'EDC-001', title: 'Example study' } })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockRejectedValue(new Error('Could not create the initial draft.'))

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Create initial draft' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not create the initial draft.')
  })

  it('blocks publication until the aggregate design is ready', async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'EDC-001', title: 'Example study' } })
      if (url === '/designer/versions/version-1/validation') return Promise.resolve({ data: {
        version_id: 'version-1',
        valid: false,
        counts: { forms: 1, sections: 1, fields: 2, visits: 1, scheduled_form_mappings: 0, codelists: 0, codelist_items: 0, edit_checks: 0, subject_phases: 0 },
        issues: [{ code: 'FORM_NOT_SCHEDULED', severity: 'error', message: 'Form DM is not mapped to any visit.' }],
      } })
      return Promise.resolve({ data: [{ id: 'version-1', study_id: 'study-1', version_number: '1.0', status: 'draft', created_at: '2026-10-10T12:00:00Z' }] })
    })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Publish' }))

    expect(await screen.findByText('Form DM is not mapped to any visit.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish version' })).toBeDisabled()
    expect(api.post).not.toHaveBeenCalledWith('/designer/versions/version-1/publish')
  })

  it('opens each published version inside the Designer workspace', async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/studies/study-1') return Promise.resolve({ data: { id: 'study-1', study_code: 'EDC-001', title: 'Example study' } })
      return Promise.resolve({ data: [{ id: 'version-1', study_id: 'study-1', version_number: '1.0', status: 'published', published_at: '2026-10-10T12:00:00Z', created_at: '2026-10-10T10:00:00Z' }] })
    })

    renderPage()

    expect(await screen.findByRole('link', { name: 'View in Designer' })).toHaveAttribute('href', '/studies/study-1/designer/forms?design_version_id=version-1')
  })
})
