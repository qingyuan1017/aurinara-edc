import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { StatusBadge } from '@/components/patterns'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useStudyContext } from '@/lib/study-context'

interface AssignUser { id: string; email: string; first_name: string; last_name: string; status: string }
interface RoleOption { id: string; name: string; scope_level: 'system' | 'study' | 'site'; description?: string }
interface StudyOption { id: string; study_code: string; title: string }
interface SiteOption { id: string; site_number: string; name: string }

const selectClass =
  'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'

export function AssignRolesDialog({
  user,
  open,
  onOpenChange,
}: {
  user: AssignUser
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const canAssign = usePermission(PERMISSIONS.USER_ASSIGN)
  const defaultStudyId = useStudyContext((state) => state.selectedStudyId)
  const [studyId, setStudyId] = useState<string>(defaultStudyId ?? '')
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [siteId, setSiteId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  const { data: roles } = useQuery({
    queryKey: ['roles', 'assign-roles'],
    queryFn: async () =>
      (await api.get<PaginatedResponse<RoleOption>>('/roles', { params: { page_size: 100 } })).data.items,
  })
  const { data: studies } = useQuery({
    queryKey: ['studies', 'assign-roles'],
    queryFn: async () =>
      (await api.get<PaginatedResponse<StudyOption>>('/studies', { params: { page_size: 100 } })).data.items,
  })

  const selectedRoles = (roles ?? []).filter((role) => selectedRoleIds.includes(role.id))
  const requiresSite = selectedRoles.some((role) => role.scope_level === 'site')

  const { data: sites } = useQuery({
    queryKey: ['sites', studyId],
    queryFn: async () =>
      (await api.get<PaginatedResponse<SiteOption>>(`/studies/${studyId}/sites`, { params: { page_size: 100 } })).data
        .items,
    enabled: Boolean(studyId) && requiresSite,
  })

  const assignMutation = useMutation({
    mutationFn: async () => {
      const body = selectedRoles.map((role) => ({
        role_id: role.id,
        study_id: studyId,
        ...(role.scope_level === 'site' ? { site_id: siteId } : {}),
      }))
      return (await api.post(`/studies/${studyId}/users/${user.id}/assign`, body)).data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      resetForm()
      onOpenChange(false)
    },
    onError: (err: unknown) => {
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(message ?? 'Failed to assign roles')
    },
  })

  function resetForm() {
    setStudyId(defaultStudyId ?? '')
    setSelectedRoleIds([])
    setSiteId('')
    setError(null)
  }

  function toggleRole(roleId: string) {
    setSelectedRoleIds((current) =>
      current.includes(roleId) ? current.filter((id) => id !== roleId) : [...current, roleId],
    )
  }

  const canSubmit =
    canAssign && Boolean(studyId) && selectedRoleIds.length > 0 && (!requiresSite || Boolean(siteId))

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) resetForm()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Assign roles</DialogTitle>
          <DialogDescription>
            Grant internal roles to this user, scoped by study and (for site-scoped roles) site.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1 rounded border border-border bg-muted/40 p-3 text-sm">
          <p className="font-medium">
            {user.first_name} {user.last_name}
          </p>
          <p className="text-muted-foreground">{user.email}</p>
          <StatusBadge status={user.status} label="User status" />
        </div>
        <p className="text-xs text-muted-foreground">
          Current role assignments aren&apos;t returned by the API and can&apos;t be shown here.
        </p>

        {error ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <form
          onSubmit={(event) => {
            event.preventDefault()
            assignMutation.mutate()
          }}
          className="space-y-4"
        >
          <div className="space-y-2">
            <Label htmlFor="assign-study">Study</Label>
            <select
              id="assign-study"
              value={studyId}
              onChange={(event) => {
                setStudyId(event.target.value)
                setSiteId('')
              }}
              className={selectClass}
              required
            >
              <option value="">Select study…</option>
              {studies?.map((study) => (
                <option key={study.id} value={study.id}>
                  {study.study_code} — {study.title}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium leading-none">Roles</legend>
            <p className="text-xs text-muted-foreground">
              Select one or more roles. Site-scoped roles require a site below.
            </p>
            <div className="space-y-2">
              {roles?.map((role) => (
                <label key={role.id} htmlFor={`assign-role-${role.id}`} className="flex items-center gap-2 text-sm">
                  <input
                    id={`assign-role-${role.id}`}
                    type="checkbox"
                    checked={selectedRoleIds.includes(role.id)}
                    onChange={() => toggleRole(role.id)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <span>{role.name}</span>
                  <StatusBadge status={role.scope_level} label="Role scope" tone="info" />
                </label>
              ))}
            </div>
          </fieldset>

          {requiresSite ? (
            <div className="space-y-2">
              <Label htmlFor="assign-site">Site</Label>
              <select
                id="assign-site"
                value={siteId}
                onChange={(event) => setSiteId(event.target.value)}
                className={selectClass}
                required
              >
                <option value="">Select site…</option>
                {sites?.map((site) => (
                  <option key={site.id} value={site.id}>
                    {site.site_number} — {site.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false)
                resetForm()
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit} pending={assignMutation.isPending} loadingText="Assigning…">
              Assign roles
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
