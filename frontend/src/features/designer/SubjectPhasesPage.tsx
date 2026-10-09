import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import type { SubjectPhaseDefinitionCreate, SubjectPhaseDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

function SubjectPhasesEditor({ versionId }: { versionId: string }) {
  const [name, setName] = useState('')
  const [displayOrder, setDisplayOrder] = useState(1)
  const [created, setCreated] = useState<SubjectPhaseDefinitionResponse[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('A phase name is required.')
      const payload: SubjectPhaseDefinitionCreate = { name: name.trim(), display_order: displayOrder }
      return (await api.post<SubjectPhaseDefinitionResponse>(`/designer/versions/${versionId}/subject-phases`, payload)).data
    },
    onSuccess: (data) => {
      setCreated((prev) => [...prev, data])
      setName('')
      setDisplayOrder((order) => order + 1)
      setError('')
      setMessage(`Subject phase "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the subject phase.')); setMessage('') },
  })

  const rows = [...created].sort((a, b) => a.display_order - b.display_order)

  return (
    <PageContainer wide>
      <PageHeader
        title="Subject phases"
        description="Define the phases subjects progress through for the current draft version."
      />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Card>
          <CardHeader><CardTitle className="text-base">New phase</CardTitle></CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
              <FormField label="Name" name="phase-name" required>
                <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Screening" required />
              </FormField>
              <FormField label="Display order" name="phase-order" required>
                <Input type="number" min={1} max={999} value={displayOrder} onChange={(event) => setDisplayOrder(Number(event.target.value))} required />
              </FormField>
              <FormActions pending={create.isPending} submitLabel="Add phase" pendingLabel="Adding…" />
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Added this session</CardTitle>
            <span className="text-xs text-muted-foreground">{rows.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Subject phases" empty={!rows.length} emptyTitle="No phases added yet" emptyDescription="Phases you create appear here.">
              <Table>
                <caption className="sr-only">Subject phases added this session</caption>
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

export function SubjectPhasesPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_SUBJECT_PHASE_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId) => <SubjectPhasesEditor versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
