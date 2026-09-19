# Requirements Document

## Introduction

This document specifies completion and productization of the existing CTMS frontend inside the authenticated React application at `frontend/src/features/ctms/`. The feature extends the current `AppShell`, TanStack Router routes, TanStack Query hooks, capability manifest, ownership presentation, and EDC fallback tests. It does not create a second application, replace the existing EDC clinical frontend, or transfer clinical authority to CTMS.

The CTMS frontend presents CTMS-owned operational study and site work, approved read-only projections, and coordination remediation. The EDC frontend remains authoritative for `Study_Version`, clinical subjects, `Visit_Instances`, `Form_Instances`, `Field_Values`, `Queries`, SDV, review, freeze/lock, signatures, `Clinical_Attachments`, and clinical exports. Frontend permission checks control affordances only; server-side authorization remains authoritative for every read, mutation, upload, replay, resolution, and download.

This specification builds on `.kiro/specs/ctms-integration/requirements.md` and `.kiro/specs/ctms-integration/design.md`. The integration documents remain authoritative for backend ownership, coordination, projection allowlists, server permissions, and API error semantics. This document narrows those contracts to frontend behavior, API assumptions required by the UI, accessibility, responsive presentation, and incremental implementation.

## Glossary

- **CTMS_Frontend**: The existing React/TypeScript CTMS feature area under `frontend/src/features/ctms/`, including its routes, pages, components, API clients, hooks, and tests.
- **EDC_Frontend**: The existing clinical feature areas and navigation outside `frontend/src/features/ctms/`.
- **AppShell**: The authenticated layout in `frontend/src/components/layout/AppShell.tsx` that owns global navigation, study/site selectors, and the route outlet.
- **CTMS_Admin**: A server-defined CTMS role that can administer CTMS operational configuration and authorized remediation actions within assigned scope.
- **CTMS_Operations_User**: A server-defined CTMS role that can perform assigned operational study, site, enrollment, monitoring, task, contact, attachment, and export work within assigned scope.
- **CTMS_Viewer**: A server-defined CTMS role that can read authorized CTMS data and projections without CTMS mutation actions.
- **CTMS_Capability_Manifest**: The server response describing whether CTMS is enabled, the available delivery phase, capability codes, and optional environment/platform availability signals.
- **CTMS_Phase**: A server-controlled delivery boundary. Phase 1 covers operational study/site/enrollment foundations and dashboards; Phase 2 adds monitoring, work management, attachments, projections, coordination, and notifications; Phase 3 adds quality signals, recovery, advanced reports/exports, and health operations.
- **Operational_Workspace**: A study-scoped or site-scoped CTMS route that presents CTMS-owned operational records and permitted actions.
- **Operational_Record**: A CTMS-owned study profile, site profile, enrollment target, operational milestone, monitoring plan/activity, operational task, operational contact, operational attachment, report, or export job.
- **Projection**: An approved, minimized, versioned, read-only view of data owned by another module.
- **Ownership_Label**: A visible label identifying EDC or CTMS as authoritative and identifying projected or read-only state where applicable.
- **Freshness_Metadata**: Projection source timestamp, projected timestamp, source version, and current/stale/unknown state used to explain projection currency.
- **Operational_Export**: An export containing CTMS-owned operational data and explicitly approved projections only.
- **Operational_Attachment**: A CTMS-owned file associated with an operational record and governed by shared storage controls.
- **Coordination_Record**: A sanitized failed event or conflict that can be inspected and, when authorized, replayed or resolved.
- **Frontend_Convenience_Check**: A client-side visibility or affordance check that improves usability but is not an authorization boundary.
- **Server_Authorization**: The API-enforced permission, study scope, site scope, ownership, transition, and data-minimization decision that determines whether a request succeeds.
- **Degraded_State**: A user-visible disabled, unavailable, offline, loading, error, empty, or worker-unavailable state with an explicit explanation and recovery action where applicable.

## Requirements

### Requirement 1: Preserve the first-party module boundary

