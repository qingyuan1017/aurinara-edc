import { Link, useLocation } from '@tanstack/react-router'
import { ArrowRight, BookOpen, Building2, Layers, ShieldCheck } from 'lucide-react'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, MetricCard, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { useCTMSCapabilityState } from './capabilities'
import { findCTMSNavigationMatch, getCTMSWorkspaceFromPath } from './navigation'
import { useWorkspaceStudies } from './workspace-studies'

function CapabilityBoundary({ children }: { children: React.ReactNode }) {
  const state = useCTMSCapabilityState()
  const canRead = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)
  if (!canRead) return <AccessDeniedPage />
  if (state.status !== 'ready') return <PageContainer><EmptyState title={state.status === 'disabled' ? 'CTMS is disabled' : 'CTMS is unavailable'} description="The CTMS workspace is not currently available. EDC workflows remain available." /></PageContainer>
  return <>{children}</>
}

export function CTMSPortfolioWorkspacePage({ portfolioOnly = false }: { portfolioOnly?: boolean }) {
  const studies = useWorkspaceStudies()
  const items = studies.data?.items ?? []
  const active = items.filter((study) => String(study.status).toLowerCase() === 'active').length
  const statusCount = new Set(items.map((study) => study.status)).size

  return <CapabilityBoundary><PageContainer wide className="space-y-6">
    <PageHeader
      title={portfolioOnly ? 'Study Portfolio' : 'Portfolio Overview'}
      description={portfolioOnly ? 'Browse accessible canonical studies and enter a study workspace for operational execution.' : 'Cross-study operational oversight for the studies you are authorized to access.'}
      actions={<Button asChild variant="outline"><Link to="/ctms/studies">View study portfolio <ArrowRight className="size-4" /></Link></Button>}
    />
    {!portfolioOnly ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Accessible studies" value={studies.isLoading ? '—' : items.length} description="Server-authorized study records" icon={<BookOpen className="size-4" />} loading={studies.isLoading} />
      <MetricCard label="Active studies" value={studies.isLoading ? '—' : active} description="Canonical status is Active" icon={<ShieldCheck className="size-4" />} loading={studies.isLoading} />
      <MetricCard label="Lifecycle states" value={studies.isLoading ? '—' : statusCount} description="Statuses represented in this portfolio" icon={<Layers className="size-4" />} loading={studies.isLoading} />
      <MetricCard label="Workspace scope" value="Portfolio" description="Cross-study, permission-filtered context" icon={<Building2 className="size-4" />} />
    </div> : null}
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3"><div><CardTitle>{portfolioOnly ? 'All accessible studies' : 'Study workspaces'}</CardTitle><p className="mt-1 text-sm text-muted-foreground">Select a study to move from portfolio oversight into detailed operational execution.</p></div><span className="text-xs text-muted-foreground">{studies.data ? `${studies.data.total} total` : 'Loading…'}</span></CardHeader>
      <CardContent>
        {studies.isError ? <EmptyState title="Study portfolio could not be loaded" description="Retry when the study service is available." action={<Button variant="outline" onClick={() => void studies.refetch()}>Retry</Button>} /> : null}
        {!studies.isLoading && !studies.isError && items.length === 0 ? <EmptyState title="No accessible studies" description="No studies are available for the current server-authorized scope." /> : null}
        {items.length ? <div className="divide-y rounded-lg border">
          {items.map((study) => <Link key={study.id} to="/studies/$studyId/ctms" params={{ studyId: study.id }} className="group flex items-center gap-4 px-4 py-3 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">{study.study_code.slice(0, 2).toUpperCase()}</span>
            <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-foreground">{study.study_code}</span><span className="block truncate text-sm text-muted-foreground">{study.title}</span></span>
            <StatusBadge status={study.status} label="Study status" />
            <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>)}
        </div> : null}
      </CardContent>
    </Card>
    {!portfolioOnly ? <div className="rounded-xl border border-dashed bg-muted/25 p-5"><h2 className="text-sm font-semibold">Portfolio operations</h2><p className="mt-1 max-w-3xl text-sm text-muted-foreground">Cross-study monitoring, contracts, finance, tasks, resources, documents, and analytics are represented in the workspace navigation. Pages without a delivered aggregate API show an explicit planned-feature state rather than fabricated operational data.</p></div> : null}
  </PageContainer></CapabilityBoundary>
}

export function CTMSPlannedWorkspacePage() {
  const pathname = useLocation().pathname
  const match = findCTMSNavigationMatch(pathname)
  const workspace = getCTMSWorkspaceFromPath(pathname)
  const Icon = match?.item.icon ?? Layers
  const root = workspace?.kind === 'study' && workspace.studyId ? `/studies/${encodeURIComponent(workspace.studyId)}/ctms` : '/ctms'
  return <CapabilityBoundary><PageContainer wide>
    <PageHeader title={match?.item.label ?? 'CTMS workspace'} description={match?.item.description ?? 'This CTMS workspace is not configured.'} />
    <EmptyState
      icon={<Icon className="size-6" />}
      title={`${match?.item.label ?? 'This workspace'} is planned`}
      description="The navigation and study scope are ready, but no compatible production API is delivered for this view yet. Existing CTMS records remain in their current shared domain services."
      action={<Button asChild variant="outline"><Link to={root}>Return to {workspace?.kind === 'study' ? 'study dashboard' : 'portfolio overview'}</Link></Button>}
    />
  </PageContainer></CapabilityBoundary>
}
