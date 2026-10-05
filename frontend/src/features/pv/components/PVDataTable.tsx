import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { DataTableShell } from '@/components/patterns'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export interface PVDataTableProps<T> {
  label: string
  columns: ColumnDef<T, unknown>[]
  data: T[]
  isLoading?: boolean
  isFetching?: boolean
  error?: unknown
  onRetry?: () => void
  errorMessage?: React.ReactNode
  emptyTitle?: string
  emptyDescription?: React.ReactNode
  emptyAction?: React.ReactNode
}

/**
 * High-density PV listing built on TanStack Table with the shared
 * DataTableShell for loading/empty/error/refreshing states. The server is
 * authoritative for the rows; totals and status text are rendered verbatim.
 */
export function PVDataTable<T>({
  label,
  columns,
  data,
  isLoading = false,
  isFetching = false,
  error,
  onRetry,
  errorMessage,
  emptyTitle,
  emptyDescription,
  emptyAction,
}: PVDataTableProps<T>) {
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel() })

  const state = isLoading
    ? 'loading'
    : error
      ? 'error'
      : data.length === 0
        ? 'empty'
        : isFetching
          ? 'refreshing'
          : undefined

  return (
    <DataTableShell
      label={label}
      state={state}
      errorMessage={errorMessage}
      onRetry={onRetry}
      emptyTitle={emptyTitle ?? label}
      emptyDescription={emptyDescription}
      emptyAction={emptyAction}
    >
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </DataTableShell>
  )
}
