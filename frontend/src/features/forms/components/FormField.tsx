import { useFormContext } from 'react-hook-form'
import { cn } from '@/lib/utils'

/**
 * Supported field control types for eCRF forms.
 */
export type ControlType =
  | 'text'
  | 'textarea'
  | 'integer'
  | 'decimal'
  | 'date'
  | 'dropdown'
  | 'radio'
  | 'checkbox'
  | 'boolean'

export interface CodelistItem {
  value: string
  label: string
}

export interface FieldDefinition {
  id: string
  name: string
  label: string
  control_type: ControlType
  is_required: boolean
  codelist_items?: CodelistItem[]
  min_value?: number
  max_value?: number
  placeholder?: string
  help_text?: string
}

interface FormFieldProps {
  field: FieldDefinition
  disabled?: boolean
  onFieldFocus?: (fieldId: string) => void
}

/**
 * Dynamic field renderer — renders the appropriate input control
 * based on the field's control_type definition.
 */
export function FormField({ field, disabled = false, onFieldFocus }: FormFieldProps) {
  const { register, formState: { errors } } = useFormContext()
  const fieldError = errors[field.id]
  const hasError = !!fieldError

  const baseInputClasses = cn(
    'w-full px-3 py-2 border rounded-md text-sm transition-colors',
    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
    'disabled:bg-gray-100 disabled:text-gray-500 disabled:cursor-not-allowed',
    hasError && 'border-red-500 ring-1 ring-red-500',
    !hasError && 'border-gray-300',
  )

  const handleFocus = () => {
    onFieldFocus?.(field.id)
  }

  const renderControl = () => {
    switch (field.control_type) {
      case 'text':
        return (
          <input
            type="text"
            id={field.id}
            className={baseInputClasses}
            placeholder={field.placeholder}
            disabled={disabled}
            onFocus={handleFocus}
            {...register(field.id)}
          />
        )

      case 'textarea':
        return (
          <textarea
            id={field.id}
            className={cn(baseInputClasses, 'min-h-[80px] resize-y')}
            placeholder={field.placeholder}
            disabled={disabled}
            rows={3}
            onFocus={handleFocus}
            {...register(field.id)}
          />
        )

      case 'integer':
        return (
          <input
            type="number"
            id={field.id}
            className={baseInputClasses}
            placeholder={field.placeholder}
            disabled={disabled}
            step="1"
            min={field.min_value}
            max={field.max_value}
            onFocus={handleFocus}
            {...register(field.id, { valueAsNumber: true })}
          />
        )

      case 'decimal':
        return (
          <input
            type="number"
            id={field.id}
            className={baseInputClasses}
            placeholder={field.placeholder}
            disabled={disabled}
            step="any"
            min={field.min_value}
            max={field.max_value}
            onFocus={handleFocus}
            {...register(field.id, { valueAsNumber: true })}
          />
        )

      case 'date':
        return (
          <input
            type="date"
            id={field.id}
            className={baseInputClasses}
            disabled={disabled}
            onFocus={handleFocus}
            {...register(field.id)}
          />
        )

      case 'dropdown':
        return (
          <select
            id={field.id}
            className={baseInputClasses}
            disabled={disabled}
            onFocus={handleFocus}
            {...register(field.id)}
          >
            <option value="">— Select —</option>
            {field.codelist_items?.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        )

      case 'radio':
        return (
          <div className="space-y-2" role="radiogroup" aria-labelledby={`${field.id}-label`}>
            {field.codelist_items?.map((item) => (
              <label key={item.value} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  value={item.value}
                  disabled={disabled}
                  className="h-4 w-4 text-blue-600 border-gray-300 focus:ring-blue-500 disabled:opacity-50"
                  onFocus={handleFocus}
                  {...register(field.id)}
                />
                <span className={cn(disabled && 'text-gray-500')}>{item.label}</span>
              </label>
            ))}
          </div>
        )

      case 'checkbox':
        return (
          <div className="space-y-2">
            {field.codelist_items?.map((item) => (
              <label key={item.value} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  value={item.value}
                  disabled={disabled}
                  className="h-4 w-4 rounded text-blue-600 border-gray-300 focus:ring-blue-500 disabled:opacity-50"
                  onFocus={handleFocus}
                  {...register(field.id)}
                />
                <span className={cn(disabled && 'text-gray-500')}>{item.label}</span>
              </label>
            ))}
          </div>
        )

      case 'boolean':
        return (
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              disabled={disabled}
              className="h-4 w-4 rounded text-blue-600 border-gray-300 focus:ring-blue-500 disabled:opacity-50"
              onFocus={handleFocus}
              {...register(field.id)}
            />
            <span className={cn(disabled && 'text-gray-500')}>Yes</span>
          </label>
        )

      default:
        return (
          <input
            type="text"
            id={field.id}
            className={baseInputClasses}
            disabled={disabled}
            onFocus={handleFocus}
            {...register(field.id)}
          />
        )
    }
  }

  return (
    <div className="space-y-1.5">
      <label
        id={`${field.id}-label`}
        htmlFor={field.id}
        className={cn(
          'block text-sm font-medium',
          disabled ? 'text-gray-500' : 'text-gray-700',
        )}
      >
        {field.label}
        {field.is_required && (
          <span className="text-red-500 ml-0.5" aria-label="required">*</span>
        )}
      </label>

      {renderControl()}

      {field.help_text && (
        <p className="text-xs text-gray-500">{field.help_text}</p>
      )}

      {fieldError && (
        <p className="text-xs text-red-600" role="alert">
          {fieldError.message as string}
        </p>
      )}
    </div>
  )
}
