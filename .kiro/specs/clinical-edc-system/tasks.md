# Implementation Plan: Clinical EDC System

## Overview

This plan converts the current design into incremental coding and testing tasks, preserving the completed EDC clinical delivery phases while adding the revised unified-platform boundary work from Requirement 32. Phase 1 ships the auditable EDC MVP (auth, authorization, canonical clinical Study/Site/Subject setup, eCRF metadata + data capture, immutable audit, manual queries, CSV export) with authorization scope, audit immutability, and clinical ownership independently verified. Phase 2 adds the EDC edit-check engine, repeating records, SDV, review, freeze/lock, Clinical_Attachments, and clinical notifications. Phase 3 adds EDC electronic signatures, published-version amendments, advanced clinical exports, and the optional AI assistant. A cross-cutting boundary phase adds EDC-side canonical identity guards, ownership enforcement, minimized read-only CTMS projections, explicit coordination validation, shared module-owner discrimination, request/correlation propagation, boundary tests, and EDC resilience when CTMS is disabled or unavailable.

Implementation follows the design's layering throughout: thin routes → services (transaction boundary) → repositories; the EDC Audit_Service writes an append-only, module-owned Audit_Event in the **same transaction** as every EDC clinical/config mutation; the Permission_Service enforces route- and object-level access on every protected endpoint; canonical identity and authoritative-module guards reject cross-module writes; deletions are soft only; edit checks are safe declarative DSL (no arbitrary code); all DB timestamps are UTC; the API is versioned under `/api/v1` with generated OpenAPI. Shared audit, notification, file, and export primitives carry explicit module-owner discriminators, while EDC consumes only approved minimized read-only CTMS projections and never owns CTMS operational records.

Property-based tests (Hypothesis) cover all 44 correctness properties, each as an optional (`*`) sub-task tagged `# Feature: clinical-edc-system, Property {n}: ...` and run at 100+ iterations, placed next to the feature it protects. Optional (`*`) sub-tasks are not required for a working build and may be skipped for a faster MVP. The new boundary properties 38–44 use deterministic EDC/CTMS fakes and repository-level isolation tests; EDC tasks implement only shared primitives, EDC-side guards/consumers, and rejection/resilience behavior, while CTMS operational ownership remains in the separate CTMS task plan.

---

## Tasks

### Phase 1 — MVP (Requirements 1, 2, 3, 4, 6, 7, 8, 9, 10, 13 manual, 18, 19 CSV, 21, 22, 23, 24, 25, 26, 30, 32 boundary prerequisites)

- [x] 1. Project bootstrap
  - [x] 1.1 Scaffold the backend project
    - Create FastAPI app factory in `app/main.py` mounting the router under `/api/v1`; set up `pyproject.toml` with FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, pytest, Hypothesis, and `[tool.ruff]` lint/format
    - Implement `core/config.py` (per-Environment Pydantic settings) and `core/database.py` (engine, session, unit-of-work / transaction scope); initialize Alembic; add `.env.example`
    - _Requirements: 21.1, 22.1, 23.2, 25.1_
  - [x] 1.2 Scaffold the frontend project
    - Create Vite + React + TypeScript SPA with Tailwind CSS, shadcn/ui, TanStack Query/Router/Table, Zustand, React Hook Form + Zod; add `lib/api.ts`, `lib/auth.ts`, `lib/permissions.ts`
    - Establish the feature-based folder structure from the design
    - _Requirements: 24.1, 24.2_

- [x] 2. Core API foundation and cross-cutting infrastructure
  - [x] 2.1 Implement request-id middleware, request context, and structured logging
    - Add middleware that assigns a request identifier at ingress, binds it (and actor) to `core/request_context.py` contextvars, returns it as `X-Request-ID`, and correlates every structured log line by it
    - _Requirements: 21.5, 30.4_
  - [x] 2.2 Implement the standard error envelope and exception mapping
    - Add `core/exceptions.py` domain exceptions and a single handler mapping them to the `{error:{code,message,details}}` envelope per the design's Exception→HTTP table, suppressing internal DB/stack details
    - _Requirements: 21.3_
  - [x] 2.3 Implement the pagination envelope and base schemas
    - Add a reusable `{items, page, page_size, total}` paginator and base list dependencies
    - _Requirements: 21.2, 29.2_
  - [x] 2.4 Implement health, readiness, and metrics endpoints
    - Add `GET /health/live`, `GET /health/ready`, `GET /metrics`; register metrics for API latency, error rate, DB connections, worker/export/auth failures
    - _Requirements: 30.1, 30.2, 30.3, 30.5_
  - [x] 2.5 Write property test for the pagination envelope
    - **Property 32: Pagination envelope is well-formed**
    - **Validates: Requirements 21.2, 29.2**
  - [x] 2.6 Write property test for the error envelope
    - **Property 33: Error envelope is standard and leak-free**
    - **Validates: Requirements 21.3**

- [x] 3. Append-only audit foundation (brought forward)
  - [x] 3.1 Create the audit_events model, migration, and database-level immutability guard
    - Define `audit_events` with actor, timestamp (UTC server clock), entity type/id, study, site, subject, action, field, old/new value, reason, request_id, ip/user-agent; add indexes
    - Revoke UPDATE/DELETE on `audit_events` from the application role and add a trigger that raises on UPDATE/DELETE
    - _Requirements: 18.1, 18.2, 22.4, 22.6, 25.2_
  - [x] 3.2 Implement Audit_Service bound to the active transaction
    - Add `core/audit.py` + `Audit_Service.record(event)` that writes within the caller's transaction using the request context; implement `search(filters)` and `export(selection)`
    - _Requirements: 18.1, 18.3, 18.5, 18.6, 21.4_
  - [x] 3.3 Write property test for audit immutability
    - **Property 18: The audit trail is immutable**
    - **Validates: Requirements 18.2**
  - [x] 3.4 Write property test for request-id propagation
    - **Property 19: Request identifier is returned and propagated**
    - **Validates: Requirements 21.5, 30.4**
  - [x] 3.5 Write property test for audit search filters
    - **Property 20: Audit search matches its filters**
    - **Validates: Requirements 18.5**

