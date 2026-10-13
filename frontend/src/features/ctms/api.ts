import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'

export type CTMSPhase = 0 | 1 | 2 | 3
export type CTMSStatus = string
export type CTMSList<T> = CTMSPage<T>
export type CTMSScalar = string | number | boolean | null

export interface CTMSPage<T> extends PaginatedResponse<T> {
  next_cursor?: string | null
  previous_cursor?: string | null
  status_options?: CTMSStatusOption[]
}

export interface CTMSCorrelationMetadata {
  requestId?: string
  correlationId?: string
  outcome?: 'accepted' | 'succeeded' | 'queued' | 'failed' | string
}

export interface CTMSMutationResult<T> {
  data: T
  meta: CTMSCorrelationMetadata
}

/** Status choices are returned by the server; the client must not infer transitions. */
export interface CTMSStatusOption {
  value: string
  label?: string
  requiresReason?: boolean
  reasonLabel?: string
}

export interface CTMSValidationDetails {
  fields?: Record<string, string[]>
  [key: string]: unknown
}

export interface CTMSBaselineErrorBody {
  code: string
  message: string
  details?: CTMSValidationDetails
}

export interface CTMSBaselineErrorEnvelope {
  error?: CTMSBaselineErrorBody
  detail?: string
  request_id?: string
  correlation_id?: string
  errors?: Record<string, string[]>
}

export type CTMSErrorCategory =
  | 'unauthenticated'
  | 'unauthorized'
  | 'not-found'
  | 'validation'
  | 'conflict'
  | 'rate-limited'
  | 'too-large'
  | 'unavailable'
  | 'unknown'

export interface CTMSClientErrorOptions {
  code?: string
  details?: CTMSValidationDetails
  requestId?: string
  correlationId?: string
  status?: number
  retryable?: boolean
  category?: CTMSErrorCategory
}

/** A sanitized error that is safe to render in CTMS feedback and support diagnostics. */
export class CTMSClientError extends Error {
  readonly code: string
  readonly details: CTMSValidationDetails
  readonly requestId?: string
  readonly correlationId?: string
  readonly status?: number
  readonly retryable: boolean
  readonly category: CTMSErrorCategory

  constructor(message: string, options: CTMSClientErrorOptions = {}) {
    super(message)
    this.name = 'CTMSClientError'
    this.code = options.code ?? 'CTMS_REQUEST_FAILED'
    this.details = options.details ?? {}
    this.requestId = options.requestId
    this.correlationId = options.correlationId
    this.status = options.status
    this.retryable = options.retryable ?? false
    this.category = options.category ?? classifyCTMSError(options.status)
  }
}

export interface CTMSQueryScope {
  routeScope?: string
  studyId?: string
  siteId?: string
}

export interface CTMSFilterState {
  status?: string | string[]
  siteId?: string
  ownerId?: string
  from?: string
  to?: string
  priority?: string
  dueCategory?: string
  reportType?: string
  recordType?: string | string[]
  includeArchived?: boolean
  page?: number
  pageSize?: number
  cursor?: string | null
}

export interface CTMSPagination {
  page?: number
  pageSize?: number
  cursor?: string | null
}

export interface CTMSQueryContext extends CTMSQueryScope {
  filters?: CTMSFilterState
  pagination?: CTMSPagination
  phase?: CTMSPhase
}

/** Convert supported UI filters to the server's allowlisted query parameter names. */
export function serializeCTMSFilters(
  filters: CTMSFilterState = {},
  pagination: CTMSPagination = {},
): Record<string, string> {
  const params: Record<string, string> = {}
  const add = (name: string, value: string | number | boolean | null | undefined) => {
    if (value !== undefined && value !== null && value !== '') params[name] = String(value)
  }
  const addList = (name: string, value: string | string[] | undefined) => {
    if (Array.isArray(value)) {
      if (value.length) params[name] = value.join(',')
    } else add(name, value)
  }

  addList('status', filters.status)
  add('site_id', filters.siteId)
  add('owner_id', filters.ownerId)
  add('date_from', filters.from)
  add('date_to', filters.to)
  add('priority', filters.priority)
  add('due_category', filters.dueCategory)
  add('report_type', filters.reportType)
  addList('record_type', filters.recordType)
  add('include_archived', filters.includeArchived)
  add('page', pagination.page ?? filters.page)
  add('page_size', pagination.pageSize ?? filters.pageSize)
  add('cursor', pagination.cursor ?? filters.cursor)
  return params
}

function appendCTMSQuery(path: string, context?: CTMSQueryContext): string {
  if (!context) return path
  const params = serializeCTMSFilters(context.filters, context.pagination)
  const query = new URLSearchParams(params).toString()
  return query ? `${path}${path.includes('?') ? '&' : '?'}${query}` : path
}

function normalizeQueryContext(context: CTMSQueryContext = {}): Record<string, unknown> {
  return {
    routeScope: context.routeScope ?? null,
    studyId: context.studyId ?? null,
    siteId: context.siteId ?? null,
    filters: context.filters ?? {},
    pagination: context.pagination ?? {},
    phase: context.phase ?? null,
  }
}

function withQueryContext<T extends readonly unknown[]>(key: T, context?: CTMSQueryContext) {
  return context ? [...key, normalizeQueryContext(context)] as const : key
}

function scopedContext(context: CTMSQueryContext | undefined, scope: CTMSQueryScope): CTMSQueryContext | undefined {
  return context ? { ...context, ...scope } : undefined
}

export interface CTMSOperationalStudy {
  id: string
  study_id: string
  sponsor?: string | null
  study_name?: string | null
  phase?: string | null
  study_type?: string | null
  main_purpose?: string | null
  therapeutic_area?: string | null
  program?: string | null
  indication?: string | null
  study_description?: string | null
  investigational_product?: string | null
  blind_method?: string | null
  randomized?: boolean | null
  expected_subject_count?: number | null
  language?: string | null
  expected_site_count?: number | null
  construction_period?: string | null
  planned_start_date?: string | null
  planned_end_date?: string | null
  actual_start_date?: string | null
  actual_end_date?: string | null
  study_currency?: string | null
  exchange_date?: string | null
  query_expected_days?: number | null
  operational_owner_id?: string | null
  readiness_criteria?: unknown[] | null
  status: CTMSStatus
  archived_at?: string | null
  created_at: string
  updated_at: string
}

export interface CTMSOperationalStudyPayload {
  phase: string
  study_type: string
  main_purpose: string
  therapeutic_area?: string | null
  program?: string | null
  indication?: string | null
  study_description?: string | null
  investigational_product?: string | null
  blind_method: string
  randomized: boolean
  expected_subject_count: number
  language: string
  expected_site_count: number
  construction_period: string
  planned_start_date: string
  planned_end_date: string
  actual_start_date?: string | null
  actual_end_date?: string | null
  study_currency: string
  exchange_date?: string | null
  query_expected_days?: number | null
  operational_owner_id?: string | null
  planning_metadata?: Record<string, unknown>
  readiness_criteria?: Record<string, unknown>
  status?: CTMSStatus
  correlation_id?: string
}

export type CTMSOperationalStudyUpdate = Partial<CTMSOperationalStudyPayload>

export type CTMSManagedEntityType = 'country' | 'site' | 'depot' | 'staff' | 'participating_organization' | 'investigational_product'
export type CTMSReferenceCategory = 'country' | 'participating_organization_type' | 'therapeutic_area' | 'indication' | 'milestone_type' | 'project_status'

export type CTMSProjectScopeLevel = 'study' | 'country' | 'site'

export interface CTMSReferenceValue {
  id: string
  category: CTMSReferenceCategory
  code: string
  label: string
  description?: string | null
  sort_order: number
  active: boolean
  created_at: string
  updated_at: string
}

export interface CTMSReferenceValuePayload {
  category: CTMSReferenceCategory
  code: string
  label: string
  description?: string | null
  sort_order?: number
}

export interface CTMSManagedEntity {
  id: string
  entity_type: CTMSManagedEntityType
  code: string
  name: string
  canonical_site_id?: string | null
  attributes: Record<string, unknown>
  active: boolean
  created_at: string
  updated_at: string
}

export interface CTMSManagedSitePayload {
  name: string
  country?: string | null
  state: string
  city: string
  phone?: string | null
  fax?: string | null
  zip_code?: string | null
  email?: string | null
  address?: string | null
}

export interface CTMSStudyEntityAssignment {
  id: string
  study_id: string
  entity_id: string
  entity: CTMSManagedEntity
  attributes: Record<string, unknown>
  created_at: string
}

export interface CTMSStudyPlan {
  id: string
  study_id: string
  title: string
  objective?: string | null
  milestone_id?: string | null
  scope_level: CTMSProjectScopeLevel
  country_code?: string | null
  site_id?: string | null
  planning_scope?: Record<string, unknown>
  owner_id?: string | null
  assignee_role_id?: string | null
  assignee_user_id?: string | null
  start_at?: string | null
  due_at?: string | null
  status?: CTMSStatus | null
  correlation_id?: string
  created_at: string
  updated_at: string
}

export interface CTMSStudyPlanPayload {
  title: string
  objective?: string | null
  milestone_id?: string | null
  scope_level?: CTMSProjectScopeLevel
  country_code?: string | null
  site_id?: string | null
  planning_scope?: Record<string, unknown>
  owner_id?: string | null
  assignee_role_id?: string | null
  assignee_user_id?: string | null
  start_at?: string | null
  due_at?: string | null
  status?: CTMSStatus | null
  correlation_id?: string
}

