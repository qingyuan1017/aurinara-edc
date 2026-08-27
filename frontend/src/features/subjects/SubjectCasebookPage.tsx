import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { StatusBadge } from './components/StatusBadge'

/** A form within a visit */
export interface CasebookForm {
  id: string
  form_name: string
  status: string
  query_count: number
}

/** A visit section in the casebook */
export interface CasebookVisit {
  id: string
  visit_name: string
  visit_number: number
  forms: CasebookForm[]
}

/** Full casebook response */
export interface Casebook {
  subject_id: string
  subject_number: string
  status: string
  visits: CasebookVisit[]
}

interface SubjectCasebookPageProps {
  subjectId: string
}

/**
 * SubjectCasebookPage — Shows the subject's visit/form structure.
 * Visits are expandable accordion sections, each containing forms with their status.
 */
export function SubjectCasebookPage({ subjectId }: SubjectCasebookPageProps) {
  const { data: casebook, isLoading, error } = useQuery({
    queryKey: ['casebook', subjectId],
    queryFn: async () => {
      const response = await api.get<Casebook>(`/subjects/${subjectId}/casebook`)
      return response.data
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-gray-500">Loading casebook…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4">
        <p className="text-sm text-red-700">Failed to load casebook. Please try again.</p>
      </div>
    )
  }

  if (!casebook) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-gray-900">
            Subject {casebook.subject_number}
          </h1>
          <StatusBadge domain="subject" status={casebook.status} />
        </div>
      </div>

      {/* Visit list */}
      <div className="space-y-3">
        {casebook.visits.length === 0 ? (
          <p className="text-gray-500 py-4">No visits scheduled for this subject.</p>
        ) : (
          casebook.visits.map((visit) => (
            <VisitSection key={visit.id} visit={visit} subjectId={subjectId} />
          ))
        )}
      </div>
    </div>
  )
}

/** Expandable visit section */
function VisitSection({
  visit,
  subjectId,
}: {
  visit: CasebookVisit
  subjectId: string
}) {
  const [isExpanded, setIsExpanded] = useState(false)

  const completedForms = visit.forms.filter(
    (f) => f.status.toLowerCase() === 'submitted' || f.status.toLowerCase() === 'locked',
  ).length
  const totalForms = visit.forms.length

  return (
    <div className="rounded-md border bg-white">
      <button
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        aria-controls={`visit-${visit.id}-forms`}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-gray-400 transition-transform duration-200"
            style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
            aria-hidden="true"
          >
            ▶
          </span>
          <span className="font-medium text-gray-900">
            Visit {visit.visit_number}: {visit.visit_name}
          </span>
        </div>
        <span className="text-sm text-gray-500">
          {completedForms}/{totalForms} forms complete
        </span>
      </button>

      {isExpanded && (
        <div
          id={`visit-${visit.id}-forms`}
          className="border-t divide-y divide-gray-100"
          role="region"
          aria-label={`Forms for ${visit.visit_name}`}
        >
          {visit.forms.length === 0 ? (
            <p className="px-4 py-3 text-sm text-gray-500">No forms in this visit.</p>
          ) : (
            visit.forms.map((form) => (
              <a
                key={form.id}
                href={`/subjects/${subjectId}/forms/${form.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className="text-sm text-gray-900">{form.form_name}</span>
                <div className="flex items-center gap-3">
                  {form.query_count > 0 && (
                    <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                      {form.query_count} {form.query_count === 1 ? 'query' : 'queries'}
                    </span>
                  )}
                  <StatusBadge domain="form" status={form.status} />
                </div>
              </a>
            ))
          )}
        </div>
      )}
    </div>
  )
}
