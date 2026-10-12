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
    if (url === '/studies/study-1/versions') return Promise.resolve({ data: [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }] })
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
    localStorage.clear()
    window.history.replaceState({}, '', window.location.pathname)
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
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }] })
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

  it('opens form settings in a right-side drawer and exposes grid layout controls', async () => {
    mockBase()
    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Form settings' }))

    expect(screen.getByRole('dialog', { name: 'Form settings' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Form type'), { target: { value: 'grid' } })
    expect(screen.getByLabelText('Rows')).toBeInTheDocument()
    expect(screen.getByLabelText('Columns')).toBeInTheDocument()
    expect(screen.getByLabelText('Domain')).toBeInTheDocument()
    expect(screen.getByLabelText('Label')).toBeInTheDocument()
    const columns = screen.getByLabelText('Columns')
    columns.focus()
    fireEvent.change(columns, { target: { value: '4' } })
    await waitFor(() => expect(columns).toHaveFocus())
  })

  it('opens field settings in a right-side drawer', async () => {
    const detail = {
      ...FORM_DETAIL,
      show_variable_name: true,
      sections: [{
        id: 'sec-1', name: 'General', label: 'General', display_order: 1,
        fields: [{ id: 'fld-1', label: 'Height', text_align: 'left', variable_name: 'HEIGHT', control_type: 'float', data_type: 'float', is_required: false, display_order: 1 }],
      }],
    }
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }] })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/studies/study-1/codelists') return Promise.resolve({ data: [] })
      if (url === '/designer/forms/form-1') return Promise.resolve({ data: detail })
      if (url === '/designer/forms/form-1/dependencies') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))
    fireEvent.click((await screen.findByText('Height')).closest('button')!)

    expect(screen.getByRole('dialog', { name: 'Field settings' })).toBeInTheDocument()
    expect(screen.getByLabelText('CRF ID')).toBeInTheDocument()
    expect(screen.getByLabelText('ODM ID')).toBeInTheDocument()
  })

  it('shows each field type as its corresponding widget in the builder', async () => {
    const detail = {
      ...FORM_DETAIL,
      sections: [{
        id: 'sec-1', name: 'General', label: 'General', display_order: 1,
        fields: [
          { id: 'notes', label: 'Notes', text_align: 'left', variable_name: 'NOTES', control_type: 'textarea', data_type: 'string', is_required: false, display_order: 1 },
          { id: 'visit-date', label: 'Visit date', text_align: 'left', variable_name: 'VDATE', control_type: 'date', data_type: 'date', is_required: false, display_order: 2 },
          { id: 'score', label: 'Score', text_align: 'left', variable_name: 'SCORE', control_type: 'slider', data_type: 'float', is_required: false, display_order: 3 },
          { id: 'location', label: 'Location', text_align: 'left', variable_name: 'LOC', control_type: 'body_image', data_type: 'string', is_required: false, display_order: 4 },
        ],
      }],
    }
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: [{ id: 'ver-draft', study_id: 'study-1', version_number: '1', status: 'draft', created_at: 'x' }] })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/studies/study-1/codelists') return Promise.resolve({ data: [] })
      if (url === '/designer/forms/form-1') return Promise.resolve({ data: detail })
      if (url === '/designer/forms/form-1/dependencies') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    renderPage(<FormBuilderPage studyId="study-1" />)

    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))
    expect(await screen.findByLabelText('Notes preview')).toBeDisabled()
    expect(screen.getByLabelText('Visit date preview')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Score preview')).toHaveAttribute('type', 'range')
    expect(screen.getByRole('img', { name: 'Body image preview' })).toBeInTheDocument()
  })

  it('reviews published form and field settings in the normal builder without authoring controls', async () => {
    localStorage.setItem('designer:selected-version:study-1', 'ver-pub')
    const detail = {
      ...FORM_DETAIL,
      form_type: 'grid',
      access_type: 'restricted_edit',
      domain: 'VS',
      label: 'Vital Signs',
      grid_rows: 3,
      grid_columns: 2,
      sections: [{
        id: 'sec-1', name: 'General', label: 'General', display_order: 1,
        fields: [{ id: 'height', label: 'Height', text_align: 'left', variable_name: 'HEIGHT', control_type: 'float', data_type: 'float', is_required: false, display_order: 1 }],
      }],
    }
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/studies/study-1/versions') return Promise.resolve({ data: [
        { id: 'ver-draft', study_id: 'study-1', version_number: '2', status: 'draft', created_at: '2024-02-01' },
        { id: 'ver-pub', study_id: 'study-1', version_number: '1', status: 'published', created_at: '2024-01-01' },
      ] })
      if (url === '/designer/studies/study-1/forms') return Promise.resolve({ data: FORMS })
      if (url === '/designer/studies/study-1/codelists') return Promise.resolve({ data: [] })
      if (url === '/designer/forms/form-1') return Promise.resolve({ data: detail })
      if (url === '/designer/forms/form-1/dependencies') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    renderPage(<FormBuilderPage studyId="study-1" />)

    expect(await screen.findByText('Viewing published version 1. This design is read-only.')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /VITALS — Vitals/ }))
    expect(screen.queryByRole('button', { name: 'Add form' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add section' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reorder Height' })).not.toBeInTheDocument()

    fireEvent.click((await screen.findByText('Height')).closest('button')!)
    expect(screen.getByRole('dialog', { name: 'Field settings' })).toBeInTheDocument()
    expect(screen.getByLabelText('Variable name')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save field' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    fireEvent.click(screen.getByRole('button', { name: 'View form settings' }))
    expect(screen.getByRole('dialog', { name: 'Form settings' })).toBeInTheDocument()
    expect(screen.getByLabelText('Form name')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save form settings' })).not.toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/designer/studies/study-1/forms', { params: { study_version_id: 'ver-pub' } })
  })
})
