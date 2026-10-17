import { useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Briefcase, Gauge, Layers, ListTodo, Search, Shield, TrendingUp, UserRound, Workflow } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, ErrorState, LoadingState, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { Input } from '@/components/ui/input'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import { usePortfolioAction, usePortfolioManagementList } from './portfolio-management-api'

export type PortfolioManagementView = 'work'|'templates'|'feasibility'|'performance'|'tasks'|'issues'|'escalations'|'capas'|'assignments'|'capacity'|'workflows'
const config: Record<PortfolioManagementView,{title:string;description:string;icon:typeof Briefcase}> = {
  work:{title:'My Work',description:'Your assigned operational work across authorized studies.',icon:Briefcase}, templates:{title:'Study Templates',description:'Published operational setup templates that can be applied to existing studies.',icon:Layers}, feasibility:{title:'Site Feasibility Pipeline',description:'Questionnaire, review, and selection status across authorized studies.',icon:Search}, performance:{title:'Cross-Study Site Performance',description:'Transparent, versioned operational scorecards with component coverage.',icon:TrendingUp}, tasks:{title:'My Tasks',description:'Operational tasks assigned to you across authorized studies.',icon:ListTodo}, issues:{title:'All Issues',description:'A normalized view of findings, blocked tasks, and overdue operational work.',icon:AlertTriangle}, escalations:{title:'Escalations & CAPA',description:'Escalated tasks and corrective action oversight.',icon:Shield}, capas:{title:'Corrective Action Plans',description:'Root-cause, implementation, effectiveness, and closure tracking.',icon:Shield}, assignments:{title:'CRA Assignments',description:'Effective-dated CRA allocation across studies and sites.',icon:UserRound}, capacity:{title:'Capacity & Utilization',description:'Weekly capacity, availability exceptions, allocations, and visit workload.',icon:Gauge}, workflows:{title:'Workflow Rules',description:'Versioned, allowlisted operational automation without arbitrary code.',icon:Workflow},
}

function value(row: Record<string, unknown>, ...keys: string[]) { for (const key of keys) if (row[key] !== undefined && row[key] !== null && row[key] !== '') return String(row[key]); return '—' }
function title(row: Record<string, unknown>) { return value(row,'title','name','task_title','site_name','user_name') }
function subtitle(row: Record<string, unknown>) { const study=value(row,'study_code'); const site=value(row,'site_label','site_number'); return [study==='—'?null:study,site==='—'?null:site].filter(Boolean).join(' · ') || value(row,'template_type','trigger_type','source_type') }
function destination(row: Record<string, unknown>) { return typeof row.destination_path === 'string' ? row.destination_path : null }

