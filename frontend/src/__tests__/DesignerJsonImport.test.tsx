import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DesignerJsonImport } from '@/features/designer/DesignerJsonImport'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

function renderImporter() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DesignerJsonImport studyId="study-1" />
    </QueryClientProvider>,
  )
}

function jsonFile(contents: string) {
  const file = new File([contents], 'definitions.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(contents) })
  return file
}

describe('DesignerJsonImport', () => {
  beforeEach(() => vi.clearAllMocks())

  it('previews collection counts and submits the parsed JSON', async () => {
    const payload = {
      forms: [{ name: 'Demographics', form_code: 'DM', display_order: 1, sections: [] }],
      edit_checks: [],
      codelists: [],
      visits: [{ name: 'Baseline', visit_number: 1, visit_type: 'scheduled', display_order: 1 }],
    }
    vi.mocked(api.post).mockResolvedValue({
      data: {
        forms_created: 1,
        sections_created: 0,
        fields_created: 0,
        edit_checks_created: 0,
        codelists_created: 0,
        codelist_items_created: 0,
        visits_created: 1,
      },
    } as never)

    renderImporter()
    fireEvent.click(screen.getByRole('button', { name: 'Import JSON' }))
    fireEvent.change(screen.getByLabelText('JSON file'), { target: { files: [jsonFile(JSON.stringify(payload))] } })

    expect(await screen.findByText(/1 forms · 0 edit checks · 0 codelists · 1 visits/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import definitions' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/studies/study-1/bulk-import',
      payload,
    ))
    expect(await screen.findByText(/Imported 1 forms/)).toBeInTheDocument()
  })

  it('rejects malformed files before calling the API', async () => {
    renderImporter()
    fireEvent.click(screen.getByRole('button', { name: 'Import JSON' }))
    fireEvent.change(screen.getByLabelText('JSON file'), { target: { files: [jsonFile('{bad json')] } })

    expect(await screen.findByText('The selected file is not valid JSON.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import definitions' })).toBeDisabled()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('validates and imports pasted JSON text', async () => {
    const payload = {
      forms: [],
      edit_checks: [{ name: 'Required', rule_json: { field: 'AETERM', operator: 'is_null' }, severity: 'query' }],
      codelists: [],
      visits: [],
    }
    vi.mocked(api.post).mockResolvedValue({
      data: {
        forms_created: 0,
        sections_created: 0,
        fields_created: 0,
        edit_checks_created: 1,
        codelists_created: 0,
        codelist_items_created: 0,
        visits_created: 0,
      },
    } as never)

    renderImporter()
    fireEvent.click(screen.getByRole('button', { name: 'Import JSON' }))
    fireEvent.change(screen.getByLabelText('JSON text'), { target: { value: JSON.stringify(payload) } })
    fireEvent.click(screen.getByRole('button', { name: 'Validate JSON text' }))

    expect(await screen.findByText(/Pasted JSON/)).toBeInTheDocument()
    expect(screen.getByText(/0 forms · 1 edit checks · 0 codelists · 0 visits/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import definitions' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/studies/study-1/bulk-import',
      payload,
    ))
    expect(await screen.findByText(/Imported 0 forms/)).toBeInTheDocument()
  })
})
