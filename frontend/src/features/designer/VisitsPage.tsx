import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { VisitDefinitionCreate, VisitDefinitionResponse, VisitDependencyCreate, VisitDependencyResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

const VISIT_TYPES = ['visit', 'cycle', 'scheduled', 'unscheduled', 'screening'] as const

function optionalNumber(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  return Number(trimmed)
}

/**
 * Per-visit visit->visit dependency editor.
 *
 * CRITICAL (Finding 2): the list endpoint returns ALL outgoing edges including
 * system-managed `cycle_member` membership edges. We filter client-side to
 * `prerequisite` and HIDE `cycle_member` rows (they have no delete path and
 * would misrepresent membership as authored dependencies). Listing + create
 * only (no delete endpoint).
 */
function VisitDependencyEditor({ visit, visits, canConfigure }: { visit: VisitDefinitionResponse; visits: VisitDefinitionResponse[]; canConfigure: boolean }) {
  const client = useQueryClient()
  const [dependsOn, setDependsOn] = useState('')
  const [condition, setCondition] = useState('')
  const [error, setError] = useState('')

  const depsQuery = useQuery({
    queryKey: ['designer-visit-dependencies', visit.id],
    queryFn: async () => (await api.get<VisitDependencyResponse[]>(`/designer/visits/${visit.id}/dependencies`)).data,
  })

  const create = useMutation({
    mutationFn: async () => {
      if (!dependsOn) throw new Error('Pick a prerequisite visit.')
      const payload: VisitDependencyCreate = {
        depends_on_visit_definition_id: dependsOn,
        dependency_type: 'prerequisite',
        condition_expression: condition.trim() || null,
      }
      return (await api.post<VisitDependencyResponse>(`/designer/visits/${visit.id}/dependencies`, payload)).data
    },
    onSuccess: () => {
      setError(''); setDependsOn(''); setCondition('')
      client.invalidateQueries({ queryKey: ['designer-visit-dependencies', visit.id] })
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not create the visit dependency.')),
  })

  const prerequisites = (depsQuery.data ?? []).filter((dep) => dep.dependency_type === 'prerequisite')
  const nameFor = (id: string) => visits.find((v) => v.id === id)?.name ?? id

  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Depends on</h4>
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      {prerequisites.length ? (
        <ul className="space-y-1 text-sm">
          {prerequisites.map((dep) => (
            <li key={dep.id} className="rounded bg-background px-2 py-1">
              {nameFor(dep.depends_on_visit_definition_id)}
              {dep.condition_expression ? <span className="text-muted-foreground"> · {dep.condition_expression}</span> : null}
            </li>
          ))}
        </ul>
      ) : <p className="text-xs text-muted-foreground">No prerequisites.</p>}
      {canConfigure ? (
        <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); create.mutate() }}>
          <select aria-label={`Prerequisite visit for ${visit.name}`} value={dependsOn} onChange={(event) => setDependsOn(event.target.value)} className="h-8 w-full rounded-md border bg-background px-2 text-sm">
            <option value="">— select prerequisite visit —</option>
            {visits.filter((v) => v.id !== visit.id).map((v) => <option key={v.id} value={v.id}>{v.visit_number} · {v.name}</option>)}
          </select>
          <Input aria-label={`Condition expression for ${visit.name}`} value={condition} onChange={(event) => setCondition(event.target.value)} placeholder="Optional condition expression" className="h-8" />
          <Button type="submit" size="sm" variant="outline" pending={create.isPending} loadingText="Adding…">Add prerequisite</Button>
        </form>
      ) : null}
    </div>
  )
}

