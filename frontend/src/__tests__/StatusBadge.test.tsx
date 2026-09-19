import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { StatusBadge } from '@/features/subjects/components/StatusBadge'

describe('StatusBadge', () => {
  describe('subject statuses', () => {
    it('renders "screening" with blue color', () => {
      render(<StatusBadge domain="subject" status="screening" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveTextContent('screening')
      expect(badge).toHaveClass('border-transparent', 'bg-info/15', 'text-info')
    })

    it('renders "enrolled" with green color', () => {
      render(<StatusBadge domain="subject" status="enrolled" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-success/15', 'text-success')
    })

    it('renders "withdrawn" with red color', () => {
      render(<StatusBadge domain="subject" status="withdrawn" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-destructive', 'text-destructive-foreground')
    })

    it('renders "completed" with indigo color', () => {
      render(<StatusBadge domain="subject" status="completed" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-info/15', 'text-info')
    })
  })

  describe('form statuses', () => {
    it('renders "not started" with gray color', () => {
      render(<StatusBadge domain="form" status="not started" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-secondary', 'text-secondary-foreground')
    })

    it('renders "in progress" with yellow color', () => {
      render(<StatusBadge domain="form" status="in progress" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-warning/20', 'text-warning-foreground')
    })

    it('renders "submitted" with green color', () => {
      render(<StatusBadge domain="form" status="submitted" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-success/15', 'text-success')
    })

    it('renders "locked" with red color', () => {
      render(<StatusBadge domain="form" status="locked" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-destructive', 'text-destructive-foreground')
    })
  })

  describe('query statuses', () => {
    it('renders "open" with red color', () => {
      render(<StatusBadge domain="query" status="open" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-destructive', 'text-destructive-foreground')
    })

    it('renders "answered" with orange color', () => {
      render(<StatusBadge domain="query" status="answered" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-warning/20', 'text-warning-foreground')
    })

    it('renders "closed" with green color', () => {
      render(<StatusBadge domain="query" status="closed" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-success/15', 'text-success')
    })
  })

  describe('unknown status fallback', () => {
    it('falls back to gray for an unknown status', () => {
      render(<StatusBadge domain="subject" status="unknown" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-secondary', 'text-secondary-foreground')
    })
  })

  describe('case normalization', () => {
    it('normalizes status to lowercase for color lookup', () => {
      render(<StatusBadge domain="subject" status="Enrolled" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('border-transparent', 'bg-success/15', 'text-success')
    })
  })

  describe('accessibility', () => {
    it('includes an accessible aria-label', () => {
      render(<StatusBadge domain="query" status="open" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveAttribute('aria-label', 'query status: open')
    })
  })
})
