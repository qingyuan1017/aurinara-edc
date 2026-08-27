import { createRouter, createRootRoute, createRoute, Outlet, useParams } from '@tanstack/react-router'
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
import { StudyDetailPage } from '@/features/studies/StudyDetailPage'
import { SubjectCasebookPage, SubjectListPage } from '@/features/subjects'
import { FormBuilderPage, FormEntryPage } from '@/features/forms'
import { QueryListPage } from '@/features/queries'
import { VisitListPage } from '@/features/visits'
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

const studyDetailRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies/$studyId',
  component: StudyDetailRoute,
})

const studyDashboardRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies/$studyId/dashboard',
  component: StudyDashboardDetailRoute,
})

const studyFormsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies/$studyId/forms',
  component: StudyFormsRoute,
})

function StudyDetailRoute() {
  const { studyId } = useParams({ from: '/authenticated/app-shell/studies/$studyId' })
  return createElement(StudyDetailPage, { studyId })
}

function StudyDashboardDetailRoute() {
  const { studyId } = useParams({ from: '/authenticated/app-shell/studies/$studyId/dashboard' })
  return createElement(StudyDashboardPage, { studyId })
}

function StudyFormsRoute() {
  const { studyId } = useParams({ from: '/authenticated/app-shell/studies/$studyId/forms' })
  return createElement(FormBuilderPage, { studyId })
}

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
  component: () => createElement(StudyScopedFormsRoute),
})

function StudyScopedFormsRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId
    ? createElement(FormBuilderPage, { studyId })
    : createElement('div', { className: 'space-y-4' },
        createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Forms'),
        createElement('p', { className: 'text-gray-600' }, 'Select a study to configure its forms.'),
      )
}

const formEntryRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/subjects/$subjectId/forms/$formInstanceId',
  component: FormEntryRoute,
})

const subjectCasebookRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/subjects/$subjectId/casebook',
  component: SubjectCasebookRoute,
})

const subjectVisitsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/subjects/$subjectId/visits',
  component: SubjectVisitsRoute,
})

function FormEntryRoute() {
  const { formInstanceId } = useParams({ from: '/authenticated/app-shell/subjects/$subjectId/forms/$formInstanceId' })
  return createElement(FormEntryPage, { formInstanceId })
}

function SubjectCasebookRoute() {
  const { subjectId } = useParams({ from: '/authenticated/app-shell/subjects/$subjectId/casebook' })
  return createElement(SubjectCasebookPage, { subjectId })
}

function SubjectVisitsRoute() {
  const { subjectId } = useParams({ from: '/authenticated/app-shell/subjects/$subjectId/visits' })
  return createElement(VisitListPage, { subjectId })
}

const queriesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/queries',
  component: () => createElement(StudyScopedQueriesRoute),
})

function StudyScopedQueriesRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId ? createElement(QueryListPage, { studyId }) : createElement('p', { className: 'text-gray-600' }, 'Select a study to view queries.')
}

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
      studyDetailRoute,
      studyDashboardRoute,
      studyFormsRoute,
      sitesRoute,
      subjectsRoute,
      subjectCasebookRoute,
      subjectVisitsRoute,
      formsRoute,
      formEntryRoute,
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
