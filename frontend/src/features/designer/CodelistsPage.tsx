import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PermissionGuard } from '@/components/guards/PermissionGuard'
import { PERMISSIONS, usePermission } from '@/lib/permissions'
import type { CodelistCreate, CodelistItemCreate, CodelistResponse } from '@/api/model'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, EmptyState, ErrorState, FormActions, FormField, LoadingState, PageContainer, PageHeader } from '@/components/patterns'
import { getApiErrorMessage } from './shared'

interface DraftItem extends CodelistItemCreate {
  key: string
}

const makeKey = () => Math.random().toString(36).slice(2)

function emptyItem(order: number): DraftItem {
  return { key: makeKey(), code: '', label: '', display_order: order }
}

/**
 * Codelist authoring — controlled vocabularies for the current draft version.
 *
 * Codelists are study-scoped: the Designer service resolves the latest draft
 * Design_Version server-side. Lists and detail reads are available; creation
 * accepts an optional set of initial items (Requirement 6.1).
 */
export function CodelistsPage({ studyId }: { studyId: string }) {
  const client = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.DESIGNER_CODELIST_CONFIGURE, studyId)
  const [showForm, setShowForm] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [items, setItems] = useState<DraftItem[]>([emptyItem(1)])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const listQuery = useQuery({
    queryKey: ['designer-codelists', studyId],
    queryFn: async () => (await api.get<CodelistResponse[]>(`/designer/studies/${studyId}/codelists`)).data,
  })

  const detailQuery = useQuery({
    queryKey: ['designer-codelist', selectedId],
    queryFn: async () => (await api.get<CodelistResponse>(`/designer/codelists/${selectedId}`)).data,
    enabled: Boolean(selectedId),
  })

  const resetForm = () => {
    setName('')
    setCode('')
    setItems([emptyItem(1)])
    setError('')
  }

  const create = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error('A codelist name is required.')
      if (!code.trim()) throw new Error('A codelist code is required.')
      const cleanedItems = items
        .filter((item) => item.code.trim() || item.label.trim())
        .map((item, index) => ({
          code: item.code.trim(),
          label: item.label.trim(),
          display_order: index + 1,
        }))
      if (cleanedItems.some((item) => !item.code || !item.label)) {
        throw new Error('Each code list item needs both a code and a label.')
      }
      const payload: CodelistCreate = {
        name: name.trim(),
        code: code.trim(),
        items: cleanedItems.length ? cleanedItems : undefined,
      }
      return (await api.post<CodelistResponse>(`/designer/studies/${studyId}/codelists`, payload)).data
    },
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['designer-codelists', studyId] })
      setShowForm(false)
      resetForm()
      setSelectedId(data.id)
      setMessage(`Codelist "${data.name}" created.`)
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Could not create the codelist.')),
  })

  const selected = detailQuery.data
  const selectedItems = useMemo(
    () => [...(selected?.items ?? [])].sort((a, b) => a.display_order - b.display_order),
    [selected],
  )

  return (
    <PermissionGuard permission={PERMISSIONS.DESIGNER_CODELIST_READ} studyId={studyId}>
      <PageContainer wide>
        <PageHeader
          title="Codelists"
          description="Controlled vocabularies authored against the current draft version."
          actions={canConfigure ? (
            <Button type="button" onClick={() => { setShowForm((open) => !open); setMessage(''); setError('') }}>
              {showForm ? 'Close' : 'New codelist'}
            </Button>
          ) : null}
        />

        {message ? <Alert variant="success" className="mb-4"><AlertDescription>{message}</AlertDescription></Alert> : null}
        {error ? <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert> : null}

        {showForm && canConfigure ? (
          <Card className="mb-6">
            <CardHeader><CardTitle className="text-base">New codelist</CardTitle></CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}>
                <div className="grid gap-4 md:grid-cols-2">
                  <FormField label="Name" name="codelist-name" required>
                    <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Severity grades" required />
                  </FormField>
                  <FormField label="Code" name="codelist-code" required description="Stable identifier used by form fields.">
                    <Input value={code} onChange={(event) => setCode(event.target.value)} placeholder="SEV_GRADE" required />
                  </FormField>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">Items</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => setItems((prev) => [...prev, emptyItem(prev.length + 1)])}>Add item</Button>
                  </div>
                  <div className="space-y-2">
                    {items.map((item, index) => (
                      <div key={item.key} className="grid grid-cols-[1fr_2fr_auto] items-end gap-2">
                        <FormField label={index === 0 ? 'Code' : ''} name={`item-code-${item.key}`}>
                          <Input aria-label={`Item ${index + 1} code`} value={item.code} onChange={(event) => setItems((prev) => prev.map((it) => it.key === item.key ? { ...it, code: event.target.value } : it))} placeholder="1" />
                        </FormField>
                        <FormField label={index === 0 ? 'Label' : ''} name={`item-label-${item.key}`}>
                          <Input aria-label={`Item ${index + 1} label`} value={item.label} onChange={(event) => setItems((prev) => prev.map((it) => it.key === item.key ? { ...it, label: event.target.value } : it))} placeholder="Mild" />
                        </FormField>
                        <Button type="button" variant="ghost" size="sm" aria-label={`Remove item ${index + 1}`} disabled={items.length === 1} onClick={() => setItems((prev) => prev.filter((it) => it.key !== item.key))}>Remove</Button>
                      </div>
                    ))}
                  </div>
                </div>

                <FormActions pending={create.isPending} submitLabel="Create codelist" pendingLabel="Creating…" onCancel={() => { setShowForm(false); resetForm() }} />
              </form>
            </CardContent>
          </Card>
        ) : null}

        <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Codelists</CardTitle>
              <span className="text-xs text-muted-foreground">{listQuery.data?.length ?? 0}</span>
            </CardHeader>
            <CardContent className="space-y-2">
              {listQuery.isLoading ? <LoadingState label="codelists" className="border-0 p-0 shadow-none" /> : null}
              {listQuery.isError ? <ErrorState message="Unable to load codelists." onRetry={() => void listQuery.refetch()} /> : null}
              {!listQuery.isLoading && !listQuery.isError && !listQuery.data?.length ? (
                <EmptyState title="No codelists yet" description="Create a codelist to define a controlled vocabulary." className="min-h-32 p-4" />
              ) : null}
              {listQuery.data?.map((codelist) => (
                <button
                  type="button"
                  key={codelist.id}
                  onClick={() => setSelectedId(codelist.id)}
                  aria-pressed={codelist.id === selectedId}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${codelist.id === selectedId ? 'border-primary bg-primary/10 text-primary' : 'border-transparent hover:bg-muted'}`}
                >
                  <span className="block font-medium">{codelist.name}</span>
                  <span className="block text-xs text-muted-foreground">{codelist.code}</span>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">{selected ? selected.name : 'Codelist detail'}</CardTitle></CardHeader>
            <CardContent>
              {!selectedId ? (
                <EmptyState title="Select a codelist" description="Choose a codelist to view its items." className="min-h-32 p-4" />
              ) : detailQuery.isLoading ? (
                <LoadingState label="codelist" className="border-0 p-0 shadow-none" />
              ) : detailQuery.isError ? (
                <ErrorState message="Unable to load this codelist." onRetry={() => void detailQuery.refetch()} />
              ) : (
                <DataTableShell label="Codelist items" empty={!selectedItems.length} emptyTitle="No items" emptyDescription="This codelist has no items.">
                  <Table>
                    <caption className="sr-only">Codelist items for {selected?.name}</caption>
                    <TableHeader><TableRow>{['Order', 'Code', 'Label'].map((heading) => <TableHead key={heading}>{heading}</TableHead>)}</TableRow></TableHeader>
                    <TableBody>{selectedItems.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="whitespace-nowrap">{item.display_order}</TableCell>
                        <TableCell className="font-medium">{item.code}</TableCell>
                        <TableCell>{item.label}</TableCell>
                      </TableRow>
                    ))}</TableBody>
                  </Table>
                </DataTableShell>
              )}
            </CardContent>
          </Card>
        </div>
      </PageContainer>
    </PermissionGuard>
  )
}
