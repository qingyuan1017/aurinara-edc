import { createRouter, createRootRoute, createRoute, Outlet, redirect, useParams } from '@tanstack/react-router'
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
import { CTMSCatalogReportPage, CTMSHomePage, CTMSPlannedWorkspacePage, CTMSPortfolioWorkspacePage, CTMSStudyAreaPage, CTMSStudyCompletionPage, CTMSWorkspacePage, EntityManagementPage, FinancialManagementPage, MonitoringModulePage, PortfolioManagementPage, PortfolioOperationsPage, ReferenceDataPage, type CTMSStudyOperationResource, type CTMSView, type MonitoringModuleView, type StudyWorkspaceView } from '@/features/ctms'
import { findCTMSReportDefinition } from '@/features/ctms/reportCatalog'
import { PVHomePage, PVWorkspacePage, type PVView } from '@/features/pv'
import { ExportCenterPage } from '@/features/exports'
import { SiteListPage } from '@/features/sites'
import { StudyDashboardPage, DataCleaningDashboardPage } from '@/features/dashboards'
import { EditCheckBuilderPage } from '@/features/edit-checks'
import { NotificationsPage } from '@/features/notifications'
import { SDVWorklistPage, ReviewWorklistPage } from '@/features/quality'
import { StudyListPage, StudyVersioningPage } from '@/features/studies'
import { StudyDetailPage } from '@/features/studies/StudyDetailPage'
import { CodelistsPage, SubjectPhasesPage, VisitsPage, ScheduleOfAssessmentPage, ArmsPage, CrfAccessPage, RawDataVariablesPage, CodingSettingsPage, FormBuilderPage } from '@/features/designer'
import { SubjectCasebookPage, SubjectListPage } from '@/features/subjects'
import { FormEntryPage } from '@/features/forms'
import { QueryListPage, QueryDetailPage } from '@/features/queries'
import { SubjectSignaturesPage } from '@/features/signatures'
import { VisitListPage } from '@/features/visits'
import { EDCWorkspacePage, type EDCWorkspaceView } from '@/features/edc'
import { RepositoryPage } from '@/features/repository/RepositoryPage'
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
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => {
    const redirect = search.redirect
    return typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')
      ? { redirect }
      : {}
  },
  component: () => createElement(LoginPage),
})

const cognitoCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/auth/callback',
  component: () => createElement(CognitoCallbackPage),
})

// Production Cognito clients already use this callback. Keep the shorter
// local-development callback above as a compatible alias.
const deployedCognitoCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/auth/cognito/callback',
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

const repositoryRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies/$studyId/edc/repository',
  component: RepositoryRoute,
})

function RepositoryRoute() {
  const { studyId } = useParams({ from: '/authenticated/app-shell/studies/$studyId/edc/repository' })
  return createElement(RepositoryPage, { studyId })
}

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

function StudyEDCWorkspaceRoute({ view }: { view: EDCWorkspaceView }) {
  const params = useParams({ strict: false })
  return createElement(EDCWorkspacePage, { studyId: String(params.studyId), view })
}

function StudyEDCSubjectRoute() {
  const params = useParams({ strict: false })
  return createElement(SubjectCasebookPage, { subjectId: String(params.subjectId), studyId: String(params.studyId) })
}

function StudyEDCSubjectVisitsRoute() {
  const params = useParams({ strict: false })
  return createElement(VisitListPage, { subjectId: String(params.subjectId) })
}

function StudyEDCFormRoute() {
  const params = useParams({ strict: false })
  return createElement(FormEntryPage, { formInstanceId: String(params.formId) })
}

function StudyEDCQueryDetailRoute() {
  const params = useParams({ strict: false })
  return createElement(QueryDetailPage, { queryId: String(params.queryId), studyId: String(params.studyId) })
}

const edcOverviewRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/overview', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'overview-dashboard' }) })
const edcCollectionProgressRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/overview/data-collection-progress', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'overview-progress' }) })
const edcOutstandingActivitiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/overview/outstanding-activities', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'overview-activities' }) })
const edcSubjectsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/subjects', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'subject-list' }) })
const edcSubjectProfileDirectoryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/subjects/profile', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'subject-profile' }) })
const edcSubjectVisitsFormsDirectoryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/subjects/visits-forms', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'subject-visits-forms' }) })
const edcSubjectRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/subjects/$subjectId', component: StudyEDCSubjectRoute })
const edcSubjectVisitsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/subjects/$subjectId/visits', component: StudyEDCSubjectVisitsRoute })
const edcFormRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/subjects/$subjectId/visits/$visitId/forms/$formId', component: StudyEDCFormRoute })
const edcDataEntryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-entry', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'data-entry' }) })
const edcIncompleteFormsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-entry/incomplete-forms', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'incomplete-forms' }) })
const edcChangeHistoryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-entry/change-history', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'change-history' }) })
const edcReviewDashboardRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-review', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'review-dashboard' }) })
const edcFormsReviewRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-review/forms', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'forms-review' }) })
const edcSDVSDRRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-review/sdv-sdr', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'sdv-sdr' }) })
const edcDataListingsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/data-review/listings', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'data-listings' }) })
const edcQueriesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/queries', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'query-dashboard' }) })
const edcOpenQueriesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/queries/open', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'open-queries' }) })
const edcQueryHistoryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/queries/history', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'query-history' }) })
const edcQueryDetailRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/queries/$queryId', component: StudyEDCQueryDetailRoute })
const edcCodingDashboardRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/medical-coding', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'coding-dashboard' }) })
const edcMedDRARoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/medical-coding/meddra', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'meddra-coding' }) })
const edcWHODrugRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/medical-coding/whodrug', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'whodrug-coding' }) })
const edcCodingReviewRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/medical-coding/review', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'coding-review' }) })
const edcExportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/exports', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'dataset-exports' }) })
const edcExportHistoryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/exports/history', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'export-history' }) })
const edcLockReadinessRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/database-lock', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'lock-readiness' }) })
const edcDataFreezeRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/database-lock/freeze', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'data-freeze' }) })
const edcDatabaseLockRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/database-lock/manage', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'database-lock' }) })
const edcLockHistoryRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/edc/database-lock/history', component: () => createElement(StudyEDCWorkspaceRoute, { view: 'lock-history' }) })

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
const ctmsSitesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/sites', component: () => createElement(EntityManagementPage, { view: 'site-directory' }) })
const ctmsEntitiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/entities', component: () => createElement(EntityManagementPage, { view: 'entity-directory' }) })
const ctmsDepotsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/entities/depots', component: () => createElement(EntityManagementPage, { view: 'entity-directory', entityType: 'depot' }) })
const ctmsStaffRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/entities/staff', component: () => createElement(EntityManagementPage, { view: 'entity-directory', entityType: 'staff' }) })
const ctmsOrganizationsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/entities/organizations', component: () => createElement(EntityManagementPage, { view: 'entity-directory', entityType: 'participating_organization' }) })
const ctmsInvestigationalProductsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/entities/investigational-products', component: () => createElement(EntityManagementPage, { view: 'entity-directory', entityType: 'investigational_product' }) })
const ctmsReferencesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/references', component: () => createElement(ReferenceDataPage) })
const ctmsPortfolioStudiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/studies', component: () => createElement(CTMSPortfolioWorkspacePage, { portfolioOnly: true }) })
const ctmsAlertsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/alerts', component: () => createElement(NotificationsPage, { module: 'CTMS' }) })
const ctmsPortfolioWorkRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/work', component: () => createElement(PortfolioManagementPage, { view: 'work' }) })
const ctmsStudyTemplatesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/studies/templates', component: () => createElement(PortfolioManagementPage, { view: 'templates' }) })
const ctmsFeasibilityRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/sites/feasibility', component: () => createElement(PortfolioManagementPage, { view: 'feasibility' }) })
const ctmsSitePerformanceRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/sites/performance', component: () => createElement(PortfolioManagementPage, { view: 'performance' }) })
const ctmsPortfolioTasksRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/tasks', component: () => createElement(PortfolioManagementPage, { view: 'tasks' }) })
const ctmsPortfolioIssuesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/issues', component: () => createElement(PortfolioManagementPage, { view: 'issues' }) })
const ctmsPortfolioEscalationsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/issues/escalations', component: () => createElement(PortfolioManagementPage, { view: 'escalations' }) })
const ctmsPortfolioCapasRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/issues/capa', component: () => createElement(PortfolioManagementPage, { view: 'capas' }) })
const ctmsCraAssignmentsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/resources/cra-assignments', component: () => createElement(PortfolioManagementPage, { view: 'assignments' }) })
const ctmsCapacityRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/resources/capacity', component: () => createElement(PortfolioManagementPage, { view: 'capacity' }) })
const ctmsWorkflowRulesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/admin/workflows', component: () => createElement(PortfolioManagementPage, { view: 'workflows' }) })
const ctmsAdminTemplatesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/admin/templates', component: () => createElement(PortfolioManagementPage, { view: 'templates', admin: true }) })
const ctmsPortfolioMonitoringVisitsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/monitoring/visits', component: () => createElement(PortfolioOperationsPage, { view: 'monitoring-visits' }) })
const ctmsPortfolioMonitoringCalendarRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/monitoring/calendar', component: () => createElement(PortfolioOperationsPage, { view: 'monitoring-calendar' }) })
const ctmsPortfolioMonitoringOverdueRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/monitoring/overdue', component: () => createElement(PortfolioOperationsPage, { view: 'monitoring-overdue' }) })
const ctmsPortfolioMonitoringFindingsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/monitoring/findings', component: () => createElement(PortfolioOperationsPage, { view: 'monitoring-findings' }) })
const ctmsPortfolioContractsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/contracts', component: () => createElement(PortfolioOperationsPage, { view: 'contracts' }) })
const ctmsPortfolioContractApprovalsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/contracts/approvals', component: () => createElement(PortfolioOperationsPage, { view: 'contract-approvals' }) })
const ctmsPortfolioContractExpiringRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/contracts/expiring', component: () => createElement(PortfolioOperationsPage, { view: 'contract-expiring' }) })
const ctmsPortfolioFinancialsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/financials', component: () => createElement(PortfolioOperationsPage, { view: 'financial-dashboard' }) })
const ctmsPortfolioPaymentsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/financials/payments', component: () => createElement(PortfolioOperationsPage, { view: 'financial-payments' }) })
const ctmsPortfolioInvoicesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/financials/invoices', component: () => createElement(PortfolioOperationsPage, { view: 'financial-invoices' }) })
const ctmsPortfolioFinancialReportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/financials/reports', component: () => createElement(PortfolioOperationsPage, { view: 'financial-reports' }) })
const ctmsAdminEntitiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/admin/organizations-users', component: () => createElement(EntityManagementPage, { view: 'entity-directory' }) })
const ctmsAdminReferencesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/admin/reference-data', component: () => createElement(ReferenceDataPage) })
const ctmsAdminAuditRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/admin/audit-trail', component: () => createElement(AuditViewerPage) })
const ctmsGlobalPlannedRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/ctms/$', component: () => createElement(CTMSPlannedWorkspacePage) })

const ctmsStudyWorkspaceRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms', component: () => createElement(CTMSStudyCompletionRoute, { view: 'summary' }) })
const ctmsStudyDetailsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/details', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'profile' }) })
const ctmsProjectManagementRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/project-management', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'plans' }) })
const ctmsProjectMilestonesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/project-management/milestones', beforeLoad: ({ params, search }) => { throw redirect({ to: '/studies/$studyId/ctms/project-management', params: { studyId: params.studyId }, search }) } })
const ctmsMasterActivitiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/project-management/master-activities', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'plans' }) })
const ctmsFinancialOverviewRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management', component: () => createElement(CTMSFinancialRoute, { initialTab: 'overview' }) })
const ctmsContractsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management/contracts', component: () => createElement(CTMSFinancialRoute, { initialTab: 'contracts' }) })
const ctmsPricingTemplatesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management/pricing-templates', component: () => createElement(CTMSStudyAreaRoute, { resource: 'pricing_template', title: 'Pricing Template', description: 'Define reusable study pricing schedules.' }) })
const ctmsBudgetsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management/budgets', component: () => createElement(CTMSFinancialRoute, { initialTab: 'budgets' }) })
const ctmsPaymentsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management/payments', component: () => createElement(CTMSFinancialRoute, { initialTab: 'payments' }) })
const ctmsInvoicesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management/invoices', component: () => createElement(CTMSFinancialRoute, { initialTab: 'invoices' }) })
const ctmsFinancialReportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/financial-management/reports', component: () => createElement(CTMSFinancialRoute, { initialTab: 'reporting' }) })
const ctmsRactRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/rbm/ract', component: () => createElement(CTMSStudyCompletionRoute, { view: 'ract' }) })
const ctmsKriRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/rbm/kri', component: () => createElement(CTMSStudyCompletionRoute, { view: 'kris' }) })
const ctmsMonitoringOverviewRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring', component: () => createElement(CTMSMonitoringRoute, { view: 'overview' }) })
const ctmsMonitoringPlanRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/plans', component: () => createElement(CTMSMonitoringRoute, { view: 'plans' }) })
const ctmsMonitoringVisitRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/visits', component: () => createElement(CTMSMonitoringRoute, { view: 'visits' }) })
const ctmsMonitoringFindingsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/findings', component: () => createElement(CTMSMonitoringRoute, { view: 'findings' }) })
const ctmsMonitoringRiskRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/risk', component: () => createElement(CTMSMonitoringRoute, { view: 'risk' }) })
const ctmsMonitoringReportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/reports', component: () => createElement(CTMSMonitoringRoute, { view: 'reports' }) })
const ctmsMonitoringIssuesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/issues', component: () => createElement(CTMSStudyCompletionRoute, { view: 'issues' }) })
const ctmsProtocolDeviationsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/protocol-deviations', component: () => createElement(CTMSStudyCompletionRoute, { view: 'protocol-deviations' }) })
const ctmsIcfRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/icf', component: () => createElement(CTMSStudyCompletionRoute, { view: 'icf-rollouts' }) })
const ctmsTrackLogsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/track-logs', component: () => createElement(CTMSStudyCompletionRoute, { view: 'tracking-logs' }) })

const ctmsRecentActivityRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/recent-activity', component: () => createElement(CTMSStudyCompletionRoute, { view: 'activity' }) })
const ctmsTeamRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/team', component: () => createElement(CTMSStudyCompletionRoute, { view: 'team' }) })
const ctmsAmendmentsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/amendments', component: () => createElement(CTMSStudyCompletionRoute, { view: 'amendments' }) })
const ctmsStudySitesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/sites', component: () => createElement(CTMSStudyCompletionRoute, { view: 'sites' }) })
const ctmsStudyFeasibilityRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/sites/feasibility', component: () => createElement(CTMSStudyCompletionRoute, { view: 'feasibility' }) })
const ctmsStudyStartupRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/sites/startup', component: () => createElement(CTMSStudyCompletionRoute, { view: 'startup' }) })
const ctmsStudyPerformanceRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/sites/performance', component: () => createElement(CTMSStudyCompletionRoute, { view: 'performance' }) })
const ctmsStudyCloseoutRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/sites/closeout', component: () => createElement(CTMSStudyCompletionRoute, { view: 'closeout' }) })
const ctmsActionItemsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/tasks/action-items', component: () => createElement(CTMSStudyCompletionRoute, { view: 'action-items' }) })
const ctmsCapaRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/tasks/capa', component: () => createElement(CTMSStudyCompletionRoute, { view: 'capas' }) })
const ctmsEscalationsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/escalations', component: () => createElement(CTMSStudyCompletionRoute, { view: 'escalations' }) })
const ctmsMonitoringRactRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/ract', component: () => createElement(CTMSStudyCompletionRoute, { view: 'ract' }) })
const ctmsMonitoringKriRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring/kris', component: () => createElement(CTMSStudyCompletionRoute, { view: 'kris' }) })
const ctmsCompliancePdRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/compliance/protocol-deviations', component: () => createElement(CTMSStudyCompletionRoute, { view: 'protocol-deviations' }) })
const ctmsComplianceIcfRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/compliance/icf-rollout', component: () => createElement(CTMSStudyCompletionRoute, { view: 'icf-rollouts' }) })
const ctmsComplianceTrackingRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/compliance/tracking-logs', component: () => createElement(CTMSStudyCompletionRoute, { view: 'tracking-logs' }) })
const ctmsSiteAgreementsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/contracts/site-agreements', component: () => createElement(CTMSFinancialRoute, { initialTab: 'contracts' }) })
const ctmsVendorAgreementsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/contracts/vendor-agreements', component: () => createElement(CTMSFinancialRoute, { initialTab: 'contracts' }) })
const ctmsContractAmendmentsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/contracts/amendments', component: () => createElement(CTMSFinancialRoute, { initialTab: 'contracts' }) })
const ctmsPaymentTermsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/contracts/payment-terms', component: () => createElement(CTMSFinancialRoute, { initialTab: 'contracts' }) })

