import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import {
  ctmsApi,
  normalizeCTMSError,
  sanitizeCTMSRemediationDetails,
  serializeCTMSExportRequest,
} from '@/features/ctms/api'
import {
  attachmentConstraintsFixture,
  attachmentFixture,
  baselineErrorFixture,
  capabilityFixtures,
  conflictFixture,
  conflictResolutionOutcomeFixture,
  errorCategoryFixtures,
  exportJobFixtures,
  failedEventFixture,
  healthFixture,
  projectionFreshnessFixtures,
  queryContextFixture,
  replayOutcomeFixture,
  taskPageFixture,
  transitionFixture,
  transitionPayloadFixture,
} from './fixtures/ctmsContracts'

const projectionPageFixture = {
  items: Object.values(projectionFreshnessFixtures),
  page: 1,
  page_size: 25,
  total: 3,
}

function calledPaths(spy: { mock: { calls: unknown[][] } }): string[] {
  return spy.mock.calls.map(([path]) => String(path))
}

function expectCTMSMutationBoundary(paths: string[]) {
  expect(paths.every((path) => path.startsWith('/ctms/') || path.startsWith('/objects/'))).toBe(true)
  expect(paths.some((path) => /\/edc(?:\/|$)|clinical|visit[_-]?instances|form[_-]?instances|field[_-]?values|\/subjects(?:\/|$)/i.test(path))).toBe(false)
}

