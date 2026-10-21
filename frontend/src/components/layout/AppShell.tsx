import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '@/lib/auth'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useCTMSCapabilityState } from '@/features/ctms'
import { getCTMSWorkspaceFromPath } from '@/features/ctms/navigation'
import { getLastCTMSWorkspacePath } from '@/features/ctms/workspace-state'
import { usePVCapabilityState } from '@/features/pv'
import { getEDCLandingPath, getEDCStudyIdFromPath } from '@/features/edc'
import { getDesignerLandingPath } from '@/features/designer/navigation'
import { useStudyContext } from '@/lib/study-context'
import { resolveAppModule, useModuleStore, type AppModule } from '@/lib/module-context'
import { resolveNavigationModel } from '@/lib/navigation-model'
import { PageContainer } from '@/components/patterns/PageContainer'
import { AppHeader } from './AppHeader'
import { AppSidebar } from './AppSidebar'

/**
 * AppShell — main authenticated layout with sidebar navigation,
 * top bar, study/site selectors, and content area.
 *
 * Authentication, capability, permission, study/site, navigation, and route
 * behavior remain owned by their existing stores and adapters. This component
 * only composes those contracts into the authenticated presentation shell.
 */
export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const user = useAuthStore((s) => s.user)
  const ctmsState = useCTMSCapabilityState()
  const canReadCTMS = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)
  const pvState = usePVCapabilityState()
  const canReadPV = usePermission(PERMISSIONS.PV_SAFETY_CASE_READ)
  const { selectedStudyId, selectedSiteId } = useStudyContext()
  const setModule = useModuleStore((s) => s.setModule)
  const pathname = useLocation().pathname
  const navigate = useNavigate()

  // The URL is authoritative for the visible hierarchy, including direct
  // links and browser refreshes. The store remembers the user's last choice
  // for consumers that need it, while every module switch lands on its root.
  const activeModule = resolveAppModule(pathname)
  const ctmsWorkspace = getCTMSWorkspaceFromPath(pathname)
  const edcRouteStudyId = getEDCStudyIdFromPath(pathname)

  // Navigation is a convenience filter only; every CTMS and PV API route
  // remains server-authorized and direct navigation renders Access Denied.
  const navigationModel = resolveNavigationModel(ctmsState, pvState, user?.permissions ?? [], {
    studyId: ctmsWorkspace?.kind === 'study'
      ? ctmsWorkspace.studyId
      : activeModule === 'ctms'
        ? null
        : edcRouteStudyId ?? selectedStudyId,
    siteId: selectedSiteId,
  })
  const showCTMS = ctmsState.status === 'ready' && canReadCTMS
  const showPV = pvState.status === 'ready' && canReadPV
  const designerLandingPath = getDesignerLandingPath(user?.permissions ?? [])
  const showDesigner = designerLandingPath !== null

  const handleModuleChange = (module: AppModule) => {
    setModule(module)
    navigate({
      to: module === 'designer'
        ? (designerLandingPath ?? '/designer/forms')
        : module === 'ctms'
          ? getLastCTMSWorkspacePath()
          : module === 'pv'
            ? '/pv'
            : getEDCLandingPath(selectedStudyId),
    })
  }

  return (
    <div
      className="flex min-h-screen min-w-0 max-w-full overflow-x-hidden bg-background"
      data-testid="app-shell"
    >
      <AppSidebar
        collapsed={!sidebarOpen}
        onCollapsedChange={(collapsed) => setSidebarOpen(!collapsed)}
        edcSections={navigationModel.edcSections}
        designerSections={navigationModel.designerSections}
        ctmsSections={navigationModel.ctmsSections}
        pvSections={navigationModel.pvSections}
        showCTMS={showCTMS}
        showDesigner={showDesigner}
        showPV={showPV}
        activeModule={activeModule}
        onModuleChange={handleModuleChange}
        mobileOpen={mobileSidebarOpen}
        onMobileOpenChange={setMobileSidebarOpen}
      />

      <div className="flex min-w-0 max-w-full flex-1 flex-col overflow-hidden">
        <AppHeader
          onMobileMenuOpen={() => setMobileSidebarOpen(true)}
          onDesktopSidebarToggle={() => setSidebarOpen((open) => !open)}
          activeModule={activeModule}
          ctmsStudyId={ctmsWorkspace?.studyId}
        />

        <PageContainer
          wide
          data-testid="app-shell-content"
          className="min-h-0 flex-1 max-w-full overflow-x-auto overflow-y-auto"
        >
          <Outlet />
        </PageContainer>
      </div>
    </div>
  )
}