- [x] 4. Authentication (Auth_Service)
  - [x] 4.1 Create identity models and migration
    - Define `users`, `roles`, `permissions`, `role_permissions`, `user_roles` (with study/site scope columns), and `invitations`; add indexes
    - _Requirements: 3.1, 3.3, 22.6_
  - [x] 4.2 Implement security primitives
    - Add `core/security.py`: local JWT issue/verify, password hashing + reset tokens, optional Cognito/OIDC token validation, re-authentication, MFA verification, and inactivity/last-activity handling
    - _Requirements: 1.1, 1.2, 1.7, 1.8, 1.9, 3.5_
  - [x] 4.3 Implement Auth_Service
    - `login` (active + MFA + valid credentials), `refresh`, `logout` (revoke refresh token), `me` (identity + resolved scope), `request_password_reset` / `reset_password` (single-use), `validate_external_token`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 1.9, 3.5_
  - [x] 4.4 Implement auth routes and the current-user dependency
    - Add `auth.py` routes and a `get_current_user` dependency that normalizes local/Cognito tokens to an internal User + session
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 21.1_
  - [x] 4.5 Write property test for token issuance
    - **Property 4: Authentication issues tokens only for valid, active, MFA-satisfied credentials**
    - **Validates: Requirements 1.1, 1.2, 1.9, 3.5**
  - [x] 4.6 Write property test for session round-trip and revocation
    - **Property 5: Session token round-trip and revocation**
    - **Validates: Requirements 1.3, 1.4, 1.6, 1.8**

- [x] 5. Authorization (Permission_Service)
  - [x] 5.1 Define permission codes and the role-capability map with seeding
    - Add `core/permissions.py` with stable permission codes and the role→capability map (System Admin, Study Admin, Data Manager, CRA, PI, Site Coordinator, Medical Reviewer, Sponsor Viewer read-only); add a seeding routine
    - _Requirements: 2.1, 3.3, 3.6_
  - [x] 5.2 Implement Permission_Service scope resolution and enforcement
    - `resolve_scope`, `require`, `filter_studies`/`filter_sites`, `assert_object_access` (route- and object-level by study/site scope)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 23.4_
  - [x] 5.3 Implement permission guard dependencies
    - Add `api/deps.py` guards that resolve the Authorization_Scope and enforce `require` before any protected handler delegates
    - _Requirements: 2.2, 2.3, 23.1, 23.4_
  - [x] 5.4 Write property test for scope resolution
    - **Property 1: Authorization scope is the union of role grants**
    - **Validates: Requirements 2.1**
  - [x] 5.5 Write property test for access enforcement
    - **Property 2: Access is permitted if and only if in scope**
    - **Validates: Requirements 2.2, 2.3, 2.5, 3.5, 3.6, 23.4, 26.4**
  - [x] 5.6 Write property test for scope-filtered listings
    - **Property 3: Listing and aggregation are scope-filtered**
    - **Validates: Requirements 2.4, 4.4, 6.3, 20.1, 20.2, 20.3, 20.4, 28.5, 31.3**

- [x] 6. User, Role, and Invitation management
  - [x] 6.1 Implement user/role/invitation schemas and repository
    - Pydantic schemas and a repository for users, roles, invitations, and assignments
    - _Requirements: 3.1, 3.3_
  - [x] 6.2 Implement UserService
    - `invite` (pending user + single-use token), `accept_invitation` (activate + apply roles at scope), `deactivate` (soft, revoke sessions, retain record), `assign_roles`; write Audit_Events
    - _Requirements: 3.1, 3.2, 3.4, 3.5_
  - [x] 6.3 Implement users/roles/permissions routes
    - `GET/POST /users`, `GET/PATCH /users/{id}`, `POST /users/{id}/deactivate`, `GET/POST /roles`, `GET /permissions`, `POST /studies/{id}/users/{uid}/assign`, `POST /auth/invite/accept`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 21.1_
  - [x] 6.4 Write property test for the invitation lifecycle
    - **Property 6: Invitation lifecycle round-trip**
    - **Validates: Requirements 3.1, 3.2**

- [x] 7. Study and Study-Version foundation
  - [x] 7.1 Create studies and study_versions models and migration
    - Define `studies` (study_code globally unique) and `study_versions` (unique version per study); add indexes
    - _Requirements: 4.1, 4.2, 5.1, 5.5, 22.1, 22.5, 22.6_
  - [x] 7.2 Implement Study_Service
    - `create_study` (unique code, audit), `transition_status` (Draft→UAT→Active→Enrollment Closed→Locked→Archived); reject illegal transitions
    - _Requirements: 4.1, 4.2, 4.3, 4.5_
  - [x] 7.3 Implement Study_Version publish and immutability guard
    - `publish` (draft→published, record actor/timestamp) and `guard_mutable` blocking writes to a published version and its children; expose for Form/Visit/EditCheck services
    - _Requirements: 5.1, 5.2_
  - [x] 7.4 Implement studies and versions routes
    - `GET/POST /studies`, `GET/PATCH/DELETE /studies/{id}`, `POST /studies/{id}/publish|archive`, `GET/POST /studies/{id}/versions`, `POST /versions/{id}/publish`
    - _Requirements: 4.1, 4.3, 5.1, 21.1_

