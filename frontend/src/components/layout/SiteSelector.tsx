import { useQuery } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { useStudyContext } from '@/lib/study-context'

interface SiteOption { id: string; site_number: string; name: string }

/**
 * SiteSelector — dropdown that lets users switch site context.
 * Stores the selected site ID in the global Zustand store.
 * Disabled when no study is selected.
 */
export function SiteSelector() {
  const { selectedStudyId, selectedSiteId, setSite } = useStudyContext()
  const { data } = useQuery({
    queryKey: ['site-selector', selectedStudyId],
    enabled: !!selectedStudyId,
    queryFn: async () => (await api.get<PaginatedResponse<SiteOption>>(
      `/studies/${selectedStudyId}/sites`, { params: { page: 1, page_size: 100 } },
    )).data,
  })

  return (
    <select
      aria-label="Select site"
      value={selectedSiteId ?? ''}
      onChange={(e) => setSite(e.target.value || null)}
      disabled={!selectedStudyId}
      className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <option value="">All Sites</option>
      {data?.items.map((site) => (
        <option key={site.id} value={site.id}>
          {site.site_number} — {site.name}
        </option>
      ))}
    </select>
  )
}