export function PortfolioManagementPage({view,admin=false}:{view:PortfolioManagementView;admin?:boolean}) {
  const [search,setSearch]=useState('')
  const canManageCapa=usePermission(PERMISSIONS.CTMS_CAPA_MANAGEMENT)
  const canManageTemplates=usePermission(PERMISSIONS.CTMS_TEMPLATE_RULE_MANAGEMENT)
  const query=usePortfolioManagementList(view,{page:1,page_size:100,mine:view==='tasks'?true:undefined})
  const action=usePortfolioAction()
  const filtered=useMemo(()=>((query.data?.items ?? []) as Record<string,unknown>[]).filter(row=>JSON.stringify(row).toLowerCase().includes(search.toLowerCase())),[query.data?.items,search])
  const page=view==='templates'&&admin?{...config.templates,title:'Administration Templates',description:'Author, version, publish, and retire reusable operational templates.'}:config[view]; const Icon=page.icon
  const transition=(kind:'feasibility'|'capa'|'template'|'template-retire'|'workflow',id:string,status:string)=>{ const reason=window.prompt(`Reason for ${status}`); if(reason?.trim()) action.mutate({kind,id,status,reason:reason.trim()}) }
  return <PageContainer wide className="space-y-5">
    <PageHeader title={page.title} description={page.description} />
    <div className="relative max-w-md"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground"/><Input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Filter this queue" className="pl-9" aria-label={`Filter ${page.title}`} /></div>
    {query.isLoading?<LoadingState label={page.title}/>:null}
    {query.isError?<ErrorState state="error" message={`${page.title} could not be loaded.`} onRetry={()=>void query.refetch()}/>:null}
    {!query.isLoading&&!query.isError&&!filtered.length?<EmptyState icon={<Icon className="size-6"/>} title={`No ${page.title.toLowerCase()} found`} description="No records match the current authorized scope and filter."/>:null}
    {filtered.length?<Card><CardHeader className="flex-row items-center justify-between"><CardTitle>{page.title}</CardTitle><span className="text-xs text-muted-foreground">{filtered.length} of {query.data?.total ?? filtered.length}</span></CardHeader><CardContent className="divide-y rounded-lg border p-0">
      {filtered.map((row,index)=>{ const id=value(row,'id','source_id','user_id'); const status=value(row,'status','version_status'); const target=destination(row); return <div key={`${id}-${index}`} className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon className="size-4"/></div>
        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{title(row)}</p><p className="mt-0.5 text-xs text-muted-foreground">{subtitle(row)}</p>
          {view==='performance'?<p className="mt-1 text-xs">Score {value(row,'overall_score')} · Coverage {value(row,'coverage_percent')}%</p>:null}
          {view==='capacity'?<p className="mt-1 text-xs">{value(row,'allocated_hours')}h allocated / {value(row,'available_hours')}h available · {value(row,'utilization_percent')}%</p>:null}
          {view==='capacity'?<p className="mt-1 text-xs text-muted-foreground">{value(row,'upcoming_visits')} upcoming visits · {value(row,'overdue_visits')} overdue visits</p>:null}
          {view==='issues' || view==='work' || view==='tasks'?<p className="mt-1 text-xs">Due {row.due_at?new Date(String(row.due_at)).toLocaleDateString():'not set'}{row.is_overdue?' · Overdue':''}</p>:null}
        </div>
        {status!=='—'?<StatusBadge status={status} label="Status"/>:null}
        <div className="flex flex-wrap gap-2">
          {view==='feasibility'&&status==='Draft'?<Button size="sm" variant="outline" pending={action.isPending} onClick={()=>transition('feasibility',id,'Questionnaire Sent')}>Send</Button>:null}
          {view==='feasibility'&&status==='Under Review'?<><Button size="sm" variant="outline" pending={action.isPending} onClick={()=>transition('feasibility',id,'Selected')}>Select</Button><Button size="sm" variant="ghost" pending={action.isPending} onClick={()=>transition('feasibility',id,'Not Selected')}>Decline</Button></>:null}
          {view==='capas'&&canManageCapa&&status==='Effectiveness Review'?<Button size="sm" variant="outline" pending={action.isPending} onClick={()=>transition('capa',id,'Closed')}>Close</Button>:null}
          {view==='templates'&&canManageTemplates&&status==='Draft'&&row.version_id?<Button size="sm" variant="outline" pending={action.isPending} onClick={()=>transition('template',String(row.version_id),'Published')}>Publish</Button>:null}
          {view==='templates'&&admin&&canManageTemplates&&!row.retired_at?<Button size="sm" variant="ghost" pending={action.isPending} onClick={()=>transition('template-retire',id,'Retired')}>Retire</Button>:null}
          {view==='workflows'&&canManageTemplates&&row.version_id&&(status==='Draft'||status==='Paused')?<Button size="sm" variant="outline" pending={action.isPending} onClick={()=>transition('workflow',String(row.version_id),'Published')}>Publish</Button>:null}
          {view==='workflows'&&canManageTemplates&&row.version_id&&status==='Published'?<><Button size="sm" variant="outline" pending={action.isPending} onClick={()=>transition('workflow',String(row.version_id),'Paused')}>Pause</Button><Button size="sm" variant="ghost" pending={action.isPending} onClick={()=>transition('workflow',String(row.version_id),'Retired')}>Retire</Button></>:null}
          {target?<Button asChild size="sm" variant="ghost"><a href={target}>Open <ArrowRight className="size-4"/></a></Button>:null}
        </div>
      </div>})}
    </CardContent></Card>:null}
  </PageContainer>
}
