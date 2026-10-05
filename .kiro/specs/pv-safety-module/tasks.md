# Implementation Plan: PV/Safety Module

## Overview

This plan converts the `pv-safety-module` design into incremental prompts for a code-generation LLM. It implements the PV_Safety_Module as a third co-equal first-party module inside the Unified_Clinical_Platform, alongside the EDC_System and CTMS_Module. PV reuses the shared authentication, authorization, audit, request-context, notification, file-storage, export-job, observability, environment, and coordination primitives without forking them, and it owns the safety case system of record: Safety_Case intake and capture, the case lifecycle and Case_Version state machine, seriousness/causality/expectedness/severity assessments, MedDRA and WHODrug coding, Case_Narratives, regulatory reporting with expedited Regulatory_Clocks, ICSR/E2B(R3) produce/parse, EDC adverse-event reconciliation, safety notifications, the immutable PV safety audit trail, Safety_Attachments, safety exports, and safety dashboards/reports.

The implementation must preserve a hard ownership boundary. EDC remains authoritative for clinical configuration, the Clinical_Subject_Registry, protocol Visit_Instances, eCRF metadata and clinical data capture, EDC Queries, SDV, clinical review, freeze/lock, clinical Electronic_Signatures, Clinical_Attachments, and clinical exports. CTMS remains authoritative for operational study/site profiles, enrollment, monitoring, work management, operational attachments, and operational exports. PV never creates, allocates, or mutates any EDC clinical record or CTMS operational record; it references canonical Study/Site identity and the EDC Subject_Reference/Visit_Instance identity, and it consumes EDC_Adverse_Events only through an approved, minimized, read-only `Safety_Operational_Projection` delivered by the shared `Coordination_Service`. Reconciliation is one-way and read-only.

The design specifies Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL, pytest/Hypothesis, React/TypeScript/Vite, TanStack Router/Query/Table, React Hook Form/Zod, Tailwind/shadcn/ui, and deterministic in-memory fakes for property tests. Routes remain thin; PV service methods own validation and transaction boundaries; repositories do persistence; the shared Audit_Service writes exactly one immutable PV safety Audit_Event atomically with each Safety_Data or Safety_Attachment mutation, and any required coordination outbox row commits in the same transaction. All timestamps are timezone-aware UTC values with at least one-second precision, and all deletable PV records use soft deletion/archival that retains deletion actor, timestamp, and reason.

Tasks marked with `*` are optional test tasks. Property tests use Hypothesis, one test per design Correctness Property, with at least 100 generated examples and no external services, and each property task is placed close to the implementation it verifies. `compute_clock`, `is_overdue`, `produce_e2b`, `parse_e2b`, and `diff` are pure functions exercised directly by property tests. Checkpoints are planning gates only and are excluded from the dependency graph.

## Tasks

### 1. PV module scaffolding, boundaries, and persistence foundation

- [x] 1.1 Scaffold the PV backend package, frontend feature boundaries, and phase capability manifest
  - Add the `backend/app/models/pv`, `schemas/pv`, `repositories/pv`, PV service modules (`safety_case_service.py`, `assessment_service.py`, `coding_service.py`, `narrative_service.py`, `regulatory_reporting_service.py`, `reconciliation_service.py`), `backend/app/workers/pv_*` workers, the `backend/app/api/routes/pv` route package, and the `frontend/src/features/pv` area from the design package structure.
  - Add server-side phase capability metadata/feature flags so disabling PV hides PV navigation and operations without deleting PV data or altering EDC/CTMS routes.
  - Define shared PV enums and value types (`Module`, `ActorContext`, `CaseState`, `ReportStatus`, correlation identifier, idempotency key) without duplicating EDC clinical or CTMS operational models.
  - _Requirements: 1.1, 16.1, 21.1, 23.1, 23.9, 23.10_

