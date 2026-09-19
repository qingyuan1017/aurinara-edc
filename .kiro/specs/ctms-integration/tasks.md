# Implementation Plan: CTMS Integration

## Overview

This plan converts the `ctms-integration` design into incremental prompts for a code-generation LLM. It implements CTMS as a co-equal first-party module inside the Unified_Clinical_Platform, reusing shared authentication, authorization, audit, request, notification, storage, export-job, observability, environment, and coordination primitives. CTMS owns operational study/site planning, enrollment operations, monitoring, work management, minimized projections, operational reporting, exports, and attachments.

The implementation must preserve EDC authority over Study_Version and clinical configuration, Clinical_Subject_Registry, protocol Visit_Instances and casebooks, eCRFs, Form_Instances, Field_Values, Queries, SDV, review, freeze/lock, signatures, Clinical_Attachments, clinical exports, and all other Clinical_Data. CTMS references canonical EDC identities and may consume only approved read-only projections or explicitly configured coordinated transitions.

The design specifies Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL, pytest/Hypothesis, React/TypeScript/Vite, TanStack Router/Query/Table, React Hook Form/Zod, Tailwind/shadcn/ui, and deterministic in-memory fakes for property tests. Routes remain thin; service methods own validation and transaction boundaries; repositories do persistence; shared Audit_Service writes atomically with authoritative mutations and outbox records. All timestamps are timezone-aware UTC values and all deletable CTMS records use configured soft deletion or archival.

Tasks marked with `*` are optional test tasks. Property tests use Hypothesis, one test per design property, with at least 100 generated examples and no external services. Each property task is placed close to the implementation it verifies. Checkpoints are planning gates only and are excluded from the dependency graph.

## Tasks

### 1. Shared platform foundation and CTMS boundaries

- [x] 1.1 Scaffold the CTMS backend, frontend feature boundaries, and phase capability manifest
  - Add the `backend/app/models/ctms`, `schemas/ctms`, `repositories/ctms`, CTMS service modules, workers, `/api/v1/ctms` route package, and frontend CTMS feature areas from the design package structure.
  - Add server-side phase capability metadata/feature flags so disabling CTMS hides CTMS capabilities without deleting records or changing EDC routes.
  - Define shared enums and identifiers for `Module`, `Correlation_Identifier`, `Idempotency_Key`, ownership state, and UTC timestamps without duplicating EDC clinical models.
  - _Requirements: 1.1–1.4, 2.9–2.10, 14.1–14.3, 14.10_

- [x] 1.2 Create additive CTMS migrations and base persistence conventions
  - Add phase-gated Alembic revisions for CTMS-owned tables, UUID keys, UTC `TIMESTAMPTZ` columns, study/site scope, indexes, foreign-key/reference constraints, soft-deletion/archive columns, and no duplicate clinical tables.
  - Establish common SQLAlchemy mixins for actor, correlation, created/updated timestamps, retention state, and soft deletion; preserve existing EDC tables as authoritative references.
  - Add migration upgrade/downgrade checks and database guards for immutable records where required.
  - _Requirements: 1.2–1.3, 1.9–1.10, 12.4–12.5, 12.13, 14.1–14.3_

- [x] 1.3 Implement shared request context and CTMS API contracts
  - Extend request middleware to assign request and correlation identifiers, resolve authenticated actor context, return `X-Request-ID`, and propagate identifiers to services, audit events, logs, and coordination records.
  - Implement/reuse Pydantic v2 base schemas, the baseline error envelope, pagination `{items, page, page_size, total}`, UTC serialization, sanitized error mapping, and CTMS OpenAPI metadata.
  - Ensure CTMS errors never expose stack traces, database errors, credentials, Clinical_Data, prohibited projection values, raw event bodies, or unrestricted query messages.
  - _Requirements: 1.7, 1.9, 2.5, 11.2, 11.7–11.10_

- [x] 1.4 Extend shared authentication and authorization for CTMS
  - Seed `CTMS_Admin`, `CTMS_Operations_User`, and `CTMS_Viewer` permissions, including system/study/site scope and management, monitoring, enrollment, conflict, replay, and read permissions.
  - Extend `Permission_Service` to resolve one `Authorization_Scope` for EDC and CTMS, enforce route/object scope server-side, reject inactive users, and deny site-scope actions after scope removal.
  - Add reusable FastAPI guards that run before service mutations and preserve baseline authorization errors for viewer and out-of-scope mutations.
  - _Requirements: 2.1–2.3, 10.1–10.18, 11.15–11.16, 13.6_

