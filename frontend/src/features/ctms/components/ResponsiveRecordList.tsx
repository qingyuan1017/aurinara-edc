/* eslint-disable react-refresh/only-export-components */
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { StatusPresentation, type StatusKind } from './OwnershipPresentation'

export interface ResponsiveRecordColumn<T extends object> {
  key: string
  label: string
  render?: (row: T) => ReactNode
  status?: boolean
  statusKind?: StatusKind
  date?: boolean
  className?: string
}

export interface ResponsiveRecordFilter {
  label: string
  value: string | number | boolean
}

export interface ResponsiveRecordPagination {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  isLoading?: boolean
}

export interface ResponsiveRecordListProps<T extends object> {
  label: string
  rows: readonly T[]
  columns: readonly ResponsiveRecordColumn<T>[]
  emptyLabel: string
  rowKey?: (row: T, index: number) => string
  renderActions?: (row: T) => ReactNode
  filters?: readonly ResponsiveRecordFilter[]
  pagination?: ResponsiveRecordPagination
  statusOwner?: string
  emptyActionHref?: string
  emptyActionLabel?: string
}

function formatDate(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString()
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function getValue<T extends object>(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function renderCell<T extends object>(
  row: T,
  column: ResponsiveRecordColumn<T>,
  statusOwner: string,
): ReactNode {
  if (column.render) return column.render(row)
  const value = getValue(row, column.key)
  if (column.status) {
    return (
      <StatusPresentation
        kind={column.statusKind ?? 'operational'}
        status={formatValue(value)}
        owner={statusOwner}
        readOnly={statusOwner !== 'CTMS'}
      />
    )
  }
  return column.date ? formatDate(value) : formatValue(value)
}

function Pagination({ pagination, label }: { pagination: ResponsiveRecordPagination; label: string }) {
  const totalPages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize))
  if (pagination.total <= pagination.pageSize && pagination.page <= 1) return null

  const goToPage = (page: number) => {
    pagination.onPageChange(Math.min(totalPages, Math.max(1, page)))
  }

  return (
    <nav aria-label={`${label} pagination`} className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/30 px-3 py-3 sm:px-4">
      <p className="text-sm text-muted-foreground" aria-live="polite">
        Page {pagination.page} of {totalPages} ({pagination.total} total)
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => goToPage(pagination.page - 1)}
          disabled={pagination.page <= 1 || pagination.isLoading}
          aria-label={`Previous ${label} page`}
        >
          Previous
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => goToPage(pagination.page + 1)}
          disabled={pagination.page >= totalPages || pagination.isLoading}
          aria-label={`Next ${label} page`}
        >
          Next
        </Button>
      </div>
    </nav>
  )
}

export function ResponsiveRecordList<T extends object>({
  label,
  rows,
  columns,
  emptyLabel,
  rowKey = (_row, index) => String(index),
  renderActions,
  filters = [],
  pagination,
  statusOwner = 'CTMS',
  emptyActionHref,
  emptyActionLabel,
}: ResponsiveRecordListProps<T>) {
  const activeFilterSummary = filters.length > 0 && (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-info/30 bg-info/10 p-3 text-sm text-foreground" role="status" aria-label="Active filters">
      <span className="font-semibold">Active filters:</span>
      {filters.map((filter) => (
        <span key={`${filter.label}-${String(filter.value)}`} className="rounded-full border border-border bg-background px-2 py-0.5">
          {filter.label}: {String(filter.value)}
        </span>
      ))}
    </div>
  )

  if (!rows.length) {
    return <section className="space-y-3" aria-label={label}>
      {activeFilterSummary}
      <div className="rounded-md border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground" role="status">
        <p>{filters.length > 0 ? `No ${emptyLabel.toLowerCase()} match the active filters.` : `${emptyLabel} has no records configured yet.`}</p>
        {emptyActionHref && emptyActionLabel && <Button asChild variant="outline" size="sm" className="mt-2"><a href={emptyActionHref}>{emptyActionLabel}</a></Button>}
      </div>
    </section>
  }

  return (
    <section className="space-y-3" aria-label={label} data-testid="responsive-record-list">
      {activeFilterSummary}

      <div className="overflow-x-auto rounded-md border" tabIndex={0} aria-label={`Scrollable ${label} table`}>
        <Table>
          <TableCaption className="sr-only">{label}</TableCaption>
          <TableHeader className="bg-muted/30">
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.key} scope="col" className={cn('whitespace-nowrap font-semibold', column.className)}>
                  {column.label}
                </TableHead>
              ))}
              {renderActions && <TableHead scope="col" className="font-semibold">Actions</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow key={rowKey(row, index)} className="align-top focus-within:bg-muted/50">
                {columns.map((column) => (
                  <TableCell key={column.key} className={cn('max-w-xs text-foreground', column.className)}>
                    {renderCell(row, column, statusOwner)}
                  </TableCell>
                ))}
                {renderActions && <TableCell>{renderActions(row)}</TableCell>}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="grid gap-3 md:hidden" role="list" aria-label={`${label} cards`}>
        {rows.map((row, index) => (
          <article key={`card-${rowKey(row, index)}`} className="rounded-md border bg-card p-3" role="listitem">
            <dl className="grid gap-2">
              {columns.map((column) => (
                <div key={column.key}>
                  <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{column.label}</dt>
                  <dd className="mt-1 text-sm text-foreground">{renderCell(row, column, statusOwner)}</dd>
                </div>
              ))}
            </dl>
            {renderActions ? <div className="mt-3 border-t pt-3">{renderActions(row)}</div> : null}
          </article>
        ))}
      </div>

      {pagination && <Pagination pagination={pagination} label={label} />}
    </section>
  )
}

export { formatDate, formatValue }