**User Story:** As a platform owner, I want the CTMS frontend to extend the existing authenticated application, so that operational workflows remain integrated with EDC without creating duplicate clinical authority.

#### Acceptance Criteria

1. THE CTMS_Frontend SHALL render inside the existing AppShell and authenticated route tree without creating a second application shell or authentication flow.
2. THE CTMS_Frontend SHALL use canonical EDC Study, Site, Subject, and Visit_Instance identifiers as references and SHALL not create a competing clinical identity.
3. THE CTMS_Frontend SHALL label CTMS operational statuses separately from EDC clinical statuses whenever both statuses are shown.
4. THE CTMS_Frontend SHALL keep EDC clinical navigation and clinical indicators available when CTMS is disabled, unavailable, empty, or unable to load.
5. THE CTMS_Frontend SHALL not expose mutation controls for EDC-owned Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV, review, freeze/lock, signatures, Clinical_Attachments, or clinical exports.
6. WHEN a CTMS view references an EDC-owned record, THE CTMS_Frontend SHALL display the canonical identifier and an Ownership_Label that identifies EDC authority.

### Requirement 2: Capability and server-controlled phase gating

**User Story:** As a delivery lead, I want CTMS capabilities to be gated by the server manifest, so that incomplete phases cannot expose unsupported operations.

#### Acceptance Criteria

1. WHEN the CTMS_Capability_Manifest reports `enabled: false`, THE CTMS_Frontend SHALL hide CTMS navigation and SHALL render a stable CTMS-disabled explanation for direct CTMS navigation without changing EDC routes.
2. WHEN the CTMS_Capability_Manifest reports an enabled CTMS_Phase, THE CTMS_Frontend SHALL expose only routes, navigation items, forms, and actions whose capability codes are present in the manifest and whose phase is delivered.
3. WHEN the capability request fails, THE CTMS_Frontend SHALL preserve EDC navigation and SHALL render CTMS as unavailable rather than treating the failure as successful authorization.
4. WHEN a capability manifest changes during an active session, THE CTMS_Frontend SHALL remove unavailable CTMS actions and invalidate affected CTMS queries before permitting a new mutation.
5. THE CTMS_Frontend SHALL treat capability and permission checks as Frontend_Convenience_Checks while the CTMS API SHALL remain the Server_Authorization authority.
6. WHEN a direct CTMS route lacks a required capability or Server_Authorization, THE CTMS_Frontend SHALL render an access-denied or unavailable state without attempting a prohibited mutation.

### Requirement 3: Persona-based navigation and access affordances

**User Story:** As a CTMS user, I want navigation and actions to match my CTMS persona, so that the workspace is focused while direct URLs remain safe.

#### Acceptance Criteria

1. WHEN an authenticated user has CTMS_Admin permissions, THE CTMS_Frontend SHALL provide navigation to authorized operational workspaces, reports, exports, health, failed events, and conflicts within the user's scope.
2. WHEN an authenticated user has CTMS_Operations_User permissions, THE CTMS_Frontend SHALL provide navigation and actions for authorized operational study, site, enrollment, monitoring, task, contact, attachment, dashboard, report, and export work.
3. WHEN an authenticated user has CTMS_Viewer permissions, THE CTMS_Frontend SHALL provide read navigation and SHALL hide CTMS mutation, upload, replay, resolution, and destructive action controls.
4. WHILE a user lacks a CTMS permission, THE CTMS_Frontend SHALL hide the corresponding navigation item or action as a Frontend_Convenience_Check.
5. WHEN the server rejects an action because of permission or scope, THE CTMS_Frontend SHALL show the baseline access or scope error and SHALL not infer that a hidden control provided authorization.
6. THE CTMS_Frontend SHALL preserve all EDC navigation items and active route behavior for every CTMS persona.

### Requirement 4: Study and site operational workspaces

**User Story:** As a study operations user, I want study and site workspaces with consistent context, so that operational records can be managed without losing canonical EDC context.

#### Acceptance Criteria