- [x] 8. Site management
  - [x] 8.1 Create sites and study_site_users models and migration
    - Define `sites` (site_number unique within study) and `study_site_users`; add indexes
    - _Requirements: 6.1, 6.2, 6.5, 22.5, 22.6_
  - [x] 8.2 Implement Site_Service
    - `create_site` (unique number, audit), `deactivate_site` (retain record), `assign_user`
    - _Requirements: 6.1, 6.2, 6.4, 6.5_
  - [x] 8.3 Implement sites routes
    - `GET/POST /studies/{id}/sites`, `GET/PATCH/DELETE /sites/{id}`
    - _Requirements: 6.1, 6.4, 6.5, 21.1_

- [x] 9. Subject management
  - [x] 9.1 Create subjects model and migration
    - Define `subjects` (subject_number unique within study, bound study_version_id); add filter indexes (study, site, status)
    - _Requirements: 7.1, 7.2, 22.5, 22.6_
  - [x] 9.2 Implement Subject_Service
    - `create_subject` (bind published version, generate id by configured rule), `transition_status` (subject state machine, audit), `get_casebook`, soft-delete; write Audit_Events
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 22.2_
  - [x] 9.3 Implement subjects routes
    - `GET/POST /studies/{id}/subjects`, `GET/PATCH /subjects/{id}`, `POST /subjects/{id}/screen-fail|randomize|terminate`, `GET /subjects/{id}/casebook`
    - _Requirements: 7.1, 7.3, 7.5, 21.1_
  - [x] 9.4 Write property test for scoped uniqueness
    - **Property 7: Scoped uniqueness is enforced**
    - **Validates: Requirements 4.2, 6.2, 7.2, 22.5**
  - [x] 9.5 Write property test for soft-deletion retention
    - **Property 22: Soft deletion retains records**
    - **Validates: Requirements 3.4, 6.4, 22.2, 27.3**

- [x] 10. Visit schedule
  - [x] 10.1 Create visit_definitions and visit_instances models and migration
    - _Requirements: 8.1, 8.2_
  - [x] 10.2 Implement Visit_Service
    - `define_visit` (draft-only via guard_mutable), `record_visit_date` (compute before/in/after window status), `create_unscheduled`, `mark_missed`; write Audit_Events
    - _Requirements: 8.1, 8.3, 8.4, 8.5_
  - [x] 10.3 Wire Visit_Instance initialization into subject creation
    - `initialize_instances(subject)` creates Visit_Instances from the bound version's definitions
    - _Requirements: 7.4, 8.2_
  - [x] 10.4 Implement visits routes
    - `GET /subjects/{id}/visits`, `POST /subjects/{id}/visits/unscheduled`, `GET/PATCH /visits/{id}`, `POST /visits/{id}/mark-missed`
    - _Requirements: 8.1, 8.3, 8.4, 8.5, 21.1_
  - [x] 10.5 Write property test for visit window status
    - **Property 13: Visit window status is computed correctly**
    - **Validates: Requirements 8.3**
  - [x] 10.6 Write property test for record round-trip persistence
    - **Property 9: Persisted records round-trip**
    - **Validates: Requirements 4.1, 6.1, 6.5, 8.1**

- [x] 11. eCRF form metadata (Form_Metadata_Service)
  - [x] 11.1 Create form metadata models and migration
    - Define `form_definitions` (versioned via study_version_id, no form_versions table), `form_sections`, `field_definitions`, `codelists`, `codelist_items` (with normal_low/normal_high)
    - _Requirements: 9.1, 9.2, 9.5, 22.1, 22.6_
  - [x] 11.2 Implement Form_Metadata_Service
    - Draft-only CRUD/order of forms/sections/fields (guard_mutable), all control types and field attributes, code lists; write Audit_Events
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 5.2_
  - [x] 11.3 Implement standard form template seeding
    - Seed AE, CM, DM/Demographics, MH, VS, LB, EX, DS, EG, and Visit Date templates into a draft version
    - _Requirements: 9.3, 9.4_
  - [x] 11.4 Implement the shared safe expression evaluator and calculated fields
    - Server-side evaluation of declarative calculation expressions (e.g., BMI), reused later by the Edit_Check_Engine
    - _Requirements: 9.4_
  - [x] 11.5 Implement forms/fields routes
    - `GET/POST /studies/{id}/forms`, `GET/PATCH/DELETE /forms/{id}`, `POST /forms/{id}/sections|fields`, `PATCH/DELETE /fields/{id}`
    - _Requirements: 9.1, 9.2, 21.1_
  - [x] 11.6 Wire Form_Instance initialization from definitions
    - On subject/visit initialization, create Form_Instances for the bound version's form definitions
    - _Requirements: 7.4_
  - [x] 11.7 Write property test for published-version immutability
    - **Property 10: Published study versions are immutable**
    - **Validates: Requirements 5.2, 9.1, 9.2, 12.6**
  - [x] 11.8 Write property test for subject binding and instance initialization
    - **Property 12: Subject binding and instance initialization**
    - **Validates: Requirements 7.1, 7.4, 8.2**

