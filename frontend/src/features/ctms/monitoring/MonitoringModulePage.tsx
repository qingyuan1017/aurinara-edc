import { useState, type ReactNode } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  ClipboardCheck,
  FileCheck2,
  Gauge,
  ListChecks,
  Plus,
  ShieldAlert,
  Users,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MetricCard, PageHeader } from '@/components/patterns'
import { useAuthStore } from '@/lib/auth'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import {
  ctmsApi,
  ctmsKeys,
  type CTMSMonitoringActivity,
  type CTMSMonitoringFinding,
  type CTMSMonitoringPlan,
  type CTMSMonitoringPlanVersion,
  type CTMSMonitoringReport,
  useCTMSMonitoringActivities,
  useCTMSMonitoringFindings,
  useCTMSMonitoringPlans,
  useCTMSMonitoringPlanVersions,
} from '../api'
import {
  MonitoringActivityActions,
  MonitoringActivityForm,
  MonitoringPlanForm,
  MonitoringPlanVersionActions,
} from '../forms'
import { MonitoringFindingsPage } from './MonitoringFindingsPage'
import { MonitoringVisitWorkspace } from './MonitoringVisitWorkspace'

export type MonitoringModuleView = 'overview' | 'plans' | 'visits' | 'findings' | 'risk' | 'reports'

const PAGE_SIZE = 100
const CLOSED_VISIT_STATUSES = new Set(['Completed', 'Cancelled'])
const CLOSED_FINDING_STATUSES = new Set(['Closed', 'Cancelled'])
const RISK_ORDER: Record<SiteAttention['risk'], number> = { High: 0, Medium: 1, Low: 2 }

const VIEW_CONFIG: Record<MonitoringModuleView, { label: string; description: string; path: string }> = {
  overview: { label: 'Overview', description: 'Monitoring coverage, upcoming work, compliance, and operational attention.', path: '' },
  plans: { label: 'Monitoring Plans', description: 'Study strategy, approved versions, visit rules, activities, and risk controls.', path: '/plans' },
  visits: { label: 'Monitoring Visits', description: 'Plan, execute, document, and report site monitoring visits.', path: '/visits' },
  findings: { label: 'Findings & Actions', description: 'Track findings, corrective actions, verification, and closure independently of the MVR.', path: '/findings' },
  risk: { label: 'Risk-Based Monitoring', description: 'Review plan-defined risk rules and operational signals requiring human assessment.', path: '/risk' },
  reports: { label: 'Monitoring Reports', description: 'Monitor plan adherence, MVR turnaround, follow-up aging, and workload.', path: '/reports' },
}

function formatDate(value?: string | null, withTime = false) {
  if (!value) return 'Not set'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(date)
}

function formatSite(siteId?: string | null) {
  return siteId ? `Site ${siteId}` : 'Study level'
}

function groupBy<T>(items: T[], keyFor: (item: T) => string) {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const key = keyFor(item)
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  return groups
}

