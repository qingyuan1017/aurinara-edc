import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { api, type PaginatedResponse } from '@/lib/api'
import { DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

interface AuditEvent {
  id: string
  actor_email: string
  action: string
  entity_type: string
  entity_id: string
  field?: string
  old_value?: string
  new_value?: string
  reason?: string
  timestamp: string
  request_id: string
}

const columnHelper = createColumnHelper<AuditEvent>()
const columns = [
  columnHelper.accessor('timestamp', { header: 'Timestamp', cell: (info) => new Date(info.getValue()).toLocaleString() }),
  columnHelper.accessor('actor_email', { header: 'Actor' }),
  columnHelper.accessor('action', { header: 'Action', cell: (info) => <StatusBadge status={info.getValue()} label="Audit action" /> }),
  columnHelper.accessor('entity_type', { header: 'Entity Type' }),
  columnHelper.accessor('entity_id', { header: 'Entity ID', cell: (info) => <span className="font-mono text-xs">{info.getValue().slice(0, 8)}…</span> }),
  columnHelper.accessor('field', { header: 'Field', cell: (info) => info.getValue() ?? '—' }),
  columnHelper.accessor('old_value', { header: 'Old', cell: (info) => { const value = info.getValue(); return value ? <span className="text-xs text-destructive">{value}</span> : '—' } }),
  columnHelper.accessor('new_value', { header: 'New', cell: (info) => { const value = info.getValue(); return value ? <span className="text-xs text-success">{value}</span> : '—' } }),
]

const entityTypes = ['study', 'site', 'subject', 'form', 'field_data', 'query', 'user', 'role', 'export']
const actions = ['create', 'update', 'delete', 'login', 'logout', 'status_change']

export function AuditViewerPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [entityType, setEntityType] = useState('')
  const [action, setAction] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  const params: Record<string, string | number> = { page, page_size: 50 }
  if (search) params.search = search
  if (entityType) params.entity_type = entityType
  if (action) params.action = action
  if (startDate) params.start_date = startDate
  if (endDate) params.end_date = endDate

  const { data, isLoading, error } = useQuery({
    queryKey: ['audit-events', params],
    queryFn: async () => {
      const response = await api.get<PaginatedResponse<AuditEvent>>('/audit-events', { params })
      return response.data
    },
  })

  const table = useReactTable({ data: data?.items ?? [], columns, getCoreRowModel: getCoreRowModel() })
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0
  const clearFilters = () => { setSearch(''); setEntityType(''); setAction(''); setStartDate(''); setEndDate(''); setPage(1) }

  return (
    <PageContainer wide>
      <PageHeader title="Audit Trail" description="Review immutable activity recorded by the EDC audit service." />

      <PageToolbar label="Audit filters" actions={<Button type="button" variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>}>
        <div className="min-w-[200px] flex-1 space-y-1">
          <Label htmlFor="audit-search">Search</Label>
          <Input id="audit-search" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} placeholder="Actor email, entity ID…" />
        </div>
        <div className="min-w-[150px] space-y-1">
          <Label htmlFor="audit-entity-type">Entity type</Label>
          <Select value={entityType || 'all'} onValueChange={(value) => { setEntityType(value === 'all' ? '' : value); setPage(1) }}>
            <SelectTrigger id="audit-entity-type" aria-label="Entity type"><SelectValue placeholder="All" /></SelectTrigger>
            <SelectContent><SelectItem value="all">All</SelectItem>{entityTypes.map((type) => <SelectItem key={type} value={type}>{type.replace('_', ' ')}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="min-w-[140px] space-y-1">
          <Label htmlFor="audit-action">Action</Label>
          <Select value={action || 'all'} onValueChange={(value) => { setAction(value === 'all' ? '' : value); setPage(1) }}>
            <SelectTrigger id="audit-action" aria-label="Action"><SelectValue placeholder="All" /></SelectTrigger>
            <SelectContent><SelectItem value="all">All</SelectItem>{actions.map((value) => <SelectItem key={value} value={value}>{value.replace('_', ' ')}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1"><Label htmlFor="audit-start">From</Label><Input id="audit-start" type="date" value={startDate} onChange={(event) => { setStartDate(event.target.value); setPage(1) }} /></div>
        <div className="space-y-1"><Label htmlFor="audit-end">To</Label><Input id="audit-end" type="date" value={endDate} onChange={(event) => { setEndDate(event.target.value); setPage(1) }} /></div>
      </PageToolbar>

      <DataTableShell label="Audit events" loading={isLoading} error={Boolean(error)} errorMessage="Audit events could not be loaded." empty={data?.items.length === 0} emptyTitle="No audit events match your filters.">
        <Table>
          <caption className="sr-only">Audit events</caption>
          <TableHeader>{table.getHeaderGroups().map((headerGroup) => <TableRow key={headerGroup.id}>{headerGroup.headers.map((header) => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}</TableRow>)}</TableHeader>
          <TableBody>{table.getRowModel().rows.map((row) => <TableRow key={row.id}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id} className="whitespace-nowrap">{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}</TableRow>)}</TableBody>
        </Table>
      </DataTableShell>

      {totalPages > 1 ? <div className="flex flex-wrap items-center justify-between gap-3 pt-4"><p className="text-sm text-muted-foreground">Page {page} of {totalPages} ({data?.total ?? 0} events)</p><div className="flex gap-2"><Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</Button><Button type="button" variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>Next</Button></div></div> : null}
    </PageContainer>
  )
}
