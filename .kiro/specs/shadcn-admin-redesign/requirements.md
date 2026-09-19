# Requirements Document

## Introduction

This specification defines a whole-frontend visual and interaction redesign for the existing React application at `/Users/jason/Aurinara/edc/frontend`. The redesign shall make the authenticated application look and behave like a modern shadcn-admin dashboard while retaining the existing application boundary, TanStack Router route tree, authentication flow, permission checks, study/site context, EDC clinical workflows, CTMS operational boundary, API contracts, query behavior, deep links, and degraded-state behavior.

The work is a presentation and interaction-system migration. It establishes reusable design tokens and accessible primitives before migrating the authenticated shell and feature pages incrementally. The redesign does not create a second application, replace the current route tree, change backend business logic, or add clinical mutation authority to CTMS.

## Glossary

- **Frontend_Redesign**: The visual, responsive, accessibility, theme, component, layout, and interaction changes delivered in `frontend/src`.
- **Authenticated_Shell**: The existing `AppShell` composition that renders the authenticated sidebar, header, selectors, sign-out action, and route outlet.
- **Design_Token**: A named CSS custom property or Tailwind-compatible semantic value for color, typography, spacing, radius, shadow, focus, motion, or layout.
- **UI_Primitive**: A reusable accessible component such as Button, Badge, Card, Input, Select, Tabs, Dialog, DropdownMenu, Sheet, Table, Tooltip, Breadcrumb, Alert, Skeleton, or Sonner-like feedback surface.
- **Navigation_Model**: The typed model that groups EDC navigation and dynamically resolved CTMS navigation while retaining route targets, active matching, permissions, capability state, and search state.
- **Route_State**: TanStack Router path parameters, search parameters, hash state, active route state, and route context required to reproduce a page view.
- **Study_Context**: The existing Zustand state containing selected study and site identifiers.
- **Permission_Affordance**: A client-side visibility or disabled-state decision that improves usability but never replaces server authorization.
- **Capability_State**: The CTMS capability status and manifest represented by `ready`, `disabled`, or `unavailable` state.
- **Clinical_Boundary**: The rule that EDC remains authoritative for Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV/review/freeze/lock/signatures, Clinical_Attachments, and clinical exports.
- **Operational_CTMS_Content**: CTMS-owned study/site operations, enrollment planning, milestones, monitoring, tasks, contacts, operational projections, reports, exports, coordination, and health views.
- **Degraded_State**: A loading, refreshing, empty, error, unauthorized, disabled, unavailable, offline, worker-unavailable, or stale-data presentation with explicit semantics.
- **Supported_Viewport**: A viewport from 320 CSS pixels through the largest desktop viewport supported by the application.
- **Reduced_Motion**: The user preference exposed by `prefers-reduced-motion: reduce`.
- **Visual_Regression_Baseline**: An approved screenshot or DOM/accessibility expectation used to detect unintended presentation changes.

## Requirements

### Requirement 1: Establish the visual foundation

**User Story:** As a frontend maintainer, I want shared design tokens and primitives, so that every page can use one coherent shadcn-admin visual language.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL define semantic Design_Tokens for background, foreground, card, popover, primary, secondary, muted, accent, destructive, border, input, ring, radius, shadow, typography, and layout surfaces in the shared stylesheet or an equivalent typed token module.
2. THE Frontend_Redesign SHALL provide reusable UI_Primitives for Button, Badge, Card, Input, Label, Textarea, Select, Checkbox, Switch, Tabs, Table, Dialog, DropdownMenu, Sheet, Tooltip, Breadcrumb, Alert, Skeleton, Separator, ScrollArea, and EmptyState before feature-page migration begins.
3. WHEN a UI_Primitive receives a visual variant or size, THE Frontend_Redesign SHALL render the variant through typed class-variance or equivalent component options without requiring page-specific duplicate styles.
4. THE Frontend_Redesign SHALL use the existing `cn()` helper and existing Tailwind CSS v4 integration for class composition and shall not introduce a second styling system.
5. WHEN a UI_Primitive is rendered with keyboard focus, THE Frontend_Redesign SHALL display a visible focus indicator that uses the shared ring Design_Token and remains distinguishable in light and dark themes.
6. THE Frontend_Redesign SHALL preserve the existing frontend dependency set unless a missing primitive requires a truly necessary dependency with an exact pinned version and a documented compatibility rationale.