// Legacy CTMS paths remain registered so saved links and bookmarks keep working.
const ctmsProfileRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/profile', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'profile' }) })
const ctmsPlansRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/plans', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'plans' }) })
const ctmsEnrollmentRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/enrollment', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'enrollment' }) })
const ctmsMilestonesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/milestones', beforeLoad: ({ params, search }) => { throw redirect({ to: '/studies/$studyId/ctms/project-management', params: { studyId: params.studyId }, search }) } })
const ctmsTasksRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/tasks', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'tasks' }) })
const ctmsContactsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/contacts', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'contacts' }) })
const ctmsMonitoringPlansRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring-plans', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'monitoring-plans' }) })
const ctmsMonitoringActivitiesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/monitoring-activities', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'monitoring-activities' }) })
const ctmsProjectionsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/projections', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'projections' }) })
const ctmsFailedEventsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/coordination/failed-events', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'failed-events' }) })
const ctmsConflictsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/coordination/conflicts', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'conflicts' }) })
const ctmsCatalogReportRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/reports/$category/$report', component: () => createElement(CTMSCatalogReportRoute) })
const ctmsReportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/reports/$type', component: () => createElement(CTMSReportRoute) })
const ctmsExportsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/exports', component: () => createElement(CTMSStudyWorkspaceRoute, { view: 'exports' }) })
const ctmsHealthRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/health', component: () => createElement(CTMSStudyCompletionRoute, { view: 'health' }) })
const ctmsSiteWorkspaceRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/sites/$siteId/ctms', component: () => createElement(CTMSSiteWorkspaceRoute) })
const ctmsSiteActivationRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/sites/$siteId/ctms/activation', component: () => createElement(CTMSSiteActivationRoute) })
const ctmsStudyPlannedRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/ctms/$', component: () => createElement(CTMSPlannedWorkspacePage) })

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

function CTMSStudyCompletionRoute({ view }: { view: StudyWorkspaceView }) {
  const params = useParams({ strict: false })
  return createElement(CTMSStudyCompletionPage, { view, studyId: params.studyId })
}

