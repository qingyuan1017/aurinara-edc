import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import type { ArmDefinitionCreate, ArmDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

function ArmsEditor({ versionId }: { versionId: string }) {
  const [name, setName] = useState('')
  const [displayOrder, setDisplayOrder] = useState(1)
  const [description, setDescription] = useState('')
  const [created, setCreated] = useState<ArmDefinitionResponse[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('An arm name is required.')
      const payload: ArmDefinitionCreate = { name: name.trim(), display_order: displayOrder, description: description.trim() || null }
      return (await api.post<ArmDefinitionResponse>(`/designer/versions/${versionId}/arms`, payload)).data
    },
    onSuccess: (data) => {
      setCreated((prev) => [...prev, data])
      setName(''); setDescription(''); setDisplayOrder((order) => order + 1)
      setError(''); setMessage(`Arm "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the arm.')); setMessage('') },
  })

  const rows = [...created].sort((a, b) => a.display_order - b.display_order)

  return (
    <PageContainer wide>
      <PageHeader title="Treatment arms" description="Define the treatment arms for the current draft version." />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
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
              <FormActions pending={create.isPending} submitLabel="Add arm" pendingLabel="Adding…" />
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Added this session</CardTitle>
            <span className="text-xs text-muted-foreground">{rows.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Treatment arms" empty={!rows.length} emptyTitle="No arms added yet" emptyDescription="Arms you create appear here.">
              <Table>
                <caption className="sr-only">Treatment arms added this session</caption>
                <TableHeader><TableRow>{['Order', 'Name', 'Description'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{rows.map((row) => (
                  <TableRow key={row.id}><TableCell>{row.display_order}</TableCell><TableCell className="font-medium">{row.name}</TableCell><TableCell>{row.description || '—'}</TableCell></TableRow>
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
    <PermissionGuard permission={PERMISSIONS.DESIGNER_ARM_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId) => <ArmsEditor versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