- [x] 1.5 Integrate shared audit, notification, file, and export primitives without transferring content ownership
  - Extend the immutable append-only `Audit_Service` for CTMS operational, projection, coordination, attachment, notification, health, and export events with actor/worker, scope, UTC timestamp, action, changed fields, and correlation metadata.
  - Reuse shared notification persistence/delivery state, file metadata/access/retention primitives, and export-job lifecycle/storage/download controls while keeping CTMS and EDC content semantics separate.
  - Make authoritative CTMS mutation + status history + audit + outbox writes share one transaction and preserve rollback behavior.
  - _Requirements: 2.4, 2.6–2.8, 3.5, 4.4, 7.8–7.11, 12.1–12.10, 13.8–13.11_

- [x] 1.6 Write the shared authorization property test
  - **Property 3: Authorization is exact and module-wide**
  - Generate users, role grants, system/study/site scopes, module operations, and target records; verify operations succeed exactly when the shared `Authorization_Scope` permits them and otherwise mutate no CTMS, projection, coordination, attachment, or EDC state.
  - **Validates: Requirements 2.1–2.3, 2.7, 2.10–2.11, 3.9, 4.10, 5.15, 6.8, 6.12, 7.8, 7.10, 8.6–8.7, 10.1–10.18, 13.6, 14.5**

- [x] 1.7 Write the audit/correlation/atomicity property test
  - **Property 16: Audit, correlation, and traceability are complete and atomic**
  - Verify CTMS mutations, projections, coordination events, failures, replays, conflicts, attachments, and exports contain complete sanitized audit metadata; verify authoritative data and its audit/outbox record commit or roll back together and remain traversable by correlation ID.
  - **Validates: Requirements 1.7, 2.4–2.5, 3.5, 4.4, 6.14, 7.8, 7.11, 9.1, 9.3–9.4, 9.7, 9.18, 12.1–12.5, 12.10, 14.6**

- [x] 1.8 Add shared observability, environment isolation, and optional AI control hooks
  - Add CTMS health/readiness metrics, structured logs, tracing fields, queue/projection counters, and sanitized error categories without clinical values or raw event bodies.
  - Extend environment configuration for isolated database, object storage, secrets, authentication, logging, retention, backup, and restore settings; expose feature capability metadata server-side.
  - Add optional AI platform hooks that enforce module scope, data minimization, human confirmation, and audit before any CTMS action, without implementing an independent CTMS AI authority.
  - _Requirements: 2.9–2.11, 11.7–11.10, 13.12–13.16, 14.5, 14.10_

### 2. Phase 1 operational study, site, enrollment, and milestone foundation

- [x] 2.1 Implement canonical identity resolution and cross-module ownership guards
  - Resolve canonical Study and Site identities and EDC Subject, Visit_Instance, and Query identifiers through stable IDs; reject display-name identity, unknown references, ambiguous matches, and competing clinical-record creation.
  - Define service-level guards that reject CTMS commands containing EDC-owned Study_Version, subject identity/binding, Visit_Instance, Form_Instance, Field_Value, Query lifecycle, quality, lock, signature, attachment, or clinical-export mutations before any transaction changes state.
  - Preserve read-only canonical EDC identifiers on CTMS records and record source/target/rule/correlation metadata for linked identities.
  - _Requirements: 1.2–1.8, 3.6–3.8, 4.7–4.8, 5.4, 5.6–5.7, 6.1–6.2, 6.15, 11.6_

- [x] 2.2 Implement `Operational_Study_Service` and study planning persistence
  - Add operational study profile, study plan, enrollment plan, readiness criteria, operational milestone, status history, archive, and dashboard/report query models using the canonical `study_id`.
  - Implement create/update/transition/archive operations for sponsor, phase, therapeutic area, indication, operational owner, planning metadata, and statuses `Draft`, `Planning`, `Ready`, `Active`, `Enrollment Closed`, `Suspended`, and `Closed`; require configured reasons and retain history while Active.
  - Audit every CTMS change and ensure no operation mutates EDC `Study_Version` or clinical configuration.
  - _Requirements: 3.1–3.10, 14.1, 14.6_

- [x] 2.3 Write the operational study lifecycle property test
  - **Property 4: Operational study lifecycle is independent of clinical configuration**
  - Generate profiles, plans, readiness criteria, milestones, and status sequences; verify only configured transitions succeed, required history/reasons persist, and canonical EDC Study/Study_Version/clinical configuration snapshots remain unchanged.
  - **Validates: Requirements 3.1–3.10**

