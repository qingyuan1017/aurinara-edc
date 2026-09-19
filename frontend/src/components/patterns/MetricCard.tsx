import * as React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export interface MetricCardProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string
  value: React.ReactNode
  description?: React.ReactNode
  trend?: React.ReactNode
  icon?: React.ReactNode
  status?: React.ReactNode
  loading?: boolean
}

export function MetricCard({ className, label, value, description, trend, icon, status, loading = false, ...props }: MetricCardProps) {
  return (
    <Card className={cn('min-w-0', className)} {...props}>
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        {icon ? <span className="text-muted-foreground" aria-hidden="true">{icon}</span> : null}
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2" role="status" aria-label={`Loading ${label}`}>
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-4 w-32" />
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <p className="text-2xl font-bold tracking-tight">{value}</p>
              {trend ? <span className="text-sm text-muted-foreground">{trend}</span> : null}
            </div>
            {description ? <p className="mt-1 text-xs text-muted-foreground">{description}</p> : null}
            {status ? <div className="mt-3">{status}</div> : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}
