/** PV/Safety first-party frontend feature boundary.
 *
 * PV routes, listings, forms, and permission-aware navigation register with
 * their implementation tasks under this area. Disabling or failing PV must
 * never remove or alter EDC/CTMS navigation.
 */

export {
  PV_CAPABILITY_CODES,
  PV_ACTION_ROUTE_MAP,
  PV_DISABLED_MANIFEST,
  fetchPVCapabilities,
  isPVActionAvailable,
  normalizePVCapabilities,
  unavailablePVCapabilities,
  usePVCapabilities,
  usePVCapabilityState,
} from './capabilities'
export type {
  Module,
  PVActionRouteDescriptor,
  PVActionRouteId,
  PVCapabilityCode,
  PVCapabilityManifest,
  PVCapabilityState,
  PVCapabilityStatus,
  PVEnvironmentMetadata,
  PVPhase,
  PVPlatformCapabilities,
  PVPlatformCapability,
} from './capabilities'
export { pvApi, pvKeys, isPVCaseClosed } from './api'
export { resolvePVNavigation } from './navigation'
export type { PVNavigationItem, PVNavigationSection } from './navigation'
export { PVWorkspacePage, type PVView } from './WorkspacePage'
export { PVHomePage } from './PVHomePage'