- [x] 12. Clinical data capture (Data_Capture_Service)
  - [x] 12.1 Create form_instances and field_values models and migration
    - Hybrid storage: `form_instances.data_jsonb` plus normalized `field_values` rows; add indexes
    - _Requirements: 10.2, 22.3, 22.6_
  - [x] 12.2 Implement Data_Capture_Service
    - `load`, `save_draft` (status In Progress), `submit` (validate required/type/range/codelist/conditional; preserve values on failure), `change_value` (Reason_For_Change after submit; lock-block hook), `mark_not_applicable`; status machine (Not Started/In Progress/Submitted/Reviewed/Frozen/Locked/Signed); write Audit_Event in the same transaction, keeping data_jsonb and field_values consistent
    - _Requirements: 10.1, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 21.4, 23.3_
  - [x] 12.3 Implement form data routes
    - `GET /form-instances/{id}`, `PATCH /form-instances/{id}/data`, `POST /form-instances/{id}/save|submit|reopen`, `GET /form-instances/{id}/audit`
    - _Requirements: 10.1, 10.3, 10.5, 21.1_
  - [x] 12.4 Write property test for draft save
    - **Property 14: Draft save persists values and sets In Progress**
    - **Validates: Requirements 10.1, 10.6**
  - [x] 12.5 Write property test for submission validation
    - **Property 15: Submission validates atomically and preserves data on failure**
    - **Validates: Requirements 10.3, 10.4**
  - [x] 12.6 Write property test for post-submission reason
    - **Property 16: Post-submission changes require a reason**
    - **Validates: Requirements 10.5, 18.3**
  - [x] 12.7 Write property test for audit atomicity
    - **Property 17: Clinical mutations write an atomic, complete Audit_Event**
    - **Validates: Requirements 4.5, 7.6, 9.6, 10.8, 11.2, 13.7, 14.4, 15.4, 16.5, 17.4, 18.1, 21.4, 22.4, 25.2, 31.5**
  - [x] 12.8 Write property test for hybrid storage consistency
    - **Property 31: Hybrid storage stays consistent**
    - **Validates: Requirements 22.3**

- [x] 13. Manual queries (Query_Service)
  - [x] 13.1 Create queries and query_messages models and migration
    - Exactly-one affected-object target; append-only thread; indexes
    - _Requirements: 13.1, 13.6, 22.6_
  - [x] 13.2 Implement Query_Service
    - `create_query` (manual; one affected object), `respond`, `close`, `reopen`, `cancel` (status machine Open/Answered/Closed/Reopened/Cancelled), threaded history; write Audit_Events
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_
  - [x] 13.3 Implement queries routes
    - `GET/POST /queries`, `GET /queries/{id}`, `POST /queries/{id}/respond|close|reopen|cancel`, `GET /queries/{id}/history`
    - _Requirements: 13.1, 13.3, 13.4, 13.5, 21.1_
  - [x] 13.4 Write property test for query linkage and thread ordering
    - **Property 26: A query is linked to exactly one affected object with an ordered, append-only thread**
    - **Validates: Requirements 13.1, 13.6**

- [x] 14. CSV export (Export_Service)
  - [x] 14.1 Create exports model and implement Export_Service job lifecycle
    - `exports` table; `create_export` (status Queued→Running→Completed/Failed), `subject_list_export`, filter parsing
    - _Requirements: 19.1, 19.2, 19.3_
  - [x] 14.2 Implement the CSV export worker
    - Async job that applies filters (study/site/subject/visit/form/domain/date range/changed-since/locked-only/clean-only), generates CSV, stores it, and audits downloads
    - _Requirements: 19.1, 19.3, 19.4, 19.5, 29.3_
  - [x] 14.3 Implement exports routes
    - `GET/POST /studies/{id}/exports`, `GET /exports/{id}`, `GET /exports/{id}/download`
    - _Requirements: 19.1, 19.4, 21.1_
  - [x] 14.4 Write property test for status-machine transitions
    - **Property 8: Only legal status transitions are accepted**
    - **Validates: Requirements 4.3, 5.1, 7.3, 13.2, 13.3, 13.4, 13.5, 19.1**
  - [x] 14.5 Write property test for export filtering and fidelity (CSV)
    - **Property 34: Export filtering and content fidelity**
    - **Validates: Requirements 18.4, 19.3, 19.4, 19.5**

- [x] 15. Audit viewer and core Dashboard_Service
  - [x] 15.1 Implement Dashboard_Service (core)
    - `study_dashboard`, `site_dashboard`, `query_metrics` computed strictly within the caller's Authorization_Scope (read-only)
    - _Requirements: 4.4, 6.3, 20.1, 20.2, 20.3, 20.4_
  - [x] 15.2 Implement audit and dashboards routes
    - `GET /audit-events`, `GET /subjects/{id}/audit`, `GET /form-instances/{id}/audit`, `GET /fields/{id}/audit`, audit export, `GET /studies/{id}/dashboard`, `GET /sites/{id}/dashboard`, `GET /studies/{id}/query-metrics`
    - _Requirements: 18.5, 18.6, 20.1, 20.2, 20.3, 21.1_

- [x] 16. Frontend foundations, auth/permission UI, and Phase 1 clinical UI
  - [x] 16.1 Build authentication UI
    - Login, forgot-password, reset-password, accept-invitation pages; token/session handling and inactivity logout
    - _Requirements: 1.1, 1.6, 3.2, 24.2_
  - [x] 16.2 Build permission-aware routing and app shell
    - PermissionGuard, access-denied view, StudySelector/SiteSelector, app shell and navigation (frontend checks are convenience only)
    - _Requirements: 2.6, 24.1, 24.6_
  - [x] 16.3 Build clinical status components and subject/casebook views
    - Status badges (subject/form/query/SDV/review/lock/signature), ClinicalDataTable, subject list, subject casebook
    - _Requirements: 24.1_
  - [x] 16.4 Build the form data-entry page
    - RHF + Zod validation, required-missing highlighting, Reason_For_Change dialog on post-submit edits, save/submit/reopen, audit and query side panels
    - _Requirements: 24.2, 24.3, 24.5_
  - [x] 16.5 Build study/site/subject/user management, dashboards, audit viewer, and export center
    - _Requirements: 4.1, 6.1, 7.1, 20.1, 24.1_
  - [x] 16.6 Write frontend component, route, and form tests
    - Status rendering snapshots, guarded-route hide/deny, Zod validation, Reason_For_Change dialog
    - _Requirements: 24.1, 24.2, 24.3, 24.6_

