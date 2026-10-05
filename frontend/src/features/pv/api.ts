/**
 * PV/Safety API client boundary.
 *
 * This module owns the typed PV capability contract and the query keys/client
 * used by PV feature routes. The concrete PV resource clients (cases,
 * assessments, coding, narratives, reports, reconciliation, attachments,
 * exports, dashboards, audit) target the authenticated PV API under
 * `/api/v1/pv`. The API_Layer remains authoritative for authorization,
 * validation, and state transitions; these typed models are a convenience
 * contract for the React frontend only.
 */

import { useQuery } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'

export type PVPhase = 0 | 1 | 2 | 3

/** Server capability manifest returned by `/api/v1/pv/capabilities`. */
export interface PVCapabilityManifest {
  module: 'PV'
  enabled: boolean
  phase: PVPhase
  capabilities: string[]
  environment?: Record<string, unknown>
  platform_capabilities?: Record<string, boolean>
}

/** PV list envelope. The PV API allows page sizes 1–1,000 (Requirement 16.2). */
export type PVList<T> = PaginatedResponse<T>

/**
 * Canonical safety status vocabularies. The frontend renders the exact textual
 * value the server returns; it never infers transitions (Requirement 19.1).
 */
export type PVCaseState =
  | 'Open'
  | 'In Review'
  | 'Follow-up Required'
  | 'Ready to Report'
  | 'Reported'
  | 'Closed'
  | 'Reopened'

export type PVCaseVersionKind = 'Initial' | 'Follow-up'
export type PVCaseVersionStatus = 'Draft' | 'Submitted'
export type PVReportStatus = 'Pending' | 'Submitted' | 'Acknowledged' | 'Rejected' | 'Cancelled'
export type PVDiscrepancyStatus = 'Open' | 'Resolved'

/** A closed case renders its input controls disabled (Requirement 19.4). */
export function isPVCaseClosed(state: PVCaseState | string | null | undefined): boolean {
  return state === 'Closed'
}

/* ----------------------------------------------------------------------- */
/* Resource models                                                          */
/* ----------------------------------------------------------------------- */

