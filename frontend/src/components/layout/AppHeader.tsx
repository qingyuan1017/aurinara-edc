import { Bell, Menu } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Breadcrumbs } from './Breadcrumbs'
import { GlobalSearch } from './GlobalSearch'
import { SiteSelector } from './SiteSelector'
import { StudySelector } from './StudySelector'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

export interface AppHeaderProps {
  displayName: string
  onSignOut: () => void | Promise<void>
  /** Opens the controlled mobile navigation Sheet without navigating. */
  onMobileMenuOpen?: () => void
}

/**
 * Authenticated header. Context selectors and account controls remain wired to
 * their existing stores/actions while presentation-only controls stay local.
 */
export function AppHeader({ displayName, onSignOut, onMobileMenuOpen }: AppHeaderProps) {
  return (
    <header
      className="flex min-h-[var(--header-height)] min-w-0 max-w-full items-center gap-2 overflow-x-hidden border-b bg-background px-3 py-2 sm:px-4"
      data-testid="app-header"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="shrink-0 md:hidden"
        onClick={onMobileMenuOpen}
        aria-label="Open navigation"
        aria-controls="mobile-navigation"
      >
        <Menu className="size-4" aria-hidden="true" />
      </Button>

      <div className="min-w-0 flex-1 overflow-hidden">
        <Breadcrumbs />
      </div>

      <div className="flex min-w-0 max-w-full flex-wrap items-center justify-end gap-1.5 sm:gap-2">
        <div className="min-w-0 max-w-[8rem] sm:max-w-[12rem] [&>select]:max-w-full">
          <StudySelector />
        </div>
        <div className="min-w-0 max-w-[8rem] sm:max-w-[12rem] [&>select]:max-w-full">
          <SiteSelector />
        </div>
        <GlobalSearch />
        <Button asChild variant="ghost" size="icon" aria-label="Notifications" title="Notifications">
          <Link to="/notifications" search={(previous) => previous}>
            <Bell className="size-4" aria-hidden="true" />
          </Link>
        </Button>
        <ThemeToggle />
        <UserMenu displayName={displayName} onSignOut={onSignOut} />
      </div>
    </header>
  )
}
