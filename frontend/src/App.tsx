import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { Suspense } from 'react'
import { queryClient } from './lib/query-client'
import { router } from './lib/router'
import { ThemeProvider } from './lib/theme'
import { useInactivityLogout } from './features/auth'

function InactivityGuard({ children }: { children: React.ReactNode }) {
  useInactivityLogout()
  return <>{children}</>
}

function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <InactivityGuard>
          <Suspense
            fallback={
              <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
                <p className="text-muted-foreground">Loading…</p>
              </div>
            }
          >
            <RouterProvider router={router} />
          </Suspense>
        </InactivityGuard>
      </QueryClientProvider>
    </ThemeProvider>
  )
}

export default App
