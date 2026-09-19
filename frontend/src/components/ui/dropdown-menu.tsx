import * as React from 'react'
import { Check, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

type MenuContextValue = { open: boolean; setOpen: (open: boolean) => void }
const MenuContext = React.createContext<MenuContextValue | null>(null)
export interface DropdownMenuProps { children: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void }
const DropdownMenu = ({ children, open: controlledOpen, defaultOpen = false, onOpenChange }: DropdownMenuProps) => { const [uncontrolledOpen, setOpen] = React.useState(defaultOpen); const open = controlledOpen ?? uncontrolledOpen; const change = (next: boolean) => { setOpen(next); onOpenChange?.(next) }; return <MenuContext.Provider value={{ open, setOpen: change }}>{children}</MenuContext.Provider> }
const DropdownMenuTrigger = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(({ className, ...props }, ref) => { const context = React.useContext(MenuContext); if (!context) throw new Error('DropdownMenuTrigger must be used within DropdownMenu'); return <button ref={ref} type="button" aria-haspopup="menu" aria-expanded={context.open} className={cn('focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2', className)} onClick={() => context.setOpen(!context.open)} {...props} /> })
DropdownMenuTrigger.displayName = 'DropdownMenuTrigger'
const DropdownMenuContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => { const context = React.useContext(MenuContext); if (!context?.open) return null; return <div ref={ref} role="menu" tabIndex={-1} className={cn('absolute z-50 min-w-32 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md focus:outline-none', className)} onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); context.setOpen(false) } }} {...props} /> })
DropdownMenuContent.displayName = 'DropdownMenuContent'
export interface DropdownMenuItemProps extends React.HTMLAttributes<HTMLDivElement> { inset?: boolean; disabled?: boolean }
const DropdownMenuItem = React.forwardRef<HTMLDivElement, DropdownMenuItemProps>(({ className, inset, disabled, onClick, ...props }, ref) => { const context = React.useContext(MenuContext); return <div ref={ref} role="menuitem" tabIndex={disabled ? -1 : 0} aria-disabled={disabled || undefined} className={cn('relative flex cursor-default select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none focus:bg-accent focus:text-accent-foreground', inset && 'pl-8', disabled && 'pointer-events-none opacity-50', className)} onClick={(event) => { if (!disabled) { onClick?.(event); context?.setOpen(false) } }} onKeyDown={(event) => { if (!disabled && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onClick?.(event as unknown as React.MouseEvent<HTMLDivElement>); context?.setOpen(false) } }} {...props} /> })
DropdownMenuItem.displayName = 'DropdownMenuItem'
const DropdownMenuCheckboxItem = React.forwardRef<HTMLDivElement, DropdownMenuItemProps & { checked?: boolean; onCheckedChange?: (checked: boolean) => void }>(({ className, checked = false, onCheckedChange, children, ...props }, ref) => <DropdownMenuItem ref={ref} className={cn('pl-8', className)} onClick={() => onCheckedChange?.(!checked)} {...props}>{checked ? <Check className="absolute left-2 size-4" aria-hidden="true" /> : null}{children}</DropdownMenuItem>)
DropdownMenuCheckboxItem.displayName = 'DropdownMenuCheckboxItem'
const DropdownMenuLabel = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { inset?: boolean }>(({ className, inset, ...props }, ref) => <div ref={ref} className={cn('px-2 py-1.5 text-sm font-semibold', inset && 'pl-8', className)} {...props} />)
DropdownMenuLabel.displayName = 'DropdownMenuLabel'
const DropdownMenuSeparator = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => <div ref={ref} role="separator" className={cn('-mx-1 my-1 h-px bg-muted', className)} {...props} />)
DropdownMenuSeparator.displayName = 'DropdownMenuSeparator'
const DropdownMenuGroup = ({ ...props }: React.HTMLAttributes<HTMLDivElement>) => <div role="group" {...props} />
const DropdownMenuSub = DropdownMenu
const DropdownMenuSubTrigger = React.forwardRef<HTMLDivElement, DropdownMenuItemProps>(({ className, children, ...props }, ref) => <div ref={ref} role="menuitem" tabIndex={0} className={cn('flex cursor-default items-center rounded-sm px-2 py-1.5 text-sm outline-none focus:bg-accent', className)} {...props}>{children}<ChevronRight className="ml-auto size-4" aria-hidden="true" /></div>)
DropdownMenuSubTrigger.displayName = 'DropdownMenuSubTrigger'
const DropdownMenuSubContent = DropdownMenuContent
export { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger }
