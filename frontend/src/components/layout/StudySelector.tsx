import { useQuery } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { useStudyContext } from '@/lib/study-context'

interface StudyOption { id: string; study_code: string; title: string }

/**
 * StudySelector — dropdown that lets users switch study context.
 * Stores the selected study ID in the global Zustand store.
 */
export function StudySelector() {
  const { selectedStudyId, setStudy } = useStudyContext()
  const { data } = useQuery({
    queryKey: ['study-selector'],
    queryFn: async () => (await api.get<PaginatedResponse<StudyOption>>('/studies', {
      params: { page: 1, page_size: 100 },
    })).data,
  })

  return (
    <select
      aria-label="Select study"
      value={selectedStudyId ?? ''}
      onChange={(e) => setStudy(e.target.value || null)}
      className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      <option value="">All Studies</option>
      {data?.items.map((study) => (
        <option key={study.id} value={study.id}>
          {study.study_code} — {study.title}
        </option>
      ))}
    </select>
  )
}
