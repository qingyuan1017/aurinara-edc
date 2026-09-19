import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import {
  ActivationActionForm,
  EnrollmentTargetForm,
  MonitoringPlanForm,
  OperationalContactForm,
  OperationalSiteForm,
  OperationalStudyForm,
  OperationalTaskForm,
  OperationalTaskStatusForm,
  StudyPlanForm,
} from '@/features/ctms/forms'
import { ctmsKeys, type CTMSContact, type CTMSEnrollmentTarget, type CTMSMonitoringPlan, type CTMSOperationalSite, type CTMSOperationalStudy, type CTMSTask, type CTMSStudyPlan } from '@/features/ctms/api'

function renderForm(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const invalidateQueries = vi.spyOn(client, 'invalidateQueries').mockImplementation(async () => undefined)
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
  return { client, invalidateQueries }
}

const study: CTMSOperationalStudy = {
  id: 'profile-1', study_id: 'study-1', sponsor: 'Initial sponsor', phase: 'Phase 2', status: 'Draft', created_at: '', updated_at: '',
}

const site: CTMSOperationalSite = {
  id: 'site-profile-1', site_id: 'site-1', study_id: 'study-1', status: 'Planned', monitoring_readiness: 'Not ready', responsible_role: 'Site lead', created_at: '', updated_at: '',
}

const plan: CTMSStudyPlan = {
  id: 'plan-1', study_id: 'study-1', title: 'Initial plan', status: 'Draft', created_at: '', updated_at: '',
}

const target: CTMSEnrollmentTarget = {
  id: 'target-1', study_id: 'study-1', site_id: 'site-1', target_type: 'Enrollment', target_quantity: 10,
  planning_period_start: '2026-03-01T00:00:00.000Z', planning_period_end: '2026-03-31T00:00:00.000Z', status: 'Draft', created_at: '', updated_at: '',
}

const monitoringPlan: CTMSMonitoringPlan = {
  id: 'monitoring-plan-1', study_id: 'study-1', name: 'Risk-based monitoring', status: 'Draft', created_at: '', updated_at: '',
}

const task: CTMSTask = {
  id: 'task-1', study_id: 'study-1', site_id: 'site-1', title: 'Confirm monitoring date', description: 'Confirm the date.',
  owner_id: 'user-1', priority: 'high', status: 'Open', created_at: '', updated_at: '',
}

