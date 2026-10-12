import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { VisitCategory, VisitDefinitionCreate, VisitDefinitionKind, VisitDefinitionResponse, VisitDependencyCreate, VisitDependencyResponse, VisitSubtype, VisitType } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'
import { DesignerJsonImport } from './DesignerJsonImport'

const DEFINITION_KINDS = ['visit', 'folder', 'cycle'] as const
const VISIT_TYPES = ['scheduled', 'unscheduled', 'common'] as const
const VISIT_CATEGORIES = ['screening', 'pretreatment', 'treatment', 'follow_up'] as const
const VISIT_SUBTYPES = ['ecoa', 'ediary'] as const
const kindFor = (visit: VisitDefinitionResponse) => visit.definition_kind ?? (visit.visit_type === 'cycle' ? 'cycle' : 'visit')

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

function CycleVisitEditor({ cycle, visits, versionId, canConfigure }: { cycle: VisitDefinitionResponse; visits: VisitDefinitionResponse[]; versionId: string; canConfigure: boolean }) {
  const client = useQueryClient()
  const [name, setName] = useState('')
  const [visitNumber, setVisitNumber] = useState(1)
  const [visitType, setVisitType] = useState<string>('scheduled')
  const [category, setCategory] = useState('')
  const [subtype, setSubtype] = useState('')
  const [targetDay, setTargetDay] = useState('')
  const [windowBefore, setWindowBefore] = useState('')
  const [windowAfter, setWindowAfter] = useState('')
  const [displayOrder, setDisplayOrder] = useState(1)
  const [isRequired, setIsRequired] = useState(true)
  const [error, setError] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('A cycle visit name is required.')
      const payload: VisitDefinitionCreate = {
        name: name.trim(),
        definition_kind: 'cycle_visit' as VisitDefinitionKind,
        visit_number: visitNumber,
        visit_type: visitType as VisitType,
        parent_folder_id: null,
        category: category ? category as VisitCategory : null,
        subtype: subtype ? subtype as VisitSubtype : null,
        target_day: optionalNumber(targetDay),
        window_before: optionalNumber(windowBefore),
        window_after: optionalNumber(windowAfter),
        display_order: displayOrder,
        is_required: isRequired,
        repeat_min: null,
        repeat_max: null,
        cycle_length: null,
      }
      return (await api.post<VisitDefinitionResponse>(`/designer/versions/${versionId}/cycles/${cycle.id}/visits`, payload)).data
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['designer-visits', versionId] })
      setName(''); setTargetDay(''); setWindowBefore(''); setWindowAfter('')
      setCategory(''); setSubtype(''); setIsRequired(true); setError('')
      setVisitNumber((value) => value + 1); setDisplayOrder((value) => value + 1)
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not create the cycle visit.')),
  })

  return (
    <div className="space-y-4 rounded-md border bg-muted/30 p-4">
      <div>
        <h4 className="font-medium">{cycle.name}: visits</h4>
        <p className="text-xs text-muted-foreground">These visits belong only to this cycle and appear in the Schedule of Assessments.</p>
      </div>
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
        {canConfigure ? (
          <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-5" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
            <FormField label="Cycle visit name" name="cycle-visit-name" required><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Cycle day 1" required /></FormField>
            <FormField label="Cycle visit number" name="cycle-visit-number" required><Input type="number" min={1} max={9999} value={visitNumber} onChange={(event) => setVisitNumber(Number(event.target.value))} required /></FormField>
            <FormField label="Visit type" name="cycle-visit-type" required><select id="field-cycle-visit-type" value={visitType} onChange={(event) => setVisitType(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{VISIT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></FormField>
            <FormField label="Category" name="cycle-visit-category"><select id="field-cycle-visit-category" value={category} onChange={(event) => setCategory(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="">— none —</option>{VISIT_CATEGORIES.map((value) => <option key={value} value={value}>{value.replace('_', ' ')}</option>)}</select></FormField>
            <FormField label="Subtype" name="cycle-visit-subtype"><select id="field-cycle-visit-subtype" value={subtype} onChange={(event) => setSubtype(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="">— none —</option>{VISIT_SUBTYPES.map((value) => <option key={value} value={value}>{value}</option>)}</select></FormField>
            <FormField label="Target day" name="cycle-visit-target-day"><Input type="number" min={0} max={99999} value={targetDay} onChange={(event) => setTargetDay(event.target.value)} /></FormField>
            <FormField label="Window before" name="cycle-visit-window-before"><Input type="number" min={0} max={99999} value={windowBefore} onChange={(event) => setWindowBefore(event.target.value)} /></FormField>
            <FormField label="Window after" name="cycle-visit-window-after"><Input type="number" min={0} max={99999} value={windowAfter} onChange={(event) => setWindowAfter(event.target.value)} /></FormField>
            <FormField label="Display order" name="cycle-visit-order" required><Input type="number" min={1} max={9999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required /></FormField>
            <div className="flex items-end gap-2 pb-1"><Checkbox id="field-cycle-visit-required" checked={isRequired} onChange={(event) => setIsRequired(event.target.checked)} /><label htmlFor="field-cycle-visit-required" className="text-sm">Required</label></div>
            <div className="md:col-span-2 xl:col-span-5"><FormActions pending={create.isPending} submitLabel="Add cycle visit" pendingLabel="Adding…" /></div>
          </form>
        ) : null}

        <DataTableShell label={`${cycle.name}: visits`} empty={!visits.length} emptyTitle="No visits in this cycle" emptyDescription="Add the first child visit for this cycle.">
          <Table>
            <TableHeader><TableRow>{['Order', '#', 'Name', 'Type', 'Category / subtype', 'Target / window', 'Required'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
            <TableBody>{visits.map((visit) => <TableRow key={visit.id}>
              <TableCell>{visit.display_order}</TableCell><TableCell>{visit.visit_number}</TableCell><TableCell className="font-medium">{visit.name}</TableCell><TableCell>{visit.visit_type}</TableCell><TableCell>{visit.category?.replace('_', ' ') ?? '—'}{visit.subtype ? ` · ${visit.subtype}` : ''}</TableCell><TableCell>{visit.target_day ?? '—'} ({visit.window_before ?? '—'} / {visit.window_after ?? '—'})</TableCell><TableCell>{visit.is_required ? 'Yes' : 'No'}</TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </DataTableShell>
    </div>
  )
}

function VisitsEditor({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_VISIT_CONFIGURE, studyId) && !readOnly
  const [expandedVisitId, setExpandedVisitId] = useState('')

  const [name, setName] = useState('')
  const [definitionKind, setDefinitionKind] = useState<string>('visit')
  const [visitNumber, setVisitNumber] = useState(1)
  const [visitType, setVisitType] = useState<string>('scheduled')
  const [parentFolderId, setParentFolderId] = useState('')
  const [category, setCategory] = useState('')
  const [subtype, setSubtype] = useState('')
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
      const isVisit = definitionKind === 'visit'
      const isCycle = definitionKind === 'cycle'
      const payload: VisitDefinitionCreate = {
        name: name.trim(),
        definition_kind: definitionKind as VisitDefinitionKind,
        visit_number: isVisit ? visitNumber : null,
        visit_type: (isVisit ? visitType : isCycle ? 'cycle' : 'common') as VisitType,
        parent_folder_id: isVisit && parentFolderId ? parentFolderId : null,
        category: isVisit && category ? category as VisitCategory : null,
        subtype: isVisit && subtype ? subtype as VisitSubtype : null,
        target_day: isVisit ? optionalNumber(targetDay) : null,
        window_before: isVisit ? optionalNumber(windowBefore) : null,
        window_after: isVisit ? optionalNumber(windowAfter) : null,
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
      setParentFolderId(''); setCategory(''); setSubtype('')
      setVisitNumber((n) => n + 1); setDisplayOrder((order) => order + 1); setIsRequired(true)
      setError(''); setMessage(`Visit "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the visit.')); setMessage('') },
  })

  const rows = [...(visitsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order)
  const definitionRows = rows.filter((row) => kindFor(row) !== 'cycle_visit')
  const folders = rows.filter((row) => kindFor(row) === 'folder')
  const visitRows = rows.filter((row) => kindFor(row) === 'visit')
  const cycleVisitRows = rows.filter((row) => kindFor(row) === 'cycle_visit')
  const nameFor = (id: string) => rows.find((row) => row.id === id)?.name ?? id

  if (visitsQuery.isLoading) return <PageContainer><LoadingState label="visit definitions" /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader title="Visits, folders, and cycles" description={readOnly ? 'Review visits and their retained folder and cycle hierarchy for this published design version.' : 'Treat each cycle as a special folder: expand it to configure visits owned only by that cycle. Folder and cycle containers never appear as SoA columns.'} actions={canConfigure ? <DesignerJsonImport studyId={studyId} /> : undefined} />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {canConfigure ? (
          <Card>
            <CardHeader><CardTitle className="text-base">New definition</CardTitle></CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
                <FormField label="Name" name="visit-name" required>
                  <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Baseline" required />
                </FormField>
                <FormField label="Definition kind" name="definition-kind" required>
                  <select
                    id="field-definition-kind"
                    value={definitionKind}
                    onChange={(event) => setDefinitionKind(event.target.value)}
                    className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  >
                    {DEFINITION_KINDS.map((type) => <option key={type} value={type}>{type}</option>)}
                  </select>
                </FormField>
                {definitionKind === 'visit' ? (
                  <>
                    <FormField label="Visit number" name="visit-number" required>
                      <Input type="number" min={1} max={9999} value={visitNumber} onChange={(event) => setVisitNumber(Number(event.target.value))} required />
                    </FormField>
                    <FormField label="Parent folder" name="parent-folder">
                      <select id="field-parent-folder" value={parentFolderId} onChange={(event) => setParentFolderId(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="">— no folder —</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select>
                    </FormField>
                    <FormField label="Visit type" name="visit-type" required>
                      <select id="field-visit-type" value={visitType} onChange={(event) => setVisitType(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{VISIT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select>
                    </FormField>
                    <FormField label="Category" name="visit-category">
                      <select id="field-visit-category" value={category} onChange={(event) => setCategory(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="">— none —</option>{VISIT_CATEGORIES.map((value) => <option key={value} value={value}>{value.replace('_', ' ')}</option>)}</select>
                    </FormField>
                    <FormField label="Subtype" name="visit-subtype">
                      <select id="field-visit-subtype" value={subtype} onChange={(event) => setSubtype(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="">— none —</option>{VISIT_SUBTYPES.map((value) => <option key={value} value={value}>{value}</option>)}</select>
                    </FormField>
                  </>
                ) : null}
                {definitionKind === 'cycle' ? (
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
                {definitionKind === 'visit' ? <><FormField label="Target day" name="visit-target-day" description="Optional day relative to baseline.">
                  <Input type="number" min={0} max={99999} value={targetDay} onChange={(event) => setTargetDay(event.target.value)} placeholder="0" />
                </FormField>
                <FormField label="Window before" name="visit-window-before" description="Optional days before target day.">
                  <Input type="number" min={0} max={99999} value={windowBefore} onChange={(event) => setWindowBefore(event.target.value)} />
                </FormField>
                <FormField label="Window after" name="visit-window-after" description="Optional days after target day.">
                  <Input type="number" min={0} max={99999} value={windowAfter} onChange={(event) => setWindowAfter(event.target.value)} />
                </FormField></> : null}
                <FormField label="Display order" name="visit-order" required>
                  <Input type="number" min={1} max={9999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required />
                </FormField>
                {definitionKind === 'visit' ? <div className="flex items-center gap-2">
                  <Checkbox id="field-visit-required" checked={isRequired} onChange={(event) => setIsRequired(event.target.checked)} />
                  <label htmlFor="field-visit-required" className="text-sm">Required visit</label>
                </div> : null}
                <FormActions pending={create.isPending} submitLabel={`Add ${definitionKind}`} pendingLabel="Adding…" />
              </form>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Visit definitions</CardTitle>
            <span className="text-xs text-muted-foreground">{definitionRows.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Visit definitions" empty={!definitionRows.length} emptyTitle="No visits defined yet" emptyDescription="Visits you create appear here.">
              <Table>
                <caption className="sr-only">Visit definitions ordered by display order</caption>
                <TableHeader><TableRow>{['Order', '#', 'Name', 'Kind / type', 'Folder / category', 'Cycle visits', 'Target / window', 'Required', 'Dependencies'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{definitionRows.map((row) => {
                  const expanded = expandedVisitId === row.id
                  return (
                    <Fragment key={row.id}>
                      <TableRow>
                        <TableCell>{row.display_order}</TableCell>
                        <TableCell>{row.visit_number}</TableCell>
                        <TableCell className="font-medium">{row.name}</TableCell>
                        <TableCell>{kindFor(row)} · {row.visit_type}</TableCell>
                        <TableCell>{row.parent_folder_id ? nameFor(row.parent_folder_id) : row.category?.replace('_', ' ') ?? '—'}{row.subtype ? ` · ${row.subtype}` : ''}</TableCell>
                        <TableCell>{kindFor(row) === 'cycle' ? <><span>{(row.member_visit_ids ?? []).map(nameFor).join(', ') || 'No visits'}</span><span className="block text-xs text-muted-foreground">{row.repeat_min ?? '—'}–{row.repeat_max ?? '—'} · {row.cycle_length ?? '—'}d</span></> : '—'}</TableCell>
                        <TableCell>{row.target_day ?? '—'}{kindFor(row) === 'visit' ? ` (${row.window_before ?? '—'} / ${row.window_after ?? '—'})` : ''}</TableCell>
                        <TableCell>{kindFor(row) === 'visit' ? row.is_required ? 'Yes' : 'No' : '—'}</TableCell>
                        <TableCell>
                          {kindFor(row) === 'visit' || kindFor(row) === 'cycle' ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? 'Hide' : 'Show'} ${kindFor(row) === 'cycle' ? 'visits' : 'dependencies'} for ${row.name}`}
                            onClick={() => setExpandedVisitId(expanded ? '' : row.id)}
                          >
                            {expanded ? 'Hide' : kindFor(row) === 'cycle' ? 'Edit visits' : 'Depends on'}
                          </Button>) : '—'}
                        </TableCell>
                      </TableRow>
                      {expanded ? (
                        <TableRow>
                          <TableCell colSpan={9} className="bg-muted/20">
                            {kindFor(row) === 'cycle' ? <CycleVisitEditor cycle={row} visits={cycleVisitRows.filter((visit) => (row.member_visit_ids ?? []).includes(visit.id))} versionId={versionId} canConfigure={canConfigure} /> : <VisitDependencyEditor visit={row} visits={visitRows} canConfigure={canConfigure} />}
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
        {(versionId, selection) => <VisitsEditor studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
