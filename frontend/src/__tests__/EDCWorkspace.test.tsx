import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EDCWorkspacePage, FormStatusStrip, normalizeDataEntryStatus } from '@/features/edc'
import { api } from '@/lib/api'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

function renderPage(view: Parameters<typeof EDCWorkspacePage>[0]['view']) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <EDCWorkspacePage studyId="study-1" view={view} />
    </QueryClientProvider>,
  )
}

describe('EDC study workspaces', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders collection progress from the authoritative dashboard response', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        subject_counts_by_status: { Enrolled: 3, Screening: 1 },
        total_form_instances: 20,
        submitted_form_instances: 15,
        open_query_count: 2,
      },
    } as never)

    renderPage('overview-progress')

    expect(await screen.findByText('Data Collection Progress')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/studies/study-1/dashboard')
  })

  it('does not invent licensed terminology when medical coding is unavailable', () => {
    renderPage('meddra-coding')

    expect(screen.getByText('MedDRA Coding')).toBeInTheDocument()
    expect(screen.getByText(/No licensed MedDRA dictionary endpoint is configured/)).toBeInTheDocument()
    expect(screen.getByText('Backend capability required')).toBeInTheDocument()
  })

  it('renders query workload from the study query-metrics endpoint', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { open_count: 8, answered_count: 3, closed_count: 21, overdue_count: 2, average_days_open: 4.5 } } as never)

    renderPage('query-dashboard')

    expect(await screen.findByText('Query Dashboard')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/studies/study-1/query-metrics')
  })

  it('filters the form worklist independently by every displayed column', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        items: [
          {
            form_instance_id: 'form-instance-1',
            subject_id: 'subject-1',
            subject_number: 'SUBJ-001',
            site_name: 'North Clinic',
            visit_name: 'Screening',
            form_name: 'Demographics',
            status: { data_entry: 'In Progress', review: 'Not Reviewed', sdv: 'Not Verified', sdr: 'Pending', freeze: 'Inactive', lock: 'Inactive', signature: 'Missing', active_query_count: 2 },
          },
          {
            form_instance_id: 'form-instance-2',
            subject_id: 'subject-2',
            subject_number: 'SUBJ-002',
            site_name: 'South Clinic',
            visit_name: 'Baseline',
            form_name: 'Vital Signs',
            status: { data_entry: 'Draft', review: 'Reviewed', sdv: 'Verified', sdr: 'Complete', freeze: 'Inactive', lock: 'Inactive', signature: 'Missing', active_query_count: 0 },
          },
        ],
        page: 1,
        page_size: 100,
        total: 2,
      },
    } as never)

    renderPage('incomplete-forms')

    expect(await screen.findByText('SUBJ-001')).toBeInTheDocument()
    for (const name of ['site', 'subject', 'visit', 'form', 'entry', 'review', 'SDV', 'SDR', 'queries']) {
      expect(screen.getByLabelText(`Filter by ${name}`)).toBeInTheDocument()
    }

    fireEvent.change(screen.getByLabelText('Filter by subject'), { target: { value: '002' } })
    expect(screen.queryByText('SUBJ-001')).not.toBeInTheDocument()
    expect(screen.getByText('SUBJ-002')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Filter by review'), { target: { value: 'Not Reviewed' } })
    expect(screen.getByText('No forms match the current column filters.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Clear column filters' }))
    expect(screen.getByText('SUBJ-001')).toBeInTheDocument()
    expect(screen.getByText('SUBJ-002')).toBeInTheDocument()
  })

  it('presents form workflow dimensions independently', () => {
    render(<FormStatusStrip status={{
      dataEntry: normalizeDataEntryStatus('Submitted'),
      queries: 'Open',
      review: 'Reviewed',
      sdv: 'Partially Verified',
      signature: 'Unsigned',
      lock: 'Unlocked',
    }} />)

    expect(screen.getByLabelText('Data entry status: Complete')).toBeInTheDocument()
    expect(screen.getByLabelText('Queries status: Open')).toBeInTheDocument()
    expect(screen.getByLabelText('SDV status: Partially Verified')).toBeInTheDocument()
    expect(screen.getByLabelText('Lock status: Unlocked')).toBeInTheDocument()
  })
})
