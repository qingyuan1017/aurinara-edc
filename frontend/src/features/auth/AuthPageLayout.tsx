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
    <PageContainer className="relative flex min-h-screen max-w-none items-center justify-center overflow-hidden bg-primary px-4 py-8 before:absolute before:-right-24 before:-top-32 before:size-[28rem] before:rounded-full before:border before:border-primary-foreground/10 before:shadow-[0_0_0_80px_rgb(232_196_119_/_0.05),0_0_0_160px_rgb(232_196_119_/_0.025)]">
      <div className="w-full max-w-md">
        <div className="relative mb-6 text-center text-primary-foreground">
          <div className="font-display text-3xl font-medium tracking-tight">Aurinara</div>
          <div className="mt-1 text-[0.6875rem] font-semibold uppercase tracking-[0.18em] text-[#e8c477]">
            Clinical Data Platform
          </div>
        </div>
        <PageHeader title={title} description={description} className="relative text-center [&_h1]:text-primary-foreground [&_p]:text-primary-foreground/70" />
        <Card className="relative border-primary-foreground/15 bg-card shadow-xl">
          <CardContent className="space-y-6 pt-6">{children}</CardContent>
          {footer ? <CardFooter className="justify-center border-t pt-6">{footer}</CardFooter> : null}
        </Card>
      </div>
    </PageContainer>
  )
}
