import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, type PaginationState } from '@tanstack/react-table'
import { api, type PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useStudyContext } from '@/lib/study-context'
import { ClinicalDataTable } from './components/ClinicalDataTable'
import { StatusBadge } from './components/StatusBadge'

/** Subject as returned by GET /studies/{id}/subjects */
export interface Subject {
  id: string
  subject_number: string
  site_id: string
  site_name?: string
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
    cell: (info) => info.getValue() ?? info.row.original.site_id,
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
  const queryClient = useQueryClient()
  const canCreate = usePermission(PERMISSIONS.SUBJECT_CREATE)
  const selectedSiteId = useStudyContext((state) => state.selectedSiteId)
  const [showCreate, setShowCreate] = useState(false)
  const [subjectNumber, setSubjectNumber] = useState('')
  const [createError, setCreateError] = useState('')
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

  const createSubject = useMutation({
    mutationFn: () => api.post(`/studies/${studyId}/subjects`, { site_id: selectedSiteId, subject_number: subjectNumber || null }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['subjects', studyId] }); setShowCreate(false); setSubjectNumber('') },
    onError: () => setCreateError('Select a site first, then try again.'),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Subjects</h1>
        <div className="flex items-center gap-3">
          {canCreate && <button onClick={() => setShowCreate(true)} className="rounded-md bg-blue-600 px-3 py-2 text-sm text-white">Add subject</button>}
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

      {showCreate && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"><form onSubmit={(e) => { e.preventDefault(); createSubject.mutate() }} className="w-full max-w-md space-y-4 rounded-lg bg-white p-6"><h2 className="text-lg font-semibold">Add subject</h2><p className="text-sm text-gray-500">Site: {selectedSiteId ?? 'not selected'}</p>{createError && <p className="rounded bg-red-50 p-2 text-sm text-red-700">{createError}</p>}<input placeholder="Subject number (optional)" value={subjectNumber} onChange={(e) => setSubjectNumber(e.target.value)} className="w-full rounded border px-3 py-2 text-sm" /><div className="flex justify-end gap-2"><button type="button" onClick={() => setShowCreate(false)} className="rounded border px-3 py-2 text-sm">Cancel</button><button disabled={!selectedSiteId || createSubject.isPending} className="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">Create</button></div></form></div>}

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
