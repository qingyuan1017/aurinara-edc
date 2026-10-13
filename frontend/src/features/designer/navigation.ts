import {
  CalendarClock,
  CalendarRange,
  CheckCircle2,
  Database,
  FileClock,
  FileText,
  KeyRound,
  ListChecks,
  Tags,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { PERMISSIONS, type PermissionCode } from '@/lib/permissions'

export interface DesignerNavigationItem {
  readonly id: string
  readonly label: string
  readonly to: string
  readonly icon: LucideIcon
  readonly requiredPermissions: readonly PermissionCode[]
}

export interface DesignerNavigationSection {
  readonly id: string
  readonly label: string
  readonly items: readonly DesignerNavigationItem[]
}

const DESIGNER_NAVIGATION_SECTIONS = [
  {
    id: 'lifecycle',
    label: 'Design lifecycle',
    items: [
      {
        id: 'versions',
        label: 'Version History',
        to: '/designer/versions',
        icon: FileClock,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_STUDY_VERSION_READ,
          PERMISSIONS.DESIGNER_STUDY_VERSION_CREATE,
          PERMISSIONS.DESIGNER_STUDY_VERSION_AMEND,
          PERMISSIONS.DESIGNER_VERSION_PUBLISH,
        ],
      },
    ],
  },
  {
    id: 'crf-design',
    label: 'CRF design',
    items: [
      {
        id: 'forms',
        label: 'Form Builder',
        to: '/designer/forms',
        icon: FileText,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_FORM_READ,
          PERMISSIONS.DESIGNER_FORM_CONFIGURE,
          PERMISSIONS.DESIGNER_FIELD_CONFIGURE,
        ],
      },
      {
        id: 'subject-phases',
        label: 'Subject Phases',
        to: '/designer/subject-phases',
        icon: Workflow,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_SUBJECT_PHASE_READ,
          PERMISSIONS.DESIGNER_SUBJECT_PHASE_CONFIGURE,
        ],
      },
      {
        id: 'visits',
        label: 'Visits',
        to: '/designer/visits',
        icon: CalendarClock,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_VISIT_READ,
          PERMISSIONS.DESIGNER_VISIT_CONFIGURE,
        ],
      },
      {
        id: 'schedule-of-assessment',
        label: 'Schedule of Assessment',
        to: '/designer/schedule-of-assessment',
        icon: CalendarRange,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_SOA_READ,
          PERMISSIONS.DESIGNER_SOA_CONFIGURE,
        ],
      },
      {
        id: 'arms',
        label: 'Arms',
        to: '/designer/arms',
        icon: ListChecks,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_ARM_READ,
          PERMISSIONS.DESIGNER_ARM_CONFIGURE,
        ],
      },
    ],
  },
  {
    id: 'rules-and-standards',
    label: 'Rules and standards',
    items: [
      {
        id: 'edit-checks',
        label: 'Edit Checks',
        to: '/designer/edit-checks',
        icon: CheckCircle2,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_EDITCHECK_CONFIGURE,
          PERMISSIONS.DESIGNER_EDITCHECK_TEST,
        ],
      },
      {
        id: 'codelists',
        label: 'Codelists',
        to: '/designer/codelists',
        icon: Tags,
        requiredPermissions: [
          PERMISSIONS.DESIGNER_CODELIST_READ,
          PERMISSIONS.DESIGNER_CODELIST_CONFIGURE,
        ],
      },
      {
        id: 'crf-access',
        label: 'CRF Access',
        to: '/designer/crf-access',
        icon: KeyRound,
        requiredPermissions: [PERMISSIONS.DESIGNER_CRF_ACCESS_CONFIGURE],
      },
      {
        id: 'raw-data-variables',
        label: 'Raw-Data Variables',
        to: '/designer/raw-data-variables',
        icon: Database,
        requiredPermissions: [PERMISSIONS.DESIGNER_RAW_DATA_VARIABLE_CONFIGURE],
      },
      {
        id: 'coding-settings',
        label: 'Coding Settings',
        to: '/designer/coding-settings',
        icon: FileText,
        requiredPermissions: [PERMISSIONS.DESIGNER_CODING_SETTING_CONFIGURE],
      },
    ],
  },
] as const satisfies readonly DesignerNavigationSection[]

export type DesignerRoutePath = (typeof DESIGNER_NAVIGATION_SECTIONS)[number]['items'][number]['to']

export function getDesignerLandingPath(
  permissions: readonly string[],
): DesignerRoutePath | null {
  const granted = new Set(permissions)

  for (const section of DESIGNER_NAVIGATION_SECTIONS) {
    for (const item of section.items) {
      if (item.requiredPermissions.some((permission) => granted.has(permission))) return item.to
    }
  }

  return null
}

/**
 * Designer navigation is a convenience affordance only. The API remains the
 * authority for every permission and study-scoped access decision.
 */
export function resolveDesignerNavigation(
  permissions: readonly string[],
): readonly DesignerNavigationSection[] {
  const granted = new Set(permissions)

  return DESIGNER_NAVIGATION_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) =>
      item.requiredPermissions.some((permission) => granted.has(permission)),
    ),
  })).filter((section) => section.items.length > 0)
}

export { DESIGNER_NAVIGATION_SECTIONS }