- [x] 1.2 Create additive PV migrations and base persistence conventions
  - Add phase-gated Alembic revisions for `pv_`-prefixed tables (Phase 1: `pv_safety_cases`, `pv_adverse_event_records`, `pv_case_versions`, `pv_seriousness_assessments`, PV permission seeds) with UUID primary keys, UTC `TIMESTAMPTZ` columns, study/site scope, actor/correlation metadata, and soft-deletion/retention columns.
  - Enforce the globally unique safety case identifier and add queryable indexes for study identifier, site identifier, subject reference, case identifier, case status, report status, and creation timestamp; add partial indexes that exclude soft-deleted rows.
  - Add common SQLAlchemy mixins for UUID PK, created/updated UTC timestamps, actor/correlation, retention state, and soft deletion; add upgrade/downgrade paths and database guards preventing physical deletion of Safety_Data and Audit_Events; add no duplicate clinical/operational tables.
  - _Requirements: 3.2, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

- [x] 1.3 Implement shared request context and PV API contracts
  - Reuse request middleware to assign request and correlation identifiers, resolve authenticated actor context, return `X-Request-ID`, and propagate the identifier to services, audit events, logs, and coordination records.
  - Implement/reuse Pydantic v2 base schemas, the baseline error envelope, the pagination envelope `{items, page, page_size, total}` with page ≥ 1 and page size 1–1,000, UTC serialization, sanitized error mapping, and PV OpenAPI metadata under `/api/v1/pv`.
  - Ensure PV errors never expose stack traces, internal database errors, prohibited safety data, raw coordination payloads, or credentials.
  - _Requirements: 16.1, 16.2, 16.3, 16.5, 24.2_

- [x] 1.4 Extend shared authentication and authorization for PV safety roles
  - Reuse the shared `Auth_Service` for every PV request (token validation, 1,800-second inactivity timeout, optional Cognito/OIDC JWT validation) without introducing a separate PV identity or session system.
  - Seed PV safety permissions/roles (for example `safety_case.enter`, assessment, coding, narrative, reporting, reconciliation, export, and audit read permissions) at system/study/site scope; extend `Permission_Service` to resolve one `Authorization_Scope` and enforce route-level and object-level checks server-side, returning scoped lists or empty lists and non-disclosing access-denied indications.
  - Add reusable FastAPI dependency guards that resolve the required permission and target scope before any PV mutation, reject inactive users, and deny site-scope actions after scope removal; ensure PV roles cannot mutate EDC clinical or CTMS operational records.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 18.4_

- [x] 1.5 Write the safety authorization scope property test
  - **Property 5: Safety authorization scope**
  - Generate users, PV permission grants, system/study/site scopes, PV operations, and target objects; verify an operation succeeds exactly when the resolved `Authorization_Scope` contains the required permission and target scope, and otherwise changes no safety, audit, attachment, export, or projection state and returns only in-scope records or an empty list.
  - **Validates: Requirements 1, 2, 11, 12, 16, 19, 23**

- [x] 1.6 Integrate shared audit, notification, file, export, and coordination primitives with atomic writes
  - Extend the immutable append-only `Audit_Service` to emit PV safety Audit_Event content (actor, UTC timestamp, entity type/identifier, study, site, action, old/new values for value changes, Reason_For_Change for post-submission changes, request identifier) and PV audit search/export, without altering EDC or CTMS audit content.
  - Reuse shared notification persistence/delivery state, file metadata/access/retention primitives, export-job lifecycle/storage/download controls, and the `Coordination_Service` transactional outbox while keeping PV safety content semantics separate.
  - Make each PV Safety_Data or Safety_Attachment mutation commit its data change, its PV safety Audit_Event, and any required outbox row in one transaction; if the audit or outbox write fails, roll the change back so no Safety_Data or Safety_Attachment state persists without its Audit_Event.
  - _Requirements: 11.1, 11.2, 11.3, 11.6, 11.7, 16.4, 18.1, 18.2, 18.3_

- [x] 1.7 Write the safety audit atomicity and immutability property test
  - **Property 4: Safety audit atomicity and immutability**
  - Generate PV Safety_Data mutations and Safety_Attachment actions including forced audit-write failures; verify the change and its PV safety Audit_Event commit or roll back together, each event contains actor/UTC timestamp/entity/action and applicable old/new values and reason, completed Audit_Events cannot be updated or deleted, and scoped audit search returns matching events ordered by UTC timestamp ascending with ties broken by Audit_Event identifier ascending.
  - **Validates: Requirements 11, 16, 18, 20**

### 2. Safety case intake, capture, lifecycle, and versioning