function VisitsEditor({ studyId, versionId }: { studyId: string; versionId: string }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_VISIT_CONFIGURE, studyId)
  const [expandedVisitId, setExpandedVisitId] = useState('')

  const [name, setName] = useState('')
  const [visitNumber, setVisitNumber] = useState(1)
  const [visitType, setVisitType] = useState<string>('visit')
  const [repeatMin, setRepeatMin] = useState('')
  const [repeatMax, setRepeatMax] = useState('')
  const [cycleLength, setCycleLength] = useState('')
  const [targetDay, setTargetDay] = useState('')
  const [windowBefore, setWindowBefore] = useState('')
  const [windowAfter, setWindowAfter] = useState('')
  const [displayOrder, setDisplayOrder] = useState(1)
  const [isRequired, setIsRequired] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const visitsQuery = useQuery({
    queryKey: ['designer-visits', versionId],
    queryFn: async () => (await api.get<VisitDefinitionResponse[]>(`/designer/versions/${versionId}/visits`)).data,
  })

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('A visit name is required.')
      const isCycle = visitType === 'cycle'
      const payload: VisitDefinitionCreate = {
        name: name.trim(),
        visit_number: visitNumber,
        visit_type: visitType.trim(),
        target_day: optionalNumber(targetDay),
        window_before: optionalNumber(windowBefore),
        window_after: optionalNumber(windowAfter),
        display_order: displayOrder,
        is_required: isRequired,
        repeat_min: isCycle ? optionalNumber(repeatMin) : null,
        repeat_max: isCycle ? optionalNumber(repeatMax) : null,
        cycle_length: isCycle ? optionalNumber(cycleLength) : null,
      }
      return (await api.post<VisitDefinitionResponse>(`/designer/versions/${versionId}/visits`, payload)).data
    },
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['designer-visits', versionId] })
      setName(''); setTargetDay(''); setWindowBefore(''); setWindowAfter('')
      setRepeatMin(''); setRepeatMax(''); setCycleLength('')
      setVisitNumber((n) => n + 1); setDisplayOrder((order) => order + 1); setIsRequired(true)
      setError(''); setMessage(`Visit "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the visit.')); setMessage('') },
  })

  const rows = [...(visitsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order)

  if (visitsQuery.isLoading) return <PageContainer><LoadingState label="visit definitions" /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader title="Visits" description="Define study visits and cycles for the current draft version. Select the 'cycle' type to configure repeat counts and cycle length." />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {canConfigure ? (
          <Card>
            <CardHeader><CardTitle className="text-base">New visit</CardTitle></CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
                <FormField label="Name" name="visit-name" required>
                  <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Baseline" required />
                </FormField>
                <FormField label="Visit number" name="visit-number" required>
                  <Input type="number" min={1} max={9999} value={visitNumber} onChange={(event) => setVisitNumber(Number(event.target.value))} required />
                </FormField>
                <FormField label="Visit type" name="visit-type" required>
                  <select
                    id="field-visit-type"
                    value={visitType}
                    onChange={(event) => setVisitType(event.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  >
                    {VISIT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                  </select>
                </FormField>
                {visitType === 'cycle' ? (
                  <>
                    <FormField label="Repeat min" name="visit-repeat-min" description="Cycle-only: minimum repeat count.">
                      <Input type="number" min={0} max={99999} value={repeatMin} onChange={(event) => setRepeatMin(event.target.value)} />
                    </FormField>
                    <FormField label="Repeat max" name="visit-repeat-max" description="Cycle-only: maximum repeat count.">
                      <Input type="number" min={0} max={99999} value={repeatMax} onChange={(event) => setRepeatMax(event.target.value)} />
                    </FormField>
                    <FormField label="Cycle length" name="visit-cycle-length" description="Cycle-only: nominal length in days of one iteration.">
                      <Input type="number" min={0} max={99999} value={cycleLength} onChange={(event) => setCycleLength(event.target.value)} />
                    </FormField>
                  </>
                ) : null}
                <FormField label="Target day" name="visit-target-day" description="Optional day relative to baseline.">
                  <Input type="number" min={0} max={99999} value={targetDay} onChange={(event) => setTargetDay(event.target.value)} placeholder="0" />
                </FormField>
                <FormField label="Window before" name="visit-window-before" description="Optional days before target day.">
                  <Input type="number" min={0} max={99999} value={windowBefore} onChange={(event) => setWindowBefore(event.target.value)} />
                </FormField>
                <FormField label="Window after" name="visit-window-after" description="Optional days after target day.">
                  <Input type="number" min={0} max={99999} value={windowAfter} onChange={(event) => setWindowAfter(event.target.value)} />
                </FormField>
                <FormField label="Display order" name="visit-order" required>
                  <Input type="number" min={1} max={9999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required />
                </FormField>
                <div className="flex items-center gap-2">
                  <Checkbox id="field-visit-required" checked={isRequired} onChange={(event) => setIsRequired(event.target.checked)} />
                  <label htmlFor="field-visit-required" className="text-sm">Required visit</label>
                </div>
                <FormActions pending={create.isPending} submitLabel="Add visit" pendingLabel="Adding…" />
              </form>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Visit definitions</CardTitle>
            <span className="text-xs text-muted-foreground">{rows.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Visit definitions" empty={!rows.length} emptyTitle="No visits defined yet" emptyDescription="Visits you create appear here.">
              <Table>
                <caption className="sr-only">Visit definitions ordered by display order</caption>
                <TableHeader><TableRow>{['Order', '#', 'Name', 'Type', 'Repeat / length', 'Target day', 'Window -', 'Window +', 'Required', 'Dependencies'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{rows.map((row) => {
                  const expanded = expandedVisitId === row.id
                  return (
                    <Fragment key={row.id}>
                      <TableRow>
                        <TableCell>{row.display_order}</TableCell>
                        <TableCell>{row.visit_number}</TableCell>
                        <TableCell className="font-medium">{row.name}</TableCell>
                        <TableCell>{row.visit_type}</TableCell>
                        <TableCell>{row.visit_type === 'cycle' ? `${row.repeat_min ?? '—'}–${row.repeat_max ?? '—'} · ${row.cycle_length ?? '—'}d` : '—'}</TableCell>
                        <TableCell>{row.target_day ?? '—'}</TableCell>
                        <TableCell>{row.window_before ?? '—'}</TableCell>
                        <TableCell>{row.window_after ?? '—'}</TableCell>
                        <TableCell>{row.is_required ? 'Yes' : 'No'}</TableCell>
                        <TableCell>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? 'Hide' : 'Show'} dependencies for ${row.name}`}
                            onClick={() => setExpandedVisitId(expanded ? '' : row.id)}
                          >
                            {expanded ? 'Hide' : 'Depends on'}
                          </Button>
                        </TableCell>
                      </TableRow>
                      {expanded ? (
                        <TableRow>
                          <TableCell colSpan={10} className="bg-muted/20">
                            <VisitDependencyEditor visit={row} visits={rows} canConfigure={canConfigure} />
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  )
                })}</TableBody>
              </Table>
            </DataTableShell>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}

export function VisitsPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_VISIT_READ} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId) => <VisitsEditor studyId={studyId} versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
