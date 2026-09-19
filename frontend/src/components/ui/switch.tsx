import * as React from 'react'
import { cn } from '@/lib/utils'

const Switch = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, type = 'checkbox', role = 'switch', ...props }, ref) => <input ref={ref} type={type} role={role} className={cn('peer inline-flex h-6 w-11 shrink-0 cursor-pointer appearance-none rounded-full border-2 border-transparent bg-muted transition-colors checked:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', className)} {...props} />)
Switch.displayName = 'Switch'
export { Switch }
