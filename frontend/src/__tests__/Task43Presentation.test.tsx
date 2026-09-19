import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { LoginPage } from '@/features/auth/LoginPage'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { AcceptInvitationPage } from '@/features/auth/AcceptInvitationPage'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { ExportCenterPage } from '@/features/exports/ExportCenterPage'
import { EditCheckBuilderPage } from '@/features/edit-checks/EditCheckBuilderPage'

const { mockNavigate, mockSearch } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockSearch: vi.fn(() => ({})),
}))

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => mockNavigate,
  useSearch: () => mockSearch(),
}))

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function setUser(permissions: string[] = []) {
  useAuthStore.setState({
    user: { id: 'user-1', email: 'user@example.com', first_name: 'Test', last_name: 'User', roles: [], permissions },
    isAuthenticated: true,
  })
}

describe('task 4.3 public page composition', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockNavigate.mockReset()
    mockSearch.mockReturnValue({})
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('uses shared form fields on the login page without changing its public links', () => {
    render(<LoginPage />)

    expect(screen.getByRole('heading', { name: 'Sign In' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Email/)).toHaveAttribute('autocomplete', 'email')
    expect(screen.getByLabelText(/^Password/)).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByRole('link', { name: 'Forgot your password?' })).toHaveAttribute('href', '/forgot-password')
  })

  it('preserves the forgot-password endpoint and enumeration-safe success state', async () => {
    const post = vi.spyOn(api, 'post').mockRejectedValue(new Error('network failure'))
    render(<ForgotPasswordPage />)

    fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'user@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/auth/forgot-password', { email: 'user@example.com' }))
    expect(await screen.findByRole('status')).toHaveTextContent('If an account with that email exists')
  })

  it('preserves reset and invitation payloads while using shared pending controls', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    mockSearch.mockReturnValue({ token: 'reset-token' })
    const { rerender } = render(<ResetPasswordPage />)

    fireEvent.change(screen.getByLabelText(/New Password/), { target: { value: 'new-password' } })
    fireEvent.change(screen.getByLabelText(/Confirm Password/), { target: { value: 'new-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/auth/reset-password', { token: 'reset-token', new_password: 'new-password' }))

    mockSearch.mockReturnValue({ token: 'invite-token' })
    rerender(<AcceptInvitationPage />)
    fireEvent.change(screen.getByLabelText(/^First Name/), { target: { value: 'Ada' } })
    fireEvent.change(screen.getByLabelText(/^Last Name/), { target: { value: 'Lovelace' } })
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: 'new-password' } })
    fireEvent.change(screen.getByLabelText(/Confirm Password/), { target: { value: 'new-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/auth/invite/accept', {
      token: 'invite-token',
      password: 'new-password',
      first_name: 'Ada',
      last_name: 'Lovelace',
    }))
  })

  it('keeps invalid reset and invitation links actionable without making API calls', () => {
    const post = vi.spyOn(api, 'post')
    const { rerender } = render(<ResetPasswordPage />)
    expect(screen.getByRole('heading', { name: 'Invalid Link' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Request a new reset link' })).toHaveAttribute('href', '/forgot-password')

    rerender(<AcceptInvitationPage />)
    expect(screen.getByRole('heading', { name: 'Invalid Invitation' })).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('preserves access-denied semantics and dashboard navigation', () => {
    render(<AccessDeniedPage />)
    expect(screen.getByRole('heading', { name: 'Access Denied' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Return to Dashboard' }))
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/' })
  })
})

describe('task 4.3 export and edit-check composition', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockNavigate.mockReset()
    setUser([PERMISSIONS.DATA_EXPORT, PERMISSIONS.EDITCHECK_CONFIGURE])
  })

  it('preserves export status labels, completed downloads, and create payloads', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{ id: 'export-1', format: 'csv', status: 'completed', filters: {}, created_at: '2026-01-01T10:00:00Z', completed_at: '2026-01-01T10:01:00Z' }],
        page: 1,
        page_size: 20,
        total: 1,
      },
    } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    renderWithQueryClient(<ExportCenterPage studyId="study-1" />)

    expect(await screen.findByRole('status', { name: 'Export status: completed' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download' }))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/exports/export-1/download'))
    expect(open).toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Create Export' }))
    fireEvent.change(screen.getByLabelText('Site Filter (optional)'), { target: { value: 'site-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start Export' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/exports', { format: 'csv', filters: { site_id: 'site-1' } }))
  })

  it('preserves edit-check JSON validation and clinical validation payloads', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: [] } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {
      id: 'check-1', name: 'Required weight', description: null, rule_json: { field: 'weight', operator: 'not_null' }, severity: 'warning', is_active: true, created_at: '2026-01-01T10:00:00Z',
    } } as never)
    renderWithQueryClient(<EditCheckBuilderPage studyId="study-1" />)

    expect(await screen.findByRole('heading', { name: 'Edit-check builder' })).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('AE start before end'), { target: { value: 'Required weight' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Rule definition' }), { target: { value: '{invalid' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save check' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Rule JSON must be valid JSON.')
    expect(post).not.toHaveBeenCalled()

    fireEvent.change(screen.getByRole('textbox', { name: 'Rule definition' }), { target: { value: '{"field":"weight","operator":"not_null"}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save check' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/studies/study-1/edit-checks', {
      name: 'Required weight', description: null, severity: 'warning', rule_json: { field: 'weight', operator: 'not_null' }, is_active: true,
    }))
    expect(get).toHaveBeenCalledWith('/studies/study-1/edit-checks')
  })
})
