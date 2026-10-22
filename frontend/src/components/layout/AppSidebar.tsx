import { useState } from 'react'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { Bot, ChevronsUpDown, ChevronRight, Folder, LogOut, Menu, PanelsTopLeft, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import type {
  CTMSNavigationViewSection,
  DesignerNavigationViewSection,
  EDCNavigationItem,
  NavigationSection,
  PVNavigationViewSection,
} from '@/lib/navigation-model'
import type { AppModule } from '@/lib/module-context'
import { useAuthStore } from '@/lib/auth'
import { WorkspaceSwitcher } from '@/features/ctms/components/WorkspaceSwitcher'

export interface AppSidebarProps {
  /** Whether the desktop sidebar is in its compact presentation. */
  collapsed: boolean
  onCollapsedChange: (collapsed: boolean) => void
  edcSections: readonly NavigationSection[]
  designerSections: readonly DesignerNavigationViewSection[]
  ctmsSections: readonly CTMSNavigationViewSection[]
  pvSections: readonly PVNavigationViewSection[]
  /** Keeps the existing capability gate visible even when no CTMS item is resolved. */
  showCTMS: boolean
  /** Whether the signed-in user has at least one Designer permission. */
  showDesigner: boolean
  /** Keeps the PV capability gate visible even when no PV item is resolved. */
  showPV: boolean
  /** The module whose navigation hierarchy should be displayed. */
  activeModule?: AppModule
  /** Changes the active product module and lets the shell perform navigation. */
  onModuleChange?: (module: AppModule) => void
  /** Controlled state for the mobile navigation Sheet. */
  mobileOpen?: boolean
  /** Updates mobile Sheet state without changing route or search state. */
  onMobileOpenChange?: (open: boolean) => void
}

const navLinkClassName =
  'group flex h-8 w-full items-center gap-2 overflow-hidden rounded-md p-2 text-start text-sm text-sidebar-foreground outline-none ring-sidebar-ring transition-[width,height,padding] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:bg-sidebar-accent active:text-sidebar-accent-foreground disabled:pointer-events-none disabled:opacity-50 [&>span:last-child]:truncate [&>svg]:size-4 [&>svg]:shrink-0'
const activeNavLinkClassName =
  'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
const navGroupLabelClassName =
  'flex h-8 w-full shrink-0 items-center gap-2 rounded-md px-2 text-xs font-medium text-sidebar-foreground/70 outline-none transition-[margin,opacity,background-color,color] duration-[var(--duration-normal)] ease-[var(--ease-standard)] focus-visible:ring-2 focus-visible:ring-sidebar-ring'
const navMenuClassName = 'flex w-full min-w-0 flex-col gap-1'
const navSectionButtonClassName =
  'group flex h-8 w-full items-center gap-2 overflow-hidden rounded-md p-2 text-start text-sm text-sidebar-foreground outline-none ring-sidebar-ring transition-[width,height,padding] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:bg-sidebar-accent active:text-sidebar-accent-foreground [&>svg]:size-4 [&>svg]:shrink-0'

type SidebarNavigationItem =
  | EDCNavigationItem
  | DesignerNavigationViewSection['items'][number]
  | CTMSNavigationViewSection['items'][number]
  | PVNavigationViewSection['items'][number]

function sectionHeadingId(prefix: string, id: string) {
  return `${prefix}-nav-${id}`
}

function NavigationLink({
  item,
  collapsed,
  nested = false,
  activeOptions,
  onNavigate,
}: {
  item: SidebarNavigationItem
  collapsed: boolean
  nested?: boolean
  activeOptions?: { readonly exact: boolean }
  onNavigate?: () => void
}) {
  return (
    <Link
      to={item.to}
      search={item.search}
      activeOptions={activeOptions}
      onClick={onNavigate}
      activeProps={{ className: cn(navLinkClassName, activeNavLinkClassName) }}
      aria-label={item.label}
      title={collapsed ? item.label : undefined}
      className={cn(
        navLinkClassName,
        nested && !collapsed && 'h-7 px-2',
        collapsed && 'mx-auto size-8 w-8 justify-center p-2',
      )}
    >
      {(() => {
        const Icon = 'icon' in item ? item.icon : Folder
        return <Icon className="size-4 shrink-0" aria-hidden="true" />
      })()}
      <span className={cn(collapsed && 'sr-only')}>{item.label}</span>
    </Link>
  )
}

function itemMatchesPath(item: SidebarNavigationItem, pathname: string) {
  const target = item.to.split('?')[0].replace(/\/$/, '') || '/'
  const current = pathname.replace(/\/$/, '') || '/'

  if (item.activeOptions?.exact || target === '/') return current === target
  return current === target || current.startsWith(`${target}/`)
}

function NavigationSectionItem({
  prefix,
  id,
  label,
  icon: SectionIcon,
  items,
  collapsed,
  pathname,
  onNavigate,
}: {
  prefix: string
  id: string
  label: string
  icon?: LucideIcon
  items: readonly SidebarNavigationItem[]
  collapsed: boolean
  pathname: string
  onNavigate?: () => void
}) {
  const isActive = items.some((item) => itemMatchesPath(item, pathname))
  const [open, setOpen] = useState(isActive)
  const [flyoutOpen, setFlyoutOpen] = useState(false)
  const firstItem = items[0]
  const Icon = SectionIcon ?? (firstItem && 'icon' in firstItem ? firstItem.icon : Folder)

  if (collapsed) {
    return (
      <DropdownMenu open={flyoutOpen} onOpenChange={setFlyoutOpen}>
        <div className="relative">
          <DropdownMenuTrigger
            className={cn(
              navSectionButtonClassName,
              'mx-auto size-8 w-8 justify-center p-2',
              isActive && activeNavLinkClassName,
            )}
            aria-label={label}
            title={label}
          >
            <Icon className="size-4" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent className="left-[calc(100%+0.5rem)] top-0 w-64 p-1.5">
            <DropdownMenuLabel className="px-2 py-1.5 text-xs font-semibold text-muted-foreground">
              {label}
            </DropdownMenuLabel>
            <div className={navMenuClassName}>
              {items.map((item) => (
                <NavigationLink
                  key={item.id}
                  item={item}
                  collapsed={false}
                  nested
                  activeOptions={item.activeOptions}
                  onNavigate={() => {
                    setFlyoutOpen(false)
                    onNavigate?.()
                  }}
                />
              ))}
            </div>
          </DropdownMenuContent>
        </div>
      </DropdownMenu>
    )
  }

  return (
    <div data-navigation-section={`${prefix}-${id}`}>
      <button
        type="button"
        className={cn(navSectionButtonClassName, isActive && 'text-sidebar-accent-foreground')}
        aria-expanded={open}
        aria-controls={`${sectionHeadingId(prefix, id)}-items`}
        onClick={() => setOpen((current) => !current)}
      >
        <Icon className="size-4" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronRight
          className={cn('ms-auto size-4 transition-transform duration-200', open && 'rotate-90')}
          aria-hidden
        />
      </button>
      {open ? (
        <div
          id={`${sectionHeadingId(prefix, id)}-items`}
          className="mx-3.5 flex min-w-0 translate-x-px flex-col gap-1 border-s border-sidebar-border px-2.5 py-0.5"
        >
          {items.map((item) => (
            <NavigationLink
              key={item.id}
              item={item}
              collapsed={false}
              nested
              activeOptions={item.activeOptions}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

type SidebarNavigationSection = {
  readonly id: string
  readonly label: string
  readonly icon?: LucideIcon
  readonly items: readonly SidebarNavigationItem[]
}

function NavigationGroup({
  prefix,
  label,
  sections,
  collapsed,
  pathname,
  onNavigate,
}: {
  prefix: string
  label: string
  sections: readonly SidebarNavigationSection[]
  collapsed: boolean
  pathname: string
  onNavigate?: () => void
}) {
  const headingId = `${prefix}-navigation-label`

  return (
    <section aria-labelledby={headingId}>
      <div id={headingId} className={cn(navGroupLabelClassName, collapsed && '-mt-8 opacity-0')}>
        {label}
      </div>
      <div className={navMenuClassName}>
        {sections.map((section) => (
          <NavigationSectionItem
            key={section.id}
            prefix={prefix}
            id={section.id}
            label={section.label}
            icon={section.icon}
            items={section.items}
            collapsed={collapsed}
            pathname={pathname}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </section>
  )
}

function NavigationSections({
  collapsed,
  edcSections,
  designerSections,
  ctmsSections,
  pvSections,
  showCTMS,
  showDesigner,
  showPV,
  activeModule,
  onNavigate,
}: {
  collapsed: boolean
  edcSections: readonly NavigationSection[]
  designerSections: readonly DesignerNavigationViewSection[]
  ctmsSections: readonly CTMSNavigationViewSection[]
  pvSections: readonly PVNavigationViewSection[]
  showCTMS: boolean
  showDesigner: boolean
  showPV: boolean
  activeModule?: AppModule
  onNavigate?: () => void
}) {
  const pathname = useLocation().pathname

  return (
    <>
      {(activeModule === undefined || activeModule === 'edc') && (
        <NavigationGroup prefix="edc" label="EDC" sections={edcSections} collapsed={collapsed} pathname={pathname} onNavigate={onNavigate} />
      )}

      {showDesigner && (activeModule === undefined || activeModule === 'designer') && (
        <div aria-label="Designer navigation">
          <NavigationGroup prefix="designer" label="Designer" sections={designerSections} collapsed={collapsed} pathname={pathname} onNavigate={onNavigate} />
        </div>
      )}

      {showCTMS && (activeModule === undefined || activeModule === 'ctms') && (
        <div aria-label="CTMS navigation">
          <NavigationGroup prefix="ctms" label="CTMS" sections={ctmsSections} collapsed={collapsed} pathname={pathname} onNavigate={onNavigate} />
        </div>
      )}

      {showPV && (activeModule === undefined || activeModule === 'pv') && (
        <div aria-label="PV navigation">
          <NavigationGroup prefix="pv" label="PV" sections={pvSections} collapsed={collapsed} pathname={pathname} onNavigate={onNavigate} />
        </div>
      )}
    </>
  )
}

function PlaygroundLink({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <Link
      to="/playground"
      onClick={onNavigate}
      activeProps={{ className: cn(navLinkClassName, activeNavLinkClassName) }}
      inactiveProps={{ className: navLinkClassName }}
      title={collapsed ? 'Playground' : undefined}
    >
      <Bot aria-hidden />
      {collapsed ? null : <span>Playground</span>}
    </Link>
  )
}

/**
 * Presentation-only authenticated navigation. Authority and route resolution
 * remain owned by the existing navigation model and server-authorized routes.
 */
export function AppSidebar({
  collapsed,
  onCollapsedChange,
  edcSections,
  designerSections,
  ctmsSections,
  pvSections,
  showCTMS,
  showDesigner,
  showPV,
  activeModule,
  onModuleChange = () => undefined,
  mobileOpen = false,
  onMobileOpenChange = () => undefined,
}: AppSidebarProps) {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const moduleLabel = activeModule === 'designer'
    ? 'Designer'
    : activeModule === 'ctms'
      ? 'CTMS'
      : activeModule === 'pv'
        ? 'PV'
        : 'EDC'
  const displayName = user ? `${user.first_name} ${user.last_name}`.trim() || user.email : 'Account'
  const initials = displayName.slice(0, 2).toUpperCase()

  const moduleSwitcher = (mobile = false) => (
    activeModule === undefined ? null : (
      <label className={cn(
        'relative flex h-12 w-full items-center gap-2 overflow-hidden rounded-md p-2 text-start text-sm hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-within:ring-2 focus-within:ring-sidebar-ring',
        collapsed && !mobile && 'mx-auto size-8 p-0',
      )}>
        <span className="flex aspect-square size-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
          <PanelsTopLeft className="size-4" aria-hidden />
        </span>
        {collapsed && !mobile ? null : <>
          <span className="grid min-w-0 flex-1 text-start text-sm leading-tight">
            <span className="truncate font-semibold">{moduleLabel}</span>
            <span className="truncate text-xs text-muted-foreground">Clinical module</span>
          </span>
          <ChevronsUpDown className="ms-auto size-4" aria-hidden />
        </>}
        <select
          aria-label="Select module"
          value={activeModule}
          onChange={(event) => onModuleChange(event.target.value as AppModule)}
          className="absolute inset-0 size-full cursor-pointer opacity-0"
        >
          <option value="edc">EDC</option>
          <option value="designer" disabled={!showDesigner}>Designer{!showDesigner ? ' (Unavailable)' : ''}</option>
          <option value="ctms" disabled={!showCTMS}>CTMS{!showCTMS ? ' (Unavailable)' : ''}</option>
          <option value="pv" disabled={!showPV}>PV{!showPV ? ' (Unavailable)' : ''}</option>
        </select>
      </label>
    )
  )

  const sidebarUser = (compact = collapsed, mobile = false) => (
    <DropdownMenu>
      <div className="relative">
        <DropdownMenuTrigger
          aria-label={`Open user menu for ${displayName}`}
          className={cn(
            'flex h-12 w-full items-center gap-2 overflow-hidden rounded-md p-2 text-start text-sm hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring',
            compact && 'mx-auto size-8 p-0',
          )}
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-xs font-semibold text-muted-foreground">{initials}</span>
          {compact ? null : <>
            <span className="grid min-w-0 flex-1 text-start text-sm leading-tight">
              <span className="truncate font-semibold">{displayName}</span>
              <span className="truncate text-xs">{user?.email ?? 'Signed in'}</span>
            </span>
            <ChevronsUpDown className="ms-auto size-4" aria-hidden />
          </>}
        </DropdownMenuTrigger>
        <DropdownMenuContent className={cn('min-w-56 rounded-lg', mobile ? 'bottom-[calc(100%+0.25rem)] left-0' : 'bottom-0 left-[calc(100%+0.25rem)]')}>
          <DropdownMenuLabel className="font-normal"><span className="block truncate font-semibold">{displayName}</span><span className="block truncate text-xs">{user?.email ?? 'Signed in'}</span></DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => { void logout().then(() => navigate({ to: '/login' })) }}><LogOut className="size-4" />Sign out</DropdownMenuItem>
        </DropdownMenuContent>
      </div>
    </DropdownMenu>
  )

  return (
    <>
      <aside
        aria-label="Application sidebar"
        data-testid="app-sidebar"
        className={cn(
          'hidden min-h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-[var(--duration-normal)] ease-[var(--ease-standard)] md:flex',
          collapsed ? 'w-[var(--sidebar-width-collapsed)]' : 'w-[var(--sidebar-width)]',
        )}
      >
        <div className="flex shrink-0 flex-col gap-2 p-2">
          <div className={cn('flex h-12 w-full items-center gap-0 rounded-md p-2', collapsed && 'mx-auto size-8 p-0')}>
            {collapsed ? null : <span className="grid min-w-0 flex-1 text-start text-sm leading-tight"><span className="truncate font-bold">Aurinara</span></span>}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="aspect-square size-8 shrink-0"
              onClick={() => onCollapsedChange(!collapsed)}
              aria-label="Toggle Sidebar"
              title="Toggle Sidebar"
              aria-expanded={!collapsed}
              aria-controls="authenticated-navigation"
            >
              <Menu aria-hidden />
            </Button>
          </div>
          {moduleSwitcher()}
        </div>
        {activeModule === 'ctms' ? <WorkspaceSwitcher collapsed={collapsed} /> : null}

        <nav
          id="authenticated-navigation"
          aria-label="Primary navigation"
          className={cn(
            'min-w-0 flex-1 px-2 py-2',
            collapsed ? 'overflow-visible' : 'overflow-y-auto',
          )}
        >
          <NavigationSections
            collapsed={collapsed}
            edcSections={edcSections}
            designerSections={designerSections}
            ctmsSections={ctmsSections}
            pvSections={pvSections}
            showCTMS={showCTMS}
            showDesigner={showDesigner}
            showPV={showPV}
            activeModule={activeModule}
          />
          <div className="mt-3 border-t border-sidebar-border pt-3"><PlaygroundLink collapsed={collapsed} /></div>
        </nav>
        <div className="flex flex-col gap-2 p-2">{sidebarUser()}</div>
      </aside>

      <Sheet open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <SheetContent
          id="mobile-navigation"
          side="left"
          className="flex w-[min(18rem,calc(100vw-1rem))] flex-col overflow-y-auto bg-sidebar p-0 text-sidebar-foreground md:hidden"
        >
          <SheetHeader className="p-2 pr-12 text-left">
            <SheetTitle className="flex h-12 items-center p-2 text-sm font-bold text-sidebar-foreground">Aurinara</SheetTitle>
            <SheetDescription className="sr-only">Clinical {moduleLabel} authenticated workspace</SheetDescription>
          </SheetHeader>
          <div className="px-2">{moduleSwitcher(true)}</div>
          {activeModule === 'ctms' ? <WorkspaceSwitcher mobile onNavigate={() => onMobileOpenChange(false)} /> : null}
          <nav
            id="mobile-navigation-links"
            aria-label="Mobile primary navigation"
            className="min-w-0 flex-1 overflow-y-auto px-2 py-2"
          >
            <NavigationSections
              collapsed={false}
              edcSections={edcSections}
              designerSections={designerSections}
              ctmsSections={ctmsSections}
              pvSections={pvSections}
              showCTMS={showCTMS}
              showDesigner={showDesigner}
              showPV={showPV}
              activeModule={activeModule}
              onNavigate={() => onMobileOpenChange(false)}
            />
            <div className="mt-3 border-t border-sidebar-border pt-3"><PlaygroundLink collapsed={false} onNavigate={() => onMobileOpenChange(false)} /></div>
          </nav>
          <div className="flex flex-col gap-2 p-2">{sidebarUser(false, true)}</div>
        </SheetContent>
      </Sheet>
    </>
  )
}