export interface CTMSProjectMilestone {
  id: string
  study_id: string
  title: string
  description?: string | null
  milestone_type: string
  scope_level: CTMSProjectScopeLevel
  country_code?: string | null
  site_id?: string | null
  planned_at?: string | null
  completed_at?: string | null
  owner_id?: string | null
  notes?: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface CTMSProjectMilestonePayload {
  title: string
  description?: string | null
  milestone_type: string
  scope_level?: CTMSProjectScopeLevel
  country_code?: string | null
  site_id?: string | null
  planned_at?: string | null
  status?: string
}

export interface CTMSProjectOption { id: string; label: string; secondary_label?: string | null; country_code?: string | null }
export interface CTMSProjectManagementOptions { users: CTMSProjectOption[]; roles: CTMSProjectOption[]; sites: CTMSProjectOption[] }

export interface CTMSOperationalSite {
  id: string
  site_id: string
  study_id?: string | null
  status: CTMSStatus
  monitoring_readiness?: string | null
  responsible_role?: string | null
  planned_activation_date?: string | null
  created_at: string
  updated_at: string
}

export interface CTMSOperationalSitePayload {
  study_id?: string | null
  monitoring_readiness?: string | null
  responsible_role?: string | null
  planned_activation_date?: string | null
  status?: CTMSStatus
  correlation_id?: string
}

export interface CTMSActivationAction {
  id: string
  study_id: string
  site_id: string
  action_type: string
  status: CTMSStatus
  responsible_role?: string | null
  responsible_user_id?: string | null
  planned_date?: string | null
  completion_criteria?: string | null
  completion_evidence?: string | null
  completed_at?: string | null
  completed_by?: string | null
  created_at: string
  updated_at: string
}

export interface CTMSActivationActionPayload {
  study_id?: string | null
  action_type: string
  responsible_role?: string | null
  responsible_user_id?: string | null
  planned_date?: string | null
  completion_criteria?: string | null
  correlation_id?: string
}

export interface CTMSStatusTransitionPayload {
  status: string
  reason?: string
}

export interface CTMSTransitionOption {
  status: string
  requires_reason?: boolean
  reason_label?: string
}

export interface CTMSTransitionResult<T> {
  resource: T
  current_status: string
  allowed_transitions: CTMSTransitionOption[]
  meta?: CTMSCorrelationMetadata
}

export interface CTMSEnrollmentTarget {
  id: string
  study_id: string
  site_id?: string | null
  target_type: CTMSStatus
  target_quantity: number
  planning_period_start: string
  planning_period_end: string
  dimension?: Record<string, unknown>
  owner_id?: string | null
  status: CTMSStatus
  created_at: string
  updated_at: string
}

export interface CTMSEnrollmentTargetPayload {
  study_id: string
  site_id?: string | null
  target_type: string
  target_quantity: number
  planning_period_start: string
  planning_period_end: string
  dimension?: Record<string, unknown>
  owner_id?: string | null
  status?: CTMSStatus
}

export interface CTMSOperationalMilestone {
  id: string
  study_id: string
  site_id?: string | null
  subject_id: string
  approved_pseudonym?: string | null
  approved_reference?: string | null
  milestone_type: string
  milestone_date: string
  status: CTMSStatus
  created_at: string
  updated_at: string
}

export interface CTMSOperationalMilestonePayload {
  study_id: string
  site_id?: string | null
  subject_id: string
  approved_pseudonym?: string | null
  approved_reference?: string | null
  milestone_type: string
  milestone_date: string
  status: CTMSStatus
}

export interface CTMSMonitoringPlan {
  id: string
  study_id: string
  site_id?: string | null
  name: string
  description?: string | null
  status: CTMSStatus
  current_version_id?: string | null
  retention_state?: string | null
  correlation_id?: string | null
  created_at: string
  updated_at: string
  allowed_transitions?: CTMSTransitionOption[]
}

export interface CTMSMonitoringPlanVersion {
  id: string
  plan_id: string
  study_id?: string
  site_id?: string | null
  version_number: number
  version?: number
  status: CTMSStatus
  objectives?: string | null
  activity_types?: string[]
  frequency?: string | null
  frequency_value?: number | null
  frequency_unit?: string | null
  cadence?: string | null
  responsibilities?: Record<string, unknown>
  scope?: Record<string, unknown>
  completion_criteria?: string | null
  risk_level?: string | null
  risk_strategy?: string | null
  monitoring_strategy?: string | null
  risk_threshold?: string | null
  thresholds?: Record<string, unknown>
  amendment_reason?: string | null
  published_at?: string | null
  correlation_id?: string | null
  created_at?: string
  updated_at?: string
  allowed_transitions?: CTMSTransitionOption[]
  rules?: CTMSMonitoringRule[]
}

export interface CTMSMonitoringRule {
  id: string
  plan_version_id: string
  visit_type: string
  frequency_value?: number | null
  frequency_unit?: string | null
  trigger?: string | null
  allowed_modalities: string[]
  expected_duration_hours?: number | null
  required_activities: Array<string | { key?: string; requirement: string; plan_reference?: string | null }>
  report_due_days: number
  sort_order: number
}

export interface CTMSMonitoringPlanVersionPayload {
  objectives?: string | null
  activity_types?: string[]
  frequency?: string | null
  frequency_value?: number | null
  frequency_unit?: string | null
  cadence?: string | null
  responsibilities?: Record<string, unknown>
  scope?: Record<string, unknown>
  completion_criteria?: string | null
  risk_level?: string | null
  risk_strategy?: string | null
  monitoring_strategy?: string | null
  risk_threshold?: string | null
  thresholds?: Record<string, unknown>
  visit_rules?: Array<{
    visit_type: string
    frequency_value?: number | null
    frequency_unit?: string | null
    trigger?: string | null
    allowed_modalities?: string[]
    expected_duration_hours?: number | null
    required_activities?: string[]
    report_due_days?: number
    sort_order?: number
  }>
}

export interface CTMSMonitoringPlanPayload {
  study_id?: string
  name: string
  description?: string | null
  site_id?: string | null
  version?: CTMSMonitoringPlanVersionPayload | null
  correlation_id?: string
}

export interface CTMSMonitoringPlanAmendPayload {
  reason: string
  changes: CTMSMonitoringPlanVersionPayload
  correlation_id?: string
}

export interface CTMSMonitoringActivity {
  id: string
  plan_version_id?: string
  study_id: string
  site_id?: string | null
  activity_type: string
  visit_code?: string | null
  modality: string
  planned_date: string
  actual_start_at?: string | null
  actual_end_at?: string | null
  assigned_cra_id?: string | null
  status: CTMSStatus
  completion_evidence?: Record<string, unknown> | string | null
  completion_notes?: string | null
  completed_at?: string | null
  cancellation_reason?: string | null
  cancelled_at?: string | null
  edc_visit_instance_id?: string | null
  attachments?: CTMSAttachment[]
  attachment_constraints?: CTMSAttachmentConstraints
  correlation_id?: string | null
  updated_at: string
  created_at: string
  allowed_transitions?: CTMSTransitionOption[]
}

export interface CTMSMonitoringActivityPayload {
  plan_id: string
  site_id?: string | null
  activity_type: string
  modality?: string
  planned_date: string
  assigned_cra_id?: string | null
  edc_visit_instance_id?: string | null
  correlation_id?: string
}

export interface CTMSMonitoringActivityAssignPayload {
  assigned_cra_id: string
  correlation_id?: string
}

export interface CTMSMonitoringActivityReschedulePayload {
  planned_date: string
  reason: string
  correlation_id?: string
}

export interface CTMSMonitoringActivityCompletePayload {
  evidence: Record<string, unknown> | string
  notes?: string | null
  correlation_id?: string
}

export interface CTMSMonitoringActivityCancelPayload {
  reason: string
  correlation_id?: string
}

export type CTMSChecklistResult = 'Pending' | 'Completed' | 'Not Completed' | 'Not Applicable'

export interface CTMSMonitoringChecklistItem {
  id: string
  visit_id: string
  rule_id?: string | null
  study_id: string
  site_id?: string | null
  requirement_key: string
  requirement: string
  plan_reference?: string | null
  result: CTMSChecklistResult
  review_details?: string | null
  observations?: string | null
  subject_reference?: string | null
  record_reference?: string | null
  evidence_references: string[]
  completed_at?: string | null
  completed_by?: string | null
  sort_order: number
}

export interface CTMSMonitoringReport {
  id: string
  visit_id: string
  previous_report_id?: string | null
  study_id: string
  site_id?: string | null
  version_number: number
  status: 'Draft' | 'Submitted' | 'Under Review' | 'Revision Required' | 'Approved' | 'Finalized'
  content: Record<string, unknown>
  reviewer_comments?: string | null
  submitted_at?: string | null
  approved_at?: string | null
  finalized_at?: string | null
  controlled_snapshot?: Record<string, unknown> | null
  document_reference?: string | null
  created_at?: string
  updated_at?: string
}

export interface CTMSMonitoringActionItem {
  id: string
  finding_id: string
  title: string
  description?: string | null
  owner_id?: string | null
  responsible_party?: string | null
  due_date?: string | null
  status: string
  completion_evidence: Record<string, unknown>
  completed_at?: string | null
}

export interface CTMSMonitoringFinding {
  id: string
  finding_code: string
  study_id: string
  site_id?: string | null
  visit_id?: string | null
  report_id?: string | null
  category: string
  severity: 'Critical' | 'Major' | 'Minor' | 'Observation'
  description: string
  responsible_party?: string | null
  owner_id?: string | null
  due_date?: string | null
  status: 'Open' | 'Action Assigned' | 'In Progress' | 'Pending Verification' | 'Closed' | 'Cancelled'
  capa_required: boolean
  capa_reference?: string | null
  resolution?: string | null
  actions: CTMSMonitoringActionItem[]
  created_at: string
  updated_at: string
}

export interface CTMSTask {
  id: string
  study_id: string
  site_id?: string | null
  title: string
  description?: string | null
  owner_id?: string | null
  due_date?: string | null
  priority?: string | null
  status: CTMSStatus
  query_id?: string | null
  query_summary?: string | null
  attachments?: CTMSAttachment[]
  attachment_constraints?: CTMSAttachmentConstraints
  correlation_id?: string | null
  updated_at: string
  created_at: string
  allowed_transitions?: CTMSTransitionOption[]
}

export interface CTMSTaskPayload {
  study_id?: string
  site_id?: string | null
  title: string
  description?: string | null
  owner_id?: string | null
  due_date?: string | null
  priority?: string
  status?: CTMSStatus
  query_id?: string | null
  query_summary?: string | null
  correlation_id?: string
}

export interface CTMSQueryFollowUpPayload {
  title?: string | null
  approved_summary?: string | null
  owner_id?: string | null
  due_date?: string | null
  priority?: string
}

export interface CTMSTaskUpdatePayload {
  title?: string
  description?: string | null
  owner_id?: string | null
  due_date?: string | null
  priority?: string
  correlation_id?: string
}

export interface CTMSTaskTransitionPayload {
  status: string
  reason: string
  correlation_id?: string
}

export interface CTMSContact {
  id: string
  study_id: string
  site_id?: string | null
  name: string
  role?: string | null
  organization?: string | null
  channels?: Record<string, unknown>
  owner_id?: string | null
  status: CTMSStatus
  correlation_id?: string | null
  created_at: string
  updated_at: string
  allowed_transitions?: CTMSTransitionOption[]
}

export interface CTMSContactPayload {
  study_id?: string
  site_id?: string | null
  name: string
  role?: string | null
  organization?: string | null
  channels?: Record<string, string>
  owner_id?: string | null
  status?: CTMSStatus
  correlation_id?: string
}

export interface CTMSContactTransitionPayload {
  status: string
  reason: string
  correlation_id?: string
}

export interface CTMSProjection {
  id: string
  study_id?: string | null
  site_id?: string | null
  subject_id?: string | null
  source_module: string
  source_record_id: string
  projection_type: string
  source_version?: string | number | null
  rule_version?: string | number | null
  source_timestamp?: string | null
  source_sequence?: number | null
  visit_instance_id?: string | null
  payload: Record<string, unknown>
  status: CTMSStatus
  projected_at: string
  correlation_id?: string | null
  freshness?: 'current' | 'stale' | 'unknown' | string
  read_only?: boolean
}

export interface CTMSDashboardMetricGroup {
  [key: string]: unknown
  status?: Record<string, number>
  total?: number
  count?: number
  target?: number
  actual?: number
  variance?: number
  overdue?: number
  upcoming?: number
  active?: number
}

export interface CTMSOperationalDashboard {
  enrollment?: CTMSDashboardMetricGroup & {
    targets?: Record<string, { target: number; actual: number; variance: number }>
    target_count?: number
  }
  readiness?: CTMSDashboardMetricGroup & {
    study_status?: CTMSStatus | null
    criteria?: Record<string, number>
    required_total?: number
    required_met?: number
    completion_percentage?: number
  }
  activation?: CTMSDashboardMetricGroup & {
    site_status?: Record<string, number>
    actions?: Record<string, number>
    active_sites?: number
  }
  monitoring?: CTMSDashboardMetricGroup
  tasks?: CTMSDashboardMetricGroup
  milestones?: CTMSDashboardMetricGroup
  contacts?: CTMSDashboardMetricGroup
  [key: string]: unknown
}

export interface CTMSQualitySignal {
  projection_id?: string
  signal_type?: string | null
  value?: string | number | null
  numerator?: number | null
  denominator?: number | null
  source_module?: string
  source_record_id?: string | null
  source_timestamp?: string | null
  projected_at?: string | null
  source_version?: string | number | null
  freshness_seconds?: number | null
  freshness?: 'current' | 'fresh' | 'stale' | 'unknown' | string
  rule_version?: string | number | null
  ownership?: 'projected' | string
  read_only?: boolean
}

export interface CTMSDashboard {
  study_id?: string
  site_id?: string | null
  operational: CTMSOperationalDashboard
  projected_clinical: CTMSQualitySignal[]
  generated_at?: string
}

export type CTMSReportItem = Record<string, unknown>

export interface CTMSReport {
  study_id?: string
  site_id?: string | null
  category?: string | null
  report_type?: string
  label?: string | null
  data_source?: 'ctms' | 'approved_projection' | string
  read_only?: boolean
  items: CTMSReportItem[]
  /** Legacy alias accepted while older API deployments return rows. */
  rows?: CTMSReportItem[]
  page?: number
  page_size?: number
  total?: number
  next_cursor?: string | null
  previous_cursor?: string | null
  totals: Record<string, unknown>
  generated_at?: string
  source_timestamp?: string | null
  freshness?: 'current' | 'stale' | 'unknown' | string
  [key: string]: unknown
}

export type CTMSStudyOperationResource = 'contract' | 'pricing_template' | 'payment' | 'ract' | 'kri' | 'monitoring_issue' | 'protocol_deviation' | 'icf' | 'tracking_log'

export interface CTMSStudyOperationRecord {
  id: string
  study_id: string
  site_id?: string | null
  subject_id?: string | null
  reference_id?: string | null
  resource_type: CTMSStudyOperationResource
  title: string
  record_subtype?: string | null
  status: string
  owner_id?: string | null
  start_at?: string | null
  end_at?: string | null
  amount?: string | number | null
  currency?: string | null
  details: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CTMSStudyOperationCreate {
  title: string
  site_id?: string
  subject_id?: string
  reference_id?: string
  record_subtype?: string
  status?: string
  owner_id?: string
  start_at?: string
  end_at?: string
  amount?: number
  currency?: string
  details?: Record<string, unknown>
}

export type CTMSFinancialDirection = 'receivable' | 'payable'
export type CTMSContractType = 'sponsor_agreement' | 'clinical_trial_agreement' | 'vendor_agreement'

export interface CTMSFinancialOverview {
  study_id: string
  currency?: string | null
  approved_budget: string | number
  contracted: string | number
  earned: string | number
  holdback: string | number
  approved: string | number
  invoiced: string | number
  paid: string | number
  outstanding: string | number
  overdue: string | number
}

export interface CTMSFinancialContract {
  id: string
  study_id: string
  site_id?: string | null
  contract_number: string
  title: string
  contract_type: CTMSContractType
  direction: CTMSFinancialDirection
  party_id?: string | null
  organization_id?: string | null
  party_name: string
  country_code?: string | null
  status: string
  currency: string
  owner_id?: string | null
  created_at: string
  updated_at: string
}

export interface CTMSFinancialContractCreate {
  contract_number: string
  title: string
  contract_type: CTMSContractType
  direction: CTMSFinancialDirection
  party_name: string
  party_id?: string
  organization_id?: string
  site_id?: string
  country_code?: string
  currency: string
  owner_id?: string
}

export interface CTMSContractVersion {
  id: string
  contract_id: string
  version_number: number
  amendment_reason?: string | null
  effective_from: string
  effective_to?: string | null
  status: string
  total_value: string | number
  holdback_percent: string | number
  payment_window_days: number
  invoice_required: boolean
  tax_treatment?: string | null
  terms_snapshot_json?: Record<string, unknown>
  executed_at?: string | null
  executed_by?: string | null
  created_by?: string
  created_at?: string
}

export interface CTMSPaymentTerm {
  id: string
  version_id: string
  code: string
  description: string
  payment_method: 'fixed' | 'visit_based' | 'crf_based' | 'invoice_based' | 'lab_based' | 'quantity_based' | 'procedure_based' | 'milestone_based' | 'recurring' | 'pass_through' | 'manual_adjustment'
  trigger_code: string
  unit_rate: string | number
  cost_category?: string | null
  billing_unit?: string | null
  visit_definition_id?: string | null
  form_definition_id?: string | null
  lab_code?: string | null
  invoice_category?: string | null
  dimensions_json?: Record<string, string>
  holdback_percent?: string | number | null
  frequency?: string | null
  quantity_cap?: string | number | null
  amount_cap?: string | number | null
  active?: boolean
  created_by?: string
  created_at?: string
}

export interface CTMSFinancialDefinitionOption {
  id: string
  code: string
  label: string
  version: string
}

export interface CTMSFinancialConfigurationOptions {
  visits: CTMSFinancialDefinitionOption[]
  forms: CTMSFinancialDefinitionOption[]
  payment_rules: {
    code: string
    label: string
    charge_item_count: number
    methods: CTMSPaymentTerm['payment_method'][]
  }[]
}

export interface CTMSPayableItem {
  id: string
  study_id: string
  contract_id: string
  contract_version_id: string
  contract_term_id: string
  event_id: string
  gross_amount: string | number
  holdback_amount: string | number
  net_amount: string | number
  currency: string
  status: string
  calculation_snapshot: Record<string, unknown>
  approved_at?: string | null
  approved_by?: string | null
  created_at: string
}

export interface CTMSFinancialEventCreate {
  site_id?: string
  subject_id?: string
  visit_instance_id?: string
  source_type: string
  source_id?: string
  trigger_code: string
  event_date: string
  quantity: number
  verification_status?: 'verified' | 'approved'
  idempotency_key: string
  evidence?: Record<string, unknown>
}

export interface CTMSFinancialCalculation {
  event: { id: string; idempotency_key: string; trigger_code: string }
  payable_items: CTMSPayableItem[]
  replayed: boolean
}

export interface CTMSFinancialInvoice {
  id: string
  study_id: string
  contract_id: string
  party_name: string
  invoice_number: string
  direction: CTMSFinancialDirection
  invoice_date: string
  due_date: string
  amount: string | number
  currency: string
  status: string
  created_at: string
}

export interface CTMSFinancialInvoiceCreate {
  contract_id: string
  party_name: string
  invoice_number: string
  direction: CTMSFinancialDirection
  invoice_date: string
  due_date: string
  amount: number
  currency: string
  lines: { payable_item_id: string; amount: number }[]
}

export interface CTMSFinancialPayment {
  id: string
  study_id: string
  party_name: string
  direction: CTMSFinancialDirection
  payment_date: string
  amount: string | number
  currency: string
  reference: string
  status: string
  reversal_of_id?: string | null
  created_at: string
}

export interface CTMSFinancialPaymentCreate {
  party_name: string
  direction: CTMSFinancialDirection
  payment_date: string
  amount: number
  currency: string
  reference: string
  allocations: { invoice_id: string; allocated_amount: number }[]
}

export interface CTMSFinancialBudgetLine {
  id: string
  version_id: string
  category: string
  description: string
  quantity: string | number
  unit_cost: string | number
  planned_amount: string | number
}

export interface CTMSFinancialBudgetVersion {
  id: string
  budget_id: string
  version_number: number
  status: string
  effective_from: string
  reason?: string | null
  approved_at?: string | null
  approved_by?: string | null
  total: string | number
  lines: CTMSFinancialBudgetLine[]
  created_at: string
}

export interface CTMSFinancialBudget {
  id: string
  study_id: string
  name: string
  scope: 'study' | 'site' | 'vendor'
  currency: string
  status: string
  current_version?: CTMSFinancialBudgetVersion | null
  created_at: string
}

export interface CTMSFinancialBudgetPayload {
  name: string
  scope: 'study' | 'site' | 'vendor'
  currency: string
  effective_from: string
  reason?: string
  lines: { category: string; description: string; quantity: number; unit_cost: number }[]
}

export interface CTMSFinancialAuditEntry {
  id: string
  entity_type: string
  entity_id: string
  action: string
  actor_id?: string | null
  timestamp: string
  reason?: string | null
  changed_fields?: string[] | null
}

export interface CTMSFinancialReport extends CTMSFinancialOverview {
  budget_variance: string | number
  contract_utilization_percent: string | number
  invoice_coverage_percent: string | number
  aging: Record<string, string | number>
  cash_flow_forecast: { period: string; amount: string | number }[]
}

export type CTMSExportFormat = 'csv' | 'json' | 'excel'
export type CTMSExportStatus = 'queued' | 'running' | 'completed' | 'failed' | 'expired' | string

/** Server allowlist of CTMS-owned records that may appear in an operational export. */
export type CTMSOperationalRecordType =
  | 'operational_study'
  | 'study_plan'
  | 'enrollment_plan'
  | 'readiness_criterion'
  | 'study_milestone'
  | 'operational_site'
  | 'activation_action'
  | 'enrollment_target'
  | 'operational_milestone'
  | 'monitoring_plan'
  | 'monitoring_plan_version'
  | 'monitoring_activity'
  | 'operational_task'
  | 'operational_contact'

export interface CTMSExportFilters {
  siteId?: string
  recordTypes?: string[]
  statuses?: string[]
  dateFrom?: string
  dateTo?: string
  includeArchived?: boolean
  includeProjections?: boolean
  projectionTypes?: string[]
  page?: number
  pageSize?: number
}

export interface CTMSExportRequest {
  exportType: CTMSExportFormat
  filters?: CTMSExportFilters
}

/** Serialize only fields accepted by OperationalExportFilters on the CTMS API. */
export function serializeCTMSExportRequest(request: CTMSExportRequest): Record<string, unknown> {
  const filters = request.filters
  return {
    export_type: request.exportType,
    ...(filters ? {
      filters: {
        ...(filters.siteId ? { site_id: filters.siteId } : {}),
        ...(filters.recordTypes?.length ? { record_types: filters.recordTypes } : {}),
        ...(filters.statuses?.length ? { statuses: filters.statuses } : {}),
        ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
        ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
        ...(filters.includeArchived !== undefined ? { include_archived: filters.includeArchived } : {}),
        ...(filters.includeProjections !== undefined ? { include_projections: filters.includeProjections } : {}),
        ...(filters.projectionTypes?.length ? { projection_types: filters.projectionTypes } : {}),
        ...(filters.page !== undefined ? { page: filters.page } : {}),
        ...(filters.pageSize !== undefined ? { page_size: filters.pageSize } : {}),
      },
    } : {}),
  }
}

/** Convert a server filter object back to the typed request model for retry. */
export function parseCTMSExportFilters(value: unknown): CTMSExportFilters {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const filters = value as Record<string, unknown>
  const strings = (input: unknown): string[] | undefined => {
    if (!Array.isArray(input)) return undefined
    return input.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
  }
  const result: CTMSExportFilters = {}
  if (typeof filters.site_id === 'string' && filters.site_id) result.siteId = filters.site_id
  const recordTypes = strings(filters.record_types)
  if (recordTypes?.length) result.recordTypes = recordTypes
  const statuses = strings(filters.statuses)
  if (statuses?.length) result.statuses = statuses
  if (typeof filters.date_from === 'string' && filters.date_from) result.dateFrom = filters.date_from
  if (typeof filters.date_to === 'string' && filters.date_to) result.dateTo = filters.date_to
  if (typeof filters.include_archived === 'boolean') result.includeArchived = filters.include_archived
  if (typeof filters.include_projections === 'boolean') result.includeProjections = filters.include_projections
  const projectionTypes = strings(filters.projection_types)
  if (projectionTypes?.length) result.projectionTypes = projectionTypes
  if (typeof filters.page === 'number' && Number.isInteger(filters.page) && filters.page > 0) result.page = filters.page
  if (typeof filters.page_size === 'number' && Number.isInteger(filters.page_size) && filters.page_size > 0) result.pageSize = filters.page_size
  return result
}

export interface CTMSExport {
  id: string
  study_id: string
  module?: string
  content_owner?: string
  export_type: string
  status: CTMSExportStatus
  filters?: Record<string, unknown> | null
  file_path?: string | null
  file_size?: number | null
  error_message?: string | null
  correlation_id?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  expires_at?: string | null
  updated_at?: string
}

export type CTMSExportJob = CTMSExport

export type CTMSAttachmentRetentionState = 'active' | 'soft_deleted' | 'archived' | 'expired' | string

export interface CTMSAttachment {
  id: string
  module: 'CTMS' | string
  attachment_type: 'Operational_Attachment' | string
  object_type: string
  object_id: string
  study_id: string
  site_id?: string | null
  filename: string
  content_type: string
  size_bytes: number
  storage_key?: string
  uploaded_by?: string
  uploaded_at: string
  deleted_at?: string | null
  retention_until?: string | null
  retention_state?: CTMSAttachmentRetentionState | null
  correlation_id?: string | null
  archived_at?: string | null
  restored_at?: string | null
}

export interface CTMSAttachmentConstraints {
  max_size_bytes: number
  allowed_content_types: string[]
  allowed_object_types: string[]
  retention_days?: number
  ownership: 'CTMS' | string
  attachment_type: 'Operational_Attachment' | string
}

export interface CTMSAttachmentUploadProgress {
  loaded: number
  total?: number
  percentage: number
}

export interface CTMSAttachmentUploadPayload {
  studyId: string
  objectType: string
  objectId: string
  file: File | Blob
  filename?: string
  contentType?: string
  onProgress?: (progress: CTMSAttachmentUploadProgress) => void
}

export interface CTMSAttachmentDeletePayload {
  reason: string
}

export interface CTMSAttachmentRestorePayload {
  reason: string
}

export const CTMS_OPERATIONAL_ATTACHMENT_PARENT_TYPES = [
  'operational',
  'operational_study',
  'operational_site',
  'study_plan',
  'enrollment_target',
  'milestone',
  'activation_action',
  'monitoring_plan',
  'monitoring_activity',
  'task',
  'contact',
  'operational_task',
  'operational_contact',
  'financial_contract',
] as const

const CTMS_CLINICAL_ATTACHMENT_PARENT_TYPES = new Set([
  'field', 'form', 'visit', 'subject', 'site', 'study', 'query', 'clinical_attachment', 'clinical_export',
])

export function isCTMSOperationalAttachmentParent(objectType: string): boolean {
  const normalized = objectType.trim().replaceAll('-', '_').toLowerCase()
  return CTMS_OPERATIONAL_ATTACHMENT_PARENT_TYPES.includes(normalized as typeof CTMS_OPERATIONAL_ATTACHMENT_PARENT_TYPES[number]) && !CTMS_CLINICAL_ATTACHMENT_PARENT_TYPES.has(normalized)
}

export function isCTMSOperationalAttachment(value: Partial<CTMSAttachment> | null | undefined): value is CTMSAttachment {
  return Boolean(value && value.module === 'CTMS' && value.attachment_type === 'Operational_Attachment' && typeof value.object_type === 'string' && isCTMSOperationalAttachmentParent(value.object_type))
}

export function validateCTMSAttachmentMetadata(
  file: Pick<File, 'name' | 'type' | 'size'>,
  constraints: CTMSAttachmentConstraints,
): string | undefined {
  if (constraints.ownership !== 'CTMS' || constraints.attachment_type !== 'Operational_Attachment') return 'The server did not provide operational attachment constraints.'
  if (!file.name.trim() || file.name.length > 255 || /[\\\\/]/.test(file.name)) return 'Choose a file with a valid name.'
  if (file.size > constraints.max_size_bytes) return `The selected file exceeds the ${Math.ceil(constraints.max_size_bytes / 1024 / 1024)} MB size limit.`
  const contentType = file.type.split(';', 1)[0].trim().toLowerCase()
  if (!contentType || !constraints.allowed_content_types.some((allowed) => allowed.toLowerCase() === contentType)) return 'This file type is not permitted for CTMS operational content.'
  return undefined
}

export interface CTMSHealth {
  worker_status?: string
  worker_available?: boolean
  pending_event_count?: number
  failed_event_count?: number
  conflict_count?: number
  projection_lag?: number | string
  last_successful_processing_time?: string | null
  request_id?: string | null
  [key: string]: unknown
}

export interface CTMSCoordinationEvent {
  id: string
  event_id: string
  event_type: string
  aggregate_type?: string | null
  aggregate_id?: string | null
  source_module?: string | null
  target_module?: string | null
  status: CTMSStatus
  correlation_id?: string | null
  source_version?: string | null
  source_sequence?: number | null
  current_version?: string | null
  rule_version?: number | null
  resulting_projection_id?: string | null
  outcome?: string | null
  reason?: string | null
  accepted_at?: string | null
  processed_at?: string | null
}

export interface CTMSFailedEvent {
  id: string
  event_id: string
  event_type: string
  source_module?: string | null
  target_module?: string | null
  aggregate_type?: string | null
  aggregate_id?: string | null
  status: CTMSStatus
  reason_code: string
  sanitized_details: Record<string, unknown>
  correlation_id?: string | null
  source_version?: string | null
  current_version?: string | null
  created_at: string
  updated_at?: string | null
  available_actions?: string[]
}

export interface CTMSConflict {
  id: string
  event_id: string
  entity_type: string
  field_path?: string | null
  conflict_type: string
  source_version?: string | null
  current_version?: string | null
  status: CTMSStatus
  policy?: string | null
  sanitized_details: Record<string, unknown>
  correlation_id?: string | null
  created_at: string
  resolved_at?: string | null
  policy_choices?: string[]
  available_actions?: string[]
}

export interface CTMSReplayPayload {
  reason: string
}

export interface CTMSConflictResolutionPayload {
  policy: string
  reason: string
  selectedValue?: string | number | boolean | null
}

export interface CTMSCapabilityManifest {
  module: 'EDC' | 'CTMS'
  enabled: boolean
  phase: CTMSPhase
  capabilities: string[]
  environment?: Record<string, unknown>
  platform_capabilities?: Record<string, boolean>
}

export const ctmsKeys = {
  all: ['ctms'] as const,
  capabilities: (context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'capabilities'] as const, context),
  list: (resource: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'list', resource] as const, context),
  detail: (resource: string, id: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, resource, 'detail', id] as const, context),
  studyProfile: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'study-profile', studyId] as const, scopedContext(context, { studyId })),
  entities: (studyId?: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'entities', studyId ?? 'global'] as const, context),
  referenceValues: (category?: CTMSReferenceCategory, active: boolean | null = true) => [...ctmsKeys.all, 'reference-values', category ?? 'all', active] as const,
  studyEntities: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'study-entities', studyId] as const, scopedContext(context, { studyId })),
  plans: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'plans', studyId] as const, scopedContext(context, { studyId })),
  projectMilestones: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'project-milestones', studyId] as const, scopedContext(context, { studyId })),
  projectOptions: (studyId: string) => [...ctmsKeys.all, 'project-options', studyId] as const,
  siteProfile: (siteId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'site-profile', siteId] as const, scopedContext(context, { siteId })),
  activation: (siteId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'activation', siteId] as const, scopedContext(context, { siteId })),
  targets: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'targets', studyId] as const, scopedContext(context, { studyId })),
  milestones: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'milestones', studyId] as const, scopedContext(context, { studyId })),
  monitoringPlans: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'monitoring-plans', studyId] as const, scopedContext(context, { studyId })),
  monitoringPlanVersions: (planId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'monitoring-plan-versions', planId] as const, context),
  monitoringActivities: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'monitoring-activities', studyId] as const, scopedContext(context, { studyId })),
  monitoringChecklist: (visitId: string) => [...ctmsKeys.all, 'monitoring-checklist', visitId] as const,
  monitoringReports: (visitId: string) => [...ctmsKeys.all, 'monitoring-reports', visitId] as const,
  monitoringFindings: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'monitoring-findings', studyId] as const, scopedContext(context, { studyId })),
  tasks: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'tasks', studyId] as const, scopedContext(context, { studyId })),
  contacts: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'contacts', studyId] as const, scopedContext(context, { studyId })),
  projections: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'projections', studyId] as const, scopedContext(context, { studyId })),
  dashboard: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'dashboard', studyId] as const, scopedContext(context, { studyId })),
  siteDashboard: (siteId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'site-dashboard', siteId] as const, scopedContext(context, { siteId })),
  report: (studyId: string, type: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'report', studyId, type] as const, context ? { ...context, studyId, filters: { ...context.filters, reportType: context.filters?.reportType ?? type } } : undefined),
  catalogReport: (studyId: string, category: string, type: string) => [...ctmsKeys.all, 'catalog-report', studyId, category, type] as const,
  studyOperations: (studyId: string, resource: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'study-operations', studyId, resource] as const, scopedContext(context, { studyId })),
  financialOverview: (studyId: string) => [...ctmsKeys.all, 'financial-overview', studyId] as const,
  financialConfigurationOptions: (studyId: string, asOf?: string) => [...ctmsKeys.all, 'financial-configuration-options', studyId, asOf ?? 'all'] as const,
  financialContracts: (studyId: string) => [...ctmsKeys.all, 'financial-contracts', studyId] as const,
  contractVersions: (studyId: string, contractId: string) => [...ctmsKeys.all, 'financial-contract-versions', studyId, contractId] as const,
  paymentTerms: (studyId: string, versionId: string) => [...ctmsKeys.all, 'financial-payment-terms', studyId, versionId] as const,
  contractDocuments: (studyId: string, contractId: string) => [...ctmsKeys.all, 'financial-contract-documents', studyId, contractId] as const,
  contractAudit: (studyId: string, contractId: string) => [...ctmsKeys.all, 'financial-contract-audit', studyId, contractId] as const,
  financialBudgets: (studyId: string) => [...ctmsKeys.all, 'financial-budgets', studyId] as const,
  financialReport: (studyId: string) => [...ctmsKeys.all, 'financial-report', studyId] as const,
  financialPayables: (studyId: string) => [...ctmsKeys.all, 'financial-payables', studyId] as const,
  financialInvoices: (studyId: string) => [...ctmsKeys.all, 'financial-invoices', studyId] as const,
  financialPayments: (studyId: string) => [...ctmsKeys.all, 'financial-payments', studyId] as const,
  exports: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'exports', studyId] as const, scopedContext(context, { studyId })),
  exportJob: (id: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'exports', 'detail', id] as const, context),
  attachments: (objectType: string, objectId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'attachments', objectType, objectId] as const, context),
  attachment: (id: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'attachments', 'detail', id] as const, context),
  health: (context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'health'] as const, context),
  events: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'events', studyId] as const, scopedContext(context, { studyId })),
  failedEvents: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'failed-events', studyId] as const, scopedContext(context, { studyId })),
  conflicts: (studyId: string, context?: CTMSQueryContext) => withQueryContext([...ctmsKeys.all, 'conflicts', studyId] as const, scopedContext(context, { studyId })),
}

