import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import type { CycleDefinitionCreate, CycleDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

function CyclesEditor({ versionId }: { versionId: string }) {
  const [name, setName] = useState('')
  const [displayOrder, setDisplayOrder] = useState(1)
  const [visitIds, setVisitIds] = useState('')
  const [created, setCreated] = useState<CycleDefinitionResponse[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('A cycle name is required.')
      const ids = visitIds.split(',').map((value) => value.trim()).filter(Boolean)
      const payload: CycleDefinitionCreate = { name: name.trim(), display_order: displayOrder, visit_definition_ids: ids.length ? ids : undefined }
      return (await api.post<CycleDefinitionResponse>(`/designer/versions/${versionId}/cycles`, payload)).data
    },
    onSuccess: (data) => {
      setCreated((prev) => [...prev, data])
      setName(''); setVisitIds(''); setDisplayOrder((order) => order + 1)
      setError(''); setMessage(`Cycle "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the cycle.')); setMessage('') },
  })

  const rows = [...created].sort((a, b) => a.display_order - b.display_order)

  return (
    <PageContainer wide>
      <PageHeader title="Cycles" description="Define treatment cycles for the current draft version." />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Card>
          <CardHeader><CardTitle className="text-base">New cycle</CardTitle></CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
              <FormField label="Name" name="cycle-name" required>
                <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Cycle 1" required />
              </FormField>
              <FormField label="Display order" name="cycle-order" required>
                <Input type="number" min={1} max={999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required />
              </FormField>
              <FormField label="Visit definition IDs" name="cycle-visits" description="Optional comma-separated visit definition IDs assigned to this cycle.">
                <Input value={visitIds} onChange={(event) => setVisitIds(event.target.value)} placeholder="uuid-1, uuid-2" />
              </FormField>
              <FormActions pending={create.isPending} submitLabel="Add cycle" pendingLabel="Adding…" />
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Added this session</CardTitle>
            <span className="text-xs text-muted-foreground">{rows.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Cycles" empty={!rows.length} emptyTitle="No cycles added yet" emptyDescription="Cycles you create appear here.">
              <Table>
                <caption className="sr-only">Cycles added this session</caption>
                <TableHeader><TableRow>{['Order', 'Name'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{rows.map((row) => (
                  <TableRow key={row.id}><TableCell>{row.display_order}</TableCell><TableCell className="font-medium">{row.name}</TableCell></TableRow>
                ))}</TableBody>
              </Table>
            </DataTableShell>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}

export function CyclesPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_CYCLE_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId) => <CyclesEditor versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
