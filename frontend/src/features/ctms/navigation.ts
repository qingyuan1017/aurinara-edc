import {
  Activity, AlertTriangle, Archive, BarChart3, Bell, BookOpen, Briefcase,
  Building2, Calendar, CheckCircle2, ClipboardList, Clock, CreditCard, Database,
  DollarSign, FileText, FolderOpen, Gauge, HeartPulse, Layers, LayoutDashboard,
  ListTodo, MapPin, Radar, Receipt, ScrollText, Search,
  Settings, Shield, TrendingUp, UserRound, Users, Workflow, type LucideIcon,
} from 'lucide-react'
import { PERMISSIONS } from '@/lib/permissions'
import { CTMS_CAPABILITY_CODES, type CTMSCapabilityCode, type CTMSCapabilityState } from './capabilities'

export type CTMSWorkspaceKind = 'global' | 'study'

export interface CTMSNavigationItem {
  readonly id: string
  readonly label: string
  readonly to: string
  readonly icon: LucideIcon
  readonly group?: string
  readonly description?: string
  readonly planned?: boolean
  readonly exact?: boolean
}

export interface CTMSNavigationSection {
  readonly id: string
  readonly label: string
  readonly icon: LucideIcon
  readonly workspace: CTMSWorkspaceKind
  readonly items: readonly CTMSNavigationItem[]
}

export interface CTMSNavigationScope {
  readonly studyId?: string | null
  readonly siteId?: string | null
}

interface NavigationDefinition {
  readonly id: string
  readonly label: string
  readonly icon: LucideIcon
  readonly path: string
  readonly description: string
  readonly capability?: CTMSCapabilityCode
  readonly permission?: string
  readonly planned?: boolean
  readonly exact?: boolean
}

interface NavigationSectionDefinition {
  readonly id: string
  readonly label: string
  readonly icon: LucideIcon
  readonly workspace: CTMSWorkspaceKind
  readonly items: readonly NavigationDefinition[]
}

const C = CTMS_CAPABILITY_CODES