### Requirement 2: Redesign the authenticated shell without changing application boundaries

**User Story:** As an authenticated user, I want a compact dashboard shell, so that navigation and context are easy to scan while the existing application remains intact.

#### Acceptance Criteria

1. THE Authenticated_Shell SHALL remain the only authenticated shell and SHALL continue to render `Outlet` content inside the existing TanStack Router authenticated route tree.
2. THE Authenticated_Shell SHALL provide a compact collapsible desktop sidebar with grouped navigation, active-route styling, accessible labels, and tooltips when the sidebar is collapsed.
3. WHEN a Supported_Viewport is narrower than the desktop sidebar breakpoint, THE Authenticated_Shell SHALL replace the persistent sidebar with an accessible mobile Sheet or drawer that can be opened, navigated, and closed without changing the current route.
4. THE Authenticated_Shell SHALL provide a top header containing a menu trigger where needed, breadcrumbs derived from the current route, Study_Context selectors, global search affordance, notifications affordance, theme control, and a user menu containing the existing sign-out action.
5. THE Authenticated_Shell SHALL render the route outlet in a responsive content container with consistent page-header, content-spacing, and overflow behavior without changing route parameters or search parameters.
6. THE Frontend_Redesign SHALL preserve every existing EDC navigation target and every existing CTMS navigation target resolved by `resolveCTMSNavigation` when the corresponding Permission_Affordance and Capability_State allow the target.
7. WHEN Capability_State is disabled or unavailable, THE Authenticated_Shell SHALL preserve EDC navigation and SHALL hide or explain CTMS navigation according to the existing capability behavior.
8. THE Authenticated_Shell SHALL preserve the existing authentication, logout, permission, study/site context, direct-route access-denied, and server-authoritative authorization behavior.

### Requirement 3: Provide consistent navigation and route context

**User Story:** As a user moving across studies, sites, and workspaces, I want clear navigation context, so that page location and scope remain understandable.

#### Acceptance Criteria

1. THE Navigation_Model SHALL group existing EDC destinations into stable labeled sections without removing, renaming, or re-targeting an existing EDC route.
2. THE Navigation_Model SHALL group dynamic CTMS destinations by the sections returned by `resolveCTMSNavigation` and SHALL preserve CTMS route paths, permission filtering, capability filtering, and `search={(previous) => previous}` behavior.
3. WHEN the current route has a known route hierarchy, THE Authenticated_Shell SHALL render breadcrumbs whose links preserve the current Route_State unless the breadcrumb intentionally represents a parent route.
4. WHEN a user changes Study_Context through a selector, THE Frontend_Redesign SHALL invoke the existing Study_Context actions and SHALL preserve the current route and unrelated Route_State unless existing application behavior intentionally clears dependent site context.
5. WHEN a user opens the mobile navigation or user menu, THE Frontend_Redesign SHALL return focus to the invoking control after the surface closes.
6. THE Frontend_Redesign SHALL expose navigation state through text, active styling, and accessible semantics rather than color alone or icon shape alone.

### Requirement 4: Add light and dark theme behavior

**User Story:** As a user working across environments, I want a reliable light/dark theme, so that the dashboard remains comfortable and legible.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL provide light and dark theme token values for all shared Design_Tokens used by the Authenticated_Shell, UI_Primitives, forms, tables, dialogs, status labels, and feature pages.
2. THE Frontend_Redesign SHALL provide a theme control with `light`, `dark`, and `system` choices, or an equivalent behavior explicitly approved for the existing application.
3. WHEN a user changes the theme, THE Frontend_Redesign SHALL apply the selected theme without changing the current route, Route_State, Study_Context, form values, or query keys.
4. WHEN the application starts, THE Frontend_Redesign SHALL resolve the persisted theme preference or system preference without producing a flash of unreadable foreground/background contrast in the supported entry surface.
5. THE Frontend_Redesign SHALL preserve a minimum 3:1 contrast ratio for large text and graphical focus indicators and a minimum 4.5:1 contrast ratio for normal text against its adjacent background in both supported themes.
6. WHILE Reduced_Motion is enabled, THE Frontend_Redesign SHALL reduce non-essential transitions and animations without removing focus, open/close, loading, or status semantics.

