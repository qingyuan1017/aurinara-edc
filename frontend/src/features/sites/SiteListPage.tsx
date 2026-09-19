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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { api } from '@/lib/api'
import type { PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface Site {
  id: string
  site_number: string
  name: string
  principal_investigator: string
  country: string
  status: string
}

interface CreateSitePayload {
  site_number: string
  name: string
  principal_investigator: string
  country: string
}

const columnHelper = createColumnHelper<Site>()

const columns = [
  columnHelper.accessor('site_number', { header: 'Site #' }),
  columnHelper.accessor('name', { header: 'Name' }),
  columnHelper.accessor('principal_investigator', { header: 'PI' }),
  columnHelper.accessor('country', { header: 'Country' }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusBadge status={info.getValue()} label="Site status" />,
  }),
]

export function SiteListPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canManage = usePermission(PERMISSIONS.SITE_MANAGE)
  const [page, setPage] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [formData, setFormData] = useState<CreateSitePayload>({
    site_number: '',
    name: '',
    principal_investigator: '',
    country: '',
  })
  const [error, setError] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['sites', studyId, page],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Site>>(`/studies/${studyId}/sites`, {
        params: { page, page_size: 20 },
      })
      return data
    },
  })

  const createMutation = useMutation({
    mutationFn: async (payload: CreateSitePayload) => {
      const { data } = await api.post(`/studies/${studyId}/sites`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', studyId] })
      setShowModal(false)
      setFormData({ site_number: '', name: '', principal_investigator: '', country: '' })
      setError(null)
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to create site')
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
        title="Sites"
        description="Review sites for the selected study and preserve server-provided ordering."
        actions={canManage ? <Button type="button" onClick={() => setShowModal(true)}>Create Site</Button> : null}
      />

      <PageToolbar label="Site list controls">
        <span className="text-sm text-muted-foreground">
          {data ? `${data.total} total sites · server ordered` : `Sites for study ${studyId}`}
        </span>
      </PageToolbar>

      <DataTableShell
        label="Sites"
        loading={isLoading}
        error={isError}
        errorMessage="Failed to load sites."
        onRetry={() => void refetch()}
        empty={!isLoading && !isError && Boolean(data) && !hasRows}
        emptyTitle="No sites found."
        emptyDescription="No sites are available for the selected study and permissions."
      >
        <Table>
          <caption className="sr-only">Sites</caption>
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
        <PageToolbar label="Site pagination" className="mt-4 mb-0">
          <p className="text-sm text-muted-foreground">Page {page} of {totalPages} ({data?.total ?? 0} total)</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>Next</Button>
          </div>
        </PageToolbar>
      ) : null}

      <Dialog open={showModal} onOpenChange={(open) => { setShowModal(open); if (!open) setError(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Site</DialogTitle><DialogDescription>Add a site to the selected study.</DialogDescription></DialogHeader>
          {error ? <p className="rounded border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <form onSubmit={(event) => { event.preventDefault(); createMutation.mutate(formData) }} className="space-y-3">
            <div className="space-y-1.5"><Label htmlFor="site-number">Site Number</Label><Input id="site-number" type="text" value={formData.site_number} onChange={(event) => setFormData((current) => ({ ...current, site_number: event.target.value }))} required /></div>
            <div className="space-y-1.5"><Label htmlFor="site-name">Name</Label><Input id="site-name" type="text" value={formData.name} onChange={(event) => setFormData((current) => ({ ...current, name: event.target.value }))} required /></div>
            <div className="space-y-1.5"><Label htmlFor="site-pi">Principal Investigator</Label><Input id="site-pi" type="text" value={formData.principal_investigator} onChange={(event) => setFormData((current) => ({ ...current, principal_investigator: event.target.value }))} required /></div>
            <div className="space-y-1.5"><Label htmlFor="site-country">Country</Label><Input id="site-country" type="text" value={formData.country} onChange={(event) => setFormData((current) => ({ ...current, country: event.target.value }))} required /></div>
            <DialogFooter><Button type="button" variant="outline" onClick={() => { setShowModal(false); setError(null) }}>Cancel</Button><Button type="submit" pending={createMutation.isPending} loadingText="Creating…">Create</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
