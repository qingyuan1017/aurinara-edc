import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CTMSStudyAreaPage } from '@/features/ctms/StudyAreaPage'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><CTMSStudyAreaPage studyId="study-1" title="Contract" description="Manage study contracts." resource="contract" /></QueryClientProvider>)
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: 'ctms-user-1',
      email: 'ctms@example.test',
      first_name: 'CTMS',
      last_name: 'Manager',
      roles: [{ role_name: 'CTMS_Operations_User' }],
      permissions: [PERMISSIONS.CTMS_OPERATIONAL_DATA_READ, PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT],
    },
    isAuthenticated: true,
  })
  vi.spyOn(api, 'get').mockResolvedValue({ data: { items: [], page: 1, page_size: 20, total: 0 } } as never)
})

afterEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, isAuthenticated: false })
})

describe('CTMS Study Area page', () => {
  it('keeps the record form out of the main panel and opens it in a right-side drawer', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'record-1' } } as never)
    renderPage()

    expect(await screen.findByText('No contract records configured yet')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Title *' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
    const drawer = screen.getByRole('dialog', { name: 'Add Contract' })
    fireEvent.change(within(drawer).getByRole('textbox', { name: 'Title *' }), { target: { value: 'Central agreement' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Add record' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/study-operations/contract', expect.objectContaining({ title: 'Central agreement', status: 'Draft' })))
  })
})
