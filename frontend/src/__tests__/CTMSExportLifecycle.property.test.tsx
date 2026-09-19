import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OperationalExportPanel } from '@/features/ctms/components/OperationalExportPanel'
import {
  serializeCTMSExportRequest,
  type CTMSExport,
  type CTMSExportFormat,
  type CTMSExportRequest,
} from '@/features/ctms/api'
import { api } from '@/lib/api'

type ServerAction = 'refresh' | 'retry' | 'download'

interface GeneratedExportCase {
  exportType: CTMSExportFormat
  status: 'queued' | 'running' | 'completed' | 'failed' | 'expired'
  canManage: boolean
  canRead: boolean
  request: CTMSExportRequest
  job: CTMSExport
  serverActions: ServerAction[]
}

const formats: CTMSExportFormat[] = ['csv', 'json', 'excel']
const statuses: GeneratedExportCase['status'][] = ['queued', 'running', 'completed', 'failed', 'expired']

function generatedExportCases(count: number): GeneratedExportCase[] {
  return Array.from({ length: count }, (_, index) => {
    const status = statuses[index % statuses.length]
    const exportType = formats[index % formats.length]
    const canManage = index % 2 === 0
    const canRead = index % 3 !== 0
    const request = {
      exportType,
      filters: {
        siteId: `site-${index}`,
        recordTypes: ['operational_task', `operational_contact_${index}`],
        statuses: ['Open', `Pending-${index}`],
        dateFrom: `2026-03-${String((index % 9) + 1).padStart(2, '0')}T09:00:00.000Z`,
        dateTo: `2026-03-${String((index % 9) + 10).padStart(2, '0')}T17:00:00.000Z`,
        includeArchived: index % 2 === 0,
        includeProjections: index % 4 === 0,
        projectionTypes: ['Approved quality signal'],
        page: (index % 4) + 1,
        pageSize: 25 + (index % 4),
        // These fields represent hostile clinical input and are not part of the CTMS request contract.
        clinicalSubjectId: `subject-${index}`,
        clinicalQueryId: `query-${index}`,
      },
      // These extra fields must not cross the operational export boundary either.
      clinicalExport: true,
      clinicalAttachmentIds: [`clinical-attachment-${index}`],
    } as unknown as CTMSExportRequest
    const serverActions: ServerAction[] = ['refresh']
    if (status === 'failed' && canManage) serverActions.push('retry')
    if (status === 'completed' && canRead) serverActions.push('download')

    return {
      exportType,
      status,
      canManage,
      canRead,
      request,
      job: {
        id: `export-${status}-${index}`,
        study_id: 'study-1',
        module: 'CTMS',
        content_owner: 'CTMS',
        export_type: exportType,
        status,
        filters: request.filters as Record<string, unknown>,
        created_at: '2026-03-01T10:00:00Z',
        ...(status === 'failed' ? { error_message: 'Operational export failed.' } : {}),
        ...(status === 'expired' ? { expires_at: '2026-02-01T10:00:00Z' } : {}),
      },
      serverActions,
    }
  })
}

function actionLabel(action: ServerAction): string {
  switch (action) {
    case 'refresh': return 'Refresh status'
    case 'retry': return 'Retry export'
    case 'download': return 'Download operational export'
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CTMS export lifecycle properties', () => {
  // Feature: ctms-frontend, Property 8: Export lifecycle actions follow server state
  // **Validates: Requirements 8.1–8.3, 8.6**
  it('serializes operational options only, labels CTMS ownership, and exposes server-state actions across 128 generated cases', async () => {
    const cases = generatedExportCases(128)
    const jobs = new Map(cases.map((scenario) => [scenario.job.id, scenario.job]))
    vi.spyOn(api, 'get').mockImplementation(async (path) => {
      const exportId = String(path).split('/').pop() ?? ''
      return { data: jobs.get(exportId) } as never
    })

    for (const scenario of cases) {
      const serialized = serializeCTMSExportRequest(scenario.request)
      const filters = scenario.request.filters ?? {}

      expect(serialized).toEqual({
        export_type: scenario.exportType,
        filters: {
          site_id: filters.siteId,
          record_types: filters.recordTypes,
          statuses: filters.statuses,
          date_from: filters.dateFrom,
          date_to: filters.dateTo,
          include_archived: filters.includeArchived,
          include_projections: filters.includeProjections,
          projection_types: filters.projectionTypes,
          page: filters.page,
          page_size: filters.pageSize,
        },
      })
      expect(serialized).not.toHaveProperty('clinical_export')
      expect(serialized).not.toHaveProperty('clinical_attachment_ids')
      expect(JSON.stringify(serialized)).not.toContain('clinicalSubjectId')
      expect(JSON.stringify(serialized)).not.toContain('clinicalQueryId')
      expect(JSON.stringify(serialized)).not.toContain('clinical-attachment-')

      expect(scenario.job).toMatchObject({ module: 'CTMS', content_owner: 'CTMS' })

      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity } },
      })
      const view = render(
        <QueryClientProvider client={queryClient}>
          <OperationalExportPanel
            studyId="study-1"
            jobs={[scenario.job]}
            canManage={scenario.canManage}
            canRead={scenario.canRead}
            onRefresh={vi.fn()}
          />
        </QueryClientProvider>,
      )

      if (scenario.canManage) {
        expect(screen.getByRole('button', { name: 'Request operational export' })).toBeInTheDocument()
      } else {
        expect(screen.queryByRole('button', { name: 'Request operational export' })).not.toBeInTheDocument()
      }

      fireEvent.click(screen.getByRole('button', { name: 'View status' }))
      const detail = await screen.findByRole('region', { name: `Export ${scenario.job.id} details` })
      expect(detail).toHaveTextContent('This is CTMS-owned operational content.')
      expect(within(detail).getAllByRole('button').map((button) => button.textContent?.trim())).toEqual(
        scenario.serverActions.map(actionLabel),
      )

      view.unmount()
      queryClient.clear()
    }
  })
})
