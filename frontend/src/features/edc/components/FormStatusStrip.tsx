import { StatusBadge } from '@/components/patterns'

export interface FormStatusDimensions {
  dataEntry: string
  queries?: string
  review?: string
  sdv?: string
  signature?: string
  lock: string
}

/**
 * Presents each available workflow dimension separately. Missing dimensions
 * are omitted rather than inferred from another clinical status.
 */
export function FormStatusStrip({ status }: { status: FormStatusDimensions }) {
  const dimensions = [
    ['Data entry', status.dataEntry],
    ['Queries', status.queries],
    ['Review', status.review],
    ['SDV', status.sdv],
    ['Signature', status.signature],
    ['Lock', status.lock],
  ] as const

  return (
    <section aria-label="Form workflow statuses" className="flex flex-wrap gap-2 rounded-lg border bg-muted/20 p-3">
      {dimensions.map(([label, value]) => value ? (
          <div key={label} className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{label}</span>
            <StatusBadge status={value} label={`${label} status`} />
          </div>
        ) : null)}
    </section>
  )
}
