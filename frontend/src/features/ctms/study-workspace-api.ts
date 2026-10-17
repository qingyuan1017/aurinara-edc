import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'

export type StudyWorkspaceView =
  | 'summary' | 'health' | 'activity' | 'team' | 'amendments' | 'sites'
  | 'feasibility' | 'startup' | 'performance' | 'closeout' | 'action-items'
  | 'issues' | 'escalations' | 'capas' | 'ract' | 'kris'
  | 'protocol-deviations' | 'icf-rollouts' | 'tracking-logs'

export interface StudyWorkspaceRow { id?: string; source_id?: string; site_id?: string; title?: string; name?: string; status?: string; destination_path?: string; version?: number; [key: string]: unknown }
export interface StudySummary { study_id: string; site_count: number; active_sites: number; enrollment: Record<string, unknown>; monitoring: Record<string, unknown>; work: Record<string, unknown>; capas: Record<string, unknown>; contracts: Record<string, unknown>; financials_by_currency: Array<Record<string, unknown>>; generated_at: string }
export interface HealthSignal { dimension: string; status: 'Green' | 'Amber' | 'Red' | 'Unknown'; summary: string; factors: Array<Record<string, unknown>>; source_date?: string | null; destination_path: string }

const paths: Record<Exclude<StudyWorkspaceView, 'summary' | 'health'>, string> = {
  activity: 'activity', team: 'team', amendments: 'amendments', sites: 'sites',
  feasibility: 'sites/feasibility', startup: 'sites/startup', performance: 'sites/performance',
  closeout: 'sites/closeout', 'action-items': 'action-items', issues: 'issues',
  escalations: 'escalations', capas: 'capas', ract: 'risk-assessments', kris: 'kris',
  'protocol-deviations': 'protocol-deviations', 'icf-rollouts': 'icf-rollouts',
  'tracking-logs': 'tracking-logs',
}

const root = (studyId: string) => `/ctms/studies/${encodeURIComponent(studyId)}`
async function get<T>(path: string) { return (await api.get<T>(path)).data }

export const studyWorkspaceApi = {
  summary: (studyId: string) => get<StudySummary>(`${root(studyId)}/summary`),
  health: (studyId: string) => get<HealthSignal[]>(`${root(studyId)}/operational-health`),
  list: (studyId: string, view: Exclude<StudyWorkspaceView, 'summary' | 'health'>, page = 1, search = '') => {
    const query = new URLSearchParams({ page: String(page), page_size: '25' })
    if (search) query.set('search', search)
    return get<PaginatedResponse<StudyWorkspaceRow>>(`${root(studyId)}/${paths[view]}?${query}`)
  },
  transition: (studyId: string, view: StudyWorkspaceView, id: string, status: string, reason: string, expectedVersion?: number) => {
    const route = view === 'amendments' ? `amendments/${id}`
      : view === 'closeout' ? `sites/closeout/${id}`
      : view === 'ract' ? `risk-assessments/${id}`
      : view === 'kris' ? `kris/${id}`
      : view === 'protocol-deviations' ? `protocol-deviations/${id}`
      : view === 'icf-rollouts' ? `icf-rollouts/${id}` : null
    if (!route) throw new Error('This queue delegates changes to its authoritative study service.')
    return api.post(`${root(studyId)}/${route}/transition`, { status, reason, expected_version: expectedVersion })
  },
}

export function useStudyWorkspaceSummary(studyId: string, enabled = true) { return useQuery({ queryKey: ['ctms','study-workspace',studyId,'summary'], queryFn: () => studyWorkspaceApi.summary(studyId), enabled }) }
export function useStudyWorkspaceHealth(studyId: string, enabled = true) { return useQuery({ queryKey: ['ctms','study-workspace',studyId,'health'], queryFn: () => studyWorkspaceApi.health(studyId), enabled }) }
export function useStudyWorkspaceList(studyId: string, view: Exclude<StudyWorkspaceView, 'summary' | 'health'>, page: number, search: string, enabled = true) { return useQuery({ queryKey: ['ctms','study-workspace',studyId,view,page,search], queryFn: () => studyWorkspaceApi.list(studyId,view,page,search), enabled }) }
export function useStudyWorkspaceTransition(studyId: string) { const client = useQueryClient(); return useMutation({ mutationFn: ({view,id,status,reason,expectedVersion}:{view:StudyWorkspaceView;id:string;status:string;reason:string;expectedVersion?:number}) => studyWorkspaceApi.transition(studyId,view,id,status,reason,expectedVersion), onSuccess: () => client.invalidateQueries({queryKey:['ctms','study-workspace',studyId]}) }) }
