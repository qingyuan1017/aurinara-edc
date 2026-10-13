import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { ChevronDown, ChevronLeft, ChevronRight, Folder } from 'lucide-react'
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
  DesignerNavigationViewSection,
  EDCNavigationItem,
  NavigationSection,
  PVNavigationViewSection,
} from '@/lib/navigation-model'
import type { AppModule } from '@/lib/module-context'
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
  'group flex min-h-9 items-center gap-2 rounded-md px-3 py-2 text-sm text-sidebar-foreground transition-colors duration-[var(--duration-fast)] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar'
const activeNavLinkClassName =
  'bg-sidebar-accent font-medium text-sidebar-accent-foreground shadow-[inset_3px_0_0_var(--color-sidebar-primary)]'

function sectionHeadingId(prefix: string, id: string) {
  return `${prefix}-nav-${id}`
}

function NavigationLink({
  item,
  collapsed,
  activeOptions,
  onNavigate,
}: {
  item: EDCNavigationItem | DesignerNavigationViewSection['items'][number] | CTMSNavigationViewSection['items'][number] | PVNavigationViewSection['items'][number]
  collapsed: boolean
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
  const [expanded, setExpanded] = useState(true)
  const SectionIcon = section.icon ?? Folder

  if (collapsed) {
    const landingItem = section.items[0]
    return landingItem ? (
      <section aria-label={section.label} className="mb-1">
        <NavigationLink
          item={{ ...landingItem, label: section.label, icon: SectionIcon }}
          collapsed
          activeOptions={{ exact: false }}
          onNavigate={onNavigate}
        />
      </section>
    ) : null
  }

  return (
    <section aria-labelledby={headingId} className="mb-1">
      <h2 id={headingId}>
        <button
          type="button"
          className={cn('flex min-h-9 w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring', collapsed && 'justify-center px-2')}
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-controls={`${headingId}-items`}
        >
          <SectionIcon className="size-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate text-left">{section.label}</span>
          <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
        </button>
      </h2>
      {!collapsed && expanded ? <div id={`${headingId}-items`} className="ml-4 mt-0.5 space-y-0.5 border-l border-sidebar-border/70 pl-2">
        {section.items.map((item) => (
          <NavigationLink key={item.id} item={item} collapsed={false} activeOptions={item.activeOptions} onNavigate={onNavigate} />
        ))}
      </div> : null}
    </section>
  )
}

function CTMSSection({
  section,
  collapsed,
  onNavigate,
  onExpand,
}: {
  section: CTMSNavigationViewSection
  collapsed: boolean
  onNavigate?: () => void
  onExpand?: () => void
}) {
  const headingId = sectionHeadingId('ctms', section.id)
  const [expanded, setExpanded] = useState(true)
  const SectionIcon = section.icon

  return (
    <section aria-labelledby={headingId} className="mb-1">
      <h2 id={headingId}>
        <button
          type="button"
          className={cn('flex min-h-9 w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring', collapsed && 'justify-center px-2')}
          onClick={() => collapsed ? onExpand?.() : setExpanded((value) => !value)}
          aria-expanded={collapsed ? undefined : expanded}
          aria-controls={`${headingId}-items`}
          title={collapsed ? section.label : undefined}
        >
          <SectionIcon className="size-4 shrink-0" aria-hidden="true" />
          <span className={cn('min-w-0 flex-1 truncate text-left', collapsed && 'sr-only')}>{section.label}</span>
          {!collapsed ? <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', expanded && 'rotate-180')} aria-hidden="true" /> : null}
        </button>
      </h2>
      {!collapsed && expanded ? (
        <div id={`${headingId}-items`} className="ml-4 mt-0.5 space-y-0.5 border-l border-sidebar-border/70 pl-2">
          {section.items.map((item) => (
            <NavigationLink key={item.id} item={item} collapsed={false} activeOptions={item.activeOptions} onNavigate={onNavigate} />
          ))}
        </div>
      ) : null}
    </section>
  )
}

function DesignerSection({
  section,
  collapsed,
  onNavigate,
}: {
  section: DesignerNavigationViewSection
  collapsed: boolean
  onNavigate?: () => void
}) {
  const headingId = sectionHeadingId('designer', section.id)

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

function PVSection({
  section,
  collapsed,
  onNavigate,
}: {
  section: PVNavigationViewSection
  collapsed: boolean
  onNavigate?: () => void
}) {
  const headingId = sectionHeadingId('pv', section.id)

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
  designerSections,
  ctmsSections,
  pvSections,
  showCTMS,
  showDesigner,
  showPV,
  activeModule,
  onCollapsedChange,
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
  onCollapsedChange: (collapsed: boolean) => void
  onNavigate?: () => void
}) {
  return (
    <>
      {(activeModule === undefined || activeModule === 'edc') && (
        <div className="space-y-1">
          {edcSections.map((section) => (
            <EDCSection key={section.id} section={section} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </div>
      )}

      {showDesigner && (activeModule === undefined || activeModule === 'designer') && (
        <div className="space-y-1" aria-label="Designer navigation">
          {designerSections.map((section) => (
            <DesignerSection key={section.id} section={section} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </div>
      )}

      {showCTMS && (activeModule === undefined || activeModule === 'ctms') && (
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
              <CTMSSection key={section.id} section={section} collapsed={collapsed} onNavigate={onNavigate} onExpand={() => onCollapsedChange(false)} />
            ))}
          </div>
        </div>
      )}

      {showPV && (activeModule === undefined || activeModule === 'pv') && (
        <div className="mt-3 border-t border-sidebar-border pt-1" aria-label="PV navigation">
          <p
            className={cn(
              'px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground',
              collapsed && 'sr-only',
            )}
          >
            PV
          </p>
          <div className="space-y-1">
            {pvSections.map((section) => (
              <PVSection key={section.id} section={section} collapsed={collapsed} onNavigate={onNavigate} />
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
  const moduleLabel = activeModule === 'designer'
    ? 'Designer'
    : activeModule === 'ctms'
      ? 'CTMS'
      : activeModule === 'pv'
        ? 'PV'
        : 'EDC'

  const moduleSwitcher = (mobile = false) => (
    <div className={cn('border-b border-sidebar-border px-3 py-2', mobile && 'px-0')}>
      {activeModule === undefined ? null : collapsed && !mobile ? (
        <button
          type="button"
          className="flex min-h-9 w-full items-center justify-center rounded-md text-xs font-semibold text-sidebar-foreground hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
          onClick={() => onCollapsedChange(false)}
          aria-label={`Current module: ${moduleLabel}. Expand sidebar to switch modules`}
          title={`Current module: ${moduleLabel}. Expand sidebar to switch modules`}
        >
          {moduleLabel}
        </button>
      ) : (
        <label className="block space-y-1">
          <span className="px-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
            Module
          </span>
          <select
            aria-label="Select module"
            value={activeModule}
            onChange={(event) => onModuleChange(event.target.value as AppModule)}
            className="h-9 w-full rounded-md border border-sidebar-border bg-sidebar-accent px-2 text-sm font-medium text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
          >
            <option value="edc">EDC</option>
            <option value="designer" disabled={!showDesigner}>Designer{!showDesigner ? ' (Unavailable)' : ''}</option>
            <option value="ctms" disabled={!showCTMS}>CTMS{!showCTMS ? ' (Unavailable)' : ''}</option>
            <option value="pv" disabled={!showPV}>PV{!showPV ? ' (Unavailable)' : ''}</option>
          </select>
        </label>
      )}
    </div>
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
        <div className="flex h-[var(--header-height)] shrink-0 items-center justify-between border-b border-sidebar-border px-3">
          <div className={cn('min-w-0 leading-tight', collapsed && 'sr-only')}>
            <span className="block truncate font-display text-lg font-medium text-sidebar-foreground">
              Aurinara
            </span>
            <span className="block truncate text-[0.625rem] font-semibold uppercase tracking-[0.16em] text-sidebar-primary">
              Clinical {moduleLabel}
            </span>
          </div>
          {collapsed && <span className="font-display text-xl text-sidebar-primary" aria-hidden="true">A</span>}
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

        {moduleSwitcher()}
        {activeModule === 'ctms' ? <WorkspaceSwitcher collapsed={collapsed} /> : null}

        <nav
          id="authenticated-navigation"
          aria-label="Primary navigation"
          className="min-w-0 flex-1 overflow-y-auto px-2 py-2"
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
            onCollapsedChange={onCollapsedChange}
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
            <SheetTitle className="font-display text-xl text-sidebar-foreground">Aurinara</SheetTitle>
            <SheetDescription className="text-sidebar-foreground/70">
              Clinical {moduleLabel} · authenticated workspace
            </SheetDescription>
          </SheetHeader>
          {moduleSwitcher(true)}
          {activeModule === 'ctms' ? <WorkspaceSwitcher mobile onNavigate={() => onMobileOpenChange(false)} /> : null}
          <nav
            id="mobile-navigation-links"
            aria-label="Mobile primary navigation"
            className="min-w-0 overflow-y-auto"
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
              onCollapsedChange={onCollapsedChange}
              onNavigate={() => onMobileOpenChange(false)}
            />
          </nav>
        </SheetContent>
      </Sheet>
    </>
  )
}
