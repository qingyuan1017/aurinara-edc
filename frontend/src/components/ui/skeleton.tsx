import * as React from 'react'
import { cn } from '@/lib/utils'

const Skeleton = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, 'aria-label': ariaLabel = 'Loading', ...props }, ref) => <div ref={ref} role="status" aria-label={ariaLabel} className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />)
Skeleton.displayName = 'Skeleton'
export { Skeleton }
