import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import type { RawDataVariableSettingCreate, RawDataVariableSettingResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

const EMPTY_ATTRIBUTES = '{}'

function RawDataVariablesEditor({ versionId }: { versionId: string }) {
  const [name, setName] = useState('')
  const [dataType, setDataType] = useState('')
  const [label, setLabel] = useState('')
  const [suffix, setSuffix] = useState('')
  const [attributesText, setAttributesText] = useState(EMPTY_ATTRIBUTES)
  const [created, setCreated] = useState<RawDataVariableSettingResponse[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('A variable name is required.')
      if (!dataType.trim()) throw new Error('A data type is required.')
      let attributes: Record<string, unknown> | undefined
      const trimmed = attributesText.trim()
      if (trimmed && trimmed !== '{}') {
        try {
          attributes = JSON.parse(trimmed) as Record<string, unknown>
        } catch {
          throw new Error('Attributes must be valid JSON.')
        }
      }
      const payload: RawDataVariableSettingCreate = {
        name: name.trim(),
        data_type: dataType.trim(),
        attributes,
        label: label.trim() || null,
        suffix: suffix.trim() || null,
      }
      return (await api.post<RawDataVariableSettingResponse>(`/designer/versions/${versionId}/raw-data-variables`, payload)).data
    },
    onSuccess: (data) => {
      setCreated((prev) => [...prev, data])
      setName(''); setDataType(''); setLabel(''); setSuffix(''); setAttributesText(EMPTY_ATTRIBUTES)
      setError(''); setMessage(`Raw-data variable "${data.name}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the raw-data variable.')); setMessage('') },
  })

  return (
    <PageContainer wide>
      <PageHeader title="Raw-data variables" description="Define raw-data variable settings for the current draft version." />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Card>
          <CardHeader><CardTitle className="text-base">New variable</CardTitle></CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
              <FormField label="Name" name="rdv-name" required>
                <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="SUBJID" required />
              </FormField>
              <FormField label="Data type" name="rdv-type" required>
                <Input value={dataType} onChange={(event) => setDataType(event.target.value)} placeholder="string" required />
              </FormField>
              <FormField label="Label" name="rdv-label" description="Optional display label for a fixed variable.">
                <Input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Subject identifier" />
              </FormField>
              <FormField label="Suffix" name="rdv-suffix" description="Optional suffix for special variable types.">
                <Input value={suffix} onChange={(event) => setSuffix(event.target.value)} placeholder="_RAW" />
              </FormField>
              <FormField label="Attributes (JSON)" name="rdv-attributes" description="Optional JSON object of additional attributes.">
                <Textarea value={attributesText} onChange={(event) => setAttributesText(event.target.value)} className="min-h-24 font-mono text-sm" />
              </FormField>
              <FormActions pending={create.isPending} submitLabel="Add variable" pendingLabel="Adding…" />
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Added this session</CardTitle>
            <span className="text-xs text-muted-foreground">{created.length}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Raw-data variables" empty={!created.length} emptyTitle="No variables added yet" emptyDescription="Variables you create appear here.">
              <Table>
                <caption className="sr-only">Raw-data variables added this session</caption>
                <TableHeader><TableRow>{['Name', 'Data type', 'Label', 'Suffix'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{created.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell>{row.data_type}</TableCell>
                    <TableCell>{row.label ?? '—'}</TableCell>
                    <TableCell>{row.suffix ?? '—'}</TableCell>
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

export function RawDataVariablesPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_RAW_DATA_VARIABLE_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId) => <RawDataVariablesEditor versionId={versionId} />}
      </DraftGate>
    </PermissionGuard>
  )
}
