/* eslint-disable react-refresh/only-export-components */
import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva('inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium transition-[color,box-shadow] focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50', {
  variants: { variant: { default: 'border-transparent bg-primary text-primary-foreground', secondary: 'border-transparent bg-secondary text-secondary-foreground', destructive: 'border-transparent bg-destructive text-destructive-foreground', outline: 'text-foreground', success: 'border-transparent bg-success/15 text-success', warning: 'border-transparent bg-warning/20 text-warning-foreground', info: 'border-transparent bg-info/15 text-info' } },
  defaultVariants: { variant: 'default' },
})
export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}
const Badge = React.forwardRef<HTMLDivElement, BadgeProps>(({ className, variant, ...props }, ref) => <div ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />)
Badge.displayName = 'Badge'
export { Badge, badgeVariants }