1. WHEN a user opens a study Operational_Workspace, THE CTMS_Frontend SHALL display the canonical EDC Study identifier, operational profile, plans, enrollment, milestones, monitoring, tasks, contacts, projections, reports, exports, and coordination views allowed by the manifest and scope.
2. WHEN a user opens a site Operational_Workspace, THE CTMS_Frontend SHALL display the canonical EDC Study and Site identifiers, operational site profile, activation/readiness actions, monitoring work, contacts, tasks, reports, and attachments allowed by the manifest and scope.
3. WHEN a workspace has no Operational_Record items, THE CTMS_Frontend SHALL display an actionable empty state that identifies the missing configuration and the permitted create action.
4. WHEN a workspace is scoped by the global study or site selector, THE CTMS_Frontend SHALL keep route parameters, query keys, displayed identifiers, and submitted scope consistent.
5. THE CTMS_Frontend SHALL render tables and cards with keyboard-accessible controls, visible status context, responsive overflow handling, and stable loading/error/empty states.

### Requirement 5: Operational forms and lifecycle transitions

**User Story:** As a CTMS operations user, I want validated forms for operational records, so that create, update, and status-transition work is efficient and auditable.

#### Acceptance Criteria

1. WHEN an authorized user submits a valid study profile or study plan form, THE CTMS_Frontend SHALL send only CTMS-owned fields with the canonical study identifier and SHALL refresh the affected study workspace after Server_Authorization succeeds.
2. WHEN an authorized user submits a valid site profile or activation form, THE CTMS_Frontend SHALL send only CTMS-owned fields with the canonical site identifier and SHALL refresh the affected site workspace after Server_Authorization succeeds.
3. WHEN an authorized user submits a valid enrollment target or operational milestone form, THE CTMS_Frontend SHALL send approved operational fields and canonical references without sending clinical values or clinical identity replacements.
4. WHEN an authorized user submits a valid monitoring plan, monitoring activity, task, or contact form, THE CTMS_Frontend SHALL send the corresponding CTMS-owned payload and SHALL display the resulting status and audit-relevant timestamps.
5. WHEN a user requests an operational status transition, THE CTMS_Frontend SHALL require a reason whenever the API contract requires a reason and SHALL present the allowed transition choices returned by the server.
6. WHEN a form receives a validation error, THE CTMS_Frontend SHALL preserve entered safe values, associate the error with the relevant field or form, and SHALL not clear unrelated workspace data.
7. WHEN a mutation succeeds, THE CTMS_Frontend SHALL invalidate or update the affected TanStack Query cache entries and SHALL show a success confirmation that identifies the changed operational record.
8. WHEN a mutation fails, THE CTMS_Frontend SHALL show the sanitized server error, SHALL preserve the current authoritative query data, and SHALL not optimistically display an unauthorized or uncommitted status.
9. THE CTMS_Frontend SHALL use React Hook Form and Zod for client-side shape and convenience validation while treating server validation and authorization as authoritative.

### Requirement 6: Dashboards, reports, and filtering

**User Story:** As a study operations lead, I want scoped dashboards and reports with useful filters, so that I can identify operational risk without viewing unauthorized or misleading clinical data.

#### Acceptance Criteria

1. WHEN an authorized user opens an operational dashboard, THE CTMS_Frontend SHALL display CTMS-owned enrollment, readiness, activation, monitoring, milestone, task, and approved quality-signal data returned by the API.
2. WHEN a user changes a dashboard or report filter, THE CTMS_Frontend SHALL encode the filter in the route or query state, preserve it during navigation, and request data for the selected scope.
3. WHEN a report response contains projected clinical metrics, THE CTMS_Frontend SHALL display the source module, source timestamp, Freshness_Metadata, and read-only state next to the metric.
4. WHEN a report response contains no rows for the selected filters, THE CTMS_Frontend SHALL display the active filters and an empty-result explanation without presenting stale rows as current results.
5. THE CTMS_Frontend SHALL provide filter controls for the report dimensions supported by the API contract, including status, site, owner, date range, priority, due-date category, and report type where supported.
6. WHEN a filter request is rejected for scope or validation, THE CTMS_Frontend SHALL display the server error and SHALL retain the last valid result with an explanation of its timestamp.

