import { createRouter, createRootRoute, createRoute, Outlet } from '@tanstack/react-router'
import { createElement } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { AuthGuard } from '@/components/guards/AuthGuard'
import { LoginPage } from '@/features/auth/LoginPage'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { AcceptInvitationPage } from '@/features/auth/AcceptInvitationPage'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { AuditViewerPage, UserListPage } from '@/features/admin'
import { ExportCenterPage } from '@/features/exports'
import { SiteListPage } from '@/features/sites'
import { StudyDashboardPage } from '@/features/dashboards'
import { StudyListPage } from '@/features/studies'
import { SubjectListPage } from '@/features/subjects'
import { useStudyContext } from './study-context'

/**
 * Root route — renders an Outlet so child routes appear.
 */
const rootRoute = createRootRoute({
  component: () => createElement(Outlet),
})

/**
 * Login route (public) — uses the real LoginPage component.
 */
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: () => createElement(LoginPage),
})

/**
 * Forgot password route (public).
 */
const forgotPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/forgot-password',
  component: () => createElement(ForgotPasswordPage),
})

/**
 * Reset password route (public).
 */
const resetPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/reset-password',
  component: () => createElement(ResetPasswordPage),
})

/**
 * Accept invitation route (public).
 */
const acceptInvitationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/accept-invitation',
  component: () => createElement(AcceptInvitationPage),
})

/**
 * Access-denied route (public, for direct navigation).
 */
const accessDeniedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/access-denied',
  component: () => createElement(AccessDeniedPage),
})

/**
 * Authenticated layout route — uses AuthGuard + AppShell.
 * All protected routes are children of this layout.
 */
const authenticatedLayout = createRoute({
  getParentRoute: () => rootRoute,
  id: 'authenticated',
  component: () => createElement(AuthGuard),
})

/**
 * App Shell layout — the visual wrapper with sidebar and top bar.
 * Nested inside AuthGuard so the shell only renders when authenticated.
 */
const appShellLayout = createRoute({
  getParentRoute: () => authenticatedLayout,
  id: 'app-shell',
  component: () => createElement(AppShell),
})

/**
 * Index (dashboard) route — landing page after login.
 */
const indexRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/',
  component: () => createElement(StudyDashboardRoute),
})

function StudyDashboardRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId
    ? createElement(StudyDashboardPage, { studyId })
    : createElement('div', { className: 'space-y-4' },
        createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Dashboard'),
        createElement('p', { className: 'text-gray-600' }, 'Select a study to view its dashboard.'),
      )
}

const studiesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies',
  component: () => createElement(StudyListPage),
})

const sitesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/sites',
  component: () => createElement(StudyScopedSitesRoute),
})

function StudyScopedSitesRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId
    ? createElement(SiteListPage, { studyId })
    : createElement('p', { className: 'text-gray-600' }, 'Select a study to view sites.')
}

const subjectsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/subjects',
  component: () => createElement(StudyScopedSubjectsRoute),
})

function StudyScopedSubjectsRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId
    ? createElement(SubjectListPage, { studyId })
    : createElement('p', { className: 'text-gray-600' }, 'Select a study to view subjects.')
}

const formsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/forms',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Forms'),
    createElement('p', { className: 'text-gray-600' }, 'Open a form instance from a subject casebook to begin data entry.'),
  ),
})

const queriesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/queries',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Queries'),
    createElement('p', { className: 'text-gray-600' }, 'Query management is not yet connected to a page.'),
  ),
})

const exportsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/exports',
  component: () => createElement(StudyScopedExportsRoute),
})

function StudyScopedExportsRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId
    ? createElement(ExportCenterPage, { studyId })
    : createElement('p', { className: 'text-gray-600' }, 'Select a study to view exports.')
}

const adminRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/admin',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Admin'),
    createElement(UserListPage),
  ),
})

const auditRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/audit',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Audit Trail'),
    createElement(AuditViewerPage),
  ),
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  acceptInvitationRoute,
  accessDeniedRoute,
  authenticatedLayout.addChildren([
    appShellLayout.addChildren([
      indexRoute,
      studiesRoute,
      sitesRoute,
      subjectsRoute,
      formsRoute,
      queriesRoute,
      exportsRoute,
      adminRoute,
      auditRoute,
    ]),
  ]),
])

export const router = createRouter({ routeTree })

// Type-safe router declaration for TanStack Router
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
