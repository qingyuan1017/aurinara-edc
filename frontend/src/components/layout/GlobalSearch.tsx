import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * Search affordance placeholder. There is no supported global-search contract,
 * so this control is intentionally non-submitting and does not touch query state.
 */
export function GlobalSearch() {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled
      aria-label="Global search unavailable"
      title="Global search is not available"
      className="min-w-28 justify-start text-muted-foreground"
    >
      <Search className="size-4" aria-hidden="true" />
      <span>Search unavailable</span>
    </Button>
  )
}