function CTMSStudyAreaRoute({ title, description, resource }: { title: string; description: string; resource: CTMSStudyOperationResource }) {
  const params = useParams({ strict: false })
  return createElement(CTMSStudyAreaPage, { studyId: params.studyId, title, description, resource })
}

function CTMSFinancialRoute({ initialTab }: { initialTab: 'overview' | 'contracts' | 'budgets' | 'payments' | 'invoices' | 'reporting' }) {
  const params = useParams({ strict: false })
  return createElement(FinancialManagementPage, { studyId: params.studyId, initialTab })
}

function CTMSMonitoringRoute({ view }: { view: MonitoringModuleView }) {
  const params = useParams({ strict: false })
  return createElement(MonitoringModulePage, { studyId: params.studyId, view })
}

function CTMSReportRoute() {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view: 'reports', studyId: params.studyId, reportType: params.type })
}

function CTMSCatalogReportRoute() {
  const params = useParams({ strict: false })
  const report = findCTMSReportDefinition(params.category, params.report)
  return createElement(CTMSCatalogReportPage, {
    studyId: params.studyId,
    category: params.category,
    reportType: params.report,
    title: report?.label ?? 'Report',
    description: report?.description ?? 'The requested CTMS report is not configured.',
  })
}

function CTMSSiteWorkspaceRoute() {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view: 'site-dashboard', siteId: params.siteId })
}

function CTMSSiteActivationRoute() {
  const params = useParams({ strict: false })
  return createElement(CTMSWorkspacePage, { view: 'activation', siteId: params.siteId })
}

// Designer authoring routes — brand-new Designer resources, study-scoped and
// gated server-side by designer.* permissions. Each resolves the study's open
// draft Design_Version where the surface is version-scoped.
const designerCodelistsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/codelists', component: () => createElement(DesignerResourceRoute, { Component: CodelistsPage }) })
const designerSubjectPhasesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/subject-phases', component: () => createElement(DesignerResourceRoute, { Component: SubjectPhasesPage }) })
const designerVisitsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/visits', component: () => createElement(DesignerResourceRoute, { Component: VisitsPage }) })
const designerSoARoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/schedule-of-assessment', component: () => createElement(DesignerResourceRoute, { Component: ScheduleOfAssessmentPage }) })
const designerArmsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/arms', component: () => createElement(DesignerResourceRoute, { Component: ArmsPage }) })
const designerCrfAccessRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/crf-access', component: () => createElement(DesignerResourceRoute, { Component: CrfAccessPage }) })
const designerRawDataVariablesRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/raw-data-variables', component: () => createElement(DesignerResourceRoute, { Component: RawDataVariablesPage }) })
const designerCodingSettingsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/coding-settings', component: () => createElement(DesignerResourceRoute, { Component: CodingSettingsPage }) })
const designerVersionsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/versions', component: () => createElement(DesignerResourceRoute, { Component: StudyVersioningPage }) })
// Study-context-scoped designer routes (sidebar entry points, mirroring the
// edit-checks pattern). studyId is resolved from the active study context.
const designerCodelistsCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/codelists', component: () => createElement(DesignerResourceRoute, { Component: CodelistsPage }) })
const designerSubjectPhasesCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/subject-phases', component: () => createElement(DesignerResourceRoute, { Component: SubjectPhasesPage }) })
const designerVisitsCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/visits', component: () => createElement(DesignerResourceRoute, { Component: VisitsPage }) })
const designerSoACtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/schedule-of-assessment', component: () => createElement(DesignerResourceRoute, { Component: ScheduleOfAssessmentPage }) })
const designerArmsCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/arms', component: () => createElement(DesignerResourceRoute, { Component: ArmsPage }) })
const designerCrfAccessCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/crf-access', component: () => createElement(DesignerResourceRoute, { Component: CrfAccessPage }) })
const designerRawDataVariablesCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/raw-data-variables', component: () => createElement(DesignerResourceRoute, { Component: RawDataVariablesPage }) })
const designerCodingSettingsCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/coding-settings', component: () => createElement(DesignerResourceRoute, { Component: CodingSettingsPage }) })
const designerVersionsCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/versions', component: () => createElement(DesignerResourceRoute, { Component: StudyVersioningPage }) })
// Form Builder (CRF design) and Edit Checks (CRF design) now live under the
// Designer area, mirroring the designer resource pattern: a study-scoped route
// and a study-context-scoped sidebar entry point. The legacy /forms,
// /studies/$studyId/forms, /edit-checks, and /studies/$studyId/edit-checks
// routes are kept rendering the same pages for backward compatibility.
const designerFormsRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/forms', component: () => createElement(DesignerResourceRoute, { Component: FormBuilderPage }) })
const designerFormsCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/forms', component: () => createElement(DesignerResourceRoute, { Component: FormBuilderPage }) })
const designerEditChecksRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/studies/$studyId/designer/edit-checks', component: () => createElement(DesignerResourceRoute, { Component: EditCheckBuilderPage }) })
const designerEditChecksCtxRoute = createRoute({ getParentRoute: () => appShellLayout, path: '/designer/edit-checks', component: () => createElement(DesignerResourceRoute, { Component: EditCheckBuilderPage }) })

