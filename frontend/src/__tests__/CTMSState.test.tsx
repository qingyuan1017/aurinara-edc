import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  classifyCTMSMutationState,
  classifyCTMSQueryState,
} from '@/features/ctms/state'
import {
  CTMSOfflineMutationError,
  assertCTMSMutationAllowed,
  canRunCTMSMutation,
  useCTMSMutation,
} from '@/features/ctms/offline'
import {
  CTMSMutationFeedback,
  formatCTMSMutationMessage,
} from '@/features/ctms/components'

function setOnline(value: boolean) {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value })
}

describe('CTMS shared state primitives', () => {
  beforeEach(() => setOnline(true))

  it('keeps query states distinct across loading, refresh, empty, authorization, and degraded conditions', () => {
    expect(classifyCTMSQueryState({ isLoading: true })).toBe('loading')
    expect(classifyCTMSQueryState({ isFetching: true, data: { items: [{ id: '1' }] } })).toBe('refreshing')
    expect(classifyCTMSQueryState({ data: { items: [] } })).toBe('empty')
    expect(classifyCTMSQueryState({ error: { response: { status: 403 } } })).toBe('unauthorized')
    expect(classifyCTMSQueryState({ capability: 'disabled' })).toBe('disabled')
    expect(classifyCTMSQueryState({ capability: 'unavailable' })).toBe('unavailable')
    expect(classifyCTMSQueryState({ isOnline: false, data: { items: [{ id: '1' }] } })).toBe('offline')
    expect(classifyCTMSQueryState({ error: new Error('bad request') })).toBe('error')
    expect(classifyCTMSQueryState({ workerStatus: 'degraded', data: {} })).toBe('worker-unavailable')
    expect(classifyCTMSQueryState({ data: { id: 'record-1' } })).toBe('success')
  })

  it('classifies mutation feedback without treating offline as a server authorization result', () => {
    expect(classifyCTMSMutationState({ status: 'idle' })).toBe('idle')
    expect(classifyCTMSMutationState({ status: 'pending' })).toBe('pending')
    expect(classifyCTMSMutationState({ status: 'success' })).toBe('success')
    expect(classifyCTMSMutationState({ status: 'error', error: { response: { status: 403 } } })).toBe('unauthorized')
    expect(classifyCTMSMutationState({ status: 'error', isOnline: false })).toBe('offline')
    expect(classifyCTMSMutationState({ status: 'error', error: { response: { status: 503 } } })).toBe('unavailable')
  })

  it('blocks non-idempotent CTMS mutations offline without creating a queue', () => {
    expect(canRunCTMSMutation({ isOnline: false })).toBe(false)
    expect(canRunCTMSMutation({ isOnline: false, method: 'GET' })).toBe(true)
    expect(() => assertCTMSMutationAllowed({ isOnline: false })).toThrow(CTMSOfflineMutationError)
  })

  it('announces successful mutations with safe request and correlation identifiers', () => {
    expect(formatCTMSMutationMessage('Replay failed event', 'success', { request_id: 'req-123', correlation_id: 'corr-456' }))
      .toBe('Replay failed event completed successfully. Request ID req-123. Correlation ID corr-456.')
    expect(formatCTMSMutationMessage('Replay failed event', 'success', { request_id: 'not safe value!' }))
      .toBe('Replay failed event completed successfully.')
  })

  it('subscribes to browser offline events and blocks a wrapped write', async () => {
    const mutationFn = vi.fn().mockResolvedValue({ request_id: 'req-1' })

    function Probe() {
      const mutation = useCTMSMutation({ mutationFn })
      return <><button type="button" onClick={() => mutation.mutate()}>Submit</button><span>{String(mutation.canMutate)}</span></>
    }

    render(<QueryClientProvider client={new QueryClient()}><Probe /></QueryClientProvider>)
    setOnline(false)
    fireEvent(window, new Event('offline'))
    await waitFor(() => expect(screen.getByText('false')).toBeInTheDocument())
    expect(canRunCTMSMutation({ isOnline: false })).toBe(false)
    expect(mutationFn).not.toHaveBeenCalled()

    render(<CTMSMutationFeedback status="error" action="Submit change" error={new CTMSOfflineMutationError()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('cannot be submitted while offline')
  })
})
