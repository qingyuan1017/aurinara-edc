import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ResponsiveRecordList, type ResponsiveRecordColumn } from '@/features/ctms/components'

interface RecordItem {
  id: string
  title: string
  status: string
  updated_at: string
}

const columns: ResponsiveRecordColumn<RecordItem>[] = [
  { key: 'title', label: 'Title' },
  { key: 'status', label: 'Status', status: true },
  { key: 'updated_at', label: 'Updated', date: true },
]

const rows: RecordItem[] = [{ id: 'task-1', title: 'Confirm activation', status: 'Open', updated_at: '2026-01-01T10:00:00Z' }]

describe('ResponsiveRecordList', () => {
  it('renders semantic headers, ownership-aware status text, and mobile card fields', () => {
    render(<ResponsiveRecordList label="Operational tasks" rows={rows} columns={columns} emptyLabel="Operational tasks" />)

    expect(screen.getByRole('columnheader', { name: 'Title' })).toHaveAttribute('scope', 'col')
    expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument()
    expect(screen.getAllByTestId('operational-status')).toHaveLength(2)
    expect(screen.getByRole('list', { name: 'Operational tasks cards' })).toHaveTextContent('Confirm activation')
  })

  it('shows active filters and keyboard-operable pagination controls', () => {
    const onPageChange = vi.fn()
    render(
      <ResponsiveRecordList
        label="Operational tasks"
        rows={rows}
        columns={columns}
        emptyLabel="Operational tasks"
        filters={[{ label: 'Status', value: 'Open' }, { label: 'Site', value: 'site-1' }]}
        pagination={{ page: 1, pageSize: 1, total: 3, onPageChange }}
      />,
    )

    expect(screen.getByRole('status', { name: 'Active filters' })).toHaveTextContent('Status: Open')
    const next = screen.getByRole('button', { name: 'Next Operational tasks page' })
    expect(next).toBeEnabled()
    fireEvent.click(next)
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('keeps an actionable row action in the keyboard focus order', () => {
    render(
      <ResponsiveRecordList
        label="Operational tasks"
        rows={rows}
        columns={columns}
        emptyLabel="Operational tasks"
        renderActions={() => <button type="button">Open record</button>}
      />,
    )

    expect(screen.getAllByRole('button', { name: 'Open record' })).toHaveLength(2)
  })
})