- [x] 2.1 Implement canonical identity resolution and cross-module ownership guards for PV
  - Resolve canonical Study and Site identity and the EDC Subject_Reference/Visit_Instance identity through stable IDs; reject unknown or ambiguous references and any attempt to create, allocate, or mutate an EDC clinical subject or protocol visit.
  - Define service-level guards that reject any PV command containing an EDC-owned (Study_Version, Clinical_Subject_Registry record, Visit_Instance, Form_Instance, Field_Value, Query, SDV/review, freeze/lock, clinical signature, Clinical_Attachment, clinical export) or CTMS-owned operational field, before any module's authoritative or audit state changes.
  - Preserve read-only canonical identifiers on PV records and record source/rule/correlation metadata for referenced identities.
  - _Requirements: 3.10, 16.6, 23.1, 23.2, 23.3, 23.4, 23.5, 23.9_

- [x] 2.2 Implement `Safety_Case_Service` intake and Adverse_Event_Record capture
  - Implement Safety_Case creation bound to a valid Study, Site, and Subject_Reference with a case type, generating a globally unique safety case identifier and persisting exactly one case; reject unknown references and duplicate identifiers.
  - Implement Adverse_Event_Record capture with a verbatim term of 1–200 characters, onset date, and outcome, persisting a resolution date only when it is not earlier than the onset date; reject invalid verbatim length or resolution-before-onset and persist neither invalid data nor a change event.
  - Emit exactly one PV safety Audit_Event per valid save within the same transaction; never create, allocate, or mutate an EDC clinical subject record.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

- [x] 2.3 Write the safety identity and reference integrity property test
  - **Property 1: Safety identity and reference integrity**
  - Generate valid Study/Site/Subject_Reference/Safety_Case sequences; verify canonical Study/Site identity remains stable, each Safety_Case references exactly one canonical Subject_Reference without duplicating or mutating EDC clinical identity, each safety case identifier is globally unique, and each Adverse_Event_Record belongs to exactly one Safety_Case.
  - **Validates: Requirements 3, 10, 23**

- [x] 2.4 Implement the safety case lifecycle and Case_Version state machine
  - Implement the constrained case lifecycle transitions (Open→In Review; In Review→Follow-up Required/Ready to Report/Closed; Follow-up Required→In Review; Ready to Report→Reported/In Review; Reported→Closed/Follow-up Required; Closed→Reopened), rejecting any other transition without changing case state or content.
  - Implement Case_Version submission with initial version sequence number 1 and follow-up sequence number max+1, snapshotting captured content immutably once Submitted; reject modification of a submitted version's captured content and never delete or overwrite a prior submitted version.
  - Implement post-submission changes to submitted Safety_Data with a required Reason_For_Change (non-empty, ≤ 4,000 characters), rejecting empty or over-length reasons; emit one PV safety Audit_Event per transition or version submission capturing action, actor, and timestamp.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

- [x] 2.5 Write the safety lifecycle transition validity property test
  - **Property 2: Safety lifecycle transition validity**
  - Generate Safety_Case, Case_Version, Regulatory_Report, and notification status sequences; verify PV services accept only configured transitions, record initial version 1 and follow-up version max+1, preserve all prior submitted versions, and reject invalid transitions without partial mutation.
  - **Validates: Requirements 4, 8, 14**

### 3. Safety assessments, coding, and narratives

- [x] 3.1 Implement `Assessment_Service` for seriousness, causality, expectedness, and severity
  - Implement Seriousness_Assessment persistence requiring at least one criterion (death, life-threatening, hospitalization, disability, congenital anomaly, other medically important) when serious, and persisting a not-serious determination otherwise; reject serious-without-criterion and preserve prior state.
  - Implement Causality_Assessment (suspect product, causality category, actor, timestamp), Expectedness_Assessment (expected/unexpected against referenced safety information), and Severity_Grade persistence; reject assessments referencing a missing Adverse_Event_Record or suspect product and persist no assessment.
  - Reject new or changed assessments when the parent Safety_Case is Closed, preserving existing state; emit one PV safety Audit_Event per assessment capturing actor, timestamp, prior value, and new value.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

