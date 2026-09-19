import * as React from 'react'
import { cn } from '@/lib/utils'

export interface PageContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Keeps page content readable while allowing wide data surfaces to scroll locally. */
  wide?: boolean
}

export const PageContainer = React.forwardRef<HTMLDivElement, PageContainerProps>(
  ({ className, wide = false, ...props }, ref) => (
    <main ref={ref} className={cn('mx-auto w-full min-w-0 px-4 py-6 sm:px-6 lg:px-8', wide ? 'max-w-[var(--content-max-width)]' : 'max-w-7xl', className)} {...props} />
  ),
)
PageContainer.displayName = 'PageContainer'
