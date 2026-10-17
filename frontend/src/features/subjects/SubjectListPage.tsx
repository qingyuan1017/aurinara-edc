import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { createColumnHelper, type PaginationState } from '@tanstack/react-table'
import { ChevronDown } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button, buttonVariants } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { ConfirmDialog, DataTableShell, PageContainer, PageHeader, PageToolbar, StatusBadge } from '@/components/patterns'
import { Label } from '@/components/ui/label'
import { api, getApiErrorMessage, type PaginatedResponse } from '@/lib/api'
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
  current_phase_name?: string | null
  current_phase_type?: string | null
  created_at: string
  deleted_at?: string | null
  deletion_reason?: string | null
  forms_total?: number
  forms_submitted?: number
  completion_percent?: number
  active_query_count?: number
  review_summary?: string
  sdv_summary?: string
  sdr_summary?: string
}

interface SiteOption {
  id: string
  site_number: string
  name: string
  status?: string
}

interface SubjectEnrollmentReadiness {
  study_id: string
  ready: boolean
  published_version_id?: string | null
  published_version_number?: string | null
  authorized_active_site_count: number
  blockers: Array<{ code: string; message: string }>
}

interface SubjectListPageProps {
  studyId: string
}

const columnHelper = createColumnHelper<Subject>()

type SubjectLifecycleAction = {
  kind: 'delete' | 'restore' | 'switch-site' | 'inactive' | 'discontinue'
  subject: Subject
}

const INACTIVE_ELIGIBLE_STATUSES = new Set(['Screening', 'Enrolled', 'Randomized', 'On Treatment'])
const DISCONTINUE_ELIGIBLE_STATUSES = new Set([...INACTIVE_ELIGIBLE_STATUSES, 'Inactive'])

