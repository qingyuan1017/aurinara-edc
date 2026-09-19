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
  const user = useAuthStore((s) => s.user)
  const refreshUser = useAuthStore((s) => s.refreshUser)
  const navigate = useNavigate()

  useEffect(() => {
    if (!isAuthenticated) {
      navigate({ to: '/login' })
    } else if (!user) {
      void refreshUser()
    }
  }, [isAuthenticated, navigate, refreshUser, user])

  if (!isAuthenticated || !user) {
    return null
  }

  return <Outlet />
}
