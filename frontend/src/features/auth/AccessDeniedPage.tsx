import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from '@/components/patterns/PageHeader'

/**
 * Access Denied page shown when a user lacks required permissions.
 * Provides a link back to the dashboard.
 */
export function AccessDeniedPage() {
  const navigate = useNavigate()

  return (
    <section className="mx-auto flex min-h-[60vh] w-full max-w-2xl flex-col justify-center gap-6">
      <PageHeader
        title="Access Denied"
        description="You do not have permission to access this page. Contact your study administrator if you believe this is an error."
      />
      <Card>
        <CardContent className="flex flex-col items-center gap-4 pt-6 text-center">
          <p className="text-4xl" aria-hidden="true">🚫</p>
          <Button type="button" onClick={() => navigate({ to: '/' })}>
            Return to Dashboard
          </Button>
        </CardContent>
      </Card>
    </section>
  )
}