/** Central source for CTMS sidebar, breadcrumbs, and planned-page metadata. */
export const CTMS_NAVIGATION_DEFINITIONS: readonly NavigationSectionDefinition[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, workspace: 'global', items: [
    { id: 'portfolioOverview', label: 'Portfolio Overview', icon: LayoutDashboard, path: '', description: 'Portfolio-level study visibility and operational signals.', capability: C.operationalDashboards, exact: true },
    { id: 'myWork', label: 'My Work', icon: Briefcase, path: '/work', description: 'Assigned work from across accessible studies.', capability: C.operationalTasks },
    { id: 'alertsNotifications', label: 'Alerts & Notifications', icon: Bell, path: '/alerts', description: 'Operational alerts and notifications requiring attention.', capability: C.notifications },
  ] },
  { id: 'studies', label: 'Studies', icon: BookOpen, workspace: 'global', items: [
    { id: 'studyPortfolio', label: 'Study Portfolio', icon: BookOpen, path: '/studies', description: 'Browse and enter the workspaces for accessible studies.', capability: C.operationalStudies },
    { id: 'studyTemplates', label: 'Study Templates', icon: Layers, path: '/studies/templates', description: 'Reusable operational study setup templates.', capability: C.operationalStudies },
  ] },
  { id: 'sites', label: 'Sites', icon: Building2, workspace: 'global', items: [
    { id: 'siteDirectory', label: 'Site Directory', icon: Building2, path: '/sites', description: 'CTMS site identities across accessible studies.', capability: C.operationalSites },
    { id: 'feasibilityPipeline', label: 'Site Feasibility Pipeline', icon: Search, path: '/sites/feasibility', description: 'Cross-study feasibility and selection pipeline.', capability: C.operationalSites },
    { id: 'crossStudySitePerformance', label: 'Cross-Study Site Performance', icon: TrendingUp, path: '/sites/performance', description: 'Compare authorized operational site performance.', capability: C.advancedOperationalReports },
  ] },
  { id: 'monitoring-operations', label: 'Monitoring Operations', icon: Activity, workspace: 'global', items: [
    { id: 'allMonitoringVisits', label: 'All Monitoring Visits', icon: Activity, path: '/monitoring/visits', description: 'Cross-study monitoring visit work queue.', capability: C.monitoring },
    { id: 'craCalendarWorkload', label: 'CRA Calendar & Workload', icon: Calendar, path: '/monitoring/calendar', description: 'Visit-based CRA assignments, calendars, and workload.', capability: C.monitoring },
    { id: 'overdueVisits', label: 'Overdue Visits', icon: Clock, path: '/monitoring/overdue', description: 'Monitoring visits beyond their planned dates.', capability: C.monitoring },
    { id: 'crossStudyFindings', label: 'Cross-Study Findings', icon: AlertTriangle, path: '/monitoring/findings', description: 'Findings and follow-up across accessible studies.', capability: C.monitoring },
  ] },
  { id: 'contracts', label: 'Contracts', icon: FileText, workspace: 'global', items: [
    { id: 'allContracts', label: 'All Contracts', icon: FileText, path: '/contracts', description: 'Cross-study contract register.', capability: C.operationalStudies },
    { id: 'contractApprovals', label: 'Reviews & Approvals', icon: CheckCircle2, path: '/contracts/approvals', description: 'Contracts in review, negotiation, or awaiting execution.', capability: C.operationalStudies },
    { id: 'expiringContracts', label: 'Expiring Contracts', icon: Clock, path: '/contracts/expiring', description: 'Agreements approaching expiration.', capability: C.operationalStudies },
  ] },
  { id: 'financial-operations', label: 'Financial Operations', icon: DollarSign, workspace: 'global', items: [
    { id: 'portfolioFinancialDashboard', label: 'Portfolio Financial Dashboard', icon: BarChart3, path: '/financials', description: 'Portfolio financial position by currency.', capability: C.operationalStudies },
    { id: 'payablesSettlement', label: 'Payables & Settlement', icon: CreditCard, path: '/financials/payments', description: 'Cross-study payable approval and settlement review.', capability: C.operationalStudies },
    { id: 'invoiceQueue', label: 'Invoice Queue', icon: Receipt, path: '/financials/invoices', description: 'Cross-study invoice review queue.', capability: C.operationalStudies },
    { id: 'budgetFinancialReports', label: 'Budget & Financial Reports', icon: BarChart3, path: '/financials/reports', description: 'Portfolio budget and financial reporting.', capability: C.advancedOperationalReports },
  ] },
  { id: 'tasks-issues', label: 'Tasks & Issues', icon: ListTodo, workspace: 'global', items: [
    { id: 'myTasks', label: 'My Tasks', icon: ListTodo, path: '/tasks', description: 'Tasks assigned to the current user.', capability: C.operationalTasks },
    { id: 'allIssues', label: 'All Issues', icon: AlertTriangle, path: '/issues', description: 'Operational issues across studies.', capability: C.monitoring },
    { id: 'escalationsCapa', label: 'Escalations', icon: Shield, path: '/issues/escalations', description: 'Escalated operational tasks.', capability: C.monitoring },
    { id: 'correctiveActionPlans', label: 'Corrective Action Plans', icon: Shield, path: '/issues/capa', description: 'Root cause, actions, effectiveness, and closure.', capability: C.monitoring },
  ] },
  { id: 'entities', label: 'Entities', icon: Database, workspace: 'global', items: [
    { id: 'depots', label: 'Depots', icon: Building2, path: '/entities/depots', description: 'Manage reusable depot entities.', capability: C.operationalStudies },
    { id: 'staff', label: 'Staff', icon: Users, path: '/entities/staff', description: 'Manage operational staff entities without changing platform users.', capability: C.operationalStudies },
    { id: 'organizations', label: 'Organizations', icon: Briefcase, path: '/entities/organizations', description: 'Manage participating organizations.', capability: C.operationalStudies },
    { id: 'investigationalProducts', label: 'Investigational Products', icon: Database, path: '/entities/investigational-products', description: 'Manage investigational product entities.', capability: C.operationalStudies },
    { id: 'craAssignments', label: 'CRA Assignments', icon: UserRound, path: '/resources/cra-assignments', description: 'CRA allocation across studies and sites.', capability: C.ctmsRoles },
    { id: 'capacityUtilization', label: 'Capacity & Utilization', icon: Gauge, path: '/resources/capacity', description: 'Resource capacity and utilization.', capability: C.advancedOperationalReports },
  ] },
  { id: 'documents', label: 'Documents', icon: FolderOpen, workspace: 'global', items: [
    { id: 'documentLibrary', label: 'Document Library', icon: FolderOpen, path: '/documents', description: 'Shared operational document library.', capability: C.operationalAttachments, planned: true },
    { id: 'pendingReviews', label: 'Pending Reviews', icon: CheckCircle2, path: '/documents/reviews', description: 'Central document review queue.', capability: C.operationalAttachments, planned: true },
    { id: 'etmfFilingQueue', label: 'eTMF Filing Queue', icon: Archive, path: '/documents/etmf', description: 'Documents pending authorized eTMF filing.', capability: C.operationalAttachments, planned: true },
  ] },
  { id: 'reports', label: 'Reports', icon: BarChart3, workspace: 'global', items: [
    { id: 'portfolioReports', label: 'Portfolio Reports', icon: BarChart3, path: '/reports', description: 'Standard portfolio operational reports.', capability: C.advancedOperationalReports, planned: true },
    { id: 'crossStudyAnalytics', label: 'Cross-Study Analytics', icon: TrendingUp, path: '/reports/analytics', description: 'Cross-study operational analytics.', capability: C.advancedOperationalReports, planned: true },
    { id: 'customReports', label: 'Custom Reports', icon: Search, path: '/reports/custom', description: 'Build authorized custom operational reports.', capability: C.advancedOperationalReports, planned: true },
  ] },
  { id: 'administration', label: 'Administration', icon: Settings, workspace: 'global', items: [
    { id: 'referenceData', label: 'Reference Data', icon: Database, path: '/admin/reference-data', description: 'Controlled CTMS reference values.', capability: C.operationalStudies },
    { id: 'workflowRules', label: 'Workflow Rules', icon: Workflow, path: '/admin/workflows', description: 'Operational workflow configuration.', capability: C.operationalStudies, permission: PERMISSIONS.CTMS_TEMPLATE_RULE_MANAGEMENT },
    { id: 'templates', label: 'Templates', icon: Layers, path: '/admin/templates', description: 'Shared operational templates.', capability: C.operationalStudies, permission: PERMISSIONS.CTMS_TEMPLATE_RULE_MANAGEMENT },
    { id: 'auditTrail', label: 'Audit Trail', icon: ScrollText, path: '/admin/audit-trail', description: 'Authorized immutable operational audit history.', capability: C.sharedAudit, permission: PERMISSIONS.AUDIT_READ },
  ] },

  { id: 'overview', label: 'Overview', icon: LayoutDashboard, workspace: 'study', items: [
    { id: 'studyDashboard', label: 'Study Dashboard', icon: LayoutDashboard, path: '', description: 'Study operational dashboard and signals.', capability: C.operationalDashboards, exact: true },
    { id: 'studyHealth', label: 'Study Health', icon: HeartPulse, path: '/health', description: 'Study operational health and service readiness.', capability: C.qualificationEvidence },
    { id: 'recentActivity', label: 'Recent Activity', icon: Clock, path: '/recent-activity', description: 'Recent authorized study activity.', capability: C.sharedAudit },
  ] },
  { id: 'study-management', label: 'Study Management', icon: BookOpen, workspace: 'study', items: [
    { id: 'studyInformation', label: 'Study Information', icon: BookOpen, path: '/details', description: 'Canonical identity and operational profile.', capability: C.operationalStudies },
    { id: 'studyTeam', label: 'Study Team', icon: Users, path: '/team', description: 'Effective-dated study team assignments.', capability: C.operationalContacts },
    { id: 'studyPlans', label: 'Study Plans', icon: ClipboardList, path: '/project-management', description: 'Operational plans and master activities.', capability: C.operationalStudies },
    { id: 'studyAmendments', label: 'Study Amendments', icon: FileText, path: '/amendments', description: 'Operational amendment coordination.', capability: C.operationalStudies },
  ] },
  { id: 'sites', label: 'Sites', icon: Building2, workspace: 'study', items: [
    { id: 'studySiteList', label: 'Study Site List', icon: Building2, path: '/sites', description: 'Sites participating in this study.', capability: C.operationalSites },
    { id: 'siteSelectionFeasibility', label: 'Site Selection & Feasibility', icon: Search, path: '/sites/feasibility', description: 'Study-specific site feasibility decisions.', capability: C.operationalSites },
    { id: 'siteStartupActivation', label: 'Site Startup & Activation', icon: CheckCircle2, path: '/sites/startup', description: 'Site startup and activation work.', capability: C.operationalSites },
    { id: 'enrollment', label: 'Enrollment', icon: Users, path: '/enrollment', description: 'Operational enrollment planning and targets.', capability: C.enrollmentPlanning },
    { id: 'sitePerformance', label: 'Site Performance', icon: TrendingUp, path: '/sites/performance', description: 'Study site operational performance.', capability: C.advancedOperationalReports },
    { id: 'siteCloseout', label: 'Site Closeout', icon: Archive, path: '/sites/closeout', description: 'Site closeout readiness and work.', capability: C.operationalSites },
  ] },
  { id: 'monitoring', label: 'Monitoring', icon: Activity, workspace: 'study', items: [
    { id: 'monitoringOverview', label: 'Monitoring Overview', icon: Activity, path: '/monitoring', description: 'Study monitoring summary.', capability: C.monitoring, exact: true },
    { id: 'monitoringPlans', label: 'Monitoring Plans', icon: ClipboardList, path: '/monitoring/plans', description: 'Versioned monitoring plans.', capability: C.monitoring },
    { id: 'monitoringVisits', label: 'Monitoring Visits', icon: MapPin, path: '/monitoring/visits', description: 'Monitoring visit planning and execution.', capability: C.monitoring },
    { id: 'visitReports', label: 'Visit Reports', icon: FileText, path: '/monitoring/reports', description: 'Monitoring visit reports.', capability: C.monitoring },
    { id: 'findingsFollowUp', label: 'Findings & Follow-up', icon: AlertTriangle, path: '/monitoring/findings', description: 'Findings, actions, and follow-up.', capability: C.monitoring },
    { id: 'riskBasedMonitoring', label: 'Risk-Based Monitoring', icon: Radar, path: '/monitoring/risk', description: 'Risk-based monitoring signals.', capability: C.monitoring },
    { id: 'ract', label: 'RACT', icon: Shield, path: '/monitoring/ract', description: 'Versioned risk assessments and risk items.', capability: C.monitoring },
    { id: 'kri', label: 'Key Risk Indicators', icon: Gauge, path: '/monitoring/kris', description: 'KRI thresholds, observations, and breach history.', capability: C.monitoring },
  ] },
  { id: 'operational-compliance', label: 'Operational Compliance', icon: Shield, workspace: 'study', items: [
    { id: 'protocolDeviations', label: 'Protocol Deviations', icon: AlertTriangle, path: '/compliance/protocol-deviations', description: 'Operational follow-up from approved EDC projections.', capability: C.monitoring },
    { id: 'icfRollout', label: 'ICF Rollout', icon: FileText, path: '/compliance/icf-rollout', description: 'Site acknowledgement, training, and effective use.', capability: C.operationalStudies },
    { id: 'trackingLogs', label: 'Tracking Logs', icon: ClipboardList, path: '/compliance/tracking-logs', description: 'Controlled operational logs with revision history.', capability: C.operationalStudies },
  ] },
  { id: 'contracts', label: 'Contracts', icon: FileText, workspace: 'study', items: [
    { id: 'studyContracts', label: 'Study Contracts', icon: FileText, path: '/financial-management/contracts', description: 'Study contract register and workflows.', capability: C.operationalStudies },
    { id: 'siteAgreements', label: 'Site Agreements', icon: Building2, path: '/contracts/site-agreements', description: 'Site agreement view of the shared contract register.', capability: C.operationalStudies },
    { id: 'vendorAgreements', label: 'Vendor Agreements', icon: Briefcase, path: '/contracts/vendor-agreements', description: 'Vendor agreement view of the shared contract register.', capability: C.operationalStudies },
    { id: 'contractAmendments', label: 'Contract Amendments', icon: FileText, path: '/contracts/amendments', description: 'Contract amendments for this study.', capability: C.operationalStudies },
    { id: 'paymentTerms', label: 'Payment Terms', icon: CreditCard, path: '/contracts/payment-terms', description: 'Study contract payment terms.', capability: C.operationalStudies },
  ] },
  { id: 'financials', label: 'Financials', icon: DollarSign, workspace: 'study', items: [
    { id: 'studyFinancialOverview', label: 'Study Financial Overview', icon: BarChart3, path: '/financial-management', description: 'Study financial ledger summary.', capability: C.operationalStudies, exact: true },
    { id: 'studyBudget', label: 'Study Budget', icon: DollarSign, path: '/financial-management/budgets', description: 'Versioned study budgets.', capability: C.operationalStudies },
    { id: 'siteVendorPayments', label: 'Site & Vendor Payments', icon: CreditCard, path: '/financial-management/payments', description: 'Study payment workflows.', capability: C.operationalStudies },
    { id: 'invoicesReconciliation', label: 'Invoices & Reconciliation', icon: Receipt, path: '/financial-management/invoices', description: 'Study invoices and allocations.', capability: C.operationalStudies },
  ] },
  { id: 'tasks-issues', label: 'Tasks & Issues', icon: ListTodo, workspace: 'study', items: [
    { id: 'studyTasks', label: 'Study Tasks', icon: ListTodo, path: '/tasks', description: 'Study operational tasks.', capability: C.operationalTasks },
    { id: 'actionItems', label: 'Action Items', icon: CheckCircle2, path: '/tasks/action-items', description: 'Study monitoring and operational actions.', capability: C.monitoring },
    { id: 'issuesEscalations', label: 'Issues & Escalations', icon: AlertTriangle, path: '/monitoring/issues', description: 'Study findings and escalations.', capability: C.monitoring },
    { id: 'capa', label: 'CAPA', icon: Shield, path: '/tasks/capa', description: 'Corrective and preventive actions.', capability: C.monitoring },
  ] },
  { id: 'documents', label: 'Documents', icon: FolderOpen, workspace: 'study', items: [
    { id: 'studyDocumentLibrary', label: 'Study Document Library', icon: FolderOpen, path: '/documents', description: 'Operational documents for this study.', capability: C.operationalAttachments, planned: true },
    { id: 'documentRequests', label: 'Document Requests', icon: ClipboardList, path: '/documents/requests', description: 'Study document request workflow.', capability: C.operationalAttachments, planned: true },
    { id: 'reviewApproval', label: 'Review & Approval', icon: CheckCircle2, path: '/documents/reviews', description: 'Study document review and approval.', capability: C.operationalAttachments, planned: true },
    { id: 'etmfFiling', label: 'eTMF Filing', icon: Archive, path: '/documents/etmf', description: 'Authorized study eTMF filing workflow.', capability: C.operationalAttachments, planned: true },
  ] },
  { id: 'reports', label: 'Reports', icon: BarChart3, workspace: 'study', items: [
    { id: 'studyProgress', label: 'Study Progress', icon: TrendingUp, path: '/reports/dashboard', description: 'Study progress operational report.', capability: C.advancedOperationalReports },
    { id: 'enrollmentReports', label: 'Enrollment Reports', icon: Users, path: '/reports/enrollment', description: 'Study enrollment operational report.', capability: C.advancedOperationalReports },
    { id: 'monitoringReports', label: 'Monitoring Reports', icon: Activity, path: '/monitoring/reports', description: 'Study monitoring reports.', capability: C.monitoring },
    { id: 'financialReports', label: 'Financial Reports', icon: DollarSign, path: '/financial-management/reports', description: 'Study financial reporting.', capability: C.operationalStudies },
  ] },
] as const