- [x] 3.2 Implement `Coding_Service` for MedDRA and WHODrug with dictionary versions
  - Implement MedDRA_Coding of an adverse-event verbatim term and WHODrug_Coding of a reported product, persisting the selected term, the Coding_Dictionary_Version used, and the assigning actor and timestamp.
  - Reject a coding assignment referencing a term absent from the identified dictionary version or a missing/unavailable dictionary version, persisting no coding.
  - Implement recoding that retains the prior coding assignment and its dictionary version immutably and records the traceability link from the prior assignment to the new one; emit one PV safety Audit_Event per assignment capturing actor, timestamp, prior/new value, and dictionary version.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 3.3 Implement `Narrative_Service` versioned Case_Narratives
  - Implement Case_Narrative creation with narrative text non-empty after trimming and ≤ 20,000 characters, persisting the text with authoring actor and timestamp.
  - Implement revision that retains the prior version and records revising actor, timestamp, and a Reason_For_Change non-empty after trimming and ≤ 4,000 characters; reject empty/over-length narrative text or reason and preserve existing narrative state.
  - Reject new or revised narratives when the parent Safety_Case is Closed; emit one PV safety Audit_Event per creation or revision.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 3.4 Write the safety data validation and preservation property test
  - **Property 3: Safety data validation and preservation**
  - Generate assessment, coding, narrative, and intake payloads (including boundary and invalid values); verify submission validates required inputs (serious requires a criterion, verbatim 1–200, resolution ≥ onset, narrative non-empty ≤ 20,000, reason non-empty ≤ 4,000), a failed validation preserves prior values and persists no change event, submitted changes require a valid Reason_For_Change, and Closed cases reject safety modifications.
  - **Validates: Requirements 3, 5, 6, 7, 18**

### 4. Regulatory reporting, clocks, and ICSR/E2B

- [x] 4.1 Implement `Regulatory_Reporting_Service` reportability, clocks, and report state machine
  - Implement reportability evaluation creating one Pending Regulatory_Report per matched configured rule (report type and destination); reject report creation when the Awareness_Date is absent and create no report.
  - Implement `compute_clock` as a pure function `due_date = awareness_date + timedelta(days=timeline_days)` with `timeline_days` constrained to 1–90 inclusive and the Awareness_Date counting as day zero in UTC, and `is_overdue` returning true exactly when `today_utc > due_date` and the status is not Submitted, Acknowledged, or Cancelled.
  - Implement the report status state machine (Pending→Submitted/Cancelled; Submitted→Acknowledged/Rejected; Rejected→Pending), rejecting other transitions; on Submitted, require and record the submitting actor, UTC submission timestamp, and E2B_Message reference, rejecting submission without a valid reference; emit one PV safety Audit_Event per report action.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

- [x] 4.2 Write the regulatory clock correctness property test
  - **Property 7: Regulatory clock correctness**
  - Generate Awareness_Dates, reporting-timeline days (including 0/1/90/91 boundaries), current-date offsets, and report statuses; verify the computed due date equals the Awareness_Date plus the configured whole calendar days in UTC (day zero = Awareness_Date), and overdue is true exactly when the current UTC date is later than the due date and the status is not Submitted, Acknowledged, or Cancelled.
  - **Validates: Requirements 8, 13**

- [x] 4.3 Implement ICSR/E2B(R3) produce and parse
  - Implement `produce_e2b` serializing a reportable Safety_Case into an E2B(R3)-structured message containing the case identifier, every mandatory field, and the Coding_Dictionary_Versions used; when a mandatory field is missing, return an error naming each missing field and produce no message and no state change.
  - Implement `parse_e2b` parsing a structurally valid message into a Safety_Case representation (case identifier, mandatory fields, dictionary versions) and rejecting a structurally invalid message with a descriptive error and no case creation.
  - Wire ICSR produce/import routes and record the associated PV safety Audit_Event, ensuring produce/parse remain pure functions with no external gateway.
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 4.4 Write the ICSR round-trip serialization property test
  - **Property 8: ICSR round-trip serialization**
  - Generate reportable Safety_Cases and E2B field maps (including structurally invalid messages); verify that for every valid produced message, parsing then producing yields an equivalent E2B_Message in case identifier, every mandatory field, and Coding_Dictionary_Versions, while a structurally invalid message produces a descriptive parse error and creates no Safety_Case.
  - **Validates: Requirements 9, 16**

