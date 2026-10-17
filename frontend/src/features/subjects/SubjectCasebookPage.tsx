import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api, getApiErrorMessage } from '@/lib/api'
import type { SubjectPhaseStateResponse, SubjectPhaseUpdate } from '@/api/model'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  DetailCard,
  ConfirmDialog,
  OwnershipBadge,
  PageContainer,
  PageHeader,
  StatusBadge,
} from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
  study_version_id: string
  current_phase_definition_id?: string | null
  current_phase_name?: string | null
  current_phase_type?: string | null
  arm_definition_id?: string | null
  arm_name?: string | null
  visits: CasebookVisit[]
}

interface SubjectCasebookPageProps {
  subjectId: string
  studyId?: string
}

/**
 * SubjectCasebookPage — Shows the subject's visit/form structure.
 * Visits are expandable accordion sections, each containing forms with their status.
 */
export function SubjectCasebookPage({ subjectId, studyId }: SubjectCasebookPageProps) {
  const client = useQueryClient()
  const canUpdatePhase = usePermission(PERMISSIONS.SUBJECT_UPDATE)
  const [selectedPhaseId, setSelectedPhaseId] = useState('')
  const [selectedArmId, setSelectedArmId] = useState('')
  const [armDialogOpen, setArmDialogOpen] = useState(false)
  const [phaseError, setPhaseError] = useState('')
  const [reverseDialogOpen, setReverseDialogOpen] = useState(false)
  const [reverseError, setReverseError] = useState('')
  const { data: casebook, isLoading, error } = useQuery({
    queryKey: ['casebook', subjectId],
    queryFn: async () => {
      const response = await api.get<Casebook>(`/subjects/${subjectId}/casebook`)
      return response.data
    },
  })
  const { data: phaseState } = useQuery({
    queryKey: ['subject-phase', subjectId],
    queryFn: async () => {
      try {
        const response = await api.get<SubjectPhaseStateResponse>(`/subjects/${subjectId}/phase`)
        return Array.isArray(response?.data?.phases) ? response.data : null
      } catch {
        return null
      }
    },
  })
  const phaseMutation = useMutation({
    mutationFn: async (payload: SubjectPhaseUpdate) =>
      (await api.patch<SubjectPhaseStateResponse>(`/subjects/${subjectId}/phase`, payload)).data,
    onSuccess: () => {
      setPhaseError('')
      setArmDialogOpen(false)
      setSelectedPhaseId('')
      setSelectedArmId('')
      client.invalidateQueries({ queryKey: ['subject-phase', subjectId] })
      client.invalidateQueries({ queryKey: ['casebook', subjectId] })
      client.invalidateQueries({ queryKey: ['visits', subjectId] })
      client.invalidateQueries({ queryKey: ['addable-visits', subjectId] })
    },
    onError: () => setPhaseError('Could not update the subject phase.'),
  })
  const reversePhase = useMutation({
    mutationFn: async (reason: string) => api.post(`/subjects/${subjectId}/phase/reverse`, { reason }),
    onSuccess: () => {
      setReverseDialogOpen(false)
      setReverseError('')
      client.invalidateQueries({ queryKey: ['subject-phase', subjectId] })
      client.invalidateQueries({ queryKey: ['casebook', subjectId] })
      client.invalidateQueries({ queryKey: ['subjects'] })
      client.invalidateQueries({ queryKey: ['visits', subjectId] })
    },
    onError: (error) => setReverseError(getApiErrorMessage(error, 'The subject phase could not be reversed.')),
  })

  const chosenPhase = phaseState?.next_phases?.find((phase) => phase.id === selectedPhaseId)
  const requestPhaseUpdate = (phase: NonNullable<SubjectPhaseStateResponse['next_phases']>[number]) => {
    setSelectedPhaseId(phase.id)
    if (phase.phase_type === 'arm') {
      setArmDialogOpen(true)
      return
    }
    phaseMutation.mutate({ phase_definition_id: phase.id })
  }

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
        status={<StatusBadge status={phaseState?.current_phase_name ?? casebook.current_phase_name ?? casebook.status} label="Subject status" />}
        ownership={<OwnershipBadge owner="EDC" />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SignatureDialog objectType="subject" objectId={subjectId} buttonLabel="Sign subject" />
            <Button asChild variant="outline" size="sm"><Link to="/subjects/$subjectId/signatures" params={{ subjectId }}>Signatures</Link></Button>
            <Button asChild variant="outline" size="sm">
              {studyId
                ? <Link to="/studies/$studyId/edc/subjects/$subjectId/visits" params={{ studyId, subjectId }}>Manage visits</Link>
                : <Link to="/subjects/$subjectId/visits" params={{ subjectId }}>Manage visits</Link>}
            </Button>
          </div>
        }
      />

      {phaseState ? (
        <DetailCard
          title="Study phase"
          description="Study Data shows protocol visits for the subject's current phase."
          status={<StatusBadge status={phaseState.current_phase_type ?? 'not assigned'} label="Phase type" />}
        >
          <div className="space-y-3">
            <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
              <span className="text-muted-foreground">Current phase</span>
              <p className="font-medium">{phaseState.current_phase_name ?? 'Not assigned'}</p>
            </div>
            <div className="space-y-2" aria-label="Available phase transitions">
              <p className="text-sm font-medium">Available next phases</p>
              {(phaseState.next_phases ?? []).length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {(phaseState.next_phases ?? []).map((phase) => (
                    <Button
                      key={phase.id}
                      type="button"
                      variant="outline"
                      disabled={!canUpdatePhase || phaseMutation.isPending}
                      onClick={() => requestPhaseUpdate(phase)}
                    >
                      {phaseMutation.isPending && selectedPhaseId === phase.id ? 'Updating…' : `Move to ${phase.name}`}
                    </Button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No next phase is configured from the current phase.</p>
              )}
            </div>
            {phaseState.previous_phase ? (
              <div className="space-y-2 border-t pt-3">
                <p className="text-sm font-medium">Correction</p>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!canUpdatePhase || reversePhase.isPending}
                  onClick={() => {
                    setReverseError('')
                    setReverseDialogOpen(true)
                  }}
                >
                  Reverse to {phaseState.previous_phase.name}
                </Button>
                <p className="text-xs text-muted-foreground">Previously collected visits and clinical data remain retained.</p>
              </div>
            ) : null}
          </div>
          {phaseState.arm_name ? <p className="mt-2 text-sm text-muted-foreground">Assigned arm: {phaseState.arm_name}</p> : null}
          {phaseError ? <Alert variant="destructive" className="mt-3"><AlertDescription>{phaseError}</AlertDescription></Alert> : null}
        </DetailCard>
      ) : null}

      <Dialog open={armDialogOpen} onOpenChange={setArmDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Choose subject arm</DialogTitle>
            <DialogDescription>Select a configured arm before entering {chosenPhase?.name ?? 'the arm phase'}.</DialogDescription>
          </DialogHeader>
          <label className="space-y-1 text-sm">
            <span className="font-medium">Arm</span>
            <select aria-label="Subject arm" className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={selectedArmId} onChange={(event) => setSelectedArmId(event.target.value)}>
              <option value="">— select arm —</option>
              {(phaseState?.arms ?? []).map((arm) => <option key={arm.id} value={arm.id}>{arm.name}</option>)}
            </select>
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setArmDialogOpen(false)}>Cancel</Button>
            <Button type="button" disabled={!chosenPhase || !selectedArmId || phaseMutation.isPending} onClick={() => chosenPhase && phaseMutation.mutate({ phase_definition_id: chosenPhase.id, arm_definition_id: selectedArmId })}>
              {phaseMutation.isPending ? 'Assigning…' : 'Assign arm and continue'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={reverseDialogOpen}
        title="Reverse subject phase"
        description={`Return this subject to ${phaseState?.previous_phase?.name ?? 'the previous phase'} without deleting any visits, forms, or audit history.`}
        confirmLabel="Reverse phase"
        confirmVariant="default"
        pending={reversePhase.isPending}
        reason={{
          label: 'Reason for change',
          description: 'Required for the immutable audit trail.',
          required: true,
          maxLength: 4000,
        }}
        onConfirm={(reason) => {
          if (reason) reversePhase.mutate(reason)
        }}
        onCancel={() => {
          setReverseDialogOpen(false)
          setReverseError('')
        }}
      >
        {reverseError ? <Alert variant="destructive"><AlertDescription>{reverseError}</AlertDescription></Alert> : null}
      </ConfirmDialog>

      {casebook.visits.length === 0 ? (
        <EmptyState title="No visits scheduled for this subject." />
      ) : (
        <section aria-label="Casebook visits" className="space-y-3">
          {casebook.visits.map((visit) => (
            <VisitSection key={visit.visit_instance_id ?? visit.visit_definition_id} visit={visit} subjectId={subjectId} studyId={studyId} />
          ))}
        </section>
      )}
    </PageContainer>
  )
}

/** Expandable visit section */
function VisitSection({ visit, subjectId, studyId }: { visit: CasebookVisit; subjectId: string; studyId?: string }) {
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
              form.form_instance_id ? (
                studyId ? (
                  <Link
                    key={form.form_instance_id}
                    to="/studies/$studyId/edc/subjects/$subjectId/visits/$visitId/forms/$formId"
                    params={{ studyId, subjectId, visitId, formId: form.form_instance_id }}
                    className="flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  >
                    <span className="text-foreground">{form.name ?? 'Form'}</span>
                    <StatusBadge status={form.status} label="Data entry status" />
                  </Link>
                ) : (
                  <Link
                    key={form.form_instance_id}
                    to="/subjects/$subjectId/forms/$formInstanceId"
                    params={{ subjectId, formInstanceId: form.form_instance_id }}
                    className="flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  >
                    <span className="text-foreground">{form.name ?? 'Form'}</span>
                    <StatusBadge status={form.status} label="Data entry status" />
                  </Link>
                )
              ) : (
                <div key={form.form_definition_id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span className="text-foreground">{form.name ?? 'Form'}</span>
                  <StatusBadge status={form.status} label="Form status" />
                </div>
              )
            ))
          )}
        </div>
      ) : null}
    </DetailCard>
  )
}