export interface PVSafetyCase {
  id: string
  case_identifier: string
  study_id: string
  site_id?: string | null
  subject_reference: string
  case_type: string
  lifecycle_state: PVCaseState
  correlation_id?: string | null
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface PVSafetyCasePayload {
  study_id: string
  site_id?: string | null
  subject_reference: string
  case_type: string
  correlation_id?: string
}

export interface PVAdverseEventRecord {
  id: string
  case_id: string
  verbatim_term: string
  onset_date: string
  outcome: string
  resolution_date?: string | null
  created_at: string
  updated_at: string
}

export interface PVAdverseEventPayload {
  verbatim_term: string
  onset_date: string
  outcome: string
  resolution_date?: string | null
  correlation_id?: string
}

export interface PVCaseVersion {
  id: string
  case_id: string
  sequence_number: number
  version_kind: PVCaseVersionKind
  status: PVCaseVersionStatus
  submitted_by?: string | null
  submitted_at?: string | null
  created_at: string
}

export interface PVCaseLifecyclePayload {
  target_state: PVCaseState
  reason?: string
  correlation_id?: string
}

/** Post-submission edits require a Reason_For_Change of 1–4,000 chars (19.3). */
export interface PVReasonForChangePayload {
  reason: string
  correlation_id?: string
}

export interface PVSeriousnessAssessment {
  id: string
  ae_id: string
  serious: boolean
  criteria: string[]
  assessed_by?: string | null
  assessed_at?: string | null
  created_at: string
}

export interface PVSeriousnessPayload {
  serious: boolean
  criteria: string[]
  correlation_id?: string
}

export interface PVCausalityAssessment {
  id: string
  ae_id: string
  suspect_product: string
  causality_category: string
  assessed_by?: string | null
  assessed_at?: string | null
  created_at: string
}

export interface PVCausalityPayload {
  suspect_product: string
  causality_category: string
  correlation_id?: string
}

export interface PVExpectednessAssessment {
  id: string
  ae_id: string
  expected: boolean
  reference_information?: string | null
  assessed_by?: string | null
  assessed_at?: string | null
}

export interface PVExpectednessPayload {
  expected: boolean
  reference_information?: string | null
  correlation_id?: string
}

export interface PVSeverityGrade {
  id: string
  ae_id: string
  grade: string
  assessed_by?: string | null
  assessed_at?: string | null
}

export interface PVSeverityPayload {
  grade: string
  correlation_id?: string
}

export interface PVMedDraCoding {
  id: string
  ae_id: string
  term: string
  dictionary_version: string
  assigned_by?: string | null
  assigned_at?: string | null
  superseded_by_id?: string | null
}

export interface PVWhoDrugCoding {
  id: string
  case_id: string
  product: string
  dictionary_version: string
  assigned_by?: string | null
  assigned_at?: string | null
  superseded_by_id?: string | null
}

export interface PVCodingPayload {
  term: string
  dictionary_version: string
  correlation_id?: string
}

export interface PVWhoDrugPayload {
  product: string
  dictionary_version: string
  correlation_id?: string
}

export interface PVCaseNarrative {
  id: string
  case_id: string
  text: string
  authored_by?: string | null
  authored_at?: string | null
  current_version_id?: string | null
  created_at: string
  updated_at: string
}

export interface PVNarrativeVersion {
  id: string
  narrative_id: string
  text: string
  revised_by?: string | null
  revised_at?: string | null
  reason?: string | null
}

export interface PVNarrativePayload {
  text: string
  correlation_id?: string
}

export interface PVNarrativeRevisionPayload {
  text: string
  reason: string
  correlation_id?: string
}

export interface PVRegulatoryReport {
  id: string
  case_id: string
  study_id: string
  report_type: string
  destination: string
  status: PVReportStatus
  awareness_date?: string | null
  due_date?: string | null
  overdue?: boolean
  submitted_by?: string | null
  submitted_at?: string | null
  e2b_message_reference?: string | null
  created_at: string
  updated_at: string
}

export interface PVReportTransitionPayload {
  target_status: PVReportStatus
  e2b_message_reference?: string
  reason?: string
  correlation_id?: string
}

export interface PVReconciliationDiscrepancy {
  id: string
  run_id: string
  case_id: string
  edc_reference: string
  differing_fields: string[]
  status: PVDiscrepancyStatus
  created_at: string
  resolved_at?: string | null
}

export interface PVReconciliationRun {
  id: string
  study_id: string
  match_count: number
  discrepancy_count: number
  status: string
  created_at: string
  discrepancies?: PVReconciliationDiscrepancy[]
}

export interface PVReconciliationRunPayload {
  study_id: string
  correlation_id?: string
}

export type PVExportFormat = 'csv' | 'excel' | 'json' | 'e2b_xml'
export type PVExportStatus = 'Queued' | 'Running' | 'Completed' | 'Failed' | string

export interface PVExportFilters {
  siteId?: string
  subjectReference?: string
  caseStatuses?: PVCaseState[]
  seriousness?: boolean
  reportStatuses?: PVReportStatus[]
  dateFrom?: string
  dateTo?: string
}

export interface PVExportRequest {
  exportType: PVExportFormat
  filters?: PVExportFilters
}

export interface PVExportJob {
  id: string
  study_id: string
  module: string
  content_owner: string
  export_type: string
  status: PVExportStatus
  filters?: Record<string, unknown> | null
  file_path?: string | null
  file_size?: number | null
  error_message?: string | null
  requested_by: string
  correlation_id?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
}

/** Serialize the typed export request to the PV API contract. */
export function serializePVExportRequest(request: PVExportRequest): Record<string, unknown> {
  const filters = request.filters
  return {
    export_type: request.exportType,
    filters: {
      ...(filters?.siteId ? { site_id: filters.siteId } : {}),
      ...(filters?.subjectReference ? { subject_reference: filters.subjectReference } : {}),
      ...(filters?.caseStatuses?.length ? { case_statuses: filters.caseStatuses } : {}),
      ...(filters?.seriousness !== undefined ? { seriousness: filters.seriousness } : {}),
      ...(filters?.reportStatuses?.length ? { report_statuses: filters.reportStatuses } : {}),
      ...(filters?.dateFrom ? { date_from: filters.dateFrom } : {}),
      ...(filters?.dateTo ? { date_to: filters.dateTo } : {}),
    },
  }
}

export interface PVReportingComplianceMetrics {
  submitted: number
  overdue: number
  on_time: number
}

export interface PVProjectedField {
  projection_id: string
  source_module: string
  field_name: string
  value?: unknown
  read_only: boolean
  ownership: string
}

export interface PVStudyDashboard {
  study_id: string
  case_counts_by_status: Record<string, number>
  adverse_event_counts_by_seriousness: Record<string, number>
  report_counts_by_status: Record<string, number>
  reporting_compliance: PVReportingComplianceMetrics
  projected_fields: PVProjectedField[]
  generated_at: string
}

export interface PVSiteDashboard extends Omit<PVStudyDashboard, 'study_id'> {
  study_id: string
  site_id: string
}

export interface PVAuditEvent {
  id: string
  actor_id?: string | null
  timestamp: string
  entity_type: string
  entity_id: string
  study_id?: string | null
  site_id?: string | null
  action: string
  old_values?: Record<string, unknown> | null
  new_values?: Record<string, unknown> | null
  reason?: string | null
  request_id?: string | null
}

export interface PVAuditSearchParams {
  userId?: string
  dateFrom?: string
  dateTo?: string
  entityType?: string
  caseId?: string
  reportId?: string
  page?: number
  pageSize?: number
}

/* ----------------------------------------------------------------------- */
/* Query keys                                                               */
/* ----------------------------------------------------------------------- */

/** Query keys for PV server state. */
export const pvKeys = {
  all: ['pv'] as const,
  capabilities: () => [...pvKeys.all, 'capabilities'] as const,
  health: () => [...pvKeys.all, 'health'] as const,
  cases: (studyId: string, params?: Record<string, unknown>) =>
    [...pvKeys.all, 'cases', studyId, params ?? {}] as const,
  case: (caseId: string) => [...pvKeys.all, 'case', caseId] as const,
  adverseEvents: (caseId: string) => [...pvKeys.all, 'adverse-events', caseId] as const,
  versions: (caseId: string) => [...pvKeys.all, 'versions', caseId] as const,
  assessments: (aeId: string) => [...pvKeys.all, 'assessments', aeId] as const,
  coding: (caseId: string) => [...pvKeys.all, 'coding', caseId] as const,
  narratives: (caseId: string) => [...pvKeys.all, 'narratives', caseId] as const,
  narrativeVersions: (narrativeId: string) =>
    [...pvKeys.all, 'narrative-versions', narrativeId] as const,
  reports: (studyId: string, params?: Record<string, unknown>) =>
    [...pvKeys.all, 'reports', studyId, params ?? {}] as const,
  caseReports: (caseId: string) => [...pvKeys.all, 'case-reports', caseId] as const,
  reconciliation: (studyId: string, params?: Record<string, unknown>) =>
    [...pvKeys.all, 'reconciliation', studyId, params ?? {}] as const,
  dashboard: (studyId: string) => [...pvKeys.all, 'dashboard', studyId] as const,
  siteDashboard: (siteId: string, studyId?: string) =>
    [...pvKeys.all, 'site-dashboard', siteId, studyId ?? null] as const,
  exports: (studyId: string, params?: Record<string, unknown>) =>
    [...pvKeys.all, 'exports', studyId, params ?? {}] as const,
  audit: (studyId: string, params?: Record<string, unknown>) =>
    [...pvKeys.all, 'audit', studyId, params ?? {}] as const,
  caseAudit: (caseId: string) => [...pvKeys.all, 'case-audit', caseId] as const,
}

/* ----------------------------------------------------------------------- */
/* Client helpers                                                           */
/* ----------------------------------------------------------------------- */

const item = async <T>(path: string): Promise<T> => (await api.get<T>(path)).data
const list = async <T>(path: string): Promise<PVList<T>> => (await api.get<PVList<T>>(path)).data
const post = async <T>(path: string, payload?: unknown): Promise<T> =>
  (await api.post<T>(path, payload)).data
const patch = async <T>(path: string, payload?: unknown): Promise<T> =>
  (await api.patch<T>(path, payload)).data

function query(params?: Record<string, unknown>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      if (value.length) search.set(key, value.join(','))
    } else {
      search.set(key, String(value))
    }
  })
  const serialized = search.toString()
  return serialized ? `?${serialized}` : ''
}

