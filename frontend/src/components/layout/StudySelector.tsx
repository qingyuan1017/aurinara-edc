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
      className="h-9 w-full rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
