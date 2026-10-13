export interface CTMSReportDefinition {
  readonly id: string
  readonly group: 'Project Management' | 'CRF' | 'Query'
  readonly category: 'project-management' | 'crf' | 'query'
  readonly slug: string
  readonly label: string
  readonly description: string
}

export const CTMS_REPORT_DEFINITIONS: readonly CTMSReportDefinition[] = [
  { id: 'reportGantt', group: 'Project Management', category: 'project-management', slug: 'gantt', label: 'Gantt', description: 'Review the study project schedule and timeline.' },
  { id: 'reportRaciMatrix', group: 'Project Management', category: 'project-management', slug: 'raci-matrix', label: 'RACI Matrix', description: 'Review responsibility and accountability assignments.' },
  { id: 'reportWorkloadAssessment', group: 'Project Management', category: 'project-management', slug: 'workload-assessment', label: 'Workload Assessment', description: 'Review assigned workload across the study team.' },
  { id: 'reportTasks', group: 'Project Management', category: 'project-management', slug: 'tasks', label: 'Tasks', description: 'Review study task status and ownership.' },
  { id: 'reportDeliverables', group: 'Project Management', category: 'project-management', slug: 'deliverables', label: 'Deliverables', description: 'Review study deliverables and due dates.' },
  { id: 'reportActivityTypes', group: 'Project Management', category: 'project-management', slug: 'activity-types', label: 'Activity Types', description: 'Review study activity distribution by type.' },
  { id: 'reportCrfStatusSummary', group: 'CRF', category: 'crf', slug: 'status-summary', label: 'Status Summary', description: 'Review the overall CRF status summary.' },
  { id: 'reportVisitStatus', group: 'CRF', category: 'crf', slug: 'visit-status', label: 'Visit Status', description: 'Review CRF completion by visit.' },
  { id: 'reportFormStatus', group: 'CRF', category: 'crf', slug: 'form-status', label: 'Form Status', description: 'Review CRF completion by form.' },
  { id: 'reportItemStatus', group: 'CRF', category: 'crf', slug: 'item-status', label: 'Item Status', description: 'Review CRF completion by item.' },
  { id: 'reportCompletionStatus', group: 'CRF', category: 'crf', slug: 'completion-status', label: 'Completion Status', description: 'Review CRF completion progress for the selected study.' },
  { id: 'reportStudySummary', group: 'CRF', category: 'crf', slug: 'study-summary', label: 'Study Summary', description: 'Review aggregate CRF metrics for the study.' },
  { id: 'reportSubjectSummary', group: 'CRF', category: 'crf', slug: 'subject-summary', label: 'Subject Summary', description: 'Review CRF status summarized by subject.' },
  { id: 'reportQueryAgingSummary', group: 'Query', category: 'query', slug: 'query-aging-summary', label: 'Query Aging Summary', description: 'Review open-query aging and resolution timelines.' },
  { id: 'reportManualQueryDetails', group: 'Query', category: 'query', slug: 'manual-query-details', label: 'Manual Query Details', description: 'Review manually created query details.' },
  { id: 'reportSystemQueryDetails', group: 'Query', category: 'query', slug: 'system-query-details', label: 'System Query Details', description: 'Review system-generated query details.' },
  { id: 'reportAllQueryDetails', group: 'Query', category: 'query', slug: 'all-query-details', label: 'All Query Details', description: 'Review all study query details.' },
  { id: 'reportPdQueries', group: 'Query', category: 'query', slug: 'pd-queries', label: 'PD Queries', description: 'Review queries associated with protocol deviations.' },
  { id: 'reportTripReportQueries', group: 'Query', category: 'query', slug: 'trip-report-queries', label: 'Trip Report Queries', description: 'Review queries associated with monitoring trip reports.' },
  { id: 'reportIcTrackingLogQueries', group: 'Query', category: 'query', slug: 'ic-tracking-log-queries', label: 'IC Tracking Log Queries', description: 'Review queries associated with informed consent tracking logs.' },
  { id: 'reportActionItemQueries', group: 'Query', category: 'query', slug: 'action-item-queries', label: 'Action Item Queries', description: 'Review queries associated with operational action items.' },
]

export function findCTMSReportDefinition(category?: string, slug?: string): CTMSReportDefinition | undefined {
  return CTMS_REPORT_DEFINITIONS.find((definition) => definition.category === category && definition.slug === slug)
}
