import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type IsValidConnection,
  type Node,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type {
  SubjectPhaseDefinitionCreate,
  SubjectPhaseDefinitionResponse,
  SubjectPhaseDefinitionUpdate,
  SubjectPhaseTransitionCreate,
  SubjectPhaseTransitionResponse,
  VisitDefinitionResponse,
} from '@/api/model'
import { SubjectPhaseType } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

/** Positions persisted client-side (the backend has no position column). */
type PositionMap = Record<string, { x: number; y: number }>

const storageKey = (versionId: string) => `designer:phaseflow:${versionId}`
const isTmpId = (id: string) => id.startsWith('tmp-')
let tmpCounter = 0
const makeTmpId = () => `tmp-${Date.now()}-${tmpCounter++}`
const phaseTypeOptions = [
  { value: SubjectPhaseType.registered, label: 'Registered' },
  { value: SubjectPhaseType.screen_failure, label: 'Screen failure' },
  { value: SubjectPhaseType.common, label: 'Common' },
  { value: SubjectPhaseType.complete, label: 'Complete' },
  { value: SubjectPhaseType.arm, label: 'Arm selection' },
]
const supportsVisits = (phaseType: string) =>
  phaseType === SubjectPhaseType.registered
  || phaseType === SubjectPhaseType.screen_failure
  || phaseType === SubjectPhaseType.common

function readPositions(versionId: string): PositionMap {
  try {
    const raw = localStorage.getItem(storageKey(versionId))
    return raw ? (JSON.parse(raw) as PositionMap) : {}
  } catch {
    return {}
  }
}

function writePositions(versionId: string, positions: PositionMap) {
  try {
    localStorage.setItem(storageKey(versionId), JSON.stringify(positions))
  } catch {
    // Ignore storage quota / unavailable (private mode) — positions are a convenience.
  }
}

/** Grid fallback for phases without a stored position, laid out by display_order. */
function gridPosition(index: number): { x: number; y: number } {
  const perRow = 4
  return { x: (index % perRow) * 220 + 40, y: Math.floor(index / perRow) * 140 + 40 }
}