function createColumns(
  studyId: string,
  canDelete: boolean,
  canRestore: boolean,
  canTransfer: boolean,
  canUpdate: boolean,
  onLifecycleAction: (action: SubjectLifecycleAction) => void,
) { return [
  columnHelper.accessor('subject_number', {
    header: 'Subject #',
    cell: (info) => info.row.original.deleted_at ? (
      <span className="font-medium">{info.getValue()}</span>
    ) : (
      <Link to="/studies/$studyId/edc/subjects/$subjectId" params={{ studyId, subjectId: info.row.original.id }} className="font-medium text-primary hover:underline">
        {info.getValue()}
      </Link>
    ),
  }),
  columnHelper.accessor('site_name', {
    header: 'Site',
    cell: (info) => info.getValue() ?? info.row.original.site_id,
  }),
  columnHelper.accessor('status', {
    id: 'status',
    header: 'Status / phase',
    cell: (info) => (
      <div className="space-y-1">
        <StatusBadge status={info.row.original.deleted_at ? 'Removed' : info.getValue()} label="Subject status" />
        {!info.row.original.deleted_at && info.row.original.current_phase_name ? (
          <p className="text-xs text-muted-foreground">Phase: {info.row.original.current_phase_name}</p>
        ) : null}
      </div>
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
  columnHelper.accessor('completion_percent', {
    header: 'Forms',
    cell: (info) => `${info.getValue() ?? 0}% (${info.row.original.forms_submitted ?? 0}/${info.row.original.forms_total ?? 0})`,
  }),
  columnHelper.accessor('active_query_count', {
    header: 'Queries',
    cell: (info) => info.getValue() ?? 0,
  }),
  columnHelper.display({
    id: 'quality',
    header: 'Quality',
    cell: (info) => <div className="flex flex-wrap gap-1"><StatusBadge status={info.row.original.review_summary ?? 'Not Applicable'} label="Review" /><StatusBadge status={info.row.original.sdv_summary ?? 'Not Applicable'} label="SDV" /><StatusBadge status={info.row.original.sdr_summary ?? 'Not Applicable'} label="SDR" /></div>,
  }),
  columnHelper.display({
    id: 'actions',
    header: 'Actions',
    cell: (info) => {
      const subject = info.row.original
      const isScreening = subject.status === 'Screening'
      const canMarkInactive = !subject.deleted_at && canUpdate && INACTIVE_ELIGIBLE_STATUSES.has(subject.status)
      const canDiscontinue = !subject.deleted_at && canUpdate && DISCONTINUE_ELIGIBLE_STATUSES.has(subject.status)
      const hasActions = subject.deleted_at
        ? canRestore
        : canMarkInactive || canDiscontinue || (isScreening && (canDelete || canTransfer))

      if (!hasActions) return <span className="text-xs text-muted-foreground">No actions</span>

      return (
        <div className="relative inline-block">
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label={`Open actions for ${subject.subject_number}`}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              Actions
              <ChevronDown className="size-4" aria-hidden="true" />
            </DropdownMenuTrigger>
            <DropdownMenuContent className="right-0 mt-1 min-w-48">
              {subject.deleted_at ? (
                <DropdownMenuItem onClick={() => onLifecycleAction({ kind: 'restore', subject })}>
                  Restore subject
                </DropdownMenuItem>
              ) : (
                <>
                  {canMarkInactive ? (
                    <DropdownMenuItem onClick={() => onLifecycleAction({ kind: 'inactive', subject })}>
                      Mark inactive
                    </DropdownMenuItem>
                  ) : null}
                  {canDiscontinue ? (
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onClick={() => onLifecycleAction({ kind: 'discontinue', subject })}
                    >
                      Discontinue
                    </DropdownMenuItem>
                  ) : null}
                  {isScreening && canTransfer ? (
                    <DropdownMenuItem onClick={() => onLifecycleAction({ kind: 'switch-site', subject })}>
                      Switch site
                    </DropdownMenuItem>
                  ) : null}
                  {isScreening && canDelete ? (
                    <>
                      {canMarkInactive || canDiscontinue || canTransfer ? <DropdownMenuSeparator /> : null}
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={() => onLifecycleAction({ kind: 'delete', subject })}
                      >
                        Remove entered in error
                      </DropdownMenuItem>
                    </>
                  ) : null}
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )
    },
  }),
] }

/**
 * SubjectListPage — Table view of subjects for a study.
 * Uses server-side pagination via GET /studies/{studyId}/subjects.
 */
export function SubjectListPage({ studyId }: SubjectListPageProps) {
  const queryClient = useQueryClient()
  const canCreate = usePermission(PERMISSIONS.SUBJECT_CREATE)
  const canDelete = usePermission(PERMISSIONS.SUBJECT_DELETE, studyId)
  const canRestore = usePermission(PERMISSIONS.SUBJECT_RESTORE, studyId)
  const canTransfer = usePermission(PERMISSIONS.SUBJECT_TRANSFER, studyId)
  const canUpdate = usePermission(PERMISSIONS.SUBJECT_UPDATE, studyId)
  const selectedSiteId = useStudyContext((state) => state.selectedSiteId)
  const [showCreate, setShowCreate] = useState(false)
  const [createSiteId, setCreateSiteId] = useState('')
  const [subjectNumber, setSubjectNumber] = useState('')
  const [createError, setCreateError] = useState('')
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 10,
  })
  const [globalFilter, setGlobalFilter] = useState('')
  const [qualityState, setQualityState] = useState('all')
  const [includeRemoved, setIncludeRemoved] = useState(false)
  const [lifecycleAction, setLifecycleAction] = useState<SubjectLifecycleAction | null>(null)
  const [subjectNumberConfirmation, setSubjectNumberConfirmation] = useState('')
  const [transferSiteId, setTransferSiteId] = useState('')
  const [lifecycleError, setLifecycleError] = useState('')

  const sites = useQuery({
    queryKey: ['subject-create-sites', studyId],
    enabled: canCreate || canTransfer,
    queryFn: async () => (await api.get<PaginatedResponse<SiteOption>>(
      `/studies/${studyId}/sites`,
      { params: { page: 1, page_size: 100 } },
    )).data,
  })
  const activeSites = (sites.data?.items ?? []).filter((site) => site.status?.toLowerCase() !== 'inactive')

  const enrollmentReadiness = useQuery({
    queryKey: ['subject-enrollment-readiness', studyId],
    enabled: canCreate,
    queryFn: async () => (await api.get<SubjectEnrollmentReadiness>(
      `/studies/${studyId}/subjects/enrollment-readiness`,
    )).data,
  })
  const enrollmentBlockers = enrollmentReadiness.data?.blockers ?? []
  const enrollmentIsReady = enrollmentReadiness.data?.ready === true

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['subjects', studyId, pagination.pageIndex, pagination.pageSize, globalFilter, qualityState, includeRemoved],
    queryFn: async () => {
      const params: Record<string, string | number> = {
        page: pagination.pageIndex + 1,
        page_size: pagination.pageSize,
      }
      if (globalFilter) {
        params.search = globalFilter
      }
      if (qualityState !== 'all') params.quality_state = qualityState
      if (includeRemoved) params.include_deleted = 'true'
      const response = await api.get<PaginatedResponse<Subject>>(
        `/studies/${studyId}/subjects`,
        { params },
      )
      return response.data
    },
  })

  const createSubject = useMutation({
    mutationFn: () => api.post(`/studies/${studyId}/subjects`, { site_id: createSiteId, subject_number: subjectNumber || null }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['subjects', studyId] }); setShowCreate(false); setCreateSiteId(''); setSubjectNumber(''); setCreateError('') },
    onError: (error) => setCreateError(getApiErrorMessage(error, 'Could not create the subject. Please try again.')),
  })

  const subjectLifecycle = useMutation({
    mutationFn: async ({ action, reason }: { action: SubjectLifecycleAction; reason: string }) => {
      if (action.kind === 'delete') {
        return api.delete(`/subjects/${action.subject.id}`, {
          data: {
            reason,
            subject_number_confirmation: subjectNumberConfirmation.trim(),
          },
        })
      }
      if (action.kind === 'switch-site') {
        return api.post(`/subjects/${action.subject.id}/switch-site`, {
          site_id: transferSiteId,
          reason,
        })
      }
      if (action.kind === 'inactive') {
        return api.post(`/subjects/${action.subject.id}/deactivate`, { reason })
      }
      if (action.kind === 'discontinue') {
        return api.post(`/subjects/${action.subject.id}/discontinue`, { reason })
      }
      return api.post(`/subjects/${action.subject.id}/restore`, { reason })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subjects', studyId] })
      setLifecycleAction(null)
      setSubjectNumberConfirmation('')
      setTransferSiteId('')
      setLifecycleError('')
    },
    onError: (error) => setLifecycleError(getApiErrorMessage(error, 'The subject lifecycle action could not be completed.')),
  })

  const hasRows = Boolean(data && data.items.length > 0)

  return (
    <PageContainer wide>
      <PageHeader
        title="Subjects"
        description="Review clinical subjects for the selected study without changing server-owned status or totals."
        actions={canCreate ? <Button type="button" disabled={!enrollmentIsReady || enrollmentReadiness.isLoading || enrollmentReadiness.isError} title={!enrollmentIsReady ? 'Resolve enrollment prerequisites first.' : undefined} onClick={() => {
          const contextSiteIsValid = activeSites.some((site) => site.id === selectedSiteId)
          setCreateSiteId(contextSiteIsValid ? selectedSiteId ?? '' : '')
          setShowCreate(true)
        }}>Add subject</Button> : null}
      />

      {canCreate && enrollmentReadiness.data?.ready === false ? (
        <Alert variant="warning" className="mb-4">
          <AlertDescription>
            <p className="font-medium">Subject enrollment is not ready.</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {enrollmentBlockers.map((blocker) => <li key={blocker.code}>{blocker.message}</li>)}
            </ul>
            {enrollmentBlockers.some((blocker) => blocker.code === 'NO_PUBLISHED_DESIGN') ? (
              <Button asChild variant="link" className="mt-2 h-auto p-0"><Link to="/studies/$studyId/versions" params={{ studyId }}>Open study versioning</Link></Button>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
      {canCreate && enrollmentReadiness.isError ? (
        <Alert variant="destructive" className="mb-4"><AlertDescription>Unable to verify subject-enrollment readiness.</AlertDescription></Alert>
      ) : null}

      <PageToolbar label="Subject list controls">
        <Input
          type="search"
          placeholder="Search subjects…"
          value={globalFilter}
          onChange={(event) => setGlobalFilter(event.target.value)}
          aria-label="Search subjects"
          className="max-w-sm"
        />
        <select aria-label="Quality state" value={qualityState} onChange={(event) => { setQualityState(event.target.value); setPagination((current) => ({ ...current, pageIndex: 0 })) }} className="h-10 rounded-md border border-input bg-background px-3">
          <option value="all">All quality states</option>
          <option value="incomplete">Incomplete</option>
          <option value="queried">Queried</option>
          <option value="stale_review">Changed since review</option>
          <option value="clean">Clean</option>
        </select>
        {canRestore ? (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeRemoved}
              onChange={(event) => {
                setIncludeRemoved(event.target.checked)
                setPagination((current) => ({ ...current, pageIndex: 0 }))
              }}
            />
            Include removed subjects
          </label>
        ) : null}
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
          columns={createColumns(studyId, canDelete, canRestore, canTransfer, canUpdate, (action) => {
            setLifecycleAction(action)
            setSubjectNumberConfirmation('')
            setTransferSiteId('')
            setLifecycleError('')
          })}
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

      <Dialog open={showCreate} onOpenChange={(open) => { setShowCreate(open); if (!open) { setCreateError(''); setCreateSiteId('') } }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add subject</DialogTitle><DialogDescription>Create a clinical subject at an authorized site in this study.</DialogDescription></DialogHeader>
          {createError ? <Alert variant="destructive"><AlertDescription>{createError}</AlertDescription></Alert> : null}
          <form onSubmit={(event) => { event.preventDefault(); createSubject.mutate() }} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="subject-site">Site</Label>
              <select
                id="subject-site"
                aria-label="Subject site"
                value={createSiteId}
                onChange={(event) => { setCreateSiteId(event.target.value); setCreateError('') }}
                disabled={sites.isLoading || sites.isError || activeSites.length === 0}
                className="h-10 w-full rounded-md border border-input bg-background px-3 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="">Select site</option>
                {activeSites.map((site) => (
                  <option key={site.id} value={site.id}>{site.site_number} — {site.name}</option>
                ))}
              </select>
              {sites.isError ? <p className="text-sm text-destructive">Unable to load authorized sites.</p> : null}
              {sites.data && activeSites.length === 0 ? <p className="text-sm text-muted-foreground">No authorized active sites are configured for this study. Add, activate, or assign a site before creating a subject.</p> : null}
            </div>
            <Label htmlFor="subject-number">Subject number (optional)</Label>
            <Input id="subject-number" placeholder="Subject number (optional)" value={subjectNumber} onChange={(event) => setSubjectNumber(event.target.value)} />
            <DialogFooter><Button type="button" variant="outline" onClick={() => { setShowCreate(false); setCreateError(''); setCreateSiteId('') }}>Cancel</Button><Button type="submit" pending={createSubject.isPending} loadingText="Creating…" disabled={!createSiteId || sites.isLoading || sites.isError}>Create</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={lifecycleAction !== null}
        title={lifecycleAction?.kind === 'restore'
          ? 'Restore subject'
          : lifecycleAction?.kind === 'switch-site'
            ? 'Switch subject site'
            : lifecycleAction?.kind === 'inactive'
              ? 'Mark subject inactive'
              : lifecycleAction?.kind === 'discontinue'
                ? 'Discontinue subject'
                : 'Remove subject entered in error'}
        description={lifecycleAction?.kind === 'restore'
          ? `Restore subject ${lifecycleAction.subject.subject_number} to active subject lists.`
          : lifecycleAction?.kind === 'switch-site'
            ? `Move ${lifecycleAction.subject.subject_number} to another active site. The subject number and audit history are preserved.`
            : lifecycleAction?.kind === 'inactive'
              ? 'Inactive stops active subject workflow while retaining all clinical and audit records. An inactive subject may later be discontinued.'
              : lifecycleAction?.kind === 'discontinue'
                ? 'Discontinued is a terminal clinical status. Existing clinical and audit records remain retained.'
                : 'This action is only for a Screening subject created in error. Subjects with clinical, safety, or operational records must use a lifecycle status.'}
        confirmLabel={lifecycleAction?.kind === 'restore'
          ? 'Restore subject'
          : lifecycleAction?.kind === 'switch-site'
            ? 'Switch site'
            : lifecycleAction?.kind === 'inactive'
              ? 'Mark inactive'
              : lifecycleAction?.kind === 'discontinue'
                ? 'Discontinue'
                : 'Remove subject'}
        confirmVariant={lifecycleAction?.kind === 'delete' || lifecycleAction?.kind === 'discontinue' ? 'destructive' : 'default'}
        pending={subjectLifecycle.isPending}
        confirmDisabled={Boolean(
          (lifecycleAction?.kind === 'delete'
            && subjectNumberConfirmation.trim() !== lifecycleAction.subject.subject_number)
          || (lifecycleAction?.kind === 'switch-site' && !transferSiteId)
        )}
        reason={{
          label: lifecycleAction?.kind === 'restore'
            ? 'Restore reason'
            : lifecycleAction?.kind === 'delete'
              ? 'Removal reason'
              : 'Reason for change',
          description: 'Required for the immutable audit trail. Do not include unnecessary sensitive details.',
          required: true,
          maxLength: 4000,
        }}
        onConfirm={(reason) => {
          if (lifecycleAction && reason) subjectLifecycle.mutate({ action: lifecycleAction, reason })
        }}
        onCancel={() => {
          setLifecycleAction(null)
          setSubjectNumberConfirmation('')
          setTransferSiteId('')
          setLifecycleError('')
        }}
      >
        {lifecycleError ? <Alert variant="destructive"><AlertDescription>{lifecycleError}</AlertDescription></Alert> : null}
        {lifecycleAction?.kind === 'delete' ? (
          <div className="space-y-2">
            <Label htmlFor="subject-number-confirmation">Type {lifecycleAction.subject.subject_number} to confirm</Label>
            <Input
              id="subject-number-confirmation"
              value={subjectNumberConfirmation}
              onChange={(event) => {
                setSubjectNumberConfirmation(event.target.value)
                setLifecycleError('')
              }}
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">The subject number remains reserved and will not be reused.</p>
          </div>
        ) : null}
        {lifecycleAction?.kind === 'switch-site' ? (
          <div className="space-y-2">
            <Label htmlFor="subject-transfer-site">Destination site</Label>
            <select
              id="subject-transfer-site"
              value={transferSiteId}
              onChange={(event) => {
                setTransferSiteId(event.target.value)
                setLifecycleError('')
              }}
              className="h-10 w-full rounded-md border border-input bg-background px-3"
            >
              <option value="">Select destination site</option>
              {activeSites.filter((site) => site.id !== lifecycleAction.subject.site_id).map((site) => (
                <option key={site.id} value={site.id}>{site.site_number} — {site.name}</option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">Switching is blocked after clinical data or downstream safety/CTMS use.</p>
          </div>
        ) : null}
      </ConfirmDialog>
    </PageContainer>
  )
}
