import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { api, getApiErrorMessage } from '@/lib/api'
import type { PaginatedResponse } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { EmptyState, ErrorState, LoadingState, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'

interface Export {
  id: string
  export_type: string
  status: string
  created_at: string
  completed_at?: string
  file_size?: number
  filters?: Record<string, unknown>
  error_message?: string
  module?: string
  content_owner?: string
  correlation_id?: string
}

interface CreateExportPayload {
  export_type: string
  filters: Record<string, string | boolean | string[]>
}

interface ExportDatasetOption {
  name: string
  label: string
  design_version_ids: string[]
  form_definition_ids: string[]
}

interface SiteOption {
  id: string
  site_number: string
  name: string
}

interface SubjectOption {
  id: string
  subject_number: string
}

interface VisitOption {
  id: string
  name: string
  visit_date: string | null
}

const columnHelper = createColumnHelper<Export>()

function exportFileExtension(exportType: string): string {
  switch (exportType) {
    case 'excel': return 'xlsx'
    case 'sas_xpt':
    case 'xpt':
    case 'csv': return 'zip'
    case 'odm_xml':
    case 'odm': return 'xml'
    case 'subject_list': return 'csv'
    default: return exportType
  }
}

function downloadFilename(contentDisposition: string | undefined): string | null {
  if (!contentDisposition) return null
  const encoded = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      return encoded
    }
  }
  return contentDisposition.match(/filename="([^"]+)"/i)?.[1]
    ?? contentDisposition.match(/filename=([^;]+)/i)?.[1]?.trim()
    ?? null
}

