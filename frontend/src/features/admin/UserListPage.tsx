import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { api, type PaginatedResponse } from '@/lib/api'
import { DataTableShell, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { usePermission, PERMISSIONS } from '@/lib/permissions'

interface User { id: string; email: string; first_name: string; last_name: string; status: string; created_at: string }
interface InviteUserPayload { email: string; first_name: string; last_name: string; role_id: string }
const columnHelper = createColumnHelper<User>()
const columns = [
  columnHelper.accessor((row) => `${row.first_name} ${row.last_name}`, { id: 'name', header: 'Name' }),
  columnHelper.accessor('email', { header: 'Email' }),
  columnHelper.accessor('status', { header: 'Status', cell: (info) => <StatusBadge status={info.getValue()} label="User status" /> }),
  columnHelper.accessor('created_at', { header: 'Created', cell: (info) => new Date(info.getValue()).toLocaleDateString() }),
]

export function UserListPage() {
  const queryClient = useQueryClient()
  const canCreate = usePermission(PERMISSIONS.USER_CREATE)
  const canDeactivate = usePermission(PERMISSIONS.USER_DEACTIVATE)
  const [page, setPage] = useState(1)
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [formData, setFormData] = useState<InviteUserPayload>({ email: '', first_name: '', last_name: '', role_id: '' })
  const [error, setError] = useState<string | null>(null)

  const { data, isLoading, error: queryError } = useQuery({
    queryKey: ['users', page],
    queryFn: async () => (await api.get<PaginatedResponse<User>>('/users', { params: { page, page_size: 20 } })).data,
  })
  const { data: roles } = useQuery({ queryKey: ['roles'], queryFn: async () => (await api.get<{ items: Array<{ id: string; name: string }> }>('/roles')).data.items })
  const inviteMutation = useMutation({
    mutationFn: async (payload: InviteUserPayload) => (await api.post('/auth/invite', { email: payload.email, role_id: payload.role_id })).data,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['users'] }); setShowInviteModal(false); setFormData({ email: '', first_name: '', last_name: '', role_id: '' }); setError(null) },
    onError: (err: unknown) => { const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail; setError(message ?? 'Failed to invite user') },
  })
  const deactivateMutation = useMutation({ mutationFn: async (userId: string) => { await api.post(`/users/${userId}/deactivate`) }, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }) })
  const table = useReactTable({ data: data?.items ?? [], columns, getCoreRowModel: getCoreRowModel() })
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0

  return (
    <PageContainer wide>
      <PageHeader title="Users" description="Manage users within the current EDC workspace." actions={canCreate ? <Button type="button" onClick={() => setShowInviteModal(true)}>Invite User</Button> : null} />

      <DataTableShell label="Users" loading={isLoading} error={Boolean(queryError)} errorMessage="Users could not be loaded." empty={data?.items.length === 0} emptyTitle="No users found.">
        <Table>
          <caption className="sr-only">Users</caption>
          <TableHeader>{table.getHeaderGroups().map((headerGroup) => <TableRow key={headerGroup.id}>{headerGroup.headers.map((header) => <TableHead key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}{canDeactivate ? <TableHead>Actions</TableHead> : null}</TableRow>)}</TableHeader>
          <TableBody>{table.getRowModel().rows.map((row) => <TableRow key={row.id}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}{canDeactivate ? <TableCell>{row.original.status === 'active' ? <Button type="button" variant="link" size="sm" pending={deactivateMutation.isPending} onClick={() => deactivateMutation.mutate(row.original.id)}>Deactivate</Button> : null}</TableCell> : null}</TableRow>)}</TableBody>
        </Table>
      </DataTableShell>

      {totalPages > 1 ? <div className="flex flex-wrap items-center justify-between gap-3 pt-4"><p className="text-sm text-muted-foreground">Page {page} of {totalPages} ({data?.total ?? 0} total)</p><div className="flex gap-2"><Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</Button><Button type="button" variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>Next</Button></div></div> : null}

      <Dialog open={showInviteModal} onOpenChange={(open) => { setShowInviteModal(open); if (!open) setError(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Invite User</DialogTitle><DialogDescription>Send an invitation using the existing user-management workflow.</DialogDescription></DialogHeader>
          {error ? <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <form onSubmit={(event) => { event.preventDefault(); inviteMutation.mutate(formData) }} className="space-y-4">
            <div className="space-y-2"><Label htmlFor="user-email">Email</Label><Input id="user-email" type="email" value={formData.email} onChange={(event) => setFormData((current) => ({ ...current, email: event.target.value }))} required /></div>
            <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="user-first-name">First Name</Label><Input id="user-first-name" value={formData.first_name} onChange={(event) => setFormData((current) => ({ ...current, first_name: event.target.value }))} required /></div><div className="space-y-2"><Label htmlFor="user-last-name">Last Name</Label><Input id="user-last-name" value={formData.last_name} onChange={(event) => setFormData((current) => ({ ...current, last_name: event.target.value }))} required /></div></div>
            <div className="space-y-2"><Label htmlFor="user-role">Role</Label><select id="user-role" value={formData.role_id} onChange={(event) => setFormData((current) => ({ ...current, role_id: event.target.value }))} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" required><option value="">Select role…</option>{roles?.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></div>
            <DialogFooter><Button type="button" variant="outline" onClick={() => { setShowInviteModal(false); setError(null) }}>Cancel</Button><Button type="submit" pending={inviteMutation.isPending} loadingText="Inviting…">Send Invite</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
