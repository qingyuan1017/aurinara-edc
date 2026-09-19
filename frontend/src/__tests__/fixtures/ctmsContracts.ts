import type {
  CTMSAttachment,
  CTMSBaselineErrorEnvelope,
  CTMSCapabilityManifest,
  CTMSConflict,
  CTMSCoordinationEvent,
  CTMSErrorCategory,
  CTMSExport,
  CTMSFailedEvent,
  CTMSHealth,
  CTMSPage,
  CTMSProjection,
  CTMSQueryContext,
  CTMSStatusTransitionPayload,
  CTMSTask,
  CTMSTransitionResult,
} from '@/features/ctms/api'

export const capabilityFixtures = {
  disabled: {
    module: 'CTMS',
    enabled: false,
    phase: 0,
    capabilities: [],
  },
  phase1: {
    module: 'CTMS',
    enabled: true,
    phase: 1,
    capabilities: ['operational_studies', 'operational_sites', 'enrollment', 'dashboard'],
  },
  phase2: {
    module: 'CTMS',
    enabled: true,
    phase: 2,
    capabilities: ['operational_studies', 'operational_sites', 'enrollment', 'dashboard', 'monitoring', 'tasks', 'attachments', 'projections', 'coordination'],
    environment: { name: 'staging', region: 'us-east-1' },
    platform_capabilities: { health_observability: true, export_worker: true },
  },
  phase3: {
    module: 'CTMS',
    enabled: true,
    phase: 3,
    capabilities: ['operational_studies', 'operational_sites', 'enrollment', 'dashboard', 'monitoring', 'tasks', 'attachments', 'projections', 'coordination', 'reports', 'exports', 'health'],
    platform_capabilities: { health_observability: true, export_worker: true },
  },
} satisfies Record<string, CTMSCapabilityManifest>

export const taskPageFixture = {
  items: [
    {
      id: 'task-1',
      study_id: 'study-1',
      site_id: 'site-1',
      title: 'Confirm monitoring date',
      description: 'Confirm the next operational monitoring visit.',
      owner_id: 'user-1',
      due_date: '2026-03-15',
      priority: 'high',
      status: 'Open',
      query_id: 'query-1',
      updated_at: '2026-03-01T10:00:00Z',
      created_at: '2026-02-20T10:00:00Z',
    },
  ],
  page: 2,
  page_size: 25,
  total: 51,
  next_cursor: 'cursor-next-2',
  previous_cursor: 'cursor-prev-2',
} satisfies CTMSPage<CTMSTask>

export const queryContextFixture = {
  routeScope: 'study-workspace',
  studyId: 'study-1',
  siteId: 'site-1',
  filters: {
    status: ['Open', 'Blocked'],
    ownerId: 'user-1',
    priority: 'high',
    dueCategory: 'overdue',
    from: '2026-03-01',
    to: '2026-03-31',
    includeArchived: false,
  },
  pagination: { page: 2, pageSize: 25, cursor: 'cursor-next-1' },
  phase: 2,
} satisfies CTMSQueryContext

export const transitionFixture = {
  resource: taskPageFixture.items[0],
  current_status: 'Open',
  allowed_transitions: [
    { status: 'In Progress' },
    { status: 'Blocked', requires_reason: true, reason_label: 'Blocking reason' },
    { status: 'Completed', requires_reason: true, reason_label: 'Completion reason' },
  ],
  meta: { requestId: 'request-transition-1', correlationId: 'correlation-transition-1', outcome: 'succeeded' },
} satisfies CTMSTransitionResult<CTMSTask>

export const transitionPayloadFixture = {
  status: 'Completed',
  reason: 'Monitoring date confirmed by the site.',
} satisfies CTMSStatusTransitionPayload

export const baselineErrorFixture = {
  error: {
    code: 'CTMS_SCOPE_DENIED',
    message: 'The requested CTMS record is outside your assigned scope.',
    details: {
      fields: { study_id: ['Study scope is not assigned.'] },
      safe_hint: 'Contact your CTMS administrator.',
      raw_event: { secret: 'must-not-render' },
      stack: 'must-not-render',
    },
  },
  request_id: 'request-denied-1',
  correlation_id: 'correlation-denied-1',
} satisfies CTMSBaselineErrorEnvelope

export const errorCategoryFixtures = {
  unauthorized: 'unauthorized',
  conflict: 'conflict',
  validation: 'validation',
  unavailable: 'unavailable',
} satisfies Record<string, CTMSErrorCategory>

export const projectionFreshnessFixtures = {
  current: {
    id: 'projection-current-1',
    study_id: 'study-1',
    subject_id: 'subject-reference-1',
    source_module: 'EDC',
    source_record_id: 'edc-signal-1',
    projection_type: 'Approved quality signal',
    source_version: 8,
    rule_version: 'quality-v2',
    source_timestamp: '2026-03-01T09:55:00Z',
    projected_at: '2026-03-01T10:00:00Z',
    payload: { open_query_count: 2 },
    status: 'Current',
    freshness: 'current',
    read_only: true,
  },
  stale: {
    id: 'projection-stale-1',
    study_id: 'study-1',
    source_module: 'EDC',
    source_record_id: 'edc-signal-2',
    projection_type: 'Approved quality signal',
    source_timestamp: '2026-02-20T09:55:00Z',
    projected_at: '2026-02-20T10:00:00Z',
    payload: { open_query_count: 4 },
    status: 'Stale',
    freshness: 'stale',
    read_only: true,
  },
  unknown: {
    id: 'projection-unknown-1',
    study_id: 'study-1',
    source_module: 'EDC',
    source_record_id: 'edc-signal-3',
    projection_type: 'Approved quality signal',
    projected_at: '2026-03-01T10:00:00Z',
    payload: {},
    status: 'Unknown',
    freshness: 'unknown',
    read_only: true,
  },
} satisfies Record<string, CTMSProjection>