function SubjectPhasesFlow({ versionId, studyId, readOnly }: { versionId: string; studyId: string; readOnly: boolean }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_SUBJECT_PHASE_CONFIGURE, studyId) && !readOnly

  const [nodes, setNodes] = useState<Node[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [syncedPhases, setSyncedPhases] = useState<SubjectPhaseDefinitionResponse[] | null>(null)
  const [syncedTransitions, setSyncedTransitions] = useState<SubjectPhaseTransitionResponse[] | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [newPhaseName, setNewPhaseName] = useState('')
  const [newPhaseType, setNewPhaseType] = useState<SubjectPhaseType>(SubjectPhaseType.common)
  const [newPhaseVisitIds, setNewPhaseVisitIds] = useState<string[]>([])
  const [selectedPhaseId, setSelectedPhaseId] = useState('')
  const [phaseNameDraft, setPhaseNameDraft] = useState('')
  const [phaseTypeDraft, setPhaseTypeDraft] = useState<SubjectPhaseType>(SubjectPhaseType.common)
  const [phaseVisitIdsDraft, setPhaseVisitIdsDraft] = useState<string[]>([])
  const [edgeFrom, setEdgeFrom] = useState('')
  const [edgeTo, setEdgeTo] = useState('')
  // Positions seed the layout and are updated on drag-stop. Initialized lazily
  // from localStorage; the backend has no position column.
  const [positions, setPositions] = useState<PositionMap>(() => readPositions(versionId))

  const phasesQuery = useQuery({
    queryKey: ['designer-subject-phases', versionId],
    queryFn: async () => (await api.get<SubjectPhaseDefinitionResponse[]>(`/designer/versions/${versionId}/subject-phases`)).data,
  })
  const transitionsQuery = useQuery({
    queryKey: ['designer-subject-phase-transitions', versionId],
    queryFn: async () => (await api.get<SubjectPhaseTransitionResponse[]>(`/designer/versions/${versionId}/subject-phase-transitions`)).data,
  })
  const visitsQuery = useQuery({
    queryKey: ['designer-visits', versionId],
    queryFn: async () => (await api.get<VisitDefinitionResponse[]>(`/designer/versions/${versionId}/visits`)).data,
  })

  const phases = useMemo(
    () => [...(phasesQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id)),
    [phasesQuery.data],
  )
  const allVisits = useMemo(() => visitsQuery.data ?? [], [visitsQuery.data])
  const visits = useMemo(
    () => allVisits.filter((visit) => ['visit', 'cycle_visit'].includes(visit.definition_kind ?? 'visit')),
    [allVisits],
  )
  const visitById = useMemo(
    () => new Map(allVisits.map((visit) => [visit.id, visit])),
    [allVisits],
  )

  // Sync nodes from the phases query during render (guarded by the last-synced
  // query reference). This is React's recommended alternative to a
  // setState-in-effect, which the compiler flags as a cascading render.
  const phasesData = phasesQuery.data
  if (phasesData !== undefined && phasesData !== syncedPhases) {
    setSyncedPhases(phasesData ?? null)
    setNodes(phases.map((phase, index) => ({
      id: phase.id,
      position: positions[phase.id] ?? gridPosition(index),
      data: { label: `${phase.name} (${(phase.phase_type ?? SubjectPhaseType.common).replace('_', ' ')})` },
      type: 'default',
    })))
  }

  // Sync edges from the transitions query. edge.id IS the server transition id.
  // Preserve any optimistic (tmp-) edges still awaiting their persisted id, and
  // drop optimistic edges the server now confirms (same source/target).
  const serverTransitions = transitionsQuery.data
  if (serverTransitions !== undefined && serverTransitions !== syncedTransitions) {
    setSyncedTransitions(serverTransitions ?? null)
    setEdges((prev) => {
      const pending = prev.filter((edge) => isTmpId(edge.id))
      const mapped: Edge[] = (serverTransitions ?? []).map((t) => ({
        id: t.id,
        source: t.from_phase_id,
        target: t.to_phase_id,
        label: t.label ?? undefined,
      }))
      const confirmed = new Set(mapped.map((e) => `${e.source}->${e.target}`))
      const stillPending = pending.filter((e) => !confirmed.has(`${e.source}->${e.target}`))
      return [...mapped, ...stillPending]
    })
  }

  const invalidate = useCallback(() => {
    client.invalidateQueries({ queryKey: ['designer-subject-phase-transitions', versionId] })
  }, [client, versionId])

  const createTransition = useMutation({
    mutationFn: async (payload: SubjectPhaseTransitionCreate) =>
      (await api.post<SubjectPhaseTransitionResponse>(`/designer/versions/${versionId}/subject-phase-transitions`, payload)).data,
    onSuccess: () => { setError(''); invalidate() },
    onError: (err) => {
      setError(getApiErrorMessage(err, 'Could not create the transition.'))
      invalidate() // Roll back the optimistic edge by re-reading the server set.
    },
  })

  const deleteTransition = useMutation({
    mutationFn: async (transitionId: string) => {
      await api.delete(`/designer/versions/${versionId}/subject-phase-transitions/${transitionId}`)
    },
    onSuccess: () => { setError(''); invalidate() },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not delete the transition.')); invalidate() },
  })

  const createPhase = useMutation({
    mutationFn: async () => {
      const name = newPhaseName.trim()
      if (!name) throw new Error('A phase name is required.')
      const payload: SubjectPhaseDefinitionCreate = {
        name,
        phase_type: newPhaseType,
        display_order: phases.length + 1,
        visit_definition_ids: supportsVisits(newPhaseType) ? newPhaseVisitIds : [],
      }
      return (await api.post<SubjectPhaseDefinitionResponse>(`/designer/versions/${versionId}/subject-phases`, payload)).data
    },
    onSuccess: (data) => {
      setNewPhaseName('')
      setNewPhaseType(SubjectPhaseType.common)
      setNewPhaseVisitIds([])
      setError('')
      setMessage(`Phase "${data.name}" added.`)
      client.invalidateQueries({ queryKey: ['designer-subject-phases', versionId] })
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the phase.')); setMessage('') },
  })

  const renamePhase = useMutation({
    mutationFn: async () => {
      const name = phaseNameDraft.trim()
      if (!selectedPhaseId) throw new Error('Select a phase first.')
      if (name.length < 1 || name.length > 100) throw new Error('Phase name must be 1–100 characters.')
      const payload: SubjectPhaseDefinitionUpdate = {
        name,
        phase_type: phaseTypeDraft,
        visit_definition_ids: supportsVisits(phaseTypeDraft) ? phaseVisitIdsDraft : [],
      }
      return (await api.patch<SubjectPhaseDefinitionResponse>(`/designer/subject-phases/${selectedPhaseId}`, payload)).data
    },
    onSuccess: (data) => {
      setError('')
      setMessage(`Phase "${data.name}" updated.`)
      client.invalidateQueries({ queryKey: ['designer-subject-phases', versionId] })
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not rename the phase.')); setMessage('') },
  })

  const deletePhase = useMutation({
    mutationFn: async (phaseId: string) => { await api.delete(`/designer/subject-phases/${phaseId}`) },
    onSuccess: () => {
      setError('')
      setSelectedPhaseId('')
      setMessage('Phase deleted.')
      client.invalidateQueries({ queryKey: ['designer-subject-phases', versionId] })
      invalidate()
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not delete the phase.')); setMessage('') },
  })

  const onNodesChange = useCallback((changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)), [])
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), [])

  const onNodeDragStop = useCallback((_e: unknown, node: Node) => {
    setPositions((prev) => {
      const next = { ...prev, [node.id]: node.position }
      writePositions(versionId, next)
      return next
    })
  }, [versionId])

  // React Flow has NO default self-connection block (NIT-1): keep the explicit guard.
  const isValidConnection = useCallback<IsValidConnection>((conn) => {
    const c = conn as Connection
    return !!c.source && !!c.target && c.source !== c.target
  }, [])

  const onConnect = useCallback((connection: Connection) => {
    if (!canConfigure) return
    const { source, target } = connection
    if (!source || !target || source === target) return // self-guard
    const tmpId = makeTmpId()
    setEdges((eds) => addEdge({ ...connection, id: tmpId }, eds))
    createTransition.mutate({ from_phase_id: source, to_phase_id: target })
  }, [canConfigure, createTransition])

  const onEdgesDelete = useCallback((deleted: Edge[]) => {
    if (!canConfigure) return
    for (const edge of deleted) {
      if (isTmpId(edge.id)) continue // optimistic edge: no server id yet
      deleteTransition.mutate(edge.id)
    }
  }, [canConfigure, deleteTransition])

  const addTransitionFromForm = () => {
    if (!edgeFrom || !edgeTo || edgeFrom === edgeTo) {
      setError('Pick two different phases to connect.')
      return
    }
    const tmpId = makeTmpId()
    setEdges((eds) => addEdge({ id: tmpId, source: edgeFrom, target: edgeTo }, eds))
    createTransition.mutate({ from_phase_id: edgeFrom, to_phase_id: edgeTo })
    setEdgeFrom(''); setEdgeTo('')
  }

  const selectPhase = (id: string) => {
    setSelectedPhaseId(id)
    const phase = phases.find((p) => p.id === id)
    setPhaseNameDraft(phase?.name ?? '')
    setPhaseTypeDraft(phase?.phase_type ?? SubjectPhaseType.common)
    setPhaseVisitIdsDraft(phase?.visit_definition_ids ?? [])
  }

  if (phasesQuery.isLoading || transitionsQuery.isLoading || visitsQuery.isLoading) {
    return <PageContainer wide><LoadingState label="subject phases" /></PageContainer>
  }

  return (
    <PageContainer wide>
      <PageHeader
        title="Subject phases"
        description={readOnly ? 'Review subject phases, visits, and transitions retained in this published design version.' : 'Model the phases subjects progress through and the transitions (data flow) between them for the current draft version.'}
      />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-6">
          {canConfigure ? (
            <Card>
              <CardHeader><CardTitle className="text-base">Add phase</CardTitle></CardHeader>
              <CardContent>
                <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); setError(''); createPhase.mutate() }}>
                  <Input aria-label="New phase name" value={newPhaseName} onChange={(event) => setNewPhaseName(event.target.value)} placeholder="Screening" />
                  <select aria-label="New phase type" value={newPhaseType} onChange={(event) => { const value = event.target.value as SubjectPhaseType; setNewPhaseType(value); if (!supportsVisits(value)) setNewPhaseVisitIds([]) }} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                    {phaseTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  {supportsVisits(newPhaseType) ? <div className="space-y-2 rounded-md border p-3">
                    <p className="text-xs font-medium">Associated visits</p>
                    {visits.length ? visits.map((visit) => <label key={visit.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={newPhaseVisitIds.includes(visit.id)} onChange={(event) => setNewPhaseVisitIds((current) => event.target.checked ? [...current, visit.id] : current.filter((id) => id !== visit.id))} />{visit.name}</label>) : <p className="text-xs text-muted-foreground">No visits are available.</p>}
                  </div> : <p className="text-xs text-muted-foreground">This phase type does not associate visits.</p>}
                  <Button type="submit" className="w-full" pending={createPhase.isPending} loadingText="Adding…">Add phase</Button>
                </form>
              </CardContent>
            </Card>
          ) : null}

          {canConfigure ? (
            <Card>
              <CardHeader><CardTitle className="text-base">Add transition</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <label className="block text-xs text-muted-foreground" htmlFor="transition-from">From phase</label>
                <select id="transition-from" aria-label="Transition from phase" value={edgeFrom} onChange={(event) => setEdgeFrom(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                  <option value="">— select —</option>
                  {phases.map((phase) => <option key={phase.id} value={phase.id}>{phase.name}</option>)}
                </select>
                <label className="block text-xs text-muted-foreground" htmlFor="transition-to">To phase</label>
                <select id="transition-to" aria-label="Transition to phase" value={edgeTo} onChange={(event) => setEdgeTo(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                  <option value="">— select —</option>
                  {phases.filter((phase) => phase.id !== edgeFrom).map((phase) => <option key={phase.id} value={phase.id}>{phase.name}</option>)}
                </select>
                <Button type="button" className="w-full" variant="outline" onClick={addTransitionFromForm}>Add transition</Button>
              </CardContent>
            </Card>
          ) : null}

          {readOnly ? (
            <Card>
              <CardHeader><CardTitle className="text-base">Phase visit membership</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {phases.length ? phases.map((phase) => {
                  const phaseType = phase.phase_type ?? SubjectPhaseType.common
                  const visitIds = phase.visit_definition_ids ?? []
                  return (
                    <section key={phase.id} className="space-y-2 rounded-md border p-3" aria-label={`${phase.name} visit membership`}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="text-sm font-medium">{phase.name}</h3>
                        <span className="text-xs text-muted-foreground">{phaseType.replace('_', ' ')}</span>
                      </div>
                      {supportsVisits(phaseType) ? (
                        visitIds.length ? (
                          <ol className="list-decimal space-y-1 pl-5 text-sm">
                            {visitIds.map((visitId) => {
                              const visit = visitById.get(visitId)
                              return <li key={visitId}>{visit?.name ?? `Unavailable visit (${visitId})`}</li>
                            })}
                          </ol>
                        ) : <p className="text-xs text-muted-foreground">No visits associated with this phase.</p>
                      ) : (
                        <p className="text-xs text-muted-foreground">{phaseType === SubjectPhaseType.arm ? 'Visits are determined by the subject’s selected arm.' : 'This phase completes the study and has no associated visits.'}</p>
                      )}
                    </section>
                  )
                }) : <p className="text-sm text-muted-foreground">No phases were retained in this version.</p>}
              </CardContent>
            </Card>
          ) : null}

          {!readOnly ? <Card>
            <CardHeader><CardTitle className="text-base">Phase details</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <select aria-label="Select phase" value={selectedPhaseId} onChange={(event) => selectPhase(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                <option value="">— select a phase —</option>
                {phases.map((phase) => <option key={phase.id} value={phase.id}>{phase.name}</option>)}
              </select>
              {selectedPhaseId && canConfigure ? (
                <>
                  <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); setError(''); renamePhase.mutate() }}>
                    <Input aria-label="Phase name" value={phaseNameDraft} onChange={(event) => setPhaseNameDraft(event.target.value)} placeholder="Phase name" />
                    <select aria-label="Phase type" value={phaseTypeDraft} onChange={(event) => { const value = event.target.value as SubjectPhaseType; setPhaseTypeDraft(value); if (!supportsVisits(value)) setPhaseVisitIdsDraft([]) }} className="h-9 w-full rounded-md border bg-background px-2 text-sm">
                      {phaseTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    {supportsVisits(phaseTypeDraft) ? <div className="space-y-2 rounded-md border p-3">
                      <p className="text-xs font-medium">Associated visits</p>
                      {visits.length ? visits.map((visit) => <label key={visit.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={phaseVisitIdsDraft.includes(visit.id)} onChange={(event) => setPhaseVisitIdsDraft((current) => event.target.checked ? [...current, visit.id] : current.filter((id) => id !== visit.id))} />{visit.name}</label>) : <p className="text-xs text-muted-foreground">No visits are available.</p>}
                    </div> : <p className="text-xs text-muted-foreground">This phase type does not associate visits.</p>}
                    <Button type="submit" className="w-full" variant="outline" pending={renamePhase.isPending} loadingText="Saving…">Save phase</Button>
                  </form>
                  <Button type="button" className="w-full" variant="destructive" pending={deletePhase.isPending} loadingText="Deleting…" onClick={() => deletePhase.mutate(selectedPhaseId)}>Delete phase</Button>
                </>
              ) : null}
            </CardContent>
          </Card> : null}
        </div>

        <Card>
          <CardHeader><CardTitle className="text-base">Flow</CardTitle></CardHeader>
          <CardContent>
            {phases.length === 0 ? (
              <Alert><AlertDescription>No phases yet. Add a phase to start building the flow.</AlertDescription></Alert>
            ) : (
              <div className="h-[70vh] w-full rounded-lg border">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onNodeDragStop={onNodeDragStop}
                  onConnect={onConnect}
                  onEdgesDelete={onEdgesDelete}
                  isValidConnection={isValidConnection}
                  nodesConnectable={canConfigure}
                  elementsSelectable={canConfigure}
                  nodesFocusable
                  edgesFocusable
                  aria-label="Subject phase flow graph"
                  fitView
                >
                  <Background />
                  <Controls />
                </ReactFlow>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}

export function SubjectPhasesPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_SUBJECT_PHASE_READ} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => (
          <ReactFlowProvider>
            <SubjectPhasesFlow versionId={versionId} studyId={studyId} readOnly={selection.isReadOnly} />
          </ReactFlowProvider>
        )}
      </DraftGate>
    </PermissionGuard>
  )
}
