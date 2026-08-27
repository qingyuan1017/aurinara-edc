import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { StatusBadge } from '@/features/subjects/components/StatusBadge'

describe('StatusBadge', () => {
  describe('subject statuses', () => {
    it('renders "screening" with blue color', () => {
      render(<StatusBadge domain="subject" status="screening" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveTextContent('screening')
      expect(badge).toHaveClass('bg-blue-100', 'text-blue-800')
    })

    it('renders "enrolled" with green color', () => {
      render(<StatusBadge domain="subject" status="enrolled" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-green-100', 'text-green-800')
    })

    it('renders "withdrawn" with red color', () => {
      render(<StatusBadge domain="subject" status="withdrawn" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-red-100', 'text-red-800')
    })

    it('renders "completed" with indigo color', () => {
      render(<StatusBadge domain="subject" status="completed" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-indigo-100', 'text-indigo-800')
    })
  })

  describe('form statuses', () => {
    it('renders "not started" with gray color', () => {
      render(<StatusBadge domain="form" status="not started" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-gray-100', 'text-gray-800')
    })

    it('renders "in progress" with yellow color', () => {
      render(<StatusBadge domain="form" status="in progress" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-yellow-100', 'text-yellow-800')
    })

    it('renders "submitted" with green color', () => {
      render(<StatusBadge domain="form" status="submitted" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-green-100', 'text-green-800')
    })

    it('renders "locked" with red color', () => {
      render(<StatusBadge domain="form" status="locked" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-red-100', 'text-red-800')
    })
  })

  describe('query statuses', () => {
    it('renders "open" with red color', () => {
      render(<StatusBadge domain="query" status="open" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-red-100', 'text-red-800')
    })

    it('renders "answered" with orange color', () => {
      render(<StatusBadge domain="query" status="answered" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-orange-100', 'text-orange-800')
    })

    it('renders "closed" with green color', () => {
      render(<StatusBadge domain="query" status="closed" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-green-100', 'text-green-800')
    })
  })

  describe('unknown status fallback', () => {
    it('falls back to gray for an unknown status', () => {
      render(<StatusBadge domain="subject" status="unknown" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-gray-100', 'text-gray-800')
    })
  })

  describe('case normalization', () => {
    it('normalizes status to lowercase for color lookup', () => {
      render(<StatusBadge domain="subject" status="Enrolled" />)
      const badge = screen.getByRole('status')
      expect(badge).toHaveClass('bg-green-100', 'text-green-800')
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
