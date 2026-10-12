import { FormProvider, useForm } from 'react-hook-form'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FormField, type FieldDefinition } from '@/features/forms/components/FormField'

const choices = [{ value: 'MILD', label: 'Mild' }, { value: 'SEVERE', label: 'Severe' }]
const field = (id: string, control_type: FieldDefinition['control_type'], extra: Partial<FieldDefinition> = {}): FieldDefinition => ({
  id,
  name: id,
  label: id,
  control_type,
  is_required: false,
  ...extra,
})

function WidgetHarness({ fields }: { fields: FieldDefinition[] }) {
  const methods = useForm({ defaultValues: { repeat: ['Initial row'] } })
  return <FormProvider {...methods}><form>{fields.map((item) => <FormField key={item.id} field={item} />)}</form></FormProvider>
}

describe('FormField widget mapping', () => {
  it('renders the corresponding native widget for authored field types', () => {
    render(<WidgetHarness fields={[
      field('Text', 'text'),
      field('Narrative', 'textarea'),
      field('Visit date', 'date'),
      field('Visit time', 'time'),
      field('Count', 'integer'),
      field('Weight', 'float'),
      field('Severity', 'dropdown', { codelist_items: choices }),
      field('Listbox', 'listbox', { codelist_items: choices }),
      field('Multiple', 'multi-select', { codelist_items: choices }),
      field('Radio', 'radio', { codelist_items: choices }),
      field('Checks', 'checkbox', { codelist_items: choices }),
      field('Range', 'slider', { min_value: 0, max_value: 10 }),
      field('Body', 'body_image'),
      field('Dose', 'unit', { unit: 'mg', data_type: 'float' }),
      field('Attachment', 'file_upload'),
      field('Derived', 'calculated'),
      field('Heading', 'label'),
    ]} />)

    expect(screen.getByLabelText('Text')).toHaveAttribute('type', 'text')
    expect(screen.getByLabelText('Narrative').tagName).toBe('TEXTAREA')
    expect(screen.getByLabelText('Visit date')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Visit time')).toHaveAttribute('type', 'time')
    expect(screen.getByLabelText('Count')).toHaveAttribute('step', '1')
    expect(screen.getByLabelText('Weight')).toHaveAttribute('step', 'any')
    expect(screen.getByLabelText('Severity').tagName).toBe('SELECT')
    expect(screen.getByLabelText('Listbox')).toHaveAttribute('size', '2')
    expect(screen.getByLabelText('Multiple')).toHaveAttribute('multiple')
    expect(screen.getByRole('radiogroup', { name: 'Radio' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Checks' })).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: 'Range' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Body location diagram' })).toBeInTheDocument()
    expect(screen.getByText('mg')).toBeInTheDocument()
    expect(screen.getByLabelText('Attachment')).toHaveAttribute('type', 'file')
    expect(screen.getByLabelText('Derived')).toHaveAttribute('readonly')
    expect(screen.getByRole('note')).toHaveTextContent('Heading')
  })

  it('supports repeating rows as structured values', () => {
    render(<WidgetHarness fields={[field('repeat', 'repeating_table', { label: 'Concomitant medication' })]} />)

    expect(screen.getByLabelText('Concomitant medication row 1')).toHaveValue('Initial row')
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }))
    expect(screen.getByLabelText('Concomitant medication row 2')).toBeInTheDocument()
  })
})
