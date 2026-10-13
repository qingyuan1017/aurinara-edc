import type { LucideIcon } from 'lucide-react'
import type { CTMSCapabilityState, CTMSNavigationSection, CTMSNavigationItem } from '@/features/ctms'
import { resolveCTMSNavigation } from '@/features/ctms'
import { resolveEDCNavigation } from '@/features/edc/navigation'
import type { DesignerNavigationSection, DesignerNavigationItem } from '@/features/designer/navigation'
import { resolveDesignerNavigation } from '@/features/designer/navigation'
import type { PVCapabilityState, PVNavigationSection, PVNavigationItem } from '@/features/pv'
import { resolvePVNavigation } from '@/features/pv'

/** Search state accepted by TanStack Router link adapters. */
export type SearchState = Record<string, unknown>

/** Preserves the current router search object when assigned to a Link. */
export type SearchPreserver = (previous: SearchState) => SearchState

/** The existing EDC navigation target represented as a shell view model. */
export interface EDCNavigationItem {
  readonly id: string
  readonly label: string
  readonly to: string
  readonly icon: LucideIcon
  readonly section: string
  readonly search: SearchPreserver
  readonly activeOptions?: { readonly exact: boolean }
}

export interface NavigationSection {
  readonly id: string
  readonly label: string
  readonly icon?: LucideIcon
  readonly items: readonly EDCNavigationItem[]
}

export interface CTMSNavigationViewItem extends CTMSNavigationItem {
  /** CTMS links intentionally retain the current route search state. */
  readonly search: SearchPreserver
  /** Overview matches only its parent route; other destinations may match descendants. */
  readonly activeOptions: { readonly exact: boolean }
}

export interface DesignerNavigationViewItem extends DesignerNavigationItem {
  /** Designer links intentionally retain the selected design version search state. */
  readonly search: SearchPreserver
  /** Designer destinations match descendants of their registered route. */
  readonly activeOptions: { readonly exact: false }
}

export interface DesignerNavigationViewSection extends Omit<DesignerNavigationSection, 'items'> {
  readonly items: readonly DesignerNavigationViewItem[]
}

export interface CTMSNavigationViewSection extends Omit<CTMSNavigationSection, 'items'> {
  readonly items: readonly CTMSNavigationViewItem[]
}

export interface PVNavigationViewItem extends PVNavigationItem {
  /** PV links intentionally retain the current route search state. */
  readonly search: SearchPreserver
  /** PV destinations match descendants of their registered route. */
  readonly activeOptions: { readonly exact: false }
}

export interface PVNavigationViewSection extends Omit<PVNavigationSection, 'items'> {
  readonly items: readonly PVNavigationViewItem[]
}

export interface NavigationModel {
  readonly edcSections: readonly NavigationSection[]
  readonly designerSections: readonly DesignerNavigationViewSection[]
  readonly ctmsSections: readonly CTMSNavigationViewSection[]
  readonly pvSections: readonly PVNavigationViewSection[]
}

/** Identity preservation matches the existing CTMS `search={(previous) => previous}` links. */
export function preserveCurrentSearch(previous: SearchState): SearchState {
  return previous
}

/** Study-aware EDC navigation used by the authenticated shell. */
export const EDC_NAVIGATION_SECTIONS: readonly NavigationSection[] = resolveEDCNavigation(null, preserveCurrentSearch)
  .map((section) => ({
    ...section,
    items: section.items.map((item) => ({ ...item, icon: section.icon })),
  }))

export const EDC_NAV_ITEMS: readonly EDCNavigationItem[] = EDC_NAVIGATION_SECTIONS.flatMap((section) => section.items)
export const NAV_ITEMS = EDC_NAV_ITEMS

/**
 * Resolves the presentation navigation from existing authority metadata.
 * This function deliberately delegates all CTMS filtering to resolveCTMSNavigation.
 */
export function resolveNavigationModel(
  state: CTMSCapabilityState,
  pvState: PVCapabilityState,
  permissions: readonly string[],
  scope: { readonly studyId?: string | null; readonly siteId?: string | null } = {},
): NavigationModel {
  const edcSections = resolveEDCNavigation(scope.studyId, preserveCurrentSearch).map((section) => ({
    ...section,
    items: section.items.map((item) => ({ ...item, icon: section.icon })),
  }))
  const ctmsSections = resolveCTMSNavigation(state, permissions, scope).map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      search: preserveCurrentSearch,
      activeOptions: { exact: item.exact ?? false },
    })),
  }))

  const designerSections = resolveDesignerNavigation(permissions).map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      search: preserveCurrentSearch,
      activeOptions: { exact: false as const },
    })),
  }))

  const pvSections = resolvePVNavigation(pvState, permissions, scope).map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      search: preserveCurrentSearch,
      activeOptions: { exact: false as const },
    })),
  }))

  return {
    edcSections,
    designerSections,
    ctmsSections,
    pvSections,
  }
}

/** Alias emphasizing that this is a view-model adapter, not an authority resolver. */
export const createNavigationModel = resolveNavigationModel
