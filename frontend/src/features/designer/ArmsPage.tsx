import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { ArmDefinitionCreate, ArmDefinitionResponse, ArmDefinitionUpdate, VisitDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'
import {
  buildVisitHierarchy,
  expandToSelectableVisitIds,
  flattenSelectableVisits,
  selectableVisitIds,
  visitKind,
  type VisitHierarchyNode,
} from './visitHierarchy'

function HierarchyPickerNode({
  node,
  selectedIds,
  onToggle,
}: {
  node: VisitHierarchyNode
  selectedIds: Set<string>
  onToggle: (node: VisitHierarchyNode) => void
}) {
  const leafIds = selectableVisitIds(node)
  const allSelected = leafIds.length > 0 && leafIds.every((id) => selectedIds.has(id))
  const someSelected = leafIds.some((id) => selectedIds.has(id))
  const isGroup = !['visit', 'cycle_visit'].includes(visitKind(node.visit))
  return (
    <div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          ref={(element) => {
            if (element) element.indeterminate = someSelected && !allSelected
          }}
          aria-label={`${isGroup ? 'Include group' : 'Include visit'} ${node.visit.name}`}
          aria-checked={someSelected && !allSelected ? 'mixed' : allSelected}
          checked={allSelected}
          disabled={leafIds.length === 0}
          onChange={() => onToggle(node)}
        />
        <span>{node.visit.visit_number} · {node.visit.name}{isGroup ? ` (${visitKind(node.visit)})` : ''}</span>
      </label>
      {node.children.length ? (
        <div className="ml-3 mt-1 space-y-1 border-l pl-4">
          {node.children.map((child) => <HierarchyPickerNode key={child.visit.id} node={child} selectedIds={selectedIds} onToggle={onToggle} />)}
        </div>
      ) : null}
    </div>
  )
}

function ArmsEditor({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_ARM_CONFIGURE, studyId) && !readOnly

  const [name, setName] = useState('')
  const [selectedArmId, setSelectedArmId] = useState<string | null>(null)
  const [displayOrder, setDisplayOrder] = useState(1)
  const [description, setDescription] = useState('')
  const [memberVisitIds, setMemberVisitIds] = useState<string[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const armsQuery = useQuery({
    queryKey: ['designer-arms', versionId],
    queryFn: async () => (await api.get<ArmDefinitionResponse[]>(`/designer/versions/${versionId}/arms`)).data,
  })
  const visitsQuery = useQuery({
    queryKey: ['designer-visits', versionId],
    queryFn: async () => (await api.get<VisitDefinitionResponse[]>(`/designer/versions/${versionId}/visits`)).data,
  })

  const visitHierarchy = useMemo(() => buildVisitHierarchy(visitsQuery.data ?? []), [visitsQuery.data])
  const selectableVisits = useMemo(() => flattenSelectableVisits(visitHierarchy), [visitHierarchy])
  const selectedMemberIds = useMemo(() => new Set(memberVisitIds), [memberVisitIds])
  const visitNameById = useMemo(() => {
    const names = new Map((visitsQuery.data ?? []).map((visit) => [visit.id, visit.name]))
    for (const { visit, parentName } of selectableVisits) {
      names.set(visit.id, parentName ? `${parentName} › ${visit.name}` : visit.name)
    }
    return names
  }, [selectableVisits, visitsQuery.data])

  const resetEditor = () => {
    setSelectedArmId(null)
    setName('')
    setDescription('')
    setMemberVisitIds([])
  }

  const save = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('An arm name is required.')
      const payload: ArmDefinitionCreate | ArmDefinitionUpdate = {
        name: name.trim(),
        display_order: displayOrder,
        description: description.trim() || null,
        visit_definition_ids: selectableVisits
          .map(({ visit }) => visit.id)
          .filter((id) => memberVisitIds.includes(id)),
      }
      if (selectedArmId) {
        return (await api.patch<ArmDefinitionResponse>(`/designer/versions/${versionId}/arms/${selectedArmId}`, payload)).data
      }
      return (await api.post<ArmDefinitionResponse>(`/designer/versions/${versionId}/arms`, payload)).data
    },
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['designer-arms', versionId] })
      const wasEditing = selectedArmId !== null
      resetEditor()
      if (!wasEditing) setDisplayOrder((order) => order + 1)
      setError(''); setMessage(`Arm "${data.name}" ${wasEditing ? 'updated' : 'added'}.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not save the arm.')); setMessage('') },
  })

  const editArm = (arm: ArmDefinitionResponse) => {
    setSelectedArmId(arm.id)
    setName(arm.name)
    setDisplayOrder(arm.display_order)
    setDescription(arm.description ?? '')
    setMemberVisitIds(expandToSelectableVisitIds(visitHierarchy, arm.visit_definition_ids ?? []))
    setError('')
    setMessage('')
  }

  const toggleHierarchyNode = (node: VisitHierarchyNode) => {
    const nodeIds = selectableVisitIds(node)
    setMemberVisitIds((previous) => {
      const next = new Set(previous)
      const remove = nodeIds.length > 0 && nodeIds.every((id) => next.has(id))
      for (const id of nodeIds) {
        if (remove) next.delete(id)
        else next.add(id)
      }
      return [...next]
    })
  }

  const rows = [...(armsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id))

  if (armsQuery.isLoading || visitsQuery.isLoading) return <PageContainer wide><LoadingState label="treatment arms" /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader title="Treatment arms" description={readOnly ? 'Review treatment arms and their visit membership for this published design version.' : 'Select individual visits or choose an entire folder or cycle to include all visits beneath it.'} />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {canConfigure ? (
          <Card>
            <CardHeader><CardTitle className="text-base">{selectedArmId ? 'Edit arm' : 'New arm'}</CardTitle></CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); save.mutate() }}>
                <FormField label="Name" name="arm-name" required>
                  <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Active" required />
                </FormField>
                <FormField label="Display order" name="arm-order" required>
                  <Input type="number" min={1} max={999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required />
                </FormField>
                <FormField label="Description" name="arm-description">
                  <Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Optional description of the arm." />
                </FormField>
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium">Member visits</legend>
                  <p className="text-xs text-muted-foreground">Selecting a folder or cycle selects all of its child visits; you can still select individual children.</p>
                  {visitHierarchy.length ? (
                    <div className="max-h-48 space-y-1 overflow-auto rounded-md border p-2">
                      {visitHierarchy.map((node) => (
                        <HierarchyPickerNode key={node.visit.id} node={node} selectedIds={selectedMemberIds} onToggle={toggleHierarchyNode} />
                      ))}
                    </div>
                  ) : <p className="text-xs text-muted-foreground">No visits defined yet.</p>}
                </fieldset>
                <FormActions
                  pending={save.isPending}
                  submitLabel={selectedArmId ? 'Update arm' : 'Add arm'}
                  pendingLabel={selectedArmId ? 'Updating…' : 'Adding…'}
                  onCancel={selectedArmId ? resetEditor : undefined}
                />
              </form>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Treatment arms</CardTitle>
            <span className="text-xs text-muted-foreground">{rows.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Treatment arms" empty={!rows.length} emptyTitle="No arms added yet" emptyDescription="Arms you create appear here.">
              <Table>
                <caption className="sr-only">Treatment arms for the selected design version</caption>
                <TableHeader><TableRow>{['Order', 'Name', 'Member visits', 'Description', ...(canConfigure ? ['Actions'] : [])].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.display_order}</TableCell>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell>{row.visit_definition_ids?.length ? row.visit_definition_ids.map((id) => visitNameById.get(id) ?? id).join(', ') : '—'}</TableCell>
                    <TableCell>{row.description || '—'}</TableCell>
                    {canConfigure ? <TableCell><Button type="button" variant="outline" size="sm" onClick={() => editArm(row)} aria-label={`Edit ${row.name}`}>Edit</Button></TableCell> : null}
                  </TableRow>
                ))}</TableBody>
              </Table>
            </DataTableShell>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}

export function ArmsPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_ARM_READ} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => <ArmsEditor studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
