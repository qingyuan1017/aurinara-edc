import { useQuery } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { DataTableShell, ErrorState, LoadingState, StatusBadge } from '@/components/patterns'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { SignatureRecord } from './SignatureDialog'

interface SignatureHistoryProps { subjectId: string }

/** Displays server-provided signature history without changing status or freshness semantics. */
export function SignatureHistory({ subjectId }: SignatureHistoryProps) {
  const { data, isLoading, error } = useQuery({ queryKey: ['subject-signatures', subjectId], queryFn: async () => (await api.get<PaginatedResponse<SignatureRecord>>(`/subjects/${subjectId}/signatures`)).data })
  if (isLoading) return <LoadingState label="signatures" />
  if (error) return <ErrorState message="Failed to load signatures." />
  const items = data?.items ?? []
  return <section className="space-y-3" aria-labelledby="signature-history-title">
    <div className="flex items-center justify-between gap-3"><div><h2 id="signature-history-title" className="text-lg font-semibold">Signature history</h2><p className="text-xs text-muted-foreground">Signatures are retained when signed data later becomes stale.</p></div><span className="text-sm text-muted-foreground">{data?.total ?? 0} total</span></div>
    <DataTableShell label="signature history" state={items.length ? undefined : 'empty'} emptyTitle="No electronic signatures" emptyDescription="No electronic signatures have been recorded.">
      <Table><TableHeader><TableRow><TableHead>Attestation</TableHead><TableHead>Signed by</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{items.map((signature) => <TableRow key={signature.id}><TableCell><p className="font-medium capitalize">{signature.object_type} signature</p><p>{signature.signature_meaning}</p>{signature.status === 'stale' && signature.stale_reason ? <p className="mt-1 text-xs text-warning-foreground">Stale: {signature.stale_reason}</p> : null}</TableCell><TableCell className="text-muted-foreground">{new Date(signature.signed_at).toLocaleString()} · {signature.signed_by}</TableCell><TableCell><StatusBadge label="signature status" status={signature.status} /></TableCell></TableRow>)}</TableBody></Table>
    </DataTableShell>
  </section>
}
