/* eslint-disable react-refresh/only-export-components */
import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors duration-[var(--duration-fast)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-md px-3',
        lg: 'h-11 rounded-md px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  loading?: boolean
  pending?: boolean
  loadingText?: string
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, pending = false, loadingText, children, disabled, ...props }, ref) => {
    const busy = loading || pending
    const content = busy && loadingText ? loadingText : children
    const classes = cn(buttonVariants({ variant, size, className }))
    const commonProps = {
      ...props,
      className: classes,
      ref,
      'aria-busy': busy || undefined,
      disabled: disabled || busy || undefined,
    }

    if (asChild && React.isValidElement(children)) {
      const child = children as React.ReactElement<{ className?: string; children?: React.ReactNode }>
      return React.cloneElement(child, {
        ...commonProps,
        className: cn(classes, child.props.className),
        children: busy && !loadingText ? <><span aria-hidden="true" className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />{content}</> : (busy && loadingText ? loadingText : child.props.children),
      } as React.HTMLAttributes<HTMLElement>)
    }

    return <button {...commonProps}>{busy && !loadingText ? <span aria-hidden="true" className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : null}{content}</button>
  },
)
Button.displayName = 'Button'

export { Button, buttonVariants }