### Requirement 7: Projection presentation and read-only semantics

**User Story:** As a study team member, I want projected clinical signals clearly identified, so that operational decisions do not become accidental clinical mutations.

#### Acceptance Criteria

1. WHEN the CTMS_Frontend renders a Projection, THE CTMS_Frontend SHALL display source module, source record identifier when permitted, source timestamp, projected timestamp, source or rule version when available, freshness state, and a read-only indicator.
2. WHEN a Projection is stale or freshness is unknown, THE CTMS_Frontend SHALL display the stale or unknown state and SHALL provide a refresh or retry action without allowing edits to the Projection.
3. WHEN an operational record links to an EDC Subject, Query, or Visit_Instance, THE CTMS_Frontend SHALL display the EDC identifier as a read-only reference and SHALL distinguish the CTMS operational record from the EDC-owned clinical record.
4. THE CTMS_Frontend SHALL not render a Projection as an editable form, mutation target, clinical status authority, or source for a clinical export.
5. WHEN projected quality signals are shown on a dashboard or report, THE CTMS_Frontend SHALL identify the signal as an approved aggregate or minimized projection rather than unrestricted clinical data.

### Requirement 8: Operational exports and attachment flows

**User Story:** As a CTMS operations user, I want operational exports and attachments, so that authorized teams can exchange operational evidence without accessing clinical files or clinical exports.

#### Acceptance Criteria

1. WHEN an authorized user submits an operational export request, THE CTMS_Frontend SHALL send only supported operational filters and format options and SHALL display the export job status returned by the API.
2. WHEN an operational export becomes available, THE CTMS_Frontend SHALL provide a scope-checked download action and SHALL identify the export as CTMS-owned operational content.
3. WHEN an operational export is queued, running, failed, or expired, THE CTMS_Frontend SHALL display the corresponding state and SHALL provide only the retry or download action permitted by the API contract.
4. WHEN an authorized user uploads an Operational_Attachment, THE CTMS_Frontend SHALL validate supported type and size constraints, associate the attachment with a CTMS operational record, and SHALL display upload progress and completion state.
5. WHEN an authorized user downloads, deletes, restores, or replaces an Operational_Attachment, THE CTMS_Frontend SHALL require the corresponding Frontend_Convenience_Check and SHALL surface server authorization or retention errors.
6. THE CTMS_Frontend SHALL not provide CTMS actions that upload, download, delete, restore, or export Clinical_Attachments or EDC clinical export content.
7. WHEN an attachment or export action is denied, THE CTMS_Frontend SHALL preserve the operational record view and SHALL not expose inaccessible file metadata or content.

### Requirement 9: Failed-event replay and conflict resolution

**User Story:** As a CTMS administrator, I want safe coordination remediation, so that failed events and conflicts can be resolved without bypassing current authorization or ownership rules.

#### Acceptance Criteria

1. WHEN an authorized CTMS_Admin opens a Coordination_Record, THE CTMS_Frontend SHALL display sanitized reason codes, correlation identifiers, source and target references permitted by the API, current status, and remediation guidance.
2. WHEN a user lacks replay or conflict-management permission, THE CTMS_Frontend SHALL hide the corresponding action or render a permission explanation without exposing raw event bodies.
3. WHEN a CTMS_Admin submits a replay request, THE CTMS_Frontend SHALL require a reason, send the event identifier and reason to the API, and display the asynchronous correlation and outcome returned by the API.
4. WHEN a CTMS_Admin submits a conflict resolution, THE CTMS_Frontend SHALL present only policy choices returned by the API, require a resolution reason, and display the resulting conflict status.
5. WHEN replay or resolution succeeds, THE CTMS_Frontend SHALL invalidate failed-event, conflict, event-log, projection, and affected workspace queries as defined by the cache contract.
6. WHEN replay or resolution fails because current policy, identity, ownership, or scope changed, THE CTMS_Frontend SHALL display the sanitized server reason and SHALL not claim that the source or target record changed.
7. THE CTMS_Frontend SHALL never display raw event bodies, prohibited projection values, credentials, unrestricted clinical messages, stack traces, or unrestricted clinical audit data in remediation views.