### 5. EDC adverse-event reconciliation and read-only projection

- [x] 5.1 Implement the read-only `Safety_Operational_Projection` consumption and projection worker
  - Implement `pv_edc_ae_projections`/`pv_coordination_refs` persistence storing only the approved minimized fields (subject reference, verbatim term, onset date, seriousness) with source identifier, rule version, correlation identifier, projected timestamp, payload fingerprint, and projection status (Current/Stale/Rejected).
  - Implement `pv_projection_worker` that claims one coordination outbox event, revalidates the active Status_Ownership_Rule and field allowlist, upserts only the PV-side projection read model idempotently by idempotency key, records the processing outcome, and never lets a stale event overwrite a current projection.
  - Reject and record any unapproved/unauthorized projection request, delivering no content; ensure the projection is read-only for PV with no write path into EDC clinical or CTMS operational state.
  - _Requirements: 10.4, 23.6, 23.7, 23.8, 23.10, 17.6_

- [x] 5.2 Implement `Reconciliation_Service` one-way read-only diffing
  - Implement `diff` as a pure function over the safety events and the projected EDC field set (subject reference, verbatim term, onset date, seriousness), producing one Reconciliation_Discrepancy per differing record identifying the affected Safety_Case, EDC reference, and each differing field.
  - Implement `run` scoped to a Study within the user's Authorization_Scope, recording match and discrepancy counts; when the required projection is unavailable or stale, produce no results and return an error indicating the EDC projection is unavailable.
  - Reject any reconciliation operation that attempts to modify an EDC clinical record, changing neither EDC clinical nor PV safety state; emit one PV safety Audit_Event when a discrepancy is created or resolved.
  - _Requirements: 10.1, 10.2, 10.3, 10.5, 10.6, 10.7_

- [x] 5.3 Write the safety and cross-module content separation property test
  - **Property 6: Safety and cross-module content separation**
  - Generate PV exports, dashboards/reports, Safety_Attachments, notifications, audit searches, reconciliation runs, and projection payloads containing prohibited fields; verify each result contains only authorized PV safety content and approved read-only projections, EDC clinical and CTMS operational content cannot be written through any PV operation, and projected fields are excluded from PV metric calculations.
  - **Validates: Requirements 10, 11, 12, 13, 15, 23**

### 6. Safety exports, dashboards, notifications, and attachments

- [x] 6.1 Implement PV safety exports on shared export-job infrastructure
  - Implement export job creation with Queued→Running→Completed/Failed transitions, storing the generated file on completion, transitioning jobs Running for more than 900 seconds to Failed with a failure reason and no downloadable file, and producing only in-scope Safety_Cases (empty result when none qualify).
  - Apply study, site, subject reference, case status, seriousness, report status, and inclusive UTC date-range filters as intersections, rejecting a requested date span exceeding 1,830 days without creating a Completed job; accept and produce only CSV, Excel, JSON, and E2B XML and reject any other format.
  - Provide the file only to the authorized requesting user within 900 seconds of completion (recording a download Audit_Event) and deny downloads after 900 seconds or for jobs owned by another user; keep PV export content separate from EDC/CTMS content and label any approved projection as projected content excluding unapproved fields.
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

- [x] 6.2 Implement PV safety dashboards and reports
  - Implement scoped study dashboards returning within 5 seconds Safety_Case counts by lifecycle status, adverse-event counts by seriousness, and Regulatory_Report counts by report status, computed from in-scope PV records as of the request timestamp.
  - Implement reporting-compliance metrics with mutually exclusive submitted/overdue/on-time buckets derived from report status and Regulatory_Clock due date versus the current UTC date, and site dashboards returning only in-scope PV site metrics with zero-valued metrics when no records qualify.
  - Reuse shared aggregation/authorization primitives, display any approved EDC/CTMS projection as read-only source-labeled fields, and prevent projected fields from entering PV metric calculations or being mutated through PV.
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 6.3 Implement PV safety notifications
  - Implement triggers creating one PV safety notification per resolved assigned recipient within 60 seconds of a serious-case creation, one notification within 60 seconds when a Regulatory_Clock due date enters a configured 1–30 day warning window while the report is not Submitted, and one notification within 60 seconds when a safety export job reaches Completed or Failed.
  - Support only Unread/Read/Archived statuses with Unread→Read/Archived and Read→Archived transitions, return only the requesting user's Unread notifications (empty list when none qualify), and dedupe warning notifications so no additional notification is created for the same report and due date when an unarchived one exists.
  - When a serious case resolves no assigned recipient, create no per-recipient notification and record one PV safety Audit_Event indicating no recipient was resolved; keep Notification_Service shared while PV owns its safety triggers.
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8_

