import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

interface FormRecord { id: string; sequence_number: number; data_jsonb?: Record<string, unknown> | null; deleted_at?: string | null }

export function RepeatingRecordsTable({ formInstanceId, submitted, disabled }: { formInstanceId: string; submitted: boolean; disabled: boolean }) {
  const client = useQueryClient()
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const query = useQuery({ queryKey: ['form-records', formInstanceId], queryFn: async () => (await api.get<PaginatedResponse<FormRecord>>(`/form-instances/${formInstanceId}/records`, { params: { page: 1, page_size: 100, include_deleted: true } })).data })
  const refresh = () => void client.invalidateQueries({ queryKey: ['form-records', formInstanceId] })
  const reason = () => submitted ? window.prompt('Reason for change (required after submission)')?.trim() : undefined
  const mutation = useMutation({
    mutationFn: async ({ record, action }: { record?: FormRecord; action: 'add' | 'save' | 'delete' | 'restore' }) => {
      const changeReason = reason()
      if (submitted && !changeReason) throw new Error('A reason for change is required.')
      if (action === 'add') return api.post(`/form-instances/${formInstanceId}/records`, { values: {}, reason: changeReason })
      if (!record) throw new Error('Record is required')
      if (action === 'delete') return api.delete(`/records/${record.id}`, { data: { reason: changeReason || 'Removed before submission' } })
      if (action === 'restore') return api.post(`/records/${record.id}/restore`, { reason: changeReason })
      let values: Record<string, unknown>
      try { values = JSON.parse(drafts[record.id] ?? JSON.stringify(record.data_jsonb ?? {})) as Record<string, unknown> } catch { throw new Error('Record values must be valid JSON.') }
      return api.patch(`/records/${record.id}`, { values, reason: changeReason })
    },
    onSuccess: () => { setError(''); refresh() },
    onError: (caught) => setError(caught instanceof Error ? caught.message : 'Repeating record action failed.'),
  })
  const rows = query.data?.items ?? []
  return <Card><CardHeader className="flex-row items-center justify-between"><CardTitle className="text-lg">Repeating records</CardTitle><Button size="sm" disabled={disabled || mutation.isPending} onClick={() => mutation.mutate({ action: 'add' })}>Add record</Button></CardHeader><CardContent>{error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}<Table><TableHeader><TableRow><TableHead>Sequence</TableHead><TableHead>Values</TableHead><TableHead>Status</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader><TableBody>{rows.map((record) => <TableRow key={record.id}><TableCell>{record.sequence_number}</TableCell><TableCell><Textarea aria-label={`Record ${record.sequence_number} values`} disabled={disabled || Boolean(record.deleted_at)} value={drafts[record.id] ?? JSON.stringify(record.data_jsonb ?? {}, null, 2)} onChange={(event) => setDrafts((current) => ({ ...current, [record.id]: event.target.value }))} className="min-h-24 font-mono text-xs" /></TableCell><TableCell>{record.deleted_at ? 'Deleted' : 'Active'}</TableCell><TableCell><div className="flex flex-wrap gap-2">{record.deleted_at ? <Button size="sm" variant="outline" disabled={disabled || mutation.isPending} onClick={() => mutation.mutate({ record, action: 'restore' })}>Restore</Button> : <><Button size="sm" variant="outline" disabled={disabled || mutation.isPending} onClick={() => mutation.mutate({ record, action: 'save' })}>Save row</Button><Button size="sm" variant="destructive" disabled={disabled || mutation.isPending} onClick={() => mutation.mutate({ record, action: 'delete' })}>Delete</Button></>}</div></TableCell></TableRow>)}</TableBody></Table>{!query.isLoading && rows.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">No repeating records have been added.</p> : null}</CardContent></Card>
}
