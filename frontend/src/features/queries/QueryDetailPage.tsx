import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { DataTableShell, ErrorState, LoadingState, OwnershipBadge, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface QueryMessage { id: string; author_id: string; message: string; created_at: string }
interface QueryDetail { id: string; target_type: string; target_id: string; text: string; query_type: string; assigned_role?: string | null; status: string; created_at: string; messages: QueryMessage[] }

export function QueryDetailPage({ queryId }: { queryId: string }) {
  const client = useQueryClient(); const [response, setResponse] = useState(''); const [error, setError] = useState('')
  const canRespond = usePermission(PERMISSIONS.QUERY_RESPOND); const canClose = usePermission(PERMISSIONS.QUERY_CLOSE); const canReopen = usePermission(PERMISSIONS.QUERY_REOPEN)
  const query = useQuery({ queryKey: ['query', queryId], queryFn: async () => (await api.get<QueryDetail>(`/queries/${queryId}`)).data })
  const action = useMutation({ mutationFn: ({ verb, body }: { verb: string; body?: object }) => api.post(`/queries/${queryId}/${verb}`, body), onSuccess: () => { client.invalidateQueries({ queryKey: ['query', queryId] }); client.invalidateQueries({ queryKey: ['queries'] }); setResponse(''); setError('') }, onError: () => setError('The query action could not be completed.') })
  if (query.isLoading) return <PageContainer><LoadingState label="query" /></PageContainer>
  if (query.error || !query.data) return <PageContainer><ErrorState message="Query not found or unavailable." /></PageContainer>
  const item = query.data
  const canRespondNow = canRespond && ['Open', 'Reopened'].includes(item.status)

  return <PageContainer wide>
    <PageHeader title={`Query ${item.id.slice(0, 8)}`} description={<><a href="/queries" className="text-primary hover:underline">← Query inbox</a><span className="ml-2">{item.target_type} · {item.target_id} · {item.query_type}{item.assigned_role ? ` · Assigned to ${item.assigned_role}` : ''}</span></>} status={<StatusBadge label="query status" status={item.status} />} ownership={<OwnershipBadge owner="EDC" />} />
    {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}
    <div className="space-y-5">
      <Card><CardContent className="pt-6"><p className="whitespace-pre-wrap text-sm">{item.text}</p><p className="mt-3 text-xs text-muted-foreground">Opened {new Date(item.created_at).toLocaleString()}</p></CardContent></Card>
      <section className="space-y-3" aria-labelledby="query-thread-title"><h2 id="query-thread-title" className="text-lg font-semibold">Thread</h2>{item.messages.length ? item.messages.map((message) => <Card key={message.id}><CardContent className="pt-6"><p className="whitespace-pre-wrap text-sm">{message.message}</p><p className="mt-2 text-xs text-muted-foreground">{message.author_id.slice(0, 8)} · {new Date(message.created_at).toLocaleString()}</p></CardContent></Card>) : <DataTableShell label="query thread" state="empty" emptyTitle="No responses yet" emptyDescription="Responses will appear here when the query is addressed." />}</section>
      {canRespondNow ? <Card><CardHeader><CardTitle className="text-base">Add response</CardTitle></CardHeader><CardContent><form onSubmit={(event) => { event.preventDefault(); if (!response.trim()) { setError('Enter a response before sending.'); return } action.mutate({ verb: 'respond', body: { message: response.trim() } }) }} className="space-y-3"><Label htmlFor="query-response">Response</Label><Textarea id="query-response" required value={response} onChange={(event) => setResponse(event.target.value)} placeholder="Describe the data clarification or resolution." /><Button disabled={action.isPending} pending={action.isPending} loadingText="Sending…">Send response</Button></form></CardContent></Card> : null}
      <div className="flex flex-wrap gap-2 border-t pt-4">{canClose && ['Open', 'Answered', 'Reopened'].includes(item.status) ? <Button variant="outline" onClick={() => action.mutate({ verb: 'close' })} disabled={action.isPending}>Close query</Button> : null}{canReopen && item.status === 'Closed' ? <Button variant="outline" onClick={() => action.mutate({ verb: 'reopen' })} disabled={action.isPending}>Reopen query</Button> : null}</div>
    </div>
  </PageContainer>
}
