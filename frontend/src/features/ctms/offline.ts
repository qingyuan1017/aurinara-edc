import { useMutation, type MutationFunction, type UseMutationOptions, type UseMutationResult } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

const noop = () => () => undefined

function getOnlineSnapshot(): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.onLine !== 'boolean') return true
  return navigator.onLine
}

function subscribeToOnlineState(listener: () => void): () => void {
  if (typeof window === 'undefined') return noop()
  window.addEventListener('online', listener)
  window.addEventListener('offline', listener)
  return () => {
    window.removeEventListener('online', listener)
    window.removeEventListener('offline', listener)
  }
}

/** Browser connectivity is a UX signal only; it is not an authorization result. */
export function useCTMSOfflineState(): { isOnline: boolean; isOffline: boolean } {
  const isOnline = useSyncExternalStore(subscribeToOnlineState, getOnlineSnapshot, () => true)
  return { isOnline, isOffline: !isOnline }
}

export function isIdempotentCTMSMethod(method = 'POST'): boolean {
  return ['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())
}

export class CTMSOfflineMutationError extends Error {
  readonly code = 'CTMS_OFFLINE_MUTATION_BLOCKED'

  constructor() {
    super('This CTMS change cannot be submitted while offline. Reconnect and try again.')
    this.name = 'CTMSOfflineMutationError'
  }
}

export interface CTMSMutationGuardOptions {
  isOnline: boolean
  method?: string
}

export function canRunCTMSMutation({ isOnline, method = 'POST' }: CTMSMutationGuardOptions): boolean {
  return isOnline || isIdempotentCTMSMethod(method)
}

export function assertCTMSMutationAllowed(options: CTMSMutationGuardOptions): void {
  if (!canRunCTMSMutation(options)) throw new CTMSOfflineMutationError()
}

export interface UseCTMSMutationOptions<TData, TError, TVariables, TContext> extends UseMutationOptions<TData, TError, TVariables, TContext> {
  method?: string
}

/** Wraps a TanStack mutation and blocks non-idempotent writes offline without queueing them. */
export function useCTMSMutation<TData = unknown, TError = unknown, TVariables = void, TContext = unknown>(
  options: UseCTMSMutationOptions<TData, TError, TVariables, TContext>,
): UseMutationResult<TData, TError, TVariables, TContext> & { isOffline: boolean; canMutate: boolean } {
  const { isOnline, isOffline } = useCTMSOfflineState()
  const method = options.method ?? 'POST'
  const mutationFn = options.mutationFn as MutationFunction<TData, TVariables> | undefined
  const mutation = useMutation({
    ...options,
    mutationFn: mutationFn
      ? async (variables: TVariables) => {
          assertCTMSMutationAllowed({ isOnline, method })
          return mutationFn(variables)
        }
      : undefined,
  })
  return { ...mutation, isOffline, canMutate: canRunCTMSMutation({ isOnline, method }) }
}
