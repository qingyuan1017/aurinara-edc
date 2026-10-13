import { useQuery } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'

export interface WorkspaceStudy {
  id: string
  study_code: string
  title: string
  status: string
}

export function useWorkspaceStudies(enabled = true) {
  return useQuery({
    queryKey: ['ctms-workspace-studies'],
    queryFn: async () => (await api.get<PaginatedResponse<WorkspaceStudy>>('/studies', { params: { page: 1, page_size: 100 } })).data,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    enabled,
  })
}