/* ----------------------------------------------------------------------- */
/* PV read/mutation client                                                  */
/* ----------------------------------------------------------------------- */

export const pvApi = {
  capabilities: () => item<PVCapabilityManifest>('/pv/capabilities'),
  health: () => item<Record<string, unknown>>('/pv/health'),

  // Cases and adverse events
  cases: (studyId: string, params?: Record<string, unknown>) =>
    list<PVSafetyCase>(`/pv/studies/${studyId}/cases${query(params)}`),
  case: (caseId: string) => item<PVSafetyCase>(`/pv/cases/${caseId}`),
  createCase: (studyId: string, payload: PVSafetyCasePayload) =>
    post<PVSafetyCase>(`/pv/studies/${studyId}/cases`, { ...payload, study_id: payload.study_id ?? studyId }),
  transitionCase: (caseId: string, payload: PVCaseLifecyclePayload) =>
    post<PVSafetyCase>(`/pv/cases/${caseId}/transition`, payload),
  adverseEvents: (caseId: string) =>
    list<PVAdverseEventRecord>(`/pv/cases/${caseId}/adverse-events`),
  createAdverseEvent: (caseId: string, payload: PVAdverseEventPayload) =>
    post<PVAdverseEventRecord>(`/pv/cases/${caseId}/adverse-events`, payload),
  versions: (caseId: string) => list<PVCaseVersion>(`/pv/cases/${caseId}/versions`),
  submitVersion: (caseId: string, payload?: PVReasonForChangePayload) =>
    post<PVCaseVersion>(`/pv/cases/${caseId}/versions`, payload ?? {}),

  // Assessments
  seriousness: (aeId: string) =>
    list<PVSeriousnessAssessment>(`/pv/adverse-events/${aeId}/seriousness`),
  recordSeriousness: (aeId: string, payload: PVSeriousnessPayload) =>
    post<PVSeriousnessAssessment>(`/pv/adverse-events/${aeId}/seriousness`, payload),
  recordCausality: (aeId: string, payload: PVCausalityPayload) =>
    post<PVCausalityAssessment>(`/pv/adverse-events/${aeId}/causality`, payload),
  recordExpectedness: (aeId: string, payload: PVExpectednessPayload) =>
    post<PVExpectednessAssessment>(`/pv/adverse-events/${aeId}/expectedness`, payload),
  recordSeverity: (aeId: string, payload: PVSeverityPayload) =>
    post<PVSeverityGrade>(`/pv/adverse-events/${aeId}/severity`, payload),

  // Coding
  meddraCoding: (caseId: string) => list<PVMedDraCoding>(`/pv/cases/${caseId}/meddra-coding`),
  whodrugCoding: (caseId: string) => list<PVWhoDrugCoding>(`/pv/cases/${caseId}/whodrug-coding`),
  codeMedDra: (aeId: string, payload: PVCodingPayload) =>
    post<PVMedDraCoding>(`/pv/adverse-events/${aeId}/meddra-coding`, payload),
  codeWhoDrug: (caseId: string, payload: PVWhoDrugPayload) =>
    post<PVWhoDrugCoding>(`/pv/cases/${caseId}/whodrug-coding`, payload),

  // Narratives
  narratives: (caseId: string) => list<PVCaseNarrative>(`/pv/cases/${caseId}/narratives`),
  createNarrative: (caseId: string, payload: PVNarrativePayload) =>
    post<PVCaseNarrative>(`/pv/cases/${caseId}/narratives`, payload),
  reviseNarrative: (narrativeId: string, payload: PVNarrativeRevisionPayload) =>
    patch<PVCaseNarrative>(`/pv/narratives/${narrativeId}`, payload),
  narrativeVersions: (narrativeId: string) =>
    list<PVNarrativeVersion>(`/pv/narratives/${narrativeId}/versions`),

  // Regulatory reports
  reports: (studyId: string, params?: Record<string, unknown>) =>
    list<PVRegulatoryReport>(`/pv/studies/${studyId}/reports${query(params)}`),
  caseReports: (caseId: string) => list<PVRegulatoryReport>(`/pv/cases/${caseId}/reports`),
  transitionReport: (reportId: string, payload: PVReportTransitionPayload) =>
    post<PVRegulatoryReport>(`/pv/reports/${reportId}/transition`, payload),

  // Reconciliation
  reconciliation: (studyId: string, params?: Record<string, unknown>) =>
    list<PVReconciliationRun>(`/pv/studies/${studyId}/reconciliation${query(params)}`),
  runReconciliation: (studyId: string, payload?: PVReconciliationRunPayload) =>
    post<PVReconciliationRun>(`/pv/studies/${studyId}/reconciliation`, payload ?? { study_id: studyId }),
  resolveDiscrepancy: (discrepancyId: string, payload?: PVReasonForChangePayload) =>
    post<PVReconciliationDiscrepancy>(`/pv/reconciliation/discrepancies/${discrepancyId}/resolve`, payload ?? {}),

  // Dashboards
  dashboard: (studyId: string) => item<PVStudyDashboard>(`/pv/studies/${studyId}/dashboard`),
  siteDashboard: (siteId: string, studyId?: string) =>
    item<PVSiteDashboard>(
      `/pv/sites/${siteId}/dashboard${studyId ? `?study_id=${encodeURIComponent(studyId)}` : ''}`,
    ),

  // Exports
  exports: (studyId: string, params?: Record<string, unknown>) =>
    list<PVExportJob>(`/pv/studies/${studyId}/exports${query(params)}`),
  createExport: (studyId: string, payload: PVExportRequest) =>
    post<PVExportJob>(`/pv/studies/${studyId}/exports`, serializePVExportRequest(payload)),
  exportJob: (id: string) => item<PVExportJob>(`/pv/exports/${id}`),
  downloadExport: (id: string) =>
    api.get<Blob>(`/pv/exports/${id}/download`, { responseType: 'blob' }).then((r) => r.data),

  // Audit
  audit: (studyId: string, params?: Record<string, unknown>) =>
    list<PVAuditEvent>(`/pv/studies/${studyId}/audit${query(params)}`),
  /**
   * Case-scoped PV audit history, aligned to the authoritative audit search
   * endpoint (`/pv/audit/events?safety_case_id=`). Events are returned ordered
   * by UTC timestamp ascending (Requirement 11.4) and rendered read-only in a
   * dialog while the originating case status view stays mounted (19.5).
   */
  caseAudit: (caseId: string) =>
    list<PVAuditEvent>(`/pv/audit/events${query({ safety_case_id: caseId })}`),
}

