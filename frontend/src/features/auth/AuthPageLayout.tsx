import type { ReactNode } from 'react'
import { Activity } from 'lucide-react'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { PageContainer } from '@/components/patterns/PageContainer'

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
        <div className="relative mb-6 flex items-center justify-center gap-3 text-primary-foreground">
          <span className="flex size-9 items-center justify-center rounded-lg bg-[#e8c477] text-[#0d2e38] shadow-sm"><Activity className="size-5" aria-hidden="true" /></span>
          <div className="text-left leading-tight"><div className="font-display text-xl font-medium tracking-tight">Aurinara</div><div className="mt-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.16em] text-[#e8c477]">Clinical Data Platform</div></div>
        </div>
        <Card className="relative border-primary-foreground/15 bg-card shadow-xl">
          <CardHeader className="text-center"><CardTitle className="text-2xl">{title}</CardTitle>{description ? <CardDescription>{description}</CardDescription> : null}</CardHeader>
          <CardContent className="space-y-6">{children}</CardContent>
          {footer ? <CardFooter className="justify-center border-t pt-6">{footer}</CardFooter> : null}
        </Card>
      </div>
    </PageContainer>
  )
}