describe('CTMS API contract fixtures and adapters', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uses the existing versioned API client for capability, pagination, and filter contracts', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (path) => {
      if (String(path) === '/ctms/capabilities') return { data: capabilityFixtures.phase2 } as never
      return { data: taskPageFixture } as never
    })

    expect(api.defaults.baseURL).toBe('/api/v1')
    await expect(ctmsApi.capabilities()).resolves.toEqual(capabilityFixtures.phase2)
    await expect(ctmsApi.tasks('study-1', queryContextFixture)).resolves.toEqual(taskPageFixture)

    expect(calledPaths(get)).toEqual([
      '/ctms/capabilities',
      '/ctms/studies/study-1/tasks?status=Open%2CBlocked&owner_id=user-1&date_from=2026-03-01&date_to=2026-03-31&priority=high&due_category=overdue&include_archived=false&page=2&page_size=25&cursor=cursor-next-1',
    ])
    expect(taskPageFixture.page).toBe(2)
    expect(taskPageFixture.page_size).toBe(25)
    expect(taskPageFixture.total).toBe(51)
    expect(taskPageFixture.next_cursor).toBe('cursor-next-2')
  })

  it('preserves phase metadata and scoped ownership/freshness contracts', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (path) => {
      if (String(path).includes('/projections')) return { data: projectionPageFixture } as never
      return { data: capabilityFixtures.disabled } as never
    })

    await expect(ctmsApi.capabilities()).resolves.toMatchObject({ enabled: false, phase: 0, capabilities: [] })
    await expect(ctmsApi.projections('study-1', { studyId: 'study-1', phase: 2 })).resolves.toEqual(projectionPageFixture)

    expect(calledPaths(get)).toEqual([
      '/ctms/capabilities',
      '/ctms/studies/study-1/projections',
    ])
    expect(projectionFreshnessFixtures.current).toMatchObject({
      source_module: 'EDC',
      source_record_id: 'edc-signal-1',
      source_timestamp: '2026-03-01T09:55:00Z',
      projected_at: '2026-03-01T10:00:00Z',
      freshness: 'current',
      read_only: true,
    })
    expect(projectionFreshnessFixtures.stale.freshness).toBe('stale')
    expect(projectionFreshnessFixtures.unknown.freshness).toBe('unknown')
    expect(projectionFreshnessFixtures.current.payload).not.toHaveProperty('clinical_data')
  })

  it('uses CTMS transition endpoints and preserves server choices and correlation outcomes', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: transitionFixture } as never)

    await expect(ctmsApi.completeActivationAction('activation-1', transitionPayloadFixture)).resolves.toEqual(transitionFixture)

    expect(post).toHaveBeenCalledWith('/ctms/activation-actions/activation-1/complete', transitionPayloadFixture)
    expect(transitionFixture.allowed_transitions).toEqual([
      { status: 'In Progress' },
      { status: 'Blocked', requires_reason: true, reason_label: 'Blocking reason' },
      { status: 'Completed', requires_reason: true, reason_label: 'Completion reason' },
    ])
    expect(transitionFixture.meta).toEqual({
      requestId: 'request-transition-1',
      correlationId: 'correlation-transition-1',
      outcome: 'succeeded',
    })
    expectCTMSMutationBoundary(calledPaths(post))
  })

  it('normalizes representative baseline errors while preserving request and correlation identifiers', () => {
    const error = normalizeCTMSError({
      response: {
        status: 403,
        data: baselineErrorFixture,
      },
    })

    expect(error).toMatchObject({
      code: 'CTMS_SCOPE_DENIED',
      message: 'The requested CTMS record is outside your assigned scope.',
      category: errorCategoryFixtures.unauthorized,
      requestId: 'request-denied-1',
      correlationId: 'correlation-denied-1',
      retryable: false,
    })
    expect(error.details).toEqual({
      fields: { study_id: ['Study scope is not assigned.'] },
      safe_hint: 'Contact your CTMS administrator.',
    })
    expect(JSON.stringify(error)).not.toContain('must-not-render')
  })

  it('allowlists remediation details and drops raw event, clinical, and unrestricted message fields', () => {
    expect(sanitizeCTMSRemediationDetails({
      guidance: 'Retry after target recovery.',
      source_version: '4',
      current_version: '5',
      raw_event: 'must-not-render',
      clinical_data: { subject_status: 'must-not-render' },
      query_message: 'must-not-render',
      stack: 'must-not-render',
      arbitrary_value: 'must-not-render',
    })).toEqual({ guidance: 'Retry after target recovery.', source_version: '4', current_version: '5' })
  })


  it('covers export lifecycle, operational attachment constraints, and CTMS-only mutation paths', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (path) => {
      const requestPath = String(path)
      if (requestPath === '/ctms/studies/study-1/exports') return { data: { items: [exportJobFixtures.completed], page: 1, page_size: 25, total: 1 } } as never
      return { data: new Blob(['operational export']) } as never
    })
    const post = vi.spyOn(api, 'post').mockImplementation(async (path) => {
      if (String(path).includes('/exports')) return { data: exportJobFixtures.queued } as never
      return { data: attachmentFixture } as never
    })
    const del = vi.spyOn(api, 'delete').mockResolvedValue({ data: attachmentFixture } as never)

    await expect(ctmsApi.exports('study-1')).resolves.toEqual({
      items: [exportJobFixtures.completed],
      page: 1,
      page_size: 25,
      total: 1,
    })
    await expect(ctmsApi.createExport('study-1', {
      exportType: 'csv',
      filters: { siteId: 'site-1', recordTypes: ['tasks'], includeProjections: true },
    })).resolves.toEqual(exportJobFixtures.queued)
    await expect(ctmsApi.downloadExport(exportJobFixtures.completed.id)).resolves.toBeInstanceOf(Blob)

    const file = new File(['evidence'], 'monitoring-evidence.pdf', { type: attachmentFixture.content_type })
    await expect(ctmsApi.uploadAttachment({
      studyId: attachmentFixture.study_id,
      objectType: attachmentFixture.object_type,
      objectId: attachmentFixture.object_id,
      file,
      filename: attachmentFixture.filename,
      contentType: attachmentFixture.content_type,
    })).resolves.toEqual(attachmentFixture)
    await expect(ctmsApi.deleteAttachment(attachmentFixture.id, { reason: 'Retention-approved removal' })).resolves.toEqual(attachmentFixture)

    expect(calledPaths(get)).toEqual([
      '/ctms/studies/study-1/exports',
      '/ctms/exports/export-completed-1/download',
    ])
    expect(serializeCTMSExportRequest({
      exportType: 'csv',
      filters: { siteId: 'site-1', recordTypes: ['tasks'], includeProjections: true },
    })).toEqual({
      export_type: 'csv',
      filters: { site_id: 'site-1', record_types: ['tasks'], include_projections: true },
    })
    expect(exportJobFixtures.completed).toMatchObject({ module: 'CTMS', content_owner: 'CTMS', status: 'completed', expires_at: expect.any(String) })
    expect(exportJobFixtures.failed.status).toBe('failed')
    expect(exportJobFixtures.expired.status).toBe('expired')
    expect(attachmentConstraintsFixture.ownership).toBe('CTMS')
    expect(attachmentConstraintsFixture.attachment_type).toBe('Operational_Attachment')
    expect(attachmentConstraintsFixture.allowed_content_types).toContain(attachmentFixture.content_type)
    expect(attachmentFixture.size_bytes).toBeLessThanOrEqual(attachmentConstraintsFixture.max_size_bytes)

    const uploadCall = post.mock.calls.find(([path]) => String(path).includes('/files'))
    expect(uploadCall?.[0]).toBe('/objects/operational_task/task-1/files')
    expect(uploadCall?.[1]).toBeInstanceOf(FormData)
    expect((uploadCall?.[1] as FormData).get('file')).toBeInstanceOf(File)
    expect(post.mock.calls.find(([path]) => String(path).includes('/exports'))).toEqual([
      '/ctms/studies/study-1/exports',
      { export_type: 'csv', filters: { site_id: 'site-1', record_types: ['tasks'], include_projections: true } },
    ])
    expect(calledPaths(post)).toContain('/ctms/studies/study-1/exports')
    expect(calledPaths(post)).toContain('/objects/operational_task/task-1/files')
    expect(calledPaths(del)).toEqual(['/files/attachment-1'])
    expectCTMSMutationBoundary(calledPaths(post))
    expect(calledPaths(del).some((path) => /\/edc|clinical|visit[_-]?instances|form[_-]?instances/i.test(path))).toBe(false)
  })

  it('covers health, replay, conflict resolution, and asynchronous correlation outcomes', async () => {
    const get = vi.spyOn(api, 'get').mockImplementation(async (path) => {
      if (String(path).includes('/health')) return { data: healthFixture } as never
      if (String(path).includes('/failed-events')) return { data: { items: [failedEventFixture], page: 1, page_size: 25, total: 1 } } as never
      return { data: { items: [conflictFixture], page: 1, page_size: 25, total: 1 } } as never
    })
    const post = vi.spyOn(api, 'post').mockImplementation(async (path) => {
      if (String(path).includes('/replay')) return { data: replayOutcomeFixture } as never
      return { data: conflictResolutionOutcomeFixture } as never
    })

    await expect(ctmsApi.health()).resolves.toEqual(healthFixture)
    await expect(ctmsApi.failedEvents('study-1')).resolves.toEqual({ items: [failedEventFixture], page: 1, page_size: 25, total: 1 })
    await expect(ctmsApi.conflicts('study-1')).resolves.toEqual({ items: [conflictFixture], page: 1, page_size: 25, total: 1 })
    await expect(ctmsApi.replayEvent(failedEventFixture.event_id, 'Retry after target recovery')).resolves.toEqual(replayOutcomeFixture)
    await expect(ctmsApi.resolveConflict(conflictFixture.id, 'keep_current', 'Keep the server-confirmed status.')).resolves.toEqual(conflictResolutionOutcomeFixture)

    expect(calledPaths(get)).toEqual([
      '/ctms/health',
      '/ctms/studies/study-1/failed-events',
      '/ctms/studies/study-1/coordination-conflicts',
    ])
    expect(calledPaths(post)).toEqual([
      '/ctms/coordination-events/event-1/replay',
      '/ctms/coordination-conflicts/conflict-1/resolve',
    ])
    expect(post.mock.calls[0]?.[1]).toEqual({ reason: 'Retry after target recovery' })
    expect(post.mock.calls[1]?.[1]).toEqual({ policy: 'keep_current', reason: 'Keep the server-confirmed status.' })
    expect(healthFixture.worker_available).toBe(true)
    expect(failedEventFixture.correlation_id).toBe('correlation-replay-1')
    expect(replayOutcomeFixture).toMatchObject({ status: 'accepted', outcome: 'accepted', correlation_id: 'correlation-replay-accepted' })
    expect(conflictFixture.policy_choices).toEqual(['keep_current', 'apply_source'])
    expect(conflictResolutionOutcomeFixture).toMatchObject({ status: 'resolved', correlation_id: 'correlation-conflict-resolved' })
    expectCTMSMutationBoundary(calledPaths(post))
  })
})
