import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { ScheduleEntryCreate, ScheduleOfAssessmentCreate, ScheduleOfAssessmentResponse, VisitDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

interface EntryDraft {
  key: string
  what: 'form' | 'procedure'
  formDefinitionId: string
  procedureName: string
  visitDefinitionId: string
}

interface FormDefinitionSummary {
  id: string
  name: string
  form_code: string
}

const makeKey = () => Math.random().toString(36).slice(2)
const emptyEntry = (): EntryDraft => ({ key: makeKey(), what: 'form', formDefinitionId: '', procedureName: '', visitDefinitionId: '' })

function isNotFound(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 404
}

function ScheduleOfAssessmentEditor({ studyId, versionId }: { studyId: string; versionId: string }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_SOA_CONFIGURE, studyId)
  const [entries, setEntries] = useState<EntryDraft[]>([emptyEntry()])
  const [seededSoaId, setSeededSoaId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const soaQuery = useQuery({
    queryKey: ['designer-soa', versionId],
    queryFn: async () => {
      try {
        return (await api.get<ScheduleOfAssessmentResponse>(`/designer/versions/${versionId}/schedule-of-assessment`)).data
      } catch (err) {
        if (isNotFound(err)) return null
        throw err
      }
    },
    retry: false,
  })

  const visitsQuery = useQuery({
    queryKey: ['designer-visits', versionId],
    queryFn: async () => (await api.get<VisitDefinitionResponse[]>(`/designer/versions/${versionId}/visits`)).data,
  })
  const formsQuery = useQuery({
    queryKey: ['form-definitions', studyId],
    queryFn: async () => (await api.get<FormDefinitionSummary[]>(`/designer/studies/${studyId}/forms`)).data,
  })
  const visits = visitsQuery.data ?? []
  const forms = formsQuery.data ?? []

  // Seed the editor from an existing SoA so the matrix can be reviewed/extended.
  // Adjusting state during render (guarded by the last-seeded SoA id) is the
  // React-recommended alternative to a setState-in-effect, which the compiler
  // flags as a cascading render.
  const loadedSoa = soaQuery.data
  if (loadedSoa && loadedSoa.id !== seededSoaId) {
    setSeededSoaId(loadedSoa.id)
    const existing = loadedSoa.entries
    if (existing && existing.length) {
      setEntries(existing
        .slice()
        .sort((a, b) => a.display_order - b.display_order)
        .map((entry) => ({
          key: makeKey(),
          what: entry.form_definition_id ? 'form' : 'procedure',
          formDefinitionId: entry.form_definition_id ?? '',
          procedureName: entry.procedure_name ?? '',
          visitDefinitionId: entry.visit_definition_id ?? '',
        })))
    }
  }

  const save = useMutation({
    mutationFn: async () => {
      const payloadEntries: ScheduleEntryCreate[] = entries.map((entry, index) => {
        const hasForm = entry.what === 'form' && entry.formDefinitionId.trim()
        const hasProcedure = entry.what === 'procedure' && entry.procedureName.trim()
        if (!hasForm && !hasProcedure) {
          throw new Error(`Entry ${index + 1} needs a form definition ID or a procedure name.`)
        }
        if (!entry.visitDefinitionId.trim()) {
          throw new Error(`Entry ${index + 1} needs a visit definition ID.`)
        }
        return {
          form_definition_id: hasForm ? entry.formDefinitionId.trim() : null,
          procedure_name: hasProcedure ? entry.procedureName.trim() : null,
          visit_definition_id: entry.visitDefinitionId.trim() || null,
          display_order: index + 1,
        }
      })
      const payload: ScheduleOfAssessmentCreate = { entries: payloadEntries }
      return (await api.post<ScheduleOfAssessmentResponse>(`/designer/versions/${versionId}/schedule-of-assessment`, payload)).data
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['designer-soa', versionId] })
      setError(''); setMessage('Schedule of assessment saved.')
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not save the schedule of assessment.')); setMessage('') },
  })

  const update = (key: string, patch: Partial<EntryDraft>) => setEntries((prev) => prev.map((entry) => entry.key === key ? { ...entry, ...patch } : entry))

  if (soaQuery.isLoading) return <PageContainer><LoadingState label="schedule of assessment" /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader
        title="Schedule of assessment"
        description="Map forms and procedures to visits for the current draft version."
        actions={canConfigure ? <Button type="button" variant="outline" onClick={() => setEntries((prev) => [...prev, emptyEntry()])}>Add entry</Button> : null}
      />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <Card>
        <CardHeader><CardTitle className="text-base">SoA entries</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); save.mutate() }}>
            <DataTableShell label="Schedule of assessment entries">
              <Table>
                <caption className="sr-only">Schedule of assessment entries</caption>
                <TableHeader><TableRow>{['Collect', 'What', 'Visit', ''].map((heading, index) => <TableHead key={heading || index}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{entries.map((entry, index) => (
                  <TableRow key={entry.key}>
                    <TableCell>
                      <select
                        aria-label={`Entry ${index + 1} collection type`}
                        value={entry.what}
                        onChange={(event) => update(entry.key, { what: event.target.value as EntryDraft['what'] })}
                        className="h-9 rounded-md border bg-background px-2 text-sm"
                      >
                        <option value="form">Form</option>
                        <option value="procedure">Procedure</option>
                      </select>
                    </TableCell>
                    <TableCell>
                      {entry.what === 'form' ? (
                        <select
                          aria-label={`Entry ${index + 1} form`}
                          value={entry.formDefinitionId}
                          onChange={(event) => update(entry.key, { formDefinitionId: event.target.value })}
                          className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                        >
                          <option value="">— select form —</option>
                          {forms.map((form) => <option key={form.id} value={form.id}>{form.form_code} · {form.name}</option>)}
                        </select>
                      ) : (
                        <Input aria-label={`Entry ${index + 1} procedure name`} value={entry.procedureName} onChange={(event) => update(entry.key, { procedureName: event.target.value })} placeholder="Vitals" />
                      )}
                    </TableCell>
                    <TableCell>
                      <select
                        aria-label={`Entry ${index + 1} visit`}
                        value={entry.visitDefinitionId}
                        onChange={(event) => update(entry.key, { visitDefinitionId: event.target.value })}
                        className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                      >
                        <option value="">— none —</option>
                        {visits.map((visit) => <option key={visit.id} value={visit.id}>{visit.visit_number} · {visit.name}</option>)}
                      </select>
                    </TableCell>
                    <TableCell><Button type="button" variant="ghost" size="sm" aria-label={`Remove entry ${index + 1}`} disabled={entries.length === 1} onClick={() => setEntries((prev) => prev.filter((it) => it.key !== entry.key))}>Remove</Button></TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </DataTableShell>
            {canConfigure ? <FormActions pending={save.isPending} submitLabel="Save schedule" pendingLabel="Saving…" /> : null}
          </form>
        </CardContent>
      </Card>
    </PageContainer>
  )
}

export function ScheduleOfAssessmentPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_SOA_READ} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId) => <ScheduleOfAssessmentEditor studyId={studyId} versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
