import { describe, expect, it } from 'vitest'
import {
  CTMS_ACTION_ROUTE_MAP,
  CTMS_CAPABILITY_CODES,
  isCTMSActionAvailable,
  type CTMSActionRouteDescriptor,
  type CTMSCapabilityCode,
  type CTMSCapabilityManifest,
  type CTMSPhase,
} from '@/features/ctms'

const phases = [0, 1, 2, 3] as const satisfies readonly CTMSPhase[]
const capabilityCodes = Object.values(CTMS_CAPABILITY_CODES) as CTMSCapabilityCode[]
const permissions = [
  'ctms.monitoring_activity_management',
  'ctms.operational_study_management',
  'ctms.operational_site_management',
  'ctms.enrollment_management',
  'ctms.coordination_replay',
  'ctms.conflict_management',
  'data.export',
] as const
const prohibitedEDCResources = [
  'Study_Version',
  'clinical_subjects',
  'Visit_Instances',
  'Form_Instances',
  'Field_Values',
  'Queries',
  'Clinical_Attachments',
  'clinical_exports',
] as const

/** A small deterministic generator keeps this property test dependency-free. */
function generator(seed: number) {
  let state = seed >>> 0
  return {
    next() {
      state = (Math.imul(state, 1_664_525) + 1_013_904_223) >>> 0
      return state
    },
    integer(maxExclusive: number) {
      return this.next() % maxExclusive
    },
    boolean() {
      return this.integer(2) === 0
    },
  }
}

function expectedAvailability(
  manifest: CTMSCapabilityManifest,
  descriptor: CTMSActionRouteDescriptor,
  grantedPermissions: readonly string[],
): boolean {
  if (!manifest.enabled || manifest.phase === 0) return false
  if (manifest.phase < descriptor.phase) return false
  if (!manifest.capabilities.includes(descriptor.capability)) return false
  if (descriptor.platformCapability && manifest.platform_capabilities?.[descriptor.platformCapability] !== true) return false
  if (descriptor.permission && !grantedPermissions.includes(descriptor.permission)) return false
  return descriptor.owner === 'CTMS' && descriptor.clinicalMutation === false
}

describe('CTMS capability and persona affordance properties', () => {
  it('Feature: ctms-frontend, Property 1: Phase and persona affordances never exceed server metadata', () => {
    // 256 deterministic generated examples provide more than the required 100 cases.
    for (let example = 0; example < 256; example += 1) {
      const random = generator(0xC7A5 + example)
      const phase = phases[random.integer(phases.length)]
      const enabled = random.boolean()
      const manifestCapabilities = capabilityCodes.filter(() => random.boolean())
      const platformCapabilities = {
        health_observability: random.boolean(),
      }
      const manifest: CTMSCapabilityManifest = {
        module: 'CTMS',
        enabled,
        phase,
        capabilities: manifestCapabilities,
        platform_capabilities: platformCapabilities,
      }

      // Persona names are intentionally only labels. The resolver must use the
      // generated permission codes and must not infer access from a role name.
      const persona = ['CTMS_Admin', 'CTMS_Operations_User', 'CTMS_Viewer', 'unknown'][random.integer(4)]
      const grantedPermissions = permissions.filter(() => random.boolean())
      const personaOnlyPermissions = [...grantedPermissions, persona]
      const generatedPhase = phases[random.integer(phases.length)]
      const routeDescriptors = Object.values(CTMS_ACTION_ROUTE_MAP).map((base, index) => ({
        ...base,
        kind: random.boolean() ? base.kind : base.kind === 'route' ? 'action' : 'route',
        route: `${base.route}?generated=${example}-${index}`,
        phase: generatedPhase === 0 ? 1 : generatedPhase,
        capability: capabilityCodes[random.integer(capabilityCodes.length)],
        permission: random.boolean() ? undefined : permissions[random.integer(permissions.length)],
        platformCapability: random.boolean() ? undefined : 'health_observability',
      })) as CTMSActionRouteDescriptor[]

      const prohibitedResource = prohibitedEDCResources[random.integer(prohibitedEDCResources.length)]
      const prohibitedDescriptor = {
        kind: random.boolean() ? 'route' : 'action',
        route: `/edc/${prohibitedResource}`,
        phase: 1 as const,
        capability: capabilityCodes[random.integer(capabilityCodes.length)],
        permission: random.boolean() ? undefined : permissions[random.integer(permissions.length)],
        owner: 'EDC',
        clinicalMutation: true,
      } as unknown as CTMSActionRouteDescriptor
      routeDescriptors.push(prohibitedDescriptor)

      const visibleActions = routeDescriptors.filter((descriptor) =>
        isCTMSActionAvailable(manifest, descriptor, personaOnlyPermissions),
      )

      expect(visibleActions).toEqual(
        routeDescriptors.filter((descriptor) =>
          expectedAvailability(manifest, descriptor, personaOnlyPermissions),
        ),
      )
      expect(visibleActions.every((descriptor) => descriptor.owner === 'CTMS')).toBe(true)
      expect(visibleActions.every((descriptor) => descriptor.clinicalMutation === false)).toBe(true)
      expect(visibleActions.some((descriptor) => descriptor.route === `/edc/${prohibitedResource}`)).toBe(false)
    }
  })
})
