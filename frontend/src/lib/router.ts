import { createRouter, createRootRoute, createRoute, Outlet, useParams } from '@tanstack/react-router'
import { createElement } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { AuthGuard } from '@/components/guards/AuthGuard'
import { LoginPage } from '@/features/auth/LoginPage'
import { CognitoCallbackPage } from '@/features/auth/CognitoCallbackPage'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { AcceptInvitationPage } from '@/features/auth/AcceptInvitationPage'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'
import { AuditViewerPage, UserListPage } from '@/features/admin'
import { AIAssistantPage } from '@/features/ai'
import { CTMSHomePage, CTMSWorkspacePage, type CTMSView } from '@/features/ctms'
import { PVHomePage, PVWorkspacePage, type PVView } from '@/features/pv'
import { ExportCenterPage } from '@/features/exports'
import { SiteListPage } from '@/features/sites'
import { StudyDashboardPage, DataCleaningDashboardPage } from '@/features/dashboards'
import { EditCheckBuilderPage } from '@/features/edit-checks'
import { NotificationsPage } from '@/features/notifications'
import { SDVWorklistPage, ReviewWorklistPage } from '@/features/quality'
import { StudyListPage, StudyVersioningPage } from '@/features/studies'
import { StudyDetailPage } from '@/features/studies/StudyDetailPage'
import { SubjectCasebookPage, SubjectListPage } from '@/features/subjects'
import { FormBuilderPage, FormEntryPage } from '@/features/forms'
import { QueryListPage, QueryDetailPage } from '@/features/queries'
import { SubjectSignaturesPage } from '@/features/signatures'
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

const cognitoCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/auth/callback',
  component: () => createElement(CognitoCallbackPage),
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
        createElement('h1', { className: 'text-2xl font-bold text-foreground' }, 'Dashboard'),
        createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view its dashboard.'),
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

const studyVersionsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies/$studyId/versions',
  component: StudyVersionsRoute,
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

function StudyVersionsRoute() {
  const { studyId } = useParams({ from: '/authenticated/app-shell/studies/$studyId/versions' })
  return createElement(StudyVersioningPage, { studyId })
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
    : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view sites.')
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
    : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view subjects.')
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
        createElement('h1', { className: 'text-2xl font-bold text-foreground' }, 'Forms'),
        createElement('p', { className: 'text-muted-foreground' }, 'Select a study to configure its forms.'),
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

const subjectSignaturesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/subjects/$subjectId/signatures',
  component: SubjectSignaturesRoute,
})

function SubjectSignaturesRoute() {
  const { subjectId } = useParams({ from: '/authenticated/app-shell/subjects/$subjectId/signatures' })
  return createElement(SubjectSignaturesPage, { subjectId })
}

const queriesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/queries',
  component: () => createElement(StudyScopedQueriesRoute),
})

function StudyScopedQueriesRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId ? createElement(QueryListPage, { studyId }) : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view queries.')
}

const queryDetailRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/queries/$queryId',
  component: QueryDetailRoute,
})

function QueryDetailRoute() {
  const { queryId } = useParams({ from: '/authenticated/app-shell/queries/$queryId' })
  return createElement(QueryDetailPage, { queryId })
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
    : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view exports.')
}

const editChecksRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/edit-checks',
  component: () => createElement(StudyScopedEditChecksRoute),
})

function StudyScopedEditChecksRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId ? createElement(EditCheckBuilderPage, { studyId }) : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to configure edit checks.')
}

const studyEditChecksRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies/$studyId/edit-checks',
  component: StudyEditChecksRoute,
})

function StudyEditChecksRoute() {
  const { studyId } = useParams({ from: '/authenticated/app-shell/studies/$studyId/edit-checks' })
  return createElement(EditCheckBuilderPage, { studyId })
}

const dataCleaningRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/data-cleaning',
  component: () => createElement(StudyScopedDataCleaningRoute),
})

function StudyScopedDataCleaningRoute() {
  const studyId = useStudyContext((state) => state.selectedStudyId)
  return studyId ? createElement(DataCleaningDashboardPage, { studyId }) : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view data-cleaning metrics.')
}

const sdvRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/sdv',
  component: () => createElement(StudyScopedSDVRoute),
})
function StudyScopedSDVRoute() { const studyId = useStudyContext((state) => state.selectedStudyId); return studyId ? createElement(SDVWorklistPage, { studyId }) : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view the SDV worklist.') }

const reviewRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/review',
  component: () => createElement(StudyScopedReviewRoute),
})
function StudyScopedReviewRoute() { const studyId = useStudyContext((state) => state.selectedStudyId); return studyId ? createElement(ReviewWorklistPage, { studyId }) : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to view the review worklist.') }

const aiAssistantRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/ai',
  component: () => createElement(AIAssistantPage),
})

const notificationsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/notifications',
  component: () => createElement(NotificationsPage),
})

const ctmsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/ctms',
  component: () => createElement(CTMSHomePage),
})

const ctmsStudyWorkspaceRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'overview' }) })
const ctmsProfileRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/profile', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'profile' }) })
const ctmsPlansRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/plans', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'plans' }) })
const ctmsEnrollmentRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/enrollment', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'enrollment' }) })
const ctmsMilestonesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/milestones', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'milestones' }) })
const ctmsTasksRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/tasks', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'tasks' }) })
const ctmsContactsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/contacts', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'contacts' }) })
const ctmsMonitoringPlansRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring-plans', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'monitoring-plans' }) })
const ctmsMonitoringActivitiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring-activities', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'monitoring-activities' }) })
const ctmsProjectionsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/projections', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'projections' }) })
const ctmsFailedEventsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/coordination/failed-events', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'failed-events' }) })
const ctmsConflictsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/coordination/conflicts', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'conflicts' }) })
const ctmsReportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/reports/$type', component: () => createElement(CTMSReportRoute) })
const ctmsExportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/exports', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'exports' }) })
const ctmsHealthRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/health', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'health' }) })
const ctmsSiteWorkspaceRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/sites/$siteId/ctms', component: () => createElement(CTMSSiteWorkspaceRoute) })
const ctmsSiteActivationRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/sites/$siteId/ctms/activation', component: () => createElement(CTMSSiteActivationRoute) })

// PV/Safety routes. These are additive and never alter EDC or CTMS routes.
const pvRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/pv', component: () => createElement(PVHomePage) })
const pvDashboardRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/dashboard', component: () => createElement(PVStudyRoute, { view: 'dashboard' }) })
const pvCasesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/cases', component: () => createElement(PVStudyRoute, { view: 'cases' }) })
const pvCaseDetailRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/cases/$caseId', component: () => createElement(PVCaseRoute, { view: 'case-detail' }) })
const pvCaseAssessmentsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/cases/$caseId/assessments', component: () => createElement(PVCaseRoute, { view: 'assessments' }) })
const pvCaseCodingRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/cases/$caseId/coding', component: () => createElement(PVCaseRoute, { view: 'coding' }) })
const pvCaseNarrativesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/cases/$caseId/narratives', component: () => createElement(PVCaseRoute, { view: 'narratives' }) })
const pvCaseReportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/cases/$caseId/reports', component: () => createElement(PVCaseRoute, { view: 'reports' }) })
const pvReconciliationRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/reconciliation', component: () => createElement(PVStudyRoute, { view: 'reconciliation' }) })
const pvExportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/exports', component: () => createElement(PVStudyRoute, { view: 'exports' }) })
const pvAuditRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/pv/audit', component: () => createElement(PVStudyRoute, { view: 'audit' }) })
const pvSiteDashboardRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/sites/$siteId/pv/dashboard', component: () => createElement(PVSiteRoute) })

function PVStudyRoute({ view }: { view: PVView }) {
  const params = useParams({ strict: false })
  return createElement(PVWorkspacePage, { view, studyId: params.studyId })
}

function PVCaseRoute({ view }: { view: PVView }) {
  const params = useParams({ strict: false })
  return createElement(PVWorkspacePage, { view, studyId: params.studyId, caseId: params.caseId })
}

function PVSiteRoute() {
  const params = useParams({ strict: false })
  return createElement(PVWorkspacePage, { view: 'site-dashboard', siteId: params.siteId })
}

function CTMSStudyWorkspaceRoute({ view }: { view: CTMSView }) {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view, studyId: params.studyId })
}

function CTMSReportRoute() {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view: 'reports', studyId: params.studyId, reportType: params.type })
}

function CTMSSiteWorkspaceRoute() {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view: 'site-dashboard', siteId: params.siteId })
}

function CTMSSiteActivationRoute() {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view: 'activation', siteId: params.siteId })
}

const adminRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/admin',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-foreground' }, 'Admin'),
    createElement(UserListPage),
  ),
})

const auditRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/audit',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-foreground' }, 'Audit Trail'),
    createElement(AuditViewerPage),
  ),
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  cognitoCallbackRoute,
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
      studyVersionsRoute,
      sitesRoute,
      subjectsRoute,
      subjectCasebookRoute,
      subjectVisitsRoute,
      subjectSignaturesRoute,
      formsRoute,
      formEntryRoute,
      queriesRoute,
      queryDetailRoute,
      editChecksRoute,
      studyEditChecksRoute,
      sdvRoute,
      reviewRoute,
      dataCleaningRoute,
      aiAssistantRoute,
      notificationsRoute,
      exportsRoute,
      ctmsRoute,
      ctmsStudyWorkspaceRoute,
      ctmsProfileRoute,
      ctmsPlansRoute,
      ctmsEnrollmentRoute,
      ctmsMilestonesRoute,
      ctmsTasksRoute,
      ctmsContactsRoute,
      ctmsMonitoringPlansRoute,
      ctmsMonitoringActivitiesRoute,
      ctmsProjectionsRoute,
      ctmsFailedEventsRoute,
      ctmsConflictsRoute,
      ctmsReportsRoute,
      ctmsExportsRoute,
      ctmsHealthRoute,
      ctmsSiteWorkspaceRoute,
      ctmsSiteActivationRoute,
      pvRoute,
      pvDashboardRoute,
      pvCasesRoute,
      pvCaseDetailRoute,
      pvCaseAssessmentsRoute,
      pvCaseCodingRoute,
      pvCaseNarrativesRoute,
      pvCaseReportsRoute,
      pvReconciliationRoute,
      pvExportsRoute,
      pvAuditRoute,
      pvSiteDashboardRoute,
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