/* ----------------------------------------------------------------------- */
/* TanStack Query hooks                                                     */
/* ----------------------------------------------------------------------- */

export function usePVCases(studyId: string, params?: Record<string, unknown>) {
  return useQuery({
    queryKey: pvKeys.cases(studyId, params),
    queryFn: () => pvApi.cases(studyId, params),
    enabled: Boolean(studyId),
  })
}

export function usePVCase(caseId: string) {
  return useQuery({
    queryKey: pvKeys.case(caseId),
    queryFn: () => pvApi.case(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVAdverseEvents(caseId: string) {
  return useQuery({
    queryKey: pvKeys.adverseEvents(caseId),
    queryFn: () => pvApi.adverseEvents(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVVersions(caseId: string) {
  return useQuery({
    queryKey: pvKeys.versions(caseId),
    queryFn: () => pvApi.versions(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVSeriousness(aeId: string | undefined) {
  return useQuery({
    queryKey: pvKeys.assessments(aeId ?? 'none'),
    queryFn: () => pvApi.seriousness(aeId as string),
    enabled: Boolean(aeId),
  })
}

export function usePVMedDraCoding(caseId: string) {
  return useQuery({
    queryKey: [...pvKeys.coding(caseId), 'meddra'] as const,
    queryFn: () => pvApi.meddraCoding(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVWhoDrugCoding(caseId: string) {
  return useQuery({
    queryKey: [...pvKeys.coding(caseId), 'whodrug'] as const,
    queryFn: () => pvApi.whodrugCoding(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVNarratives(caseId: string) {
  return useQuery({
    queryKey: pvKeys.narratives(caseId),
    queryFn: () => pvApi.narratives(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVNarrativeVersions(narrativeId: string | undefined) {
  return useQuery({
    queryKey: pvKeys.narrativeVersions(narrativeId ?? 'none'),
    queryFn: () => pvApi.narrativeVersions(narrativeId as string),
    enabled: Boolean(narrativeId),
  })
}

export function usePVReports(studyId: string, params?: Record<string, unknown>) {
  return useQuery({
    queryKey: pvKeys.reports(studyId, params),
    queryFn: () => pvApi.reports(studyId, params),
    enabled: Boolean(studyId),
  })
}

export function usePVCaseReports(caseId: string) {
  return useQuery({
    queryKey: pvKeys.caseReports(caseId),
    queryFn: () => pvApi.caseReports(caseId),
    enabled: Boolean(caseId),
  })
}

export function usePVReconciliation(studyId: string, params?: Record<string, unknown>) {
  return useQuery({
    queryKey: pvKeys.reconciliation(studyId, params),
    queryFn: () => pvApi.reconciliation(studyId, params),
    enabled: Boolean(studyId),
  })
}

export function usePVDashboard(studyId: string) {
  return useQuery({
    queryKey: pvKeys.dashboard(studyId),
    queryFn: () => pvApi.dashboard(studyId),
    enabled: Boolean(studyId),
  })
}

export function usePVSiteDashboard(siteId: string, studyId?: string) {
  return useQuery({
    queryKey: pvKeys.siteDashboard(siteId, studyId),
    queryFn: () => pvApi.siteDashboard(siteId, studyId),
    enabled: Boolean(siteId),
  })
}

export function usePVExports(studyId: string, params?: Record<string, unknown>) {
  return useQuery({
    queryKey: pvKeys.exports(studyId, params),
    queryFn: () => pvApi.exports(studyId, params),
    enabled: Boolean(studyId),
  })
}

export function usePVAudit(studyId: string, params?: Record<string, unknown>) {
  return useQuery({
    queryKey: pvKeys.audit(studyId, params),
    queryFn: () => pvApi.audit(studyId, params),
    enabled: Boolean(studyId),
  })
}

export function usePVCaseAudit(caseId: string | undefined) {
  return useQuery({
    queryKey: pvKeys.caseAudit(caseId ?? 'none'),
    queryFn: () => pvApi.caseAudit(caseId as string),
    enabled: Boolean(caseId),
  })
}
