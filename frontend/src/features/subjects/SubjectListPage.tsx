import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createColumnHelper, type PaginationState } from '@tanstack/react-table'
import { api, type PaginatedResponse } from '@/lib/api'
import { ClinicalDataTable } from './components/ClinicalDataTable'
import { StatusBadge } from './components/StatusBadge'

/** Subject as returned by GET /studies/{id}/subjects */
export interface Subject {
  id: string
  subject_number: string
  site_id: string
  site_name: string
  status: string
  created_at: string
}

interface SubjectListPageProps {
  studyId: string
}

const columnHelper = createColumnHelper<Subject>()

const columns = [
  columnHelper.accessor('subject_number', {
    header: 'Subject #',
    cell: (info) => (
      <a
        href={`/subjects/${info.row.original.id}/casebook`}
        className="text-blue-600 hover:underline font-medium"
      >
        {info.getValue()}
      </a>
    ),
  }),
  columnHelper.accessor('site_name', {
    header: 'Site',
  }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => (
      <StatusBadge domain="subject" status={info.getValue()} />
    ),
  }),
  columnHelper.accessor('created_at', {
    header: 'Created At',
    cell: (info) => {
      const date = new Date(info.getValue())
      return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    },
  }),
]

/**
 * SubjectListPage — Table view of subjects for a study.
 * Uses server-side pagination via GET /studies/{studyId}/subjects.
 */
export function SubjectListPage({ studyId }: SubjectListPageProps) {
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 10,
  })
  const [globalFilter, setGlobalFilter] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['subjects', studyId, pagination.pageIndex, pagination.pageSize, globalFilter],
    queryFn: async () => {
      const params: Record<string, string | number> = {
        page: pagination.pageIndex + 1,
        page_size: pagination.pageSize,
      }
      if (globalFilter) {
        params.search = globalFilter
      }
      const response = await api.get<PaginatedResponse<Subject>>(
        `/studies/${studyId}/subjects`,
        { params },
      )
      return response.data
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Subjects</h1>
        <div className="flex items-center gap-3">
          <input
            type="search"
            placeholder="Search subjects…"
            className="rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            aria-label="Search subjects"
          />
        </div>
      </div>

      <ClinicalDataTable
        columns={columns}
        data={data?.items ?? []}
        totalRows={data?.total}
        manualPagination
        onPaginationChange={setPagination}
        initialPageSize={pagination.pageSize}
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        isLoading={isLoading}
        emptyMessage="No subjects found for this study."
      />
    </div>
  )
}
