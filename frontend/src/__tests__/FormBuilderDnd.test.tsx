import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { FormBuilderPage } from '@/features/designer/FormBuilderPage'
import { useAuthStore } from '@/lib/auth'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

function renderPage(ui: ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {ui}
    </QueryClientProvider>,
  )
}

function seedPermissions(permissions: string[]) {
  useAuthStore.setState({
    user: { id: 'user-1', email: 'd@example.com', first_name: 'D', last_name: 'S', roles: [], permissions },
    isAuthenticated: true,
  })
}

const FORMS = [{ id: 'form-1', name: 'Vitals', form_code: 'VITALS', display_order: 1, is_repeating: false }]
const FORM_DETAIL = {
  id: 'form-1',
  name: 'Vitals',
  form_code: 'VITALS',
  display_order: 1,
  is_repeating: false,
  sections: [{ id: 'sec-1', name: 'General', display_order: 1, fields: [] }],
}

function mockBase() {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
    if (url === '/designer/studies/study-1/codelists') return Promise.resolve({ data: [] })
    if (url === '/designer/forms/form-1') return Promise.resolve({ data: FORM_DETAIL })
    if (url === '/designer/forms/form-1/dependencies') return Promise.resolve({ data: [] })
    return Promise.resolve({ data: [] })
  })
}

describe('FormBuilderPage (dnd)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    seedPermissions(['designer.form.read', 'designer.form.configure', 'designer.field.configure'])
  })

  it('palette renders the real control-type list (wire values incl. multi-select)', async () => {
    mockBase()
    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))

    const palette = await screen.findByRole('button', { name: 'multi-select', hidden: true }).catch(() => null)
    // The palette shows draggable field-type buttons for each ControlType value.
    const draggables = await screen.findAllByRole('button')
    const labels = draggables.map((b) => b.textContent)
    expect(labels).toContain('text')
    expect(labels).toContain('multi-select')
    expect(labels).not.toContain('multi_select')
    expect(labels).toContain('coded_term')
    void palette
  })

  it('the keyboard "Add field" path POSTs a field with the chosen control_type', async () => {
    mockBase()
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'fld-1' } } as never)

    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))

    const select = await screen.findByLabelText('Add field type to General')
    fireEvent.change(select, { target: { value: 'dropdown' } })
    // The per-section "Add field" button lives alongside its select.
    const addButtons = screen.getAllByRole('button', { name: 'Add field' })
    fireEvent.click(addButtons[0])

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/forms/form-1/fields',
      expect.objectContaining({ control_type: 'dropdown' }),
      expect.objectContaining({ params: { section_id: 'sec-1' } }),
    ))
  })

  it('exposes a keyboard-reachable Add field affordance per section', async () => {
    mockBase()
    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))

    const select = await screen.findByLabelText('Add field type to General')
    expect(select).toBeInTheDocument()
    const addButton = screen.getAllByRole('button', { name: 'Add field' })[0]
    expect(within(addButton.parentElement as HTMLElement).getByLabelText('Add field type to General')).toBe(select)
  })

  it('form dependency select excludes the current form', async () => {
    const forms = [
      { id: 'form-1', name: 'Vitals', form_code: 'VITALS', display_order: 1, is_repeating: false },
      { id: 'form-2', name: 'Labs', form_code: 'LABS', display_order: 2, is_repeating: false },
    ]
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: forms })
      if (url === '/designer/studies/study-1/codelists') return Promise.resolve({ data: [] })
      if (url === '/designer/forms/form-1') return Promise.resolve({ data: FORM_DETAIL })
      if (url === '/designer/forms/form-1/dependencies') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    vi.mocked(api.post).mockResolvedValue({ data: { id: 'dep-1' } } as never)

    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))

    const select = await screen.findByLabelText('Prerequisite form') as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)
    expect(values).not.toContain('form-1')
    expect(values).toContain('form-2')

    fireEvent.change(select, { target: { value: 'form-2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add prerequisite' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/designer/forms/form-1/dependencies',
      { depends_on_form_definition_id: 'form-2', dependency_type: 'prerequisite', condition_expression: null },
    ))
  })
})
