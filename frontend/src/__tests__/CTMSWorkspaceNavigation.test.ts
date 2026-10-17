import { afterEach, describe, expect, it } from 'vitest'
import { PERMISSIONS } from '@/lib/permissions'
import { CTMS_PHASE_CAPABILITIES, normalizeCTMSCapabilities } from '@/features/ctms'
import { findCTMSNavigationMatch, getCTMSWorkspaceFromPath, resolveCTMSNavigation } from '@/features/ctms/navigation'
import {
  CTMS_WORKSPACE_STORAGE_KEYS,
  getLastCTMSWorkspacePath,
  readCTMSWorkspacePreferences,
  recordRecentStudy,
  rememberCTMSWorkspacePath,
  saveCTMSWorkspacePreferences,
} from '@/features/ctms/workspace-state'

const ready = normalizeCTMSCapabilities({
  module: 'CTMS',
  enabled: true,
  phase: 3,
  capabilities: [...CTMS_PHASE_CAPABILITIES[3]],
  platform_capabilities: { health_observability: true },
})
const permissions = Object.values(PERMISSIONS)

afterEach(() => localStorage.clear())

describe('CTMS workspace navigation architecture', () => {
  it('uses the URL as the authoritative global or study workspace context', () => {
    expect(getCTMSWorkspaceFromPath('/ctms/monitoring/visits')).toEqual({ kind: 'global' })
    expect(getCTMSWorkspaceFromPath('/studies/study%2Fone/ctms/monitoring/visits')).toEqual({ kind: 'study', studyId: 'study/one' })
    expect(getCTMSWorkspaceFromPath('/studies/study-1/dashboard')).toBeNull()
  })

  it('exposes the requested first-class module hierarchy in each workspace', () => {
    const global = resolveCTMSNavigation(ready, permissions)
    const study = resolveCTMSNavigation(ready, permissions, { studyId: 'study-1' })
    expect(global.map((section) => section.label)).toEqual([
      'Dashboard', 'Studies', 'Sites', 'Monitoring Operations', 'Contracts',
      'Financial Operations', 'Tasks & Issues', 'Entities', 'Documents', 'Reports', 'Administration',
    ])
    expect(study.map((section) => section.label)).toEqual([
      'Overview', 'Study Management', 'Sites', 'Monitoring', 'Operational Compliance', 'Contracts', 'Financials', 'Tasks & Issues', 'Documents', 'Reports',
    ])
    const globalItems = global.flatMap((section) => section.items).map((item) => item.label)
    expect(globalItems).toContain('CRA Calendar & Workload')
    expect(globalItems).toContain('Site Directory')
    expect(globalItems).toEqual(expect.arrayContaining(['Depots', 'Staff', 'Organizations', 'Investigational Products']))
    expect(globalItems).not.toContain('Entity Directory')
    expect(globalItems).not.toContain('Create Study')
    expect(globalItems).not.toContain('Investigator Directory')
    expect(globalItems).not.toContain('Organizations & Users')
    expect(globalItems).not.toContain('Contract Requests')
    expect(globalItems).not.toContain('Contract Templates')
    expect(globalItems).not.toContain('Roles & Permissions')
    expect(globalItems).not.toContain('Integrations')
    expect(globalItems).toEqual(expect.arrayContaining([
      'Overdue Visits', 'Reviews & Approvals', 'Payables & Settlement', 'Invoice Queue',
    ]))
    const deliveredPortfolioIds = new Set([
      'allMonitoringVisits', 'craCalendarWorkload', 'overdueVisits', 'crossStudyFindings',
      'allContracts', 'contractApprovals', 'expiringContracts', 'portfolioFinancialDashboard',
      'payablesSettlement', 'invoiceQueue', 'budgetFinancialReports',
      'myWork', 'studyTemplates', 'feasibilityPipeline', 'crossStudySitePerformance',
      'myTasks', 'allIssues', 'escalationsCapa', 'correctiveActionPlans',
      'craAssignments', 'capacityUtilization', 'workflowRules', 'templates',
    ])
    expect(global.flatMap((section) => section.items).filter((item) => deliveredPortfolioIds.has(item.id)).every((item) => !item.planned)).toBe(true)
    const studyItems = study.flatMap((section) => section.items).map((item) => item.label)
    expect(studyItems).toContain('Invoices & Reconciliation')
    expect(studyItems).toContain('Study Plans')
    expect(studyItems).not.toContain('Key Milestones')
    expect(studyItems).not.toContain('Milestones & Timeline')
    expect(studyItems).toEqual(expect.arrayContaining(['RACT', 'Key Risk Indicators', 'Protocol Deviations', 'ICF Rollout', 'Tracking Logs']))
    expect(studyItems).not.toContain('Sponsor Billing')
    expect(studyItems).not.toContain('Financial Forecast')
    const deliveredStudyIds = new Set([
      'recentActivity', 'studyAmendments', 'studySiteList', 'siteSelectionFeasibility',
      'siteStartupActivation', 'sitePerformance', 'siteCloseout', 'actionItems', 'capa',
      'ract', 'kri', 'protocolDeviations', 'icfRollout', 'trackingLogs',
    ])
    expect(study.flatMap((section) => section.items).filter((item) => deliveredStudyIds.has(item.id)).every((item) => !item.planned)).toBe(true)
  })

  it('matches breadcrumbs and planned pages from the same navigation source', () => {
    expect(findCTMSNavigationMatch('/ctms/contracts/approvals')?.item.label).toBe('Reviews & Approvals')
    expect(findCTMSNavigationMatch('/studies/study-1/ctms/monitoring/visits/MV-000125')?.item.label).toBe('Monitoring Visits')
  })

  it('persists the last workspace, favorites, and bounded recent studies', () => {
    rememberCTMSWorkspacePath('/studies/study-1/ctms')
    expect(getLastCTMSWorkspacePath()).toBe('/studies/study-1/ctms')
    const preferences = ['study-1', 'study-2', 'study-3', 'study-4', 'study-5', 'study-6']
      .reduce(recordRecentStudy, { favorites: ['study-2'], recents: [] })
    saveCTMSWorkspacePreferences(preferences)
    expect(readCTMSWorkspacePreferences()).toEqual({ favorites: ['study-2'], recents: ['study-6', 'study-5', 'study-4', 'study-3', 'study-2'] })
    expect(localStorage.getItem(CTMS_WORKSPACE_STORAGE_KEYS.preferences)).not.toBeNull()
  })
})
