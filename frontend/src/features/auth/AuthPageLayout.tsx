import type { ReactNode } from 'react'
import { Card, CardContent, CardFooter } from '@/components/ui/card'
import { PageContainer } from '@/components/patterns/PageContainer'
import { PageHeader } from '@/components/patterns/PageHeader'

interface AuthPageLayoutProps {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}

/** Presentation-only layout shared by public authentication pages. */
export function AuthPageLayout({ title, description, children, footer }: AuthPageLayoutProps) {
  return (
    <PageContainer className="flex min-h-screen max-w-none items-center justify-center bg-muted/30 px-4 py-8">
      <div className="w-full max-w-md">
        <PageHeader title={title} description={description} className="text-center" />
        <Card>
          <CardContent className="space-y-6 pt-6">{children}</CardContent>
          {footer ? <CardFooter className="justify-center border-t pt-6">{footer}</CardFooter> : null}
        </Card>
      </div>
    </PageContainer>
  )
}
