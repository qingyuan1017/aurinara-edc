# Implementation Plan: CTMS Frontend

## Overview

This plan converts the `ctms-frontend` design into incremental prompts for a code-generation LLM. Each leaf task involves writing, modifying, or testing code, builds on earlier work, and leaves the resulting component wired into the existing CTMS route tree. The plan extends `frontend/src/features/ctms/`, `frontend/src/lib/router.ts`, `frontend/src/components/layout/AppShell.tsx`, and existing CTMS tests; it does not create a duplicate app or implement EDC clinical mutation paths.

The implementation uses React 19, TypeScript, Vite, TanStack Router/Query, React Hook Form, Zod, Tailwind/shadcn-style components, Vitest/Testing Library, and Playwright. Frontend permission and capability checks are convenience controls only. Server authorization, canonical identity, ownership, projection minimization, transitions, exports, attachments, replay, and conflict policy remain authoritative at the API boundary described by `.kiro/specs/ctms-integration/requirements.md` and `.kiro/specs/ctms-integration/design.md`.

Tasks marked with `*` are optional test tasks. Every property task maps to one design property and must use at least 100 generated examples. Checkpoints are planning gates and are excluded from the dependency graph. Convert each leaf task into a prompt for a code-generation LLM that implements only that step, runs the relevant validation, and wires the result into a previous route/component/test harness.

## Tasks

### 1. Establish typed CTMS frontend foundations

- [ ] 1.1 Refactor CTMS capability metadata into a phase/action matrix
  - Extend `capabilities.ts` with normalized `ready`, `disabled`, and `unavailable` states, capability-code constants, phase-to-capability metadata, and a single action/route descriptor map.
  - Preserve `CTMS_DISABLED_MANIFEST` fallback behavior and ensure capability failures never remove EDC navigation.
  - Add typed support for server environment/platform availability without inferring authorization from a failed request.
  - _Requirements: 1.1–1.6, 2.1–2.6, 3.4–3.6_

- [ ] 1.2 Implement typed API models, error normalization, and scoped query keys
  - Extend `api.ts` or split the API layer into focused modules for typed mutation payloads/results, transitions, filters, exports, attachments, health, failed events, conflicts, correlation metadata, and sanitized baseline errors.
  - Include server pagination and optional cursor metadata; preserve `/api/v1/ctms` assumptions from the integration design.
  - Add a query-key factory containing resource, route scope, site/study scope, filters, pagination, and phase whenever those values affect a response.
  - _Requirements: 5.1–5.9, 6.2–6.6, 8.1–8.7, 9.3–9.7, 11.1–11.7_

- [ ] 1.3 Implement shared CTMS state, offline, and mutation-feedback primitives
  - Add query/mutation state classification for loading, refreshing, success, empty, unauthorized, disabled, unavailable, offline, generic error, and worker-unavailable states.
  - Add browser online/offline listeners that mark cached read data and block non-idempotent mutations by default without inventing a durable offline queue.
  - Add accessible mutation success/error announcements that retain request and correlation IDs when safe.
  - _Requirements: 2.3, 5.6–5.8, 9.6–9.7, 10.1–10.7, 11.6_

- [ ]* 1.4 Write property tests for capability/persona affordances and phase safety
  - **Property 1: Phase and persona affordances never exceed server metadata**
  - Generate manifests, phases, permissions, route/action descriptors, and prohibited EDC resources; assert visible actions never exceed capability/permission metadata or expose clinical mutations.
  - Tag: `Feature: ctms-frontend, Property 1: Phase and persona affordances never exceed server metadata`
  - **Validates: Requirements 2.1–2.6, 3.1–3.5, 12.6**

- [ ]* 1.5 Write property tests for scoped filter serialization and query keys
  - **Property 2: Scope and filters round-trip without ambiguity**
  - Generate study/site scopes, supported filters, pagination, and phases; assert route scope, request params, parsed search state, and query keys remain equivalent.
  - Tag: `Feature: ctms-frontend, Property 2: Scope and filters round-trip without ambiguity`
  - **Validates: Requirements 4.4, 6.2, 6.5, 11.2–11.3, 11.7**

- [ ]* 1.6 Write property tests for safe operational payload/action construction
  - **Property 3: Operational payloads cannot become clinical mutation requests**
  - Generate operational form input with prohibited clinical keys, projections, attachment/export ownership, and canonical references; assert safe CTMS payloads and no EDC mutation actions.
  - Tag: `Feature: ctms-frontend, Property 3: Operational payloads cannot become clinical mutation requests`
  - **Validates: Requirements 1.2, 1.5, 5.1–5.4, 7.3–7.4, 8.1, 8.6, 12.2–12.6**

