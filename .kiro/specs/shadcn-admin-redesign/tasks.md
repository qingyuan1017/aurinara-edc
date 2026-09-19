# Implementation Plan: shadcn-admin Frontend Redesign

## Overview

This plan converts the `shadcn-admin-redesign` design into incremental prompts for a code-generation LLM. Each leaf task writes, modifies, or tests code, builds on earlier tasks, and wires the result into an existing route or component before the next slice. The plan does not implement application code during spec creation.

Implementation targets `/Users/jason/Aurinara/edc/frontend` and preserves the current React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Router/Query/Table, Zustand, React Hook Form, Zod, Vitest, Testing Library, and Playwright stack. The existing `cn()` helper, `Button` primitive, `AppShell`, route tree, auth store, permission helpers, study/site context, CTMS capability/navigation resolver, EDC clinical workflows, and CTMS operational-only boundary remain authoritative.

Use this instruction for every implementation prompt: **Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.**

Tasks marked with `*` are optional test tasks. Property tasks use the existing dependency-free deterministic generator convention and must execute at least 100 generated cases; do not add a property-testing dependency unless a separate exact-version approval is obtained. Checkpoints are coding validation gates and are excluded from the dependency graph.

## Tasks

### 1. Build the semantic foundation and reusable primitives

- [x] 1.1 Extend semantic tokens and theme variables
  - Modify `frontend/src/index.css` to add sidebar, elevated-surface, status, focus, typography, radius, shadow, layout, motion, light-theme, and dark-theme variables while preserving existing token names and Tailwind v4 import behavior.
  - Add `frontend/src/lib/theme.ts` with typed `ThemeMode` (`light`, `dark`, `system`), document-theme application, system-preference resolution, and a safe persistence adapter that does not touch auth, route, query, or Study_Context state.
  - Do not add dependencies or alter API/business logic.
  - _Depends on: none_
  - _Requirements: 1.1, 1.4–1.6, 4.1–4.6_
  - _Validation: Unit-test theme mode resolution and token mappings; verify no non-presentation state is read or written._

- [x] 1.2 Complete the core UI primitive set
  - Extend `frontend/src/components/ui/button.tsx` only where needed for `asChild`, loading/pending semantics, and approved variants without breaking existing imports.
  - Create or update `frontend/src/components/ui/{alert,badge,breadcrumb,card,checkbox,dialog,dropdown-menu,empty-state,input,label,scroll-area,select,separator,sheet,skeleton,switch,table,tabs,textarea,tooltip}.tsx` using semantic HTML, `cn()`, `class-variance-authority`, forwarded refs where focus requires them, and no API/business logic.
  - Ensure icon-only controls require accessible names and all focusable primitives use semantic ring tokens.
  - _Depends on: 1.1_
  - _Requirements: 1.2–1.5, 6.2, 6.4, 6.7, 9.3–9.7, 11.1_
  - _Validation: Add focused component tests for variants, disabled/pending state, keyboard operation, accessible names, focus indicators, dialog/sheet focus behavior, and light/dark class output._

- [x] 1.3 Add shared page and state presentation patterns
  - Create `frontend/src/components/patterns/PageContainer.tsx`, `PageHeader.tsx`, `PageToolbar.tsx`, `MetricCard.tsx`, `DataTableShell.tsx`, `DetailCard.tsx`, `StatusBadge.tsx`, `OwnershipBadge.tsx`, `LoadingState.tsx`, `ErrorState.tsx`, and `EmptyState.tsx`.
  - Accept server-provided values and callbacks through typed props; do not move query functions, permissions, CTMS capability checks, mutation handlers, or clinical rules into patterns.
  - Implement labeled loading, refreshing, empty, error, unauthorized, offline, disabled, unavailable, worker-unavailable, status, ownership, and freshness slots using accessible semantics.
  - _Depends on: 1.2_
  - _Requirements: 5.1–5.5, 6.3–6.5, 8.2–8.4, 9.6, 11.1_
  - _Validation: Component-test every state slot, status/ownership text plus non-color cue, retry callback, no-selected-study prompt, and responsive table access._

