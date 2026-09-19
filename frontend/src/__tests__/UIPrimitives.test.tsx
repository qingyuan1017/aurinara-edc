import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'

afterEach(() => document.body.innerHTML = '')

describe('core UI primitives', () => {
  it('supports semantic variants, theme tokens, asChild, and pending state', () => {
    render(<><Button variant="destructive" size="sm" loading aria-label="Save">Save</Button><Button asChild><a href="/dashboard">Dashboard</a></Button><Badge variant="success">Ready</Badge><Card><CardContent><Input aria-label="Name" /></CardContent></Card></>)
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('aria-busy', 'true')
    expect(save).toHaveClass('bg-destructive', 'focus-visible:ring-ring')
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveClass('bg-primary')
    expect(screen.getByText('Ready')).toHaveClass('bg-success/15')
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveClass('bg-background', 'focus-visible:ring-ring')
  })

  it('keeps dialog keyboard accessible and restores focus on close', async () => {
    const user = userEvent.setup()
    render(<Dialog><DialogTrigger>Open confirmation</DialogTrigger><DialogContent><DialogTitle>Confirm action</DialogTitle><DialogDescription>Review this action before continuing.</DialogDescription><button type="button">Confirm</button></DialogContent></Dialog>)
    const trigger = screen.getByRole('button', { name: 'Open confirmation' })
    await user.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Confirm action' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('opens and dismisses a sheet while returning focus to its trigger', async () => {
    const user = userEvent.setup()
    render(<Sheet><SheetTrigger>Open navigation</SheetTrigger><SheetContent><SheetTitle>Navigation</SheetTitle><button type="button">Home</button></SheetContent></Sheet>)
    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    await user.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Navigation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Home' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('supports keyboard selection and tab activation', async () => {
    const user = userEvent.setup()
    render(<><Select defaultValue="one"><SelectTrigger aria-label="Choice"><SelectValue placeholder="Choose" /></SelectTrigger><SelectContent><SelectItem value="one">One</SelectItem><SelectItem value="two">Two</SelectItem></SelectContent></Select><Tabs defaultValue="first"><TabsList><TabsTrigger value="first">First</TabsTrigger><TabsTrigger value="second">Second</TabsTrigger></TabsList><TabsContent value="first">First content</TabsContent><TabsContent value="second">Second content</TabsContent></Tabs></>)
    await user.click(screen.getByRole('combobox', { name: 'Choice' }))
    await user.click(screen.getByRole('option', { name: 'Two' }))
    expect(screen.getByRole('combobox', { name: 'Choice' })).toHaveTextContent('two')
    await user.click(screen.getByRole('tab', { name: 'Second' }))
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Second content')
  })

  it('supports menu dismissal and accessible table overflow', async () => {
    const user = userEvent.setup()
    render(<><DropdownMenu><DropdownMenuTrigger aria-label="More actions">More</DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem>Archive</DropdownMenuItem></DropdownMenuContent></DropdownMenu><Table><TableHeader><TableRow><TableHead>Record</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>Subject 001</TableCell></TableRow></TableBody></Table></>)
    await user.click(screen.getByRole('button', { name: 'More actions' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    await user.click(screen.getByRole('menuitem', { name: 'Archive' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByRole('table').parentElement).toHaveClass('overflow-x-auto')
  })

  it('exposes focus semantics for native controls', () => {
    render(<Button aria-label="Icon action" size="icon">+</Button>)
    const button = screen.getByRole('button', { name: 'Icon action' })
    fireEvent.focus(button)
    expect(button).toHaveClass('focus-visible:ring-ring')
  })
})
