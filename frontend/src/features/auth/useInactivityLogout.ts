import { useEffect, useRef } from 'react'
import { useAuthStore } from '@/lib/auth'

const INACTIVITY_TIMEOUT_MS = 30 * 60 * 1000 // 30 minutes

/**
 * Hook that monitors user activity (mouse/keyboard) and
 * logs the user out after 30 minutes of inactivity.
 * Only active when the user is authenticated.
 */
export function useInactivityLogout() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const logout = useAuthStore((s) => s.logout)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!isAuthenticated) return

    const resetTimer = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
      timerRef.current = setTimeout(() => {
        void logout()
        window.location.href = '/login'
      }, INACTIVITY_TIMEOUT_MS)
    }

    const activityEvents = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'] as const

    // Start the timer
    resetTimer()

    // Reset on any user activity
    for (const event of activityEvents) {
      window.addEventListener(event, resetTimer)
    }

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
      for (const event of activityEvents) {
        window.removeEventListener(event, resetTimer)
      }
    }
  }, [isAuthenticated, logout])
}