- [x] 1.4 Wire theme resolution into the existing application root
  - Modify `frontend/src/App.tsx` and, only if necessary, `frontend/src/main.tsx` to apply the theme adapter around the existing `QueryClientProvider`, inactivity guard, suspense fallback, and `RouterProvider` without adding a second provider tree or changing router behavior.
  - Replace the suspense fallback’s hard-coded light-only surface classes with semantic token classes.
  - _Depends on: 1.1_
  - _Requirements: 4.2–4.6, 8.1, 10.1_
  - _Validation: Component-test initial theme and theme switching while asserting route, auth, query client, form, and Study_Context state remain unchanged._

- [ ]* 1.5 Add primitive and pattern component regression tests
  - Create or extend `frontend/src/__tests__/UIPrimitives.test.tsx` and `frontend/src/__tests__/PagePatterns.test.tsx` for primitive variants, accessible names, focus, dialog/sheet dismissal, table overflow/stacking, state slots, and theme-compatible classes.
  - **Validates: Requirements 1.2–1.5, 5.1–5.5, 9.2–9.7, 11.1**
  - _Depends on: 1.2, 1.3, 1.4_
  - _Validation: Run the targeted Vitest files with the repository’s one-shot `vitest run` convention._

### 2. Extract and wire the shadcn-admin authenticated shell

- [x] 2.1 Create the typed navigation and route-context adapters
  - Create `frontend/src/lib/navigation-model.ts` to group existing EDC `NAV_ITEMS` and consume `resolveCTMSNavigation` without duplicating CTMS capability or permission policy.
  - Create `frontend/src/lib/route-context.ts` for route-derived breadcrumb labels, encoded route identifiers, and search-preserving parent links using TanStack Router location data.
  - Preserve every existing EDC target, CTMS section/item ID, CTMS active matching rule, and current-search propagation behavior.
  - _Depends on: 1.2_
  - _Requirements: 2.6–2.8, 3.1–3.4, 7.1–7.3_
  - _Validation: Unit-test route labels, encoded IDs, grouped targets, active options, CTMS disabled/unavailable behavior, and search-preserving links._

- [x] 2.2 Extract the desktop/sidebar presentation
  - Create `frontend/src/components/layout/AppSidebar.tsx` and update `frontend/src/components/layout/AppShell.tsx` to render grouped EDC/CTMS navigation from `navigation-model.ts`.
  - Implement compact desktop collapse, semantic `nav`/section headings, active route styling, icon labels, and tooltips for collapsed items.
  - Keep existing `useAuthStore`, `usePermission`, `useCTMSCapabilityState`, `resolveCTMSNavigation`, `useStudyContext`, `useNavigate`, logout handler, and `Outlet` behavior intact.
  - _Depends on: 2.1_
  - _Requirements: 2.1–2.2, 2.6–2.8, 3.1–3.2, 8.1–8.4_
  - _Validation: Component-test EDC and CTMS navigation for allowed, denied, disabled, and unavailable capability fixtures; assert one shell and an existing outlet._

- [x] 2.3 Extract the header and account/context controls
  - Create `frontend/src/components/layout/AppHeader.tsx`, `Breadcrumbs.tsx`, `UserMenu.tsx`, `ThemeToggle.tsx`, and `GlobalSearch.tsx`.
  - Move the existing `StudySelector` and `SiteSelector` into the header without changing their query functions, selected values, disabled behavior, or Zustand actions.
  - Reuse `/notifications` for the notifications affordance and preserve the current display name/sign-out flow; if no supported search API exists, keep `GlobalSearch` explicitly non-submitting rather than inventing a request.
  - _Depends on: 1.2, 1.4, 2.1_
  - _Requirements: 2.4–2.5, 3.3–3.6, 4.2–4.3, 8.1, 11.2_
  - _Validation: Component-test selectors, breadcrumbs, theme, notifications, user menu, sign-out navigation, accessible names, and preservation of route/search state._

- [x] 2.4 Add responsive mobile navigation and shell layout
  - Update `frontend/src/components/layout/AppSidebar.tsx`, `AppHeader.tsx`, and `AppShell.tsx` to use the `Sheet` primitive below the agreed mobile breakpoint, retain desktop collapse above the breakpoint, and apply responsive `PageContainer` content sizing.
  - Ensure opening/closing the mobile drawer does not navigate, mutate query state, or lose the invoking focus; ensure the content area has no shell-induced horizontal overflow.
  - _Depends on: 2.2, 2.3_
  - _Requirements: 2.3–2.5, 3.5–3.6, 9.1–9.3, 9.5, 9.7–9.8_
  - _Validation: Component-test open/close/focus return; browser-test 320px, tablet, and desktop viewports with keyboard navigation and overflow assertions._