- [x] 2.4 Implement `Operational_Site_Service`, activation/readiness actions, and contacts references
  - Add operational site profile, activation action, monitoring-readiness, responsible-role, planned-date, completion-evidence, status-history, archive, and canonical `site_id` persistence.
  - Implement site statuses `Not Started`, `In Progress`, `Ready for Activation`, `Active`, `Suspended`, and `Closed`; require completion actor/time/evidence and configured transition reasons.
  - Enforce unique active `(site_id, action_type)` activation actions by returning the existing action on duplicate requests, and mark linked operational records Archived or Site Archived when EDC archives a site.
  - _Requirements: 4.1–4.11, 14.1, 14.6_

- [x] 2.5 Write the operational site lifecycle property test
  - **Property 5: Operational site lifecycle is independent of clinical site use**
  - Generate site profiles, activation/readiness actions, contacts, status sequences, and duplicate requests; verify required evidence/history and idempotency while the canonical EDC Site and clinical configuration remain unchanged.
  - **Validates: Requirements 4.1–4.11**

- [x] 2.6 Implement enrollment targets, operational subject milestones, and approved status projections
  - Add `Enrollment_Target` persistence for study/site/planning dimensions, target types `Recruitment`, `Screening`, and `Enrollment`, quantities, periods, owners, and statuses `Draft`, `Active`, `Met`, `Expired`, and `Cancelled`.
  - Implement operational subject milestones using existing canonical EDC `subject_id`, approved pseudonym/reference, milestone type/date, and statuses `Screening`, `Screen Failed`, `Enrolled`, `Randomized`, `On Treatment`, `Completed`, `Early Terminated`, `Lost to Follow-up`, and `Withdrawn`.
  - Reject unknown/ambiguous/withdrawn-prohibited subject references and prohibited clinical fields; retain operational state without creating/replacing clinical subjects or modifying clinical identifiers, study-version binding, Visit_Instances, Form_Instances, Field_Values, or Clinical_Data.
  - Add configured EDC-to-CTMS subject progress projection and explicit status-ownership checks; unconfigured CTMS statuses remain CTMS-only.
  - _Requirements: 5.1–5.15, 8.2–8.4, 8.10, 14.1, 14.4_

- [x] 2.7 Write the enrollment authority and clinical protection property test
  - **Property 6: Enrollment operations never duplicate or replace clinical subjects**
  - Generate targets, milestones, canonical subjects, invalid identifiers, replacement identifiers, and prohibited fields; verify valid CTMS state/projections persist while all EDC clinical subject snapshots remain unchanged and invalid commands make no mutation.
  - **Validates: Requirements 5.1–5.15, 8.2, 8.4, 8.10, 14.4**

### 3. Phase 2 monitoring and operational work management

- [x] 3.1 Create monitoring plan/version/activity models and additive migration
  - Add `Monitoring_Plan`, immutable `Monitoring_Plan_Version`, `Monitoring_Activity`, scheduling/rescheduling history, assignment, completion/cancellation evidence, status history, optional canonical EDC `edc_visit_instance_id`, and operational attachment references.
  - Add activity types Site Initiation, Routine Monitoring, Close-out, Remote Review, and Triggered Review with study/site scope and indexes for planned date, status, CRA, and linked EDC visit.
  - Ensure database relationships are references only: CTMS must not copy writable protocol visit or Clinical_Data fields.
  - _Requirements: 6.3, 6.6–6.7, 6.9–6.11, 6.14–6.15, 14.2_

- [x] 3.2 Implement `Monitoring_Service` and protocol/monitoring separation
  - Implement monitoring plan creation, publication, amendment-by-new-draft with mandatory reason, and retrieval of immutable published versions.
  - Implement activity schedule, study/site-scoped CRA assignment, reschedule with prior date/reason, completion with evidence/notes/actor, and cancellation with reason/actor.
  - Permit CTMS scheduling/completion when a linked EDC Visit_Instance is Frozen or Locked, while never creating, rescheduling, completing, marking missed, freezing, locking, or changing the EDC Visit_Instance or Clinical_Data.
  - _Requirements: 6.1–6.15, 14.2, 14.7_

- [x] 3.3 Write the monitoring-plan immutability property test
  - **Property 7: Published monitoring plans are immutable and amend by version**
  - Verify direct mutation of a published plan is rejected, an amendment with a non-empty reason creates exactly one new Draft version, and prior Published versions remain unchanged and retrievable.
  - **Validates: Requirements 6.3–6.5**

- [x] 3.4 Write the monitoring/protocol visit separation property test
  - **Property 8: Monitoring activities remain separate from protocol visits**
  - Generate monitoring activity sequences and linked EDC Visit_Instance states including Frozen and Locked; verify CTMS history changes while protocol definitions, dates, windows, missed state, casebook state, and Clinical_Data remain unchanged.
  - **Validates: Requirements 6.1–6.2, 6.6–6.15, 14.7**

