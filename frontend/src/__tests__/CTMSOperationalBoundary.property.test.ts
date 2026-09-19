import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import {
  CTMS_ACTION_ROUTE_MAP,
  CTMS_CAPABILITY_CODES,
  isCTMSActionAvailable,
  normalizeCTMSCapabilities,
} from '@/features/ctms/capabilities'
import {
  ctmsApi,
  serializeCTMSExportRequest,
  type CTMSExportFilters,
  type CTMSExportRequest,
} from '@/features/ctms/api'

const prohibitedKeys = [
  'subject_id',
  'visit_instance_id',
  'form_instance_id',
  'field_value',
  'query_id',
  'clinical_data',
  'clinical_attachment_id',
  'clinical_export_id',
  'source_module',
  'content_owner',
  'attachment_type',
  'projection',
  'attachment',
  'export',
] as const

type UntrustedFilters = CTMSExportFilters & Record<string, unknown>
type UntrustedExportRequest = CTMSExportRequest & Record<string, unknown> & { filters: UntrustedFilters }

/**
 * fast-check is not installed in this repository. This deterministic generator
 * provides the required generated-example coverage without external services.
 */
function generatedOperationalInputs(count: number): UntrustedExportRequest[] {
  const formats: CTMSExportRequest['exportType'][] = ['csv', 'json', 'excel']
  return Array.from({ length: count }, (_, index) => {
    const marker = `clinical-marker-${index}`
    const filters: UntrustedFilters = {
      siteId: `site-${index}`,
      recordTypes: [`milestone-${index}`],
      statuses: [index % 2 === 0 ? 'active' : 'planned'],
      dateFrom: `2026-01-${String((index % 9) + 1).padStart(2, '0')}`,
      dateTo: `2026-02-${String((index % 9) + 1).padStart(2, '0')}`,
      includeArchived: index % 2 === 0,
      includeProjections: index % 3 === 0,
      projectionTypes: [`approved-quality-signal-${index}`],
      page: index + 1,
      pageSize: 20,
      subject_id: marker,
      visit_instance_id: marker,
      form_instance_id: marker,
      field_value: marker,
      query_id: marker,
      clinical_data: { value: marker },
      clinical_attachment_id: marker,
      clinical_export_id: marker,
      source_module: 'EDC',
      content_owner: 'EDC',
      attachment_type: 'Clinical_Attachment',
    }

    return {
      exportType: formats[index % formats.length],
      studyId: `edc-study-${index}`,
      linkedReference: { studyId: `edc-study-${index}`, siteId: `site-${index}` },
      projection: { source_module: 'EDC', source_record_id: marker, payload: { clinical_data: marker } },
      attachment: { module: 'EDC', attachment_type: 'Clinical_Attachment', object_id: marker },
      export: { content_owner: 'EDC', export_type: 'clinical' },
      filters,
    }
  })
}

function availableOperationalActions() {
  const state = normalizeCTMSCapabilities({
    module: 'CTMS',
    enabled: true,
    phase: 3,
    capabilities: Object.values(CTMS_CAPABILITY_CODES),
    platform_capabilities: { health_observability: true },
  })
  const permissions = Object.values(CTMS_ACTION_ROUTE_MAP)
    .flatMap((descriptor) => descriptor.permission ? [descriptor.permission] : [])

  return Object.values(CTMS_ACTION_ROUTE_MAP).filter((descriptor) => isCTMSActionAvailable(state, descriptor, permissions))
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CTMS operational payload and action boundary properties', () => {
  // Feature: ctms-frontend, Property 3: Operational payloads cannot become clinical mutation requests
  // **Validates: Requirements 1.2, 1.5, 5.1–5.4, 7.3–7.4, 8.1, 8.6, 12.2–12.6**
  it('strips prohibited clinical ownership fields across 128 generated operational inputs', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: {} } as never)
    const actions = availableOperationalActions()

    for (const input of generatedOperationalInputs(128)) {
      const serialized = serializeCTMSExportRequest(input)
      const studyId = String(input.studyId)
      await ctmsApi.createExport(studyId, input)
      const lastCall = post.mock.calls[post.mock.calls.length - 1]

      expect(lastCall?.[0]).toBe(`/ctms/studies/${studyId}/exports`)
      expect(lastCall?.[1]).toEqual(serialized)
      expect(Object.keys(serialized)).toEqual(['export_type', 'filters'])
      expect(Object.keys(serialized.filters as Record<string, unknown>).sort()).toEqual([
        'date_from',
        'date_to',
        'due_category',
        'include_archived',
        'include_projections',
        'page',
        'page_size',
        'priority',
        'projection_types',
        'record_types',
        'site_id',
        'statuses',
      ].filter((key) => key in (serialized.filters as Record<string, unknown>)).sort())
      expect(serialized).not.toHaveProperty('study_id')
      expect(serialized).not.toHaveProperty('projection')
      expect(serialized).not.toHaveProperty('attachment')
      expect(serialized).not.toHaveProperty('export')

      const serializedText = JSON.stringify(serialized)
      expect(prohibitedKeys.every((key) => !serializedText.includes(`"${key}"`))).toBe(true)
      expect(serializedText).not.toContain('Clinical_Attachment')
      expect(serializedText).not.toContain('clinical-marker-')
      expect(serializedText).not.toContain('content_owner')
      expect(serializedText).not.toContain('source_module')

      expect(actions.every((action) => (
        action.owner === 'CTMS'
        && action.clinicalMutation === false
        && action.route.includes('/ctms')
        && !/clinical|edc/i.test(action.route)
      ))).toBe(true)
    }

    expect(post).toHaveBeenCalledTimes(128)
    expect(actions.length).toBeGreaterThan(0)
  })
})
