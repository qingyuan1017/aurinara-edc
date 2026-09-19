import * as React from 'react'
import type { FieldError } from 'react-hook-form'
import { cn } from '@/lib/utils'
import { Label } from '@/components/ui/label'

export type FormFieldError = Pick<FieldError, 'type' | 'message'> | { message?: unknown } | string | null | undefined

export interface FormFieldProps {
  label: React.ReactNode
  children: React.ReactElement
  name?: string
  id?: string
  description?: React.ReactNode
  error?: FormFieldError
  required?: boolean
  className?: string
}

function readableId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, '-')
}

function errorMessage(error: FormFieldError): string | undefined {
  if (typeof error === 'string') return error.trim() || undefined
  if (!error || typeof error !== 'object') return undefined
  return typeof error.message === 'string' && error.message.trim() ? error.message : undefined
}

/**
 * Presentation-only form field wrapper. Validation and server error mapping
 * remain owned by React Hook Form and the feature that renders the control.
 */
export function FormField({
  label,
  children,
  name,
  id,
  description,
  error,
  required = false,
  className,
}: FormFieldProps) {
  const generatedId = React.useId()
  const controlId = id ?? (name ? `field-${readableId(name)}` : `field-${readableId(generatedId)}`)
  const descriptionId = description ? `${controlId}-description` : undefined
  const validationMessage = errorMessage(error)
  const errorId = validationMessage ? `${controlId}-error` : undefined
  const describedBy = [
    (children.props as { 'aria-describedby'?: string })['aria-describedby'],
    descriptionId,
    errorId,
  ].filter(Boolean).join(' ') || undefined
  const childProps = children.props as {
    id?: string
    'aria-describedby'?: string
    'aria-invalid'?: boolean | 'true' | 'false'
    'aria-required'?: boolean | 'true' | 'false'
  }
  const control = React.cloneElement(children, {
    id: childProps.id ?? controlId,
    'aria-describedby': describedBy,
    'aria-invalid': validationMessage ? true : childProps['aria-invalid'],
    'aria-required': required || childProps['aria-required'] ? required || childProps['aria-required'] : undefined,
    'data-form-control': true,
  } as Partial<typeof childProps>)

  return (
    <div className={cn('space-y-1.5', className)} data-form-field={name}>
      <Label htmlFor={childProps.id ?? controlId}>
        {label}{required ? <span aria-hidden="true"> *</span> : null}
      </Label>
      {description ? <p id={descriptionId} className="text-xs text-muted-foreground">{description}</p> : null}
      {control}
      {validationMessage ? <p id={errorId} role="alert" className="text-xs text-destructive">{validationMessage}</p> : null}
    </div>
  )
}
