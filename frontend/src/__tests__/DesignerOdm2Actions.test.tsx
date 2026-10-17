import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DesignerOdm2Actions } from '@/features/designer/DesignerOdm2Actions'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

const DOCUMENT = {
  study: {
    metaDataVersion: {
      name: '2.0_23Dec2025',
    },
  },
}

const VALIDATION_REPORT = {
  valid: true,
  counts: { forms: 74, items: 899 },
  errors: [],
  warnings: [],
  extensionsUsed: [],
}

function jsonFile(contents: string) {
  const file = new File([contents], 'study.odm2.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(contents) })
  return file
}

function renderActions() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DesignerOdm2Actions studyId="study-1" versionId="version-current" allowImport />
    </QueryClientProvider>,
  )
}

describe('DesignerOdm2Actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    window.history.replaceState({}, '', window.location.pathname)
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url.endsWith('/validate')) return Promise.resolve({ data: VALIDATION_REPORT })
      return Promise.resolve({ data: { studyVersionId: 'version-new' } })
    })
  })

  it('creates a new draft by default using the ODM metadata version name', async () => {
    renderActions()

    fireEvent.click(screen.getByRole('button', { name: 'Import ODM 2.0' }))
    fireEvent.change(screen.getByLabelText('ODM JSON file'), {
      target: { files: [jsonFile(JSON.stringify(DOCUMENT))] },
    })

    expect(await screen.findByText(/Valid document:/)).toBeInTheDocument()
    expect(screen.getByLabelText('New draft version number')).toHaveValue('2.0_23Dec2025')
    fireEvent.click(screen.getByRole('button', { name: 'Import as new draft' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/studies/study-1/odm2/import',
      DOCUMENT,
      { params: { version_number: '2.0_23Dec2025' } },
    ))
    await waitFor(() => expect(localStorage.getItem('designer:selected-version:study-1')).toBe('version-new'))
    expect(new URLSearchParams(window.location.search).get('design_version_id')).toBe('version-new')
  })

  it('can explicitly import into the selected empty draft', async () => {
    renderActions()

    fireEvent.click(screen.getByRole('button', { name: 'Import ODM 2.0' }))
    fireEvent.change(screen.getByLabelText('ODM JSON file'), {
      target: { files: [jsonFile(JSON.stringify(DOCUMENT))] },
    })
    expect(await screen.findByText(/Valid document:/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: /Populate the selected draft/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Import into selected draft' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/studies/study-1/odm2/import',
      DOCUMENT,
      { params: { target_version_id: 'version-current' } },
    ))
  })
})
