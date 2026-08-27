import { useNavigate } from '@tanstack/react-router'

/**
 * Access Denied page shown when a user lacks required permissions.
 * Provides a link back to the dashboard.
 */
export function AccessDeniedPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="text-center space-y-4 max-w-md">
        <div className="text-5xl text-gray-300">🚫</div>
        <h1 className="text-2xl font-bold text-gray-900">Access Denied</h1>
        <p className="text-gray-600">
          You do not have permission to access this page. Contact your study administrator if you
          believe this is an error.
        </p>
        <button
          type="button"
          onClick={() => navigate({ to: '/' })}
          className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition"
        >
          Return to Dashboard
        </button>
      </div>
    </div>
  )
}