- [x] 3.5 Implement `Work_Management_Service` for tasks, query follow-ups, contacts, dependencies, and escalations
  - Add operational task/contact models, status history, owner/due date/priority/scope/correlation fields, optional EDC `query_id`, dependency links, and environment-gated escalation records.
  - Implement task statuses Open, In Progress, Blocked, Completed, Cancelled, Archived and contact statuses Active, Inactive, Archived; require configured reasons, active-user assignment, scope checks, and completion history.
  - Create query follow-up tasks with only approved EDC Query identifier/summary metadata; never persist unrestricted query messages, Clinical_Data, source documents, or clinical audit history and never change EDC Query state.
  - Emit assignment notifications and CTMS operational audit events.
  - _Requirements: 7.1–7.12, 12.1, 14.2_

- [x] 3.6 Write the operational work lifecycle property test
  - **Property 9: Work management remains operational and query follow-ups remain non-clinical**
  - Generate tasks, contacts, follow-ups, dependencies, escalations, assignments, and status sequences; verify lifecycle/scope/reason enforcement, linked query identifiers after completion, active-user rules, and exclusion of prohibited clinical content.
  - **Validates: Requirements 7.1–7.12**

- [x] 3.7 Write monitoring and work-management integration boundary tests
  - Test published-plan amendment/versioning, CRA scope checks, frozen/locked EDC visits, query follow-up creation without query mutation, task assignment notifications, and operational audit/status-history transactions using the shared async database harness.
  - **Validates: Requirements 6.3–6.15, 7.5–7.12, 14.2, 14.7**

### 4. Minimized projections and internal coordination

- [x] 4.1 Implement versioned `Status_Ownership_Rule` records and typed projection allowlists
  - Add ownership-rule persistence for entity/field path, authoritative module, writable module, projection target, allowed transitions, typed allowlist, effective version/interval, and active/retired state.
  - Define schema-specific allowlists for subject projections, query summaries, approved Data_Quality_Signals, and coordinated transitions; reject arbitrary source JSON and prohibited identifiers/fields.
  - Compile rules and allowlists into deterministic validation decisions used at command acceptance and immediately before coordination application.
  - _Requirements: 1.2, 1.6–1.8, 5.8–5.13, 8.1–8.4, 8.8–8.10, 12.11–12.12_

- [x] 4.2 Implement `CTMS_Operational_Projection` persistence and minimization service
  - Add typed projection records with source module/ID, canonical references, source/rule versions, correlation ID, projected timestamp, payload fingerprint, current/stale/rejected/archived state, and rebuild generation.
  - Implement projection validation, allowlisted payload construction, prohibited-field rejection, sanitized field fingerprints, current source timestamp/version checks, and read-only consumer access.
  - Ensure projected subjects/queries/quality signals cannot authorize CTMS mutation of EDC Clinical_Data.
  - _Requirements: 1.6, 5.8–5.13, 8.1–8.12, 12.2, 12.11–12.12_

- [x] 4.3 Write the explicit ownership-boundary property test
  - **Property 1: Exactly one authoritative owner governs each field**
  - Generate shared entities, field paths, active ownership rules, CTMS/EDC commands, and projections; verify exactly one authority, read-only consumer access, and rejection of competing clinical writes or unconfigured transitions.
  - **Validates: Requirements 1.2, 1.5–1.8, 3.7–3.8, 4.5–4.8, 5.8–5.11, 6.15, 8.10, 14.4**

- [x] 4.4 Write the canonical identity stability property test
  - **Property 2: Canonical references are stable and unambiguous**
  - Generate canonical maps, display-name changes/collisions, repeated resolution, unknown records, and ambiguous references; verify stable source IDs, preserved identity, and rejection without state changes.
  - **Validates: Requirements 1.3–1.7, 3.6, 4.7, 5.4, 6.7, 7.5–7.6, 9.4, 9.10–9.11**

- [x] 4.5 Implement transactional outbox, coordination events, immutable logs, and idempotent processing
  - Add coordination event, event attempt, event log, and outbox models with source/target/entity IDs, source sequence/version, rule version, allowlisted payload/fingerprint, idempotency key, correlation ID, status, attempts, resulting projection ID, and sanitized reason.
  - Implement accepted → queued → processing → succeeded/skipped/retrying/failed/conflict state transitions; enforce unique idempotency keys and immutable completed event logs at application and database layers.
  - Implement deterministic processing that returns prior outcomes for duplicate delivery, applies source order, skips current projections, and updates only approved projections or explicitly named coordinated targets in one target/audit transaction.
  - _Requirements: 9.1–9.9, 9.17–9.18, 12.3–12.5, 14.2_