const list = async <T>(path: string, context?: CTMSQueryContext): Promise<CTMSList<T>> => (await api.get<CTMSList<T>>(appendCTMSQuery(path, context))).data
const item = async <T>(path: string, context?: CTMSQueryContext): Promise<T> => (await api.get<T>(appendCTMSQuery(path, context))).data
const post = async <T>(path: string, payload: unknown): Promise<T> => (await api.post<T>(path, payload)).data
const patch = async <T>(path: string, payload: unknown): Promise<T> => (await api.patch<T>(path, payload)).data

export const ctmsApi = {
  capabilities: (context?: CTMSQueryContext) => item<CTMSCapabilityManifest>('/ctms/capabilities', context),
  studyProfile: (studyId: string, context?: CTMSQueryContext) => item<CTMSOperationalStudy>(`/ctms/studies/${studyId}/operational-profile`, context),
  createStudyProfile: (studyId: string, payload: CTMSOperationalStudyPayload) => post<CTMSOperationalStudy>(`/ctms/studies/${studyId}/operational-profile`, payload),
  updateStudyProfile: (id: string, payload: CTMSOperationalStudyUpdate) => patch<CTMSOperationalStudy>(`/ctms/operational-studies/${id}`, payload),
  entities: (studyId?: string, context?: CTMSQueryContext) => list<CTMSManagedEntity>(studyId ? `/ctms/studies/${studyId}/available-entities` : '/ctms/entities', context),
  createStudySite: (studyId: string, payload: CTMSManagedSitePayload) => post<CTMSManagedEntity>(`/ctms/studies/${studyId}/sites`, payload),
  createEntity: (payload: { entity_type: CTMSManagedEntityType; code: string; name: string; canonical_site_id?: string; attributes?: Record<string, unknown> }) => post<CTMSManagedEntity>('/ctms/entities', payload),
  updateEntity: (id: string, payload: Partial<Pick<CTMSManagedEntity, 'code' | 'name' | 'attributes' | 'active'>>) => patch<CTMSManagedEntity>(`/ctms/entities/${id}`, payload),
  referenceValues: (category?: CTMSReferenceCategory, active: boolean | null = true) => {
    const params = new URLSearchParams({ page_size: '100' })
    if (category) params.set('category', category)
    if (active !== null) params.set('active', String(active))
    return list<CTMSReferenceValue>(`/ctms/reference-values?${params}`)
  },
  createReferenceValue: (payload: CTMSReferenceValuePayload) => post<CTMSReferenceValue>('/ctms/reference-values', payload),
  updateReferenceValue: (id: string, payload: Partial<Pick<CTMSReferenceValue, 'label' | 'description' | 'sort_order' | 'active'>>) => patch<CTMSReferenceValue>(`/ctms/reference-values/${id}`, payload),
  studyEntities: (studyId: string, context?: CTMSQueryContext) => list<CTMSStudyEntityAssignment>(`/ctms/studies/${studyId}/entities`, context),
  assignStudyEntity: (studyId: string, entityId: string, attributes: Record<string, unknown> = {}) => post<CTMSStudyEntityAssignment>(`/ctms/studies/${studyId}/entities`, { entity_id: entityId, attributes }),
  plans: (studyId: string, context?: CTMSQueryContext) => list<CTMSStudyPlan>(`/ctms/studies/${studyId}/plans`, context),
  createPlan: (studyId: string, payload: CTMSStudyPlanPayload) => post<CTMSStudyPlan>(`/ctms/studies/${studyId}/plans`, payload),
  updatePlan: (id: string, payload: Partial<CTMSStudyPlanPayload> & { reason: string }) => patch<CTMSStudyPlan>(`/ctms/study-plans/${id}`, payload),
  projectMilestones: (studyId: string, context?: CTMSQueryContext) => list<CTMSProjectMilestone>(`/ctms/studies/${studyId}/milestones`, context),
  createProjectMilestone: (studyId: string, payload: CTMSProjectMilestonePayload) => post<CTMSProjectMilestone>(`/ctms/studies/${studyId}/milestones`, payload),
  updateProjectMilestone: (id: string, payload: Partial<CTMSProjectMilestonePayload> & { reason: string }) => patch<CTMSProjectMilestone>(`/ctms/study-milestones/${id}`, payload),
  projectOptions: (studyId: string) => item<CTMSProjectManagementOptions>(`/ctms/studies/${studyId}/project-management/options`),
  siteProfile: (siteId: string, context?: CTMSQueryContext) => item<CTMSOperationalSite>(`/ctms/sites/${siteId}/operational-profile`, context),
  createSiteProfile: (siteId: string, payload: CTMSOperationalSitePayload) => post<CTMSOperationalSite>(`/ctms/sites/${siteId}/operational-profile`, payload),
  updateSiteProfile: (id: string, payload: Omit<CTMSOperationalSitePayload, 'study_id' | 'status'>) => patch<CTMSOperationalSite>(`/ctms/operational-sites/${id}`, payload),
  activation: (siteId: string, context?: CTMSQueryContext) => list<CTMSActivationAction>(`/ctms/sites/${siteId}/activation`, context),
  createActivationAction: (siteId: string, payload: CTMSActivationActionPayload) => post<CTMSActivationAction>(`/ctms/sites/${siteId}/activation`, payload),
  updateActivationAction: (id: string, payload: Partial<CTMSActivationActionPayload>) => patch<CTMSActivationAction>(`/ctms/activation-actions/${id}`, payload),
  transitionActivationAction: (id: string, payload: CTMSStatusTransitionPayload) => post<CTMSActivationAction>(`/ctms/activation-actions/${id}/transition`, payload),
  completeActivationAction: (id: string, payload: CTMSStatusTransitionPayload) => post<CTMSActivationAction>(`/ctms/activation-actions/${id}/complete`, payload),
  targets: (studyId: string, context?: CTMSQueryContext) => list<CTMSEnrollmentTarget>(`/ctms/studies/${studyId}/enrollment-targets`, context),
  createTarget: (studyId: string, payload: CTMSEnrollmentTargetPayload) => post<CTMSEnrollmentTarget>(`/ctms/studies/${studyId}/enrollment-targets`, payload),
  updateTarget: (id: string, payload: Partial<Omit<CTMSEnrollmentTargetPayload, 'study_id' | 'site_id' | 'target_type'>>) => patch<CTMSEnrollmentTarget>(`/ctms/enrollment-targets/${id}`, payload),
  milestones: (studyId: string, context?: CTMSQueryContext) => list<CTMSOperationalMilestone>(`/ctms/studies/${studyId}/operational-milestones`, context),
  createMilestone: (subjectId: string, payload: Omit<CTMSOperationalMilestonePayload, 'subject_id'>) => post<CTMSOperationalMilestone>(`/ctms/subjects/${subjectId}/operational-milestones`, { ...payload, subject_id: subjectId }),
  monitoringPlans: (studyId: string, context?: CTMSQueryContext) => list<CTMSMonitoringPlan>(`/ctms/studies/${studyId}/monitoring-plans`, context),
  createMonitoringPlan: (studyId: string, payload: Omit<CTMSMonitoringPlanPayload, 'study_id'>) => post<CTMSMonitoringPlan>(`/ctms/studies/${studyId}/monitoring-plans`, payload),
  updateMonitoringPlan: (id: string, payload: Omit<CTMSMonitoringPlanPayload, 'study_id' | 'site_id' | 'version'>) => patch<CTMSMonitoringPlan>(`/ctms/monitoring-plans/${id}`, payload),
  monitoringPlanVersions: (planId: string, context?: CTMSQueryContext) => list<CTMSMonitoringPlanVersion>(`/ctms/monitoring-plans/${planId}/versions`, context),
  publishMonitoringPlan: (id: string, payload: { correlation_id?: string } = {}) => post<CTMSMonitoringPlanVersion>(`/ctms/monitoring-plans/${id}/publish`, payload),
  amendMonitoringPlan: (id: string, payload: CTMSMonitoringPlanAmendPayload) => post<CTMSMonitoringPlanVersion>(`/ctms/monitoring-plans/${id}/amend`, payload),
  monitoringActivities: (studyId: string, context?: CTMSQueryContext) => list<CTMSMonitoringActivity>(`/ctms/studies/${studyId}/monitoring-activities`, context),
  createMonitoringActivity: (studyId: string, payload: Omit<CTMSMonitoringActivityPayload, 'study_id'>) => post<CTMSMonitoringActivity>(`/ctms/studies/${studyId}/monitoring-activities`, payload),
  updateMonitoringActivity: (id: string, payload: Partial<CTMSMonitoringActivityPayload>) => patch<CTMSMonitoringActivity>(`/ctms/monitoring-activities/${id}`, payload),
  assignMonitoringActivity: (id: string, payload: CTMSMonitoringActivityAssignPayload) => post<CTMSMonitoringActivity>(`/ctms/monitoring-activities/${id}/assign`, payload),
  rescheduleMonitoringActivity: (id: string, payload: CTMSMonitoringActivityReschedulePayload) => post<CTMSMonitoringActivity>(`/ctms/monitoring-activities/${id}/reschedule`, payload),
  completeMonitoringActivity: (id: string, payload: CTMSMonitoringActivityCompletePayload) => post<CTMSMonitoringActivity>(`/ctms/monitoring-activities/${id}/complete`, payload),
  cancelMonitoringActivity: (id: string, payload: CTMSMonitoringActivityCancelPayload) => post<CTMSMonitoringActivity>(`/ctms/monitoring-activities/${id}/cancel`, payload),
  startMonitoringActivity: (id: string) => post<CTMSMonitoringActivity>(`/ctms/monitoring-activities/${id}/start`, {}),
  monitoringChecklist: (visitId: string) => item<CTMSMonitoringChecklistItem[]>(`/ctms/monitoring-activities/${visitId}/checklist`),
  addMonitoringChecklistItem: (visitId: string, payload: { requirement_key: string; requirement: string; plan_reference?: string | null; sort_order?: number }) => post<CTMSMonitoringChecklistItem>(`/ctms/monitoring-activities/${visitId}/checklist`, payload),
  updateMonitoringChecklistItem: (id: string, payload: { result: CTMSChecklistResult; review_details?: string | null; observations?: string | null; subject_reference?: string | null; record_reference?: string | null; evidence_references?: string[] }) => patch<CTMSMonitoringChecklistItem>(`/ctms/monitoring-checklist-items/${id}`, payload),
  monitoringReports: (visitId: string) => item<CTMSMonitoringReport[]>(`/ctms/monitoring-activities/${visitId}/reports`),
  createMonitoringReport: (visitId: string, content: Record<string, unknown> = {}) => post<CTMSMonitoringReport>(`/ctms/monitoring-activities/${visitId}/reports`, { content }),
  updateMonitoringReport: (id: string, content: Record<string, unknown>) => patch<CTMSMonitoringReport>(`/ctms/monitoring-reports/${id}`, { content }),
  transitionMonitoringReport: (id: string, action: string, comments?: string, documentReference?: string) => post<CTMSMonitoringReport>(`/ctms/monitoring-reports/${id}/transition`, { action, comments, document_reference: documentReference }),
  monitoringFindings: (studyId: string, context?: CTMSQueryContext) => list<CTMSMonitoringFinding>(`/ctms/studies/${studyId}/monitoring-findings`, context),
  createMonitoringFinding: (studyId: string, payload: { site_id?: string | null; visit_id?: string | null; report_id?: string | null; category: string; severity: CTMSMonitoringFinding['severity']; description: string; responsible_party?: string | null; owner_id?: string | null; due_date?: string | null; capa_required?: boolean; capa_reference?: string | null }) => post<CTMSMonitoringFinding>(`/ctms/studies/${studyId}/monitoring-findings`, payload),
  transitionMonitoringFinding: (id: string, status: CTMSMonitoringFinding['status'], reason: string, resolution?: string) => post<CTMSMonitoringFinding>(`/ctms/monitoring-findings/${id}/transition`, { status, reason, resolution }),
  createMonitoringAction: (findingId: string, payload: { title: string; description?: string | null; owner_id?: string | null; responsible_party?: string | null; due_date?: string | null }) => post<CTMSMonitoringActionItem>(`/ctms/monitoring-findings/${findingId}/actions`, payload),
  completeMonitoringAction: (id: string, evidence: Record<string, unknown> | string) => post<CTMSMonitoringActionItem>(`/ctms/monitoring-actions/${id}/complete`, { evidence }),
  tasks: (studyId: string, context?: CTMSQueryContext) => list<CTMSTask>(`/ctms/studies/${studyId}/tasks`, context),
  task: (id: string, context?: CTMSQueryContext) => item<CTMSTask>(`/ctms/tasks/${id}`, context),
  createTask: (studyId: string, payload: Omit<CTMSTaskPayload, 'study_id'> & { study_id?: string }) => post<CTMSTask>(`/ctms/studies/${studyId}/tasks`, { ...payload, study_id: payload.study_id ?? studyId }),
  updateTask: (id: string, payload: CTMSTaskUpdatePayload) => patch<CTMSTask>(`/ctms/tasks/${id}`, payload),
  transitionTask: (id: string, payload: CTMSTaskTransitionPayload) => post<CTMSTask>(`/ctms/tasks/${id}/transition`, payload),
  createQueryFollowUp: (queryId: string, payload: CTMSQueryFollowUpPayload) => post<CTMSTask>(`/ctms/queries/${queryId}/follow-ups`, payload),
  contacts: (studyId: string, context?: CTMSQueryContext) => list<CTMSContact>(`/ctms/studies/${studyId}/contacts`, context),
  contact: (id: string, context?: CTMSQueryContext) => item<CTMSContact>(`/ctms/contacts/${id}`, context),
  createContact: (studyId: string, payload: Omit<CTMSContactPayload, 'study_id'> & { study_id?: string }) => post<CTMSContact>(`/ctms/studies/${studyId}/contacts`, { ...payload, study_id: payload.study_id ?? studyId }),
  updateContact: (id: string, payload: Omit<CTMSContactPayload, 'study_id' | 'status'>) => patch<CTMSContact>(`/ctms/contacts/${id}`, payload),
  transitionContact: (id: string, payload: CTMSContactTransitionPayload) => post<CTMSContact>(`/ctms/contacts/${id}/transition`, payload),
  projections: (studyId: string, context?: CTMSQueryContext) => list<CTMSProjection>(`/ctms/studies/${studyId}/projections`, context),
  projection: (id: string, context?: CTMSQueryContext) => item<CTMSProjection>(`/ctms/projections/${id}`, context),
  dashboard: (studyId: string, context?: CTMSQueryContext) => item<CTMSDashboard>(`/ctms/studies/${studyId}/dashboard`, context),
  siteDashboard: (siteId: string, studyId?: string, context?: CTMSQueryContext) => item<CTMSDashboard>(`/ctms/sites/${siteId}/dashboard${studyId ? `?study_id=${encodeURIComponent(studyId)}` : ''}`, context),
  report: (studyId: string, type: string, context?: CTMSQueryContext) => item<CTMSReport>(`/ctms/studies/${studyId}/reports/${type}`, context),
  catalogReport: (studyId: string, category: string, type: string, context?: CTMSQueryContext) => item<CTMSReport>(`/ctms/studies/${studyId}/reports/${category}/${type}`, context),
  studyOperations: (studyId: string, resource: CTMSStudyOperationResource, context?: CTMSQueryContext) => list<CTMSStudyOperationRecord>(`/ctms/studies/${studyId}/study-operations/${resource}`, context),
  createStudyOperation: (studyId: string, resource: CTMSStudyOperationResource, payload: CTMSStudyOperationCreate) => post<CTMSStudyOperationRecord>(`/ctms/studies/${studyId}/study-operations/${resource}`, payload),
  financialOverview: (studyId: string) => item<CTMSFinancialOverview>(`/ctms/studies/${studyId}/financials/overview`),
  financialConfigurationOptions: (studyId: string, asOf?: string) => item<CTMSFinancialConfigurationOptions>(`/ctms/studies/${studyId}/financials/configuration-options${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`),
  financialContracts: (studyId: string) => list<CTMSFinancialContract>(`/ctms/studies/${studyId}/financials/contracts`),
  contractVersions: (studyId: string, contractId: string) => item<CTMSContractVersion[]>(`/ctms/studies/${studyId}/financials/contracts/${contractId}/versions`),
  paymentTerms: (studyId: string, versionId: string) => item<CTMSPaymentTerm[]>(`/ctms/studies/${studyId}/financials/versions/${versionId}/terms`),
  createFinancialContract: (studyId: string, payload: CTMSFinancialContractCreate) => post<CTMSFinancialContract>(`/ctms/studies/${studyId}/financials/contracts`, payload),
  transitionFinancialContract: (studyId: string, contractId: string, toStatus: string, reason: string) => post<CTMSFinancialContract>(`/ctms/studies/${studyId}/financials/contracts/${contractId}/transition`, { to_status: toStatus, reason }),
  createContractVersion: (studyId: string, contractId: string, payload: { effective_from: string; effective_to?: string; total_value: number; holdback_percent: number; payment_window_days?: number; invoice_required?: boolean; tax_treatment?: string; amendment_reason?: string }) => post<CTMSContractVersion>(`/ctms/studies/${studyId}/financials/contracts/${contractId}/versions`, payload),
  createPaymentTerm: (studyId: string, versionId: string, payload: { code: string; description: string; payment_method: CTMSPaymentTerm['payment_method']; trigger_code: string; unit_rate: number; cost_category?: string; billing_unit?: string; visit_definition_id?: string; form_definition_id?: string; lab_code?: string; invoice_category?: string; dimensions_json?: Record<string, string>; frequency?: string; quantity_cap?: number; amount_cap?: number; holdback_percent?: number }) => post<CTMSPaymentTerm>(`/ctms/studies/${studyId}/financials/versions/${versionId}/terms`, payload),
  executeContractVersion: (studyId: string, versionId: string, reason: string) => post<CTMSContractVersion>(`/ctms/studies/${studyId}/financials/versions/${versionId}/execute`, { reason }),
  contractDocuments: (studyId: string, contractId: string) => item<CTMSAttachment[]>(`/ctms/studies/${studyId}/financials/contracts/${contractId}/documents`),
  uploadContractDocument: (studyId: string, contractId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<CTMSAttachment>(`/ctms/studies/${studyId}/financials/contracts/${contractId}/documents`, form, { headers: { 'Content-Type': 'multipart/form-data' } }).then((response) => response.data)
  },
  contractAudit: (studyId: string, contractId: string) => item<CTMSFinancialAuditEntry[]>(`/ctms/studies/${studyId}/financials/contracts/${contractId}/audit`),
  financialBudgets: (studyId: string) => item<CTMSFinancialBudget[]>(`/ctms/studies/${studyId}/financials/budgets`),
  createFinancialBudget: (studyId: string, payload: CTMSFinancialBudgetPayload) => post<CTMSFinancialBudget>(`/ctms/studies/${studyId}/financials/budgets`, payload),
  createFinancialBudgetVersion: (studyId: string, budgetId: string, payload: Omit<CTMSFinancialBudgetPayload, 'name' | 'scope' | 'currency'>) => post<CTMSFinancialBudgetVersion>(`/ctms/studies/${studyId}/financials/budgets/${budgetId}/versions`, payload),
  approveFinancialBudgetVersion: (studyId: string, versionId: string, reason: string) => post<CTMSFinancialBudgetVersion>(`/ctms/studies/${studyId}/financials/budget-versions/${versionId}/approve`, { reason }),
  financialReport: (studyId: string) => item<CTMSFinancialReport>(`/ctms/studies/${studyId}/financials/reports`),
  financialPayables: (studyId: string) => list<CTMSPayableItem>(`/ctms/studies/${studyId}/financials/payables`),
  calculateFinancialEvent: (studyId: string, payload: CTMSFinancialEventCreate) => post<CTMSFinancialCalculation>(`/ctms/studies/${studyId}/financials/events/calculate`, payload),
  approvePayable: (studyId: string, payableId: string, reason: string) => post<CTMSPayableItem>(`/ctms/studies/${studyId}/financials/payables/${payableId}/approve`, { reason }),
  financialInvoices: (studyId: string) => list<CTMSFinancialInvoice>(`/ctms/studies/${studyId}/financials/invoices`),
  createFinancialInvoice: (studyId: string, payload: CTMSFinancialInvoiceCreate) => post<CTMSFinancialInvoice>(`/ctms/studies/${studyId}/financials/invoices`, payload),
  financialPayments: (studyId: string) => list<CTMSFinancialPayment>(`/ctms/studies/${studyId}/financials/payments`),
  reconcileFinancialPayment: (studyId: string, payload: CTMSFinancialPaymentCreate) => post<CTMSFinancialPayment>(`/ctms/studies/${studyId}/financials/payments`, payload),
  reverseFinancialPayment: (studyId: string, paymentId: string, payload: { payment_date: string; reference: string; reason: string }) => post<CTMSFinancialPayment>(`/ctms/studies/${studyId}/financials/payments/${paymentId}/reverse`, payload),
  exports: (studyId: string, context?: CTMSQueryContext) => list<CTMSExport>(`/ctms/studies/${studyId}/exports`, context),
  createExport: (studyId: string, payload: CTMSExportRequest) => post<CTMSExport>(`/ctms/studies/${studyId}/exports`, serializeCTMSExportRequest(payload)),
  exportJob: (id: string, context?: CTMSQueryContext) => item<CTMSExport>(`/ctms/exports/${id}`, context),
  downloadExport: (id: string) => api.get<Blob>(`/ctms/exports/${id}/download`, { responseType: 'blob' }).then((response) => response.data),
  attachments: (objectType: string, objectId: string, context?: CTMSQueryContext) => list<CTMSAttachment>(`/objects/${objectType}/${objectId}/files`, context),
  uploadAttachment: (payload: CTMSAttachmentUploadPayload) => {
    if (!isCTMSOperationalAttachmentParent(payload.objectType)) {
      return Promise.reject(new CTMSClientError('Operational attachments require a CTMS-owned parent.', { code: 'CTMS_ATTACHMENT_PARENT_INVALID', category: 'validation' }))
    }
    const form = new FormData()
    if (payload.filename) form.append('file', payload.file, payload.filename)
    else form.append('file', payload.file)
    return api.post<CTMSAttachment>(`/objects/${payload.objectType}/${payload.objectId}/files`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        const total = typeof event.total === 'number' && event.total > 0 ? event.total : undefined
        const loaded = event.loaded ?? 0
        const percentage = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0
        payload.onProgress?.({ loaded, total, percentage })
      },
    }).then((response) => response.data)
  },
  downloadAttachment: (id: string) => api.get<Blob>(`/files/${id}/download`, { responseType: 'blob' }).then((response) => response.data),
  deleteAttachment: (id: string, payload: CTMSAttachmentDeletePayload) => api.delete<CTMSAttachment>(`/files/${id}`, { data: payload }).then((response) => response.data),
  restoreAttachment: (id: string, payload: CTMSAttachmentRestorePayload) => post<CTMSAttachment>(`/files/${id}/restore`, payload),
  health: (context?: CTMSQueryContext) => item<CTMSHealth>('/ctms/health', context),
  events: (studyId: string, context?: CTMSQueryContext) => list<CTMSCoordinationEvent>(`/ctms/studies/${studyId}/coordination-events`, context),
  failedEvents: (studyId: string, context?: CTMSQueryContext) => list<CTMSFailedEvent>(`/ctms/studies/${studyId}/failed-events`, context),
  conflicts: (studyId: string, context?: CTMSQueryContext) => list<CTMSConflict>(`/ctms/studies/${studyId}/coordination-conflicts`, context),
  replayEvent: (eventId: string, reason: string) => post<CTMSCoordinationEvent>(`/ctms/coordination-events/${eventId}/replay`, { reason } satisfies CTMSReplayPayload),
  resolveConflict: (conflictId: string, policy: string, reason: string, selectedValue?: CTMSConflictResolutionPayload['selectedValue']) => post<CTMSConflict>(`/ctms/coordination-conflicts/${conflictId}/resolve`, { policy, reason, ...(selectedValue !== undefined ? { selectedValue } : {}) } satisfies CTMSConflictResolutionPayload),
}