### 2. Productize persona navigation and scoped workspaces

- [ ] 2.1 Implement persona- and capability-aware CTMS navigation in AppShell
  - Replace the single CTMS navigation item with a resolver that groups study operations, site operations, reporting/exports, and coordination/health according to capability codes and frontend permission affordances.
  - Keep all existing EDC navigation items, selectors, route behavior, and shell layout unchanged for CTMS_Admin, CTMS_Operations_User, CTMS_Viewer, mixed permissions, disabled CTMS, and capability failure.
  - Use TanStack Router `Link` navigation and preserve active route/search state.
  - _Requirements: 1.1, 1.4, 2.1–2.6, 3.1–3.6_

- [ ] 2.2 Build reusable study/site workspace layouts and direct-route states
  - Refactor `WorkspacePage.tsx` into a context-aware layout with canonical EDC study/site identifiers, section navigation, capability gating, permission affordances, and direct-route access-denied/unavailable/disabled states.
  - Enable only the active view's queries; preserve the existing CTMS route paths and add aliases only where needed.
  - Add actionable empty states for study and site workspaces and route-authoritative study/site scope handling.
  - _Requirements: 1.2–1.6, 2.6, 4.1–4.5, 10.1–10.7, 12.1–12.5_

- [ ] 2.3 Implement responsive record-list and dashboard primitives
  - Replace generic dense record output where needed with accessible tables/cards supporting semantic headers, responsive stacking or controlled scroll, pagination, filter summary, status text, and keyboard actions.
  - Reuse existing Tailwind/shadcn-style components and ownership presentation primitives rather than creating a parallel design system.
  - _Requirements: 4.5, 6.1–6.6, 13.1–13.6_

- [ ]* 2.4 Write persona, workspace, and EDC-shell component tests
  - Test Admin, Operations User, Viewer, mixed permissions, disabled/unavailable manifests, direct denied routes, canonical identifiers, actionable empty states, and preservation of baseline EDC navigation.
  - **Validates: Requirements 1.1–1.6, 2.1–2.6, 3.1–3.6, 4.1–4.5, 12.5**

### 3. Implement operational forms and mutations

- [ ] 3.1 Create shared React Hook Form/Zod schemas and form shell
  - Add schemas and reusable form components for owned strings, dates, quantities, enum values, canonical references, file metadata, transition reasons, and server field/form error mapping.
  - Ensure schemas are convenience validation only, do not encode server scope as authorization, and do not persist potentially clinical draft values to local storage.
  - Add focus management, `aria-invalid`, error descriptions, cancel behavior, and mutation feedback.
  - _Requirements: 5.5–5.9, 13.1–13.3_

- [ ] 3.2 Implement study/site profile, plan, activation, enrollment, and milestone forms
  - Add create/update forms for CTMS operational study profile/plans and operational site profile/activation actions using canonical Study/Site IDs.
  - Add enrollment target and operational milestone forms with server-provided status options and no clinical identity replacement or clinical values.
  - Wire successful responses to scoped cache invalidation and failed responses to safe server error preservation.
  - _Requirements: 4.1–4.4, 5.1–5.3, 5.5–5.8, 11.4–11.6_

- [ ] 3.3 Implement monitoring plan/activity, task, and contact forms
  - Add create/update forms and detail actions for monitoring plans/versions, monitoring activities, operational tasks, query follow-ups, and operational contacts.
  - Keep monitoring activities distinct from EDC Visit_Instances and query follow-ups distinct from Query lifecycle actions.
  - Support server-owned transition choices, assignment, rescheduling/completion/cancellation reasons, and correlation metadata.
  - _Requirements: 5.4–5.8, 6.1–6.5, 7.1–7.4, 12.2–12.3_

- [ ] 3.4 Implement reusable status-transition mutation flow
  - Add a transition form/dialog that renders only server-returned allowed statuses, requires reasons where declared, prevents stale local status display, and presents current status after success.
  - Add mutation hooks with no optimistic status replacement and minimal resource-specific invalidation.
  - _Requirements: 5.5–5.8, 11.4–11.5_

