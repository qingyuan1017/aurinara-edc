import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { StatusBadge } from './components/StatusBadge'

/** A form within a visit */
export interface CasebookForm {
  form_instance_id: string | null
  form_definition_id: string | null
  name: string | null
  status: string
}

/** A visit section in the casebook */
export interface CasebookVisit {
  visit_instance_id: string | null
  visit_definition_id: string | null
  name: string | null
  status: string
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
        <a href={`/subjects/${subjectId}/visits`} className="rounded border px-3 py-2 text-sm text-blue-700 hover:bg-blue-50">Manage visits</a>
      </div>

      {/* Visit list */}
      <div className="space-y-3">
        {casebook.visits.length === 0 ? (
          <p className="text-gray-500 py-4">No visits scheduled for this subject.</p>
        ) : (
          casebook.visits.map((visit) => (
            <VisitSection key={visit.visit_instance_id ?? visit.visit_definition_id} visit={visit} subjectId={subjectId} />
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
  const visitId = visit.visit_instance_id ?? visit.visit_definition_id ?? 'visit'

  return (
    <div className="rounded-md border bg-white">
      <button
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        aria-controls={`visit-${visitId}-forms`}
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
            {visit.name ?? 'Visit'}
          </span>
        </div>
        <span className="text-sm text-gray-500">
          {completedForms}/{totalForms} forms complete
        </span>
      </button>

      {isExpanded && (
        <div
          id={`visit-${visitId}-forms`}
          className="border-t divide-y divide-gray-100"
          role="region"
          aria-label={`Forms for ${visit.name ?? 'visit'}`}
        >
          {visit.forms.length === 0 ? (
            <p className="px-4 py-3 text-sm text-gray-500">No forms in this visit.</p>
          ) : (
            visit.forms.map((form) => (
              <a
                key={form.form_instance_id ?? form.form_definition_id}
                href={form.form_instance_id ? `/subjects/${subjectId}/forms/${form.form_instance_id}` : '#'}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className="text-sm text-gray-900">{form.name ?? 'Form'}</span>
                <div className="flex items-center gap-3">
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
