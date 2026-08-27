import { useStudyContext } from '@/lib/study-context'

/**
 * Placeholder site data — replaced by API calls with TanStack Query
 * once the sites feature is connected.
 */
const PLACEHOLDER_SITES = [
  { id: 'site-1', name: 'Site 001 – Boston' },
  { id: 'site-2', name: 'Site 002 – London' },
]

/**
 * SiteSelector — dropdown that lets users switch site context.
 * Stores the selected site ID in the global Zustand store.
 * Disabled when no study is selected.
 */
export function SiteSelector() {
  const { selectedStudyId, selectedSiteId, setSite } = useStudyContext()

  return (
    <select
      aria-label="Select site"
      value={selectedSiteId ?? ''}
      onChange={(e) => setSite(e.target.value || null)}
      disabled={!selectedStudyId}
      className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <option value="">All Sites</option>
      {PLACEHOLDER_SITES.map((site) => (
        <option key={site.id} value={site.id}>
          {site.name}
        </option>
      ))}
    </select>
  )
}