### Requirement 5: Standardize page composition and dashboard content

**User Story:** As a study team member, I want each page to follow a predictable dashboard composition, so that lists, details, and workflows are easier to understand.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL provide reusable page-header, section, card-grid, metric-card, toolbar, filter-bar, table, detail-panel, and content-width patterns for feature pages.
2. WHEN a feature page displays a collection, THE Frontend_Redesign SHALL provide a labeled loading state, empty state, error state, and populated state using consistent UI_Primitives.
3. WHEN a feature page displays tabular data, THE Frontend_Redesign SHALL preserve server-provided ordering, pagination, totals, filters, status/ownership/freshness labels, and row actions without reconstructing unauthorized data on the client.
4. WHEN a feature page displays a record status, THE Frontend_Redesign SHALL use a text label and a non-color cue, and SHALL preserve the existing status meaning for EDC and Operational_CTMS_Content.
5. WHEN a feature page has no selected Study_Context required by existing behavior, THE Frontend_Redesign SHALL retain the existing actionable prompt and SHALL present the prompt through the shared empty/content-state pattern.
6. THE Frontend_Redesign SHALL preserve existing feature-page API calls, query keys, mutation behavior, and business logic while changing presentation composition.

### Requirement 6: Preserve forms, dialogs, menus, tables, and interaction semantics

**User Story:** As a user completing clinical and operational work, I want polished reusable interactions, so that the redesign does not change the meaning or safety of existing workflows.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL migrate existing forms to shared Label, Input, Select, Textarea, Checkbox, Switch, Button, Alert, Dialog, and validation-message primitives without changing existing validation schemas, submission payloads, or mutation endpoints.
2. WHEN a form submission is pending, THE Frontend_Redesign SHALL disable only the controls required by the existing workflow, expose a pending state, and prevent duplicate submission.
3. WHEN a form submission fails, THE Frontend_Redesign SHALL preserve safe entered values, display the existing sanitized server error and field associations, and SHALL not display a false success state.
4. WHEN a destructive or regulated action requires confirmation, THE Frontend_Redesign SHALL use an accessible Dialog with explicit action text, cancellation, focus management, and the existing permission/reason/re-authentication requirements.
5. THE Frontend_Redesign SHALL preserve EDC clinical status, ownership, freshness, lock, signature, query, review, SDV, offline, and degraded-state affordances during component migration.
6. THE Frontend_Redesign SHALL preserve CTMS operational-only behavior and SHALL not add mutation controls for Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV/review/freeze/lock/signatures, Clinical_Attachments, or clinical exports.
7. WHEN a menu, dropdown, tooltip, dialog, or sheet opens, THE Frontend_Redesign SHALL provide an accessible name, keyboard operation, dismissal behavior, and focus behavior appropriate to the surface.

### Requirement 7: Preserve routing, deep links, search state, and query behavior

**User Story:** As a user returning to a saved page or sharing a filtered view, I want the redesign to preserve route behavior, so that visual migration does not break navigation.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL preserve every existing route path, path parameter, direct link, redirect, access-denied route, and route-level loader behavior.
2. WHEN a route contains search parameters, THE Frontend_Redesign SHALL preserve supported search keys and values through navigation, shell interactions, breadcrumb navigation, responsive navigation, and theme changes unless an existing route explicitly changes the search state.
3. WHEN a navigation action changes only presentation state, THE Frontend_Redesign SHALL not change TanStack Query keys, invalidate unrelated queries, or refetch unrelated EDC or CTMS data.
4. WHEN a user navigates through an existing deep link, THE Frontend_Redesign SHALL render the same feature component and preserve route-derived identifiers and authorization behavior.
5. THE Frontend_Redesign SHALL preserve API request parameters, query keys, pagination state, filter state, cache invalidation policy, and server error handling for existing feature pages.
6. THE Frontend_Redesign SHALL preserve direct-route access-denied behavior even when a navigation item is hidden by a Permission_Affordance.

