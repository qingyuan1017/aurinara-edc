import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CTMSStudyCompletionPage } from '@/features/ctms'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...props }: { to: string; children: React.ReactNode }) => <a href={to} {...props}>{children}</a>,
}))

function renderPage(view: Parameters<typeof CTMSStudyCompletionPage>[0]['view']) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <CTMSStudyCompletionPage studyId="study-1" view={view} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: 'study-user',
      email: 'study@example.test',
      first_name: 'Study',
      last_name: 'Manager',
      roles: [{ role_name: 'CTMS_Operations_User', study_id: 'study-1' }],
      permissions: [
        PERMISSIONS.CTMS_OPERATIONAL_DATA_READ,
        PERMISSIONS.CTMS_OPERATIONAL_STUDY_MANAGEMENT,
        PERMISSIONS.CTMS_OPERATIONAL_SITE_MANAGEMENT,
        PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT,
      ],
    },
    isAuthenticated: true,
  })
})

afterEach(() => vi.restoreAllMocks())

describe('CTMS study completion workspace', () => {
  it('loads the dashboard from one study summary without list fan-out', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        study_id: 'study-1', site_count: 4, active_sites: 3,
        enrollment: { targets: { subjects: 100 }, operational_subjects: 25 },
        monitoring: { visits: 8, overdue_visits: 1, open_findings: 2 },
        work: { total: 5, open: 3, overdue: 1 }, capas: { open: 1 },
        contracts: { total: 2 },
        financials_by_currency: [{ currency: 'USD', approved_budget: 500, paid: 100 }],
        generated_at: '2026-10-13T12:00:00Z',
      },
    } as never)

    renderPage('summary')

    expect(await screen.findByRole('heading', { name: 'Study Dashboard' })).toBeInTheDocument()
    expect(await screen.findByText(/"currency":"USD"/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledTimes(1)
    expect(String(get.mock.calls[0][0])).toBe('/ctms/studies/study-1/summary')
  })

  it('requires a reason in the lifecycle transition dialog', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [{
          id: 'ract-1', name: 'Initial RACT', status: 'Draft', version: 1,
          destination_path: '/studies/study-1/ctms/monitoring/ract',
        }],
        page: 1, page_size: 25, total: 1,
      },
    } as never)
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderPage('ract')
    fireEvent.click((await screen.findAllByRole('button', { name: 'Change status' }))[0])

    const apply = screen.getByRole('button', { name: 'Apply transition' })
    expect(apply).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Assessment ready' } })
    fireEvent.click(apply)

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        '/ctms/studies/study-1/risk-assessments/ract-1/transition',
        { status: 'Under Review', reason: 'Assessment ready', expected_version: 1 },
      )
    })
  })

  it('adds an available Site from the Study Site List with a study-specific ID', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      const path = String(url)
      if (path.includes('/available-entities')) {
        return Promise.resolve({
          data: {
            items: [{
              id: '44444444-4444-4444-8444-444444444444',
              entity_type: 'site',
              code: 'GENERAL-HOSPITAL',
              name: 'General Hospital',
              attributes: { country: 'US', state: 'New York', city: 'New York' },
              active: true,
            }],
            page: 1, page_size: 100, total: 1,
          },
        }) as never
      }
      return Promise.resolve({ data: { items: [], page: 1, page_size: 25, total: 0 } }) as never
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)

    renderPage('sites')
    fireEvent.click(await screen.findByRole('button', { name: 'Add Site' }))
    expect(await screen.findByRole('option', { name: 'General Hospital' })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: /Available site/i }), {
      target: { value: '44444444-4444-4444-8444-444444444444' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Site number' }), {
      target: { value: 'SITE-101' },
    })
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Add Site' })).getByRole('button', { name: 'Add Site' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/sites', {
      entity_id: '44444444-4444-4444-8444-444444444444',
      site_number: 'SITE-101',
    }))
  })
})
