import { useFormContext } from 'react-hook-form'
import { cn } from '@/lib/utils'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export type ControlType = 'text' | 'textarea' | 'integer' | 'decimal' | 'date' | 'dropdown' | 'radio' | 'checkbox' | 'boolean'
export interface CodelistItem { value: string; label: string }
export interface FieldDefinition { id: string; name: string; label: string; control_type: ControlType; is_required: boolean; codelist_items?: CodelistItem[]; min_value?: number; max_value?: number; placeholder?: string; help_text?: string }
interface FormFieldProps { field: FieldDefinition; disabled?: boolean; onFieldFocus?: (fieldId: string) => void }

/** Dynamic eCRF control renderer. RHF registration and clinical validation remain unchanged. */
export function FormField({ field, disabled = false, onFieldFocus }: FormFieldProps) {
  const { register, formState: { errors } } = useFormContext()
  const fieldError = errors[field.id]
  const errorMessage = typeof fieldError?.message === 'string' ? fieldError.message : undefined
  const describedBy = [field.help_text ? `${field.id}-help` : undefined, errorMessage ? `${field.id}-error` : undefined].filter(Boolean).join(' ') || undefined
  const common = { id: field.id, disabled, placeholder: field.placeholder, 'aria-invalid': Boolean(fieldError), 'aria-describedby': describedBy, onFocus: () => onFieldFocus?.(field.id) }
  const inputClassName = cn(fieldError && 'border-destructive ring-1 ring-destructive')

  const renderControl = () => {
    switch (field.control_type) {
      case 'textarea': return <Textarea rows={3} {...common} className={cn('min-h-20 resize-y', inputClassName)} {...register(field.id)} />
      case 'integer': return <Input type="number" step="1" min={field.min_value} max={field.max_value} {...common} className={inputClassName} {...register(field.id, { valueAsNumber: true })} />
      case 'decimal': return <Input type="number" step="any" min={field.min_value} max={field.max_value} {...common} className={inputClassName} {...register(field.id, { valueAsNumber: true })} />
      case 'date': return <Input type="date" {...common} className={inputClassName} {...register(field.id)} />
      case 'dropdown': return <select {...common} className={cn('flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', inputClassName)} {...register(field.id)}><option value="">— Select —</option>{field.codelist_items?.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
      case 'radio': return <div className="space-y-2" role="radiogroup" aria-labelledby={`${field.id}-label`}>{field.codelist_items?.map((item) => <label key={item.value} className="flex cursor-pointer items-center gap-2 text-sm"><input type="radio" value={item.value} disabled={disabled} className="size-4 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>{item.label}</span></label>)}</div>
      case 'checkbox': return <div className="space-y-2">{field.codelist_items?.map((item) => <label key={item.value} className="flex cursor-pointer items-center gap-2 text-sm"><Checkbox value={item.value} disabled={disabled} onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>{item.label}</span></label>)}</div>
      case 'boolean': return <label className="flex cursor-pointer items-center gap-2 text-sm"><Checkbox disabled={disabled} onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>Yes</span></label>
      default: return <Input type="text" {...common} className={inputClassName} {...register(field.id)} />
    }
  }

  return <div className="space-y-1.5">
    <Label id={`${field.id}-label`} htmlFor={field.id} className={disabled ? 'text-muted-foreground' : undefined}>{field.label}{field.is_required ? <span aria-hidden="true"> *</span> : null}</Label>
    {renderControl()}
    {field.help_text ? <p id={`${field.id}-help`} className="text-xs text-muted-foreground">{field.help_text}</p> : null}
    {errorMessage ? <p id={`${field.id}-error`} className="text-xs text-destructive" role="alert">{errorMessage}</p> : null}
  </div>
}