function DesignerResourceRoute({ Component }: { Component: (props: { studyId: string }) => ReturnType<typeof createElement> }) {
  const params = useParams({ strict: false })
  const contextStudyId = useStudyContext((state) => state.selectedStudyId)
  const studyId = params.studyId ?? contextStudyId
  return studyId
    ? createElement(Component, { studyId })
    : createElement('p', { className: 'text-muted-foreground' }, 'Select a study to author designer definitions.')
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
  deployedCognitoCallbackRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  acceptInvitationRoute,
  accessDeniedRoute,
  authenticatedLayout.addChildren([
    appShellLayout.addChildren([
      indexRoute,
      repositoryRoute,
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
      designerCodelistsRoute,
      designerSubjectPhasesRoute,
      designerVisitsRoute,
      designerSoARoute,
      designerArmsRoute,
      designerCrfAccessRoute,
      designerRawDataVariablesRoute,
      designerCodingSettingsRoute,
      designerVersionsRoute,
      designerCodelistsCtxRoute,
      designerSubjectPhasesCtxRoute,
      designerVisitsCtxRoute,
      designerSoACtxRoute,
      designerArmsCtxRoute,
      designerCrfAccessCtxRoute,
      designerRawDataVariablesCtxRoute,
      designerCodingSettingsCtxRoute,
      designerVersionsCtxRoute,
      designerFormsRoute,
      designerFormsCtxRoute,
      designerEditChecksRoute,
      designerEditChecksCtxRoute,
      sdvRoute,
      reviewRoute,
      dataCleaningRoute,
      aiAssistantRoute,
      notificationsRoute,
      exportsRoute,
      edcOverviewRoute,
      edcCollectionProgressRoute,
      edcOutstandingActivitiesRoute,
      edcSubjectsRoute,
      edcSubjectProfileDirectoryRoute,
      edcSubjectVisitsFormsDirectoryRoute,
      edcSubjectRoute,
      edcSubjectVisitsRoute,
      edcFormRoute,
      edcDataEntryRoute,
      edcIncompleteFormsRoute,
      edcChangeHistoryRoute,
      edcReviewDashboardRoute,
      edcFormsReviewRoute,
      edcSDVSDRRoute,
      edcDataListingsRoute,
      edcQueriesRoute,
      edcOpenQueriesRoute,
      edcQueryHistoryRoute,
      edcQueryDetailRoute,
      edcCodingDashboardRoute,
      edcMedDRARoute,
      edcWHODrugRoute,
      edcCodingReviewRoute,
      edcExportsRoute,
      edcExportHistoryRoute,
      edcLockReadinessRoute,
      edcDataFreezeRoute,
      edcDatabaseLockRoute,
      edcLockHistoryRoute,
      ctmsRoute,
      ctmsSitesRoute,
      ctmsEntitiesRoute,
      ctmsDepotsRoute,
      ctmsStaffRoute,
      ctmsOrganizationsRoute,
      ctmsInvestigationalProductsRoute,
      ctmsReferencesRoute,
      ctmsPortfolioStudiesRoute,
      ctmsAlertsRoute,
      ctmsPortfolioWorkRoute,
      ctmsStudyTemplatesRoute,
      ctmsFeasibilityRoute,
      ctmsSitePerformanceRoute,
      ctmsPortfolioTasksRoute,
      ctmsPortfolioIssuesRoute,
      ctmsPortfolioEscalationsRoute,
      ctmsPortfolioCapasRoute,
      ctmsCraAssignmentsRoute,
      ctmsCapacityRoute,
      ctmsWorkflowRulesRoute,
      ctmsAdminTemplatesRoute,
      ctmsPortfolioMonitoringVisitsRoute,
      ctmsPortfolioMonitoringCalendarRoute,
      ctmsPortfolioMonitoringOverdueRoute,
      ctmsPortfolioMonitoringFindingsRoute,
      ctmsPortfolioContractsRoute,
      ctmsPortfolioContractApprovalsRoute,
      ctmsPortfolioContractExpiringRoute,
      ctmsPortfolioFinancialsRoute,
      ctmsPortfolioPaymentsRoute,
      ctmsPortfolioInvoicesRoute,
      ctmsPortfolioFinancialReportsRoute,
      ctmsAdminEntitiesRoute,
      ctmsAdminReferencesRoute,
      ctmsAdminAuditRoute,
      ctmsGlobalPlannedRoute,
      ctmsStudyWorkspaceRoute,
      ctmsStudyDetailsRoute,
      ctmsProjectManagementRoute,
      ctmsProjectMilestonesRoute,
      ctmsMasterActivitiesRoute,
      ctmsFinancialOverviewRoute,
      ctmsContractsRoute,
      ctmsPricingTemplatesRoute,
      ctmsBudgetsRoute,
      ctmsPaymentsRoute,
      ctmsInvoicesRoute,
      ctmsFinancialReportsRoute,
      ctmsRactRoute,
      ctmsKriRoute,
      ctmsMonitoringOverviewRoute,
      ctmsMonitoringPlanRoute,
      ctmsMonitoringVisitRoute,
      ctmsMonitoringFindingsRoute,
      ctmsMonitoringRiskRoute,
      ctmsMonitoringReportsRoute,
      ctmsMonitoringIssuesRoute,
      ctmsProtocolDeviationsRoute,
      ctmsIcfRoute,
      ctmsTrackLogsRoute,
      ctmsRecentActivityRoute,
      ctmsTeamRoute,
      ctmsAmendmentsRoute,
      ctmsStudySitesRoute,
      ctmsStudyFeasibilityRoute,
      ctmsStudyStartupRoute,
      ctmsStudyPerformanceRoute,
      ctmsStudyCloseoutRoute,
      ctmsActionItemsRoute,
      ctmsCapaRoute,
      ctmsEscalationsRoute,
      ctmsMonitoringRactRoute,
      ctmsMonitoringKriRoute,
      ctmsCompliancePdRoute,
      ctmsComplianceIcfRoute,
      ctmsComplianceTrackingRoute,
      ctmsSiteAgreementsRoute,
      ctmsVendorAgreementsRoute,
      ctmsContractAmendmentsRoute,
      ctmsPaymentTermsRoute,
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
      ctmsCatalogReportRoute,
      ctmsReportsRoute,
      ctmsExportsRoute,
      ctmsHealthRoute,
      ctmsSiteWorkspaceRoute,
      ctmsSiteActivationRoute,
      ctmsStudyPlannedRoute,
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
