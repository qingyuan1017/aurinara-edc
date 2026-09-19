import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import {
  DataTableShell,
  DetailCard,
  ErrorState,
  LoadingState,
  PageContainer,
  PageHeader,
  StatusBadge,
  OwnershipBadge,
} from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface StudyDetail {
  id: string
  study_code: string
  title: string
  phase: string
  status: string
  description?: string
  created_at: string
  updated_at: string
}

interface StudyVersion {
  id: string
  version_number: string
  status: string
  amendment_reason?: string | null
  created_at: string
}

const STATUS_TRANSITIONS: Record<string, string[]> = {
  Draft: ['UAT'],
  UAT: ['Active'],
  Active: ['Enrollment Closed'],
  'Enrollment Closed': ['Locked'],
  Locked: ['Archived'],
  Archived: [],
}

export function StudyDetailPage({ studyId }: { studyId: string }) {
  const queryClient = useQueryClient()
  const canConfigure = usePermission(PERMISSIONS.STUDY_CONFIGURE)
  const canPublish = usePermission(PERMISSIONS.VERSION_PUBLISH)

  const { data: study, isLoading } = useQuery({
    queryKey: ['study', studyId],
    queryFn: async () => {
      const { data } = await api.get<StudyDetail>(`/studies/${studyId}`)
      return data
    },
  })

  const { data: versions, isLoading: isVersionsLoading, error: versionsError } = useQuery({
    queryKey: ['study-versions', studyId],
    queryFn: async () => {
      const { data } = await api.get<StudyVersion[]>(`/studies/${studyId}/versions`)
      return data
    },
  })

  const transitionMutation = useMutation({
    mutationFn: async (newStatus: string) => {
      await api.post(`/studies/${studyId}/transition`, { target_status: newStatus })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['study', studyId] })
      queryClient.invalidateQueries({ queryKey: ['studies'] })
    },
  })

  const publishMutation = useMutation({
    mutationFn: (versionId: string) => api.post(`/versions/${versionId}/publish`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['study-versions', studyId] }),
  })

  if (isLoading) {
    return <PageContainer><LoadingState label="study" /></PageContainer>
  }

  if (!study) {
    return <PageContainer><ErrorState message="Study not found." /></PageContainer>
  }

  const allowedTransitions = STATUS_TRANSITIONS[study.status] ?? []

  return (
    <PageContainer>
      <PageHeader
        title={study.title}
        description={`${study.study_code} · Phase ${study.phase ?? '—'}`}
        status={<StatusBadge status={study.status} label="Study status" />}
        ownership={<OwnershipBadge owner="EDC" />}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm"><a href={`/studies/${studyId}/dashboard`}>View Dashboard</a></Button>
            <Button asChild variant="secondary" size="sm"><a href={`/studies/${studyId}/versions`}>Manage Versions</a></Button>
            <Button asChild variant="outline" size="sm"><a href={`/studies/${studyId}/forms`}>Configure Forms</a></Button>
          </div>
        }
      />

      {canConfigure && allowedTransitions.length > 0 ? (
        <DetailCard title="Study lifecycle" description="Advance the study through its permitted lifecycle states." className="mb-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Transition to:</span>
            {allowedTransitions.map((status) => (
              <Button
                key={status}
                type="button"
                variant="outline"
                size="sm"
                pending={transitionMutation.isPending}
                onClick={() => transitionMutation.mutate(status)}
              >
                {status.charAt(0).toUpperCase() + status.slice(1)}
              </Button>
            ))}
          </div>
        </DetailCard>
      ) : null}

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList aria-label="Study detail sections">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <DetailCard title="Study information" description="Study metadata supplied by the EDC study service.">
            <dl className="grid gap-4 sm:grid-cols-2">
              <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Created</dt><dd className="mt-1 text-sm text-foreground">{new Date(study.created_at).toLocaleString()}</dd></div>
              <div><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Last updated</dt><dd className="mt-1 text-sm text-foreground">{new Date(study.updated_at).toLocaleString()}</dd></div>
              {study.description ? <div className="sm:col-span-2"><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Description</dt><dd className="mt-1 text-sm text-foreground">{study.description}</dd></div> : null}
            </dl>
          </DetailCard>
        </TabsContent>

        <TabsContent value="versions">
          <DataTableShell
            label="Study versions"
            loading={isVersionsLoading}
            error={Boolean(versionsError)}
            errorMessage="Study versions could not be loaded."
            empty={versions?.length === 0}
            emptyTitle="No versions created yet."
          >
            <Table>
              <caption className="sr-only">Study versions</caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead><span className="sr-only">Actions</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions?.map((version) => (
                  <TableRow key={version.id}>
                    <TableCell className="font-medium">v{version.version_number}</TableCell>
                    <TableCell><StatusBadge status={version.status} label="Version status" /></TableCell>
                    <TableCell>{new Date(version.created_at).toLocaleDateString()}</TableCell>
                    <TableCell>
                      {canPublish && version.status === 'draft' ? (
                        <Button type="button" variant="link" size="sm" pending={publishMutation.isPending} onClick={() => publishMutation.mutate(version.id)}>Publish</Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DataTableShell>
        </TabsContent>
      </Tabs>
    </PageContainer>
  )
}
