import * as React from 'react'
import { cn } from '@/lib/utils'

const Checkbox = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, type = 'checkbox', ...props }, ref) => <input ref={ref} type={type} className={cn('peer size-4 shrink-0 appearance-none rounded-sm border border-primary ring-offset-background checked:bg-primary checked:after:block checked:after:h-full checked:after:w-full checked:after:content-["✓"] checked:after:text-center checked:after:text-xs checked:after:font-bold checked:after:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', className)} {...props} />)
Checkbox.displayName = 'Checkbox'
export { Checkbox }
