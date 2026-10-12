import { useFormContext } from 'react-hook-form'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export type ControlType =
  | 'label' | 'text' | 'textarea' | 'listbox' | 'radio' | 'checkbox'
  | 'time' | 'date' | 'datetime' | 'integer' | 'decimal' | 'float'
  | 'slider' | 'body_image' | 'unit' | 'dropdown' | 'multi-select'
  | 'boolean' | 'file_upload' | 'calculated' | 'repeating_table' | 'coded_term'

export interface CodelistItem { value: string; label: string }
export interface FieldDefinition {
  id: string
  name?: string
  label: string
  question?: string | null
  caption?: string | null
  text_align?: string
  control_type: ControlType
  data_type?: string
  is_required: boolean
  codelist_items?: CodelistItem[]
  min_value?: number | string | null
  max_value?: number | string | null
  max_length?: number | null
  decimal_precision?: number | null
  placeholder?: string
  help_text?: string | null
  unit?: string | null
  is_read_only?: boolean
  is_calculated?: boolean
}
interface FormFieldProps { field: FieldDefinition; disabled?: boolean; onFieldFocus?: (fieldId: string) => void }

const BODY_REGIONS = ['Head', 'Chest', 'Abdomen', 'Left arm', 'Right arm', 'Left leg', 'Right leg', 'Back']
const selectClassName = 'flex min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'

