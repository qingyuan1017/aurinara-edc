/* eslint-disable react-refresh/only-export-components */
import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const alertVariants = cva('relative w-full rounded-lg border p-4 text-sm [&>svg~*]:pl-7 [&>svg+div]:translate-y-[-3px] [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg]:text-foreground', {
  variants: { variant: { default: 'border-border bg-background text-foreground', destructive: 'border-destructive/50 bg-destructive/10 text-destructive dark:border-destructive [&>svg]:text-destructive', success: 'border-success/50 bg-success/10 text-foreground [&>svg]:text-success', warning: 'border-warning/50 bg-warning/10 text-foreground [&>svg]:text-warning' } },
  defaultVariants: { variant: 'default' },
})

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof alertVariants> {}
const Alert = React.forwardRef<HTMLDivElement, AlertProps>(({ className, variant, role = variant === 'destructive' ? 'alert' : 'status', ...props }, ref) => <div ref={ref} role={role} className={cn(alertVariants({ variant }), className)} {...props} />)
Alert.displayName = 'Alert'
const AlertTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(({ className, ...props }, ref) => <h5 ref={ref} className={cn('mb-1 font-medium leading-none tracking-tight', className)} {...props} />)
AlertTitle.displayName = 'AlertTitle'
const AlertDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(({ className, ...props }, ref) => <div ref={ref} className={cn('text-sm [&_p]:leading-relaxed', className)} {...props} />)
AlertDescription.displayName = 'AlertDescription'
export { Alert, AlertDescription, AlertTitle, alertVariants }