export const exportJobFixtures = {
  queued: {
    id: 'export-queued-1',
    study_id: 'study-1',
    module: 'CTMS',
    content_owner: 'CTMS',
    export_type: 'csv',
    status: 'queued',
    filters: { site_id: 'site-1', record_types: ['tasks'] },
    correlation_id: 'correlation-export-queued',
    created_at: '2026-03-01T10:00:00Z',
  },
  completed: {
    id: 'export-completed-1',
    study_id: 'study-1',
    module: 'CTMS',
    content_owner: 'CTMS',
    export_type: 'csv',
    status: 'completed',
    filters: { site_id: 'site-1', record_types: ['tasks'] },
    file_path: 'operational/export-completed-1.csv',
    file_size: 2048,
    correlation_id: 'correlation-export-completed',
    created_at: '2026-03-01T10:00:00Z',
    completed_at: '2026-03-01T10:01:00Z',
    expires_at: '2026-03-08T10:01:00Z',
  },
  failed: {
    id: 'export-failed-1',
    study_id: 'study-1',
    module: 'CTMS',
    content_owner: 'CTMS',
    export_type: 'json',
    status: 'failed',
    error_message: 'The operational export worker could not complete the job.',
    correlation_id: 'correlation-export-failed',
    created_at: '2026-03-01T10:00:00Z',
  },
  expired: {
    id: 'export-expired-1',
    study_id: 'study-1',
    module: 'CTMS',
    content_owner: 'CTMS',
    export_type: 'excel',
    status: 'expired',
    correlation_id: 'correlation-export-expired',
    created_at: '2026-02-20T10:00:00Z',
    expires_at: '2026-02-27T10:00:00Z',
  },
} satisfies Record<string, CTMSExport>

export const attachmentConstraintsFixture = {
  max_size_bytes: 10 * 1024 * 1024,
  allowed_content_types: ['application/pdf', 'text/plain', 'image/png'],
  allowed_object_types: ['operational_task', 'monitoring_activity'],
  retention_days: 365,
  ownership: 'CTMS',
  attachment_type: 'Operational_Attachment',
} as const

export const attachmentFixture = {
  id: 'attachment-1',
  module: 'CTMS',
  attachment_type: 'Operational_Attachment',
  object_type: 'operational_task',
  object_id: 'task-1',
  study_id: 'study-1',
  site_id: 'site-1',
  filename: 'monitoring-evidence.pdf',
  content_type: 'application/pdf',
  size_bytes: 4096,
  uploaded_by: 'user-1',
  uploaded_at: '2026-03-01T10:00:00Z',
  retention_until: '2027-03-01T10:00:00Z',
  correlation_id: 'correlation-attachment-1',
} satisfies CTMSAttachment

export const healthFixture = {
  worker_status: 'available',
  worker_available: true,
  pending_event_count: 1,
  failed_event_count: 0,
  conflict_count: 0,
  projection_lag: 0,
  last_successful_processing_time: '2026-03-01T09:59:00Z',
  request_id: 'request-health-1',
} satisfies CTMSHealth

export const failedEventFixture = {
  id: 'failed-event-1',
  event_id: 'event-1',
  event_type: 'OperationalTaskUpdated',
  source_module: 'CTMS',
  status: 'failed',
  reason_code: 'TARGET_UNAVAILABLE',
  sanitized_details: { guidance: 'Retry after the target projection is available.' },
  correlation_id: 'correlation-replay-1',
  created_at: '2026-03-01T10:00:00Z',
  available_actions: ['replay'],
} satisfies CTMSFailedEvent

export const conflictFixture = {
  id: 'conflict-1',
  event_id: 'event-2',
  entity_type: 'OperationalTask',
  field_path: 'status',
  conflict_type: 'VERSION_MISMATCH',
  source_version: '4',
  current_version: '5',
  status: 'open',
  sanitized_details: { guidance: 'Review the current operational status before resolving.' },
  correlation_id: 'correlation-conflict-1',
  created_at: '2026-03-01T10:00:00Z',
  policy_choices: ['keep_current', 'apply_source'],
  available_actions: ['resolve'],
} satisfies CTMSConflict

export const replayOutcomeFixture = {
  id: 'coordination-event-1',
  event_id: 'event-1',
  event_type: 'OperationalTaskUpdated',
  source_module: 'CTMS',
  target_module: 'CTMS',
  status: 'accepted',
  correlation_id: 'correlation-replay-accepted',
  outcome: 'accepted',
} satisfies CTMSCoordinationEvent

export const conflictResolutionOutcomeFixture = {
  ...conflictFixture,
  status: 'resolved',
  resolved_at: '2026-03-01T10:05:00Z',
  correlation_id: 'correlation-conflict-resolved',
}