- [x] 4.6 Write the idempotent coordination property test
  - **Property 11: Coordination is idempotent**
  - Generate accepted events, idempotency keys, duplicate deliveries, and target projections; verify one logical update/side effect, stable outcome/target ID, and duplicate/skipped records without duplicate records.
  - **Validates: Requirements 1.7, 4.11, 9.2–9.8, 9.18**

- [x] 4.7 Implement source ordering, stale detection, and current-projection handling
  - Add per-entity source sequence/version checks, deterministic event ordering, stale/out-of-order conflict/skipped outcomes, and current-version recording.
  - Ensure an older event cannot overwrite a newer projection and that rebuild/refresh operations preserve source and target version metadata.
  - _Requirements: 8.11–8.12, 9.8–9.9, 9.17–9.18_

- [x] 4.8 Write the ordered/current projection property test
  - **Property 12: Coordination preserves source order and freshness**
  - Generate permutations of source-versioned events for one correlated entity; verify source-order application, stale rejection, current-version recording, and no older overwrite.
  - **Validates: Requirements 8.11–8.12, 9.8–9.9, 9.17–9.18**

- [x] 4.9 Implement retry, failure classification, conflicts, replay, and policy revalidation
  - Classify unknown/ambiguous references, schema, authorization, ownership, minimization, out-of-order, and retryable storage/service failures; apply bounded backoff only to retryable errors and retain sanitized attempts.
  - Add `Failed_Event` and `Coordination_Conflict` handling, resolution policies, authorized CTMS_Admin replay, current identity/scope/ownership/allowlist revalidation, and no-partial-mutation rollback.
  - Add failure/conflict notifications and sanitized remediation fields without prohibited values or raw event bodies.
  - _Requirements: 9.10–9.16, 10.9–10.10, 13.10, 13.13–13.15, 14.3_

- [x] 4.10 Write the retry and failure-classification property test
  - **Property 13: Coordination failures are bounded and sanitized**
  - Generate worker result sequences and retry policies; verify bounded retry for retryable failures, correct Failed_Event/Coordination_Conflict classification, no partial target mutation, and no prohibited values in retained details.
  - **Validates: Requirements 9.10–9.15, 13.13–13.15**

- [x] 4.11 Write the current-policy replay property test
  - **Property 14: Replay revalidates current policy**
  - Generate failed events followed by changes to authorization, ownership, identity, or allowlists; verify replay applies only when all current checks pass and otherwise preserves failed/conflicted state and source records.
  - **Validates: Requirements 9.16, 10.9–10.10**

- [x] 4.12 Implement projection rebuild and deterministic generation/watermark tracking
  - Add a scope-limited rebuild worker that reads authoritative CTMS/EDC records in stable order, applies the active allowlist, upserts only projection rows, and records generation/watermark state.
  - Make repeated rebuilds over unchanged source data produce identical typed payloads/fingerprints; never emit reverse mutations or alter authoritative records/audit history.
  - _Requirements: 8.1–8.7, 9.17, 14.6_

- [x] 4.13 Write the projection-rebuild safety property test
  - **Property 15: Projection rebuilds are source-preserving and repeatable**
  - Generate authoritative record sets and rule generations; verify repeated rebuild equality and unchanged CTMS/EDC source records, source status, and source audit history.
  - **Validates: Requirements 8.1–8.7, 9.17, 14.6**

- [x] 4.14 Write coordination/database boundary tests
  - Test outbox atomicity, duplicate delivery, immutable event logs, source ordering, stale projections, retry exhaustion, sanitized failures, conflict resolution, replay revalidation, worker restart, and projection rebuilds against deterministic fakes and the async database harness.
  - **Validates: Requirements 9.1–9.18, 12.3–12.5, 13.10, 13.14–13.15**

- [x] 4.15 Write the projection minimization property test
  - **Property 10: Projection payloads obey versioned minimization allowlists**
  - Generate source records, projection types, active rules, arbitrary nested payloads, prohibited clinical fields, credentials, unrestricted messages, and prohibited identifiers; verify resulting projections contain exactly approved typed fields and rejected records retain only sanitized fingerprints.
  - **Validates: Requirements 1.6, 5.12–5.13, 8.1–8.9, 8.11–8.12, 12.11–12.12**

### 5. Operational dashboards, reports, exports, attachments, health, and resilience

- [x] 5.1 Implement CTMS dashboard and report services
  - Add scoped study/site dashboards for enrollment targets/actual/variance, readiness, activation, monitoring activities, overdue tasks, milestones, contacts, and approved quality signals.
  - Add monitoring, enrollment, and task reports with status/owner/priority/due-date/trend filters; calculate only in-scope CTMS records and approved projections.
  - Label projected clinical metrics as read-only with source module, source timestamp, and freshness; reuse shared dashboard aggregation and authorization primitives without blending EDC clinical content.
  - _Requirements: 5.15, 8.5–8.7, 10.11, 11.12, 13.1–13.7, 14.1–14.3_

