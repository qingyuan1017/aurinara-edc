import type { QueryClient } from '@tanstack/react-query'
import { ctmsKeys, type CTMSConflict, type CTMSFailedEvent } from './api'

export type CTMSMutationResource = 'study-profile' | 'plan' | 'site-profile' | 'activation' | 'enrollment-target' | 'milestone' | 'attachment'

export interface CTMSMutationScope {
  studyId?: string
  siteId?: string
  objectType?: string
  objectId?: string
}

/**
 * Invalidate only CTMS queries affected by a committed operational mutation.
 * No EDC query key is included here: CTMS convenience checks never own EDC
 * clinical data or workflow state.
 */
export function invalidateCTMSMutation(
  queryClient: QueryClient,
  resource: CTMSMutationResource,
  scope: CTMSMutationScope,
): Promise<void[]> {
  const keys: (readonly unknown[])[] = []
  const studyId = scope.studyId
  const siteId = scope.siteId

  if (resource === 'study-profile' && studyId) {
    keys.push(ctmsKeys.studyProfile(studyId), ctmsKeys.dashboard(studyId), [...ctmsKeys.all, 'report', studyId])
  }
  if (resource === 'plan' && studyId) {
    keys.push(ctmsKeys.plans(studyId), ctmsKeys.dashboard(studyId))
  }
  if (resource === 'site-profile' && siteId) {
    keys.push(ctmsKeys.siteProfile(siteId), ctmsKeys.siteDashboard(siteId, { studyId }))
  }
  if (resource === 'activation' && siteId) {
    keys.push(ctmsKeys.activation(siteId), ctmsKeys.siteProfile(siteId), ctmsKeys.siteDashboard(siteId, { studyId }))
  }
  if (resource === 'enrollment-target' && studyId) {
    keys.push(ctmsKeys.targets(studyId), ctmsKeys.dashboard(studyId), [...ctmsKeys.all, 'report', studyId])
  }
  if (resource === 'milestone' && studyId) {
    keys.push(ctmsKeys.milestones(studyId), ctmsKeys.dashboard(studyId), [...ctmsKeys.all, 'report', studyId])
  }
  if (resource === 'attachment' && scope.objectType && scope.objectId) {
    keys.push(ctmsKeys.attachments(scope.objectType, scope.objectId, { studyId, siteId }))
    if (studyId) keys.push(ctmsKeys.dashboard(studyId), ctmsKeys.tasks(studyId), ctmsKeys.monitoringActivities(studyId))
  }

  return Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
}
/**
 * Invalidate export list/detail and notification summaries only after the
 * server has committed an export mutation. Callers must invoke this from
 * mutation onSuccess, never on validation or authorization failure.
 */
export function invalidateCTMSExportMutation(
  queryClient: QueryClient,
  studyId: string,
  exportId?: string,
): Promise<void[]> {
  const keys: (readonly unknown[])[] = [
    ctmsKeys.exports(studyId),
    ['notifications'],
  ]
  if (exportId) keys.push(ctmsKeys.exportJob(exportId))
  return Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
}

export type CTMSCoordinationRemediationRecord = CTMSFailedEvent | CTMSConflict

function coordinationResource(entityType?: string | null): string | undefined {
  const normalized = entityType?.toLowerCase().replaceAll('_', '').replaceAll('-', '')
  if (!normalized) return undefined
  if (normalized.includes('study')) return 'study-profile'
  if (normalized.includes('site')) return 'site-profile'
  if (normalized.includes('enrollment') || normalized.includes('target')) return 'targets'
  if (normalized.includes('milestone')) return 'milestones'
  if (normalized.includes('monitoringplan')) return 'monitoring-plans'
  if (normalized.includes('monitoringactivity')) return 'monitoring-activities'
  if (normalized.includes('task')) return 'tasks'
  if (normalized.includes('contact')) return 'contacts'
  return undefined
}

/**
 * Reconcile coordination remediation without touching EDC query families.
 * Coordination lists, event logs, projections, dashboards/reports, and the
 * identified operational record are all server-confirmed again after success.
 */
export function invalidateCTMSCoordinationRemediation(
  queryClient: QueryClient,
  studyId: string,
  record: CTMSCoordinationRemediationRecord,
): Promise<void[]> {
  const queryKeys: (readonly unknown[])[] = [
    ctmsKeys.failedEvents(studyId),
    ctmsKeys.conflicts(studyId),
    ctmsKeys.events(studyId),
    ctmsKeys.projections(studyId),
    ctmsKeys.dashboard(studyId),
    [...ctmsKeys.all, 'report', studyId],
  ]
  const entityType = 'entity_type' in record ? record.entity_type : record.aggregate_type
  const resource = coordinationResource(entityType)
  const aggregateId = 'entity_type' in record ? record.id : record.aggregate_id
  if (resource && aggregateId) queryKeys.push(ctmsKeys.detail(resource, aggregateId, { studyId }))
  if (resource === 'study-profile') queryKeys.push(ctmsKeys.studyProfile(studyId))
  if (resource === 'targets') queryKeys.push(ctmsKeys.targets(studyId))
  if (resource === 'milestones') queryKeys.push(ctmsKeys.milestones(studyId))
  if (resource === 'monitoring-plans') queryKeys.push(ctmsKeys.monitoringPlans(studyId))
  if (resource === 'monitoring-activities') queryKeys.push(ctmsKeys.monitoringActivities(studyId))
  if (resource === 'tasks') queryKeys.push(ctmsKeys.tasks(studyId))
  if (resource === 'contacts') queryKeys.push(ctmsKeys.contacts(studyId))

  const uniqueKeys = queryKeys.filter((queryKey, index) => queryKeys.findIndex((candidate) => JSON.stringify(candidate) === JSON.stringify(queryKey)) === index)
  return Promise.all(uniqueKeys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
}