function statusTone(status: string) {
  if (['Completed', 'Approved', 'Finalized', 'Closed', 'Published', 'Active'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (['Overdue', 'Critical', 'Major', 'Revision Required'].includes(status)) return 'border-red-200 bg-red-50 text-red-700'
  if (['Scheduled', 'Submitted', 'Under Review', 'Pending Verification'].includes(status)) return 'border-blue-200 bg-blue-50 text-blue-700'
  return 'border-border bg-muted/40 text-muted-foreground'
}

function StatusPill({ children }: { children: string }) {
  return <span className={cn('inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium', statusTone(children))}>{children}</span>
}

function EmptyPanel({ title, description }: { title: string; description: string }) {
  return <div className="rounded-xl border border-dashed p-10 text-center"><p className="font-medium">{title}</p><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>
}

function MonitoringNavigation({ studyId, view }: { studyId: string; view: MonitoringModuleView }) {
  const root = `/studies/${encodeURIComponent(studyId)}/ctms/monitoring`
  return <nav aria-label="Monitoring module" className="mb-6 overflow-x-auto border-b">
    <div className="flex min-w-max gap-1">
      {(Object.entries(VIEW_CONFIG) as Array<[MonitoringModuleView, typeof VIEW_CONFIG[MonitoringModuleView]]>).map(([key, item]) => <a
        key={key}
        href={`${root}${item.path}`}
        aria-current={view === key ? 'page' : undefined}
        className={cn('border-b-2 px-3 py-3 text-sm font-medium transition-colors', view === key ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}
      >{item.label}</a>)}
    </div>
  </nav>
}

type SiteAttention = {
  siteId: string
  risk: 'High' | 'Medium' | 'Low'
  nextVisit?: CTMSMonitoringActivity
  openFindings: number
  overdueVisits: number
}

function buildSiteAttention(visits: CTMSMonitoringActivity[], findings: CTMSMonitoringFinding[]): SiteAttention[] {
  const siteIds = new Set([...visits.map((item) => item.site_id), ...findings.map((item) => item.site_id)].filter((value): value is string => Boolean(value)))
  const now = new Date().getTime()
  return [...siteIds].map<SiteAttention>((siteId) => {
    const siteVisits = visits.filter((item) => item.site_id === siteId)
    const siteFindings = findings.filter((item) => item.site_id === siteId && !CLOSED_FINDING_STATUSES.has(item.status))
    const overdueVisits = siteVisits.filter((item) => !CLOSED_VISIT_STATUSES.has(item.status) && new Date(item.planned_date).getTime() < now).length
    const hasSeriousFinding = siteFindings.some((item) => item.severity === 'Critical' || item.severity === 'Major')
    const nextVisit = siteVisits
      .filter((item) => !CLOSED_VISIT_STATUSES.has(item.status) && new Date(item.planned_date).getTime() >= now)
      .sort((left, right) => new Date(left.planned_date).getTime() - new Date(right.planned_date).getTime())[0]
    return { siteId, risk: overdueVisits || hasSeriousFinding ? 'High' : siteFindings.length ? 'Medium' : 'Low', nextVisit, openFindings: siteFindings.length, overdueVisits }
  }).sort((left, right) => RISK_ORDER[left.risk] - RISK_ORDER[right.risk])
}

function OverviewView({ visits, findings, loading }: { visits: CTMSMonitoringActivity[]; findings: CTMSMonitoringFinding[]; loading: boolean }) {
  const user = useAuthStore((state) => state.user)
  const now = new Date()
  const inThirtyDays = new Date(now)
  inThirtyDays.setDate(now.getDate() + 30)
  const currentYear = now.getFullYear()
  const activeVisits = visits.filter((item) => !CLOSED_VISIT_STATUSES.has(item.status))
  const upcoming = activeVisits.filter((item) => {
    const planned = new Date(item.planned_date)
    return planned >= now && planned <= inThirtyDays
  })
  const overdue = activeVisits.filter((item) => item.status === 'Overdue' || new Date(item.planned_date) < now)
  const openFindings = findings.filter((item) => !CLOSED_FINDING_STATUSES.has(item.status))
  const majorFindings = openFindings.filter((item) => item.severity === 'Critical' || item.severity === 'Major')
  const yearVisits = visits.filter((item) => new Date(item.planned_date).getFullYear() === currentYear && item.status !== 'Cancelled')
  const completedYearVisits = yearVisits.filter((item) => item.status === 'Completed')
  const completion = yearVisits.length ? Math.round((completedYearVisits.length / yearVisits.length) * 100) : 0
  const attention = buildSiteAttention(visits, findings)
  const roleNames = user?.roles.map((role) => role.role_name.toLowerCase()) ?? []
  const persona = roleNames.some((role) => role.includes('cra')) ? 'CRA'
    : roleNames.some((role) => role.includes('sponsor')) ? 'Sponsor'
      : 'Clinical Operations Manager'
  const personaMessage = persona === 'CRA'
    ? 'Focus on your upcoming visits, draft MVRs, overdue follow-ups, and assigned sites.'
    : persona === 'Sponsor'
      ? 'Focus on monitoring coverage, critical findings, compliance trends, and oversight.'
      : 'Focus on plan adherence, overdue approvals, site attention, and CRA workload.'

  return <div className="space-y-6">
    <Card className="border-primary/20 bg-primary/[0.03]"><CardContent className="flex flex-col gap-2 p-5 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-semibold uppercase tracking-wide text-primary">{persona} view</p><p className="mt-1 text-sm">{personaMessage}</p></div><span className="text-xs text-muted-foreground">Study-scoped, server-authorized data</span></CardContent></Card>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard loading={loading} label="Active sites" value={new Set(activeVisits.map((item) => item.site_id).filter(Boolean)).size} description={`${attention.filter((item) => item.risk === 'High').length} requiring attention`} icon={<Users className="h-5 w-5" />} />
      <MetricCard loading={loading} label="Upcoming visits" value={upcoming.length} description="Next 30 days" icon={<CalendarDays className="h-5 w-5" />} />
      <MetricCard loading={loading} label="Overdue visits" value={overdue.length} description={overdue.length ? 'Action required' : 'No overdue visits'} icon={<AlertTriangle className="h-5 w-5" />} />
      <MetricCard loading={loading} label="Open findings" value={openFindings.length} description={`${majorFindings.length} critical or major`} icon={<ShieldAlert className="h-5 w-5" />} />
    </div>
    <Card><CardHeader><CardTitle className="text-lg">Monitoring visit completion</CardTitle><CardDescription>{currentYear} plan delivery</CardDescription></CardHeader><CardContent className="space-y-3"><div className="flex items-end justify-between"><p className="text-3xl font-semibold">{completion}%</p><p className="text-sm text-muted-foreground">{completedYearVisits.length} of {yearVisits.length} planned visits</p></div><div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${completion}%` }} /></div></CardContent></Card>
    <Card><CardHeader><CardTitle className="text-lg">Sites requiring attention</CardTitle><CardDescription>Prioritized from overdue visits and unresolved findings. This is an operational summary, not an automated clinical risk decision.</CardDescription></CardHeader><CardContent>{attention.length ? <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-muted-foreground"><th className="pb-3 font-medium">Site</th><th className="pb-3 font-medium">Attention</th><th className="pb-3 font-medium">Next visit</th><th className="pb-3 text-right font-medium">Open findings</th></tr></thead><tbody>{attention.slice(0, 8).map((site) => <tr key={site.siteId} className="border-b last:border-0"><td className="py-3 font-medium">{site.siteId}</td><td className="py-3"><StatusPill>{site.risk}</StatusPill>{site.overdueVisits ? <span className="ml-2 text-xs text-destructive">{site.overdueVisits} overdue</span> : null}</td><td className="py-3">{site.nextVisit ? formatDate(site.nextVisit.planned_date) : 'Not scheduled'}</td><td className="py-3 text-right">{site.openFindings}</td></tr>)}</tbody></table></div> : <EmptyPanel title="No site monitoring records" description="Schedule a site visit or record a site finding to populate attention monitoring." />}</CardContent></Card>
  </div>
}

function VersionDetails({ version }: { version: CTMSMonitoringPlanVersion }) {
  const activities = version.activity_types ?? []
  const thresholds = Object.entries(version.thresholds ?? {})
  return <Tabs defaultValue="overview" className="mt-4">
    <TabsList className="h-auto flex-wrap justify-start"><TabsTrigger value="overview">Overview</TabsTrigger><TabsTrigger value="rules">Visit rules</TabsTrigger><TabsTrigger value="activities">Activities</TabsTrigger><TabsTrigger value="risk">Risk rules</TabsTrigger><TabsTrigger value="history">History</TabsTrigger></TabsList>
    <TabsContent value="overview" className="grid gap-4 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-4"><Info label="Strategy" value={version.monitoring_strategy ?? 'Not configured'} /><Info label="Frequency" value={version.frequency ?? (version.frequency_value ? `Every ${version.frequency_value} ${version.frequency_unit ?? ''}` : 'Not configured')} /><Info label="Risk level" value={version.risk_level ?? 'Not configured'} /><Info label="Effective" value={formatDate(version.published_at)} /><div className="sm:col-span-2 lg:col-span-4"><Info label="Objectives" value={version.objectives ?? 'No objectives documented.'} /></div></TabsContent>
    <TabsContent value="rules" className="rounded-lg border p-4">{version.rules?.length ? <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-muted-foreground"><th className="pb-2">Visit type</th><th className="pb-2">Frequency / trigger</th><th className="pb-2">Mode</th><th className="pb-2">MVR due</th></tr></thead><tbody>{version.rules.map((rule) => <tr key={rule.id} className="border-b last:border-0"><td className="py-3 font-medium">{rule.visit_type}</td><td className="py-3">{rule.trigger ?? (rule.frequency_value ? `Every ${rule.frequency_value} ${rule.frequency_unit ?? ''}` : 'As required')}</td><td className="py-3">{rule.allowed_modalities.join(' / ') || 'Not set'}</td><td className="py-3">{rule.report_due_days} days</td></tr>)}</tbody></table></div> : <p className="text-sm text-muted-foreground">No structured visit rules in this version.</p>}</TabsContent>
    <TabsContent value="activities" className="rounded-lg border p-4">{activities.length ? <div className="flex flex-wrap gap-2">{activities.map((activity) => <span key={activity} className="rounded-full border bg-muted/40 px-3 py-1 text-sm">{activity}</span>)}</div> : <p className="text-sm text-muted-foreground">No activity categories configured.</p>}</TabsContent>
    <TabsContent value="risk" className="space-y-4 rounded-lg border p-4"><Info label="Risk strategy" value={version.risk_strategy ?? 'No risk strategy documented.'} /><Info label="Escalation threshold" value={version.risk_threshold ?? 'No narrative threshold configured.'} />{thresholds.length ? <dl className="grid gap-3 sm:grid-cols-2">{thresholds.map(([key, value]) => <Info key={key} label={key.replaceAll('_', ' ')} value={String(value)} />)}</dl> : null}</TabsContent>
    <TabsContent value="history" className="rounded-lg border p-4"><p className="text-sm">Version {version.version_number} · {version.status}</p><p className="mt-1 text-sm text-muted-foreground">Created {formatDate(version.created_at)}{version.amendment_reason ? ` · ${version.amendment_reason}` : ''}</p></TabsContent>
  </Tabs>
}

function Info({ label, value }: { label: string; value: ReactNode }) {
  return <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt><dd className="mt-1 text-sm">{value}</dd></div>
}

function PlanCard({ plan, canManage, onChanged }: { plan: CTMSMonitoringPlan; canManage: boolean; onChanged: () => void }) {
  const versions = useCTMSMonitoringPlanVersions(plan.id, { pagination: { pageSize: PAGE_SIZE } })
  const current = versions.data?.items.find((item) => item.id === plan.current_version_id) ?? versions.data?.items.at(-1)
  return <Card><CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><CardTitle className="text-lg">{plan.name}</CardTitle><StatusPill>{plan.status}</StatusPill>{plan.site_id ? <span className="rounded-full border px-2 py-0.5 text-xs">Site override</span> : null}</div><CardDescription className="mt-1">{plan.description ?? (plan.site_id ? `Site-specific plan for ${plan.site_id}` : 'Study-level monitoring plan')}</CardDescription></div>{current ? <div className="text-right"><p className="text-sm font-medium">Version {current.version_number}</p><p className="text-xs text-muted-foreground">{current.status}</p></div> : null}</div></CardHeader><CardContent>{versions.isLoading ? <p className="text-sm text-muted-foreground">Loading plan configuration…</p> : current ? <><VersionDetails version={current} /><div className="mt-4 border-t pt-4"><MonitoringPlanVersionActions planId={plan.id} canManage={canManage} onChanged={() => { void versions.refetch(); onChanged() }} /></div></> : <EmptyPanel title="No plan version" description="Create or amend this plan to add structured monitoring requirements." />}</CardContent></Card>
}

function PlansView({ studyId, plans, loading, canManage, onChanged }: { studyId: string; plans: CTMSMonitoringPlan[]; loading: boolean; canManage: boolean; onChanged: () => void }) {
  const [creating, setCreating] = useState(false)
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-3xl text-sm text-muted-foreground">Approved versions remain historically intact. Every planned visit retains the exact plan version that generated its requirements.</p>{canManage ? <Button onClick={() => setCreating((value) => !value)}><Plus className="mr-2 h-4 w-4" />{creating ? 'Close form' : 'New monitoring plan'}</Button> : null}</div>
    {creating ? <Card><CardContent className="pt-6"><MonitoringPlanForm studyId={studyId} onSaved={() => { setCreating(false); onChanged() }} onCancel={() => setCreating(false)} /></CardContent></Card> : null}
    {loading ? <p className="text-sm text-muted-foreground">Loading monitoring plans…</p> : plans.length ? <div className="space-y-4">{plans.map((plan) => <PlanCard key={plan.id} plan={plan} canManage={canManage} onChanged={onChanged} />)}</div> : <EmptyPanel title="No monitoring plan yet" description="Create a structured study monitoring plan to drive visit requirements and checklists." />}
  </div>
}

function VisitCard({ visit, canManage, onChanged }: { visit: CTMSMonitoringActivity; canManage: boolean; onChanged: () => void }) {
  return <Card><CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-mono text-xs text-muted-foreground">{visit.visit_code ?? visit.id}</p><CardTitle className="mt-1 text-lg">{visit.activity_type}</CardTitle><CardDescription>{formatSite(visit.site_id)} · {formatDate(visit.planned_date, true)} · {visit.modality}</CardDescription></div><StatusPill>{visit.status}</StatusPill></div></CardHeader><CardContent className="space-y-4"><dl className="grid gap-3 text-sm sm:grid-cols-3"><Info label="Assigned CRA" value={visit.assigned_cra_id ?? 'Unassigned'} /><Info label="Actual start" value={formatDate(visit.actual_start_at, true)} /><Info label="Plan version" value={visit.plan_version_id ?? 'Not linked'} /></dl>{canManage ? <MonitoringActivityActions activity={visit} onChanged={onChanged} /> : null}<MonitoringVisitWorkspace visit={visit} canManage={canManage} onVisitChanged={onChanged} /></CardContent></Card>
}

function VisitsView({ studyId, visits, loading, canManage, onChanged }: { studyId: string; visits: CTMSMonitoringActivity[]; loading: boolean; canManage: boolean; onChanged: () => void }) {
  const [creating, setCreating] = useState(false)
  const [display, setDisplay] = useState('list')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('All')
  const filtered = visits.filter((visit) => {
    const haystack = `${visit.site_id ?? ''} ${visit.assigned_cra_id ?? ''} ${visit.activity_type} ${visit.visit_code ?? ''} ${visit.modality}`.toLowerCase()
    return haystack.includes(search.toLowerCase()) && (status === 'All' || visit.status === status || (status === 'Upcoming' && !CLOSED_VISIT_STATUSES.has(visit.status) && new Date(visit.planned_date) >= new Date()))
  }).sort((left, right) => new Date(left.planned_date).getTime() - new Date(right.planned_date).getTime())
  const byDate = groupBy(filtered, (visit) => new Date(visit.planned_date).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }))
  const byCra = groupBy(filtered, (visit) => visit.assigned_cra_id ?? 'Unassigned')
  const statuses = ['All', 'Upcoming', ...new Set(visits.map((item) => item.status))]
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-1 flex-wrap gap-2"><Input className="max-w-sm" aria-label="Search monitoring visits" placeholder="Search site, CRA, type, or code" value={search} onChange={(event) => setSearch(event.target.value)} /><select className="h-10 rounded-md border bg-background px-3 text-sm" aria-label="Filter visit status" value={status} onChange={(event) => setStatus(event.target.value)}>{statuses.map((item) => <option key={item}>{item}</option>)}</select></div>{canManage ? <Button onClick={() => setCreating((value) => !value)}><Plus className="mr-2 h-4 w-4" />{creating ? 'Close form' : 'Schedule visit'}</Button> : null}</div>
    {creating ? <Card><CardContent className="pt-6"><MonitoringActivityForm studyId={studyId} onSaved={() => { setCreating(false); onChanged() }} onCancel={() => setCreating(false)} /></CardContent></Card> : null}
    <Tabs value={display} onValueChange={setDisplay}><TabsList><TabsTrigger value="list">Table</TabsTrigger><TabsTrigger value="calendar">Calendar</TabsTrigger><TabsTrigger value="workload">CRA workload</TabsTrigger></TabsList>
      <TabsContent value="list" className="space-y-3">{loading ? <p className="text-sm text-muted-foreground">Loading monitoring visits…</p> : filtered.length ? filtered.map((visit) => <VisitCard key={visit.id} visit={visit} canManage={canManage} onChanged={onChanged} />) : <EmptyPanel title="No visits match" description="Adjust the filters or schedule a monitoring visit." />}</TabsContent>
      <TabsContent value="calendar" className="space-y-4">{[...byDate].map(([month, items]) => <Card key={month}><CardHeader><CardTitle className="text-lg">{month}</CardTitle></CardHeader><CardContent className="space-y-2">{items.map((visit) => <div key={visit.id} className="grid gap-2 rounded-lg border p-3 text-sm sm:grid-cols-[120px_1fr_auto]"><span className="font-medium">{new Date(visit.planned_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span><span>{formatSite(visit.site_id)} · {visit.activity_type} · {visit.assigned_cra_id ?? 'Unassigned'}</span><StatusPill>{visit.status}</StatusPill></div>)}</CardContent></Card>)}{!filtered.length && !loading ? <EmptyPanel title="Calendar is clear" description="No visits match the current filters." /> : null}</TabsContent>
      <TabsContent value="workload"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[...byCra].map(([cra, items]) => <Card key={cra}><CardHeader><CardTitle className="text-lg">{cra}</CardTitle><CardDescription>{items.length} visit{items.length === 1 ? '' : 's'} in this result</CardDescription></CardHeader><CardContent className="space-y-2">{items.slice(0, 6).map((visit) => <div key={visit.id} className="flex items-center justify-between gap-2 text-sm"><span>{formatSite(visit.site_id)} · {formatDate(visit.planned_date)}</span><StatusPill>{visit.status}</StatusPill></div>)}</CardContent></Card>)}</div>{!filtered.length && !loading ? <EmptyPanel title="No workload data" description="Assign a CRA to scheduled visits to populate workload." /> : null}</TabsContent>
    </Tabs>
  </div>
}

function RiskView({ plans, visits, findings, versions, loading }: { plans: CTMSMonitoringPlan[]; visits: CTMSMonitoringActivity[]; findings: CTMSMonitoringFinding[]; versions: CTMSMonitoringPlanVersion[]; loading: boolean }) {
  const attention = buildSiteAttention(visits, findings)
  const high = attention.filter((item) => item.risk === 'High')
  const thresholds = versions.flatMap((version) => Object.entries(version.thresholds ?? {}).map(([name, value]) => ({ version, name, value })))
  return <div className="space-y-6">
    <Card className="border-blue-200 bg-blue-50/50"><CardContent className="flex gap-3 p-5"><Gauge className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" /><div><p className="font-medium">Risk signals support, but do not replace, clinical judgment.</p><p className="mt-1 text-sm text-muted-foreground">This MVP combines approved plan rules with operational signals. Authorized users must assess and approve any monitoring frequency adjustment.</p></div></CardContent></Card>
    <div className="grid gap-4 sm:grid-cols-3"><MetricCard loading={loading} label="Configured plans" value={plans.length} description={`${versions.filter((item) => item.status === 'Published' || item.status === 'Approved').length} approved or published versions`} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard loading={loading} label="High-attention sites" value={high.length} description="From overdue visits or serious findings" icon={<ShieldAlert className="h-5 w-5" />} /><MetricCard loading={loading} label="Defined thresholds" value={thresholds.length} description="Across current plan versions" icon={<Gauge className="h-5 w-5" />} /></div>
    <div className="grid gap-5 xl:grid-cols-2"><Card><CardHeader><CardTitle className="text-lg">Site signals</CardTitle><CardDescription>Operational evidence for review by the study team.</CardDescription></CardHeader><CardContent>{attention.length ? <div className="space-y-3">{attention.map((site) => <div key={site.siteId} className="flex items-center justify-between gap-3 rounded-lg border p-3"><div><p className="font-medium">{site.siteId}</p><p className="text-xs text-muted-foreground">{site.openFindings} open findings · {site.overdueVisits} overdue visits</p></div><StatusPill>{site.risk}</StatusPill></div>)}</div> : <EmptyPanel title="No site signals" description="Signals appear as site visits and findings are recorded." />}</CardContent></Card><Card><CardHeader><CardTitle className="text-lg">Approved risk configuration</CardTitle><CardDescription>Thresholds are inherited from version-controlled monitoring plans.</CardDescription></CardHeader><CardContent>{thresholds.length ? <div className="space-y-3">{thresholds.map(({ version, name, value }) => <div key={`${version.id}:${name}`} className="rounded-lg border p-3"><p className="font-medium capitalize">{name.replaceAll('_', ' ')}</p><p className="text-sm text-muted-foreground">{String(value)} · Plan v{version.version_number}</p></div>)}</div> : <EmptyPanel title="No structured thresholds" description="Add risk thresholds to an approved monitoring plan version." />}</CardContent></Card></div>
    <div className="flex flex-wrap gap-2"><a href="../rbm/ract"><Button variant="outline">Open RACT</Button></a><a href="../rbm/kri"><Button variant="outline">Open KRI workspace</Button></a></div>
  </div>
}

type VisitReportRecord = { visit: CTMSMonitoringActivity; report?: CTMSMonitoringReport }

function ReportsView({ visits, findings, reports, loading }: { visits: CTMSMonitoringActivity[]; findings: CTMSMonitoringFinding[]; reports: VisitReportRecord[]; loading: boolean }) {
  const eligible = visits.filter((visit) => visit.status !== 'Cancelled')
  const completed = eligible.filter((visit) => visit.status === 'Completed')
  const adherence = eligible.length ? Math.round((completed.length / eligible.length) * 100) : 0
  const finalized = reports.filter((item) => item.report?.status === 'Finalized')
  const turnaroundDays = finalized.flatMap(({ visit, report }) => {
    const from = visit.actual_end_at ?? visit.completed_at
    if (!from || !report?.finalized_at) return []
    return [Math.max(0, (new Date(report.finalized_at).getTime() - new Date(from).getTime()) / 86_400_000)]
  })
  const averageTurnaround = turnaroundDays.length ? `${(turnaroundDays.reduce((sum, value) => sum + value, 0) / turnaroundDays.length).toFixed(1)} days` : '—'
  const now = new Date().getTime()
  const overdueActions = findings.flatMap((finding) => finding.actions).filter((action) => action.status !== 'Completed' && action.due_date && new Date(action.due_date).getTime() < now)
  const workload = groupBy(visits, (visit) => visit.assigned_cra_id ?? 'Unassigned')
  return <div className="space-y-6">
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard loading={loading} label="Plan adherence" value={`${adherence}%`} description={`${completed.length} of ${eligible.length} visits completed`} icon={<ClipboardCheck className="h-5 w-5" />} /><MetricCard loading={loading} label="MVR finalized" value={finalized.length} description={`${reports.filter((item) => item.report && item.report.status !== 'Finalized').length} still in workflow`} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard loading={loading} label="MVR turnaround" value={averageTurnaround} description="Visit completion to finalization" icon={<BarChart3 className="h-5 w-5" />} /><MetricCard loading={loading} label="Overdue actions" value={overdueActions.length} description="Open action items past due" icon={<ListChecks className="h-5 w-5" />} /></div>
    <Card><CardHeader><CardTitle className="text-lg">Visit and MVR compliance</CardTitle><CardDescription>Latest report version for each monitoring visit.</CardDescription></CardHeader><CardContent>{reports.length ? <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left text-muted-foreground"><th className="pb-3">Visit</th><th className="pb-3">Site</th><th className="pb-3">Visit status</th><th className="pb-3">MVR status</th><th className="pb-3">Finalized</th></tr></thead><tbody>{reports.map(({ visit, report }) => <tr key={visit.id} className="border-b last:border-0"><td className="py-3"><p className="font-medium">{visit.visit_code ?? visit.activity_type}</p><p className="text-xs text-muted-foreground">{formatDate(visit.planned_date)}</p></td><td className="py-3">{visit.site_id ?? '—'}</td><td className="py-3"><StatusPill>{visit.status}</StatusPill></td><td className="py-3">{report ? <StatusPill>{report.status}</StatusPill> : <span className="text-muted-foreground">Not started</span>}</td><td className="py-3">{formatDate(report?.finalized_at)}</td></tr>)}</tbody></table></div> : <EmptyPanel title="No monitoring report data" description="Schedule visits and create MVRs to populate compliance reporting." />}</CardContent></Card>
    <Card><CardHeader><CardTitle className="text-lg">CRA workload</CardTitle><CardDescription>Current distribution of visits in this study.</CardDescription></CardHeader><CardContent><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{[...workload].map(([cra, items]) => <div key={cra} className="rounded-lg border p-4"><p className="font-medium">{cra}</p><p className="mt-1 text-2xl font-semibold">{items.length}</p><p className="text-xs text-muted-foreground">{items.filter((item) => !CLOSED_VISIT_STATUSES.has(item.status)).length} active · {items.filter((item) => item.status === 'Completed').length} completed</p></div>)}</div></CardContent></Card>
  </div>
}

export function MonitoringModulePage({ studyId, view }: { studyId: string; view: MonitoringModuleView }) {
  const plansQuery = useCTMSMonitoringPlans(studyId, { pagination: { pageSize: PAGE_SIZE } })
  const visitsQuery = useCTMSMonitoringActivities(studyId, { pagination: { pageSize: PAGE_SIZE } })
  const findingsQuery = useCTMSMonitoringFindings(studyId, { pagination: { pageSize: PAGE_SIZE } })
  const plans = plansQuery.data?.items ?? []
  const visits = visitsQuery.data?.items ?? []
  const findings = findingsQuery.data?.items ?? []
  const canManage = usePermission(PERMISSIONS.CTMS_MONITORING_ACTIVITY_MANAGEMENT, studyId)
  const versionQueries = useQueries({ queries: plans.map((plan) => ({ queryKey: ctmsKeys.monitoringPlanVersions(plan.id, { pagination: { pageSize: PAGE_SIZE } }), queryFn: () => ctmsApi.monitoringPlanVersions(plan.id, { pagination: { pageSize: PAGE_SIZE } }), enabled: view === 'risk' })) })
  const reportQueries = useQueries({ queries: visits.map((visit) => ({ queryKey: ctmsKeys.monitoringReports(visit.id), queryFn: () => ctmsApi.monitoringReports(visit.id), enabled: view === 'reports' })) })
  const versions = versionQueries.flatMap((query, index) => {
    const items = query.data?.items ?? []
    const current = items.find((version) => version.id === plans[index]?.current_version_id) ?? items.at(-1)
    return current ? [current] : []
  })
  const reportRecords = visits.map((visit, index) => ({ visit, report: reportQueries[index]?.data?.at(-1) }))
  const loading = plansQuery.isLoading || visitsQuery.isLoading || findingsQuery.isLoading || (view === 'risk' && versionQueries.some((query) => query.isLoading)) || (view === 'reports' && reportQueries.some((query) => query.isLoading))
  const config = VIEW_CONFIG[view]
  const refresh = () => { void plansQuery.refetch(); void visitsQuery.refetch(); void findingsQuery.refetch() }
  const content = view === 'overview' ? <OverviewView visits={visits} findings={findings} loading={loading} />
    : view === 'plans' ? <PlansView studyId={studyId} plans={plans} loading={plansQuery.isLoading} canManage={canManage} onChanged={refresh} />
      : view === 'visits' ? <VisitsView studyId={studyId} visits={visits} loading={visitsQuery.isLoading} canManage={canManage} onChanged={refresh} />
        : view === 'findings' ? <MonitoringFindingsPage studyId={studyId} embedded />
          : view === 'risk' ? <RiskView plans={plans} visits={visits} findings={findings} versions={versions} loading={loading} />
            : <ReportsView visits={visits} findings={findings} reports={reportRecords} loading={loading} />

  return <main className="space-y-0"><PageHeader title={config.label} description={config.description} status={<span className="rounded-full border bg-muted/40 px-2.5 py-1 text-xs">Study {studyId}</span>} /><MonitoringNavigation studyId={studyId} view={view} />{plansQuery.error || visitsQuery.error || findingsQuery.error ? <div role="alert" className="mb-5 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">Some monitoring data could not be loaded. Available records are shown below.</div> : null}{content}</main>
}
