import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { ArmDefinitionCreate, ArmDefinitionResponse, VisitDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

function ArmsEditor({ studyId, versionId }: { studyId: string; versionId: string }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_ARM_CONFIGURE, studyId)

  const [name, setName] = useState('')
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

  const visits = useMemo(
    () => [...(visitsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id)),
    [visitsQuery.data],
  )
  const visitNameById = useMemo(() => new Map(visits.map((v) => [v.id, v.name])), [visits])

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('An arm name is required.')
      const payload: ArmDefinitionCreate = {
        name: name.trim(),
        display_order: displayOrder,
        description: description.trim() || null,
        visit_definition_ids: memberVisitIds,
      }
      return (await api.post<ArmDefinitionResponse>(`/designer/versions/${versionId}/arms`, payload)).data
    },
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['designer-arms', versionId] })
      setName(''); setDescription(''); setMemberVisitIds([]); setDisplayOrder((order) => order + 1)
      setError(''); setMessage(`Arm "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the arm.')); setMessage('') },
  })

  const toggleMemberVisit = (visitId: string) => {
    setMemberVisitIds((prev) => (prev.includes(visitId) ? prev.filter((id) => id !== visitId) : [...prev, visitId]))
  }

  const rows = [...(armsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id))

  if (armsQuery.isLoading) return <PageContainer wide><LoadingState label="treatment arms" /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader title="Treatment arms" description="Define the treatment arms for the current draft version and the visits (and cycles) that occur in each." />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {canConfigure ? (
          <Card>
            <CardHeader><CardTitle className="text-base">New arm</CardTitle></CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
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
                  <p className="text-xs text-muted-foreground">Select the visits and cycles that occur in this arm.</p>
                  {visits.length ? (
                    <div className="max-h-48 space-y-1 overflow-auto rounded-md border p-2">
                      {visits.map((visit) => (
                        <label key={visit.id} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            aria-label={`Include visit ${visit.name}`}
                            checked={memberVisitIds.includes(visit.id)}
                            onChange={() => toggleMemberVisit(visit.id)}
                          />
                          <span>{visit.visit_number} · {visit.name}{visit.visit_type === 'cycle' ? ' (cycle)' : ''}</span>
                        </label>
                      ))}
                    </div>
                  ) : <p className="text-xs text-muted-foreground">No visits defined yet.</p>}
                </fieldset>
                <FormActions pending={create.isPending} submitLabel="Add arm" pendingLabel="Adding…" />
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
                <caption className="sr-only">Treatment arms for the current draft version</caption>
                <TableHeader><TableRow>{['Order', 'Name', 'Member visits', 'Description'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.display_order}</TableCell>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell>{row.visit_definition_ids?.length ? row.visit_definition_ids.map((id) => visitNameById.get(id) ?? id).join(', ') : '—'}</TableCell>
                    <TableCell>{row.description || '—'}</TableCell>
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
        {(versionId) => <ArmsEditor studyId={studyId} versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
