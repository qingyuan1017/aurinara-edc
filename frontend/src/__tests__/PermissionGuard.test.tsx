import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAuthStore } from '@/lib/auth'
import { PermissionGuard } from '@/components/guards/PermissionGuard'

// Mock TanStack Router's useNavigate used by AccessDeniedPage
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}))

describe('PermissionGuard', () => {
  beforeEach(() => {
    // Reset auth store between tests
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  it('renders children when user has the required permission', () => {
    useAuthStore.setState({
      user: {
        id: '1',
        email: 'user@example.com',
        first_name: 'Test',
        last_name: 'User',
        roles: [],
        permissions: ['form.enter'],
      },
      isAuthenticated: true,
    })

    render(
      <PermissionGuard permission="form.enter">
        <div data-testid="protected-content">Protected Content</div>
      </PermissionGuard>,
    )

    expect(screen.getByTestId('protected-content')).toBeInTheDocument()
  })

  it('renders AccessDenied when user lacks the required permission', () => {
    useAuthStore.setState({
      user: {
        id: '1',
        email: 'user@example.com',
        first_name: 'Test',
        last_name: 'User',
        roles: [],
        permissions: ['study.read'],
      },
      isAuthenticated: true,
    })

    render(
      <PermissionGuard permission="form.enter">
        <div data-testid="protected-content">Protected Content</div>
      </PermissionGuard>,
    )

    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument()
    expect(screen.getByText('Access Denied')).toBeInTheDocument()
  })

  it('does not flatten a study-scoped permission into another study', () => {
    useAuthStore.setState({
      user: {
        id: '1',
        email: 'user@example.com',
        first_name: 'Study',
        last_name: 'User',
        permissions: [],
        roles: [{
          role_name: 'Data Entry',
          study_id: 'study-a',
          permissions: ['form.enter'],
        }],
      },
      isAuthenticated: true,
    })

    const { rerender } = render(
      <PermissionGuard permission="form.enter" studyId="study-a">
        <div data-testid="protected-content">Protected Content</div>
      </PermissionGuard>,
    )
    expect(screen.getByTestId('protected-content')).toBeInTheDocument()

    rerender(
      <PermissionGuard permission="form.enter" studyId="study-b">
        <div data-testid="protected-content">Protected Content</div>
      </PermissionGuard>,
    )
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument()
  })

  it('renders AccessDenied when user is null (unauthenticated)', () => {
    useAuthStore.setState({ user: null, isAuthenticated: false })

    render(
      <PermissionGuard permission="form.enter">
        <div data-testid="protected-content">Protected Content</div>
      </PermissionGuard>,
    )

    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument()
    expect(screen.getByText('Access Denied')).toBeInTheDocument()
  })
})