- [x] 5.2 Write the dashboard/report scope property test
  - **Property 17: Operational dashboards and reports are scope-consistent**
  - Generate operational records, approved quality projections, filters, and authorization scopes; verify rows, totals, variances, trends, and buckets equal the in-scope reference calculation and projected metrics retain read-only freshness labels.
  - **Validates: Requirements 5.15, 8.5–8.7, 10.11, 11.12, 13.1–13.7**

- [x] 5.3 Implement CTMS operational exports on shared export-job infrastructure
  - Add validated operational export filters/formats, CTMS content-owner discrimination, queued/running/completed/failed lifecycle, object storage, download controls, page/size limits, and download audit.
  - Export only CTMS-owned operational data and approved projection fields; exclude Clinical_Data, source documents, unrestricted messages, credentials, unrestricted clinical audit history, and unapproved EDC content.
  - Preserve EDC clinical export ownership and behavior and prevent CTMS routes from requesting or mutating clinical export content.
  - _Requirements: 2.8, 11.5, 12.8–12.10, 12.13, 14.3_

- [x] 5.4 Implement CTMS Operational_Attachments using shared storage primitives
  - Add operational attachment metadata, parent references, storage keys, ownership module, scope, retention, soft deletion, restore, and type/size validation.
  - Enforce CTMS authorization on upload/download/delete/restore and explicitly reject clinical attachment content through operational permissions; support metadata-only clinical references only under an approved EDC rule.
  - Audit each attachment action and ensure CTMS deletion/unavailability cannot alter EDC Clinical_Attachments.
  - _Requirements: 2.7, 10.11, 12.6–12.7, 12.13, 12.15, 14.2_

- [x] 5.5 Implement CTMS notifications, health responses, worker outage, and bounded backpressure
  - Trigger notifications for task assignment, monitoring assignment/reschedule/overdue, and Failed_Event; support Unread/Read/Archived state and scope filtering.
  - Implement authorized CTMS health output for worker status, pending/failed/conflict counts, projection lag, and last successful processing time with redaction.
  - Preserve accepted coordination events during worker outage and apply bounded queueing/backpressure without blocking EDC authentication, capture, audit, clinical export, or lifecycle operations.
  - _Requirements: 2.6, 13.8–13.16, 14.2–14.3_

- [x] 5.6 Write the export/attachment ownership property test
  - **Property 18: Export and attachment ownership is separated**
  - Generate export/attachment requests, owners, scopes, and content; verify shared lifecycle/download auditing, CTMS-only operational content, EDC-only clinical content, and denial of clinical reads through CTMS permissions.
  - **Validates: Requirements 2.7–2.8, 8.4, 10.11, 11.5, 12.6–12.12, 12.15**

- [x] 5.7 Write the optional-module resilience property test
  - **Property 19: Optional CTMS failure does not alter EDC behavior**
  - Generate EDC workflows with CTMS disabled, empty, or worker-unavailable; verify authentication, capture, clinical audit/export, protocol visits/casebook, and clinical lifecycle behavior is unchanged while accepted CTMS work remains queued/pending/unavailable.
  - **Validates: Requirements 12.14–12.15, 13.14–13.16, 14.4, 14.7, 14.10**

- [x] 5.8 Implement retention, archival, soft deletion, and immutable coordination-record controls
  - Add configured retention jobs for CTMS operational data, projections, event attempts/logs, Failed_Events, conflicts, exports, attachments, notifications, and audit-linked records without cascading into EDC clinical data.
  - Enforce actor/time/reason on soft deletion/archive/restore and reject update/physical deletion of completed coordination logs and immutable audit records.
  - _Requirements: 1.10, 3.10, 4.9, 5.14, 9.18, 12.4–12.5, 12.13–12.15_

- [x] 5.9 Write the retention and immutable-history property test
  - **Property 20: Soft deletion, archival, and immutable coordination retention preserve history**
  - Generate deletable records and retention states; verify configured soft-deletion/archive semantics, actor/time/reason, queryable references, and inability to update or physically delete completed coordination/audit records.
  - **Validates: Requirements 1.10, 3.10, 4.9, 5.14, 9.18, 12.4–12.5, 12.13**

### 6. CTMS API and frontend ownership visibility