- [x] 17. Phase 1 end-to-end and compliance/validation testing
  - [x] 17.1 Write the Phase 1 Playwright end-to-end flow
    - login → create subject → enter data → submit → create/answer query → CSV export
    - _Requirements: 26.1_
  - [x] 17.2 Write the compliance and validation suite
    - 21 CFR Part 11 / ALCOA+ (audit completeness/immutability, Reason_For_Change), environment-separation smoke tests, UTC clock derivation; independent verification of scope enforcement and audit immutability
    - _Requirements: 25.1, 25.2, 25.5, 25.6, 26.4_

- [x] 18. Checkpoint — Phase 1 MVP
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 2 — Validation, SDV, Review, Lock, Files, Notifications (Requirements 5 draft, 11, 12, 14, 15, 16, 20, 27, 28)

- [x] 19. Edit_Check_Engine
  - [x] 19.1 Create edit_checks and validation_results models and migration
    - Versioned with owning study version
    - _Requirements: 12.1, 12.6, 22.6_
  - [x] 19.2 Implement the safe JSON DSL parser, schema validator, and evaluator
    - Boolean trees over conditions with the fixed operator set; validate against schema before persisting; never execute user-provided code; reuse the shared safe expression evaluator
    - _Requirements: 12.1, 12.2, 12.7_
  - [x] 19.3 Implement runtime evaluation, severities, lab pseudo-fields, and test-without-persist
    - Severities info/warning/error/query; `<field>.normal_low/high` pseudo-fields; `test(rule, sample_data)` without writing clinical data; on query-severity match, request Query_Service to create a linked system Query
    - _Requirements: 12.3, 12.4, 12.5_
  - [x] 19.4 Seed example edit checks
    - AE start ≤ end; consent date ≤ first procedure; AE Serious=Yes ⇒ seriousness criteria; AE Outcome=Fatal ⇒ death date; visit date within window else warning
    - _Requirements: 12.2_
  - [x] 19.5 Implement edit-checks routes
    - `GET/POST /studies/{id}/edit-checks`, `GET/PATCH /edit-checks/{id}`, `POST /edit-checks/{id}/test`, `POST /studies/{id}/edit-checks/run`
    - _Requirements: 12.1, 12.4, 12.5, 21.1_
  - [x] 19.6 Write property test for DSL round-trip and safe evaluation
    - **Property 23: Edit-check rule serialization round-trip and safe evaluation**
    - **Validates: Requirements 12.1, 12.7**
  - [x] 19.7 Write property test for test-without-persist
    - **Property 24: Edit-check test does not persist clinical data**
    - **Validates: Requirements 12.4**
  - [x] 19.8 Write property test for system-query generation
    - **Property 25: Query-severity checks generate a linked system query**
    - **Validates: Requirements 12.5**

- [x] 20. Repeating records (Repeating_Record_Service)
  - [x] 20.1 Create form_records model and migration
    - Sequence number and soft-delete columns (deleted_at/by/reason)
    - _Requirements: 11.1, 11.3, 22.2, 22.6_
  - [x] 20.2 Implement Repeating_Record_Service
    - `add_record` (monotonic sequence), `edit_record`, `soft_delete` (actor/timestamp/reason, retain), `restore`; write Audit_Events
    - _Requirements: 11.1, 11.2, 11.3, 11.4_
  - [x] 20.3 Implement records routes
    - `POST /form-instances/{id}/records`, `PATCH/DELETE /records/{id}`, `POST /records/{id}/restore`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 21.1_
  - [x] 20.4 Write property test for repeating records
    - **Property 21: Repeating-record sequence is monotonic and soft-delete round-trips**
    - **Validates: Requirements 11.1, 11.3, 11.4**

- [x] 21. Source data verification (SDV_Service)
  - [x] 21.1 Create sdv_status model and migration
    - _Requirements: 14.1, 22.6_
  - [x] 21.2 Implement SDV_Service
    - `set_sdv`/`clear_sdv` at field/form/visit/subject scope (actor/timestamp), `progress` counts; write Audit_Events
    - _Requirements: 14.1, 14.2, 14.3, 14.4_
  - [x] 21.3 Implement SDV routes
    - `POST /fields/{id}/sdv|unsdv`, `POST /form-instances/{id}/sdv|unsdv`, `GET /studies/{id}/sdv-progress`
    - _Requirements: 14.1, 14.2, 14.3, 21.1_

- [x] 22. Clinical review (Review_Service)
  - [x] 22.1 Create review_status model and migration
    - _Requirements: 15.1, 22.6_
  - [x] 22.2 Implement Review_Service
    - `mark_reviewed`/`clear_review` (actor/timestamp), `progress` counts; write Audit_Events
    - _Requirements: 15.1, 15.2, 15.3, 15.4_
  - [x] 22.3 Implement review routes
    - `POST /form-instances/{id}/review|unreview`, `GET /studies/{id}/review-progress`
    - _Requirements: 15.1, 15.2, 15.3, 21.1_
  - [x] 22.4 Write property test for SDV and review toggles
    - **Property 27: SDV and review toggles round-trip and counts are accurate**
    - **Validates: Requirements 14.1, 14.2, 14.3, 15.1, 15.2, 15.3**

