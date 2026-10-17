import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { ArmDefinitionCreate, ArmDefinitionResponse, ArmDefinitionUpdate } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

function ArmsEditor({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_ARM_CONFIGURE, studyId) && !readOnly
  const [name, setName] = useState('')
  const [selectedArmId, setSelectedArmId] = useState<string | null>(null)
  const [displayOrder, setDisplayOrder] = useState(1)
  const [description, setDescription] = useState('')
  const [armToDelete, setArmToDelete] = useState<ArmDefinitionResponse | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const armsQuery = useQuery({
    queryKey: ['designer-arms', versionId],
    queryFn: async () => (await api.get<ArmDefinitionResponse[]>(`/designer/versions/${versionId}/arms`)).data,
  })

  const resetEditor = () => {
    setSelectedArmId(null)
    setName('')
    setDescription('')
  }

  const save = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('An arm name is required.')
      const payload: ArmDefinitionCreate | ArmDefinitionUpdate = {
        name: name.trim(),
        display_order: displayOrder,
        description: description.trim() || null,
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
      setError('')
      setMessage(`Arm "${data.name}" ${wasEditing ? 'updated' : 'added'}. Configure its visits and forms on the Schedule of Assessment page.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not save the arm.')); setMessage('') },
  })

  const remove = useMutation({
    mutationFn: async (arm: ArmDefinitionResponse) => {
      await api.delete(`/designer/versions/${versionId}/arms/${arm.id}`)
      return arm
    },
    onSuccess: (arm) => {
      if (selectedArmId === arm.id) resetEditor()
      setArmToDelete(null)
      setError('')
      setMessage(`Arm "${arm.name}" removed. Any schedule configured specifically for this arm was also removed.`)
      client.invalidateQueries({ queryKey: ['designer-arms', versionId] })
      client.invalidateQueries({ queryKey: ['designer-soa', versionId] })
    },
    onError: (err) => {
      setError(getApiErrorMessage(err, 'Could not remove the arm.'))
      setMessage('')
    },
  })

  const editArm = (arm: ArmDefinitionResponse) => {
    setSelectedArmId(arm.id)
    setName(arm.name)
    setDisplayOrder(arm.display_order)
    setDescription(arm.description ?? '')
    setError('')
    setMessage('')
  }

  const rows = [...(armsQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id))
  if (armsQuery.isLoading) return <PageContainer wide><LoadingState label="treatment arms" /></PageContainer>

  return (
    <PageContainer wide>
      <PageHeader title="Treatment arms" description="Create arm definitions here, then configure a separate schedule of assessment for each arm." />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {canConfigure ? (
          <Card>
            <CardHeader><CardTitle className="text-base">{selectedArmId ? 'Edit arm' : 'New arm'}</CardTitle></CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); save.mutate() }}>
                <FormField label="Name" name="arm-name" required><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Active" required /></FormField>
                <FormField label="Display order" name="arm-order" required><Input type="number" min={1} max={999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required /></FormField>
                <FormField label="Description" name="arm-description"><Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Optional description of the arm." /></FormField>
                <FormActions pending={save.isPending} submitLabel={selectedArmId ? 'Update arm' : 'Add arm'} pendingLabel={selectedArmId ? 'Updating…' : 'Adding…'} onCancel={selectedArmId ? resetEditor : undefined} />
              </form>
            </CardContent>
          </Card>
        ) : null}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle className="text-base">Treatment arms</CardTitle><span className="text-xs text-muted-foreground">{rows.length}</span></CardHeader>
          <CardContent>
            <DataTableShell label="Treatment arms" empty={!rows.length} emptyTitle="No arms added yet" emptyDescription="Arms you create appear here.">
              <Table>
                <caption className="sr-only">Treatment arms for the selected design version</caption>
                <TableHeader><TableRow>{['Order', 'Name', 'Description', ...(canConfigure ? ['Actions'] : [])].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{rows.map((row) => <TableRow key={row.id}><TableCell>{row.display_order}</TableCell><TableCell className="font-medium">{row.name}</TableCell><TableCell>{row.description || '—'}</TableCell>{canConfigure ? <TableCell><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => editArm(row)} aria-label={`Edit ${row.name}`}>Edit</Button><Button type="button" variant="destructive" size="sm" disabled={remove.isPending} onClick={() => setArmToDelete(row)} aria-label={`Remove ${row.name}`}>Remove</Button></div></TableCell> : null}</TableRow>)}</TableBody>
              </Table>
            </DataTableShell>
          </CardContent>
        </Card>
      </div>

      <Dialog open={Boolean(armToDelete)} onOpenChange={(open) => { if (!open && !remove.isPending) setArmToDelete(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove treatment arm</DialogTitle>
            <DialogDescription>
              Remove {armToDelete?.name}? Any Schedule of Assessment configured specifically for this arm will also be removed. This cannot be changed after the design version is published.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={remove.isPending} onClick={() => setArmToDelete(null)}>Cancel</Button>
            <Button type="button" variant="destructive" pending={remove.isPending} loadingText="Removing…" onClick={() => armToDelete && remove.mutate(armToDelete)}>Remove arm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}

export function ArmsPage({ studyId }: { studyId: string }) {
  return <PermissionGuard permission={PERMISSIONS.DESIGNER_ARM_READ} studyId={studyId}><DraftGate studyId={studyId}>{(versionId, selection) => <ArmsEditor studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}</DraftGate></PermissionGuard>
}
