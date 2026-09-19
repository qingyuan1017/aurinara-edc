import { Bell, BookOpen, Building2, CheckCircle2, CircleHelp, FileText, LayoutDashboard, ScrollText, Search, Settings, Sparkles, Stethoscope, Upload, Users, type LucideIcon } from 'lucide-react'
import type { CTMSCapabilityState, CTMSNavigationSection, CTMSNavigationItem } from '@/features/ctms'
import { resolveCTMSNavigation } from '@/features/ctms'

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
}

export interface NavigationSection {
  readonly id: string
  readonly label: string
  readonly items: readonly EDCNavigationItem[]
}

export interface CTMSNavigationViewItem extends CTMSNavigationItem {
  /** CTMS links intentionally retain the current route search state. */
  readonly search: SearchPreserver
  /** CTMS destinations match descendants of their registered route. */
  readonly activeOptions: { readonly exact: false }
}

export interface CTMSNavigationViewSection extends Omit<CTMSNavigationSection, 'items'> {
  readonly items: readonly CTMSNavigationViewItem[]
}

export interface NavigationModel {
  readonly edcSections: readonly NavigationSection[]
  readonly ctmsSections: readonly CTMSNavigationViewSection[]
}

/** The same EDC destinations previously defined in AppShell, grouped for presentation. */
export const EDC_NAV_ITEMS: readonly EDCNavigationItem[] = [
  { id: 'dashboard', label: 'Dashboard', to: '/', icon: LayoutDashboard, section: 'workspace', search: preserveCurrentSearch },
  { id: 'studies', label: 'Studies', to: '/studies', icon: BookOpen, section: 'study-data', search: preserveCurrentSearch },
  { id: 'sites', label: 'Sites', to: '/sites', icon: Building2, section: 'study-data', search: preserveCurrentSearch },
  { id: 'subjects', label: 'Subjects', to: '/subjects', icon: Users, section: 'study-data', search: preserveCurrentSearch },
  { id: 'forms', label: 'Forms', to: '/forms', icon: FileText, section: 'study-data', search: preserveCurrentSearch },
  { id: 'queries', label: 'Queries', to: '/queries', icon: CircleHelp, section: 'data-quality', search: preserveCurrentSearch },
  { id: 'data-cleaning', label: 'Data Cleaning', to: '/data-cleaning', icon: Search, section: 'data-quality', search: preserveCurrentSearch },
  { id: 'sdv', label: 'SDV Worklist', to: '/sdv', icon: CheckCircle2, section: 'data-quality', search: preserveCurrentSearch },
  { id: 'review', label: 'Clinical Review', to: '/review', icon: Stethoscope, section: 'data-quality', search: preserveCurrentSearch },
  { id: 'edit-checks', label: 'Edit Checks', to: '/edit-checks', icon: CheckCircle2, section: 'data-quality', search: preserveCurrentSearch },
  { id: 'ai', label: 'AI Assistant', to: '/ai', icon: Sparkles, section: 'operations', search: preserveCurrentSearch },
  { id: 'notifications', label: 'Notifications', to: '/notifications', icon: Bell, section: 'operations', search: preserveCurrentSearch },
  { id: 'exports', label: 'Exports', to: '/exports', icon: Upload, section: 'operations', search: preserveCurrentSearch },
  { id: 'admin', label: 'Admin', to: '/admin', icon: Settings, section: 'administration', search: preserveCurrentSearch },
  { id: 'audit', label: 'Audit Trail', to: '/audit', icon: ScrollText, section: 'administration', search: preserveCurrentSearch },
] as const

/** Backwards-friendly name for consumers migrating the old AppShell constant. */
export const NAV_ITEMS = EDC_NAV_ITEMS

const EDC_SECTION_LABELS: Readonly<Record<string, string>> = {
  workspace: 'Workspace',
  'study-data': 'Study data',
  'data-quality': 'Data quality',
  operations: 'Operations',
  administration: 'Administration',
}

export const EDC_NAVIGATION_SECTIONS: readonly NavigationSection[] = Object.entries(EDC_SECTION_LABELS).map(([id, label]) => ({
  id,
  label,
  items: EDC_NAV_ITEMS.filter((item) => item.section === id),
}))

/** Identity preservation matches the existing CTMS `search={(previous) => previous}` links. */
export function preserveCurrentSearch(previous: SearchState): SearchState {
  return previous
}

/**
 * Resolves the presentation navigation from existing authority metadata.
 * This function deliberately delegates all CTMS filtering to resolveCTMSNavigation.
 */
export function resolveNavigationModel(
  state: CTMSCapabilityState,
  permissions: readonly string[],
  scope: { readonly studyId?: string | null; readonly siteId?: string | null } = {},
): NavigationModel {
  const ctmsSections = resolveCTMSNavigation(state, permissions, scope).map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      search: preserveCurrentSearch,
      activeOptions: { exact: false as const },
    })),
  }))

  return {
    edcSections: EDC_NAVIGATION_SECTIONS,
    ctmsSections,
  }
}

/** Alias emphasizing that this is a view-model adapter, not an authority resolver. */
export const createNavigationModel = resolveNavigationModel
