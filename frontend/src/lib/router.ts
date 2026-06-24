import { createRouter, createRootRoute, createRoute } from '@tanstack/react-router'

/**
 * Root route — all other routes are children of this.
 * Permission-aware route guards will be added per-feature.
 */
const rootRoute = createRootRoute()

/**
 * Placeholder index route.
 */
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
})

/**
 * Login route (public).
 */
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
})

const routeTree = rootRoute.addChildren([indexRoute, loginRoute])

export const router = createRouter({ routeTree })

// Type-safe router declaration for TanStack Router
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
