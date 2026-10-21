import * as React from 'react'
import { cn } from '@/lib/utils'

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => <div ref={ref} data-slot="card" className={cn('flex flex-col gap-6 rounded-xl border bg-card py-6 text-card-foreground shadow-sm', className)} {...props} />)
Card.displayName = 'Card'
const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => <div ref={ref} data-slot="card-header" className={cn('grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 px-6 [.border-b]:pb-6', className)} {...props} />)
CardHeader.displayName = 'CardHeader'
const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(({ className, ...props }, ref) => <h3 ref={ref} data-slot="card-title" className={cn('font-semibold leading-none', className)} {...props} />)
CardTitle.displayName = 'CardTitle'
const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(({ className, ...props }, ref) => <p ref={ref} data-slot="card-description" className={cn('text-sm text-muted-foreground', className)} {...props} />)
CardDescription.displayName = 'CardDescription'
const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => <div ref={ref} data-slot="card-content" className={cn('px-6', className)} {...props} />)
CardContent.displayName = 'CardContent'
const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => <div ref={ref} data-slot="card-footer" className={cn('flex items-center px-6 [.border-t]:pt-6', className)} {...props} />)
CardFooter.displayName = 'CardFooter'
export { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle }
