import * as React from 'react'
import { EmptyState as EmptyStatePrimitive } from '@/components/ui/empty-state'
import { cn } from '@/lib/utils'

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: string
  description?: React.ReactNode
  action?: React.ReactNode
  icon?: React.ReactNode
  requiresStudy?: boolean
  hasSelectedStudy?: boolean
  noSelectedStudyTitle?: string
  noSelectedStudyDescription?: React.ReactNode
}

export function EmptyState({ className, title, description, action, icon, requiresStudy = false, hasSelectedStudy = true, noSelectedStudyTitle = 'Select a study to continue', noSelectedStudyDescription = 'Choose a study context before viewing this content.', ...props }: EmptyStateProps) {
  const noSelectedStudy = requiresStudy && !hasSelectedStudy
  return (
    <EmptyStatePrimitive
      {...props}
      title={noSelectedStudy ? noSelectedStudyTitle : title ?? 'No records found'}
      description={noSelectedStudy ? noSelectedStudyDescription : description}
      action={action}
      icon={icon}
      data-state={noSelectedStudy ? 'no-selected-study' : 'empty'}
      className={cn(className)}
    />
  )
}
