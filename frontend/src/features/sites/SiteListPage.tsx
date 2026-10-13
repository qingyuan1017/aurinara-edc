import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { api } from '@/lib/api'
import type { PaginatedResponse } from '@/lib/api'

interface Site {
  id: string
  site_number: string
  name: string
  principal_investigator: string
  country: string
  status: string
}

const columnHelper = createColumnHelper<Site>()

const columns = [
  columnHelper.accessor('id', { header: 'Site ID' }),
  columnHelper.accessor('name', { header: 'Name' }),
  columnHelper.accessor('principal_investigator', { header: 'PI' }),
  columnHelper.accessor('country', { header: 'Country' }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusBadge status={info.getValue()} label="Site status" />,
  }),
]

export function SiteListPage({ studyId }: { studyId: string }) {
  const [page, setPage] = useState(1)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['sites', studyId, page],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Site>>(`/studies/${studyId}/sites`, {
        params: { page, page_size: 20 },
      })
      return data
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
        description="Review Sites synchronized from CTMS. Create and manage Site identities from CTMS Entity Management."
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
    </PageContainer>
  )
}
