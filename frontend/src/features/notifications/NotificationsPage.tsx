import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'
import { DetailCard, EmptyState, ErrorState, LoadingState, PageContainer, PageHeader, StatusBadge } from '@/components/patterns'
import { Button } from '@/components/ui/button'

interface Notification { id: string; type: string; payload_json: Record<string, unknown>; status: 'Unread' | 'Read' | 'Archived'; created_at: string }

function notificationText(item: Notification) {
  const payload = item.payload_json
  return String(payload.message ?? payload.text ?? payload.title ?? `A ${item.type.toLowerCase()} event needs your attention.`)
}

export function NotificationsPage() {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['notifications'],
    queryFn: async () => (await api.get<PaginatedResponse<Notification>>('/notifications', { params: { page: 1, page_size: 50 } })).data,
  })
  const action = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: 'read' | 'archive' }) => api.post(`/notifications/${id}/${verb}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['notifications'] }),
  })

  return (
    <PageContainer>
      <PageHeader title="Notifications" description="Workflow events assigned to you." />

      {query.error ? <ErrorState state="error" message="Notifications could not be loaded." /> : null}
      {query.isLoading ? <LoadingState label="notifications" /> : null}
      {!query.isLoading && !query.error && query.data?.items.length === 0 ? (
        <EmptyState title="You have no unread notifications." description="New workflow events will appear here when they need your attention." />
      ) : null}
      {!query.isLoading && !query.error && query.data?.items.length ? (
        <section aria-label="Notifications" className="grid gap-3">
          {query.data.items.map((item) => (
            <DetailCard
              key={item.id}
              title={item.type.replaceAll('_', ' ')}
              status={<StatusBadge status={item.status} label="Notification status" />}
              className={item.status === 'Unread' ? 'border-primary/30 bg-primary/5' : undefined}
              footer={
                <div className="flex w-full justify-end gap-2">
                  {item.status === 'Unread' ? <Button size="sm" variant="outline" pending={action.isPending} onClick={() => action.mutate({ id: item.id, verb: 'read' })}>Mark read</Button> : null}
                  <Button size="sm" variant="ghost" pending={action.isPending} onClick={() => action.mutate({ id: item.id, verb: 'archive' })}>Archive</Button>
                </div>
              }
            >
              <p className="text-sm text-foreground">{notificationText(item)}</p>
              <p className="mt-2 text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString()}</p>
            </DetailCard>
          ))}
        </section>
      ) : null}
    </PageContainer>
  )
}
