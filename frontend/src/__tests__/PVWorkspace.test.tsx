import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { useStudyContext } from '@/lib/study-context'
import { PERMISSIONS } from '@/lib/permissions'
import { PV_CAPABILITY_CODES } from '@/features/pv'
import { PVWorkspacePage } from '@/features/pv/WorkspacePage'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  useSearch: () => ({}),
  useParams: () => ({ studyId: 'study-1' }),
}))

const enabledManifest = {
  module: 'PV' as const,
  enabled: true,
  phase: 3 as const,
  capabilities: Object.values(PV_CAPABILITY_CODES),
}

const disabledManifest = { module: 'PV' as const, enabled: false, phase: 0 as const, capabilities: [] }

const emptyList = { items: [], page: 1, page_size: 50, total: 0 }

function setUser(permissions: string[]) {
  useAuthStore.setState({
    user: {
      id: 'user-1',
      email: 'safety@example.com',
      first_name: 'Safety',
      last_name: 'User',
      roles: [{ role_name: 'Safety_Viewer' }],
      permissions,
    },
    isAuthenticated: true,
  })
}

function renderWithApi(ui: React.ReactNode, responseFactory: (path: string) => unknown) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.spyOn(api, 'get').mockImplementation((url) =>
    Promise.resolve({ data: responseFactory(String(url)) }) as never,
  )
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('PV workspace — permission-aware rendering and module states', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useStudyContext.setState({ selectedStudyId: 'study-1', selectedSiteId: null })
  })

  it('renders the safety cases workspace when ready and permitted', async () => {
    setUser([PERMISSIONS.PV_SAFETY_CASE_READ, PERMISSIONS.PV_SAFETY_CASE_ENTER])
    renderWithApi(<PVWorkspacePage view="cases" studyId="study-1" />, (path) => {
      if (path === '/pv/capabilities') return enabledManifest
      if (path.endsWith('/cases')) return emptyList
      return emptyList
    })

    expect(await screen.findByTestId('pv-workspace')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Safety cases' })).toBeInTheDocument()
  })

  it('renders an access-denied view when the user lacks the read permission', async () => {
    setUser([])
    renderWithApi(<PVWorkspacePage view="cases" studyId="study-1" />, (path) => {
      if (path === '/pv/capabilities') return enabledManifest
      return emptyList
    })

    expect(await screen.findByRole('heading', { name: 'Access Denied' })).toBeInTheDocument()
    expect(screen.queryByTestId('pv-workspace')).not.toBeInTheDocument()
  })

  it('shows a disabled state that points back to EDC when PV is disabled', async () => {
    setUser([PERMISSIONS.PV_SAFETY_CASE_READ])
    renderWithApi(<PVWorkspacePage view="cases" studyId="study-1" />, (path) => {
      if (path === '/pv/capabilities') return disabledManifest
      return emptyList
    })

    await waitFor(() =>
      expect(screen.getByText(/PV\/Safety module is disabled/i)).toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: /Return to EDC dashboard/i })).toBeInTheDocument()
    expect(screen.queryByTestId('pv-workspace')).not.toBeInTheDocument()
  })

  it('shows an unavailable state when the capability or worker request fails', async () => {
    setUser([PERMISSIONS.PV_SAFETY_CASE_READ])
    vi.spyOn(api, 'get').mockRejectedValue(new Error('worker unavailable'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <PVWorkspacePage view="cases" studyId="study-1" />
      </QueryClientProvider>,
    )

    expect(await screen.findByText(/PV safety data is temporarily unavailable/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Return to EDC dashboard/i })).toHaveAttribute('href', '/')
    expect(screen.queryByTestId('pv-workspace')).not.toBeInTheDocument()
  })
})
