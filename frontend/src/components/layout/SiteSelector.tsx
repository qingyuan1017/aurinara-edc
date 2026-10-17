import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { api, type PaginatedResponse } from '@/lib/api'
import { useStudyContext } from '@/lib/study-context'

interface SiteOption { id: string; study_id?: string; site_number: string; name: string }

/**
 * SiteSelector — dropdown that lets users switch site context.
 * Stores the selected site ID in the global Zustand store.
 * Disabled when no study is selected.
 */
export function SiteSelector() {
  const { selectedStudyId, selectedSiteId, selectedSiteName, setSite } = useStudyContext()
  const { data } = useQuery({
    queryKey: ['site-selector', selectedStudyId],
    enabled: !!selectedStudyId,
    queryFn: async () => (await api.get<PaginatedResponse<SiteOption>>(
      `/studies/${selectedStudyId}/sites`, { params: { page: 1, page_size: 100 } },
    )).data,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

  const selectedSiteIsLoaded = data?.items.some((site) => site.id === selectedSiteId)
  const selectedSite = useQuery({
    queryKey: ['site-selector-selection', selectedSiteId],
    enabled: Boolean(data && selectedSiteId && !selectedSiteIsLoaded),
    queryFn: async () => (await api.get<SiteOption>(`/sites/${selectedSiteId}`)).data,
    retry: false,
  })

  useEffect(() => {
    const inaccessible = isAxiosError(selectedSite.error)
      && (selectedSite.error.response?.status === 403 || selectedSite.error.response?.status === 404)
    const belongsToAnotherStudy = selectedSite.data?.study_id !== undefined
      && selectedSite.data.study_id !== selectedStudyId
    if (selectedSiteId && (inaccessible || belongsToAnotherStudy)) {
      setSite(null)
    }
  }, [selectedSite.data, selectedSite.error, selectedSiteId, selectedStudyId, setSite])

  const selectedSiteLabel = selectedSite.data
    ? `${selectedSite.data.site_number} — ${selectedSite.data.name}`
    : selectedSiteName ?? 'Selected site'

  return (
    <select
      aria-label="Select site"
      value={selectedSiteId ?? ''}
      onChange={(event) => {
        const siteId = event.target.value || null
        const site = data?.items.find((item) => item.id === siteId)
        setSite(siteId, site ? `${site.site_number} — ${site.name}` : null)
      }}
      disabled={!selectedStudyId}
      className="h-9 w-full rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <option value="">All Sites</option>
      {selectedSiteId && !selectedSiteIsLoaded ? (
        <option value={selectedSiteId}>{selectedSiteLabel}</option>
      ) : null}
      {data?.items.map((site) => (
        <option key={site.id} value={site.id}>
          {site.site_number} — {site.name}
        </option>
      ))}
    </select>
  )
}
