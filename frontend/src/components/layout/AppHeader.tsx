import { ArrowLeft, Bell, Menu } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Breadcrumbs } from './Breadcrumbs'
import { GlobalSearch } from './GlobalSearch'
import { SiteSelector } from './SiteSelector'
import { StudySelector } from './StudySelector'
import { ThemeToggle } from './ThemeToggle'
import type { AppModule } from '@/lib/module-context'

export interface AppHeaderProps {
  /** Opens the controlled mobile navigation Sheet without navigating. */
  onMobileMenuOpen?: () => void
  onDesktopSidebarToggle?: () => void
  activeModule?: AppModule
  ctmsStudyId?: string
}

/**
 * Authenticated header. Context selectors and account controls remain wired to
 * their existing stores/actions while presentation-only controls stay local.
 */
export function AppHeader({ onMobileMenuOpen, onDesktopSidebarToggle, activeModule, ctmsStudyId }: AppHeaderProps) {
  const isCTMS = activeModule === 'ctms'
  const workspaceLabel = activeModule === 'ctms'
    ? 'Clinical operations'
    : activeModule === 'designer'
      ? 'Clinical designer'
      : activeModule === 'pv'
        ? 'Pharmacovigilance'
        : 'Electronic data capture'
  return (
    <header
      className="sticky top-0 z-50 flex h-16 min-w-0 max-w-full shrink-0 items-center gap-3 border-b bg-background/85 p-4 backdrop-blur-xl sm:gap-4"
      data-testid="app-header"
    >
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="shrink-0 scale-125 md:hidden"
        onClick={onMobileMenuOpen}
        aria-label="Open navigation"
        aria-controls="mobile-navigation"
      >
        <Menu className="size-4" aria-hidden="true" />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="hidden shrink-0 md:inline-flex"
        onClick={onDesktopSidebarToggle}
        aria-label="Toggle navigation"
        aria-controls="authenticated-navigation"
      >
        <Menu className="size-4" aria-hidden="true" />
      </Button>
      <Separator orientation="vertical" className="h-6" />

      <div className="min-w-0 flex-1 overflow-hidden leading-tight">
        <span className="block truncate text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{workspaceLabel}</span>
        <Breadcrumbs />
      </div>

      <div className="flex shrink-0 items-center justify-end gap-2">
        {!isCTMS ? <><div className="hidden max-w-48 xl:block [&>select]:max-w-full"><StudySelector /></div><div className="hidden max-w-48 xl:block [&>select]:max-w-full"><SiteSelector /></div></> : null}
        {isCTMS && ctmsStudyId ? <Button asChild variant="ghost" size="sm" className="hidden lg:inline-flex"><Link to="/ctms"><ArrowLeft className="size-3.5" aria-hidden="true" />Portfolio</Link></Button> : null}
        <div className="hidden 2xl:block"><GlobalSearch /></div>
        <Button asChild variant="ghost" size="icon" aria-label="Notifications" title="Notifications">
          <Link to="/notifications" search={(previous) => previous}>
            <Bell className="size-4" aria-hidden="true" />
          </Link>
        </Button>
        <ThemeToggle />
      </div>
    </header>
  )
}