- [ ]* 2.5 Add shell, navigation, and context regression tests
  - Extend `frontend/src/__tests__/FinalEDCRegression.test.tsx`, `PermissionGuard.test.tsx`, and add `frontend/src/__tests__/AppShell.test.tsx` for grouped EDC navigation, CTMS capability states, direct access-denied behavior, selectors, breadcrumbs, theme, user menu, mobile drawer, and preserved outlet rendering.
  - **Validates: Requirements 2.1–2.8, 3.1–3.6, 8.1–8.4, 11.2–11.5**
  - _Depends on: 2.2, 2.3, 2.4_
  - _Validation: Run targeted Vitest tests; preserve all existing EDC/CTMS assertions rather than replacing them._

- [ ]* 2.6 Add Property 1 navigation safety coverage
  - Create `frontend/src/__tests__/NavigationModel.property.test.ts` using the existing deterministic generator pattern with at least 128 generated permission/capability/scope cases.
  - **Property 1: Navigation never exceeds current authority metadata**
  - Assert every existing allowed EDC target remains available, CTMS targets match `resolveCTMSNavigation`, and no clinical mutation or capability-ineligible action is exposed.
  - Tag: `Feature: shadcn-admin-redesign, Property 1: Navigation never exceeds current authority metadata`
  - **Validates: Requirements 2.6–2.8, 3.1–3.2, 8.2–8.5**
  - _Depends on: 2.1_
  - _Validation: Run the targeted property-style Vitest file with at least 100 generated cases._

### 3. Preserve route/search state and migrate representative dashboard patterns

- [x] 3.1 Implement search-preserving shell action helpers
  - Complete `frontend/src/lib/route-context.ts` with typed helpers for breadcrumb parent navigation, shell link search preservation, and presentation-only action classification.
  - Do not modify route paths or route definitions in `frontend/src/lib/router.ts`; only add adapters if the existing router API requires a non-semantic integration change.
  - _Depends on: 2.1, 2.4_
  - _Requirements: 3.3–3.5, 7.1–7.6_
  - _Validation: Unit-test representative EDC/CTMS paths, encoded IDs, supported/unknown search keys, and direct denied routes._

- [x] 3.2 Migrate dashboard and list/table page composition
  - Update `frontend/src/features/dashboards/StudyDashboardPage.tsx`, `DataCleaningDashboardPage.tsx`, `frontend/src/features/studies/StudyListPage.tsx`, `frontend/src/features/sites/SiteListPage.tsx`, and `frontend/src/features/subjects/SubjectListPage.tsx` to use `PageContainer`, `PageHeader`, `PageToolbar`, `MetricCard`, `DataTableShell`, `StatusBadge`, and shared state patterns.
  - Preserve existing query keys, query functions, pagination, server totals/order, filters, permission checks, Study_Context behavior, status labels, and action callbacks.
  - _Depends on: 1.3, 3.1_
  - _Requirements: 5.1–5.6, 7.3–7.5, 9.1–9.2, 10.2–10.5_
  - _Validation: Component-test loading/empty/error/populated states and server metadata; route-test current dashboard/list deep links and search state._

- [x] 3.3 Migrate detail, casebook, audit, and notification composition
  - Update `frontend/src/features/studies/StudyDetailPage.tsx`, `frontend/src/features/subjects/SubjectCasebookPage.tsx`, `frontend/src/features/admin/*`, and `frontend/src/features/notifications/NotificationsPage.tsx` to use shared detail cards, page headers, tabs, badges, tables, and state patterns.
  - Preserve EDC ownership/status/freshness labels, audit behavior, notification read/archive actions, permission affordances, query behavior, and clinical boundaries.
  - _Depends on: 1.3, 3.2_
  - _Requirements: 5.1–5.6, 6.5–6.6, 8.2–8.6, 10.2, 11.2–11.5_
  - _Validation: Extend existing status, audit, notification, and subject/casebook tests; assert unchanged API calls and mutation payloads._

