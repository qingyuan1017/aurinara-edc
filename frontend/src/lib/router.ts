import { createRouter, createRootRoute, createRoute, Outlet } from '@tanstack/react-router'
import { createElement } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { AuthGuard } from '@/components/guards/AuthGuard'
import { LoginPage } from '@/features/auth/LoginPage'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { AcceptInvitationPage } from '@/features/auth/AcceptInvitationPage'
import { AccessDeniedPage } from '@/features/auth/AccessDeniedPage'

/**
 * Root route — renders an Outlet so child routes appear.
 */
const rootRoute = createRootRoute({
  component: () => createElement(Outlet),
})

/**
 * Login route (public) — uses the real LoginPage component.
 */
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: () => createElement(LoginPage),
})

/**
 * Forgot password route (public).
 */
const forgotPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/forgot-password',
  component: () => createElement(ForgotPasswordPage),
})

/**
 * Reset password route (public).
 */
const resetPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/reset-password',
  component: () => createElement(ResetPasswordPage),
})

/**
 * Accept invitation route (public).
 */
const acceptInvitationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/accept-invitation',
  component: () => createElement(AcceptInvitationPage),
})

/**
 * Access-denied route (public, for direct navigation).
 */
const accessDeniedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/access-denied',
  component: () => createElement(AccessDeniedPage),
})

/**
 * Authenticated layout route — uses AuthGuard + AppShell.
 * All protected routes are children of this layout.
 */
const authenticatedLayout = createRoute({
  getParentRoute: () => rootRoute,
  id: 'authenticated',
  component: () => createElement(AuthGuard),
})

/**
 * App Shell layout — the visual wrapper with sidebar and top bar.
 * Nested inside AuthGuard so the shell only renders when authenticated.
 */
const appShellLayout = createRoute({
  getParentRoute: () => authenticatedLayout,
  id: 'app-shell',
  component: () => createElement(AppShell),
})

/**
 * Index (dashboard) route — landing page after login.
 */
const indexRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/',
  component: () =>
    createElement(
      'div',
      { className: 'space-y-4' },
      createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Dashboard'),
      createElement('p', { className: 'text-gray-600' }, 'Welcome to the Clinical EDC System.'),
    ),
})

/**
 * Placeholder routes for navigation items.
 * Each will be expanded with feature-specific components.
 */
const studiesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/studies',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Studies'),
    createElement('p', { className: 'text-gray-600' }, 'Study management coming soon.'),
  ),
})

const sitesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/sites',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Sites'),
    createElement('p', { className: 'text-gray-600' }, 'Site management coming soon.'),
  ),
})

const subjectsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/subjects',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Subjects'),
    createElement('p', { className: 'text-gray-600' }, 'Subject management coming soon.'),
  ),
})

const formsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/forms',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Forms'),
    createElement('p', { className: 'text-gray-600' }, 'Form management coming soon.'),
  ),
})

const queriesRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/queries',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Queries'),
    createElement('p', { className: 'text-gray-600' }, 'Query management coming soon.'),
  ),
})

const exportsRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/exports',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Exports'),
    createElement('p', { className: 'text-gray-600' }, 'Data export coming soon.'),
  ),
})

const adminRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/admin',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Admin'),
    createElement('p', { className: 'text-gray-600' }, 'Administration coming soon.'),
  ),
})

const auditRoute = createRoute({
  getParentRoute: () => appShellLayout,
  path: '/audit',
  component: () => createElement('div', { className: 'space-y-4' },
    createElement('h1', { className: 'text-2xl font-bold text-gray-900' }, 'Audit Trail'),
    createElement('p', { className: 'text-gray-600' }, 'Audit trail viewer coming soon.'),
  ),
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  acceptInvitationRoute,
  accessDeniedRoute,
  authenticatedLayout.addChildren([
    appShellLayout.addChildren([
      indexRoute,
      studiesRoute,
      sitesRoute,
      subjectsRoute,
      formsRoute,
      queriesRoute,
      exportsRoute,
      adminRoute,
      auditRoute,
    ]),
  ]),
])

export const router = createRouter({ routeTree })

// Type-safe router declaration for TanStack Router
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