function workspaceRoot(workspace: CTMSWorkspaceKind, studyId?: string | null): string | null {
  if (workspace === 'global') return '/ctms'
  return studyId ? `/studies/${encodeURIComponent(studyId)}/ctms` : null
}

function isDefinitionAvailable(definition: NavigationDefinition, state: CTMSCapabilityState, permissions: readonly string[]): boolean {
  if (definition.capability && !state.manifest.capabilities.includes(definition.capability)) return false
  if (definition.permission && !permissions.includes(definition.permission)) return false
  return true
}

export function resolveCTMSNavigation(state: CTMSCapabilityState, permissions: readonly string[], scope: CTMSNavigationScope = {}): readonly CTMSNavigationSection[] {
  if (state.status !== 'ready' || !permissions.includes(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)) return []
  const workspace: CTMSWorkspaceKind = scope.studyId ? 'study' : 'global'
  const root = workspaceRoot(workspace, scope.studyId)
  if (!root) return []
  return CTMS_NAVIGATION_DEFINITIONS.filter((section) => section.workspace === workspace).map((section) => ({
    id: section.id,
    label: section.label,
    icon: section.icon,
    workspace,
    items: section.items.filter((item) => isDefinitionAvailable(item, state, permissions)).map((item) => ({
      id: item.id, label: item.label, icon: item.icon, to: `${root}${item.path}`,
      description: item.description, planned: item.planned, exact: item.exact,
    })),
  })).filter((section) => section.items.length > 0)
}

