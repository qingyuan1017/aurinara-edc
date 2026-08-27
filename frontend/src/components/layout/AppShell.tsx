import { useState } from 'react'
import { Outlet, Link, useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '@/lib/auth'
import { StudySelector } from './StudySelector'
import { SiteSelector } from './SiteSelector'

interface NavItem {
  label: string
  to: string
  icon: string
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: '📊' },
  { label: 'Studies', to: '/studies', icon: '📋' },
  { label: 'Sites', to: '/sites', icon: '🏥' },
  { label: 'Subjects', to: '/subjects', icon: '👤' },
  { label: 'Forms', to: '/forms', icon: '📝' },
  { label: 'Queries', to: '/queries', icon: '❓' },
  { label: 'Exports', to: '/exports', icon: '📤' },
  { label: 'Admin', to: '/admin', icon: '⚙️' },
  { label: 'Audit Trail', to: '/audit', icon: '📜' },
]

/**
 * AppShell — main authenticated layout with sidebar navigation,
 * top bar (user info, study/site selectors, logout), and content area.
 */
export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate({ to: '/login' })
  }

  const displayName = user
    ? `${user.first_name} ${user.last_name}`
    : 'User'

  return (
    <div className="min-h-screen flex bg-gray-50">
      {/* Sidebar */}
      <aside
        className={`${sidebarOpen ? 'w-56' : 'w-14'} flex-shrink-0 bg-white border-r border-gray-200 transition-all duration-200 flex flex-col`}
      >
        {/* Logo / brand */}
        <div className="h-14 flex items-center justify-between px-3 border-b border-gray-200">
          {sidebarOpen && (
            <span className="font-semibold text-gray-900 text-sm">Clinical EDC</span>
          )}
          <button
            type="button"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-2 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-md mx-1 transition"
              activeProps={{ className: 'bg-blue-50 text-blue-700 font-medium' }}
            >
              <span className="text-base">{item.icon}</span>
              {sidebarOpen && <span>{item.label}</span>}
            </Link>
          ))}
        </nav>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <StudySelector />
            <SiteSelector />
          </div>

          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-700">{displayName}</span>
            <button
              type="button"
              onClick={handleLogout}
              className="text-sm text-gray-500 hover:text-gray-700 transition"
            >
              Sign Out
            </button>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