- [x] 6.1 Implement authenticated CTMS API schemas, routes, and service wiring
  - Add Pydantic v2 request/response schemas and authenticated routes under `/api/v1/ctms` for operational studies/plans, sites/activation, enrollment targets/milestones, monitoring plans/activities, tasks/contacts, projections, coordination events, Failed_Events, conflicts, dashboards/reports, exports, and health.
  - Wire every route through request context, shared permission guards, canonical identity resolution, service transaction boundaries, pagination, standard errors, and `X-Request-ID`.
  - Do not add mutation routes for EDC Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV, review, freeze/lock, signatures, Clinical_Attachments, or clinical exports.
  - _Requirements: 1.5–1.9, 2.1–2.5, 10.11–10.16, 11.1–11.10, 14.1–14.3_

- [x] 6.2 Implement API ownership/error/pagination contract and OpenAPI publication
  - Publish CTMS enum values, ownership rules, event types, projection states, failure/conflict codes, pagination schemas, and error responses in OpenAPI.
  - Ensure ownership conflicts return explicit CTMS/coordination errors rather than redirecting commands, and failing responses contain only sanitized details.
  - _Requirements: 1.8, 8.8–8.9, 9.10–9.16, 11.7–11.10, 13.13_

- [x] 6.3 Build the frontend CTMS workspace and data-access foundation
  - Add authenticated CTMS routes under the existing AppShell, TanStack Query clients, typed API models, capability metadata, loading/error states, and permission-aware navigation for study/site workspaces.
  - Add views for operational profile/plans, site activation, enrollment/milestones, monitoring plans/activities, tasks/contacts, projections, reports/dashboards, exports, health, Failed_Events, and conflicts.
  - Preserve baseline EDC navigation and clinical indicators when CTMS is disabled, empty, or unavailable.
  - _Requirements: 11.11, 11.15–11.17, 13.16, 14.10_

- [x] 6.4 Implement ownership-visible status presentation and guarded CTMS actions
  - Display canonical EDC Study/Site/Subject/Visit identifiers, authoritative module badges, operational versus clinical status labels, projection source timestamps/freshness, and read-only indicators.
  - Keep monitoring activities distinct from protocol visits, operational subject status distinct from EDC clinical access state, and query follow-ups distinct from query lifecycle actions.
  - Hide unavailable actions or render access-denied views as convenience controls while retaining server-side authorization as authoritative; show only permissioned sanitized remediation actions.
  - _Requirements: 5.7, 6.14, 8.10–8.12, 10.11–10.16, 11.12–11.17_

- [x] 6.5 Write frontend component and route tests
  - Test CTMS route registration, permission-aware hiding/denial, canonical identifiers, authoritative-module badges, projection freshness, operational/protocol labels, enrollment/monitoring/task workflows, sanitized failure/conflict views, export filters, attachment access, and CTMS_Viewer read-only behavior.
  - Test EDC navigation/casebook/clinical indicators remain unchanged with CTMS disabled, empty, and worker-unavailable.
  - **Validates: Requirements 11.11–11.17, 13.16, 14.10**

- [x] 6.6 Write the API contract and non-leakage property test
  - **Property 21: CTMS API contracts are consistent and non-leaking**
  - Generate CTMS list requests, failing commands, sensitive values, prohibited payloads, and permission states; verify pagination, baseline error envelopes, `X-Request-ID`, and absence of stack traces, credentials, Clinical_Data, prohibited values, raw event bodies, and unrestricted messages.
  - **Validates: Requirements 2.5, 8.8–8.9, 11.1–11.10, 13.13**

- [x] 6.7 Write API security and EDC-boundary integration tests
  - Directly attempt EDC-owned field injection, competing clinical-subject creation, protocol-visit mutation, query mutation, prohibited projection fields, out-of-scope reads, viewer mutations, unauthorized replay/conflict resolution, clinical attachment access, and raw-event/log leakage.
  - Verify each denial leaves CTMS, projection, coordination, audit, and EDC clinical state unchanged.
  - **Validates: Requirements 1.5, 1.8, 5.6–5.13, 6.12–6.15, 8.8–8.10, 10.11–10.18, 11.6–11.10, 14.4–14.5**

### 7. Phased integration, qualification, and delivery verification

- [x] 7.1 Implement Phase 1 integration and boundary qualification tests
  - Verify additive migrations, canonical Study/Site references, operational study/site lifecycle, enrollment targets/milestones, CTMS roles/scope, audit atomicity, soft deletion, core dashboards, API scaffolding, and frontend workspace.
  - Independently snapshot EDC Study_Version, Clinical_Subject_Registry, Visit_Instance, Form_Instance, Field_Value, Query, Clinical_Attachment, and clinical-export state before/after CTMS commands and assert no unauthorized mutation.
  - **Validates: Requirements 14.1, 14.4–14.6**