- [ ]* 3.4 Add Property 2 theme-state preservation coverage
  - Create `frontend/src/__tests__/ThemeState.property.test.ts` using at least 128 deterministic generated route/search/auth/Study_Context/form/query-key fixtures.
  - **Property 2: Presentation theme changes preserve application state**
  - Toggle supported theme modes and assert path, search, selected study/site IDs, auth state, form values, and query keys remain equivalent.
  - Tag: `Feature: shadcn-admin-redesign, Property 2: Presentation theme changes preserve application state`
  - **Validates: Requirements 4.2–4.4, 7.2–7.5**
  - _Depends on: 1.4, 3.1_
  - _Validation: Run targeted property-style Vitest coverage with at least 100 generated cases._

- [ ]* 3.5 Add Property 3 search/query preservation coverage
  - Create `frontend/src/__tests__/RouteState.property.test.ts` using at least 128 deterministic supported search-state and shell-action fixtures.
  - **Property 3: Shell presentation actions preserve supported search state**
  - Assert sidebar, mobile drawer, breadcrumb, selector presentation, theme, notification, and user-menu actions preserve unrelated search values and do not invalidate unrelated queries.
  - Tag: `Feature: shadcn-admin-redesign, Property 3: Shell presentation actions preserve supported search state`
  - **Validates: Requirements 3.3–3.5, 7.2–7.3**
  - _Depends on: 3.1_
  - _Validation: Run targeted property-style Vitest coverage with at least 100 generated cases._

### 4. Migrate forms, regulated dialogs, and status-heavy EDC workflows

- [x] 4.1 Create the shared migrated form and dialog shell
  - Create `frontend/src/components/patterns/FormField.tsx`, `FormActions.tsx`, `ConfirmDialog.tsx`, and `MutationFeedback.tsx` using existing React Hook Form/Zod error contracts and shared primitives.
  - Preserve pending, duplicate-submit, validation, sanitized server-error, cancellation, reason, re-authentication, permission, and cache behavior; do not persist clinical drafts to local storage.
  - _Depends on: 1.2, 1.3_
  - _Requirements: 6.1–6.4, 6.7, 8.2, 8.6, 9.4–9.6_
  - _Validation: Component-test pending/error/confirm/focus behavior with representative 403/409/422/network fixtures._

- [x] 4.2 Migrate EDC form entry and clinical lifecycle surfaces
  - Update `frontend/src/features/forms/FormEntryPage.tsx`, `FormBuilderPage.tsx`, `frontend/src/features/signatures/*`, `frontend/src/features/queries/*`, `frontend/src/features/quality/*`, and `frontend/src/features/visits/*` to use shared form, dialog, table, status, ownership, and state patterns.
  - Preserve React Hook Form/Zod schemas, EDC endpoints/payloads, Reason_For_Change, lock/freeze, signature/re-authentication, query lifecycle, SDV/review, offline/degraded behavior, and clinical ownership.
  - _Depends on: 4.1, 3.2_
  - _Requirements: 5.3–5.6, 6.1–6.6, 8.1–8.6, 10.2, 11.2–11.5_
  - _Validation: Extend `FormValidation.test.ts`, `ReasonForChangeDialog.test.tsx`, `SignatureWorkflow.test.tsx`, `Phase2Workflows.test.tsx`, and related route tests._

- [x] 4.3 Migrate auth, export, edit-check, and public page composition
  - Update `frontend/src/features/auth/{LoginPage,ForgotPasswordPage,ResetPasswordPage,AcceptInvitationPage,AccessDeniedPage}.tsx`, `frontend/src/features/exports/*`, and `frontend/src/features/edit-checks/*` to use shared page, form, card, alert, dialog, status, and state patterns.
  - Preserve public route paths, auth lifecycle, reset/invitation payloads, access-denied semantics, export filters/status/download behavior, edit-check validation, and clinical export ownership.
  - _Depends on: 4.1, 4.2_
  - _Requirements: 5.1–5.6, 6.1–6.7, 7.1–7.6, 8.1–8.6, 10.2–10.6_
  - _Validation: Extend auth, export, edit-check, and access-denied tests; assert unchanged request URLs, payloads, and query behavior._

