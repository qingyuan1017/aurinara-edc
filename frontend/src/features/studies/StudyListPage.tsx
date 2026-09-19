import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { api } from '@/lib/api'
import type { PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface Study {
  id: string
  study_code: string
  title: string
  phase: string
  status: string
  created_at: string
}

interface CreateStudyPayload {
  study_code: string
  title: string
  phase: string
}

const columnHelper = createColumnHelper<Study>()

const columns = [
  columnHelper.accessor('study_code', {
    header: 'Code',
    cell: (info) => <a href={`/studies/${info.row.original.id}`} className="font-medium text-primary hover:underline">{info.getValue()}</a>,
  }),
  columnHelper.accessor('title', { header: 'Title' }),
  columnHelper.accessor('phase', { header: 'Phase' }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusBadge status={info.getValue()} label="Study status" />,
  }),
  columnHelper.accessor('created_at', {
    header: 'Created',
    cell: (info) => new Date(info.getValue()).toLocaleDateString(),
  }),
]

export function StudyListPage() {
  const queryClient = useQueryClient()
  const canCreate = usePermission(PERMISSIONS.STUDY_CREATE)
  const [page, setPage] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [formData, setFormData] = useState<CreateStudyPayload>({ study_code: '', title: '', phase: '' })
  const [error, setError] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['studies', page],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Study>>('/studies', {
        params: { page, page_size: 20 },
      })
      return data
    },
  })

  const createMutation = useMutation({
    mutationFn: async (payload: CreateStudyPayload) => {
      const { data } = await api.post('/studies', payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['studies'] })
      setShowModal(false)
      setFormData({ study_code: '', title: '', phase: '' })
      setError(null)
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to create study')
    },
  })

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0
  const hasRows = Boolean(data && data.items.length > 0)

  return (
    <PageContainer wide>
      <PageHeader
        title="Studies"
        description="Review studies available in your authorized workspace."
        actions={canCreate ? <Button type="button" onClick={() => setShowModal(true)}>Create Study</Button> : null}
      />

      <PageToolbar label="Study list controls">
        <span className="text-sm text-muted-foreground">
          {data ? `${data.total} total studies · server ordered` : 'Server-ordered study records'}
        </span>
      </PageToolbar>

      <DataTableShell
        label="Studies"
        loading={isLoading}
        error={isError}
        errorMessage="Failed to load studies."
        onRetry={() => void refetch()}
        empty={!isLoading && !isError && Boolean(data) && !hasRows}
        emptyTitle="No studies found."
        emptyDescription="No studies are available for the current permissions."
      >
        <Table>
          <caption className="sr-only">Studies</caption>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableShell>

      {totalPages > 1 ? (
        <PageToolbar label="Study pagination" className="mt-4 mb-0">
          <p className="text-sm text-muted-foreground">Page {page} of {totalPages} ({data?.total ?? 0} total)</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>Next</Button>
          </div>
        </PageToolbar>
      ) : null}

      <Dialog open={showModal} onOpenChange={(open) => { setShowModal(open); if (!open) setError(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Study</DialogTitle><DialogDescription>Create a study in the current authorized workspace.</DialogDescription></DialogHeader>
          {error ? <p className="rounded border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <form onSubmit={(event) => { event.preventDefault(); createMutation.mutate(formData) }} className="space-y-3">
            <div className="space-y-1.5"><Label htmlFor="study-code">Code</Label><Input id="study-code" type="text" value={formData.study_code} onChange={(event) => setFormData((current) => ({ ...current, study_code: event.target.value }))} required /></div>
            <div className="space-y-1.5"><Label htmlFor="study-title">Title</Label><Input id="study-title" type="text" value={formData.title} onChange={(event) => setFormData((current) => ({ ...current, title: event.target.value }))} required /></div>
            <div className="space-y-1.5"><Label htmlFor="study-phase">Phase</Label><Select value={formData.phase} onValueChange={(value) => setFormData((current) => ({ ...current, phase: value }))}><SelectTrigger id="study-phase" aria-label="Phase"><SelectValue placeholder="Select phase…" /></SelectTrigger><SelectContent><SelectItem value="I">Phase I</SelectItem><SelectItem value="II">Phase II</SelectItem><SelectItem value="III">Phase III</SelectItem><SelectItem value="IV">Phase IV</SelectItem></SelectContent></Select></div>
            <DialogFooter><Button type="button" variant="outline" onClick={() => { setShowModal(false); setError(null) }}>Cancel</Button><Button type="submit" pending={createMutation.isPending} loadingText="Creating…">Create</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
