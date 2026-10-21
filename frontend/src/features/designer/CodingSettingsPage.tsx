import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import type { CodingSettingCreate, CodingSettingResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

interface CodingForm { name: string; form_code: string; sections?: Array<{ fields?: Array<{ id: string; label: string; variable_name: string }> }> }

function CodingSettingsEditor({ studyId, versionId, readOnly }: { studyId: string; versionId: string; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const [dictionary, setDictionary] = useState('')
  const [codingRule, setCodingRule] = useState('')
  const [fieldId, setFieldId] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const listQuery = useQuery({ queryKey: ['designer-coding-settings', versionId], queryFn: async () => (await api.get<CodingSettingResponse[]>(`/designer/versions/${versionId}/coding-settings`)).data })
  const formsQuery = useQuery({ queryKey: ['coding-field-options', studyId, versionId], queryFn: async () => (await api.get<CodingForm[]>(`/designer/studies/${studyId}/forms`, { params: { study_version_id: versionId } })).data })
  const fieldOptions = (formsQuery.data ?? []).flatMap((form) => (form.sections ?? []).flatMap((section) => (section.fields ?? []).map((field) => ({ id: field.id, label: `${form.form_code} · ${field.label} (${field.variable_name})` }))))
  const fieldLabels = new Map(fieldOptions.map((field) => [field.id, field.label]))

  const create = useMutation({
    mutationFn: async () => {
      if (!dictionary.trim()) throw new Error('A dictionary reference is required.')
      const payload: CodingSettingCreate = {
        dictionary_reference: dictionary.trim(),
        coding_rule: codingRule.trim() || null,
        field_definition_id: fieldId.trim() || null,
      }
      return (await api.post<CodingSettingResponse>(`/designer/versions/${versionId}/coding-settings`, payload)).data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['designer-coding-settings', versionId] })
      setDictionary(''); setCodingRule(''); setFieldId('')
      setError(''); setMessage(`Coding setting for "${data.dictionary_reference}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the coding setting.')); setMessage('') },
  })

  return (
    <PageContainer wide>
      <PageHeader title="Coding settings" description={readOnly ? 'Review medical-dictionary coding retained in this published design version.' : 'Configure medical-dictionary coding for the current draft version.'} />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {!readOnly ? <Card>
          <CardHeader><CardTitle className="text-base">New coding setting</CardTitle></CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
              <FormField label="Dictionary reference" name="coding-dictionary" required>
                <Input value={dictionary} onChange={(event) => setDictionary(event.target.value)} placeholder="MedDRA 27.0" required />
              </FormField>
              <FormField label="Coding rule" name="coding-rule" description="Optional rule describing how coding is applied.">
                <Textarea value={codingRule} onChange={(event) => setCodingRule(event.target.value)} placeholder="Auto-code verbatim AE terms." />
              </FormField>
              <FormField label="Clinical field" name="coding-field" description="Optional. Scope the setting to a specific field.">
                <select value={fieldId} onChange={(event) => setFieldId(event.target.value)} disabled={formsQuery.isLoading} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">All eligible fields</option>{fieldOptions.map((field) => <option key={field.id} value={field.id}>{field.label}</option>)}</select>
              </FormField>
              <FormActions pending={create.isPending} submitLabel="Add setting" pendingLabel="Adding…" />
            </form>
          </CardContent>
        </Card> : null}

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Coding settings</CardTitle>
            <span className="text-xs text-muted-foreground">{listQuery.data?.length ?? 0}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="Coding settings" empty={!listQuery.data?.length} emptyTitle="No coding settings" emptyDescription="Settings for the selected version appear here.">
              <Table>
                <caption className="sr-only">Coding settings for the selected design version</caption>
                <TableHeader><TableRow>{['Dictionary', 'Rule', 'Field'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{(listQuery.data ?? []).map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">{row.dictionary_reference}</TableCell>
                    <TableCell>{row.coding_rule || '—'}</TableCell>
                    <TableCell>{row.field_definition_id ? fieldLabels.get(row.field_definition_id) ?? 'Unavailable field' : 'All eligible fields'}</TableCell>
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

export function CodingSettingsPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_CODING_SETTING_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => <CodingSettingsEditor studyId={studyId} versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