- [x] 23. Freeze, lock, and unlock (Lock_Service)
  - [x] 23.1 Create freezes and locks models and migration
    - Unlock reason recorded; indexes on (object_type, object_id)
    - _Requirements: 16.1, 16.2, 16.4, 22.6_
  - [x] 23.2 Implement Lock_Service
    - `freeze`/`lock`, `unlock` (reason required), `is_modification_blocked` (field or any ancestor frozen/locked across field→form→visit→subject→site→study); write Audit_Events
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_
  - [x] 23.3 Wire lock checks into mutation paths
    - Replace the Phase 1 lock hook in Data_Capture_Service with `Lock_Service.is_modification_blocked`; prepare the File_Attachment_Service block check
    - _Requirements: 10.7, 16.3, 27.5_
  - [x] 23.4 Implement freeze/lock routes
    - `POST /form-instances/{id}/freeze|unfreeze|lock|unlock`, `POST /subjects/{id}/freeze|lock`, `POST /studies/{id}/lock`
    - _Requirements: 16.1, 16.2, 16.4, 21.1_
  - [x] 23.5 Write property test for ancestor lock blocking
    - **Property 28: Modification is blocked under any frozen or locked ancestor**
    - **Validates: Requirements 10.7, 16.1, 16.2, 16.3, 27.5**
  - [x] 23.6 Write property test for unlock reason
    - **Property 29: Unlock requires a reason and clears the lock**
    - **Validates: Requirements 16.4**

- [x] 24. File attachments (File_Attachment_Service)
  - [x] 24.1 Create file_attachments model and migration
    - Storage key, metadata, soft-delete columns
    - _Requirements: 27.1, 27.3, 22.6_
  - [x] 24.2 Implement File_Attachment_Service
    - `upload` (reject when parent frozen/locked), `download` (only with parent read access), `soft_delete`; write Audit_Events for upload/download/deletion
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 18.4_
  - [x] 24.3 Implement files routes
    - `POST /objects/{type}/{id}/files`, `GET /files/{id}/download`, `DELETE /files/{id}`
    - _Requirements: 27.1, 27.2, 27.3, 21.1_
  - [x] 24.4 Write property test for file download access
    - **Property 35: File download requires parent read access**
    - **Validates: Requirements 27.1, 27.2**

- [x] 25. Notifications (Notification_Service)
  - [x] 25.1 Create notifications model and migration
    - _Requirements: 28.4, 22.6_
  - [x] 25.2 Implement Notification_Service and event wiring
    - `on_query_assigned`, `on_form_submitted`, `on_export_completed`, statuses Unread/Read/Archived, `list_unread`; wire into Query/Data-capture/Export flows
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5_
  - [x] 25.3 Implement notifications routes
    - `GET /notifications`, `POST /notifications/{id}/read|archive`
    - _Requirements: 28.4, 28.5, 21.1_
  - [x] 25.4 Write property test for workflow notifications
    - **Property 36: Workflow events create notifications for the right recipients**
    - **Validates: Requirements 28.1, 28.2, 28.3**

- [x] 26. Full Dashboard and data-cleaning frontend
  - [x] 26.1 Build Phase 2 frontend views
    - Edit-check builder, query inbox/detail, SDV worklist, clinical review worklist, freeze/lock controls (disabled inputs when frozen/locked), file upload, notifications UI, and full data-cleaning dashboards
    - _Requirements: 24.1, 24.4, 20.1, 20.2, 20.3_
  - [x] 26.2 Write frontend tests for Phase 2 workflows
    - Query thread, frozen/locked disabling, SDV/review actions
    - _Requirements: 24.1, 24.4_

- [x] 27. Checkpoint — Phase 2
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 3 — Signatures, Amendments, Advanced Exports, AI (Requirements 5 amendments, 17, 19 advanced, 31)

- [x] 28. Electronic signatures (Signature_Service)
  - [x] 28.1 Create signatures model and migration
    - Signer identity, timestamp, meaning, signed-object reference, data hash, valid/stale status, stale reason
    - _Requirements: 17.2, 22.6_
  - [x] 28.2 Implement Signature_Service
    - `sign` (require re-authentication; persist identity/timestamp/meaning/reference/data hash), `invalidate_if_changed` (mark stale + reason); wire into Data_Capture post-signature changes; write Audit_Events
    - _Requirements: 17.1, 17.2, 17.3, 17.4_
  - [x] 28.3 Implement signatures routes and UI
    - `POST /form-instances/{id}/sign`, `POST /subjects/{id}/sign`, `GET /subjects/{id}/signatures`; signature UI with re-auth
    - _Requirements: 17.1, 17.2, 21.1, 24.1_
  - [x] 28.4 Write property test for signatures
    - **Property 30: Signatures require re-authentication and bind to signed data**
    - **Validates: Requirements 17.1, 17.2, 17.3**

- [x] 29. Study-version amendments and immutability completion
  - [x] 29.1 Implement amendment creation and prior-version retention
    - `create_amendment` (new draft + amendment reason), retain all prior published versions, each form bound to exactly one version; add `POST /studies/{id}/amend`
    - _Requirements: 5.3, 5.4, 5.5_
  - [x] 29.2 Build the amendment/versioning frontend
    - Study configuration versioning and amendment workflow
    - _Requirements: 5.3, 24.1_
  - [x] 29.3 Write property test for amendments
    - **Property 11: Amendment preserves prior versions and binds forms to one version**
    - **Validates: Requirements 5.3, 5.4, 5.5**

- [x] 30. Advanced export formats
  - [x] 30.1 Implement Excel, JSON, SAS XPT, and ODM XML generation
    - Extend the export worker with advanced formats and the changed-since/locked-only/clean-only filters
    - _Requirements: 19.3, 19.5_
  - [x] 30.2 Write advanced export fidelity tests
    - JSON/ODM round-trip and Excel/XPT generation, extending Property 34 coverage
    - _Requirements: 19.5_

