import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { Suspense } from 'react'
import { queryClient } from './lib/query-client'
import { router } from './lib/router'
import { useInactivityLogout } from './features/auth'

function InactivityGuard({ children }: { children: React.ReactNode }) {
  useInactivityLogout()
  return <>{children}</>
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <InactivityGuard>
        <Suspense
          fallback={
            <div className="min-h-screen flex items-center justify-center bg-gray-50">
              <p className="text-gray-500">Loading…</p>
            </div>
          }
        >
          <RouterProvider router={router} />
        </Suspense>
      </InactivityGuard>
    </QueryClientProvider>
  )
}

export default App