export interface CTMSNavigationMatch {
  readonly workspace: CTMSWorkspaceKind
  readonly section: Pick<NavigationSectionDefinition, 'id' | 'label' | 'icon'>
  readonly item: NavigationDefinition
}

export function findCTMSNavigationMatch(pathname: string): CTMSNavigationMatch | null {
  const studyMatch = pathname.match(/^\/studies\/[^/]+\/ctms(?<suffix>\/.*)?$/)
  const workspace: CTMSWorkspaceKind = studyMatch ? 'study' : 'global'
  const suffix = studyMatch?.groups?.suffix ?? (pathname.startsWith('/ctms') ? pathname.slice('/ctms'.length) : '')
  if (workspace === 'global' && !pathname.startsWith('/ctms')) return null
  const sections = CTMS_NAVIGATION_DEFINITIONS.filter((section) => section.workspace === workspace)
  const candidates = sections.flatMap((section) => section.items.map((item) => ({ section, item })))
  const match = candidates.filter(({ item }) => item.path === suffix || (item.path && suffix.startsWith(`${item.path}/`))).sort((a, b) => b.item.path.length - a.item.path.length)[0] ?? candidates.find(({ item }) => item.path === '')
  return match ? { workspace, section: match.section, item: match.item } : null
}

export function getCTMSWorkspaceFromPath(pathname: string): { kind: CTMSWorkspaceKind; studyId?: string } | null {
  const match = pathname.match(/^\/studies\/([^/]+)\/ctms(?:\/|$)/)
  if (match) {
    try { return { kind: 'study', studyId: decodeURIComponent(match[1]) } }
    catch { return { kind: 'study', studyId: match[1] } }
  }
  return pathname === '/ctms' || pathname.startsWith('/ctms/') ? { kind: 'global' } : null
}
