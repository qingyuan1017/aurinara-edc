import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { api } from '@/lib/api'
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

export function ExportCenterPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canExport = usePermission(PERMISSIONS.DATA_EXPORT)
  const [page, setPage] = useState(1)
  const [showModal, setShowModal] = useState(false)
  const [format, setFormat] = useState('csv')
  const [siteFilter, setSiteFilter] = useState('')
  const [error, setError] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['exports', studyId, page],
    queryFn: async () => {
      const { data } = await api.get<PaginatedResponse<Export>>(`/studies/${studyId}/exports`, {
        params: { page, page_size: 20 },
      })
      return data
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

  const columns = [
    columnHelper.accessor('format', {
      header: 'Format',
      cell: (info) => info.getValue().toUpperCase(),
    }),
    columnHelper.accessor('status', {
      header: 'Status',
      cell: (info) => <StatusBadge label="Export status" status={info.getValue()} />,
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
      header: 'Download',
      cell: (info) => {
        const row = info.row.original
        if (row.status === 'completed') {
          return (
            <Button type="button" variant="link" size="sm" onClick={() => handleDownload(row.id)}>
              Download
            </Button>
          )
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
            <DialogDescription>Choose the export format and optional site filter.</DialogDescription>
          </DialogHeader>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const filters: Record<string, string> = {}
              if (siteFilter) filters.site_id = siteFilter
              createMutation.mutate({ format, filters })
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
                  <SelectItem value="csv">CSV</SelectItem>
                  <SelectItem value="sas">SAS</SelectItem>
                  <SelectItem value="json">JSON</SelectItem>
                  <SelectItem value="odm_xml">ODM XML</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="export-site">Site Filter (optional)</Label>
              <Input
                id="export-site"
                type="text"
                value={siteFilter}
                onChange={(event) => setSiteFilter(event.target.value)}
                placeholder="Site ID (leave blank for all)"
              />
            </div>
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
