import * as React from 'react'
import { ChevronRight, MoreHorizontal } from 'lucide-react'
import { cn } from '@/lib/utils'

const Breadcrumb = React.forwardRef<HTMLElement, React.HTMLAttributes<HTMLElement>>(({ className, ...props }, ref) => <nav ref={ref} aria-label="Breadcrumb" className={cn('', className)} {...props} />)
Breadcrumb.displayName = 'Breadcrumb'
const BreadcrumbList = React.forwardRef<HTMLOListElement, React.OlHTMLAttributes<HTMLOListElement>>(({ className, ...props }, ref) => <ol ref={ref} className={cn('flex flex-wrap items-center gap-1.5 break-words text-sm text-muted-foreground sm:gap-2.5', className)} {...props} />)
BreadcrumbList.displayName = 'BreadcrumbList'
const BreadcrumbItem = React.forwardRef<HTMLLIElement, React.LiHTMLAttributes<HTMLLIElement>>(({ className, ...props }, ref) => <li ref={ref} className={cn('inline-flex items-center gap-1.5', className)} {...props} />)
BreadcrumbItem.displayName = 'BreadcrumbItem'
const BreadcrumbLink = React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(({ className, ...props }, ref) => <a ref={ref} className={cn('transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2', className)} {...props} />)
BreadcrumbLink.displayName = 'BreadcrumbLink'
const BreadcrumbPage = React.forwardRef<HTMLSpanElement, React.HTMLAttributes<HTMLSpanElement>>(({ className, ...props }, ref) => <span ref={ref} role="link" aria-current="page" className={cn('font-normal text-foreground', className)} {...props} />)
BreadcrumbPage.displayName = 'BreadcrumbPage'
const BreadcrumbSeparator = ({ children, className, ...props }: React.HTMLAttributes<HTMLLIElement>) => <li role="presentation" aria-hidden="true" className={cn('[&>svg]:size-3.5', className)} {...props}>{children ?? <ChevronRight />}</li>
const BreadcrumbEllipsis = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) => <span role="presentation" aria-hidden="true" className={cn('flex size-9 items-center justify-center', className)} {...props}><MoreHorizontal className="size-4" /></span>
export { Breadcrumb, BreadcrumbEllipsis, BreadcrumbItem, BreadcrumbLink, BreadcrumbPage, BreadcrumbSeparator, BreadcrumbList }