- [x] 6.4 Implement Safety_Attachments using shared file primitives
  - Implement Safety_Attachment upload storing a non-empty file no larger than 100 MB in object storage with metadata linked to the safety object, rejecting empty or oversized files (and rejecting uploads when object storage is unavailable) with no stored attachment, no partial file, and no persisted metadata.
  - Grant download only when the user has read access to the parent Safety_Case, apply Soft_Deletion on delete (retaining metadata and reason and preventing subsequent normal downloads), and reject new uploads while the parent Safety_Case is Closed.
  - Record one PV safety Audit_Event per completed upload/download/deletion (no completed-action event on failure), and reject any PV operation targeting an EDC Clinical_Attachment or CTMS Operational_Attachment without changing that module's state.
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_

### 7. PV API layer and frontend safety application

- [x] 7.1 Implement authenticated PV API schemas, routes, and service wiring
  - Add Pydantic v2 request/response schemas and authenticated routes under `/api/v1/pv` for cases, adverse events, assessments, coding, narratives, regulatory reports, ICSR produce/import, reconciliation, attachments, exports, dashboards/reports, audit search/export, and health/metrics.
  - Wire every route through request context, shared permission guards, canonical identity resolution, PV service transaction boundaries, pagination, the standard error envelope, and `X-Request-ID`, keeping route handlers limited to input validation, permission checks, and delegation with database access only through repositories.
  - Add no PV mutation route for EDC Study_Version, Clinical_Subject_Registry, Visit_Instance, Form_Instance, Field_Value, Query, SDV/review, freeze/lock, clinical signatures, Clinical_Attachments, or clinical exports, nor for CTMS operational records.
  - _Requirements: 16.1, 16.2, 16.3, 16.5, 16.6, 18.1, 18.2, 18.4, 23.4, 23.5_

- [x] 7.2 Implement PV audit search/export endpoints and contract publication
  - Implement scoped PV audit search supporting exact filtering by user, inclusive UTC date range, entity, Safety_Case, and Regulatory_Report, returning events ordered by UTC timestamp ascending with ties broken by Audit_Event identifier ascending, and rejecting out-of-scope search/export.
  - Implement PV audit export producing exactly the authorized selected events and recording the export action; reject any attempt to update or delete an Audit_Event.
  - Publish PV enum values, error codes, pagination schemas, and error responses in OpenAPI, ensuring ownership conflicts return explicit PV errors and failing responses contain only sanitized details.
  - _Requirements: 11.4, 11.5, 11.6, 11.8, 16.3_

- [x] 7.3 Build the frontend PV workspace and permission-aware routes
  - Add authenticated PV routes under the existing AppShell (`/pv`, study/site PV workspaces, cases, assessments, coding, narratives, reports, reconciliation, dashboard, exports, audit) with TanStack Query clients, typed API models, capability metadata, and loading/error states.
  - Add TanStack Table listings for cases/reports/reconciliation, React Hook Form + Zod pre-submission validation while the API remains authoritative, and permission-aware navigation that hides actions or renders access-denied views while relying on server-side enforcement.
  - Preserve baseline EDC and CTMS navigation when PV is disabled, empty, or unavailable.
  - _Requirements: 19.1, 19.2, 19.6, 23.10_

- [x] 7.4 Implement PV status presentation, Closed-case controls, and history dialogs
  - Display the same textual status value for each Safety_Case, Case_Version, assessment, coding, Regulatory_Report, and reconciliation state in list and detail views, and show canonical EDC Subject_Reference and any read-only EDC/CTMS projection with a source label.
  - Require a non-empty Reason_For_Change (≤ 4,000 characters) before sending edits to submitted safety data, and render input controls disabled while a Safety_Case is Closed.
  - Render PV audit history and case-narrative history in a dialog or sheet while keeping the originating safety status view mounted and visible.
  - _Requirements: 19.1, 19.3, 19.4, 19.5, 19.6_

- [x] 7.5 Write frontend component and route tests
  - Test PV route registration under the authenticated shell, permission-aware hiding/denial, consistent status labels across list and detail views, Zod pre-submit validation, Reason_For_Change enforcement, disabled controls on Closed cases, and audit/narrative history dialogs keeping the status view mounted.
  - Test that baseline EDC and CTMS navigation remains unchanged with PV disabled, empty, and worker-unavailable.
  - **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 23.10**

### 8. Compliance, resilience, observability, and phased qualification

- [x] 8.1 Implement environment isolation, retention, and compliance controls
  - Configure isolated local/development/test/staging/production environments preventing cross-environment reads of database, object storage, secrets, authentication configuration, and logs, with PV feature flags and safety settings server-side.
  - Implement retention/backup/restore jobs that retain PV safety records at least 7 years, create at least one backup per 24-hour period, and restore PV records within 4 hours without restoring into another module's authoritative records or cascading into EDC clinical or CTMS operational data.
  - Derive PV safety Audit_Event timestamps from the server clock as UTC with server-clock agreement within 5 seconds, represent Open/In Review/Ready to Report/Reported/Closed as distinct states, and maintain the Traceability_Matrix mapping each PV requirement to its design reference and qualification test.
  - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 17.3_

- [x] 8.2 Implement PV observability and performance handling
  - Add PV liveness/readiness endpoints returning within 1 second, structured log entries containing request identifier, UTC timestamp, operation outcome, and duration in milliseconds, and a metrics endpoint returning PV API latency, error rate, worker job failures, export failures, and overdue regulatory reports over at least the preceding 5 minutes, updated at least every 60 seconds.
  - Enforce bounded pagination (≤ 1,000 items per page) and asynchronous job handoff for exports and batch reconciliation of at least 100,000 records (accepted within 5 seconds with Queued/Running/Completed/Failed status), supporting at least 100 concurrent authenticated users while meeting the common-read latency target.
  - Redact prohibited safety data and raw coordination payloads from all observability output.
  - _Requirements: 24.1, 24.2, 24.3, 24.4, 25.1, 25.2, 25.3, 25.4_

- [x] 8.3 Implement the optional PV-scoped AI assistant
  - Expose chat, narrative-drafting, and case-summarization operations backed by AWS Bedrock AgentCore only when enabled (exposing none when disabled), beginning streaming within 5 seconds and emitting a terminal completion or error within 120 seconds.
  - Verify the requesting user's Authorization_Scope before sending any safety context, sending none and returning a denial when the context is out of scope, and require explicit human confirmation for any AI suggestion that would change Safety_Data, applying no change when confirmation is declined or not received within 300 seconds.
  - Record one PV safety Audit_Event identifying the user, changed safety object, action, and AI-assisted origin for a confirmed change, and emit an error within the stream applying no change if the backend or stream fails before completion.
  - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6_

- [x] 8.4 Write PV database, migration, and boundary integration tests
  - Using the async SQLAlchemy/PostgreSQL harness, test additive Phase 1/2/3 Alembic migrations and downgrades, constraints, indexes, no clinical/operational duplication, canonical reference resolution and rejection of unknown references, and transaction atomicity for Safety_Data + Audit_Event (+ outbox) including forced audit/database failures.
  - Test submitted-version immutability, reconciliation over the read-only projection with staleness handling and rejection of any EDC-mutation attempt, Safety_Attachment upload/download/soft-delete via shared file primitives, and export job lifecycle including the 900-second timeout and download-window enforcement.
  - **Validates: Requirements 10.4, 10.5, 10.6, 11.7, 12.1, 15.7, 17.1, 17.2, 17.6, 18.3, 23.6**

