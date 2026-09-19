import { useController, type Control, type FieldValues, type Path } from 'react-hook-form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export type CTMSFormFieldType = 'text' | 'date' | 'datetime-local' | 'number' | 'select' | 'textarea' | 'file'

export interface CTMSSelectOption {
  value: string
  label: string
}

export interface CTMSFormFieldProps<T extends FieldValues> {
  control: Control<T>
  name: Path<T>
  label: string
  type?: CTMSFormFieldType
  description?: string
  required?: boolean
  disabled?: boolean
  placeholder?: string
  options?: readonly CTMSSelectOption[]
  accept?: string
  className?: string
}

function fieldId(name: string): string {
  return `ctms-field-${name.replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

function fieldValue(value: unknown): string | number {
  return typeof value === 'number' ? value : typeof value === 'string' ? value : ''
}

/**
 * A small RHF-controlled field used by CTMS operational forms. It renders
 * metadata for file inputs only; file content is intentionally not persisted
 * by this component or in local storage.
 */
export function CTMSFormField<T extends FieldValues>({
  control,
  name,
  label,
  type = 'text',
  description,
  required = false,
  disabled = false,
  placeholder,
  options = [],
  accept,
  className,
}: CTMSFormFieldProps<T>) {
  const { field, fieldState } = useController({ control, name })
  const id = fieldId(String(name))
  const descriptionId = description ? `${id}-description` : undefined
  const errorId = fieldState.error ? `${id}-error` : undefined
  const describedBy = [descriptionId, errorId].filter(Boolean).join(' ') || undefined
  const invalid = Boolean(fieldState.error)
  const inputClassName = cn(
    'w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
    invalid ? 'border-destructive' : 'border-input',
  )

  const commonProps = {
    id,
    name: field.name,
    ref: field.ref,
    disabled,
    placeholder,
    'aria-invalid': invalid,
    'aria-describedby': describedBy,
    'aria-required': required,
    'data-ctms-form-control': true,
    onBlur: field.onBlur,
  }

  const input = type === 'textarea' ? (
    <Textarea
      {...commonProps}
      className={inputClassName}
      value={fieldValue(field.value)}
      onChange={(event) => field.onChange(event.target.value)}
      rows={4}
    />
  ) : type === 'select' ? (
    <select
      {...commonProps}
      className={cn(inputClassName, 'h-10')}
      value={fieldValue(field.value)}
      onChange={(event) => field.onChange(event.target.value)}
    >
      <option value="">Select an option</option>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  ) : type === 'file' ? (
    <Input
      {...commonProps}
      className={inputClassName}
      type="file"
      accept={accept}
      onChange={(event) => {
        const file = event.target.files?.[0]
        field.onChange(file ? { fileName: file.name, contentType: file.type, sizeBytes: file.size } : undefined)
      }}
    />
  ) : (
    <Input
      {...commonProps}
      className={inputClassName}
      type={type}
      inputMode={type === 'number' ? 'decimal' : undefined}
      value={fieldValue(field.value)}
      onChange={(event) => field.onChange(event.target.value)}
    />
  )

  return (
    <div className={cn('space-y-1.5', className)}>
      <Label htmlFor={id}>
        {label}{required ? <span aria-hidden="true"> *</span> : null}
      </Label>
      {description ? <p id={descriptionId} className="text-xs text-muted-foreground">{description}</p> : null}
      {input}
      {fieldState.error?.message ? <p id={errorId} role="alert" className="text-xs text-destructive">{fieldState.error.message}</p> : null}
    </div>
  )
}
