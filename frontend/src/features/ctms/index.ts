/** CTMS first-party frontend feature boundary. */

export { CTMSHomePage } from './CTMSHomePage'
export { CTMSPortfolioWorkspacePage, CTMSPlannedWorkspacePage } from './PortfolioWorkspacePage'
export { PortfolioOperationsPage } from './PortfolioOperationsPage'
export type { PortfolioOperationsView } from './PortfolioOperationsPage'
export { CTMSWorkspacePage } from './WorkspacePage'
export { CTMSCatalogReportPage, CTMSStudyAreaPage } from './StudyAreaPage'
export { FinancialManagementPage } from './FinancialManagementPage'
export type { FinancialTab } from './FinancialManagementPage'
export { EntityManagementPage } from './entities'
export { ReferenceDataPage } from './reference'
export { MonitoringFindingsPage, MonitoringModulePage } from './monitoring'
export type { MonitoringModuleView } from './monitoring'
export type { CTMSView } from './WorkspacePage'
export { resolveCTMSNavigation } from './navigation'
export type { CTMSNavigationItem, CTMSNavigationSection } from './navigation'
export {
  CTMS_ACTION_ROUTE_MAP,
  CTMS_CAPABILITY_CODES,
  CTMS_DISABLED_MANIFEST,
  CTMS_PHASE_CAPABILITIES,
  CTMS_PHASE_METADATA,
  fetchCTMSCapabilities,
  isCTMSActionAvailable,
  normalizeCTMSCapabilities,
  unavailableCTMSCapabilities,
  useCTMSCapabilities,
  useCTMSCapabilityState,
} from './capabilities'
export type {
  CTMSActionRouteDescriptor,
  CTMSActionRouteId,
  CTMSCapabilityCode,
  CTMSCapabilityManifest,
  CTMSCapabilityState,
  CTMSCapabilityStatus,
  CTMSEnvironmentMetadata,
  CTMSPhase,
  CTMSPhaseMetadata,
  CTMSPlatformCapabilities,
  CTMSPlatformCapability,
  Module,
  OwnershipState,
} from './capabilities'
export * from './api'
export * from './portfolio-api'
export * from './cache'
export * from './forms'
export * from './hooks'
