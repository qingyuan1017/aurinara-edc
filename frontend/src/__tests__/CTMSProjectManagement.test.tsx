import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MilestoneHierarchy, ProjectGantt, ProjectKanban } from '@/features/ctms/components'
import type { CTMSProjectMilestone, CTMSStudyPlan } from '@/features/ctms/api'

const milestone: CTMSProjectMilestone = {
  id: 'milestone-1', study_id: 'study-1', title: 'First patient in', description: 'Enrollment milestone', milestone_type: 'ENROLLMENT', scope_level: 'country', country_code: 'US', planned_at: '2027-02-15T00:00:00Z', status: 'Planned', created_at: '', updated_at: '',
}

const activity: CTMSStudyPlan = {
  id: 'activity-1', study_id: 'study-1', title: 'Activate US sites', objective: 'Complete startup', milestone_id: milestone.id, scope_level: 'country', country_code: 'US', assignee_role_id: 'role-cra', start_at: '2027-01-10T00:00:00Z', due_at: '2027-02-10T00:00:00Z', status: 'DRAFT', created_at: '', updated_at: '',
}

const options = {
  users: [],
  roles: [{ id: 'role-cra', label: 'CRA' }],
  sites: [],
}

describe('CTMS project management views', () => {
  it('renders Jira-style status columns and moves an activity', () => {
    const onMove = vi.fn()
    render(<ProjectKanban activities={[activity]} milestones={[milestone]} options={options} canManage onMove={onMove} onEdit={() => undefined} />)

    expect(screen.getByRole('region', { name: 'Draft activities' })).toHaveTextContent('Activate US sites')
    expect(screen.getByText('First patient in')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'Move to' }), { target: { value: 'ACTIVE' } })
    expect(onMove).toHaveBeenCalledWith(activity, 'ACTIVE')
  })

  it('renders milestone markers, activity bars, and the milestone hierarchy', () => {
    const { rerender } = render(<ProjectGantt activities={[activity]} milestones={[milestone]} options={options} />)
    expect(screen.getByLabelText('Project Gantt timeline')).toHaveTextContent('First patient in')
    expect(screen.getByLabelText('Project Gantt timeline')).toHaveTextContent('Activate US sites')

    rerender(<MilestoneHierarchy milestones={[milestone]} activities={[activity]} options={options} canManage onEdit={() => undefined} />)
    expect(screen.getByLabelText('Milestones and master activities')).toHaveTextContent('Enrollment milestone')
    expect(screen.getByLabelText('Milestones and master activities')).toHaveTextContent('CRA')
  })
})