const contact: CTMSContact = {
  id: 'contact-1', study_id: 'study-1', site_id: 'site-1', name: 'Site contact', role: 'Coordinator', organization: 'Site organization', status: 'Active', created_at: '', updated_at: '',
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('CTMS operational form and mutation contracts', () => {
  it('updates a study profile with only owned fields, request metadata, and scoped cache refresh', async () => {
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: { ...study, sponsor: 'Updated sponsor', request_id: 'request-study-1', correlation_id: 'correlation-study-1' } } as never)
    const { invalidateQueries } = renderForm(<OperationalStudyForm studyId="study-1" initialValue={study} />)

    fireEvent.change(screen.getByRole('textbox', { name: 'Operational sponsor' }), { target: { value: 'Updated sponsor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update profile' }))

    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/operational-studies/profile-1', expect.objectContaining({ sponsor: 'Updated sponsor' })))
    expect(patch.mock.calls[0]?.[1]).not.toHaveProperty('clinical_data')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Request ID request-study-1'))
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.studyProfile('study-1'), ctmsKeys.dashboard('study-1'), ['ctms', 'report', 'study-1'],
    ]))
  })

  it('creates a site profile and refreshes site-scoped operational queries', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { ...site, request_id: 'request-site-1' } } as never)
    const { invalidateQueries } = renderForm(<OperationalSiteForm siteId="site-1" studyId="study-1" />)

    fireEvent.change(screen.getByRole('textbox', { name: 'Monitoring readiness' }), { target: { value: 'Ready' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Responsible operational role' }), { target: { value: 'Site manager' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create site profile' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/sites/site-1/operational-profile', expect.objectContaining({ study_id: 'study-1', monitoring_readiness: 'Ready', responsible_role: 'Site manager' })))
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('site_id')
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.siteProfile('site-1'), ctmsKeys.siteDashboard('site-1', { studyId: 'study-1' }),
    ]))
  })

  it('updates an enrollment target with operational dates and refreshes enrollment queries', async () => {
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: { ...target, target_quantity: 18 } } as never)
    const { invalidateQueries } = renderForm(<EnrollmentTargetForm studyId="study-1" initialValue={target} />)

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Target quantity' }), { target: { value: '18' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update target' }))

    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/enrollment-targets/target-1', expect.objectContaining({ target_quantity: 18 })))
    expect(patch.mock.calls[0]?.[1]).not.toHaveProperty('subject_id')
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.targets('study-1'), ctmsKeys.dashboard('study-1'), ['ctms', 'report', 'study-1'],
    ]))
  })

  it('creates a monitoring plan with a server-correlated operational version', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { ...monitoringPlan, request_id: 'request-monitoring-1', correlation_id: 'correlation-monitoring-1' } } as never)
    const { invalidateQueries } = renderForm(<MonitoringPlanForm studyId="study-1" correlationId="correlation-request-1" />)

    fireEvent.change(screen.getByRole('textbox', { name: 'Plan name' }), { target: { value: 'Risk-based monitoring' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create plan' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/monitoring-plans', expect.objectContaining({
      name: 'Risk-based monitoring', correlation_id: 'correlation-request-1', version: expect.any(Object),
    })))
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ctmsKeys.monitoringPlans('study-1') })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Correlation ID correlation-monitoring-1'))
  })

  it('updates a study plan and refreshes the plan query family', async () => {
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: plan } as never)
    const { invalidateQueries } = renderForm(<StudyPlanForm studyId="study-1" initialValue={plan} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Plan title' }), { target: { value: 'Updated operational plan' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update plan' }))

    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/study-plans/plan-1', expect.objectContaining({ title: 'Updated operational plan' })))
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ctmsKeys.plans('study-1') })
  })

  it('creates an operational task and refreshes task and dashboard query families', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: task } as never)
    const { invalidateQueries } = renderForm(<OperationalTaskForm studyId="study-1" correlationId="correlation-task-1" />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Task title' }), { target: { value: 'Confirm monitoring date' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/tasks', expect.objectContaining({ title: 'Confirm monitoring date', correlation_id: 'correlation-task-1', study_id: 'study-1' })))
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.tasks('study-1'), ctmsKeys.dashboard('study-1'),
    ]))
  })

  it('creates an operational contact and refreshes contact and dashboard query families', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: contact } as never)
    const { invalidateQueries } = renderForm(<OperationalContactForm studyId="study-1" />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Site contact' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create contact' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/studies/study-1/contacts', expect.objectContaining({ name: 'Site contact', study_id: 'study-1' })))
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.contacts('study-1'), ctmsKeys.dashboard('study-1'),
    ]))
  })

  it('updates an activation action and preserves canonical site scope', async () => {
    const activation = { id: 'activation-1', study_id: 'study-1', site_id: 'site-1', action_type: 'Regulatory review', status: 'Planned', responsible_role: 'Site lead', created_at: '', updated_at: '' }
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: activation } as never)
    const { invalidateQueries } = renderForm(<ActivationActionForm siteId="site-1" studyId="study-1" initialValue={activation} />)

    fireEvent.change(screen.getByRole('textbox', { name: 'Completion criteria' }), { target: { value: 'All readiness evidence reviewed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update action' }))

    await waitFor(() => expect(patch).toHaveBeenCalledWith('/ctms/activation-actions/activation-1', expect.objectContaining({ completion_criteria: 'All readiness evidence reviewed' })))
    expect(patch.mock.calls[0]?.[1]).not.toHaveProperty('visit_instance_id')
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.activation('site-1'), ctmsKeys.siteProfile('site-1'), ctmsKeys.siteDashboard('site-1', { studyId: 'study-1' }),
    ]))
  })

  it('submits a server-returned task status transition with its required reason and refreshes affected queries', async () => {
    const transitionResult = { resource: { ...task, status: 'Completed' }, current_status: 'Completed', allowed_transitions: [], meta: { requestId: 'request-transition-1', correlationId: 'correlation-transition-1' } }
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: transitionResult } as never)
    const { invalidateQueries } = renderForm(<OperationalTaskStatusForm task={task} transitionOptions={[{ status: 'Completed', requires_reason: true, reason_label: 'Completion reason' }]} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'New status' }), { target: { value: 'Completed' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Completion reason' }), { target: { value: 'Monitoring date confirmed.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Transition task' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/ctms/tasks/task-1/transition', { status: 'Completed', reason: 'Monitoring date confirmed.' }))
    expect(screen.getByTestId('ctms-current-status')).toHaveTextContent('Completed')
    expect(invalidateQueries.mock.calls.map(([options]) => options?.queryKey)).toEqual(expect.arrayContaining([
      ctmsKeys.detail('tasks', 'task-1', { studyId: 'study-1' }),
      ctmsKeys.tasks('study-1', { studyId: 'study-1' }),
      ctmsKeys.dashboard('study-1', { studyId: 'study-1' }),
    ]))
  })

  it.each([
    ['403', 403, 'CTMS_SCOPE_DENIED', 'The requested CTMS record is outside your assigned scope.', 'request-403-1'],
    ['409', 409, 'CTMS_CONFLICT', 'The record changed before this update was committed.', 'request-409-1'],
  ])('preserves the form and renders a safe %s response with its request ID', async (_label, status, code, message, requestId) => {
    const post = vi.spyOn(api, 'post').mockRejectedValue({ response: { status, data: { error: { code, message }, request_id: requestId } } })
    const { invalidateQueries } = renderForm(<OperationalStudyForm studyId="study-1" />)
    const sponsor = screen.getByRole('textbox', { name: 'Operational sponsor' })
    fireEvent.change(sponsor, { target: { value: 'Entered sponsor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create profile' }))

    await waitFor(() => expect(post).toHaveBeenCalled())
    await waitFor(() => expect(screen.getAllByRole('alert').some((alert) => alert.textContent?.includes(message))).toBe(true))
    expect(screen.getAllByRole('alert').some((alert) => alert.textContent?.includes(requestId))).toBe(true)
    expect(sponsor).toHaveValue('Entered sponsor')
    expect(invalidateQueries).not.toHaveBeenCalled()
  })
})