/** Dynamic eCRF control renderer shared by every data-entry form. */
export function FormField({ field, disabled = false, onFieldFocus }: FormFieldProps) {
  const { register, setValue, watch, formState: { errors } } = useFormContext()
  const fieldError = errors[field.id]
  const errorMessage = typeof fieldError?.message === 'string' ? fieldError.message : undefined
  const describedBy = [field.help_text ? `${field.id}-help` : undefined, errorMessage ? `${field.id}-error` : undefined].filter(Boolean).join(' ') || undefined
  const isDisabled = disabled || Boolean(field.is_read_only)
  const common = { id: field.id, disabled: isDisabled, placeholder: field.placeholder, 'aria-invalid': Boolean(fieldError), 'aria-describedby': describedBy, onFocus: () => onFieldFocus?.(field.id) }
  const inputClassName = cn(fieldError && 'border-destructive ring-1 ring-destructive')
  const choices = field.codelist_items ?? []
  const watchedValue = watch(field.id)
  const choiceFallback = <p className="text-xs text-muted-foreground">No codelist options configured.</p>

  const renderControl = () => {
    switch (field.control_type) {
      case 'label':
        return <p className="rounded-md bg-muted/50 px-3 py-2 text-sm" role="note">{field.caption || field.question || field.label}</p>
      case 'textarea':
        return <Textarea rows={3} maxLength={field.max_length ?? undefined} {...common} className={cn('min-h-20 resize-y', inputClassName)} {...register(field.id)} />
      case 'integer':
        return <Input type="number" step="1" min={field.min_value ?? undefined} max={field.max_value ?? undefined} {...common} className={inputClassName} {...register(field.id, { valueAsNumber: true })} />
      case 'decimal':
      case 'float':
        return <Input type="number" step={field.decimal_precision != null ? 10 ** -field.decimal_precision : 'any'} min={field.min_value ?? undefined} max={field.max_value ?? undefined} {...common} className={inputClassName} {...register(field.id, { valueAsNumber: true })} />
      case 'slider':
        return <div className="space-y-1"><input type="range" min={field.min_value ?? 0} max={field.max_value ?? 100} step={field.decimal_precision != null ? 10 ** -field.decimal_precision : 1} className="w-full accent-primary" {...common} {...register(field.id, { valueAsNumber: true })} /><div className="flex justify-between text-xs text-muted-foreground"><span>{field.min_value ?? 0}</span><output htmlFor={field.id}>{String(watchedValue ?? field.min_value ?? 0)}</output><span>{field.max_value ?? 100}</span></div></div>
      case 'date':
        return <Input type="date" {...common} className={inputClassName} {...register(field.id)} />
      case 'time':
        return <Input type="time" {...common} className={inputClassName} {...register(field.id)} />
      case 'datetime':
        return <Input type="datetime-local" {...common} className={inputClassName} {...register(field.id)} />
      case 'dropdown':
      case 'coded_term':
        return choices.length ? <select {...common} className={cn(selectClassName, inputClassName)} {...register(field.id)}><option value="">— Select —</option>{choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select> : choiceFallback
      case 'listbox':
        return choices.length ? <select {...common} size={Math.min(Math.max(choices.length, 2), 6)} className={cn(selectClassName, 'h-auto', inputClassName)} {...register(field.id)}>{choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select> : choiceFallback
      case 'multi-select':
        return choices.length ? <select {...common} multiple size={Math.min(Math.max(choices.length, 3), 7)} className={cn(selectClassName, 'h-auto', inputClassName)} {...register(field.id)}>{choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select> : choiceFallback
      case 'radio':
        return choices.length ? <div className="space-y-2" role="radiogroup" aria-labelledby={`${field.id}-label`}>{choices.map((item) => <label key={item.value} className="flex cursor-pointer items-center gap-2 text-sm"><input type="radio" value={item.value} disabled={isDisabled} className="size-4 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>{item.label}</span></label>)}</div> : choiceFallback
      case 'checkbox':
        return choices.length ? <div className="space-y-2" role="group" aria-labelledby={`${field.id}-label`}>{choices.map((item) => <label key={item.value} className="flex cursor-pointer items-center gap-2 text-sm"><Checkbox value={item.value} disabled={isDisabled} onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>{item.label}</span></label>)}</div> : <label className="flex cursor-pointer items-center gap-2 text-sm"><Checkbox disabled={isDisabled} onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>Selected</span></label>
      case 'boolean':
        return <label className="flex cursor-pointer items-center gap-2 text-sm"><Checkbox disabled={isDisabled} onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} /><span>Yes</span></label>
      case 'body_image':
        return <div className="grid gap-3 rounded-md border p-3 sm:grid-cols-[7rem_1fr]"><svg viewBox="0 0 100 180" role="img" aria-label="Body location diagram" className="mx-auto h-40 fill-muted stroke-muted-foreground"><circle cx="50" cy="18" r="13" /><path d="M35 35h30l8 55-13 5-2 70H45l-3-70-14-5z" /><path d="M35 42 15 90l10 5 20-42M65 42l20 48-10 5-20-42" fill="none" strokeWidth="8" /></svg><div className="grid grid-cols-2 gap-2">{BODY_REGIONS.map((region) => <label key={region} className="flex items-center gap-1.5 text-xs"><input type="radio" value={region} disabled={isDisabled} onFocus={() => onFieldFocus?.(field.id)} {...register(field.id)} />{region}</label>)}</div></div>
      case 'unit':
        return <div className="flex"><Input type={['integer', 'float', 'decimal'].includes(field.data_type ?? '') ? 'number' : 'text'} maxLength={field.max_length ?? undefined} {...common} className={cn('rounded-r-none', inputClassName)} {...register(field.id, { valueAsNumber: ['integer', 'float', 'decimal'].includes(field.data_type ?? '') })} /><span className="flex items-center rounded-r-md border border-l-0 bg-muted px-3 text-sm text-muted-foreground">{field.unit || 'unit'}</span></div>
      case 'file_upload': {
        const registration = register(field.id)
        return <Input type="file" id={field.id} disabled={isDisabled} aria-describedby={describedBy} aria-invalid={Boolean(fieldError)} ref={registration.ref} name={registration.name} onBlur={registration.onBlur} onFocus={() => onFieldFocus?.(field.id)} onChange={(event) => setValue(field.id, event.target.files?.[0]?.name ?? '', { shouldDirty: true, shouldValidate: true })} className={inputClassName} />
      }
      case 'calculated':
        return <Input type="text" {...common} readOnly aria-readonly="true" className={cn('bg-muted', inputClassName)} {...register(field.id)} />
      case 'repeating_table': {
        const rows = Array.isArray(watchedValue) ? watchedValue.map(String) : watchedValue ? [String(watchedValue)] : ['']
        return <div className="space-y-2"><div className="overflow-hidden rounded-md border"><table className="w-full text-sm"><thead className="bg-muted"><tr><th className="px-3 py-2 text-left">Row</th><th className="w-16 px-3 py-2"><span className="sr-only">Actions</span></th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${field.id}-${index}`} className="border-t"><td className="p-2"><Input aria-label={`${field.label} row ${index + 1}`} value={row} disabled={isDisabled} onFocus={() => onFieldFocus?.(field.id)} onChange={(event) => { const next = [...rows]; next[index] = event.target.value; setValue(field.id, next, { shouldDirty: true, shouldValidate: true }) }} /></td><td className="p-2"><Button type="button" size="sm" variant="ghost" disabled={isDisabled || rows.length === 1} onClick={() => setValue(field.id, rows.filter((_, rowIndex) => rowIndex !== index), { shouldDirty: true, shouldValidate: true })}>Remove</Button></td></tr>)}</tbody></table></div><Button type="button" size="sm" variant="outline" disabled={isDisabled} onClick={() => setValue(field.id, [...rows, ''], { shouldDirty: true })}>Add row</Button></div>
      }
      case 'text':
      default:
        return <Input type="text" maxLength={field.max_length ?? undefined} {...common} className={inputClassName} {...register(field.id)} />
    }
  }

  if (field.control_type === 'label') {
    return <div className="space-y-1.5" style={{ textAlign: field.text_align as 'left' | 'center' | 'right' }}>{renderControl()}{field.help_text ? <p id={`${field.id}-help`} className="text-xs text-muted-foreground">{field.help_text}</p> : null}</div>
  }

  return <div className="space-y-1.5" style={{ textAlign: field.text_align as 'left' | 'center' | 'right' }}>
    <Label id={`${field.id}-label`} htmlFor={field.id} className={isDisabled ? 'text-muted-foreground' : undefined}>{field.question || field.label}{field.is_required ? <span aria-hidden="true"> *</span> : null}</Label>
    {field.caption ? <p className="text-xs text-muted-foreground">{field.caption}</p> : null}
    {renderControl()}
    {field.help_text ? <p id={`${field.id}-help`} className="text-xs text-muted-foreground">{field.help_text}</p> : null}
    {errorMessage ? <p id={`${field.id}-error`} className="text-xs text-destructive" role="alert">{errorMessage}</p> : null}
  </div>
}
