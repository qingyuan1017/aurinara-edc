import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, type PaginationState } from '@tanstack/react-table'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { Label } from '@/components/ui/label'
import { api, type PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useStudyContext } from '@/lib/study-context'
import { ClinicalDataTable } from './components/ClinicalDataTable'

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
      <a href={`/subjects/${info.row.original.id}/casebook`} className="font-medium text-primary hover:underline">
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
    cell: (info) => <StatusBadge status={info.getValue()} label="Subject status" />,
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

  const { data, isLoading, isError, refetch } = useQuery({
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
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['subjects', studyId] }); setShowCreate(false); setSubjectNumber(''); setCreateError('') },
    onError: () => setCreateError('Select a site first, then try again.'),
  })

  const hasRows = Boolean(data && data.items.length > 0)

  return (
    <PageContainer wide>
      <PageHeader
        title="Subjects"
        description="Review clinical subjects for the selected study without changing server-owned status or totals."
        actions={canCreate ? <Button type="button" onClick={() => setShowCreate(true)}>Add subject</Button> : null}
      />

      <PageToolbar label="Subject list controls">
        <Input
          type="search"
          placeholder="Search subjects…"
          value={globalFilter}
          onChange={(event) => setGlobalFilter(event.target.value)}
          aria-label="Search subjects"
          className="max-w-sm"
        />
        <span className="text-sm text-muted-foreground">
          {data ? `${data.total} total subjects · server ordered` : `Subjects for study ${studyId}`}
        </span>
      </PageToolbar>

      <DataTableShell
        label="Subjects"
        loading={isLoading}
        error={isError}
        errorMessage="Failed to load subjects."
        onRetry={() => void refetch()}
        empty={!isLoading && !isError && Boolean(data) && !hasRows}
        emptyTitle="No subjects found."
        emptyDescription={globalFilter ? 'Try changing the subject search.' : 'No subjects are available for the selected study.'}
      >
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
      </DataTableShell>

      <Dialog open={showCreate} onOpenChange={(open) => { setShowCreate(open); if (!open) setCreateError('') }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add subject</DialogTitle><DialogDescription>Create a clinical subject for the selected site.</DialogDescription></DialogHeader>
          <p className="text-sm text-muted-foreground">Site: {selectedSiteId ?? 'not selected'}</p>
          {createError ? <Alert variant="destructive"><AlertDescription>{createError}</AlertDescription></Alert> : null}
          <form onSubmit={(event) => { event.preventDefault(); createSubject.mutate() }} className="space-y-4">
            <Label htmlFor="subject-number">Subject number (optional)</Label>
            <Input id="subject-number" placeholder="Subject number (optional)" value={subjectNumber} onChange={(event) => setSubjectNumber(event.target.value)} />
            <DialogFooter><Button type="button" variant="outline" onClick={() => { setShowCreate(false); setCreateError('') }}>Cancel</Button><Button type="submit" pending={createSubject.isPending} loadingText="Creating…" disabled={!selectedSiteId}>Create</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
