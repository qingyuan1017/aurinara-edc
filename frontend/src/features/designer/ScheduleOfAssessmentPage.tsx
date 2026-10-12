import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type {
  ScheduleEntryCreate,
  ScheduleOfAssessmentCreate,
  ScheduleOfAssessmentResponse,
  VisitDefinitionResponse,
} from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FormActions, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { cn } from '@/lib/utils'
import { DraftGate, getApiErrorMessage } from './shared'
import { buildVisitHierarchy, flattenSelectableVisits } from './visitHierarchy'

interface FormDefinitionSummary {
  id: string
  name: string
  form_code: string
  display_order: number
}

/** A user-added procedure pseudo-row. Owns a required free-text procedure name. */
interface ProcedureRow {
  key: string
  name: string
}

/**
 * Local toggle state keyed by `${rowKey}::${visitId}`. A key present in the set
 * means the form/procedure (row) is scheduled at the visit (column).
 */
type CellSet = Set<string>

const makeKey = () => `proc-${Math.random().toString(36).slice(2)}`
const cellKey = (rowKey: string, visitId: string) => `${rowKey}::${visitId}`
const formRowKey = (formId: string) => `form:${formId}`
const procRowKey = (procKey: string) => `proc:${procKey}`

function isNotFound(error: unknown): boolean {
  return (error as { response?: { status?: number } })?.response?.status === 404
}