export function ExportCenterPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canExport = usePermission(PERMISSIONS.DATA_EXPORT)
  const [page, setPage] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [format, setFormat] = useState('csv')
  const [siteFilter, setSiteFilter] = useState('')
  const [subjectFilter, setSubjectFilter] = useState('')
  const [visitFilter, setVisitFilter] = useState('')
  const [formFilter, setFormFilter] = useState('')
  const [selectedDatasets, setSelectedDatasets] = useState<string[]>([])
  const [changedSince, setChangedSince] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [lockedOnly, setLockedOnly] = useState(false)
  const [cleanOnly, setCleanOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['exports', studyId, page],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Export>>(`/studies/${studyId}/exports`, {
        params: { page, page_size: 20 },
      })
      return data
    },
    refetchInterval: (query) => query.state.data?.items.some((item) => ['queued', 'running'].includes(item.status.toLowerCase())) ? 3000 : false,
  })

  const datasetsQuery = useQuery({
    queryKey: ['export-datasets', studyId],
    queryFn: async () => (await api.get<ExportDatasetOption[]>(`/studies/${studyId}/exports/datasets`)).data,
    enabled: canExport,
  })

  const sitesQuery = useQuery({
    queryKey: ['export-sites', studyId],
    queryFn: async () => (await api.get<PaginatedResponse<SiteOption>>(`/studies/${studyId}/sites`, {
      params: { page: 1, page_size: 100 },
    })).data,
    enabled: canExport && showModal,
  })

  const subjectsQuery = useQuery({
    queryKey: ['export-subjects', studyId, siteFilter],
    queryFn: async () => (await api.get<PaginatedResponse<SubjectOption>>(`/studies/${studyId}/subjects`, {
      params: { page: 1, page_size: 100, site_id: siteFilter },
    })).data,
    enabled: canExport && showModal && Boolean(siteFilter),
  })

  const visitsQuery = useQuery({
    queryKey: ['export-visits', subjectFilter],
    queryFn: async () => (await api.get<VisitOption[]>(`/subjects/${subjectFilter}/visits`)).data,
    enabled: canExport && showModal && Boolean(subjectFilter),
  })

  const handleDownload = async (job: Export) => {
    try {
      setDownloadError(null)
      const response = await api.get<Blob>(
        `/exports/${job.id}/download`,
        { responseType: 'blob' },
      )
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = downloadFilename(response.headers?.['content-disposition'])
        ?? `edc_export_${job.id}.${exportFileExtension(job.export_type)}`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (err: unknown) {
      setDownloadError(getApiErrorMessage(err, 'Failed to download export'))
    }
  }

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
      setSubjectFilter('')
      setVisitFilter('')
      setFormFilter('')
      setSelectedDatasets([])
      setChangedSince('')
      setDateFrom('')
      setDateTo('')
      setLockedOnly(false)
      setCleanOnly(false)
      setError(null)
    },
    onError: (err: unknown) => setError(getApiErrorMessage(err, 'Failed to create export')),
  })

  const retryMutation = useMutation({
    mutationFn: (exportId: string) => api.post(`/exports/${exportId}/retry`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['exports', studyId] }),
  })

  const columns = [
    columnHelper.accessor('export_type', {
      header: 'Format',
      cell: (info) => info.getValue()?.toUpperCase() ?? '—',
    }),
    columnHelper.accessor('status', {
      header: 'Status',
      cell: (info) => <StatusBadge label="Export status" status={info.getValue()} />,
    }),
    columnHelper.display({
      id: 'dataset',
      header: 'Dataset / filters',
      cell: (info) => {
        const filters = info.row.original.filters ?? {}
        const entries = Object.entries(filters)
        return (
          <div className="max-w-80 text-xs">
            <p className="font-medium">{Array.isArray(filters.datasets) ? filters.datasets.join(', ') : String(filters.dataset ?? 'All datasets')}</p>
            <p className="truncate text-muted-foreground" title={JSON.stringify(filters)}>
              {entries.filter(([key]) => !['dataset', 'datasets'].includes(key)).length ? entries.filter(([key]) => !['dataset', 'datasets'].includes(key)).map(([key, value]) => `${key}=${String(value)}`).join(', ') : 'No additional filters'}
            </p>
            {info.row.original.error_message ? <p className="text-destructive">{info.row.original.error_message}</p> : null}
          </div>
        )
      },
    }),
    columnHelper.accessor('created_at', {
      header: 'Requested',
      cell: (info) => new Date(info.getValue()).toLocaleString(),
    }),
    columnHelper.accessor('completed_at', {
      header: 'Completed',
      cell: (info) => {
        const value = info.getValue()
        return value ? new Date(value).toLocaleString() : '—'
      },
    }),
    columnHelper.display({
      id: 'actions',
      header: 'Actions',
      cell: (info) => {
        const row = info.row.original
        if (row.status.toLowerCase() === 'completed') {
          return (
            <Button type="button" variant="link" size="sm" onClick={() => handleDownload(row)}>
              Download
            </Button>
          )
        }
        if (row.status.toLowerCase() === 'failed') {
          return <Button type="button" variant="outline" size="sm" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(row.id)}>Retry</Button>
        }
        return <span className="text-sm text-muted-foreground">—</span>
      },
    }),
  ]

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0

  return (
    <PageContainer wide>
      <PageHeader
        title="Export Center"
        description="Create and download study data exports while preserving clinical data ownership."
        actions={canExport ? (
          <Button type="button" onClick={() => { setError(null); setShowModal(true) }}>
            Create Export
          </Button>
        ) : null}
      />

      {downloadError ? <Alert variant="destructive"><AlertDescription>{downloadError}</AlertDescription></Alert> : null}
      {isLoading ? <LoadingState label="exports" /> : null}
      {isError ? <ErrorState message="Unable to load exports. Please try again." onRetry={() => void refetch()} /> : null}
      {!isLoading && !isError && data && data.items.length === 0 ? (
        <EmptyState
          title="No exports yet"
          description="Create an export to download study data in a supported format."
          action={canExport ? <Button type="button" onClick={() => setShowModal(true)}>Create Export</Button> : undefined}
        />
      ) : null}
      {!isLoading && !isError && data && data.items.length > 0 ? (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {flexRender(header.column.columnDef.header, header.getContext())}
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
          </CardContent>
        </Card>
      ) : null}

      {!isLoading && !isError && data && totalPages > 1 ? (
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Page {page} of {totalPages} ({data.total} total)
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>
              Previous
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>
              Next
            </Button>
          </div>
        </div>
      ) : null}

      <Dialog open={showModal} onOpenChange={(open) => { setShowModal(open); if (!open) setError(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Export</DialogTitle>
            <DialogDescription>Choose the dataset, format, and authorized intersection filters.</DialogDescription>
          </DialogHeader>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const filters: Record<string, string | boolean | string[]> = {}
              if (selectedDatasets.length) filters.datasets = selectedDatasets
              if (siteFilter) filters.site_id = siteFilter
              if (subjectFilter) filters.subject_id = subjectFilter
              if (visitFilter) filters.visit_id = visitFilter
              if (formFilter) filters.form_id = formFilter
              if (changedSince) filters.changed_since = new Date(changedSince).toISOString()
              if (dateFrom) filters.date_from = new Date(dateFrom).toISOString()
              if (dateTo) filters.date_to = new Date(dateTo).toISOString()
              if (lockedOnly) filters.locked_only = true
              if (cleanOnly) filters.clean_only = true
              createMutation.mutate({ export_type: format, filters })
            }}
            className="space-y-4"
          >
            <div className="relative space-y-1.5">
              <Label htmlFor="export-format">Format</Label>
              <Select value={format} onValueChange={setFormat}>
                <SelectTrigger id="export-format" aria-label="Format">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="csv">CSV datasets (ZIP)</SelectItem>
                  <SelectItem value="excel">Excel workbook</SelectItem>
                  <SelectItem value="sas_xpt">SAS XPT datasets (ZIP)</SelectItem>
                  <SelectItem value="json">JSON</SelectItem>
                  <SelectItem value="odm_xml">ODM XML</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Datasets</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={selectedDatasets.length === 0} onChange={() => setSelectedDatasets([])} />
                All datasets
              </label>
              {datasetsQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading datasets…</p> : null}
              {datasetsQuery.isError ? <p className="text-sm text-destructive">Dataset definitions could not be loaded.</p> : null}
              <div className="grid max-h-40 gap-2 overflow-y-auto sm:grid-cols-2">
                {(datasetsQuery.data ?? []).map((dataset) => (
                  <label key={dataset.name} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedDatasets.includes(dataset.name)}
                      onChange={(event) => setSelectedDatasets((current) => event.target.checked ? [...current, dataset.name] : current.filter((name) => name !== dataset.name))}
                    />
                    {dataset.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="export-site">Site (optional)</Label>
                <select
                  id="export-site"
                  value={siteFilter}
                  onChange={(event) => {
                    setSiteFilter(event.target.value)
                    setSubjectFilter('')
                    setVisitFilter('')
                  }}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 disabled:opacity-50"
                  disabled={sitesQuery.isLoading}
                >
                  <option value="">{sitesQuery.isLoading ? 'Loading sites…' : 'All sites'}</option>
                  {(sitesQuery.data?.items ?? []).map((site) => (
                    <option key={site.id} value={site.id}>{site.site_number} — {site.name}</option>
                  ))}
                </select>
                {sitesQuery.isError ? <p className="text-xs text-destructive">Sites could not be loaded.</p> : null}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="export-subject">Subject (optional)</Label>
                <select
                  id="export-subject"
                  value={subjectFilter}
                  onChange={(event) => {
                    setSubjectFilter(event.target.value)
                    setVisitFilter('')
                  }}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 disabled:opacity-50"
                  disabled={!siteFilter || subjectsQuery.isLoading}
                >
                  <option value="">
                    {!siteFilter ? 'Select a site first' : subjectsQuery.isLoading ? 'Loading subjects…' : 'All subjects'}
                  </option>
                  {(subjectsQuery.data?.items ?? []).map((subject) => (
                    <option key={subject.id} value={subject.id}>{subject.subject_number}</option>
                  ))}
                </select>
                {subjectsQuery.isError ? <p className="text-xs text-destructive">Subjects could not be loaded.</p> : null}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="export-visit">Visit (optional)</Label>
                <select
                  id="export-visit"
                  value={visitFilter}
                  onChange={(event) => setVisitFilter(event.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 disabled:opacity-50"
                  disabled={!subjectFilter || visitsQuery.isLoading}
                >
                  <option value="">
                    {!subjectFilter ? 'Select a subject first' : visitsQuery.isLoading ? 'Loading visits…' : 'All visits'}
                  </option>
                  {(visitsQuery.data ?? []).map((visit) => (
                    <option key={visit.id} value={visit.id}>
                      {visit.name}{visit.visit_date ? ` — ${visit.visit_date}` : ''}
                    </option>
                  ))}
                </select>
                {visitsQuery.isError ? <p className="text-xs text-destructive">Visits could not be loaded.</p> : null}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="export-form">Form ID (optional)</Label>
              <Input id="export-form" value={formFilter} onChange={(event) => setFormFilter(event.target.value)} />
            </div>
            <div className="space-y-1.5"><Label htmlFor="export-changed">Changed since (optional)</Label><Input id="export-changed" type="datetime-local" value={changedSince} onChange={(event) => setChangedSince(event.target.value)} /></div>
            <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-1.5"><Label htmlFor="export-date-from">Date from</Label><Input id="export-date-from" type="datetime-local" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></div><div className="space-y-1.5"><Label htmlFor="export-date-to">Date to</Label><Input id="export-date-to" type="datetime-local" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></div></div>
            <div className="flex flex-wrap gap-6"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={lockedOnly} onChange={(event) => setLockedOnly(event.target.checked)} />Locked only</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={cleanOnly} onChange={(event) => setCleanOnly(event.target.checked)} />Clean only</label></div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => { setShowModal(false); setError(null) }} disabled={createMutation.isPending}>
                Cancel
              </Button>
              <Button type="submit" pending={createMutation.isPending} loadingText="Creating…">
                Start Export
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