- [ ]* 3.5 Write form and transition property tests
  - **Property 5: Form validation follows server transition metadata**
  - Generate form models, transition options, required-reason flags, safe field errors, and unrelated values; assert invalid transitions/reasons are blocked and safe values persist.
  - Tag: `Feature: ctms-frontend, Property 5: Form validation follows server transition metadata`
  - **Validates: Requirements 5.5–5.6, 5.9**

- [ ]* 3.6 Write mutation cache-policy property tests
  - **Property 6: Mutation outcomes produce minimal cache effects**
  - Generate mutation types, scopes, identifiers, successful/failed outcomes, and existing keys; assert affected CTMS families are updated/invalidated, failures preserve authoritative data, and EDC keys are untouched.
  - Tag: `Feature: ctms-frontend, Property 6: Mutation outcomes produce minimal cache effects`
  - **Validates: Requirements 5.7–5.8, 9.5, 10.6, 11.4–11.5**

- [ ]* 3.7 Write form component and mutation contract tests
  - Test representative create/update/status transitions for study, site, enrollment, monitoring, tasks, contacts, activation, server validation, 403/409/422 responses, request IDs, and cache refresh.
  - **Validates: Requirements 5.1–5.9, 11.1–11.6**

### 4. Add dashboards, reports, filters, and projections

- [ ] 4.1 Implement route-persisted dashboard and report filters
  - Add typed filter controls for supported status, site, owner, date range, priority, due-date category, and report type dimensions.
  - Serialize filters through TanStack Router search state, use server filters/totals/order as authoritative, show active-filter summaries, and distinguish empty filtered results from errors.
  - _Requirements: 6.1–6.6, 11.2–11.3, 11.7_

- [ ] 4.2 Implement scoped operational dashboards and report views
  - Add study/site dashboards and report pages for enrollment, monitoring, tasks, readiness, milestones, and approved quality signals using typed API responses.
  - Display server pagination/totals and never reconstruct unauthorized totals from rendered rows.
  - Preserve last valid result with timestamp when a subsequent filter request fails.
  - _Requirements: 4.1–4.2, 6.1–6.6, 10.2–10.3, 11.7_

- [ ] 4.3 Complete projection and freshness presentation
  - Extend `OwnershipPresentation.tsx`/`ProjectionFreshness` for source module, source record, source/projected timestamps, source/rule version, current/stale/unknown state, aggregate quality-signal wording, and refresh-only actions.
  - Ensure projections, operational subject status, monitoring links, and query follow-ups cannot produce clinical mutation actions.
  - _Requirements: 1.3, 1.6, 6.3, 7.1–7.5, 12.1–12.4_

- [ ]* 4.4 Write ownership/freshness property tests
  - **Property 4: Ownership and freshness presentation is explicit**
  - Generate operational/clinical statuses, projection metadata, canonical references, and quality signals; assert authoritative-module, read-only, freshness, and identifier semantics are always present.
  - Tag: `Feature: ctms-frontend, Property 4: Ownership and freshness presentation is explicit`
  - **Validates: Requirements 1.3, 1.6, 6.3, 7.1–7.5, 12.1–12.4**

- [ ]* 4.5 Write server-authoritative filter/report property tests
  - **Property 10: Server totals and filter results remain authoritative**
  - Generate server pages/totals, prior rows, active filters, and client row subsets; assert current server metadata is rendered and stale filtered rows are not presented.
  - Tag: `Feature: ctms-frontend, Property 10: Server totals and filter results remain authoritative`
  - **Validates: Requirements 6.2, 6.4–6.6, 11.7**

- [ ]* 4.6 Write projection clinical-authority property tests
  - **Property 11: Projection and operational status never grant clinical authority**
  - Generate projections, operational statuses, linked EDC records, and permissions; assert only CTMS actions are emitted and all clinical authority actions remain absent.
  - Tag: `Feature: ctms-frontend, Property 11: Projection and operational status never grant clinical authority`
  - **Validates: Requirements 1.5, 7.3–7.4, 8.6, 12.2–12.6**

### 5. Add exports, attachments, and coordination remediation

- [ ] 5.1 Implement operational export request and lifecycle UI
  - Add typed export filters/formats, create/retry/status/download panels, expiry handling, progress states, and CTMS-owned content labels.
  - Serialize only API-supported operational filters; do not expose clinical export actions or content.
  - Invalidate export list/detail and notification summaries only when export mutations succeed.
  - _Requirements: 8.1–8.3, 8.6–8.7, 11.4–11.5_