### Requirement 8: Preserve authentication, authorization, and clinical boundaries

**User Story:** As a platform owner, I want the visual redesign to remain behaviorally safe, so that appearance changes cannot weaken application security or clinical ownership.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL continue to use the existing `AuthGuard`, auth store, token lifecycle, inactivity behavior, login/logout routes, and server-authoritative API authorization.
2. THE Frontend_Redesign SHALL treat Permission_Affordance as a convenience filter and SHALL preserve server response handling for unauthorized, scope-denied, validation, conflict, offline, and degraded requests.
3. THE Frontend_Redesign SHALL keep EDC clinical data boundaries, status/ownership/freshness labels, and direct access-denied behavior unchanged in meaning.
4. THE Frontend_Redesign SHALL keep CTMS operational content visibly distinct from EDC clinical content and SHALL preserve CTMS disabled, unavailable, empty, worker-unavailable, and capability-gated behavior.
5. THE Frontend_Redesign SHALL not create a second auth shell, route migration, API business-logic change, clinical data model change, or CTMS clinical mutation path.
6. WHEN the visual redesign changes a control that can initiate a mutation, THE Frontend_Redesign SHALL retain the existing endpoint, payload, permission check, capability check, confirmation requirement, and post-mutation cache policy.

### Requirement 9: Responsive behavior and accessibility

**User Story:** As a user with varied devices and access needs, I want the dashboard to remain usable everywhere, so that responsive styling does not remove information or controls.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL support the Supported_Viewport range without horizontal page overflow caused by the Authenticated_Shell or shared page container.
2. WHEN a table cannot fit the current viewport, THE Frontend_Redesign SHALL provide accessible horizontal scrolling, responsive row stacking, or an equivalent layout that retains every required field and action.
3. THE Frontend_Redesign SHALL make navigation, buttons, links, form controls, tables, tabs, dialogs, dropdowns, tooltips, selectors, retry actions, and sign-out keyboard operable.
4. THE Frontend_Redesign SHALL associate visible labels and validation messages with controls through accessible names, descriptions, and invalid-state semantics.
5. WHEN a modal surface opens, THE Frontend_Redesign SHALL move focus to the first meaningful control, constrain focus as required, announce the surface name, and restore focus on close.
6. WHEN asynchronous content changes, THE Frontend_Redesign SHALL expose loading, success, error, empty, offline, and permission messages through appropriate status semantics without relying on color alone.
7. THE Frontend_Redesign SHALL not require hover to discover an essential label, status, action, ownership indicator, or error explanation.
8. THE Frontend_Redesign SHALL preserve readable status, ownership, freshness, and error text at supported viewport widths and in both supported themes.

### Requirement 10: Migrate feature pages incrementally

**User Story:** As a delivery team, I want an incremental migration, so that the redesign can ship in safe slices instead of creating a large untestable rewrite.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL migrate the visual foundation and Authenticated_Shell before migrating feature-page groups.
2. WHEN a feature-page group is migrated, THE Frontend_Redesign SHALL keep the existing route component, API integration, business logic, and behavior tests connected to the migrated presentation.
3. THE Frontend_Redesign SHALL migrate feature groups in an order that leaves every route rendered by either the new shared primitives or the existing compatible presentation at every intermediate checkpoint.
4. THE Frontend_Redesign SHALL prioritize the authenticated shell, dashboard/list/detail patterns, forms/dialogs, clinical status surfaces, EDC pages, CTMS pages, and public auth pages as separately reviewable migration slices.
5. THE Frontend_Redesign SHALL provide a compatibility strategy for legacy page-specific styles and SHALL remove duplicated styles only after the replacement primitive is covered by component or browser tests.
6. WHEN a migration slice fails a behavior regression check, THE Frontend_Redesign SHALL allow the slice to be reverted without reverting unrelated API or business-logic changes.