- [x] 7.2 Implement Phase 2 coordination, monitoring, work, and resilience qualification tests
  - Verify immutable monitoring-plan versions, monitoring/protocol separation, tasks/follow-ups/contacts, operational attachments, projections, allowlists, outbox delivery, idempotency, ordering, notifications, and EDC operation during worker outage.
  - Include database rollback, duplicate delivery, stale event, frozen/locked visit, query follow-up, attachment access, and backpressure cases.
  - **Validates: Requirements 6.1–6.15, 7.1–7.12, 8.1–8.12, 9.1–9.18, 12.6–12.7, 13.8–13.16, 14.2, 14.7**

- [x] 7.3 Implement Phase 3 recovery, quality-signal, report/export, and production-qualification tests
  - Verify approved query summaries, Data_Quality_Signals, retry/backoff, Failed_Events, conflict resolution, current-policy replay, advanced reports, operational exports, health/lag, retention, backup/restore, and sanitized traceability.
  - Verify strict operational/clinical export and attachment separation and preserve EDC clinical behavior through CTMS disablement and worker failure.
  - **Validates: Requirements 8.3–8.12, 9.10–9.18, 12.8–12.15, 13.1–13.16, 14.3–14.10**

- [x] 7.4 Write the phased-delivery property test
  - **Property 22: Phase gates preserve the ownership boundary**
  - Generate enabled phase manifests and attempted operations; verify only capabilities in the enabled phase are writable, shared authorization/audit/identity safeguards remain active, and EDC clinical ownership remains enforced before and after each phase.
  - **Validates: Requirements 14.1–14.10**

- [x] 7.5 Write the final EDC regression and fallback suite
  - Run automated backend/frontend/security/API/export/permission/audit regression tests for EDC authentication, clinical capture, protocol visits/casebooks, queries, clinical exports, clinical attachments, and lifecycle behavior with CTMS disabled, empty, and worker-unavailable.
  - **Validates: Requirements 12.14–12.15, 13.14–13.16, 14.4, 14.7, 14.9–14.10**

### 8. Checkpoint — Phase 1 foundation

- Ensure all implemented Phase 1 tests pass, verify no EDC-owned records were modified by CTMS commands, and ask the user if questions arise.

### 9. Checkpoint — Phase 2 coordination and operational execution

- Ensure all implemented Phase 2 tests pass, verify projections are minimized/idempotent/ordered, and ask the user if questions arise.

### 10. Checkpoint — Phase 3 qualification

- Ensure all implemented Phase 3 tests pass, verify operational export/attachment privacy and EDC resilience, and ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and may be skipped for a faster MVP; core implementation tasks are not optional.
- Each property-based task maps to one property in the design and should use Hypothesis with at least 100 examples, deterministic in-memory repositories/fakes, and no external services.
- Property-based tests complement, rather than replace, database transaction, migration, queue, object-storage, notification, API-contract, security, frontend, performance, and qualification tests.
- The plan deliberately creates no duplicate clinical tables and no CTMS route that writes EDC clinical authority. Any shared primitive is reused without transferring ownership of its content semantics.
- Phase 1 delivers operational study/site/enrollment foundations and dashboards; Phase 2 delivers monitoring, work management, attachments, projections, coordination, and notifications; Phase 3 delivers quality signals, recovery, advanced reports/exports, health, retention, and qualification evidence.
- Convert each leaf task into a prompt for a code-generation LLM that implements that step incrementally, builds on prior steps, runs the relevant tests, and leaves every new component wired into an existing route/service or test harness.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5", "1.8", "2.1"] },
    { "id": 2, "tasks": ["1.6", "2.2", "2.4", "2.6"] },
    { "id": 3, "tasks": ["1.7", "2.3", "2.5", "2.7", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.5", "5.4"] },
    { "id": 5, "tasks": ["3.3", "3.4", "3.6", "3.7", "4.1", "6.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "4.4", "5.1", "5.3", "5.5", "6.2"] },
    { "id": 7, "tasks": ["4.5", "4.7", "4.12", "4.15", "5.2", "5.8", "6.3", "6.4"] },
    { "id": 8, "tasks": ["4.6", "4.8", "4.13", "5.6", "5.7", "5.9", "6.5", "6.6"] },
    { "id": 9, "tasks": ["4.9", "6.7"] },
    { "id": 10, "tasks": ["4.10", "4.11", "4.14"] },
    { "id": 11, "tasks": ["7.1", "7.2"] },
    { "id": 12, "tasks": ["7.3"] },
    { "id": 13, "tasks": ["7.4", "7.5"] }
  ]
}
```
