import { useMemo, useState } from 'react'
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Flag,
  LayoutGrid,
  List,
  Plus,
  Search,
  SlidersHorizontal,
  UserRound,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type {
  CTMSProjectManagementOptions,
  CTMSProjectMilestone,
  CTMSStudyPlan,
} from '../api'

const DEFAULT_WORKFLOW_STATUSES = [
  { code: 'DRAFT', label: 'Draft' },
  { code: 'ACTIVE', label: 'Active' },
  { code: 'BLOCKED', label: 'Blocked' },
  { code: 'COMPLETED', label: 'Complete' },
] as const
export type ProjectView = 'board' | 'timeline' | 'list' | 'milestones'
export type ProjectWorkflowStatus = { code: string; label: string }

const STATUS_STYLES = [
  { dot: 'bg-slate-400', pill: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200' },
  { dot: 'bg-blue-500', pill: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200' },
  { dot: 'bg-amber-500', pill: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200' },
  { dot: 'bg-red-500', pill: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' },
  { dot: 'bg-purple-500', pill: 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-200' },
  { dot: 'bg-emerald-500', pill: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' },
] as const

function optionLabel(
  options: CTMSProjectManagementOptions | undefined,
  kind: 'roles' | 'users' | 'sites',
  id?: string | null,
) {
  return options?.[kind].find((option) => option.id === id)?.label
}

function scopeLabel(
  record: Pick<CTMSStudyPlan | CTMSProjectMilestone, 'scope_level' | 'country_code' | 'site_id'>,
  options?: CTMSProjectManagementOptions,
) {
  if (record.scope_level === 'country') return record.country_code || 'All countries'
  if (record.scope_level === 'site') {
    return record.site_id
      ? optionLabel(options, 'sites', record.site_id) ?? 'Selected site'
      : 'All sites'
  }
  return 'Study'
}

function shortDate(value?: string | null) {
  if (!value) return 'No date'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function issueKey(id: string, prefix: 'ACT' | 'MS') {
  const value = id.replace(/[^a-zA-Z0-9]/g, '').slice(-5).toUpperCase()
  return `${prefix}-${value || '00001'}`
}

function initials(value?: string) {
  if (!value) return '?'
  return value.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase()
}

function AssigneeAvatar({ name }: { name?: string }) {
  return (
    <span
      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground ring-2 ring-card"
      title={name ?? 'Unassigned'}
      aria-label={name ?? 'Unassigned'}
    >
      {name ? initials(name) : <UserRound className="h-3 w-3" />}
    </span>
  )
}

function normalizedStatusCode(status: string | null | undefined, workflowStatuses: readonly ProjectWorkflowStatus[]) {
  const value = status || workflowStatuses[0]?.code || 'DRAFT'
  return workflowStatuses.find((item) => item.code === value || item.label.toLowerCase() === value.toLowerCase())?.code ?? value
}

function StatusPill({ status, workflowStatuses = DEFAULT_WORKFLOW_STATUSES }: { status?: string | null; workflowStatuses?: readonly ProjectWorkflowStatus[] }) {
  const code = normalizedStatusCode(status, workflowStatuses)
  const index = Math.max(0, workflowStatuses.findIndex((item) => item.code === code))
  const style = STATUS_STYLES[index % STATUS_STYLES.length]
  const label = workflowStatuses.find((item) => item.code === code)?.label ?? status ?? 'Draft'
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold ${style.pill}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {label}
    </span>
  )
}

export function ProjectWorkspaceHeader({
  activityCount,
  milestoneCount,
  completedCount,
  canManage,
  onCreateActivity,
  onCreateMilestone,
}: {
  activityCount: number
  milestoneCount: number
  completedCount: number
  canManage: boolean
  onCreateActivity: () => void
  onCreateMilestone: () => void
}) {
  const progress = activityCount ? Math.round((completedCount / activityCount) * 100) : 0
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-medium tracking-tight text-foreground sm:text-3xl">Project Management</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Plan milestones and manage study, country, and site activities.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Project summary">
          <span><strong className="font-semibold text-foreground">{activityCount}</strong> activities</span>
          <span><strong className="font-semibold text-foreground">{milestoneCount}</strong> milestones</span>
          <span><strong className="font-semibold text-foreground">{progress}%</strong> complete</span>
        </div>
      </div>
      {canManage ? <div className="flex shrink-0 flex-wrap items-center gap-2"><Button type="button" variant="outline" onClick={onCreateMilestone}><Flag className="mr-1.5 h-4 w-4" />Add milestone</Button><Button type="button" onClick={onCreateActivity}><Plus className="mr-1.5 h-4 w-4" />Create activity</Button></div> : null}
    </header>
  )
}

export function ProjectToolbar({
  search,
  onSearchChange,
  scope,
  onScopeChange,
  assignee,
  onAssigneeChange,
  options,
  view,
  onViewChange,
  resultCount,
  showAssignee = true,
}: {
  search: string
  onSearchChange: (value: string) => void
  scope: string
  onScopeChange: (value: string) => void
  assignee: string
  onAssigneeChange: (value: string) => void
  options?: CTMSProjectManagementOptions
  view: ProjectView
  onViewChange: (view: ProjectView) => void
  resultCount: number
  showAssignee?: boolean
}) {
  const views: { value: ProjectView; label: string; icon: React.ReactNode }[] = [
    { value: 'board', label: 'Board', icon: <LayoutGrid className="h-3.5 w-3.5" /> },
    { value: 'timeline', label: 'Timeline', icon: <CalendarDays className="h-3.5 w-3.5" /> },
    { value: 'list', label: 'List', icon: <List className="h-3.5 w-3.5" /> },
    { value: 'milestones', label: 'Milestones', icon: <Flag className="h-3.5 w-3.5" /> },
  ]
  const hasFilters = Boolean(search || scope !== 'all' || assignee !== 'all')
  return (
    <div className="border-y py-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-[210px] flex-1 sm:max-w-xs">
          <span className="sr-only">Search work items</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder="Search this project" className="h-8 bg-background pl-8 text-sm" />
        </label>
        <label>
          <span className="sr-only">Filter by scope</span>
          <select value={scope} onChange={(event) => onScopeChange(event.target.value)} className="h-8 rounded border border-transparent bg-muted px-2.5 text-sm font-medium text-foreground hover:bg-accent">
            <option value="all">All scopes</option><option value="study">Study</option><option value="country">Country</option><option value="site">Site</option>
          </select>
        </label>
        {showAssignee ? (
          <label>
            <span className="sr-only">Filter by assignee</span>
            <select value={assignee} onChange={(event) => onAssigneeChange(event.target.value)} className="h-8 rounded border border-transparent bg-muted px-2.5 text-sm font-medium text-foreground hover:bg-accent">
              <option value="all">All assignees</option><option value="unassigned">Unassigned</option>
              <optgroup label="Roles">{options?.roles.map((option) => <option key={option.id} value={`role:${option.id}`}>{option.label}</option>)}</optgroup>
              <optgroup label="Users">{options?.users.map((option) => <option key={option.id} value={`user:${option.id}`}>{option.label}</option>)}</optgroup>
            </select>
          </label>
        ) : null}
        {hasFilters ? (
          <button type="button" className="h-8 rounded px-2 text-xs font-medium text-primary hover:bg-accent" onClick={() => { onSearchChange(''); onScopeChange('all'); onAssigneeChange('all') }}>Clear filters</button>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><SlidersHorizontal className="h-3.5 w-3.5" /> {resultCount} items</span>
        )}
        <div className="ml-auto flex rounded border bg-card p-0.5" role="group" aria-label="Project view">
          {views.map((item) => (
            <button key={item.value} type="button" className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-xs font-medium ${view === item.value ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`} onClick={() => onViewChange(item.value)}>{item.icon}{item.label}</button>
          ))}
        </div>
      </div>
    </div>
  )
}

export function ProjectKanban({ activities, milestones, options, workflowStatuses = DEFAULT_WORKFLOW_STATUSES, canManage, movingId, onMove, onEdit, onCreate }: {
  activities: CTMSStudyPlan[]
  milestones: CTMSProjectMilestone[]
  options?: CTMSProjectManagementOptions
  workflowStatuses?: readonly ProjectWorkflowStatus[]
  canManage: boolean
  movingId?: string
  onMove: (activity: CTMSStudyPlan, status: string) => void
  onEdit: (activity: CTMSStudyPlan) => void
  onCreate?: () => void
}) {
  const milestoneNames = useMemo(() => new Map(milestones.map((milestone) => [milestone.id, milestone.title])), [milestones])
  const columns = useMemo(() => {
    const configured: ProjectWorkflowStatus[] = (workflowStatuses.length ? workflowStatuses : DEFAULT_WORKFLOW_STATUSES).map((status) => ({ ...status }))
    activities.forEach((activity) => {
      const code = normalizedStatusCode(activity.status, configured)
      if (!configured.some((item) => item.code === code)) configured.push({ code, label: activity.status || code })
    })
    return configured
  }, [activities, workflowStatuses])
  return (
    <div className="overflow-x-auto pb-2" aria-label="Master activity Kanban board">
      <div className="flex min-w-max items-start gap-3">
        {columns.map((status, columnIndex) => {
          const style = STATUS_STYLES[columnIndex % STATUS_STYLES.length]
          const items = activities.filter((activity) => normalizedStatusCode(activity.status, columns) === status.code)
          return (
            <section key={status.code} className="w-[290px] shrink-0 rounded bg-muted p-2" aria-label={`${status.label} activities`} onDragOver={(event) => { if (canManage) event.preventDefault() }} onDrop={(event) => {
              const id = event.dataTransfer.getData('text/plain')
              const activity = activities.find((candidate) => candidate.id === id)
              if (canManage && activity && normalizedStatusCode(activity.status, columns) !== status.code) onMove(activity, status.code)
            }}>
              <div className="mb-2 flex h-9 items-center justify-between px-1.5">
                <h2 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-foreground"><span className={`h-2 w-2 rounded-full ${style.dot}`} />{status.label}<span className="text-muted-foreground">{items.length}</span></h2>
                <button type="button" aria-label={`${status.label} column options`} className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground">•••</button>
              </div>
              <div className="min-h-24 space-y-2">
                {items.map((activity) => {
                  const role = optionLabel(options, 'roles', activity.assignee_role_id)
                  const user = optionLabel(options, 'users', activity.assignee_user_id)
                  const assignee = user ?? role
                  const overdue = Boolean(activity.due_at && new Date(activity.due_at).getTime() < Date.now() && status.code !== 'COMPLETED')
                  return (
                    <article key={activity.id} draggable={canManage} onDragStart={(event) => event.dataTransfer.setData('text/plain', activity.id)} className={`group rounded border bg-card p-3 text-card-foreground shadow-sm transition hover:border-input hover:shadow-md ${movingId === activity.id ? 'opacity-50' : ''}`}>
                      <div className="flex items-start gap-2"><span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-info/15 text-info" title="Master activity"><CheckCircle2 className="h-3.5 w-3.5" /></span>{canManage ? <button type="button" className="line-clamp-2 text-left text-sm font-medium leading-5 text-card-foreground hover:text-primary" onClick={() => onEdit(activity)}>{activity.title}</button> : <h3 className="line-clamp-2 text-sm font-medium leading-5 text-card-foreground">{activity.title}</h3>}</div>
                      {activity.objective ? <p className="mt-2 line-clamp-2 text-xs leading-4 text-muted-foreground">{activity.objective}</p> : null}
                      {activity.milestone_id ? <div className="mt-2 flex items-center gap-1.5 truncate rounded bg-purple-50 px-1.5 py-1 text-[11px] font-medium text-purple-700 dark:bg-purple-950 dark:text-purple-200"><Flag className="h-3 w-3 shrink-0" /><span className="truncate">{milestoneNames.get(activity.milestone_id) ?? 'Linked milestone'}</span></div> : null}
                      <div className="mt-3 flex items-center gap-2"><span className="text-[11px] font-medium text-muted-foreground">{issueKey(activity.id, 'ACT')}</span><span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">{scopeLabel(activity, options)}</span><span className="ml-auto"><AssigneeAvatar name={assignee} /></span></div>
                      <div className="mt-2 flex items-center justify-between border-t pt-2"><span className={`inline-flex items-center gap-1 text-[11px] ${overdue ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}>{overdue ? <AlertCircle className="h-3 w-3" /> : <CalendarDays className="h-3 w-3" />}{shortDate(activity.due_at)}</span>{canManage ? <label><span className="sr-only">Move to</span><select aria-label="Move to" className="max-w-[110px] rounded border-0 bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-foreground" value={normalizedStatusCode(activity.status, columns)} disabled={movingId === activity.id} onChange={(event) => onMove(activity, event.target.value)}>{columns.map((column) => <option key={column.code} value={column.code}>{column.label}</option>)}</select></label> : null}</div>
                    </article>
                  )
                })}
                {!items.length ? <div className="rounded border border-dashed px-3 py-7 text-center text-xs text-muted-foreground">Drop work items here</div> : null}
              </div>
              {canManage && onCreate ? <button type="button" className="mt-2 flex w-full items-center gap-1 rounded px-2 py-1.5 text-left text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground" onClick={onCreate}><Plus className="h-3.5 w-3.5" /> Create issue</button> : null}
            </section>
          )
        })}
      </div>
    </div>
  )
}

export function ProjectIssueList({ activities, options, workflowStatuses = DEFAULT_WORKFLOW_STATUSES, canManage, onEdit }: { activities: CTMSStudyPlan[]; options?: CTMSProjectManagementOptions; workflowStatuses?: readonly ProjectWorkflowStatus[]; canManage: boolean; onEdit: (activity: CTMSStudyPlan) => void }) {
  return (
    <div>
      <div className="overflow-x-auto rounded border">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-muted text-[11px] uppercase tracking-wide text-muted-foreground"><tr><th className="px-3 py-2">Type</th><th className="px-3 py-2">Key</th><th className="px-3 py-2">Summary</th><th className="px-3 py-2">Scope</th><th className="px-3 py-2">Assignee</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Due</th></tr></thead>
          <tbody className="divide-y divide-border">{activities.map((activity) => {
            const assignee = optionLabel(options, 'users', activity.assignee_user_id) ?? optionLabel(options, 'roles', activity.assignee_role_id)
            return <tr key={activity.id} className="hover:bg-muted/50"><td className="px-3 py-2"><span className="flex h-5 w-5 items-center justify-center rounded bg-info/15 text-info"><CheckCircle2 className="h-3.5 w-3.5" /></span></td><td className="px-3 py-2 text-xs font-medium text-muted-foreground">{issueKey(activity.id, 'ACT')}</td><td className="px-3 py-2">{canManage ? <button type="button" className="font-medium text-foreground hover:text-primary" onClick={() => onEdit(activity)}>{activity.title}</button> : activity.title}</td><td className="px-3 py-2 text-muted-foreground">{scopeLabel(activity, options)}</td><td className="px-3 py-2"><span className="flex items-center gap-2"><AssigneeAvatar name={assignee} /><span>{assignee ?? 'Unassigned'}</span></span></td><td className="px-3 py-2"><StatusPill status={activity.status} workflowStatuses={workflowStatuses} /></td><td className="px-3 py-2 text-muted-foreground">{shortDate(activity.due_at)}</td></tr>
          })}</tbody>
        </table>
      </div>
    </div>
  )
}

export function ProjectGantt({ activities, milestones, options }: { activities: CTMSStudyPlan[]; milestones: CTMSProjectMilestone[]; options?: CTMSProjectManagementOptions }) {
  const datedActivities = activities.filter((activity) => activity.start_at || activity.due_at)
  const dates = [...datedActivities.flatMap((activity) => [activity.start_at, activity.due_at]), ...milestones.map((milestone) => milestone.planned_at)].filter(Boolean).map((value) => new Date(value as string).getTime()).filter(Number.isFinite)
  if (!dates.length) return <p className="rounded border border-dashed p-10 text-center text-sm text-muted-foreground">Add start, due, or target dates to build the project timeline.</p>
  const minimum = Math.min(...dates)
  const maximum = Math.max(...dates)
  const span = Math.max(maximum - minimum, 86_400_000)
  const position = (value?: string | null) => value ? Math.max(0, Math.min(100, ((new Date(value).getTime() - minimum) / span) * 100)) : 0
  const ticks = Array.from({ length: 5 }, (_, index) => new Date(minimum + (span * index) / 4).toISOString())
  const timelineGrid = { backgroundImage: 'linear-gradient(to right, var(--color-border) 1px, transparent 1px)', backgroundSize: '25% 100%' }
  return (
    <div className="overflow-x-auto" aria-label="Project Gantt timeline">
      <div className="min-w-[900px] overflow-hidden rounded border">
        <div className="grid grid-cols-[280px_1fr] border-b bg-muted text-xs font-medium text-muted-foreground"><div className="px-3 py-2.5">Work item</div><div className="grid grid-cols-5 px-2 py-2.5">{ticks.map((tick) => <span key={tick}>{shortDate(tick)}</span>)}</div></div>
        {milestones.map((milestone) => milestone.planned_at ? <div key={milestone.id} className="grid grid-cols-[280px_1fr] border-b text-sm"><div className="flex items-center gap-2 px-3 py-2.5"><Flag className="h-4 w-4 shrink-0 text-purple-600 dark:text-purple-400" /><div className="min-w-0"><div className="truncate font-medium">{milestone.title}</div><div className="text-[11px] text-muted-foreground">{issueKey(milestone.id, 'MS')} · {scopeLabel(milestone, options)}</div></div></div><div className="relative min-h-14" style={timelineGrid}><span className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] bg-purple-600 shadow-sm dark:bg-purple-400" style={{ left: `${position(milestone.planned_at)}%` }} title={`${milestone.title}: ${shortDate(milestone.planned_at)}`} /></div></div> : null)}
        {datedActivities.map((activity) => {
          const start = activity.start_at ?? activity.due_at
          const end = activity.due_at ?? activity.start_at
          const left = position(start)
          const width = Math.max(position(end) - left, 1.5)
          const assignee = optionLabel(options, 'users', activity.assignee_user_id) ?? optionLabel(options, 'roles', activity.assignee_role_id)
          return <div key={activity.id} className="grid grid-cols-[280px_1fr] border-b text-sm last:border-b-0"><div className="flex items-center gap-2 px-3 py-2.5"><CheckCircle2 className="h-4 w-4 shrink-0 text-info" /><div className="min-w-0 flex-1"><div className="truncate font-medium">{activity.title}</div><div className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><span>{issueKey(activity.id, 'ACT')}</span><span>·</span><span>{scopeLabel(activity, options)}</span></div></div><AssigneeAvatar name={assignee} /></div><div className="relative min-h-14" style={timelineGrid}><span className="absolute top-1/2 h-5 -translate-y-1/2 rounded bg-info shadow-sm" style={{ left: `${left}%`, width: `${width}%` }} title={`${shortDate(start)} – ${shortDate(end)}`}><span className="block truncate px-2 text-[10px] font-semibold leading-5 text-info-foreground">{activity.title}</span></span></div></div>
        })}
      </div>
    </div>
  )
}

export function MilestoneHierarchy({ milestones, activities, options, workflowStatuses = DEFAULT_WORKFLOW_STATUSES, canManage, onEdit }: { milestones: CTMSProjectMilestone[]; activities: CTMSStudyPlan[]; options?: CTMSProjectManagementOptions; workflowStatuses?: readonly ProjectWorkflowStatus[]; canManage: boolean; onEdit: (milestone: CTMSProjectMilestone) => void }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  return (
    <div className="space-y-3" aria-label="Milestones and master activities">
      {milestones.map((milestone) => {
        const children = activities.filter((activity) => activity.milestone_id === milestone.id)
        const completed = children.filter((activity) => normalizedStatusCode(activity.status, workflowStatuses) === 'COMPLETED').length
        const percent = children.length ? Math.round((completed / children.length) * 100) : 0
        const isOpen = expanded[milestone.id] ?? true
        return (
          <article key={milestone.id} className="overflow-hidden rounded border bg-card text-card-foreground shadow-sm">
            <div className="flex flex-wrap items-start gap-3 border-l-4 border-purple-600 p-4 dark:border-purple-400"><button type="button" className="mt-0.5 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" onClick={() => setExpanded((current) => ({ ...current, [milestone.id]: !isOpen }))} aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${milestone.title}`}>{isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button><Flag className="mt-0.5 h-4 w-4 shrink-0 text-purple-600 dark:text-purple-400" /><div className="min-w-[220px] flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-muted-foreground">{issueKey(milestone.id, 'MS')}</span>{canManage ? <button type="button" className="font-semibold text-card-foreground hover:text-primary" onClick={() => onEdit(milestone)}>{milestone.title}</button> : <h3 className="font-semibold">{milestone.title}</h3>}</div><p className="mt-1 text-xs text-muted-foreground">{milestone.milestone_type} · {scopeLabel(milestone, options)} · Target {shortDate(milestone.planned_at)}</p>{milestone.description ? <p className="mt-2 text-sm text-card-foreground/80">{milestone.description}</p> : null}</div><div className="w-40"><div className="mb-1 flex justify-between text-[11px] text-muted-foreground"><span>{completed}/{children.length} done</span><span>{percent}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success" style={{ width: `${percent}%` }} /></div></div><StatusPill status={milestone.status} /></div>
            {isOpen ? <div className="border-t bg-background">{children.length ? children.map((activity) => {
              const assignee = optionLabel(options, 'users', activity.assignee_user_id) ?? optionLabel(options, 'roles', activity.assignee_role_id)
              return <div key={activity.id} className="grid grid-cols-[auto_1fr_auto] items-center gap-3 border-b px-5 py-2.5 text-sm last:border-b-0 hover:bg-muted/50"><span className="flex items-center gap-2 text-xs text-muted-foreground"><CheckCircle2 className="h-4 w-4 text-info" />{issueKey(activity.id, 'ACT')}</span><div className="min-w-0"><div className="truncate font-medium text-foreground">{activity.title}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{scopeLabel(activity, options)} · {shortDate(activity.due_at)}</div></div><div className="flex items-center gap-3"><StatusPill status={activity.status} workflowStatuses={workflowStatuses} /><AssigneeAvatar name={assignee} /><span className="hidden min-w-20 text-xs text-muted-foreground sm:inline">{assignee ?? 'Unassigned'}</span></div></div>
            }) : <p className="px-5 py-5 text-sm text-muted-foreground">No master activities are linked to this milestone.</p>}</div> : null}
          </article>
        )
      })}
    </div>
  )
}