### Requirement 10: Loading, error, empty, offline, and worker-unavailable states

**User Story:** As a CTMS user, I want clear degraded states, so that I can distinguish missing data from service failure and continue EDC work safely.

#### Acceptance Criteria

1. WHILE a CTMS query is loading, THE CTMS_Frontend SHALL display a labeled loading state that preserves workspace context and does not imply that data is empty.
2. IF a CTMS query returns an error, THEN THE CTMS_Frontend SHALL display a sanitized error state with a retry action when retry is safe and SHALL retain EDC navigation.
3. WHEN a CTMS query returns an empty collection, THE CTMS_Frontend SHALL display an empty state distinct from a service error and SHALL identify the permitted next action.
4. WHILE the browser is offline, THE CTMS_Frontend SHALL display an offline indicator, keep previously loaded safe read data visibly marked as cached, and SHALL prevent or queue mutations only according to the API/client offline contract.
5. IF the CTMS worker is unavailable, THEN THE CTMS_Frontend SHALL display worker-unavailable health or coordination state, SHALL preserve accepted asynchronous operation status, and SHALL not block EDC clinical workflows.
6. WHEN a retry succeeds after a degraded state, THE CTMS_Frontend SHALL replace the degraded state with current data and SHALL invalidate stale dependent queries.
7. THE CTMS_Frontend SHALL distinguish CTMS disabled, CTMS unavailable, worker unavailable, unauthorized, offline, empty, and generic request-error states in user-visible copy and accessible status semantics.

### Requirement 11: API contracts, caching, and invalidation

**User Story:** As a frontend engineer, I want typed and predictable CTMS API/query contracts, so that screens remain consistent after operational mutations and coordination events.

#### Acceptance Criteria

1. THE CTMS_Frontend SHALL use typed request and response models for CTMS capability, operational records, projections, dashboards, reports, exports, health, failed events, conflicts, pagination, and baseline errors.
2. THE CTMS_Frontend SHALL call CTMS API resources through the existing API client and SHALL preserve the `/api/v1/ctms` server contract represented by the integration design.
3. THE CTMS_Frontend SHALL include study scope, site scope, filters, pagination, and capability phase in query keys whenever those values affect a response.
4. WHEN a study, site, enrollment, monitoring, task, contact, attachment, export, projection, replay, or conflict mutation succeeds, THE CTMS_Frontend SHALL invalidate the minimal affected query families and SHALL not invalidate unrelated EDC clinical query families.
5. WHEN a mutation returns an updated resource, THE CTMS_Frontend SHALL update or invalidate the corresponding detail and list cache entries so that stale operational status is not presented as current.
6. WHEN an API returns a baseline error envelope and request identifier, THE CTMS_Frontend SHALL preserve the error code, safe message, and request identifier for user feedback and support diagnostics.
7. THE CTMS_Frontend SHALL treat pagination totals, cursors or pages, server filters, and server ordering as authoritative rather than reconstructing unauthorized totals from client data.

### Requirement 12: Ownership labels and clinical workflow preservation

**User Story:** As a clinical and operations team member, I want ownership labels to be unambiguous, so that CTMS convenience does not alter EDC clinical workflows.

#### Acceptance Criteria

1. THE CTMS_Frontend SHALL label CTMS-owned operational fields and statuses as CTMS-authoritative and SHALL label EDC-owned clinical fields and statuses as EDC-authoritative.
2. WHEN a CTMS monitoring activity references a Visit_Instance, THE CTMS_Frontend SHALL identify the monitoring activity as operational and the Visit_Instance as an EDC clinical reference that CTMS cannot reschedule, complete, freeze, lock, or modify.
3. WHEN a CTMS task references an EDC Query, THE CTMS_Frontend SHALL identify the task as operational follow-up and the Query lifecycle as EDC-owned.
4. WHEN a CTMS operational subject status appears with an EDC clinical access state, THE CTMS_Frontend SHALL display both labels and SHALL state that operational status does not grant or revoke EDC clinical access.
5. WHEN CTMS is disabled or unavailable, THE CTMS_Frontend SHALL preserve EDC route availability, study/site selectors, clinical status indicators, casebook behavior, data capture, query workflows, quality workflows, signatures, clinical attachments, and clinical exports.
6. THE CTMS_Frontend SHALL not infer clinical authorization, clinical data completeness, or clinical workflow state from a CTMS Projection or operational status.

