import * as React from 'react'
import { cn } from '@/lib/utils'

const TooltipProvider = ({ children }: { children: React.ReactNode }) => <>{children}</>
type TooltipContextValue = { open: boolean; setOpen: (open: boolean) => void }
const TooltipContext = React.createContext<TooltipContextValue | null>(null)
const Tooltip = ({ children, open: controlledOpen, defaultOpen = false, onOpenChange }: { children: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void }) => { const [uncontrolledOpen, setOpen] = React.useState(defaultOpen); const open = controlledOpen ?? uncontrolledOpen; const change = (next: boolean) => { setOpen(next); onOpenChange?.(next) }; return <TooltipContext.Provider value={{ open, setOpen: change }}>{children}</TooltipContext.Provider> }
const TooltipTrigger = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(({ className, onFocus, onBlur, onMouseEnter, onMouseLeave, ...props }, ref) => { const context = React.useContext(TooltipContext); if (!context) throw new Error('TooltipTrigger must be used within Tooltip'); return <button ref={ref} type="button" className={cn('focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2', className)} onFocus={(event) => { context.setOpen(true); onFocus?.(event) }} onBlur={(event) => { context.setOpen(false); onBlur?.(event) }} onMouseEnter={(event) => { context.setOpen(true); onMouseEnter?.(event) }} onMouseLeave={(event) => { context.setOpen(false); onMouseLeave?.(event) }} {...props} /> })
TooltipTrigger.displayName = 'TooltipTrigger'
const TooltipContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => { const context = React.useContext(TooltipContext); if (!context?.open) return null; return <div ref={ref} role="tooltip" className={cn('z-50 overflow-hidden rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground animate-in fade-in-0', className)} {...props} /> })
TooltipContent.displayName = 'TooltipContent'
export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }
