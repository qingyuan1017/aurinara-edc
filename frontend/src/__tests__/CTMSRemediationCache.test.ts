import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { invalidateCTMSCoordinationRemediation } from '@/features/ctms/cache'

describe('CTMS coordination remediation cache policy', () => {
  it('invalidates coordination and affected operational queries without EDC keys', async () => {
    const queryClient = new QueryClient()
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(true)

    await invalidateCTMSCoordinationRemediation(queryClient, 'study-1', {
      id: 'task-1',
      event_id: 'event-1',
      event_type: 'OperationalTaskUpdated',
      entity_type: 'OperationalTask',
      conflict_type: 'VERSION_MISMATCH',
      status: 'open',
      sanitized_details: {},
    })

    const keys = invalidateQueries.mock.calls.map(([options]) => JSON.stringify(options.queryKey))
    expect(keys.some((key) => key.includes('failed-events'))).toBe(true)
    expect(keys.some((key) => key.includes('conflicts'))).toBe(true)
    expect(keys.some((key) => key.includes('events'))).toBe(true)
    expect(keys.some((key) => key.includes('projections'))).toBe(true)
    expect(keys.some((key) => key.includes('dashboard'))).toBe(true)
    expect(keys.some((key) => key.includes('report'))).toBe(true)
    expect(keys.some((key) => key.includes('tasks'))).toBe(true)
    expect(keys.every((key) => !/edc|clinical/i.test(key))).toBe(true)
  })
})
