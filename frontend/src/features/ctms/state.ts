export type CTMSCapabilityState = 'ready' | 'disabled' | 'unavailable'

export type CTMSQueryState =
  | 'loading'
  | 'refreshing'
  | 'success'
  | 'empty'
  | 'unauthorized'
  | 'disabled'
  | 'unavailable'
  | 'offline'
  | 'error'
  | 'worker-unavailable'

export type CTMSMutationState =
  | 'idle'
  | 'pending'
  | 'success'
  | 'unauthorized'
  | 'disabled'
  | 'unavailable'
  | 'offline'
  | 'error'
  | 'worker-unavailable'

export interface CTMSQueryStateInput {
  isLoading?: boolean
  isFetching?: boolean
  data?: unknown
  error?: unknown
  isOnline?: boolean
  capability?: CTMSCapabilityState
  workerStatus?: string | null
}

export interface CTMSMutationStateInput {
  status: 'idle' | 'pending' | 'success' | 'error'
  error?: unknown
  isOnline?: boolean
  capability?: CTMSCapabilityState
  workerStatus?: string | null
}

function responseStatus(value: unknown): number | undefined {
  if (!value || typeof value !== 'object') return undefined
  const response = 'response' in value ? (value as { response?: unknown }).response : undefined
  if (response && typeof response === 'object' && 'status' in response) {
    const status = (response as { status?: unknown }).status
    return typeof status === 'number' ? status : undefined
  }
  const status = 'status' in value ? (value as { status?: unknown }).status : undefined
  return typeof status === 'number' ? status : undefined
}

function errorCode(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined
  const candidate = value as { code?: unknown; response?: { data?: unknown } }
  if (typeof candidate.code === 'string') return candidate.code.toUpperCase()
  const data = candidate.response?.data
  if (data && typeof data === 'object') {
    const envelope = data as { code?: unknown; error?: { code?: unknown } }
    if (typeof envelope.code === 'string') return envelope.code.toUpperCase()
    if (typeof envelope.error?.code === 'string') return envelope.error.code.toUpperCase()
  }
  return undefined
}

export function isCTMSUnauthorizedError(error: unknown): boolean {
  const status = responseStatus(error)
  const code = errorCode(error)
  return status === 401 || status === 403 || code === 'UNAUTHORIZED' || code === 'FORBIDDEN' || code === 'SCOPE_DENIED'
}

export function isCTMSUnavailableError(error: unknown): boolean {
  const status = responseStatus(error)
  const code = errorCode(error)
  return status === 408 || status === 429 || status >= 500 || code === 'NETWORK_ERROR' || code === 'SERVICE_UNAVAILABLE'
}

export function isCTMSWorkerUnavailable(status?: string | null): boolean {
  if (!status) return false
  return ['unavailable', 'offline', 'degraded', 'failed', 'down'].includes(status.toLowerCase())
}

function hasData(data: unknown): boolean {
  return data !== undefined && data !== null
}

export function isCTMSEmptyData(data: unknown): boolean {
  if (Array.isArray(data)) return data.length === 0
  if (!data || typeof data !== 'object') return false
  const items = (data as { items?: unknown }).items
  return Array.isArray(items) && items.length === 0
}

/** Classifies server and browser conditions without changing authoritative query data. */
export function classifyCTMSQueryState(input: CTMSQueryStateInput): CTMSQueryState {
  if (input.capability === 'disabled') return 'disabled'
  if (input.capability === 'unavailable') return 'unavailable'
  if (isCTMSUnauthorizedError(input.error)) return 'unauthorized'
  if (isCTMSWorkerUnavailable(input.workerStatus)) return 'worker-unavailable'
  if (input.isOnline === false) return 'offline'
  if (input.isLoading && !hasData(input.data)) return 'loading'
  if (input.error && !hasData(input.data)) return isCTMSUnavailableError(input.error) ? 'unavailable' : 'error'
  if (input.isFetching && hasData(input.data)) return 'refreshing'
  if (isCTMSEmptyData(input.data)) return 'empty'
  return 'success'
}

/** Classifies mutation feedback while keeping offline writes blocked by the offline primitive. */
export function classifyCTMSMutationState(input: CTMSMutationStateInput): CTMSMutationState {
  if (input.capability === 'disabled') return 'disabled'
  if (input.capability === 'unavailable') return 'unavailable'
  if (isCTMSUnauthorizedError(input.error)) return 'unauthorized'
  if (isCTMSWorkerUnavailable(input.workerStatus)) return 'worker-unavailable'
  if (input.isOnline === false && input.status !== 'success') return 'offline'
  if (input.status === 'pending') return 'pending'
  if (input.status === 'success') return 'success'
  if (input.status === 'error') return isCTMSUnavailableError(input.error) ? 'unavailable' : 'error'
  return 'idle'
}