- [ ]* 4.4 Add Property 4 mutation-contract preservation coverage
  - Create `frontend/src/__tests__/MutationContract.property.test.ts` using at least 128 deterministic migrated form/action values, permission states, capability states, and cache-policy fixtures.
  - **Property 4: Migrated mutation contracts remain unchanged**
  - Assert endpoint, payload fields, permission/capability checks, confirmation requirements, and post-success cache behavior match the existing contract.
  - Tag: `Feature: shadcn-admin-redesign, Property 4: Migrated mutation contracts remain unchanged`
  - **Validates: Requirements 6.1–6.6, 7.5, 8.2, 8.6**
  - _Depends on: 4.1, 4.2, 4.3_
  - _Validation: Run targeted property-style Vitest coverage with at least 100 generated cases._

### 5. Migrate CTMS operational views without changing the clinical boundary

- [x] 5.1 Refactor CTMS workspace composition around shared patterns
  - Update `frontend/src/features/ctms/WorkspacePage.tsx` and existing CTMS component modules to use `PageContainer`, `PageHeader`, `PageToolbar`, `DataTableShell`, `DetailCard`, and shared loading/error/empty/degraded patterns.
  - Keep `frontend/src/features/ctms/capabilities.ts`, `navigation.ts`, `api.ts`, state/offline helpers, permission checks, route paths, ownership presentation, and server-authoritative behavior intact except for presentation extraction.
  - _Depends on: 1.3, 2.2, 3.2_
  - _Requirements: 2.7, 3.2, 5.1–5.6, 8.2–8.6, 10.1–10.7, 11.2–11.7_
  - _Validation: Extend CTMS workspace/persona/state/route tests for ready, disabled, unavailable, empty, unauthorized, offline, and worker-unavailable modes._

- [x] 5.2 Migrate CTMS operational tables, forms, reports, and exports
  - Update `frontend/src/features/ctms/*` operational views for study/site profiles, enrollment, milestones, monitoring, tasks, contacts, reports, operational exports, and health to use shared primitives and responsive patterns.
  - Preserve CTMS-owned fields, server filters/totals/order, capability/permission affordances, transition forms, request/correlation metadata, export lifecycle, and cache invalidation.
  - Do not introduce EDC mutation endpoints or clinical values into CTMS payloads.
  - _Depends on: 5.1, 4.1_
  - _Requirements: 5.2–5.6, 6.1–6.6, 8.2, 8.6, 10.1–10.7, 11.1–11.7_
  - _Validation: Extend `CTMSDashboardReports.test.tsx`, `CTMSForms.test.tsx`, `CTMSExportLifecycle.property.test.tsx`, `CTMSRoutes.test.ts`, and API contract tests._

- [x] 5.3 Migrate CTMS ownership, projection, coordination, and remediation surfaces
  - Update existing CTMS ownership/freshness, projection, attachment, failed-event, conflict, and coordination components to use `OwnershipBadge`, `StatusBadge`, `DetailCard`, `ConfirmDialog`, and shared state patterns.
  - Preserve EDC canonical identifiers, read-only projection semantics, freshness metadata, sanitized errors, policy/reason requirements, correlation IDs, operational attachment/export restrictions, and no-clinical-mutation affordances.
  - _Depends on: 5.1, 5.2, 4.1_
  - _Requirements: 6.5–6.6, 8.2–8.6, 10.2–10.7, 11.4–11.7_
  - _Validation: Extend `CTMSOwnershipPresentation.test.tsx`, `CTMSOwnershipFreshness.property.test.tsx`, `CTMSClinicalAuthority.property.test.tsx`, `CTMSOperationalBoundary.property.test.ts`, `CTMSRemediationProperty.test.tsx`, and `CTMSResilience.test.tsx`._

- [ ]* 5.4 Add Property 6 clinical-boundary preservation coverage
  - Create `frontend/src/__tests__/ClinicalBoundary.property.test.ts` using at least 128 deterministic CTMS capability, permission, operational-record, projection, EDC-reference, and requested-action fixtures.
  - **Property 6: Clinical and CTMS operational boundaries remain non-escalating**
  - Assert only CTMS operational actions are exposed and no prohibited clinical mutation action is emitted for EDC-owned objects.
  - Tag: `Feature: shadcn-admin-redesign, Property 6: Clinical and CTMS operational boundaries remain non-escalating`
  - **Validates: Requirements 6.5–6.6, 8.2–8.6**
  - _Depends on: 5.1, 5.2, 5.3_
  - _Validation: Run targeted property-style Vitest coverage with at least 100 generated cases and preserve existing CTMS authority tests._