- [x] 8.5 Write PV API contract, security, and permission tests
  - Add OpenAPI snapshot tests verifying `/api/v1/pv` paths, Pydantic v2 schemas, pagination envelope, enum values, and the absence of EDC/CTMS mutation routes; add security tests attempting EDC/CTMS-owned field injection, duplicate case identifiers, out-of-scope reads, viewer mutations, prohibited projection fields, existence disclosure, and log/error leakage.
  - Add permission tests calling the API directly as PV safety roles, out-of-scope users, inactive users, and users after scope removal, verifying each denial changes no PV, audit, attachment, export, projection, or EDC/CTMS state.
  - **Validates: Requirements 1.3, 2.1, 2.2, 2.3, 2.4, 16.3, 16.6, 23.4, 23.5**

- [x] 8.6 Write the unified-platform resilience and phased-qualification tests
  - Verify PV continues authentication, safety case capture, assessment, audit, export, and regulatory reporting using only PV-owned state and referenced canonical identity when EDC/CTMS is disabled, empty, or unresponsive within 30 seconds, returning no cross-module-dependent safety result as authoritative.
  - Provide qualification evidence with at least one passing OQ/PQ test for each phase capability (Phase 1: shared authentication, PV scope enforcement, safety case intake, case lifecycle, seriousness assessment, immutable PV safety audit, EDC non-modification boundaries, safety CSV export; Phase 2: MedDRA/WHODrug coding, causality/expectedness/severity assessments, narratives, reconciliation; Phase 3: regulatory reporting/expedited timelines, ICSR/E2B, advanced exports, optional AI), declaring no phase complete while a required test fails and not counting EDC/CTMS capabilities as PV deliverables.
  - **Validates: Requirements 20.6, 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 23.10**

### 9. Checkpoint — Phase 1 PV MVP

- Ensure all implemented Phase 1 tests pass, verify PV cannot create or mutate any EDC clinical or CTMS operational record, and ask the user if questions arise.

### 10. Checkpoint — Phase 2 coding, assessments, narratives, and reconciliation

- Ensure all implemented Phase 2 tests pass, verify one-way read-only reconciliation and projection minimization, and ask the user if questions arise.

### 11. Checkpoint — Phase 3 regulatory reporting, ICSR/E2B, exports, and optional AI

- Ensure all implemented Phase 3 tests pass, verify regulatory clock correctness, ICSR round-trip fidelity, sanitized failures, and no data change without explicit confirmation, and ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and may be skipped for a faster MVP; core implementation tasks are not optional.
- Each property-based task maps to one of the 8 design Correctness Properties and should use Hypothesis with at least 100 examples, deterministic in-memory repositories/fakes, and no external services; `compute_clock`, `is_overdue`, `produce_e2b`, `parse_e2b`, and `diff` are exercised as pure functions.
- Property-based tests complement, rather than replace, database transaction, migration, object-storage, export-job, notification, API-contract, security, frontend, performance, and qualification tests.
- The plan deliberately creates no duplicate clinical or operational tables and no PV route that writes EDC clinical or CTMS operational authority; every shared primitive is reused without transferring ownership of its content semantics.
- Phase 1 delivers shared authentication reuse, PV scope enforcement, safety case intake and lifecycle, seriousness assessment, immutable PV safety audit, and safety CSV export; Phase 2 delivers coding, assessments, narratives, and read-only reconciliation; Phase 3 delivers regulatory reporting, ICSR/E2B, advanced exports/dashboards/notifications, and the optional AI assistant.
- Convert each leaf task into a prompt for a code-generation LLM that implements that step incrementally, builds on prior steps, runs the relevant tests, and leaves every new component wired into an existing route/service or test harness.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.6", "2.1"] },
    { "id": 2, "tasks": ["1.5", "1.7", "2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["2.5", "3.1", "3.2", "3.3"] },
    { "id": 5, "tasks": ["3.4", "4.1", "4.3", "5.1"] },
    { "id": 6, "tasks": ["4.2", "4.4", "5.2", "6.1", "6.2", "6.3", "6.4"] },
    { "id": 7, "tasks": ["5.3", "7.1", "7.2", "7.3"] },
    { "id": 8, "tasks": ["7.4", "8.1", "8.2", "8.3"] },
    { "id": 9, "tasks": ["7.5", "8.4", "8.5"] },
    { "id": 10, "tasks": ["8.6"] }
  ]
}
```