### Requirement 11: Theme, component, and route regression evidence

**User Story:** As a delivery lead, I want measurable evidence for the redesign, so that visual polish can ship without regressions.

#### Acceptance Criteria

1. THE Frontend_Redesign SHALL provide component tests for UI_Primitives covering variants, disabled/pending states, accessible names, focus behavior, and theme-compatible class output.
2. THE Frontend_Redesign SHALL provide component or integration tests for Authenticated_Shell navigation, responsive drawer behavior, breadcrumbs, Study_Context selectors, user menu, theme control, CTMS capability gating, and sign-out.
3. THE Frontend_Redesign SHALL provide route regression coverage for existing EDC and CTMS paths, deep links, search state, direct access-denied behavior, and preserved query/mutation boundaries.
4. THE Frontend_Redesign SHALL provide browser coverage for representative desktop and mobile viewports, light and dark themes, keyboard navigation, dialogs, tables, forms, loading/error/empty states, offline/degraded states, and status/ownership/freshness labels.
5. THE Frontend_Redesign SHALL preserve existing EDC/CTMS regression coverage and SHALL add visual or interaction assertions without weakening existing API contract and clinical-boundary assertions.
6. THE Frontend_Redesign SHALL document any visual or interaction behavior that requires product confirmation before implementation, including exact breakpoints, theme persistence location, search scope, notification behavior, and migration order exceptions.

## Explicit Non-Goals

- No second React application, second authentication shell, duplicate route tree, or route migration.
- No backend API, database schema, business-rule, authorization-policy, or clinical data-model redesign.
- No change to EDC ownership of Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV/review/freeze/lock/signatures, Clinical_Attachments, or clinical exports.
- No CTMS mutation path for EDC-owned clinical records or workflows.
- No replacement of TanStack Router, TanStack Query, Zustand, React Hook Form, Zod, Tailwind CSS v4, or the existing `cn()` helper unless an explicitly approved compatibility issue requires it.
- No blind copying of proprietary shadcn-admin/template code; the implementation shall use compatible open patterns and repository-owned components.
- No requirement for exact pixel parity with a third-party template; the measurable target is consistent shadcn-admin-style structure, interaction, accessibility, responsive behavior, and theme semantics.
- No new global search backend or notification backend; the redesign may expose existing data and routes through new UI affordances but shall not invent unsupported API behavior.
- No offline mutation queue unless a separate API idempotency and product decision explicitly authorizes such behavior.

## Assumptions and Decisions Requiring Confirmation

1. The redesign can use the existing `lucide-react`, `class-variance-authority`, `clsx`, `tailwind-merge`, TanStack Router/Query/Table, React Hook Form, Zod, Vitest, Testing Library, and Playwright dependencies without adding a Radix package. If an accessible primitive truly requires Radix, the exact package/version must be approved and pinned before implementation.
2. The existing `frontend/src/components/ui/` directory is the intended home for reusable primitives; the implementation should confirm whether any current files exist there before task execution.
3. The global search control is a presentation affordance until an existing search API or route is identified. The initial implementation should either wire it to an existing supported search behavior or render a clearly labeled non-submitting placeholder rather than inventing a backend contract.
4. The notification control should reuse the existing `/notifications` route and notification data behavior; a new notification service is out of scope.
5. The exact desktop sidebar breakpoint, content max-width, density scale, font choice, and default theme persistence mechanism require product confirmation during design review. The specification assumes CSS media queries, a semantic density scale, the current project font stack unless a repository-approved font is available, and local browser persistence only if privacy and deployment policy allow it.
6. The visual migration should preserve existing page semantics even where current pages use emoji icons or page-specific Tailwind classes; icon replacement and style consolidation are presentation changes only.
7. No tests or builds are run while creating this specification, per the user request. Implementation tasks include validation commands for the future execution phase.
