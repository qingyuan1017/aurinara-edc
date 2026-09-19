import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ResponsiveRecordList, type ResponsiveRecordFilter } from '@/features/ctms/components/ResponsiveRecordList'

type ReportRow = {
  id: string
  title: string
  status: string
}

type GeneratedReportCase = {
  page: number
  pageSize: number
  total: number
  priorRows: ReportRow[]
  serverPageRows: ReportRow[]
  clientRows: ReportRow[]
  filters: ResponsiveRecordFilter[]
}

/** A small deterministic generator keeps this property test dependency-free. */
function generator(seed: number) {
  let state = seed >>> 0
  return {
    next() {
      state = (Math.imul(state, 1_664_525) + 1_013_904_223) >>> 0
      return state
    },
    integer(maxExclusive: number) {
      return this.next() % maxExclusive
    },
  }
}

function generatedReportCase(seed: number): GeneratedReportCase {
  const random = generator(seed)
  const pageSize = [5, 10, 25][random.integer(3)]
  const page = 2 + random.integer(3)
  const total = (page - 1) * pageSize + 1 + random.integer(pageSize)
  const priorRows = Array.from({ length: 1 + random.integer(3) }, (_, index) => ({
    id: `prior-${seed}-${index}`,
    title: `Prior filtered row ${seed}-${index}`,
    status: 'Stale',
  }))
  const serverPageRows = Array.from({ length: 2 + random.integer(4) }, (_, index) => ({
    id: `current-${seed}-${index}`,
    title: `Current filtered row ${seed}-${index}`,
    status: index % 2 === 0 ? 'Open' : 'Blocked',
  }))
  const clientRows = serverPageRows.slice(0, 1 + random.integer(serverPageRows.length))
  const filters: ResponsiveRecordFilter[] = [
    { label: 'Status', value: seed % 2 === 0 ? 'Open' : 'Blocked' },
    { label: 'Site', value: `site-${seed}` },
  ]

  return { page, pageSize, total, priorRows, serverPageRows, clientRows, filters }
}

const columns = [
  { key: 'title', label: 'Task' },
  { key: 'status', label: 'Status' },
] as const

afterEach(() => cleanup())

describe('CTMS server-authoritative report properties', () => {
  it('Feature: ctms-frontend, Property 10: Server totals and filter results remain authoritative', () => {
    // **Validates: Requirements 6.2, 6.4–6.6, 11.7**
    for (let example = 0; example < 128; example += 1) {
      const generated = generatedReportCase(0xA710 + example)
      const { rerender } = render(
        <ResponsiveRecordList
          label="Tasks report"
          rows={generated.priorRows}
          columns={columns}
          emptyLabel="Tasks"
          pagination={{ page: 1, pageSize: generated.pageSize, total: generated.priorRows.length, onPageChange: () => undefined }}
        />,
      )

      rerender(
        <ResponsiveRecordList
          label="Tasks report"
          rows={generated.clientRows}
          columns={columns}
          emptyLabel="Tasks"
          filters={generated.filters}
          pagination={{
            page: generated.page,
            pageSize: generated.pageSize,
            total: generated.total,
            onPageChange: () => undefined,
          }}
        />,
      )

      const totalPages = Math.ceil(generated.total / generated.pageSize)
      expect(screen.getByText(`Page ${generated.page} of ${totalPages} (${generated.total} total)`)).toBeInTheDocument()
      expect(screen.getByText(`Status: ${String(generated.filters[0].value)}`)).toBeInTheDocument()
      expect(screen.getByText(`Site: ${String(generated.filters[1].value)}`)).toBeInTheDocument()

      for (const row of generated.clientRows) {
        expect(screen.getByText(row.title)).toBeInTheDocument()
      }
      for (const row of generated.priorRows) {
        expect(screen.queryByText(row.title)).not.toBeInTheDocument()
      }

      // The rendered subset comes only from the current server page; rows that
      // were not returned on that page must not be reconstructed client-side.
      for (const row of generated.serverPageRows.slice(generated.clientRows.length)) {
        expect(screen.queryByText(row.title)).not.toBeInTheDocument()
      }

      cleanup()
    }
  })
})