### Requirement 13: Accessibility and responsive behavior

**User Story:** As a CTMS user with varied access needs and devices, I want an accessible responsive workspace, so that operational work remains usable without changing its meaning.

#### Acceptance Criteria

1. THE CTMS_Frontend SHALL provide keyboard-operable navigation, forms, dialogs, tables, filters, pagination, retry controls, mutation controls, and file controls.
2. THE CTMS_Frontend SHALL provide accessible names, labels, focus management, status announcements, error associations, and sufficient non-color status cues for CTMS actions and Degraded_States.
3. WHEN a dialog, drawer, or form opens, THE CTMS_Frontend SHALL move focus to the first meaningful control, trap focus within the active modal when required, and return focus to the invoking control on close.
4. WHEN a table or card layout narrows below its supported breakpoint, THE CTMS_Frontend SHALL preserve access to every field and action through responsive stacking, controlled horizontal scrolling, or an equivalent accessible layout.
5. THE CTMS_Frontend SHALL preserve readable ownership, freshness, status, and error semantics at supported viewport widths without relying on hover-only content.
6. THE CTMS_Frontend SHALL use the repository's existing Tailwind/shadcn-style components and established React Testing Library and Playwright accessibility conventions.

### Requirement 14: Frontend validation and delivery evidence

**User Story:** As a delivery lead, I want the CTMS frontend completion to be verifiable, so that each phase can ship without regressing EDC clinical work.

#### Acceptance Criteria

1. THE CTMS_Frontend SHALL provide automated unit and component coverage for role navigation, capability gating, ownership labels, freshness semantics, form validation, API error mapping, cache invalidation, and Degraded_States.
2. THE CTMS_Frontend SHALL provide integration coverage for authorized and denied operational mutations, operational exports, attachment flows, replay, conflict resolution, and server-error preservation.
3. THE CTMS_Frontend SHALL provide Playwright coverage for study and site operational workspaces, forms, filtering, projections, exports, remediation, responsive behavior, and persona-specific navigation.
4. THE EDC_Frontend SHALL have regression coverage proving EDC navigation and clinical workflows remain available when CTMS is disabled, unavailable, empty, offline, or worker-unavailable.
5. WHEN a frontend test exercises an API contract, THE test SHALL use representative server responses for pagination, ownership, projection freshness, error envelopes, capability phases, and correlation identifiers.
6. THE CTMS_Frontend SHALL document unresolved API assumptions in typed contract tests or explicit implementation notes before a phase is considered complete.

## Assumptions and Clarifications Needed

1. The API is assumed to expose the `/api/v1/ctms` contracts described in the existing CTMS integration design, including typed pagination, baseline errors, request identifiers, capabilities, mutation responses, attachment metadata, export jobs, and sanitized coordination records.
2. The frontend can rely on server-returned capability codes and allowed transition/policy choices; the exact capability-code catalog and phase-to-route matrix still need confirmation from the backend contract.
3. The existing flat frontend permission list is assumed to remain a convenience projection of server roles; study/site scope remains server-enforced unless the auth payload is expanded.
4. Offline mutation behavior is intentionally left as an API/client contract decision: the preferred default is to block non-idempotent mutations while offline and clearly explain why, unless an approved durable outbox contract is provided.
5. Attachment size/type limits, export formats, retention/expiry behavior, report filter dimensions, projection freshness thresholds, and conflict policy schemas require backend confirmation before implementation.
6. The existing `ctms-integration` requirements/design remain the source of truth for ownership, projection minimization, server authorization, coordination, and clinical non-mutation boundaries.