- [ ] 5.2 Implement Operational_Attachment upload and lifecycle UI
  - Add attachment metadata validation, upload progress, retry, download, delete, restore, retention/expiry state, and parent-record association for CTMS operational records.
  - Keep file content out of query cache and reject Clinical_Attachment actions through CTMS controls.
  - Surface server scope, type, size, retention, and authorization errors without exposing inaccessible metadata.
  - _Requirements: 8.4–8.7, 11.4–11.6, 13.1–13.5_

- [ ] 5.3 Implement failed-event replay and conflict-resolution panels
  - Replace generic remediation output with sanitized event/conflict details, correlation IDs, current versions, server-provided policy choices, reason forms, pending outcomes, and permission-aware actions.
  - Invalidate failed-event, conflict, event-log, projection, and affected operational queries after successful replay/resolution.
  - Never render raw event bodies, credentials, clinical values, unrestricted query messages, stack traces, or unrestricted audit data.
  - _Requirements: 9.1–9.7, 11.4–11.6_

- [ ]* 5.4 Write sanitized remediation property tests
  - **Property 7: Error and remediation view models are sanitized**
  - Generate errors/coordination records containing safe and prohibited fields plus permission sets; assert safe metadata remains and raw/prohibited values/actions are absent.
  - Tag: `Feature: ctms-frontend, Property 7: Error and remediation view models are sanitized`
  - **Validates: Requirements 9.1–9.2, 9.6–9.7, 10.2, 11.6**

- [ ]* 5.5 Write export lifecycle property tests
  - **Property 8: Export lifecycle actions follow server state**
  - Generate export states, supported options, permissions, and server actions; assert operational-only serialization, CTMS ownership, and state-appropriate actions.
  - Tag: `Feature: ctms-frontend, Property 8: Export lifecycle actions follow server state`
  - **Validates: Requirements 8.1–8.3, 8.6**

- [ ]* 5.6 Write export, attachment, and remediation integration tests
  - Test representative completed/failed/expired exports, attachment upload progress and denial, retention errors, replay, conflict resolution, policy changes, correlation display, and minimal invalidation.
  - **Validates: Requirements 8.1–8.7, 9.1–9.7, 11.4–11.6**

### 6. Complete accessibility, responsive behavior, and degraded-state UX

- [ ] 6.1 Implement accessible forms, dialogs, live regions, and responsive layouts
  - Apply semantic labels, error associations, keyboard behavior, focus trapping/return, status announcements, non-color ownership/status cues, and mobile table/card alternatives across CTMS views.
  - Verify no essential ownership, freshness, status, error, or action content depends on hover.
  - _Requirements: 4.5, 10.1–10.7, 13.1–13.6_

- [ ] 6.2 Wire disabled, unavailable, offline, empty, loading, error, and worker-unavailable states across all CTMS views
  - Use the shared state primitives consistently for capability, workspace, forms, reports, exports, attachments, projections, and coordination screens.
  - Ensure retry success replaces degraded state and accepted asynchronous operations remain visible by correlation ID.
  - _Requirements: 2.1–2.6, 9.3–9.6, 10.1–10.7, 12.5_

- [ ]* 6.3 Write degraded-state and capability-change property tests
  - **Property 9: Query state categories remain distinct**
  - Generate query/network/capability/worker states, prior snapshots, and retry outcomes; assert category-specific copy, cached labeling, safe mutation behavior, and successful recovery.
  - Tag: `Feature: ctms-frontend, Property 9: Query state categories remain distinct`
  - **Validates: Requirements 2.3, 10.1–10.7**

- [ ]* 6.4 Write capability monotonic-safety property tests
  - **Property 12: Capability changes are monotonic toward safety**
  - Generate old/new manifests, active actions, and cached CTMS/EDC key sets; assert removed capabilities remove actions and invalidate only CTMS data while preserving EDC keys/navigation.
  - Tag: `Feature: ctms-frontend, Property 12: Capability changes are monotonic toward safety`
  - **Validates: Requirements 2.2–2.5, 10.6, 11.3–11.5, 12.5**

- [ ]* 6.5 Write accessibility and responsive component/browser tests
  - Test keyboard navigation, form errors, dialog focus, live announcements, semantic ownership/status labels, narrow viewport tables/cards, and no hover-only actions with Testing Library and Playwright.
  - **Validates: Requirements 4.5, 10.7, 13.1–13.6**

### 7. Verify API contracts and EDC preservation