### 6. Complete remaining page migration and remove visual drift

- [x] 6.1 Migrate remaining EDC feature pages to shared composition
  - Update remaining pages under `frontend/src/features/{ai,admin,dashboards,edit-checks,exports,forms,notifications,quality,queries,signatures,sites,studies,subjects,visits}` that still use page-specific outer layout, direct color classes, duplicate cards/tables, or unshared loading/error/empty markup.
  - Preserve each page’s existing API hooks, query keys, permission checks, route props, search behavior, status/ownership/freshness semantics, and mutations.
  - _Depends on: 3.2, 3.3, 4.2, 4.3, 5.2, 5.3_
  - _Requirements: 5.1–5.6, 6.1–6.7, 8.1–8.6, 9.1–9.8, 10.2–10.5_
  - _Validation: Use route inventory and targeted feature tests to verify every existing route renders through shared patterns or an explicitly approved compatibility surface._

- [x] 6.2 Replace remaining hard-coded visual styles with semantic tokens
  - Update migrated feature files and `frontend/src/components/layout/*` to replace light-only direct colors, duplicated borders/radii/shadows, emoji-only navigation icons, and inconsistent spacing with semantic token classes, Lucide icons, and shared patterns.
  - Keep status/ownership meanings and text unchanged; remove a legacy style only after the replacement has a focused test.
  - _Depends on: 6.1_
  - _Requirements: 1.1–1.6, 4.1–4.6, 5.1–5.4, 10.5_
  - _Validation: Search the frontend source for remaining legacy shell/page style patterns; run targeted component tests for every changed shared surface._

- [x] 6.3 Add responsive/accessibility browser coverage
  - Extend or create Playwright tests under the repository’s existing e2e test location for authenticated shell, dashboard/list/detail/form/dialog/table, CTMS degraded states, light/dark themes, keyboard navigation, mobile drawer, focus return, and no-hover-only essentials.
  - Use representative stable data and mask dynamic values in visual assertions; do not weaken existing clinical/API assertions.
  - _Depends on: 2.4, 3.2, 4.2, 5.3, 6.1_
  - **Validates: Requirements 2.3–2.5, 4.4–4.6, 9.1–9.8, 11.2–11.5**
  - _Validation: Run the targeted Playwright files in one-shot mode at mobile and desktop viewports during implementation._

- [ ]* 6.4 Add Property 5 server-table metadata coverage
  - Create `frontend/src/__tests__/DataTableShell.property.test.tsx` using at least 128 deterministic ordered rows, pagination totals, active filters, status/ownership/freshness labels, and responsive modes.
  - **Property 5: Server table metadata remains authoritative**
  - Assert server order and metadata remain visible, unauthorized totals are not reconstructed, and required fields/actions remain accessible in responsive modes.
  - Tag: `Feature: shadcn-admin-redesign, Property 5: Server table metadata remains authoritative`
  - **Validates: Requirements 5.2–5.4, 9.1–9.2**
  - _Depends on: 1.3, 3.2, 6.1_
  - _Validation: Run targeted property-style Vitest coverage with at least 100 generated cases._

### 7. Final regression wiring and implementation validation

- [x] 7.1 Add route, query, and deep-link regression coverage
  - Extend `frontend/src/__tests__/CTMSRoutes.test.ts`, `FinalEDCRegression.test.tsx`, and relevant router/feature tests to cover every existing route family, representative search parameters, direct access-denied routes, CTMS disabled/unavailable/empty/worker-unavailable modes, and EDC clinical workflows.
  - Assert presentation-only shell actions do not change route state or unrelated TanStack Query keys.
  - _Depends on: 3.1, 5.1, 6.1_
  - _Requirements: 2.7–2.8, 7.1–7.6, 8.1–8.6, 11.2–11.5_
  - _Validation: Run the complete frontend Vitest suite in one-shot mode after targeted tests pass._

- [x] 7.2 Preserve and extend existing API/business-boundary tests
  - Update only test fixtures or presentation assertions in `frontend/src/__tests__/CTMSApiContract.test.ts`, CTMS operational-boundary/authority tests, clinical workflow tests, and relevant feature tests when component markup changes require selector updates.
  - Do not alter API payload expectations, clinical ownership assertions, permission semantics, or CTMS non-mutation assertions to make a visual test pass.
  - _Depends on: 4.2, 5.2, 5.3, 7.1_
  - _Requirements: 6.5–6.6, 7.4–7.6, 8.2–8.6, 11.3–11.5_
  - _Validation: Run the affected API contract, EDC clinical, CTMS boundary, and degraded-state test files._