- [x] 31. Optional AI assistant (AI_Assistant_Service)
  - [x] 31.1 Implement AI endpoints with streaming
    - Chat, edit-check drafting, and query summarization backed by Bedrock AgentCore; stream via SSE or WebSocket
    - _Requirements: 31.1, 31.2_
  - [x] 31.2 Implement scoped context and human-confirmation gating
    - `build_context` restricts context to the requesting User's Authorization_Scope; `apply_suggestion` requires explicit human confirmation before any data change; audit AI-assisted regulated changes
    - _Requirements: 31.3, 31.4, 31.5_
  - [x] 31.3 Implement AI routes and UI
    - `POST /ai/chat`, `POST /ai/edit-check-draft`, `POST /ai/query-summary` (SSE/WS); assistant UI
    - _Requirements: 31.1, 31.2, 21.1_
  - [x] 31.4 Write property test for AI confirmation
    - **Property 37: AI data changes require human confirmation**
    - **Validates: Requirements 31.4**

- [x] 32. Checkpoint — Phase 3
  - Ensure all tests pass, ask the user if questions arise.

### Cross-cutting boundary completion — Unified platform EDC side (Requirement 32 and revised cross-cutting controls)

These tasks extend the completed EDC phases with the current unified-platform boundary. They implement only EDC-owned behavior, shared primitives, EDC-side consumers/guards, and rejection/resilience tests. CTMS operational study/site/enrollment/monitoring/work-management behavior, operational dashboards/reports, operational exports, and Operational_Attachments remain in the separate CTMS task plan.

- [ ] 33. Harden EDC ownership, coordination, and CTMS isolation
  - [ ] 33.1 Implement canonical identity and authoritative-module guard contracts
    - Add typed identity/ownership policies and repository/service guards that resolve one stable canonical Study, Site, Subject, and Visit_Instance identifier, reject duplicate or ambiguous ownership, and prevent EDC services from accepting CTMS-owned operational fields
    - _Requirements: 4.1, 4.2, 6.1, 6.2, 7.1, 7.2, 8.1, 32.1, 32.2_

  - [ ] 33.2 Add explicit module-owner discriminators and persistence constraints to shared primitives
    - Extend audit events, notifications, clinical file attachments, and clinical export jobs with an EDC/CTMS owner discriminator; add migrations, model constraints, repository filters, and route validation that keep EDC clinical content separate from CTMS operational content without creating CTMS-owned records
    - _Requirements: 18.1, 18.7, 19.6, 19.7, 27.1, 27.6, 28.4, 28.6, 32.7_

  - [ ] 33.3 Implement request and correlation propagation for EDC coordination
    - Propagate request ID, correlation ID, source module, source identifier, source version, rule version, and idempotency key through request context, structured logs, Audit_Events, Coordination_Events, projection records, and sanitized failures
    - _Requirements: 21.5, 30.4, 32.4, 32.5_

  - [ ] 33.4 Implement the EDC-side minimized CTMS projection consumer
    - Validate approved allowlisted projection schemas, source metadata, authorization scope, and freshness/order; persist or serve projections as read-only, CTMS-sourced views and prevent projected fields from changing EDC clinical metrics, status, or source records
    - _Requirements: 4.6, 6.7, 7.8, 20.5, 20.6, 32.4, 32.7_

  - [ ] 33.5 Implement explicit coordinated-transition validation and sanitized conflict handling
    - Add a validator that permits a cross-module status change only when an active ownership rule names the source, target field, transition, authorization, identity, version, and allowlist; reject stale, unauthorized, ambiguous, or prohibited events before mutation and retain only sanitized conflict/failure metadata
    - _Requirements: 21.3, 21.6, 23.4, 32.4, 32.5, 32.6_

  - [ ] 33.6 Enforce CTMS route rejection for EDC-owned mutations
    - Add shared route/dependency and service-level guards that reject CTMS attempts to create or mutate Study_Version, Clinical_Subject_Registry, Visit_Instance, Form_Instance, Field_Value, Query lifecycle/messages, SDV, review, freeze/lock, signatures, Clinical_Attachments, or clinical exports before either module's authoritative state or audit state changes
    - _Requirements: 8.6, 18.7, 19.6, 19.7, 21.6, 23.4, 27.6, 32.3_

  - [ ] 33.7 Implement EDC resilience when CTMS is disabled, empty, or unavailable
    - Make EDC authentication, capture, audit, protocol visits, clinical lifecycle, and clinical exports operate from EDC-owned state without a CTMS dependency; keep accepted coordination events durable/pending and return explicit non-authoritative projection-unavailable results
    - _Requirements: 26.1, 26.5, 30.1, 30.2, 32.8_

  - [ ]* 33.8 Write boundary, security, ownership, and integration regression tests
    - Test canonical identity stability, direct CTMS mutation rejection with no partial state or audit writes, projection minimization/read-only behavior, coordinated-transition validation, module-owner separation, request/correlation propagation, sanitized errors, and EDC operation while CTMS is disabled or unavailable
    - _Requirements: 21.3, 21.5, 26.4, 26.5, 32.1, 32.2, 32.3, 32.4, 32.5, 32.6, 32.7, 32.8_

  - [ ]* 33.9 Write property test for canonical identity ownership
    - **Property 38: Canonical identity has one authoritative owner**
    - **Validates: Requirements 4.1, 4.2, 6.1, 6.2, 7.1, 7.2, 7.7, 7.8, 7.9, 8.6, 32.1, 32.2, 32.3**

  - [ ]* 33.10 Write property test for CTMS non-mutation of EDC clinical state
    - **Property 39: CTMS operational writes cannot mutate EDC clinical state**
    - **Validates: Requirements 32.3**

  - [ ]* 33.11 Write property test for protocol-visit and monitoring separation
    - **Property 40: Protocol visits and monitoring activities remain separate**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 16.3, 32.3**

  - [ ]* 33.12 Write property test for minimized read-only projections
    - **Property 41: Cross-module projections are minimized and read-only**
    - **Validates: Requirements 4.6, 6.7, 7.8, 20.5, 21.5, 32.4, 32.6**

  - [ ]* 33.13 Write property test for coordination idempotency and policy checks
    - **Property 42: Coordination is idempotent, ordered, and policy-checked**
    - **Validates: Requirements 21.3, 21.5, 23.3, 23.4, 25.1, 25.5, 30.4, 32.4, 32.5**

  - [ ]* 33.14 Write property test for EDC resilience without CTMS
    - **Property 43: EDC remains functional without CTMS**
    - **Validates: Requirements 26.1, 26.4, 26.5, 30.1, 30.2, 30.3, 30.5, 32.8**

  - [ ]* 33.15 Write property test for clinical and operational content separation
    - **Property 44: Clinical and operational content remain separated**
    - **Validates: Requirements 18.5, 18.6, 18.7, 19.6, 19.7, 20.4, 20.5, 20.6, 27.1, 27.2, 27.3, 27.4, 27.6, 28.6, 32.4, 32.7**

