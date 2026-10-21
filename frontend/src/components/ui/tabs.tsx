import * as React from 'react'
import { cn } from '@/lib/utils'

type TabsContextValue = { value?: string; onValueChange?: (value: string) => void }
const TabsContext = React.createContext<TabsContextValue>({})
export interface TabsProps extends React.HTMLAttributes<HTMLDivElement> { value?: string; defaultValue?: string; onValueChange?: (value: string) => void }
const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(({ className, value: controlledValue, defaultValue, onValueChange, ...props }, ref) => { const [uncontrolledValue, setValue] = React.useState(defaultValue); const value = controlledValue ?? uncontrolledValue; return <TabsContext.Provider value={{ value, onValueChange: (next) => { setValue(next); onValueChange?.(next) } }}><div ref={ref} className={cn('flex flex-col gap-2', className)} {...props} /></TabsContext.Provider> })
Tabs.displayName = 'Tabs'
const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(({ className, ...props }, ref) => <div ref={ref} role="tablist" className={cn('inline-flex h-9 w-fit items-center justify-center rounded-lg bg-muted p-[3px] text-muted-foreground', className)} {...props} />)
TabsList.displayName = 'TabsList'
export interface TabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> { value: string }
const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(({ className, value: triggerValue, onClick, ...props }, ref) => { const context = React.useContext(TabsContext); const selected = context.value === triggerValue; return <button ref={ref} type="button" role="tab" aria-selected={selected} tabIndex={selected ? 0 : -1} className={cn('inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-2 py-1 text-sm font-medium transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50', selected ? 'bg-background text-foreground shadow-sm' : 'hover:bg-background/50 hover:text-foreground', className)} onClick={(event) => { context.onValueChange?.(triggerValue); onClick?.(event) }} {...props} /> })
TabsTrigger.displayName = 'TabsTrigger'
export interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> { value: string }
const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(({ className, value: contentValue, ...props }, ref) => { const context = React.useContext(TabsContext); if (context.value !== contentValue) return null; return <div ref={ref} role="tabpanel" tabIndex={0} className={cn('flex-1 outline-none', className)} {...props} /> })
TabsContent.displayName = 'TabsContent'
export { Tabs, TabsContent, TabsList, TabsTrigger }
