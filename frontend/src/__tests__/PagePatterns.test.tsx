import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { DataTableShell } from '@/components/patterns/DataTableShell'
import { DetailCard } from '@/components/patterns/DetailCard'
import { EmptyState } from '@/components/patterns/EmptyState'
import { ErrorState, type PresentationState } from '@/components/patterns/ErrorState'
import { LoadingState } from '@/components/patterns/LoadingState'
import { MetricCard } from '@/components/patterns/MetricCard'
import { OwnershipBadge } from '@/components/patterns/OwnershipBadge'
import { PageContainer } from '@/components/patterns/PageContainer'
import { PageHeader } from '@/components/patterns/PageHeader'
import { PageToolbar } from '@/components/patterns/PageToolbar'
import { StatusBadge } from '@/components/patterns/StatusBadge'

const degradedStates: PresentationState[] = ['error', 'unauthorized', 'offline', 'disabled', 'unavailable', 'worker-unavailable']

describe('shared page patterns', () => {
  it('composes labeled page structure and server-provided slots', () => {
    render(
      <PageContainer>
        <PageHeader title="Study overview" description="Server-provided description" breadcrumbs={<a href="/studies">Studies</a>} status={<StatusBadge status="Ready" />} ownership={<OwnershipBadge owner="EDC" />} freshness={<StatusBadge status="Current" label="Freshness" />} actions={<button type="button">Export</button>} />
        <PageToolbar label="Study filters" actions={<button type="button">Apply</button>}><input aria-label="Search" /></PageToolbar>
        <MetricCard label="Enrollment" value={42} description="Current total" />
        <DetailCard title="Study details" status={<StatusBadge status="Active" />}><p>Server detail</p></DetailCard>
      </PageContainer>,
    )

    expect(screen.getByRole('heading', { name: 'Study overview', level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Studies')
    expect(screen.getByRole('toolbar', { name: 'Study filters' })).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Study details' })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: /authoritative module: EDC/i })).toHaveTextContent('EDC · Authoritative')
  })

  it('renders loading and non-blocking refreshing semantics', () => {
    const { rerender } = render(<LoadingState label="study records" />)
    expect(screen.getByRole('status', { name: 'Loading study records…' })).toHaveAttribute('data-state', 'loading')

    rerender(<LoadingState label="study records" refreshing />)
    expect(screen.getByRole('status', { name: 'Refreshing study records…' })).toHaveAttribute('data-state', 'refreshing')
  })

  it('renders every error and degraded state with explicit semantics', () => {
    for (const state of degradedStates) {
      const { unmount } = render(<ErrorState state={state} />)
      const alert = screen.getByRole(state === 'error' ? 'alert' : 'status')
      expect(alert.parentElement).toHaveAttribute('data-state', state)
      unmount()
    }
  })

  it('calls the retry callback without moving error handling into the pattern', () => {
    const onRetry = vi.fn()
    render(<ErrorState state="error" onRetry={onRetry} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('shows a no-selected-study prompt through the empty-state pattern', () => {
    render(<EmptyState requiresStudy={true} hasSelectedStudy={false} action={<button type="button">Choose study</button>} />)
    expect(screen.getByRole('status')).toHaveAttribute('data-state', 'no-selected-study')
    expect(screen.getByRole('heading', { name: 'Select a study to continue' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose study' })).toBeInTheDocument()
  })

  it('preserves all explicit table states and supplies a responsive keyboard-accessible surface', () => {
    const { rerender } = render(<DataTableShell label="Subjects" loading><table><tbody><tr><td>Not rendered while loading</td></tr></tbody></table></DataTableShell>)
    expect(screen.getByRole('region', { name: 'Subjects' })).toHaveAttribute('data-state', 'loading')

    rerender(<DataTableShell label="Subjects" empty requiresStudy hasSelectedStudy={false} />)
    expect(screen.getByRole('heading', { name: 'Select a study to continue' })).toBeInTheDocument()

    rerender(<DataTableShell label="Subjects" state="offline" onRetry={() => undefined} />)
    expect(screen.getByRole('region', { name: 'Subjects' })).toHaveAttribute('data-state', 'offline')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()

    rerender(<DataTableShell label="Subjects"><table><caption>Subjects</caption><tbody><tr><td>Subject 001</td></tr></tbody></table></DataTableShell>)
    const scrollSurface = screen.getByRole('region', { name: 'Subjects' }).querySelector('[aria-label="Scrollable Subjects table"]')
    expect(scrollSurface).toHaveClass('overflow-x-auto')
    expect(scrollSurface).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('table')).toHaveTextContent('Subject 001')
  })

  it('renders status, ownership, and freshness as text with non-color cues', () => {
    render(<><StatusBadge status="Stale" label="Projection freshness" freshness="stale" /><OwnershipBadge owner="CTMS" state="projected" readOnly /></>)
    expect(screen.getByRole('status', { name: 'Projection freshness: Stale · stale' })).toHaveTextContent('Stale · stale')
    expect(screen.getByRole('status', { name: /authoritative module: CTMS/i })).toHaveTextContent('CTMS · Projected · Read only')
    expect(screen.getByText('●')).toBeInTheDocument()
    expect(screen.getByText('◆')).toBeInTheDocument()
  })
})
