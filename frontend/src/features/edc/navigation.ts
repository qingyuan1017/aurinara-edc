import {
  Activity,
  BookOpenCheck,
  ClipboardCheck,
  Database,
  FileInput,
  LayoutDashboard,
  MessageCircleQuestion,
  Stethoscope,
  type LucideIcon,
} from 'lucide-react'
type SearchState = Record<string, unknown>
type SearchPreserver = (previous: SearchState) => SearchState

export interface EDCNavigationItemDefinition {
  readonly id: string
  readonly label: string
  readonly path: string
}

export interface EDCNavigationSectionDefinition {
  readonly id: string
  readonly label: string
  readonly icon: LucideIcon
  readonly items: readonly EDCNavigationItemDefinition[]
}

export interface ResolvedEDCNavigationItem extends EDCNavigationItemDefinition {
  readonly to: string
  readonly section: string
  readonly search: SearchPreserver
  readonly activeOptions: { readonly exact: boolean }
}

export interface ResolvedEDCNavigationSection extends Omit<EDCNavigationSectionDefinition, 'items'> {
  readonly items: readonly ResolvedEDCNavigationItem[]
}

export const EDC_NAVIGATION_DEFINITIONS: readonly EDCNavigationSectionDefinition[] = [
  {
    id: 'overview',
    label: 'Overview',
    icon: LayoutDashboard,
    items: [
      { id: 'edc-dashboard', label: 'EDC Dashboard', path: '/overview' },
      { id: 'collection-progress', label: 'Data Collection Progress', path: '/overview/data-collection-progress' },
      { id: 'outstanding-activities', label: 'Outstanding Activities', path: '/overview/outstanding-activities' },
    ],
  },
  {
    id: 'subjects',
    label: 'Subjects',
    icon: BookOpenCheck,
    items: [
      { id: 'subject-list', label: 'Subject List', path: '/subjects' },
      { id: 'subject-profile', label: 'Subject Profile', path: '/subjects/profile' },
      { id: 'subject-visits-forms', label: 'Subject Visits & Forms', path: '/subjects/visits-forms' },
    ],
  },
  {
    id: 'data-entry',
    label: 'Data Entry',
    icon: FileInput,
    items: [
      { id: 'ecrf-data-entry', label: 'eCRF Data Entry', path: '/data-entry' },
      { id: 'incomplete-forms', label: 'Incomplete Forms', path: '/data-entry/incomplete-forms' },
      { id: 'data-change-history', label: 'Data Change History', path: '/data-entry/change-history' },
    ],
  },
  {
    id: 'data-review',
    label: 'Data Review',
    icon: ClipboardCheck,
    items: [
      { id: 'data-review-dashboard', label: 'Data Review Dashboard', path: '/data-review' },
      { id: 'forms-review', label: 'Forms Review', path: '/data-review/forms' },
      { id: 'sdv-sdr', label: 'SDV / SDR', path: '/data-review/sdv-sdr' },
      { id: 'data-listings', label: 'Data Listings', path: '/data-review/listings' },
    ],
  },
  {
    id: 'queries',
    label: 'Queries',
    icon: MessageCircleQuestion,
    items: [
      { id: 'query-dashboard', label: 'Query Dashboard', path: '/queries' },
      { id: 'open-queries', label: 'Open Queries', path: '/queries/open' },
      { id: 'query-history', label: 'Query History', path: '/queries/history' },
    ],
  },
  {
    id: 'medical-coding',
    label: 'Medical Coding',
    icon: Stethoscope,
    items: [
      { id: 'coding-dashboard', label: 'Coding Dashboard', path: '/medical-coding' },
      { id: 'meddra-coding', label: 'MedDRA Coding', path: '/medical-coding/meddra' },
      { id: 'whodrug-coding', label: 'WHODrug Coding', path: '/medical-coding/whodrug' },
      { id: 'coding-review', label: 'Coding Review', path: '/medical-coding/review' },
    ],
  },
  {
    id: 'exports',
    label: 'Data Exports',
    icon: Activity,
    items: [
      { id: 'dataset-exports', label: 'Dataset Exports', path: '/exports' },
      { id: 'export-history', label: 'Export History', path: '/exports/history' },
    ],
  },
  {
    id: 'database-lock',
    label: 'Database Lock',
    icon: Database,
    items: [
      { id: 'lock-readiness', label: 'Lock Readiness', path: '/database-lock' },
      { id: 'data-freeze', label: 'Data Freeze', path: '/database-lock/freeze' },
      { id: 'database-lock-unlock', label: 'Database Lock / Unlock', path: '/database-lock/manage' },
      { id: 'lock-history', label: 'Lock History', path: '/database-lock/history' },
    ],
  },
] as const

export function getEDCStudyIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/studies\/([^/]+)\/edc(?:\/|$)/)
  if (!match) return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return match[1]
  }
}

export function getEDCLandingPath(studyId?: string | null): string {
  return studyId ? `/studies/${encodeURIComponent(studyId)}/edc/overview` : '/'
}

export function resolveEDCNavigation(
  studyId: string | null | undefined,
  preserveSearch: SearchPreserver,
): readonly ResolvedEDCNavigationSection[] {
  const root = studyId ? `/studies/${encodeURIComponent(studyId)}/edc` : null

  return EDC_NAVIGATION_DEFINITIONS.map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      section: section.id,
      to: root ? `${root}${item.path}` : getEDCLandingPath(studyId),
      search: preserveSearch,
      activeOptions: { exact: true as const },
    })),
  }))
}
