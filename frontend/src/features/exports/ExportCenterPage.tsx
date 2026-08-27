import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { api } from '@/lib/api'
import type { PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface Export {
  id: string
  format: string
  status: string
  filters: Record<string, string>
  created_at: string
  completed_at?: string
  file_size?: number
}

interface CreateExportPayload {
  format: string
  filters: Record<string, string>
}

const columnHelper = createColumnHelper<Export>()

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    processing: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
  }
  return colors[status] ?? 'bg-gray-100 text-gray-800'
}

export function ExportCenterPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canExport = usePermission(PERMISSIONS.DATA_EXPORT)
  const [page, setPage] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [format, setFormat] = useState('csv')
  const [siteFilter, setSiteFilter] = useState('')
  const [error, setError] = useState<string | null>(null)

  const columns = [
    columnHelper.accessor('format', {
      header: 'Format',
      cell: (info) => info.getValue().toUpperCase(),
    }),
    columnHelper.accessor('status', {
      header: 'Status',
      cell: (info) => (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusBadge(info.getValue())}`}
        >
          {info.getValue()}
        </span>
      ),
    }),
    columnHelper.accessor('created_at', {
      header: 'Requested',
      cell: (info) => new Date(info.getValue()).toLocaleString(),
    }),
    columnHelper.accessor('completed_at', {
      header: 'Completed',
      cell: (info) => {
        const val = info.getValue()
        return val ? new Date(val).toLocaleString() : '—'
      },
    }),
    columnHelper.display({
      id: 'actions',
      header: 'Download',
      cell: (info) => {
        const row = info.row.original
        if (row.status === 'completed') {
          return (
            <button
              onClick={() => handleDownload(row.id)}
              className="text-blue-600 hover:text-blue-800 text-sm font-medium"
            >
              Download
            </button>
          )
        }
        return <span className="text-gray-400 text-sm">—</span>
      },
    }),
  ]

  const { data, isLoading } = useQuery({
    queryKey: ['exports', studyId, page],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Export>>(`/studies/${studyId}/exports`, {
        params: { page, page_size: 20 },
      })
      return data
    },
  })

  const createMutation = useMutation({
    mutationFn: async (payload: CreateExportPayload) => {
      const { data } = await api.post(`/studies/${studyId}/exports`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exports', studyId] })
      setShowModal(false)
      setFormat('csv')
      setSiteFilter('')
      setError(null)
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to create export')
    },
  })

  const handleDownload = async (exportId: string) => {
    try {
      const { data } = await api.get<{ download_url: string }>(
        `/exports/${exportId}/download`,
      )
      window.open(data.download_url, '_blank')
    } catch {
      // Silently handle — user will see no download occurs
    }
  }

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Export Center</h1>
        {canExport && (
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition"
          >
            Create Export
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-gray-500">Loading…</p>
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
                        className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
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
                      <td key={cell.id} className="px-4 py-3 text-sm text-gray-900">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
                {(data?.items.length ?? 0) === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                      No exports yet. Create one to get started.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-600">
                Page {page} of {totalPages} ({data?.total ?? 0} total)
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

      {/* Create Export Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Create Export</h2>
            {error && (
              <p className="text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                const filters: Record<string, string> = {}
                if (siteFilter) filters.site_id = siteFilter
                createMutation.mutate({ format, filters })
              }}
              className="space-y-3"
            >
              <div>
                <label htmlFor="export-format" className="block text-sm font-medium text-gray-700">
                  Format
                </label>
                <select
                  id="export-format"
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                  className="mt-1 w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="csv">CSV</option>
                  <option value="sas">SAS</option>
                  <option value="json">JSON</option>
                  <option value="odm_xml">ODM XML</option>
                </select>
              </div>
              <div>
                <label htmlFor="export-site" className="block text-sm font-medium text-gray-700">
                  Site Filter (optional)
                </label>
                <input
                  id="export-site"
                  type="text"
                  value={siteFilter}
                  onChange={(e) => setSiteFilter(e.target.value)}
                  placeholder="Site ID (leave blank for all)"
                  className="mt-1 w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="flex justify-end space-x-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowModal(false)
                    setError(null)
                  }}
                  className="px-4 py-2 text-sm border rounded-md hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Creating…' : 'Start Export'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