export function useCTMSQuery<T>(query: UseQueryResult<T>, enabled = true): UseQueryResult<T> {
  void enabled
  return query
}

export function useCTMSStudyProfile(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.studyProfile(studyId, context), queryFn: () => ctmsApi.studyProfile(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSEntities(studyId?: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.entities(studyId, context), queryFn: () => ctmsApi.entities(studyId, context) }) }
export function useCTMSReferenceValues(category?: CTMSReferenceCategory, active: boolean | null = true) { return useQuery({ queryKey: ctmsKeys.referenceValues(category, active), queryFn: () => ctmsApi.referenceValues(category, active) }) }
export function useCTMSStudyEntities(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.studyEntities(studyId, context), queryFn: () => ctmsApi.studyEntities(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSPlans(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.plans(studyId, context), queryFn: () => ctmsApi.plans(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSProjectMilestones(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.projectMilestones(studyId, context), queryFn: () => ctmsApi.projectMilestones(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSProjectOptions(studyId: string) { return useQuery({ queryKey: ctmsKeys.projectOptions(studyId), queryFn: () => ctmsApi.projectOptions(studyId), enabled: Boolean(studyId) }) }
export function useCTMSSiteProfile(siteId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.siteProfile(siteId, context), queryFn: () => ctmsApi.siteProfile(siteId, context), enabled: Boolean(siteId) }) }
export function useCTMSActivation(siteId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.activation(siteId, context), queryFn: () => ctmsApi.activation(siteId, context), enabled: Boolean(siteId) }) }
export function useCTMSTargets(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.targets(studyId, context), queryFn: () => ctmsApi.targets(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSMilestones(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.milestones(studyId, context), queryFn: () => ctmsApi.milestones(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSMonitoringPlans(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.monitoringPlans(studyId, context), queryFn: () => ctmsApi.monitoringPlans(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSMonitoringPlanVersions(planId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.monitoringPlanVersions(planId, context), queryFn: () => ctmsApi.monitoringPlanVersions(planId, context), enabled: Boolean(planId) }) }
export function useCTMSMonitoringActivities(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.monitoringActivities(studyId, context), queryFn: () => ctmsApi.monitoringActivities(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSMonitoringChecklist(visitId: string) { return useQuery({ queryKey: ctmsKeys.monitoringChecklist(visitId), queryFn: () => ctmsApi.monitoringChecklist(visitId), enabled: Boolean(visitId) }) }
export function useCTMSMonitoringReports(visitId: string) { return useQuery({ queryKey: ctmsKeys.monitoringReports(visitId), queryFn: () => ctmsApi.monitoringReports(visitId), enabled: Boolean(visitId) }) }
export function useCTMSMonitoringFindings(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.monitoringFindings(studyId, context), queryFn: () => ctmsApi.monitoringFindings(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSTasks(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.tasks(studyId, context), queryFn: () => ctmsApi.tasks(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSContacts(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.contacts(studyId, context), queryFn: () => ctmsApi.contacts(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSProjections(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.projections(studyId, context), queryFn: () => ctmsApi.projections(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSDashboard(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.dashboard(studyId, context), queryFn: () => ctmsApi.dashboard(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSSiteDashboard(siteId: string, studyId?: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.siteDashboard(siteId, { ...context, studyId: context?.studyId ?? studyId }), queryFn: () => ctmsApi.siteDashboard(siteId, studyId, context), enabled: Boolean(siteId) }) }
export function useCTMSReport(studyId: string, type: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.report(studyId, type, context), queryFn: () => ctmsApi.report(studyId, type, context), enabled: Boolean(studyId && type) }) }
export function useCTMSCatalogReport(studyId: string, category: string, type: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.catalogReport(studyId, category, type), queryFn: () => ctmsApi.catalogReport(studyId, category, type, context), enabled: Boolean(studyId && category && type) }) }
export function useCTMSStudyOperations(studyId: string, resource?: CTMSStudyOperationResource, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.studyOperations(studyId, resource ?? 'none', context), queryFn: () => ctmsApi.studyOperations(studyId, resource as CTMSStudyOperationResource, context), enabled: Boolean(studyId && resource) }) }
export function useCTMSFinancialOverview(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialOverview(studyId), queryFn: () => ctmsApi.financialOverview(studyId), enabled: Boolean(studyId) }) }
export function useCTMSFinancialConfigurationOptions(studyId: string, asOf?: string) { return useQuery({ queryKey: ctmsKeys.financialConfigurationOptions(studyId, asOf), queryFn: () => ctmsApi.financialConfigurationOptions(studyId, asOf), enabled: Boolean(studyId) }) }
export function useCTMSFinancialContracts(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialContracts(studyId), queryFn: () => ctmsApi.financialContracts(studyId), enabled: Boolean(studyId) }) }
export function useCTMSContractVersions(studyId: string, contractId: string) { return useQuery({ queryKey: ctmsKeys.contractVersions(studyId, contractId), queryFn: () => ctmsApi.contractVersions(studyId, contractId), enabled: Boolean(studyId && contractId) }) }
export function useCTMSPaymentTerms(studyId: string, versionId: string) { return useQuery({ queryKey: ctmsKeys.paymentTerms(studyId, versionId), queryFn: () => ctmsApi.paymentTerms(studyId, versionId), enabled: Boolean(studyId && versionId) }) }
export function useCTMSContractDocuments(studyId: string, contractId: string) { return useQuery({ queryKey: ctmsKeys.contractDocuments(studyId, contractId), queryFn: () => ctmsApi.contractDocuments(studyId, contractId), enabled: Boolean(studyId && contractId) }) }
export function useCTMSContractAudit(studyId: string, contractId: string) { return useQuery({ queryKey: ctmsKeys.contractAudit(studyId, contractId), queryFn: () => ctmsApi.contractAudit(studyId, contractId), enabled: Boolean(studyId && contractId) }) }
export function useCTMSFinancialBudgets(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialBudgets(studyId), queryFn: () => ctmsApi.financialBudgets(studyId), enabled: Boolean(studyId) }) }
export function useCTMSFinancialReport(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialReport(studyId), queryFn: () => ctmsApi.financialReport(studyId), enabled: Boolean(studyId) }) }
export function useCTMSFinancialPayables(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialPayables(studyId), queryFn: () => ctmsApi.financialPayables(studyId), enabled: Boolean(studyId) }) }
export function useCTMSFinancialInvoices(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialInvoices(studyId), queryFn: () => ctmsApi.financialInvoices(studyId), enabled: Boolean(studyId) }) }
export function useCTMSFinancialPayments(studyId: string) { return useQuery({ queryKey: ctmsKeys.financialPayments(studyId), queryFn: () => ctmsApi.financialPayments(studyId), enabled: Boolean(studyId) }) }
export function useCTMSExports(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.exports(studyId, context), queryFn: () => ctmsApi.exports(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSAttachments(objectType: string, objectId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.attachments(objectType, objectId, context), queryFn: () => ctmsApi.attachments(objectType, objectId, context), enabled: Boolean(objectType && objectId && isCTMSOperationalAttachmentParent(objectType)) }) }
export function useCTMSExportJob(exportId: string | undefined, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.exportJob(exportId ?? 'none', context), queryFn: () => ctmsApi.exportJob(exportId as string, context), enabled: Boolean(exportId) }) }
export function useCTMSHealth(context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.health(context), queryFn: () => ctmsApi.health(context) }) }
export function useCTMSEvents(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.events(studyId, context), queryFn: () => ctmsApi.events(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSFailedEvents(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.failedEvents(studyId, context), queryFn: () => ctmsApi.failedEvents(studyId, context), enabled: Boolean(studyId) }) }
export function useCTMSConflicts(studyId: string, context?: CTMSQueryContext) { return useQuery({ queryKey: ctmsKeys.conflicts(studyId, context), queryFn: () => ctmsApi.conflicts(studyId, context), enabled: Boolean(studyId) }) }

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function headerValue(headers: unknown, name: string): string | undefined {
  const record = asRecord(headers)
  if (!record) return undefined
  const matchingKey = Object.keys(record).find((key) => key.toLowerCase() === name.toLowerCase())
  const value = matchingKey ? record[matchingKey] : undefined
  return typeof value === 'string' ? value : undefined
}

