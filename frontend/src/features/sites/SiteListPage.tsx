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
    cell: (info) => (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
        {info.getValue()}
      </span>
    ),
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

  const { data, isLoading } = useQuery({
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

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Sites</h1>
        {canManage && (
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition"
          >
            Create Site
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

      {/* Create Site Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Create Site</h2>
            {error && (
              <p className="text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                createMutation.mutate(formData)
              }}
              className="space-y-3"
            >
              <div>
                <label htmlFor="site-number" className="block text-sm font-medium text-gray-700">
                  Site Number
                </label>
                <input
                  id="site-number"
                  type="text"
                  value={formData.site_number}
                  onChange={(e) => setFormData((d) => ({ ...d, site_number: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              <div>
                <label htmlFor="site-name" className="block text-sm font-medium text-gray-700">
                  Name
                </label>
                <input
                  id="site-name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData((d) => ({ ...d, name: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              <div>
                <label htmlFor="site-pi" className="block text-sm font-medium text-gray-700">
                  Principal Investigator
                </label>
                <input
                  id="site-pi"
                  type="text"
                  value={formData.principal_investigator}
                  onChange={(e) =>
                    setFormData((d) => ({ ...d, principal_investigator: e.target.value }))
                  }
                  className="mt-1 w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              <div>
                <label htmlFor="site-country" className="block text-sm font-medium text-gray-700">
                  Country
                </label>
                <input
                  id="site-country"
                  type="text"
                  value={formData.country}
                  onChange={(e) => setFormData((d) => ({ ...d, country: e.target.value }))}
                  className="mt-1 w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
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
                  {createMutation.isPending ? 'Creating…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
