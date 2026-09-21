import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '@/lib/auth'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useCTMSCapabilityState } from '@/features/ctms'
import { useStudyContext } from '@/lib/study-context'
import { useModuleStore, type AppModule } from '@/lib/module-context'
import { resolveNavigationModel } from '@/lib/navigation-model'
import { PageContainer } from '@/components/patterns/PageContainer'
import { AppHeader } from './AppHeader'
import { AppSidebar } from './AppSidebar'

/**
 * AppShell — main authenticated layout with sidebar navigation,
 * top bar (user info, study/site selectors, logout), and content area.
 *
 * Authentication, capability, permission, study/site, navigation, and route
 * behavior remain owned by their existing stores and adapters. This component
 * only composes those contracts into the authenticated presentation shell.
 */
export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const ctmsState = useCTMSCapabilityState()
  const canReadCTMS = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)
  const { selectedStudyId, selectedSiteId } = useStudyContext()
  const setModule = useModuleStore((s) => s.setModule)
  const pathname = useLocation().pathname
  const navigate = useNavigate()

  // The URL is authoritative for the visible hierarchy, including direct
  // links and browser refreshes. The store remembers the user's last choice
  // for consumers that need it, while every module switch lands on its root.
  const activeModule: AppModule = pathname.includes('/ctms') ? 'ctms' : 'edc'

  // Navigation is a convenience filter only; every CTMS API route remains
  // server-authorized and direct navigation renders Access Denied.
  const navigationModel = resolveNavigationModel(ctmsState, user?.permissions ?? [], {
    studyId: selectedStudyId,
    siteId: selectedSiteId,
  })
  const showCTMS = ctmsState.status === 'ready' && canReadCTMS

  const handleLogout = async () => {
    await logout()
    navigate({ to: '/login' })
  }

  const handleModuleChange = (module: AppModule) => {
    setModule(module)
    navigate({ to: module === 'ctms' ? '/ctms' : '/' })
  }

  const displayName = user
    ? `${user.first_name} ${user.last_name}`
    : 'User'

  return (
    <div
      className="flex min-h-screen min-w-0 max-w-full overflow-x-hidden bg-background"
      data-testid="app-shell"
    >
      <AppSidebar
        collapsed={!sidebarOpen}
        onCollapsedChange={(collapsed) => setSidebarOpen(!collapsed)}
        edcSections={navigationModel.edcSections}
        ctmsSections={navigationModel.ctmsSections}
        showCTMS={showCTMS}
        activeModule={activeModule}
        onModuleChange={handleModuleChange}
        mobileOpen={mobileSidebarOpen}
        onMobileOpenChange={setMobileSidebarOpen}
      />

      <div className="flex min-w-0 max-w-full flex-1 flex-col overflow-hidden">
        <AppHeader
          displayName={displayName}
          onSignOut={handleLogout}
          onMobileMenuOpen={() => setMobileSidebarOpen(true)}
        />

        <PageContainer
          wide
          data-testid="app-shell-content"
          className="min-h-0 flex-1 max-w-full overflow-x-auto overflow-y-auto py-4 sm:py-6"
        >
          <Outlet />
        </PageContainer>
      </div>
    </div>
  )
}