- [ ] 7.1 Add CTMS API contract fixtures and client contract tests
  - Add representative fixtures for capabilities/phases, pagination, filters, transitions, errors/request IDs, ownership/freshness, export jobs, attachment constraints, health, replay, conflicts, and correlation outcomes.
  - Assert client adapters use the existing API client and `/api/v1/ctms` contract and do not introduce EDC mutation endpoints.
  - _Requirements: 5.1–5.9, 8.1–8.7, 9.1–9.7, 11.1–11.7, 14.5–14.6_

- [ ]* 7.2 Write API contract and non-leakage integration tests
  - Use representative error envelopes, pagination metadata, sensitive values, prohibited fields, and permission states; assert normalized responses preserve safe metadata and remove prohibited content.
  - Exercise the API adapter with representative server responses without creating a second property test for Design Property 7.
  - **Validates: Requirements 9.7, 11.1–11.7, 14.5**

- [ ] 7.3 Strengthen EDC regression coverage for every CTMS degraded mode
  - Extend the existing `FinalEDCRegression.test.tsx` and related shell tests for CTMS disabled, capability unavailable, empty data, offline, worker-unavailable, and direct denied CTMS routes.
  - Assert EDC authentication shell, study/site selectors, clinical dashboards, casebook/data capture, queries, SDV/review, signatures, clinical attachments, and clinical exports remain available and unchanged.
  - _Requirements: 1.4, 2.3, 3.6, 10.2, 10.4–10.5, 12.5, 14.4_

- [ ]* 7.4 Write EDC-preservation integration tests for projections/status links
  - Attempt all frontend CTMS actions involving EDC-owned references and assert no EDC mutation control, request, or cache invalidation is produced.
  - **Validates: Requirements 1.5, 7.3–7.4, 12.2–12.6**

- [ ] 7.5 Run frontend validation and document contract assumptions
  - Run `npm run lint`, `npm run build`, `npm run test`, and the relevant Playwright suite using the repository's non-watch scripts.
  - Record unresolved capability-code, transition, filter, projection freshness, attachment, export, offline, and conflict-policy assumptions in the implementation notes or contract fixtures before the phase checkpoint.
  - _Requirements: 13.6, 14.1–14.6_

### 8. Checkpoint — typed foundation and navigation

- Ensure all required implementation tasks through Section 2 compile and targeted tests pass; verify CTMS capability failure cannot remove EDC navigation and ask the user if questions arise.

### 9. Checkpoint — operational workflows and data boundaries

- Ensure study/site/enrollment/monitoring/task/contact forms, ownership labels, projections, filters, and cache invalidation tests pass; verify no EDC-owned mutation path was added and ask the user if questions arise.

### 10. Checkpoint — exports, remediation, accessibility, and resilience

- Ensure exports, attachments, replay/conflicts, degraded states, accessibility, responsive behavior, and EDC regression tests pass; verify all unresolved API assumptions are documented and ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and may be skipped for a faster MVP; core implementation tasks are not optional.
- Every property test is one separate task and must use pinned `fast-check` with at least 100 generated examples, deterministic inputs, and no external services.
- Component/browser tests are required for UI rendering, accessibility, responsive behavior, file chooser/progress behavior, offline signals, and EDC fallback; property tests do not replace them.
- The frontend must reuse existing CTMS routes, API client, permission codes, study/site context, ownership components, and EDC regression conventions. Any refactor must preserve existing safe fallback behavior.
- The server remains authoritative for authorization, scope, ownership, transitions, projection allowlists, export/attachment access, replay, and conflict policy. Frontend convenience checks must never be described or implemented as security controls.
- No task adds mutation paths for EDC Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV, review, freeze/lock, signatures, Clinical_Attachments, or clinical exports.
- Each task references requirements and the design's API/ownership assumptions; contract discrepancies must be resolved through adapters or typed fixtures rather than weakened UI boundaries.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "1.5", "1.6", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1", "7.1"] },
    { "id": 3, "tasks": ["2.4", "3.2", "3.3", "3.4", "4.1"] },
    { "id": 4, "tasks": ["3.5", "3.6", "3.7", "4.2", "4.3", "5.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["4.4", "4.5", "4.6", "5.4", "5.5", "5.6", "6.1", "6.2"] },
    { "id": 6, "tasks": ["6.3", "6.4", "6.5", "7.2", "7.3", "7.4"] },
    { "id": 7, "tasks": ["7.5"] }
  ]
}
```
