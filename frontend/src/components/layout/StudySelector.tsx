import { useStudyContext } from '@/lib/study-context'

/**
 * Placeholder study data — replaced by API calls with TanStack Query
 * once the studies feature is connected.
 */
const PLACEHOLDER_STUDIES = [
  { id: 'study-1', name: 'TRIAL-001' },
  { id: 'study-2', name: 'TRIAL-002' },
]

/**
 * StudySelector — dropdown that lets users switch study context.
 * Stores the selected study ID in the global Zustand store.
 */
export function StudySelector() {
  const { selectedStudyId, setStudy } = useStudyContext()

  return (
    <select
      aria-label="Select study"
      value={selectedStudyId ?? ''}
      onChange={(e) => setStudy(e.target.value || null)}
      className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      <option value="">All Studies</option>
      {PLACEHOLDER_STUDIES.map((study) => (
        <option key={study.id} value={study.id}>
          {study.name}
        </option>
      ))}
    </select>
  )
}
