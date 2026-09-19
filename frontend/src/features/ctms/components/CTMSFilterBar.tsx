import type { CTMSFilterState } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { PageToolbar } from '@/components/patterns'
import { activeCTMSFilters } from '../filters'

export interface CTMSFilterBarProps {
  filters: CTMSFilterState
  onChange: (change: Partial<CTMSFilterState>) => void
  onClear: () => void
  showReportType?: boolean
}

const statusOptions = ['Active', 'Open', 'Blocked', 'Completed', 'Failed', 'Scheduled', 'Overdue']
const priorityOptions = ['low', 'medium', 'high', 'critical']
const dueCategoryOptions = ['overdue', 'due_today', 'due_this_week', 'upcoming']
const reportTypeOptions = ['dashboard', 'enrollment', 'monitoring', 'tasks', 'readiness', 'milestones', 'quality-signals']

function selectValue(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? '' : value ?? ''
}

const fieldClassName = 'mt-1 text-sm'
const selectClassName = 'mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'
const filterLabelClassName = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'

export function CTMSFilterBar({ filters, onChange, onClear, showReportType = false }: CTMSFilterBarProps) {
  const activeFilters = activeCTMSFilters(filters)

  return (
    <PageToolbar label="CTMS filters" className="space-y-3 bg-card p-4" aria-labelledby="ctms-filter-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="ctms-filter-heading" className="text-sm font-semibold text-foreground">Filters</h2>
        {activeFilters.length > 0 && (
          <Button type="button" onClick={onClear} variant="outline" size="sm">
            Clear filters
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className={filterLabelClassName}>
          Status
          <Input
            className={fieldClassName}
            list="ctms-status-options"
            value={selectValue(filters.status)}
            onChange={(event) => onChange({ status: event.target.value || undefined })}
            placeholder="Any status"
            aria-label="Status filter"
          />
          <datalist id="ctms-status-options">{statusOptions.map((option) => <option key={option} value={option} />)}</datalist>
        </label>
        <label className={filterLabelClassName}>
          Site
          <Input className={fieldClassName} value={filters.siteId ?? ''} onChange={(event) => onChange({ siteId: event.target.value || undefined })} placeholder="Any site" aria-label="Site filter" />
        </label>
        <label className={filterLabelClassName}>
          Owner
          <Input className={fieldClassName} value={filters.ownerId ?? ''} onChange={(event) => onChange({ ownerId: event.target.value || undefined })} placeholder="Any owner" aria-label="Owner filter" />
        </label>
        <label className={filterLabelClassName}>
          Priority
          <select className={selectClassName} value={filters.priority ?? ''} onChange={(event) => onChange({ priority: event.target.value || undefined })} aria-label="Priority filter">
            <option value="">Any priority</option>{priorityOptions.map((option) => <option key={option}>{option}</option>)}
          </select>
        </label>
        <label className={filterLabelClassName}>
          From date
          <Input className={fieldClassName} type="date" value={filters.from ?? ''} onChange={(event) => onChange({ from: event.target.value || undefined })} aria-label="From date filter" />
        </label>
        <label className={filterLabelClassName}>
          To date
          <Input className={fieldClassName} type="date" value={filters.to ?? ''} onChange={(event) => onChange({ to: event.target.value || undefined })} aria-label="To date filter" />
        </label>
        <label className={filterLabelClassName}>
          Due-date category
          <select className={selectClassName} value={filters.dueCategory ?? ''} onChange={(event) => onChange({ dueCategory: event.target.value || undefined })} aria-label="Due-date category filter">
            <option value="">Any due date</option>{dueCategoryOptions.map((option) => <option key={option}>{option.replaceAll('_', ' ')}</option>)}
          </select>
        </label>
        {showReportType && <label className={filterLabelClassName}>
          Report type
          <select className={selectClassName} value={filters.reportType ?? ''} onChange={(event) => onChange({ reportType: event.target.value || undefined })} aria-label="Report type filter">
            <option value="">Current report</option>{reportTypeOptions.map((option) => <option key={option}>{option}</option>)}
          </select>
        </label>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm" role="status" aria-live="polite" aria-label="Active filters">
        <span className="font-semibold text-foreground">Active filters:</span>
        {activeFilters.length === 0 ? <span className="text-muted-foreground">None</span> : activeFilters.map((filter) => <Badge key={filter.label} variant="info">{filter.label}: {filter.value}</Badge>)}
      </div>
    </PageToolbar>
  )
}