const unsafeDetailKeys = new Set(['body', 'event_body', 'raw_event', 'payload', 'clinical_data', 'source_document', 'credentials', 'password', 'token', 'stack', 'traceback', 'query_message'])

// Coordination detail fields are an explicit presentation allowlist. The API
// marks these values as sanitized, but the client still refuses arbitrary
// detail keys so a raw event body or clinical value cannot reach the DOM.
const safeRemediationDetailKeys = new Set([
  'guidance',
  'summary',
  'reason_code',
  'conflict_type',
  'entity_type',
  'field_path',
  'source_module',
  'target_module',
  'source_version',
  'current_version',
  'current_status',
  'event_type',
  'outcome',
  'rule_version',
  'source_sequence',
])

export function sanitizeCTMSRemediationDetails(value: unknown): Record<string, string | number | boolean> {
  const record = asRecord(value)
  if (!record) return {}
  return Object.fromEntries(Object.entries(record).flatMap(([key, entry]): [string, string | number | boolean][] => {
    if (!safeRemediationDetailKeys.has(key.toLowerCase())) return []
    if (typeof entry === 'string') return entry.length <= 500 ? [[key, entry]] : []
    if (typeof entry === 'number' || typeof entry === 'boolean') return [[key, entry]]
    return []
  }))
}

