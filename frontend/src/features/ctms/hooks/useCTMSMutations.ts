import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useCTMSMutation } from '../offline'
import {
  ctmsApi,
  ctmsKeys,
  type CTMSCorrelationMetadata,
  type CTMSMonitoringActivity,
  type CTMSMonitoringPlan,
  type CTMSQueryContext,
  type CTMSStatusTransitionPayload,
  type CTMSTransitionOption,
  type CTMSTransitionResult,
} from '../api'

export type CTMSStatusTransitionResource =
  | 'study-profile'
  | 'site-profile'
  | 'plans'
  | 'activation'
  | 'targets'
  | 'milestones'
  | 'monitoring-plans'
  | 'monitoring-activities'
  | 'tasks'
  | 'contacts'

export interface CTMSStatusTransitionScope {
  studyId?: string
  siteId?: string
  context?: CTMSQueryContext
}

function queryContext(scope: CTMSStatusTransitionScope): CTMSQueryContext {
  return {
    ...scope.context,
    studyId: scope.studyId ?? scope.context?.studyId,
    siteId: scope.siteId ?? scope.context?.siteId,
  }
}

function addKey(keys: QueryKey[], key: QueryKey | undefined): void {
  if (!key) return
  const serialized = JSON.stringify(key)
  if (!keys.some((existing) => JSON.stringify(existing) === serialized)) keys.push(key)
}

/**
 * Returns only the CTMS query families affected by a committed operational
 * transition. No EDC query key is ever returned by this policy.
 */
export function getCTMSStatusTransitionInvalidationKeys(
  resource: CTMSStatusTransitionResource,
  recordId: string,
  scope: CTMSStatusTransitionScope = {},
): QueryKey[] {
  const keys: QueryKey[] = []
  const context = queryContext(scope)
  const studyId = context.studyId
  const siteId = context.siteId

  addKey(keys, ctmsKeys.detail(resource, recordId, context))
  switch (resource) {
    case 'study-profile':
      if (studyId) {
        addKey(keys, ctmsKeys.studyProfile(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'site-profile':
      if (siteId) {
        addKey(keys, ctmsKeys.siteProfile(siteId, context))
        addKey(keys, ctmsKeys.siteDashboard(siteId, studyId, context))
      }
      break
    case 'plans':
      if (studyId) {
        addKey(keys, ctmsKeys.plans(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'activation':
      if (siteId) {
        addKey(keys, ctmsKeys.activation(siteId, context))
        addKey(keys, ctmsKeys.siteProfile(siteId, context))
        addKey(keys, ctmsKeys.siteDashboard(siteId, studyId, context))
      }
      break
    case 'targets':
      if (studyId) {
        addKey(keys, ctmsKeys.targets(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'milestones':
      if (studyId) {
        addKey(keys, ctmsKeys.milestones(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'monitoring-plans':
      if (studyId) {
        addKey(keys, ctmsKeys.monitoringPlans(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'monitoring-activities':
      if (studyId) {
        addKey(keys, ctmsKeys.monitoringActivities(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'tasks':
      if (studyId) {
        addKey(keys, ctmsKeys.tasks(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
    case 'contacts':
      if (studyId) {
        addKey(keys, ctmsKeys.contacts(studyId, context))
        addKey(keys, ctmsKeys.dashboard(studyId, context))
      }
      break
  }
  return keys
}

export async function invalidateCTMSStatusTransition(
  queryClient: ReturnType<typeof useQueryClient>,
  resource: CTMSStatusTransitionResource,
  recordId: string,
  scope: CTMSStatusTransitionScope = {},
): Promise<void> {
  await Promise.all(getCTMSStatusTransitionInvalidationKeys(resource, recordId, scope).map((queryKey) => queryClient.invalidateQueries({ queryKey })))
}

export interface UseCTMSStatusTransitionOptions<T> extends CTMSStatusTransitionScope {
  resource: CTMSStatusTransitionResource
  recordId: string
  currentStatus?: string
  mutationFn: (payload: CTMSStatusTransitionPayload) => Promise<CTMSTransitionResult<T> | T>
  onSuccess?: (result: CTMSTransitionResult<T>, payload: CTMSStatusTransitionPayload) => void | Promise<void>
}

/** Normalize both the envelope and resource-shaped CTMS transition responses. */
export function normalizeCTMSStatusTransitionResult<T>(response: CTMSTransitionResult<T> | T): CTMSTransitionResult<T> {
  if (response && typeof response === 'object' && 'resource' in response && 'current_status' in response) {
    return response as CTMSTransitionResult<T>
  }
  const resource = response as T
  const record = response && typeof response === 'object' ? response as Record<string, unknown> : {}
  const allowedTransitions = Array.isArray(record.allowed_transitions) ? record.allowed_transitions as CTMSTransitionOption[] : []
  return {
    resource,
    current_status: typeof record.current_status === 'string' ? record.current_status : typeof record.status === 'string' ? record.status : '',
    allowed_transitions: allowedTransitions,
  }
}

/**
 * Mutation hook for CTMS operational status transitions. It intentionally has
 * no onMutate callback: the current status remains server-confirmed until the
 * API returns a transition result, then only affected CTMS queries invalidate.
 */
export function useCTMSStatusTransition<T>({
  resource,
  recordId,
  currentStatus,
  context,
  studyId,
  siteId,
  mutationFn,
  onSuccess,
}: UseCTMSStatusTransitionOptions<T>) {
  const queryClient = useQueryClient()
  const mutation = useCTMSMutation<CTMSTransitionResult<T>, unknown, CTMSStatusTransitionPayload>({
    method: 'POST',
    mutationFn: async (payload) => normalizeCTMSStatusTransitionResult(await mutationFn(payload)),
    onSuccess: async (result, payload) => {
      await invalidateCTMSStatusTransition(queryClient, resource, recordId, { context, studyId, siteId })
      await onSuccess?.(result, payload)
    },
  })

  return {
    ...mutation,
    currentStatus: mutation.data?.current_status ?? currentStatus,
    allowedTransitions: mutation.data?.allowed_transitions,
  }
}

export interface UseCTMSActivationTransitionOptions extends Omit<UseCTMSStatusTransitionOptions<unknown>, 'resource' | 'mutationFn' | 'recordId'> {
  actionId: string
}

export function useCTMSActivationTransition({ actionId, ...options }: UseCTMSActivationTransitionOptions) {
  return useCTMSStatusTransition({
    ...options,
    resource: 'activation',
    recordId: actionId,
    mutationFn: (payload) => ctmsApi.completeActivationAction(actionId, payload),
  })
}

export interface UseCTMSMonitoringPlanTransitionOptions extends Omit<UseCTMSStatusTransitionOptions<CTMSMonitoringPlan>, 'resource' | 'mutationFn' | 'recordId'> {
  planId: string
  action: 'publish' | 'amend'
}

export function useCTMSMonitoringPlanTransition({ planId, action, ...options }: UseCTMSMonitoringPlanTransitionOptions) {
  return useCTMSStatusTransition({
    ...options,
    resource: 'monitoring-plans',
    recordId: planId,
    mutationFn: (payload) => action === 'publish' ? ctmsApi.publishMonitoringPlan(planId, payload) : ctmsApi.amendMonitoringPlan(planId, payload),
  })
}

export interface UseCTMSMonitoringActivityTransitionOptions extends Omit<UseCTMSStatusTransitionOptions<CTMSMonitoringActivity>, 'resource' | 'mutationFn' | 'recordId'> {
  activityId: string
  action: 'reschedule' | 'complete' | 'cancel'
  plannedDate?: string
}

export function useCTMSMonitoringActivityTransition({ activityId, action, plannedDate, ...options }: UseCTMSMonitoringActivityTransitionOptions) {
  return useCTMSStatusTransition({
    ...options,
    resource: 'monitoring-activities',
    recordId: activityId,
    mutationFn: (payload) => {
      const request = plannedDate ? { ...payload, planned_date: plannedDate } : payload
      if (action === 'reschedule') return ctmsApi.rescheduleMonitoringActivity(activityId, request)
      if (action === 'complete') return ctmsApi.completeMonitoringActivity(activityId, request)
      return ctmsApi.cancelMonitoringActivity(activityId, request)
    },
  })
}

export type CTMSStatusTransitionMutationMetadata = CTMSCorrelationMetadata
