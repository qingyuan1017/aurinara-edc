import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  DetailCard,
  OwnershipBadge,
  PageContainer,
  PageHeader,
  StatusBadge,
} from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { SignatureDialog } from '@/features/signatures'

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
    return <PageContainer><LoadingState label="subject casebook" /></PageContainer>
  }

  if (error) {
    return <PageContainer><ErrorState state="error" message="Failed to load casebook. Please try again." /></PageContainer>
  }

  if (!casebook) {
    return <PageContainer><EmptyState title="Casebook unavailable" description="No casebook data was returned for this subject." /></PageContainer>
  }

  return (
    <PageContainer>
      <PageHeader
        title={`Subject ${casebook.subject_number}`}
        description="Clinical visit and form structure"
        status={<StatusBadge status={casebook.status} label="Subject status" />}
        ownership={<OwnershipBadge owner="EDC" />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SignatureDialog objectType="subject" objectId={subjectId} buttonLabel="Sign subject" />
            <Button asChild variant="outline" size="sm"><a href={`/subjects/${subjectId}/signatures`}>Signatures</a></Button>
            <Button asChild variant="outline" size="sm"><a href={`/subjects/${subjectId}/visits`}>Manage visits</a></Button>
          </div>
        }
      />

      {casebook.visits.length === 0 ? (
        <EmptyState title="No visits scheduled for this subject." />
      ) : (
        <section aria-label="Casebook visits" className="space-y-3">
          {casebook.visits.map((visit) => (
            <VisitSection key={visit.visit_instance_id ?? visit.visit_definition_id} visit={visit} subjectId={subjectId} />
          ))}
        </section>
      )}
    </PageContainer>
  )
}

/** Expandable visit section */
function VisitSection({ visit, subjectId }: { visit: CasebookVisit; subjectId: string }) {
  const [isExpanded, setIsExpanded] = useState(false)

  const completedForms = visit.forms.filter(
    (form) => form.status.toLowerCase() === 'submitted' || form.status.toLowerCase() === 'locked',
  ).length
  const totalForms = visit.forms.length
  const visitId = visit.visit_instance_id ?? visit.visit_definition_id ?? 'visit'

  return (
    <DetailCard
      title={visit.name ?? 'Visit'}
      description={`${completedForms}/${totalForms} forms complete`}
      status={<StatusBadge status={visit.status} label="Visit status" />}
    >
      <button
        type="button"
        className="mb-3 flex w-full items-center justify-between rounded-md border bg-muted/30 px-3 py-2 text-left text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        onClick={() => setIsExpanded((expanded) => !expanded)}
        aria-expanded={isExpanded}
        aria-label={`${isExpanded ? 'Hide' : 'Show'} forms for ${visit.name ?? 'visit'}`}
      >
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="text-muted-foreground">{isExpanded ? '▼' : '▶'}</span>
          <span>{isExpanded ? 'Hide forms' : 'Show forms'}</span>
        </span>
        <span className="text-xs text-muted-foreground">{totalForms} total</span>
      </button>

      {isExpanded ? (
        <div id={`visit-${visitId}-forms`} className="divide-y rounded-md border" role="region" aria-label={`Forms for ${visit.name ?? 'visit'}`}>
          {visit.forms.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">No forms in this visit.</p>
          ) : (
            visit.forms.map((form) => (
              <a
                key={form.form_instance_id ?? form.form_definition_id}
                href={form.form_instance_id ? `/subjects/${subjectId}/forms/${form.form_instance_id}` : '#'}
                className="flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
              >
                <span className="text-foreground">{form.name ?? 'Form'}</span>
                <StatusBadge status={form.status} label="Form status" />
              </a>
            ))
          )}
        </div>
      ) : null}
    </DetailCard>
  )
}
