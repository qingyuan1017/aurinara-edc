import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CTMSFilterBar } from '@/features/ctms/components/CTMSFilterBar'

const emptyFilters = {}

describe('CTMSFilterBar semantic presentation', () => {
  it('uses theme-safe shared control styles and preserves filter interactions', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const onClear = vi.fn()

    render(
      <CTMSFilterBar
        filters={{ status: 'Open', siteId: 'site-1' }}
        onChange={onChange}
        onClear={onClear}
        showReportType
      />,
    )

    expect(screen.getByRole('heading', { name: 'Filters' })).toHaveClass('text-foreground')
    expect(screen.getByRole('combobox', { name: 'Status filter' })).toHaveClass('border-input', 'bg-background', 'focus-visible:ring-ring')
    expect(screen.getByRole('combobox', { name: 'Priority filter' })).toHaveClass('border-input', 'bg-background', 'focus-visible:ring-ring')
    expect(screen.getByText('Status: Open')).toHaveClass('bg-info/15', 'text-info')
    expect(screen.getByText('Site: site-1')).toHaveClass('bg-info/15', 'text-info')

    await user.selectOptions(screen.getByRole('combobox', { name: 'Priority filter' }), 'high')
    expect(onChange).toHaveBeenCalledWith({ priority: 'high' })
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('does not render a clear action or filter badge for an empty filter state', () => {
    render(<CTMSFilterBar filters={emptyFilters} onChange={vi.fn()} onClear={vi.fn()} />)

    expect(screen.getByText('None')).toHaveClass('text-muted-foreground')
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument()
  })
})
