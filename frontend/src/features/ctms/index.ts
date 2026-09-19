/** CTMS first-party frontend feature boundary. */

export { CTMSHomePage } from './CTMSHomePage'
export { CTMSWorkspacePage } from './WorkspacePage'
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
export * from './cache'
export * from './forms'
export * from './hooks'
