import { useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
  type PaginationState,
} from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export interface ClinicalDataTableProps<TData> {
  // TanStack's column definitions use an invariant cell-value type; the table renders heterogeneous columns.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<TData, any>[]
  data: TData[]
  totalRows?: number
  pageSizeOptions?: number[]
  manualPagination?: boolean
  onPaginationChange?: (pagination: PaginationState) => void
  initialPageSize?: number
  globalFilter?: string
  onGlobalFilterChange?: (value: string) => void
  className?: string
  isLoading?: boolean
  emptyMessage?: string
}

/** Reusable TanStack table wrapper for clinical listings and server-side pagination. */
export function ClinicalDataTable<TData>({
  columns,
  data,
  totalRows,
  pageSizeOptions = [10, 25, 50],
  manualPagination = false,
  onPaginationChange,
  initialPageSize = 10,
  globalFilter,
  onGlobalFilterChange,
  className,
  isLoading = false,
  emptyMessage = 'No data available.',
}: ClinicalDataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: initialPageSize })
  const pageCount = manualPagination && totalRows != null ? Math.ceil(totalRows / pagination.pageSize) : undefined

  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters, pagination, globalFilter },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onPaginationChange: (updater) => {
      const next = typeof updater === 'function' ? updater(pagination) : updater
      setPagination(next)
      onPaginationChange?.(next)
    },
    onGlobalFilterChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination,
    pageCount,
  })

  return (
    <div className={className ?? 'space-y-4'}>
      <Table>
        <caption className="sr-only">Clinical data</caption>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  className={header.column.getCanSort() ? 'cursor-pointer select-none hover:bg-muted' : undefined}
                  onClick={header.column.getToggleSortingHandler()}
                  aria-sort={header.column.getIsSorted() === 'asc' ? 'ascending' : header.column.getIsSorted() === 'desc' ? 'descending' : 'none'}
                >
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  {header.column.getIsSorted() === 'asc' && ' ↑'}
                  {header.column.getIsSorted() === 'desc' && ' ↓'}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {isLoading ? <TableRow><TableCell colSpan={columns.length} className="py-8 text-center text-muted-foreground">Loading…</TableCell></TableRow> : null}
          {!isLoading && table.getRowModel().rows.length === 0 ? <TableRow><TableCell colSpan={columns.length} className="py-8 text-center text-muted-foreground">{emptyMessage}</TableCell></TableRow> : null}
          {!isLoading ? table.getRowModel().rows.map((row) => <TableRow key={row.id}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>) : null}
        </TableBody>
      </Table>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>Rows per page:</span>
          <Select value={String(pagination.pageSize)} onValueChange={(value) => table.setPageSize(Number(value))}>
            <SelectTrigger aria-label="Rows per page" className="h-9 w-20"><SelectValue /></SelectTrigger>
            <SelectContent>{pageSizeOptions.map((size) => <SelectItem key={size} value={String(size)}>{size}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount() || 1}</span>
          <Button type="button" variant="outline" size="sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()} aria-label="Previous page">Previous</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()} aria-label="Next page">Next</Button>
        </div>
      </div>
    </div>
  )
}