- [ ] 34. Boundary completion checkpoint
  - Ensure all boundary implementation and regression tests pass, verify no EDC task claims CTMS operational ownership, and ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (property/unit/integration/e2e/compliance tests) and can be skipped for a faster MVP; core implementation tasks are never optional.
- All 44 design correctness properties are covered by exactly one Hypothesis property-test sub-task, tagged `# Feature: clinical-edc-system, Property {n}: ...` and run at 100+ iterations, placed next to the feature it protects. Properties 38–44 cover the unified EDC/CTMS boundary using deterministic fakes and repository isolation; they do not implement CTMS operational workflows.
- The audit foundation is built in Phase 1 (Task 3) and audit atomicity (Property 17) is verified with data capture; immutability and request-id propagation (Properties 18, 19) with the audit foundation; authorization (Properties 1–3) with access control; lock-ancestor enforcement (Property 28) with freeze/lock; canonical identity, ownership, projections, coordination, resilience, and clinical/operational separation (Properties 38–44) with the cross-cutting boundary tasks.
- Every task follows thin routes → services → repositories, writes EDC audit in the same transaction as EDC clinical/config changes, enforces permissions and ownership before mutating, uses soft deletion, and stores UTC timestamps. Shared primitives use explicit module-owner discrimination; EDC tasks do not create or mutate CTMS operational study/site/enrollment/monitoring/work-management records, operational dashboards/reports, operational exports, or Operational_Attachments.
- Boundary tests verify CTMS mutation attempts are rejected before either module changes, approved projections are minimized/read-only, coordination is policy-checked and idempotent, request/correlation identifiers propagate, and EDC remains functional when CTMS is disabled or unavailable.
- Checkpoints sit at phase boundaries for incremental validation.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.5", "2.6", "3.2", "4.2", "5.1"] },
    { "id": 3, "tasks": ["3.3", "3.4", "3.5", "4.3", "5.2"] },
    { "id": 4, "tasks": ["4.4", "5.3", "6.1", "7.1"] },
    { "id": 5, "tasks": ["4.5", "4.6", "5.4", "5.5", "5.6", "6.2", "7.2", "7.3", "8.1"] },
    { "id": 6, "tasks": ["6.3", "6.4", "7.4", "8.2", "9.1"] },
    { "id": 7, "tasks": ["8.3", "9.2", "10.1"] },
    { "id": 8, "tasks": ["9.3", "10.2", "11.1"] },
    { "id": 9, "tasks": ["9.4", "9.5", "10.3", "10.4", "11.2"] },
    { "id": 10, "tasks": ["10.5", "10.6", "11.3", "11.4", "11.5", "12.1"] },
    { "id": 11, "tasks": ["11.6", "11.7", "12.2"] },
    { "id": 12, "tasks": ["11.8", "12.3", "13.1"] },
    { "id": 13, "tasks": ["12.4", "12.5", "12.6", "12.7", "12.8", "13.2"] },
    { "id": 14, "tasks": ["13.3", "13.4", "14.1"] },
    { "id": 15, "tasks": ["14.2", "14.3", "15.1"] },
    { "id": 16, "tasks": ["14.4", "14.5", "15.2"] },
    { "id": 17, "tasks": ["16.1", "16.2", "16.3", "16.4", "16.5"] },
    { "id": 18, "tasks": ["16.6", "17.1", "17.2"] },
    { "id": 19, "tasks": ["19.1", "20.1", "21.1", "22.1", "23.1", "24.1", "25.1"] },
    { "id": 20, "tasks": ["19.2", "20.2", "21.2", "22.2", "23.2", "25.2"] },
    { "id": 21, "tasks": ["19.3", "20.3", "21.3", "22.3", "23.3", "23.4", "24.2", "25.3"] },
    { "id": 22, "tasks": ["19.4", "19.5", "20.4", "22.4", "23.5", "23.6", "24.3", "25.4"] },
    { "id": 23, "tasks": ["19.6", "19.7", "19.8", "24.4"] },
    { "id": 24, "tasks": ["26.1"] },
    { "id": 25, "tasks": ["26.2"] },
    { "id": 26, "tasks": ["28.1", "29.1", "30.1", "31.1"] },
    { "id": 27, "tasks": ["28.2", "29.2", "30.2", "31.2"] },
    { "id": 28, "tasks": ["28.3", "29.3", "31.3"] },
    { "id": 29, "tasks": ["28.4", "31.4"] },
    { "id": 30, "tasks": ["33.1", "33.2"] },
    { "id": 31, "tasks": ["33.3", "33.4", "33.6"] },
    { "id": 32, "tasks": ["33.5", "33.7"] },
    { "id": 33, "tasks": ["33.8"] },
    { "id": 34, "tasks": ["33.9", "33.10", "33.11", "33.12", "33.13", "33.14", "33.15"] }
  ]
}
```