function ScheduleOfAssessmentEditor({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_SOA_CONFIGURE, studyId) && !readOnly

  const [cells, setCells] = useState<CellSet>(new Set())
  const [procedureRows, setProcedureRows] = useState<ProcedureRow[]>([])
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
    queryFn: async () => (await api.get<FormDefinitionSummary[]>(`/designer/studies/${studyId}/forms`, { params: { study_version_id: versionId } })).data,
  })

  // Sort each hierarchy level independently. Containers do not become columns,
  // but their visit descendants occupy the container's position in the matrix.
  const visitColumns = useMemo(
    () => flattenSelectableVisits(buildVisitHierarchy(visitsQuery.data ?? [])),
    [visitsQuery.data],
  )
  const visits = useMemo(() => visitColumns.map((column) => column.visit), [visitColumns])
  // Form rows ordered by form display_order, tie by id.
  const forms = useMemo(
    () => [...(formsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id)),
    [formsQuery.data],
  )

  // Seed local state from an existing SoA so the matrix round-trips. Adjusting
  // state during render (guarded by the last-seeded SoA id) is React's
  // recommended alternative to a setState-in-effect.
  const loadedSoa = soaQuery.data
  if (loadedSoa && loadedSoa.id !== seededSoaId) {
    setSeededSoaId(loadedSoa.id)
    const nextCells: CellSet = new Set()
    const nextProcedureRows: ProcedureRow[] = []
    const procByName = new Map<string, string>()
    for (const entry of loadedSoa.entries ?? []) {
      if (!entry.visit_definition_id) continue
      if (entry.form_definition_id) {
        nextCells.add(cellKey(formRowKey(entry.form_definition_id), entry.visit_definition_id))
      } else if (entry.procedure_name) {
        let key = procByName.get(entry.procedure_name)
        if (!key) {
          key = makeKey()
          procByName.set(entry.procedure_name, key)
          nextProcedureRows.push({ key, name: entry.procedure_name })
        }
        nextCells.add(cellKey(procRowKey(key), entry.visit_definition_id))
      }
    }
    setCells(nextCells)
    setProcedureRows(nextProcedureRows)
  }

  const toggleCell = (rowKey: string, visitId: string) => {
    if (!canConfigure) return
    setCells((prev) => {
      const next = new Set(prev)
      const key = cellKey(rowKey, visitId)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
    setMessage('')
  }

  const addProcedureRow = () => {
    setProcedureRows((prev) => [...prev, { key: makeKey(), name: '' }])
  }
  const updateProcedureName = (key: string, name: string) => {
    setProcedureRows((prev) => prev.map((row) => (row.key === key ? { ...row, name } : row)))
    setMessage('')
  }
  const removeProcedureRow = (key: string) => {
    setProcedureRows((prev) => prev.filter((row) => row.key !== key))
    setCells((prev) => {
      const next = new Set<string>()
      for (const cell of prev) {
        if (!cell.startsWith(`${procRowKey(key)}::`)) next.add(cell)
      }
      return next
    })
  }

  // A procedure row with a blank/whitespace name blocks save (mirrors the
  // server 422 for an empty procedure_name on a toggled cell).
  const invalidProcedureRows = useMemo(
    () => new Set(procedureRows.filter((row) => !row.name.trim()).map((row) => row.key)),
    [procedureRows],
  )
  // Only procedure rows that actually contribute entries need a valid name.
  const blockingProcedureRows = useMemo(() => {
    const blocking = new Set<string>()
    for (const row of procedureRows) {
      if (!row.name.trim()) {
        const hasToggle = [...cells].some((cell) => cell.startsWith(`${procRowKey(row.key)}::`))
        if (hasToggle) blocking.add(row.key)
      }
    }
    return blocking
  }, [procedureRows, cells])

  const buildPayload = (): ScheduleEntryCreate[] => {
    const entries: ScheduleEntryCreate[] = []
    let order = 1
    // Running index: iterate rows in render order (form rows, then procedure
    // rows by insertion order) x visits by display_order. The running counter
    // yields a stable display_order independent of row kind.
    for (const form of forms) {
      const rowKey = formRowKey(form.id)
      for (const visit of visits) {
        if (cells.has(cellKey(rowKey, visit.id))) {
          entries.push({
            form_definition_id: form.id,
            procedure_name: null,
            visit_definition_id: visit.id,
            display_order: order++,
          })
        }
      }
    }
    for (const row of procedureRows) {
      const name = row.name.trim()
      const rowKey = procRowKey(row.key)
      for (const visit of visits) {
        if (cells.has(cellKey(rowKey, visit.id))) {
          entries.push({
            form_definition_id: null,
            procedure_name: name,
            visit_definition_id: visit.id,
            display_order: order++,
          })
        }
      }
    }
    return entries
  }

  const save = useMutation({
    mutationFn: async () => {
      if (blockingProcedureRows.size) {
        throw new Error('Every scheduled procedure row needs a name before saving.')
      }
      const payload: ScheduleOfAssessmentCreate = { entries: buildPayload() }
      return (await api.post<ScheduleOfAssessmentResponse>(`/designer/versions/${versionId}/schedule-of-assessment`, payload)).data
    },
    onSuccess: () => {
      // The idempotent save replaces the prior SoA with a new row; invalidating
      // refetches it and the render-time seeding re-syncs when the id changes.
      client.invalidateQueries({ queryKey: ['designer-soa', versionId] })
      setError('')
      setMessage('Schedule of assessment saved.')
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not save the schedule of assessment.')); setMessage('') },
  })

  if (soaQuery.isLoading || visitsQuery.isLoading || formsQuery.isLoading) {
    return <PageContainer wide><LoadingState label="schedule of assessment" /></PageContainer>
  }

  const hasRows = forms.length > 0 || procedureRows.length > 0
  const hasColumns = visits.length > 0

  return (
    <PageContainer wide>
      <PageHeader
        title="Schedule of assessment"
        description="Toggle each form or procedure against standalone visits and cycle-owned child visits. Folder and cycle containers are intentionally excluded."
        actions={canConfigure ? <Button type="button" variant="outline" onClick={addProcedureRow}>Add procedure row</Button> : null}
      />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <Card>
        <CardHeader><CardTitle className="text-base">Matrix</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); save.mutate() }}>
            {!hasColumns ? (
              <Alert><AlertDescription>No visits defined yet. Add visits before building the schedule.</AlertDescription></Alert>
            ) : !hasRows ? (
              <Alert><AlertDescription>No forms defined yet. Add forms, or add a procedure row, before building the schedule.</AlertDescription></Alert>
            ) : (
              <div className="max-h-[70vh] w-full overflow-auto rounded-lg border" tabIndex={0} aria-label="Scrollable schedule of assessment matrix">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">Schedule of assessment matrix: rows are forms and procedures, columns are visits</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="sticky left-0 top-0 z-30 min-w-[14rem] border-b border-r bg-background p-2 text-left font-medium">
                        Form / procedure
                      </th>
                      {visitColumns.map(({ visit, parentName }) => (
                        <th
                          key={visit.id}
                          scope="col"
                          className="sticky top-0 z-20 min-w-[6rem] border-b bg-background p-2 text-center font-medium"
                        >
                          <span className="block">{visit.visit_number} · {visit.name}</span>
                          {parentName ? <span className="block text-[10px] font-normal text-muted-foreground">{parentName}</span> : null}
                          {visit.category ? <span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">{visit.category.replace('_', ' ')}</span> : null}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {forms.map((form) => {
                      const rowKey = formRowKey(form.id)
                      return (
                        <tr key={form.id}>
                          <th scope="row" className="sticky left-0 z-10 border-b border-r bg-background p-2 text-left font-normal">
                            <span className="font-medium">{form.form_code}</span> · {form.name}
                          </th>
                          {visits.map((visit) => {
                            const active = cells.has(cellKey(rowKey, visit.id))
                            return (
                              <td key={visit.id} className="border-b p-1 text-center">
                                <button
                                  type="button"
                                  role="checkbox"
                                  aria-checked={active}
                                  aria-label={`${form.form_code} at ${visit.name}`}
                                  disabled={!canConfigure}
                                  onClick={() => toggleCell(rowKey, visit.id)}
                                  className={cn(
                                    'mx-auto flex h-6 w-6 items-center justify-center rounded border text-xs transition-colors',
                                    active ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-background hover:bg-accent',
                                    !canConfigure && 'cursor-not-allowed opacity-60',
                                  )}
                                >
                                  {active ? '✓' : ''}
                                </button>
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                    {procedureRows.map((row) => {
                      const rowKey = procRowKey(row.key)
                      const invalid = invalidProcedureRows.has(row.key)
                      const blocking = blockingProcedureRows.has(row.key)
                      return (
                        <tr key={row.key}>
                          <th scope="row" className="sticky left-0 z-10 border-b border-r bg-background p-2 text-left font-normal align-top">
                            <div className="flex items-start gap-1">
                              <Input
                                aria-label="Procedure name"
                                value={row.name}
                                onChange={(event) => updateProcedureName(row.key, event.target.value)}
                                placeholder="Vitals"
                                aria-invalid={blocking || undefined}
                                className="h-8"
                                disabled={!canConfigure}
                              />
                              {canConfigure ? (
                                <Button type="button" variant="ghost" size="sm" aria-label="Remove procedure row" onClick={() => removeProcedureRow(row.key)}>×</Button>
                              ) : null}
                            </div>
                            {blocking ? <p className="mt-1 text-xs text-destructive">A scheduled procedure row needs a name.</p> : null}
                          </th>
                          {visits.map((visit) => {
                            const active = cells.has(cellKey(rowKey, visit.id))
                            return (
                              <td key={visit.id} className="border-b p-1 text-center">
                                <button
                                  type="button"
                                  role="checkbox"
                                  aria-checked={active}
                                  aria-label={`${row.name || 'Procedure'} at ${visit.name}`}
                                  disabled={!canConfigure}
                                  onClick={() => toggleCell(rowKey, visit.id)}
                                  className={cn(
                                    'mx-auto flex h-6 w-6 items-center justify-center rounded border text-xs transition-colors',
                                    active ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-background hover:bg-accent',
                                    invalid && active && 'border-destructive',
                                    !canConfigure && 'cursor-not-allowed opacity-60',
                                  )}
                                >
                                  {active ? '✓' : ''}
                                </button>
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {canConfigure ? (
              <FormActions
                pending={save.isPending}
                submitLabel="Save schedule"
                pendingLabel="Saving…"
                submitDisabled={!hasColumns || !hasRows || blockingProcedureRows.size > 0}
              />
            ) : null}
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
        {(versionId, selection) => <ScheduleOfAssessmentEditor studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
