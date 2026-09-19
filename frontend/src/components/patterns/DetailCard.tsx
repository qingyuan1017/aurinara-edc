import * as React from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export interface DetailCardProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string
  description?: React.ReactNode
  status?: React.ReactNode
  ownership?: React.ReactNode
  freshness?: React.ReactNode
  footer?: React.ReactNode
}

export function DetailCard({ className, title, description, status, ownership, freshness, footer, children, ...props }: DetailCardProps) {
  return (
    <Card className={cn('min-w-0', className)} {...props}>
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="space-y-1">
            <CardTitle className="text-lg">{title}</CardTitle>
            {description ? <CardDescription>{description}</CardDescription> : null}
          </div>
          {status || ownership || freshness ? <div className="flex flex-wrap items-center gap-2">{status}{ownership}{freshness}</div> : null}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
      {footer ? <div className="flex flex-wrap items-center gap-2 border-t px-6 py-4">{footer}</div> : null}
    </Card>
  )
}
