import { StatusBadge } from '@/components/patterns'

/**
 * Renders the exact textual status value the server returns for a Safety_Case,
 * Case_Version, assessment, coding, Regulatory_Report, or reconciliation state.
 * The same component is used in both list and detail views so the textual value
 * is identical across them (Requirement 19.1).
 */
export function PVStatus({ status, label = 'Status' }: { status: string; label?: string }) {
  return <StatusBadge status={status} label={label} />
}

/**
 * Labels a read-only EDC/CTMS projection field with its owning source so it is
 * never mistaken for PV-authoritative data (design: source-labeled projections).
 */
export function PVSourceLabel({ source }: { source: string }) {
  return (
    <span
      className="inline-flex items-center rounded-sm bg-muted px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-muted-foreground"
      title={`Read-only projection from ${source}`}
    >
      {source} · read-only
    </span>
  )
}
