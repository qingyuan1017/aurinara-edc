import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { useListStudiesApiV1StudiesGet } from '@/api/endpoints/studies/studies'
import type { StudyResponse } from '@/api/model'

const columnHelper = createColumnHelper<StudyResponse>()

const columns = [
  columnHelper.accessor('study_code', {
    header: 'Code',
    cell: (info) => <Link to="/studies/$studyId" params={{ studyId: info.row.original.id }} className="font-medium text-primary hover:underline">{info.getValue()}</Link>,
  }),
  columnHelper.accessor('title', { header: 'Title' }),
  columnHelper.accessor('sponsor', {
    header: 'Sponsor',
    cell: (info) => info.getValue() ?? '—',
  }),
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
  const [page, setPage] = useState(1)

  const { data, isLoading, isError, refetch } = useListStudiesApiV1StudiesGet({
    page,
    page_size: 20,
  }, {
    query: { refetchInterval: 30_000, refetchIntervalInBackground: false },
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
        description="Studies are created in Aurinara Platform. Name and sponsor are synchronized here as read-only canonical information."
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
    </PageContainer>
  )
}
