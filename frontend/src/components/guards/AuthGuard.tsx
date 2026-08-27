import { useEffect } from 'react'
import { useNavigate, Outlet } from '@tanstack/react-router'
import { useAuthStore } from '@/lib/auth'

/**
 * AuthGuard — wraps authenticated routes.
 * Redirects to /login if the user is not authenticated.
 * Frontend check is convenience only; server enforces authoritatively.
 */
export function AuthGuard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const navigate = useNavigate()

  useEffect(() => {
    if (!isAuthenticated) {
      navigate({ to: '/login' })
    }
  }, [isAuthenticated, navigate])

  if (!isAuthenticated) {
    return null
  }

  return <Outlet />
}