function sanitizeDetail(value: unknown, depth = 0): unknown {
  if (depth > 2 || value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  if (Array.isArray(value)) return value.slice(0, 20).map((entry) => sanitizeDetail(entry, depth + 1))
  const record = asRecord(value)
  if (!record) return undefined
  return Object.fromEntries(Object.entries(record).flatMap(([key, entry]) => {
    if (unsafeDetailKeys.has(key.toLowerCase())) return []
    const sanitized = sanitizeDetail(entry, depth + 1)
    return sanitized === undefined ? [] : [[key, sanitized]]
  }))
}

function sanitizeDetails(value: unknown): CTMSValidationDetails {
  const sanitized = sanitizeDetail(value)
  return asRecord(sanitized) as CTMSValidationDetails | undefined ?? {}
}

function classifyCTMSError(status?: number): CTMSErrorCategory {
  if (status === 401) return 'unauthenticated'
  if (status === 403) return 'unauthorized'
  if (status === 404) return 'not-found'
  if (status === 409) return 'conflict'
  if (status === 413) return 'too-large'
  if (status === 422) return 'validation'
  if (status === 429) return 'rate-limited'
  if (status === undefined || status >= 500) return 'unavailable'
  return 'unknown'
}

function isRetryableCTMSError(status?: number): boolean {
  return status === undefined || status === 408 || status === 429 || status >= 500
}

/** Normalize an Axios/network error into the sanitized CTMS baseline error contract. */
export function normalizeCTMSError(error: unknown): CTMSClientError {
  if (error instanceof CTMSClientError) return error
  const errorRecord = asRecord(error)
  const response = asRecord(errorRecord?.response)
  const responseData = asRecord(response?.data) ?? (response ? undefined : errorRecord)
  const nestedError = asRecord(responseData?.error)
  const status = typeof response?.status === 'number' ? response.status : undefined
  const code = typeof nestedError?.code === 'string' ? nestedError.code : typeof responseData?.code === 'string' ? responseData.code : status ? `HTTP_${status}` : 'CTMS_REQUEST_FAILED'
  const message = typeof nestedError?.message === 'string'
    ? nestedError.message
    : typeof responseData?.detail === 'string'
      ? responseData.detail
      : typeof errorRecord?.message === 'string' && !errorRecord.message.includes('\n')
        ? errorRecord.message
        : 'The CTMS service is unavailable.'
  const requestId = typeof nestedError?.request_id === 'string'
    ? nestedError.request_id
    : typeof responseData?.request_id === 'string'
      ? responseData.request_id
      : headerValue(response?.headers, 'x-request-id')
  const correlationId = typeof nestedError?.correlation_id === 'string'
    ? nestedError.correlation_id
    : typeof responseData?.correlation_id === 'string'
      ? responseData.correlation_id
      : headerValue(response?.headers, 'x-correlation-id')
  const details = sanitizeDetails(nestedError?.details ?? responseData?.errors)
  return new CTMSClientError(message, {
    code,
    details,
    requestId,
    correlationId,
    status,
    retryable: isRetryableCTMSError(status),
    category: classifyCTMSError(status),
  })
}

export function getCTMSErrorMessage(error: unknown): string {
  return normalizeCTMSError(error).message
}
