import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { api } from '@/lib/api'
import type { PaginatedResponse } from '@/lib/api'

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
  columnHelper.accessor('timestamp', {
    header: 'Timestamp',
    cell: (info) => new Date(info.getValue()).toLocaleString(),
  }),
  columnHelper.accessor('actor_email', { header: 'Actor' }),
  columnHelper.accessor('action', {
    header: 'Action',
    cell: (info) => (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('entity_type', { header: 'Entity Type' }),
  columnHelper.accessor('entity_id', {
    header: 'Entity ID',
    cell: (info) => (
      <span className="font-mono text-xs">{info.getValue().slice(0, 8)}…</span>
    ),
  }),
  columnHelper.accessor('field', {
    header: 'Field',
    cell: (info) => info.getValue() ?? '—',
  }),
  columnHelper.accessor('old_value', {
    header: 'Old',
    cell: (info) => {
      const val = info.getValue()
      return val ? <span className="text-red-600 text-xs">{val}</span> : '—'
    },
  }),
  columnHelper.accessor('new_value', {
    header: 'New',
    cell: (info) => {
      const val = info.getValue()
      return val ? <span className="text-green-600 text-xs">{val}</span> : '—'
    },
  }),
]

export function AuditViewerPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [entityType, setEntityType] = useState('')
  const [action, setAction] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  // Build query params
  const params: Record<string, string | number> = { page, page_size: 50 }
  if (search) params.search = search
  if (entityType) params.entity_type = entityType
  if (action) params.action = action
  if (startDate) params.start_date = startDate
  if (endDate) params.end_date = endDate

  const { data, isLoading } = useQuery({
    queryKey: ['audit-events', params],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<AuditEvent>>('/audit-events', { params })
      return data
    },
  })

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-gray-900">Audit Trail</h1>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 bg-gray-50 p-4 rounded-lg border">
        <div className="flex-1 min-w-[200px]">
          <label htmlFor="audit-search" className="block text-xs font-medium text-gray-600 mb-1">
            Search
          </label>
          <input
            id="audit-search"
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            placeholder="Actor email, entity ID…"
            className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label
            htmlFor="audit-entity-type"
            className="block text-xs font-medium text-gray-600 mb-1"
          >
            Entity Type
          </label>
          <select
            id="audit-entity-type"
            value={entityType}
            onChange={(e) => {
              setEntityType(e.target.value)
              setPage(1)
            }}
            className="px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="study">Study</option>
            <option value="site">Site</option>
            <option value="subject">Subject</option>
            <option value="form">Form</option>
            <option value="field_data">Field Data</option>
            <option value="query">Query</option>
            <option value="user">User</option>
            <option value="role">Role</option>
            <option value="export">Export</option>
          </select>
        </div>
        <div>
          <label htmlFor="audit-action" className="block text-xs font-medium text-gray-600 mb-1">
            Action
          </label>
          <select
            id="audit-action"
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setPage(1)
            }}
            className="px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="create">Create</option>
            <option value="update">Update</option>
            <option value="delete">Delete</option>
            <option value="login">Login</option>
            <option value="logout">Logout</option>
            <option value="status_change">Status Change</option>
          </select>
        </div>
        <div>
          <label htmlFor="audit-start" className="block text-xs font-medium text-gray-600 mb-1">
            From
          </label>
          <input
            id="audit-start"
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value)
              setPage(1)
            }}
            className="px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label htmlFor="audit-end" className="block text-xs font-medium text-gray-600 mb-1">
            To
          </label>
          <input
            id="audit-end"
            type="date"
            value={endDate}
            onChange={(e) => {
              setEndDate(e.target.value)
              setPage(1)
            }}
            className="px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <button
          onClick={() => {
            setSearch('')
            setEntityType('')
            setAction('')
            setStartDate('')
            setEndDate('')
            setPage(1)
          }}
          className="px-3 py-2 text-sm border rounded-md hover:bg-white"
        >
          Clear
        </button>
      </div>

      {/* Table */}
      {isLoading ? (
        <p className="text-gray-500">Loading audit events…</p>
      ) : (
        <>
          <div className="overflow-x-auto border rounded-lg">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 text-sm text-gray-900 whitespace-nowrap">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
                {(data?.items.length ?? 0) === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">
                      No audit events match your filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-600">
                Page {page} of {totalPages} ({data?.total ?? 0} events)
              </p>
              <div className="space-x-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="px-3 py-1 text-sm border rounded disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-3 py-1 text-sm border rounded disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
