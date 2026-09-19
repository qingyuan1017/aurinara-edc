import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import { OperationalMilestoneForm, EnrollmentTargetForm, OperationalStudyForm, StudyPlanForm } from '@/features/ctms/forms'

const statusOptions = [{ value: 'Draft' }, { value: 'Active' }]

function renderForm(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, isAuthenticated: false })
})

describe('CTMS operational forms', () => {
  it('submits a study profile scoped by the canonical Study ID and invalidates CTMS keys', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'profile-1', study_id: 'study-1' } } as never)
    renderForm(<OperationalStudyForm studyId="study-1" statusOptions={statusOptions} />)

    fireEvent.change(screen.getByRole('textbox', { name: 'Operational sponsor' }), { target: { value: 'Operations sponsor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create profile' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/operational-profile', expect.objectContaining({ sponsor: 'Operations sponsor' })))
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('study_id')
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('subject_id')
  })

  it('preserves entered values and maps a safe server validation error', async () => {
    vi.spyOn(api, 'post').mockRejectedValue({ response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: 'Review fields.', details: { fields: { sponsor: ['Sponsor is not allowed'] } } }, request_id: 'req-form-1' } } })
    renderForm(<OperationalStudyForm studyId="study-1" />)

    const sponsor = screen.getByRole('textbox', { name: 'Operational sponsor' })
    fireEvent.change(sponsor, { target: { value: 'Entered sponsor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create profile' }))

    await waitFor(() => expect(screen.getAllByRole('alert').some((alert) => alert.textContent?.includes('Sponsor is not allowed'))).toBe(true))
    expect(sponsor).toHaveValue('Entered sponsor')
    expect(screen.getAllByRole('alert').some((alert) => alert.textContent?.includes('req-form-1'))).toBe(true)
  })

  it('keeps plan payloads operational and updates by CTMS plan ID', async () => {
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: { id: 'plan-1', study_id: 'study-1' } } as never)
    renderForm(<StudyPlanForm studyId="study-1" initialValue={{ id: 'plan-1', study_id: 'study-1', title: 'Initial plan', status: 'Draft', created_at: '', updated_at: '' }} statusOptions={statusOptions} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Plan title' }), { target: { value: 'Updated plan' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update plan' }))

    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/study-plans/plan-1', expect.objectContaining({ title: 'Updated plan' })))
    expect(patch.mock.calls[0]?.[1]).not.toHaveProperty('clinical_data')
  })

  it('sends canonical study and subject references while excluding clinical values', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'milestone-1' } } as never)
    renderForm(<OperationalMilestoneForm studyId="study-1" subjectId="subject-1" statusOptions={[{ value: 'Screening' }]} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Milestone type' }), { target: { value: 'Screening complete' } })
    fireEvent.change(screen.getByLabelText(/Milestone date/), { target: { value: '2026-03-01' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Operational subject status' }), { target: { value: 'Screening' } })
    fireEvent.click(screen.getByRole('button', { name: 'Record milestone' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/subjects/subject-1/operational-milestones', expect.objectContaining({ study_id: 'study-1', subject_id: 'subject-1', milestone_type: 'Screening complete' })))
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('clinical_data')
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('form_values')
  })

  it('serializes enrollment target dates and requires server status choices only when supplied', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 'target-1' } } as never)
    renderForm(<EnrollmentTargetForm studyId="study-1" statusOptions={[{ value: 'Draft' }]} />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Target type' }), { target: { value: 'Enrollment' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Target quantity' }), { target: { value: '12' } })
    fireEvent.change(screen.getByLabelText(/Planning period start/), { target: { value: '2026-03-01' } })
    fireEvent.change(screen.getByLabelText(/Planning period end/), { target: { value: '2026-03-31' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Target status' }), { target: { value: 'Draft' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create target' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/enrollment-targets', expect.objectContaining({ study_id: 'study-1', target_quantity: 12, planning_period_start: '2026-03-01T00:00:00.000Z' })))
  })
})
