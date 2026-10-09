/**
 * Designer feature module.
 *
 * Design-time authoring surfaces for the brand-new Designer resources split
 * out of the combined EDC form metadata: codelists, subject phases, schedule
 * of assessment, cycles, arms, CRF access, raw-data variables, and coding
 * settings. All surfaces are gated by `designer.*` permissions and operate
 * against the study's open draft Design_Version.
 */
export { FormBuilderPage } from './FormBuilderPage'
export { CodelistsPage } from './CodelistsPage'
export { SubjectPhasesPage } from './SubjectPhasesPage'
export { VisitsPage } from './VisitsPage'
export { ScheduleOfAssessmentPage } from './ScheduleOfAssessmentPage'
export { CyclesPage } from './CyclesPage'
export { ArmsPage } from './ArmsPage'
export { CrfAccessPage } from './CrfAccessPage'
export { RawDataVariablesPage } from './RawDataVariablesPage'
export { CodingSettingsPage } from './CodingSettingsPage'