- [x] 7.3 Complete source-level dependency and migration checks
  - Add or update a lightweight repository check under `frontend/src/__tests__` or the existing test utilities to assert no second router/auth shell is introduced, no forbidden CTMS clinical mutation endpoint is referenced, and no unapproved dependency is required by the redesign.
  - Confirm all shared primitives are imported from `frontend/src/components/ui/` or approved compatibility files and all migrated routes remain connected to `AppShell`/`Outlet`.
  - _Depends on: 6.2, 7.2_
  - _Requirements: 1.4–1.6, 2.1, 7.1, 8.1, 8.5, 10.1–10.6_
  - _Validation: Inspect the dependency diff and route/API inventory; run the targeted source-level checks._

- [x] 7.4 Run the implementation validation matrix
  - Run from `/Users/jason/Aurinara/edc/frontend`: `npm run lint`, `npm run build`, `npm run test`, and the relevant one-shot Playwright suite; use no watch mode.
  - Before release, verify the agreed breakpoint, density, font, theme persistence, global-search behavior, notification affordance, and compatibility exceptions are represented by implemented code or typed test fixtures rather than undocumented assumptions.
  - _Depends on: 7.1, 7.2, 7.3_
  - _Requirements: 4.2–4.6, 9.1–9.8, 10.1–10.6, 11.1–11.6_
  - _Validation: All required commands pass or each failure has a corrective coding/test follow-up task._

### 8. Checkpoint — foundation and shell

- Ensure token, primitive, theme, navigation, and shell implementation tasks are wired into the existing `AppShell`, and ensure targeted component tests pass before beginning broad page migration.

### 9. Checkpoint — representative EDC and CTMS slices

- Ensure dashboard/list/detail/form/CTMS slices preserve routes, query state, permission/capability affordances, status/ownership/freshness semantics, and clinical/operational boundaries before migrating remaining pages.

### 10. Checkpoint — final frontend regression

- Ensure all required implementation and regression tests pass, verify no second shell or forbidden clinical mutation path exists, and resolve or document every product decision listed in the requirements/design assumptions.

## Notes

- Tasks marked with `*` are optional component, browser, or property-style test tasks. Core implementation tasks are not optional.
- Property-style tests use the existing dependency-free deterministic generator convention demonstrated by current CTMS property tests; each property task is separate and runs at least 100 cases.
- Component and browser tests remain necessary for UI layout, focus, responsive behavior, theme rendering, keyboard operation, dialogs, sheets, tables, loading/error/empty states, and visual regression. Property-style tests do not replace those tests.
- The server remains authoritative for auth, permissions, study/site scope, CTMS capabilities, transitions, clinical ownership, projections, and API errors. Frontend affordances only improve usability.
- No task adds mutation paths for Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV/review/freeze/lock/signatures, Clinical_Attachments, or clinical exports.
- No task adds a second application, router, auth shell, backend endpoint, or business-logic layer.
- A task may refactor presentation markup and import paths, but every migrated page must remain connected to an existing route, query, mutation, and test harness before the task is complete.
- Validation commands are listed for future implementation only. No tests or builds are run during spec creation.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["1.5", "2.2", "2.6", "4.1"] },
    { "id": 4, "tasks": ["2.3"] },
    { "id": 5, "tasks": ["2.4"] },
    { "id": 6, "tasks": ["2.5", "3.1"] },
    { "id": 7, "tasks": ["3.2", "3.4", "3.5"] },
    { "id": 8, "tasks": ["3.3", "4.2", "5.1"] },
    { "id": 9, "tasks": ["4.3", "5.2"] },
    { "id": 10, "tasks": ["4.4", "5.3"] },
    { "id": 11, "tasks": ["5.4", "6.1"] },
    { "id": 12, "tasks": ["6.2", "6.3", "6.4", "7.1"] },
    { "id": 13, "tasks": ["7.2"] },
    { "id": 14, "tasks": ["7.3"] },
    { "id": 15, "tasks": ["7.4"] }
  ]
}
```
