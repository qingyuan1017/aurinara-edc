import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS } from '@/lib/permissions'
import type { CrfAccessDefinitionCreate, CrfAccessDefinitionResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, FormActions, FormField, PageContainer, PageHeader } from '@/components/patterns'
import { DraftGate, getApiErrorMessage } from './shared'

function CrfAccessEditor({ versionId, readOnly }: { versionId: string; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const [role, setRole] = useState('')
  const [canRead, setCanRead] = useState(true)
  const [canWrite, setCanWrite] = useState(false)
  const [formId, setFormId] = useState('')
  const [fieldId, setFieldId] = useState('')
  const [blinded, setBlinded] = useState(false)
  const [unblindRole, setUnblindRole] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const listQuery = useQuery({ queryKey: ['designer-crf-access', versionId], queryFn: async () => (await api.get<CrfAccessDefinitionResponse[]>(`/designer/versions/${versionId}/crf-access`)).data })

  // The backend requires blinded===true when unblind_role is set; mirror the
  // rule in the UI by clearing/disabling unblind_role whenever blinded is off.
  const setBlindedAndSync = (next: boolean) => {
    setBlinded(next)
    if (!next) setUnblindRole('')
  }

  const create = useMutation({
    mutationFn: async () => {
      if (!role.trim()) throw new Error('A role is required.')
      const payload: CrfAccessDefinitionCreate = {
        role: role.trim(),
        can_read: canRead,
        can_write: canWrite,
        form_definition_id: formId.trim() || null,
        field_definition_id: fieldId.trim() || null,
        blinded,
        unblind_role: blinded && unblindRole.trim() ? unblindRole.trim() : null,
      }
      return (await api.post<CrfAccessDefinitionResponse>(`/designer/versions/${versionId}/crf-access`, payload)).data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['designer-crf-access', versionId] })
      setRole(''); setFormId(''); setFieldId(''); setCanRead(true); setCanWrite(false)
      setBlinded(false); setUnblindRole('')
      setError(''); setMessage(`CRF access rule for "${data.role}" added.`)
    },
    onError: (err) => { setError(getApiErrorMessage(err, 'Could not create the CRF access rule.')); setMessage('') },
  })

  return (
    <PageContainer wide>
      <PageHeader title="CRF access" description={readOnly ? 'Review role-based form and field access retained in this published design version.' : 'Grant role-based read/write access to forms and fields for the current draft version.'} />
      {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        {!readOnly ? <Card>
          <CardHeader><CardTitle className="text-base">New access rule</CardTitle></CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
              <FormField label="Role" name="crf-role" required>
                <Input value={role} onChange={(event) => setRole(event.target.value)} placeholder="Investigator" required />
              </FormField>
              <div className="flex items-center gap-6">
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={canRead} onChange={(event) => setCanRead(event.target.checked)} /> Can read</label>
                <label className="flex items-center gap-2 text-sm"><Checkbox checked={canWrite} onChange={(event) => setCanWrite(event.target.checked)} /> Can write</label>
              </div>
              <FormField label="Form definition ID" name="crf-form" description="Optional. Scope the rule to a specific form.">
                <Input value={formId} onChange={(event) => setFormId(event.target.value)} placeholder="uuid" />
              </FormField>
              <FormField label="Field definition ID" name="crf-field" description="Optional. Scope the rule to a specific field.">
                <Input value={fieldId} onChange={(event) => setFieldId(event.target.value)} placeholder="uuid" />
              </FormField>
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={blinded} onChange={(event) => setBlindedAndSync(event.target.checked)} /> Blinded</label>
              <FormField label="Unblind role" name="crf-unblind-role" description="Optional. Role permitted to unblind; requires Blinded.">
                <Input
                  value={unblindRole}
                  onChange={(event) => setUnblindRole(event.target.value)}
                  placeholder="Medical Monitor"
                  disabled={!blinded}
                />
              </FormField>
              <FormActions pending={create.isPending} submitLabel="Add rule" pendingLabel="Adding…" />
            </form>
          </CardContent>
        </Card> : null}

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Access rules</CardTitle>
            <span className="text-xs text-muted-foreground">{listQuery.data?.length ?? 0}</span>
          </CardHeader>
          <CardContent>
            <DataTableShell label="CRF access rules" empty={!listQuery.data?.length} emptyTitle="No access rules" emptyDescription="Rules for the selected version appear here.">
              <Table>
                <caption className="sr-only">CRF access rules for the selected design version</caption>
                <TableHeader><TableRow>{['Role', 'Read', 'Write', 'Blinded', 'Unblind role', 'Form', 'Field'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{(listQuery.data ?? []).map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">{row.role}</TableCell>
                    <TableCell>{row.can_read ? 'Yes' : 'No'}</TableCell>
                    <TableCell>{row.can_write ? 'Yes' : 'No'}</TableCell>
                    <TableCell>{row.blinded ? 'Yes' : 'No'}</TableCell>
                    <TableCell>{row.unblind_role ?? '—'}</TableCell>
                    <TableCell className="max-w-[8rem] truncate" title={row.form_definition_id ?? undefined}>{row.form_definition_id ?? 'All'}</TableCell>
                    <TableCell className="max-w-[8rem] truncate" title={row.field_definition_id ?? undefined}>{row.field_definition_id ?? 'All'}</TableCell>
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

export function CrfAccessPage({ studyId }: { studyId: string }) {
  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_CRF_ACCESS_CONFIGURE} studyId={studyId}>
      <DraftGate studyId={studyId}>
        {(versionId, selection) => <CrfAccessEditor versionId={versionId} readOnly={selection.isReadOnly} />}
      </DraftGate>
    </PermissionGuard>
  )
}
