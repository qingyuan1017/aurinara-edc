import { Link } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight, Folder } from 'lucide-react'
import { Button } from '@/components/ui/button'
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
  EDCNavigationItem,
  NavigationSection,
} from '@/lib/navigation-model'

export interface AppSidebarProps {
  /** Whether the desktop sidebar is in its compact presentation. */
  collapsed: boolean
  onCollapsedChange: (collapsed: boolean) => void
  edcSections: readonly NavigationSection[]
  ctmsSections: readonly CTMSNavigationViewSection[]
  /** Keeps the existing capability gate visible even when no CTMS item is resolved. */
  showCTMS: boolean
  /** Controlled state for the mobile navigation Sheet. */
  mobileOpen?: boolean
  /** Updates mobile Sheet state without changing route or search state. */
  onMobileOpenChange?: (open: boolean) => void
}

const navLinkClassName =
  'group flex min-h-9 items-center gap-2 rounded-md px-3 py-2 text-sm text-sidebar-foreground transition-colors duration-[var(--duration-fast)] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar'
const activeNavLinkClassName =
  'bg-sidebar-accent font-medium text-sidebar-accent-foreground'

function sectionHeadingId(prefix: string, id: string) {
  return `${prefix}-nav-${id}`
}

function NavigationLink({
  item,
  collapsed,
  activeOptions,
  onNavigate,
}: {
  item: EDCNavigationItem | CTMSNavigationViewSection['items'][number]
  collapsed: boolean
  activeOptions?: { readonly exact: false }
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
      className={cn(navLinkClassName, collapsed && 'justify-center px-2')}
    >
      {(() => {
        const Icon = 'icon' in item ? item.icon : Folder
        return <Icon className="size-4 shrink-0" aria-hidden="true" />
      })()}
      <span className={cn(collapsed && 'sr-only')}>{item.label}</span>
    </Link>
  )
}

function EDCSection({
  section,
  collapsed,
  onNavigate,
}: {
  section: NavigationSection
  collapsed: boolean
  onNavigate?: () => void
}) {
  const headingId = sectionHeadingId('edc', section.id)

  return (
    <section aria-labelledby={headingId}>
      <h2
        id={headingId}
        className={cn(
          'px-3 pb-1 pt-3 text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground',
          collapsed && 'sr-only',
        )}
      >
        {section.label}
      </h2>
      <div className="space-y-0.5">
        {section.items.map((item) => (
          <NavigationLink key={item.id} item={item} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </div>
    </section>
  )
}

function CTMSSection({
  section,
  collapsed,
  onNavigate,
}: {
  section: CTMSNavigationViewSection
  collapsed: boolean
  onNavigate?: () => void
}) {
  const headingId = sectionHeadingId('ctms', section.id)

  return (
    <section aria-labelledby={headingId}>
      <h2
        id={headingId}
        className={cn(
          'px-3 pb-1 pt-3 text-[0.6875rem] font-medium text-muted-foreground',
          collapsed && 'sr-only',
        )}
      >
        {section.label}
      </h2>
      <div className="space-y-0.5">
        {section.items.map((item) => (
          <NavigationLink
            key={item.id}
            item={item}
            collapsed={collapsed}
            activeOptions={item.activeOptions}
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
  ctmsSections,
  showCTMS,
  onNavigate,
}: {
  collapsed: boolean
  edcSections: readonly NavigationSection[]
  ctmsSections: readonly CTMSNavigationViewSection[]
  showCTMS: boolean
  onNavigate?: () => void
}) {
  return (
    <>
      <div className="space-y-1">
        {edcSections.map((section) => (
          <EDCSection key={section.id} section={section} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </div>

      {showCTMS && (
        <div className="mt-3 border-t border-sidebar-border pt-1" aria-label="CTMS navigation">
          <p
            className={cn(
              'px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground',
              collapsed && 'sr-only',
            )}
          >
            CTMS
          </p>
          <div className="space-y-1">
            {ctmsSections.map((section) => (
              <CTMSSection key={section.id} section={section} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </div>
        </div>
      )}
    </>
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
  ctmsSections,
  showCTMS,
  mobileOpen = false,
  onMobileOpenChange = () => undefined,
}: AppSidebarProps) {
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
        <div className="flex h-[var(--header-height)] shrink-0 items-center justify-between border-b border-sidebar-border px-3">
          <span className={cn('truncate text-sm font-semibold', collapsed && 'sr-only')}>
            Clinical EDC
          </span>
          {collapsed && <span className="text-sm font-semibold" aria-hidden="true">EDC</span>}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0 text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            onClick={() => onCollapsedChange(!collapsed)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            aria-controls="authenticated-navigation"
          >
            {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronLeft aria-hidden="true" />}
          </Button>
        </div>

        <nav
          id="authenticated-navigation"
          aria-label="Primary navigation"
          className="min-w-0 flex-1 overflow-y-auto px-2 py-2"
        >
          <NavigationSections
            collapsed={collapsed}
            edcSections={edcSections}
            ctmsSections={ctmsSections}
            showCTMS={showCTMS}
          />
        </nav>
      </aside>

      <Sheet open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <SheetContent
          id="mobile-navigation"
          side="left"
          className="w-[min(18rem,calc(100vw-1rem))] overflow-y-auto bg-sidebar p-4 text-sidebar-foreground md:hidden"
        >
          <SheetHeader className="pr-8 text-left">
            <SheetTitle className="text-sidebar-foreground">Clinical EDC</SheetTitle>
            <SheetDescription className="text-sidebar-foreground/70">
              Navigate the authenticated workspace.
            </SheetDescription>
          </SheetHeader>
          <nav
            id="mobile-navigation-links"
            aria-label="Mobile primary navigation"
            className="min-w-0 overflow-y-auto"
          >
            <NavigationSections
              collapsed={false}
              edcSections={edcSections}
              ctmsSections={ctmsSections}
              showCTMS={showCTMS}
              onNavigate={() => onMobileOpenChange(false)}
            />
          </nav>
        </SheetContent>
      </Sheet>
    </>
  )
}
