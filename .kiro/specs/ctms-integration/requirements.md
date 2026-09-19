# Requirements Document

## Introduction

This document specifies the CTMS_Module inside the Unified_Clinical_Platform. The CTMS_Module is a first-party module in the same authenticated application as the EDC_System. It owns operational planning and execution workflows, while the EDC_System remains authoritative for clinical study configuration, clinical subject records, protocol visits, clinical data, clinical quality workflows, and clinical exports.

The platform SHALL use explicit module ownership rather than treating the two modules as separate systems. Shared platform capabilities provide common identity, authorization, audit, request, notification, storage, export-job, observability, environment, and optional AI controls. Shared study, site, subject, and visit references SHALL point to one canonical identity. CTMS operational records SHALL reference EDC clinical records through approved CTMS_Operational_Projections and Coordination_Events without becoming a second clinical system of record.

The decomposition in this document is intentionally narrower than the complete EDC requirements document. The EDC requirements document remains authoritative for EDC-owned clinical behavior. This document defines the CTMS boundary, the shared platform boundary, the CTMS-owned operational behavior, and the internal coordination rules that connect them.

## Ownership and Decomposition Model

### Shared platform ownership

The Unified_Clinical_Platform owns capabilities that serve both modules and do not belong exclusively to EDC or CTMS:

- authentication, session management, and identity-provider controls;
- users, roles, invitations, and account lifecycle;
- Permission_Service resolution and study/site Authorization_Scope enforcement;
- the immutable Audit_Service and request context;
- Notification_Service primitives and delivery state;
- file storage primitives, metadata, access checks, and retention controls;
- export job infrastructure, status tracking, storage, and download controls;
- health checks, metrics, structured logs, tracing, and operational observability;
- isolated Environment configuration, secrets, storage, authentication, and logging;
- optional AI platform controls, scope filtering, confirmation, and audit hooks;
- the API_Layer conventions, error envelope, pagination, request identifiers, and OpenAPI publication;
- the Coordination_Service, which is an internal platform service used by approved module boundaries.

Shared ownership of a primitive does not transfer ownership of the data processed by that primitive. For example, the shared export job infrastructure runs both clinical EDC exports and CTMS operational exports, but EDC owns clinical export content and CTMS owns operational export content.

### CTMS ownership

The CTMS_Module owns the following operational capabilities:

- Operational_Study_Service: operational study profile, sponsor/phase/therapeutic area/indication planning metadata, operational lifecycle/readiness, study plans, enrollment plans, and operational study dashboards/reports;
- Operational_Site_Service: site operational profile, site activation/readiness, site contacts, monitoring readiness, operational site status, and operational site dashboards/reports;
- Enrollment_Service: recruitment and screening targets, enrollment plans, subject recruitment/enrollment milestones, operational subject status, and enrollment reports;
- Monitoring_Service: monitoring plans, monitoring activities/visits, CRA assignments, monitoring schedules, and completion evidence;
- Work_Management_Service: operational tasks, follow-ups, dependencies, escalations when enabled, operational contacts, and operational attachments;
- CTMS operational dashboards, reports, and exports;
- CTMS_Operational_Projections containing approved minimized EDC clinical progress or quality signals.

CTMS operational records SHALL reference canonical Study, Site, Subject, and Visit_Instance identities where applicable. CTMS SHALL not create a competing clinical identity, protocol visit schedule, clinical subject record, clinical query, or clinical data record.

### EDC ownership

The EDC_System remains authoritative for the following capabilities:

- clinical study configuration: Study_Version, protocol visit definitions used to initialize casebooks, eCRF metadata, forms, fields, code lists, edit checks, and clinical data-capture rules;
- Clinical_Subject_Registry: clinical subject identity/reference, subject-to-site binding, subject-to-study-version binding, clinical subject identifiers used for clinical capture, and clinical subject data;
- clinical subject lifecycle data where required to enforce EDC data access;
- Protocol_Visit_Service: Visit_Instances, protocol visit dates, visit-window calculation, missed visits, and the casebook schedule;
- Form_Instances, Field_Values, repeating records, clinical validation, and the clinical casebook;
- EDC Query lifecycle and complete query message history;
- SDV, clinical review, freeze/lock, and Electronic_Signature workflows;
- clinical Audit_Event content and clinical audit search/export behavior;
- clinical/source attachments and clinical data exports;
- EDC clinical dashboards and reports.

CTMS monitoring visits are operational records and are not Protocol_Visit_Service records. A Monitoring_Activity may reference an EDC Visit_Instance, but the reference does not permit CTMS to create, reschedule, complete, freeze, lock, or otherwise change the EDC Visit_Instance.

### Shared references and projection rules

Study and site identity are shared references with one canonical identity. CTMS owns operational attributes and EDC owns clinical configuration references. The read-only module view of the other module is an explicit projection, not an implicit shared write model.

CTMS owns operational subject enrollment status and milestones. EDC consumes a read-only projection for approved operational fields and retains clinical subject identity, clinical identifiers, study-version binding, and Clinical_Data. If EDC requires a status to authorize casebook access, the status SHALL be defined as either an EDC-owned derived/access field or an explicitly configured coordinated transition. No CTMS operational status SHALL silently change EDC clinical data or an EDC-owned status.

EDC clinical progress and quality metrics may be exposed to CTMS only through minimized, authorized, read-only CTMS_Operational_Projections. Clinical/source attachments remain governed by EDC. Operational attachments belong to CTMS and use shared file storage primitives. Clinical exports remain EDC-owned; operational exports remain CTMS-owned; export job infrastructure remains shared.

## Glossary

- **Unified_Clinical_Platform**: The single first-party application and service boundary containing the EDC_System, CTMS_Module, and shared platform services.
- **EDC_System**: The clinical data capture module that owns clinical configuration, clinical records, protocol visits, clinical quality workflows, and clinical exports.
- **CTMS_Module**: The first-party operational planning and execution module defined by this document.
- **Shared_Platform_Service**: A service owned by the Unified_Clinical_Platform for capabilities used by both EDC and CTMS.
- **Operational_Study_Service**: The CTMS service that manages operational study profiles, planning, readiness, milestones, and operational study reporting.
- **Operational_Site_Service**: The CTMS service that manages site operational profiles, activation, readiness, contacts, and operational site reporting.
- **Enrollment_Service**: The CTMS service that manages recruitment planning, enrollment targets, and operational subject milestones.
- **Monitoring_Service**: The CTMS service that manages monitoring plans, operational monitoring visits, CRA assignments, schedules, and completion evidence.
- **Work_Management_Service**: The CTMS service that manages operational tasks, follow-ups, dependencies, escalations, contacts, and operational attachments.
- **Clinical_Subject_Registry**: The EDC-owned registry of clinical subject identity/reference, site binding, study-version binding, clinical identifiers, and clinical lifecycle data required by EDC workflows.
- **Protocol_Visit_Service**: The EDC-owned service that defines protocol visits, creates Visit_Instances, calculates visit windows, and maintains casebook visit state.
- **Study**: The canonical shared study identity referenced by both modules.
- **Site**: The canonical shared site identity belonging to a Study and referenced by both modules.
- **Subject**: The EDC-owned clinical subject record referenced by CTMS enrollment projections and operational milestones.
- **Visit_Instance**: An EDC-owned protocol visit occurrence for a Subject.
- **Monitoring_Activity**: A CTMS-owned operational monitoring record that may reference a Visit_Instance without owning or changing it.
- **Clinical_Data**: EDC-owned Field_Values, Form_Instances, Form_Records, source documents, clinical query messages, SDV, review, freeze/lock, and signatures.
- **Operational_Data**: CTMS-owned planning and execution records, including operational study/site data, enrollment targets, milestones, monitoring records, tasks, contacts, and operational attachments.
- **Shared_Identity_Reference**: A stable canonical identifier for a Study, Site, Subject, or Visit_Instance used by both modules without duplicating authority.
- **CTMS_Operational_Projection**: A minimized, read-only CTMS or EDC read model containing approved fields from the other module.
- **Status_Ownership_Rule**: A versioned rule identifying the authoritative module, writable fields, projected fields, allowed transitions, and coordination behavior for a shared status or field.
- **Coordination_Service**: The shared internal service that publishes, consumes, orders, deduplicates, retries, and records approved Coordination_Events.
- **Coordination_Event**: An immutable internal event describing an approved change or projection update between services in the Unified_Clinical_Platform.
- **Coordination_Event_Log**: The immutable processing record for a Coordination_Event, including source, target, rule version, correlation identifier, outcome, and sanitized error details.
- **Coordination_Conflict**: A condition in which ownership, version, identity, authorization, or validation rules prevent an approved coordination action from being applied.
- **Failed_Event**: A Coordination_Event retained after bounded retry or validation failure and requiring authorized remediation.
- **Authorization_Scope**: The resolved set of permission grants for a User at system, study, and site scope.
- **Operational_Contact**: A CTMS-owned contact record for an operational study, site, role, organization, or work item.
- **Monitoring_Plan**: A CTMS-owned definition of monitoring objectives, activity types, cadence, responsibilities, and completion criteria.
- **Enrollment_Target**: A CTMS-owned planned recruitment, screening, or enrollment quantity for a study, site, cohort, or planning period.
- **Operational_Milestone**: A CTMS-owned planning or execution milestone for study, site, or subject operations.
- **Operational_Task**: A CTMS-owned actionable work item with an owner, scope, status, due date, and audit history.
- **Data_Quality_Signal**: An approved aggregate or minimized clinical progress measure exposed through a CTMS_Operational_Projection.
- **Operational_Attachment**: A CTMS-owned file metadata record and file content associated with operational work.
- **Clinical_Attachment**: An EDC-owned file metadata record and file content associated with a clinical object or source record.
- **Soft_Deletion**: Logical deletion that retains the record, deletion actor, timestamp, and reason without physical removal.
- **Correlation_Identifier**: A value linking a command, Coordination_Event, projection update, audit event, and resulting workflow outcome.
- **Idempotency_Key**: A stable key identifying one logical internal operation so replay does not create duplicate records or side effects.
- **Environment**: An isolated deployment tier with separate database, object storage, secrets, authentication, and logging configuration.

## Feature Ownership Matrix

The following matrix is the required disposition of the existing EDC capabilities when the CTMS_Module is added. A split means the existing broad capability is decomposed by data authority; it does not mean either module may write the other module's records.

| Existing capability or service | Current EDC requirement area | Disposition | Explicit ownership boundary |
|---|---:|---|---|
| Auth_Service | EDC Requirements 1, 3 | Shared Platform | Shared authentication, sessions, identity-provider validation, invitations, deactivation, and password/MFA controls; neither module owns a second identity system. |
| Permission_Service | EDC Requirements 2, 3 | Shared Platform | Shared permission resolution and study/site Authorization_Scope enforcement for both modules. |
| Audit_Service | EDC Requirement 18 and cross-cutting audit criteria | Shared Platform with module-owned event content | Shared immutable append-only primitive; EDC owns clinical audit events and CTMS owns operational audit events. |
| Request context and API conventions | EDC Requirements 21, 23 | Shared Platform | Shared request ID, correlation context, error envelope, pagination, validation, and route-to-service conventions. |
| Study_Service | EDC Requirement 4 | Split: Shared Platform, CTMS, EDC | Shared canonical Study identity; Operational_Study_Service owns operational profile/planning/readiness; EDC owns Study_Version and clinical configuration references. |
| Site_Service | EDC Requirement 6 | Split: Shared Platform, CTMS, EDC | Shared canonical Site identity; Operational_Site_Service owns operational profile/activation/contacts/readiness; EDC owns clinical site references and clinical configuration use. |
| Subject_Service | EDC Requirement 7 | Split: CTMS and EDC | Clinical_Subject_Registry owns identity, identifiers, site/study-version binding, clinical data, and EDC access state; Enrollment_Service owns operational recruitment/enrollment status and milestones, exposed to EDC as approved projections or explicit coordinated transitions. |
| Visit_Service | EDC Requirement 8 | Split: CTMS and EDC | Protocol_Visit_Service remains EDC-owned for protocol definitions, Visit_Instances, dates, windows, and casebooks; Monitoring_Service owns separate operational monitoring visits linked by reference only. |
| Form_Metadata_Service | EDC Requirement 9 | EDC | EDC owns eCRF metadata, forms, fields, code lists, and clinical configuration. |
| Data_Capture_Service | EDC Requirement 10 | EDC | EDC owns Field_Values, Form_Instances, clinical validation, submission, and clinical data changes. |
| Repeating_Record_Service | EDC Requirement 11 | EDC | EDC owns clinical repeating records and their history. |
| Edit_Check_Engine | EDC Requirement 12 | EDC | EDC owns clinical edit checks and validation rules; CTMS may consume approved aggregate signals only. |
| Query_Service | EDC Requirement 13 | EDC | EDC owns query status transitions, messages, affected clinical objects, and clinical query exports; CTMS may create operational follow-up tasks without changing queries. |
| SDV_Service | EDC Requirement 14 | EDC | EDC owns SDV state and progress. |
| Review_Service | EDC Requirement 15 | EDC | EDC owns clinical review state and progress. |
| Lock_Service | EDC Requirement 16 | EDC | EDC owns clinical freeze and lock state; CTMS operational scheduling remains writable when an EDC visit is frozen or locked, without changing clinical data. |
| Signature_Service | EDC Requirement 17 | EDC | EDC owns electronic signatures and signed clinical data. |
| Dashboard_Service | EDC Requirement 20 | Split: Shared Platform, CTMS, EDC | Shared dashboard primitives and scope filtering; CTMS owns operational dashboards/reports; EDC owns clinical dashboards/reports. |
| Export_Service | EDC Requirement 19 | Split: Shared Platform, CTMS, EDC | Shared export job infrastructure and storage/download controls; CTMS owns operational export content; EDC owns clinical export content. |
| File_Attachment_Service | EDC Requirement 27 | Split: Shared Platform, CTMS, EDC | Shared file storage primitives and access controls; EDC owns Clinical_Attachments; CTMS owns Operational_Attachments. |
| Notification_Service | EDC Requirement 28 | Shared Platform with module-owned triggers | Shared notification records and delivery state; EDC and CTMS own their event triggers and recipients. |
| health, metrics, logs, tracing | EDC Requirement 30 | Shared Platform | Shared health/observability mechanisms with module-specific metrics and sanitized structured fields. |
| Environment management | EDC Requirement 25 | Shared Platform | Shared isolated deployment, database, storage, secrets, authentication, logging, retention, backup, and restore controls. |
| AI_Assistant_Service | EDC Requirement 31 | Shared Platform with module-scoped controls | Shared optional AI transport, scope filtering, human confirmation, and audit hooks; EDC and CTMS separately authorize context and actions. |
| Clinical study configuration | EDC Requirements 5, 8, 9, 12 | EDC | Study_Version, protocol visits, eCRF metadata, code lists, and edit checks remain EDC-owned. |
| Clinical subject registry and casebook | EDC Requirements 7, 8, 10, 11 | EDC | Clinical subject identity, clinical identifiers, study-version binding, Visit_Instances, Form_Instances, Field_Values, repeating records, and casebook remain EDC-owned. |
| Clinical quality and governance | EDC Requirements 13–18 | EDC | Queries/messages, SDV, review, freeze/lock, signatures, and clinical audit records remain EDC-owned. |
| Clinical data export | EDC Requirement 19 | EDC | Clinical data and clinical audit exports remain EDC-owned, using shared job infrastructure. |

## Requirements

### Requirement 1: Explicit module boundary and canonical identity

**User Story:** As a platform owner, I want module ownership and canonical references to be explicit, so that operational workflows do not create a second clinical system of record.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL expose the EDC_System and CTMS_Module as first-party modules within one authenticated application boundary.
2. THE Unified_Clinical_Platform SHALL assign exactly one authoritative module to every persisted field of a Study, Site, Subject, Visit_Instance, projection, and operational record.
3. THE Unified_Clinical_Platform SHALL use one canonical Shared_Identity_Reference for each Study and Site used by both modules.
4. THE Unified_Clinical_Platform SHALL use the EDC clinical record identifier as the canonical reference for each Subject and Visit_Instance used by CTMS projections.
5. THE Unified_Clinical_Platform SHALL reject a CTMS command that attempts to create a competing clinical Subject, Visit_Instance, Field_Value, Form_Instance, Query, or Study_Version.
6. THE Unified_Clinical_Platform SHALL expose read-only projections when one module needs data owned by the other module.
7. WHEN a shared identity is created or linked, THE Coordination_Service SHALL record the source identifier, target reference, ownership rule version, and Correlation_Identifier.
8. IF a command contains a field owned by the other module, THEN THE Coordination_Service SHALL reject the command without changing either authoritative record.
9. THE Unified_Clinical_Platform SHALL store timestamps as timezone-aware UTC values and SHALL convert them to local time only in the Frontend_Application.
10. THE CTMS_Module SHALL apply Soft_Deletion to each CTMS record that supports deletion.

### Requirement 2: Shared platform services

**User Story:** As a security and quality lead, I want platform controls shared by both modules, so that CTMS actions receive the same governance as EDC actions.

#### Acceptance Criteria

1. THE Auth_Service SHALL provide authentication, session management, identity-provider validation, logout, password reset, MFA, invitation acceptance, and account deactivation for both modules.
2. THE Permission_Service SHALL resolve one Authorization_Scope for a User across system, study, and site permissions.
3. THE Permission_Service SHALL enforce Authorization_Scope on every EDC and CTMS route and object operation.
4. THE Audit_Service SHALL provide an immutable append-only record primitive for EDC clinical events and CTMS operational events.
5. THE Request_Context_Service SHALL assign a request identifier and Correlation_Identifier at request ingress and propagate both to service logs and audit events.
6. THE Notification_Service SHALL provide shared notification persistence and delivery state with module-specific event ownership.
7. THE File_Storage_Service SHALL provide shared file storage, metadata, access, retention, and soft-deletion primitives without owning clinical or operational content semantics.
8. THE Export_Job_Service SHALL provide shared export job status, queueing, storage, download, and failure handling without owning export content semantics.
9. THE Health_Observability_Service SHALL provide shared health endpoints, metrics, structured logs, tracing, and readiness signals.
10. THE Environment_Service SHALL isolate database, object storage, secrets, authentication, and logging configuration for every Environment.
11. WHERE the optional AI capability is enabled, THE AI_Platform_Service SHALL enforce module-specific Authorization_Scope, data minimization, human confirmation, and audit hooks before an AI action is applied.

### Requirement 3: Operational study management

**User Story:** As a study operations lead, I want operational study planning and readiness managed in CTMS, so that operational decisions are separated from clinical configuration.

#### Acceptance Criteria

1. WHEN an authorized User creates an operational study profile, THE Operational_Study_Service SHALL persist the canonical Study reference and the CTMS-owned sponsor, phase, therapeutic area, indication, operational owner, and planning metadata.
2. THE Operational_Study_Service SHALL persist study plans, enrollment plans, operational milestones, readiness criteria, and operational status separately from Study_Version and clinical configuration.
3. THE Operational_Study_Service SHALL support the operational study statuses Draft, Planning, Ready, Active, Enrollment Closed, Suspended, and Closed.
4. WHILE an operational study is Active, THE Operational_Study_Service SHALL retain each operational status change with actor, UTC timestamp, and reason.
5. WHEN an authorized User updates operational study metadata, THE Audit_Service SHALL record a CTMS operational Audit_Event without changing EDC Study_Version or clinical metadata.
6. THE Operational_Study_Service SHALL preserve the canonical EDC Study identifier as a read-only reference.
7. THE EDC_System SHALL expose a read-only projection of approved CTMS operational study status when the configured Status_Ownership_Rule permits that projection.
8. THE Operational_Study_Service SHALL not change protocol visit definitions, eCRF metadata, clinical edit checks, Clinical_Subject_Registry records, or Clinical_Data.
9. IF an authorized User requests an operational study outside the User's Authorization_Scope, THEN THE Operational_Study_Service SHALL reject the request.
10. WHEN an operational study is archived, THE Operational_Study_Service SHALL retain its operational records and linked canonical identity.

### Requirement 4: Operational site management

**User Story:** As a CTMS operations user, I want site readiness and activation managed operationally, so that site execution is visible without changing clinical site configuration.

#### Acceptance Criteria

1. WHEN an authorized User creates an operational site profile, THE Operational_Site_Service SHALL persist the canonical Site reference and CTMS-owned operational profile fields.
2. THE Operational_Site_Service SHALL manage site activation actions, readiness criteria, monitoring readiness, Operational_Contacts, responsible roles, planned dates, and completion evidence.
3. THE Operational_Site_Service SHALL support the operational site statuses Not Started, In Progress, Ready for Activation, Active, Suspended, and Closed.
4. WHEN a site activation action is completed, THE Operational_Site_Service SHALL record the completion actor, UTC timestamp, and evidence reference.
5. WHEN operational site status changes, THE Coordination_Service SHALL publish only the approved CTMS_Operational_Projection fields to EDC.
6. THE EDC_System SHALL expose a read-only projection of CTMS-owned operational site status when the configured Status_Ownership_Rule permits that projection.
7. THE Operational_Site_Service SHALL preserve the canonical EDC Site identifier as a read-only reference.
8. THE Operational_Site_Service SHALL not change EDC clinical site configuration, study-version binding, subject records, Visit_Instances, or Clinical_Data.
9. WHEN an EDC Site is archived, THE Operational_Site_Service SHALL mark linked operational records Archived or Site Archived according to the configured rule.
10. IF an authorized User requests a site operation outside the User's Authorization_Scope, THEN THE Operational_Site_Service SHALL reject the request without changing operational or clinical state.
11. IF an authorized User requests a duplicate activation action for the same canonical Site and action type, THEN THE Operational_Site_Service SHALL return the existing action and SHALL not create a duplicate.

### Requirement 5: Enrollment and subject operations

**User Story:** As a study operations lead, I want recruitment and enrollment progress managed in CTMS, so that operational planning reflects trial execution without duplicating clinical subjects.

#### Acceptance Criteria

1. WHEN an authorized User creates an Enrollment_Target, THE Enrollment_Service SHALL persist the canonical Study or Site reference, target type, target quantity, planning period, owner, and status.
2. THE Enrollment_Service SHALL support recruitment, screening, and enrollment targets as distinct operational target types.
3. THE Enrollment_Service SHALL support Enrollment_Target statuses Draft, Active, Met, Expired, and Cancelled.
4. WHEN an authorized User records an operational subject milestone, THE Enrollment_Service SHALL persist the canonical EDC Subject reference, approved pseudonym or reference, milestone type, milestone date, and operational status.
5. THE Enrollment_Service SHALL support the operational subject statuses Screening, Screen Failed, Enrolled, Randomized, On Treatment, Completed, Early Terminated, Lost to Follow-up, and Withdrawn.
6. THE Enrollment_Service SHALL not create or modify a Clinical_Subject_Registry record when recording an operational milestone.
7. THE Enrollment_Service SHALL not replace the EDC clinical subject identifier or study-version binding with an operational display identifier.
8. WHEN an EDC Subject reaches a status included in the active Status_Ownership_Rule, THE Coordination_Service SHALL publish the approved minimized subject-status projection to CTMS.
9. WHEN a CTMS operational subject status changes, THE Coordination_Service SHALL publish only the explicitly approved projection or coordinated transition to EDC.
10. THE EDC_System SHALL consume the CTMS operational subject status as read-only unless an explicit Status_Ownership_Rule grants a named coordinated transition.
11. IF an operational subject status is not covered by a configured Status_Ownership_Rule, THEN THE Enrollment_Service SHALL retain the CTMS status and SHALL not request an EDC status change.
12. THE CTMS_Module SHALL exclude Field_Values, source documents, unrestricted clinical notes, and clinical query messages from every subject operational projection.
13. IF a coordination command contains a prohibited clinical field or an identifier outside the approved subject identifier policy, THEN THE Coordination_Service SHALL reject the command and retain only a sanitized Coordination_Event_Log entry.
14. WHEN an EDC Subject is withdrawn or soft-deleted, THE Enrollment_Service SHALL retain the correlation record and apply the configured operational retention status.
15. THE Enrollment_Service SHALL provide enrollment reports from CTMS-owned targets and approved operational subject projections within the User's Authorization_Scope.

### Requirement 6: Protocol visits and operational monitoring visits

**User Story:** As a CRA, I want monitoring visits planned separately from protocol visits, so that monitoring execution can be managed without changing the clinical casebook schedule.

#### Acceptance Criteria

1. THE EDC_System SHALL remain authoritative for protocol visit definitions used to initialize casebooks.
2. THE EDC_System SHALL remain authoritative for Visit_Instances, protocol visit dates, visit-window calculation, missed-visit status, and casebook visit state.
3. THE Monitoring_Service SHALL persist Monitoring_Plans with version, objectives, activity types, cadence, responsibilities, scope, and completion criteria.
4. WHILE a Monitoring_Plan is Published, THE Monitoring_Service SHALL reject direct modification to the published plan.
5. WHEN an authorized User amends a published Monitoring_Plan, THE Monitoring_Service SHALL create a new Draft version and require an amendment reason.
6. THE Monitoring_Service SHALL support Monitoring_Activity types Site Initiation, Routine Monitoring, Close-out, Remote Review, and Triggered Review.
7. WHEN an authorized User schedules a Monitoring_Activity, THE Monitoring_Service SHALL persist the canonical Study and Site references, activity type, planned date, assigned CRA, status, and optional EDC Visit_Instance reference.
8. WHEN an authorized User assigns a Monitoring_Activity, THE Monitoring_Service SHALL verify the assignee's study and site Authorization_Scope.
9. WHEN an authorized User reschedules a Monitoring_Activity, THE Monitoring_Service SHALL retain the prior date and rescheduling reason.
10. WHEN an authorized User completes a Monitoring_Activity, THE Monitoring_Service SHALL persist completion date, completion evidence, completion notes, and completion actor.
11. WHEN an authorized User cancels a Monitoring_Activity, THE Monitoring_Service SHALL persist the cancellation reason and cancellation actor.
12. WHILE an EDC Visit_Instance is Frozen or Locked, THE Monitoring_Service SHALL permit CTMS scheduling and completion changes.
13. WHILE an EDC Visit_Instance is Frozen or Locked, THE Monitoring_Service SHALL not modify the Visit_Instance or its Clinical_Data.
14. WHEN a Monitoring_Activity changes, THE Audit_Service SHALL record the optional EDC Visit_Instance identifier when present.
15. THE Monitoring_Service SHALL not create or modify an EDC Visit_Instance as a result of monitoring scheduling or completion.

### Requirement 7: Operational work management and contacts

**User Story:** As a study operations user, I want operational work assigned and tracked in CTMS, so that follow-up work is accountable without becoming clinical data.

#### Acceptance Criteria

1. WHEN an authorized User creates an Operational_Task, THE Work_Management_Service SHALL persist the title, description, owner, canonical Study or Site scope, due date, priority, status, and Correlation_Identifier.
2. THE Work_Management_Service SHALL support Operational_Task statuses Open, In Progress, Blocked, Completed, Cancelled, and Archived.
3. WHEN an authorized User creates an Operational_Contact, THE Work_Management_Service SHALL persist the contact name, role, organization, canonical Study or Site scope, and contact status.
4. THE Work_Management_Service SHALL support Operational_Contact statuses Active, Inactive, and Archived.
5. WHEN a CTMS user records a clinical-query follow-up, THE Work_Management_Service SHALL create an Operational_Task with the EDC Query identifier and SHALL not change the EDC Query.
6. WHEN an authorized User completes an operational follow-up, THE Work_Management_Service SHALL retain the linked EDC identifier and completion history.
7. WHERE dependencies or escalations are enabled for the Environment, THE Work_Management_Service SHALL persist dependency links, escalation status, and escalation reason as CTMS-owned Operational_Data.
8. WHEN an Operational_Task changes status, THE Work_Management_Service SHALL retain status history and the reason required by the configured transition.
9. WHEN an Operational_Task is assigned to a User, THE Notification_Service SHALL create a notification for the assigned User.
10. THE Work_Management_Service SHALL prevent assignment of an Operational_Task to an inactive User.
11. WHEN CTMS Operational_Data changes, THE Audit_Service SHALL record the actor, UTC timestamp, scope, action, changed fields, and Correlation_Identifier.
12. THE Work_Management_Service SHALL not persist Clinical_Data, source documents, unrestricted query messages, or clinical audit history in an operational task or contact.

### Requirement 8: Projection minimization and clinical boundary

**User Story:** As a data-protection lead, I want approved operational projections to contain only the minimum required clinical signals, so that CTMS can support operations without exposing or modifying unrestricted clinical data.

#### Acceptance Criteria

1. THE Coordination_Service SHALL validate every CTMS_Operational_Projection against a versioned field allowlist before persistence.
2. THE CTMS_Module SHALL permit subject projections to contain only the approved subject reference or pseudonym, canonical Site reference, operational status, approved milestone date, and source version metadata.
3. THE CTMS_Module SHALL permit query projections to contain only the approved query identifier, type, canonical Study and Site references, approved subject pseudonym, form or visit reference, timestamps, and summary text.
4. THE CTMS_Module SHALL exclude Clinical_Data values, source documents, unrestricted query message history, credentials, and unrestricted clinical audit history from CTMS_Operational_Projections.
5. THE CTMS_Module SHALL permit approved aggregate Data_Quality_Signals for open queries, overdue queries, form completion, SDV progress, and review progress.
6. WHEN a Data_Quality_Signal is calculated, THE Dashboard_Service SHALL calculate it only from authorized source records or approved projections.
7. THE CTMS_Module SHALL publish Data_Quality_Signals only for the requesting User's Authorization_Scope.
8. IF a projection update contains a field outside its allowlist, THEN THE Coordination_Service SHALL reject the update and retain a sanitized field fingerprint.
9. WHEN a projection update is rejected, THE Coordination_Service SHALL exclude prohibited values from the retained failure record.
10. THE CTMS_Service SHALL not treat a projected subject, visit, query, or quality status as authority to modify EDC Clinical_Data.
11. WHEN an EDC query projection is refreshed, THE Coordination_Service SHALL retain the source query identifier, source status timestamp, rule version, and Correlation_Identifier.
12. IF a query projection is older than the current EDC Query state, THEN THE Coordination_Service SHALL create a Coordination_Conflict and SHALL leave the current projection unchanged.

### Requirement 9: Internal coordination, idempotency, ordering, and recovery

**User Story:** As a platform engineer, I want deterministic internal coordination, so that module projections remain safe without duplicating authority.

#### Acceptance Criteria

1. THE Coordination_Service SHALL support synchronous transaction boundaries for atomic changes within one service.
2. THE Coordination_Service SHALL support asynchronous Coordination_Events for approved updates to a separate module projection.
3. WHEN a Coordination_Event is accepted, THE Coordination_Service SHALL assign an Idempotency_Key and Correlation_Identifier.
4. WHEN a Coordination_Event is accepted, THE Coordination_Service SHALL record the source service, target projection, entity type, source identifier, and Status_Ownership_Rule version.
5. WHEN a Coordination_Event is processed more than once with the same Idempotency_Key, THE Coordination_Service SHALL return the prior outcome.
6. WHEN a Coordination_Event is processed more than once with the same Idempotency_Key, THE Coordination_Service SHALL not create a duplicate record or side effect.
7. WHEN a Coordination_Event succeeds, THE Coordination_Service SHALL record the resulting projection identifier and outcome.
8. WHEN a Coordination_Event is skipped because the projection is current, THE Coordination_Service SHALL record the skipped outcome and current version.
9. WHEN source ordering is provided for one correlated entity, THE Coordination_Service SHALL apply events in source order.
10. IF a Coordination_Event references an unknown canonical record, THEN THE Coordination_Service SHALL create a Failed_Event with reason `RECORD_NOT_FOUND`.
11. IF a Coordination_Event references more than one matching canonical record, THEN THE Coordination_Service SHALL create a Failed_Event with reason `AMBIGUOUS_REFERENCE`.
12. IF a Coordination_Event violates a Status_Ownership_Rule, THEN THE Coordination_Service SHALL create a Coordination_Conflict and SHALL not change the authoritative record.
13. IF an internal worker encounters a retryable storage or service error, THEN THE Coordination_Service SHALL retry according to a configured bounded backoff policy.
14. IF a Coordination_Event exceeds the configured retry limit, THEN THE Coordination_Service SHALL place the event in Failed_Event status.
15. IF a Coordination_Event fails schema, authorization, ownership, or data-minimization validation, THEN THE Coordination_Service SHALL retain a sanitized failure outcome and SHALL not partially mutate the target.
16. WHEN a CTMS_Admin replays a Failed_Event, THE Coordination_Service SHALL revalidate current Authorization_Scope, Status_Ownership_Rule, identity references, and projection allowlists.
17. WHEN a CTMS projection is rebuilt, THE Coordination_Service SHALL derive it from authoritative records and SHALL not alter EDC or CTMS authoritative source records.
18. THE Coordination_Service SHALL preserve the source event, target projection, rule version, and final outcome for every completed event.

### Requirement 10: Authorization and role boundaries

**User Story:** As a security officer, I want CTMS actions constrained by the shared EDC authorization model, so that operational information is limited to assigned study and site scope.

#### Acceptance Criteria

1. THE Permission_Service SHALL support the CTMS_Admin permission set.
2. THE Permission_Service SHALL support the CTMS_Operations_User permission set.
3. THE Permission_Service SHALL support the CTMS_Viewer permission set.
4. THE Permission_Service SHALL support system, study, and site scope for CTMS permissions.
5. WHEN a User creates or changes an operational study plan, THE Permission_Service SHALL require the operational-study-management permission.
6. WHEN a User changes an Operational_Site_Service record, THE Permission_Service SHALL require the operational-site-management permission.
7. WHEN a User schedules or assigns a Monitoring_Activity, THE Permission_Service SHALL require the monitoring-activity-management permission.
8. WHEN a User changes an Enrollment_Target, THE Permission_Service SHALL require the enrollment-management permission.
9. WHEN a User creates or resolves a Coordination_Conflict, THE Permission_Service SHALL require the conflict-management permission.
10. WHEN a User replays a Failed_Event, THE Permission_Service SHALL require the coordination-replay permission.
11. WHEN a User views CTMS operational data, THE Permission_Service SHALL filter records by Authorization_Scope.
12. IF a CTMS_Viewer mutates CTMS Operational_Data, THEN THE API_Layer SHALL return the baseline authorization error.
13. IF a CTMS_Viewer mutates a Coordination_Event_Log or Failed_Event, THEN THE API_Layer SHALL return the baseline authorization error.
14. IF a User lacks the required study or site scope, THEN THE CTMS_Module SHALL reject the operation without changing CTMS, projection, or EDC state.
15. THE CTMS_Module SHALL enforce authorization on the server side.
16. THE CTMS_Module SHALL not use Frontend_Application checks as the sole authorization control.
17. WHEN a shared-platform User is deactivated, THE Auth_Service SHALL revoke active sessions and retain operational and clinical history.
18. WHEN a User is removed from a site scope, THE Permission_Service SHALL deny new site-scoped actions while retaining prior audit records.

### Requirement 11: API and frontend ownership presentation

**User Story:** As a study team member, I want CTMS APIs and screens to show ownership clearly, so that users do not mistake operational status for clinical authority.

#### Acceptance Criteria

1. THE API_Layer SHALL expose CTMS endpoints under `/api/v1/ctms`.
2. THE API_Layer SHALL validate CTMS request and response bodies with Pydantic v2 schemas.
3. THE API_Layer SHALL expose authenticated endpoints for operational study profiles, plans, Enrollment_Targets, Operational_Milestones, Operational_Tasks, Operational_Contacts, Monitoring_Plans, and Monitoring_Activities.
4. THE API_Layer SHALL expose authenticated endpoints for CTMS_Operational_Projections, Coordination_Event_Logs, Failed_Events, and Coordination_Conflicts.
5. THE API_Layer SHALL expose authenticated endpoints for CTMS dashboards, reports, and operational exports.
6. THE API_Layer SHALL not expose CTMS endpoints that directly mutate EDC Study_Version, clinical subjects, Visit_Instances, Form_Instances, Field_Values, Queries, SDV, review, freeze/lock, or signatures.
7. WHEN a CTMS API request fails, THE API_Layer SHALL return the baseline EDC error envelope and `X-Request-ID`.
8. WHEN a CTMS API request fails, THE API_Layer SHALL exclude stack traces, secret values, unrestricted clinical data, prohibited projection values, and raw event bodies from error details.
9. WHEN a list CTMS endpoint is requested, THE API_Layer SHALL return `items`, `page`, `page_size`, and `total`.
10. THE API_Layer SHALL publish an OpenAPI contract containing CTMS enum values, ownership rules, event types, and error codes.
11. THE Frontend_Application SHALL provide permission-aware views for CTMS study planning, site activation, monitoring, enrollment, milestones, tasks, contacts, dashboards, reports, operational exports, Failed_Events, and Coordination_Conflicts.
12. WHEN a User opens a CTMS study, site, subject, or monitoring view, THE Frontend_Application SHALL display the canonical EDC identifier and the authoritative module for each shared status.
13. WHEN a User opens a Monitoring_Activity view, THE Frontend_Application SHALL display its operational status, assigned CRA, planned date, completion evidence, linked EDC Visit_Instance when present, and last change time.
14. WHEN a User reviews a Failed_Event or Coordination_Conflict, THE Frontend_Application SHALL display only permissioned remediation actions and sanitized failure details.
15. WHILE a User lacks a CTMS permission, THE Frontend_Application SHALL hide the corresponding action or render an access-denied view.
16. THE Frontend_Application SHALL treat frontend permission checks as convenience controls while the API_Layer remains authoritative.
17. THE Frontend_Application SHALL preserve EDC clinical status indicators and navigation when CTMS functionality is disabled or has no operational records.

### Requirement 12: Audit, attachments, exports, and privacy

**User Story:** As a quality lead, I want shared controls to preserve module-specific authority, so that operational records and clinical records remain attributable and separated.

#### Acceptance Criteria

1. WHEN CTMS Operational_Data changes, THE Audit_Service SHALL record an immutable CTMS operational Audit_Event.
2. WHEN a CTMS_Operational_Projection changes, THE Audit_Service SHALL record the projection source, target, actor or worker, UTC timestamp, scope, and Correlation_Identifier.
3. WHEN a Coordination_Event, Failed_Event, or Coordination_Conflict is created or resolved, THE Audit_Service SHALL record an immutable audit event with sanitized details.
4. THE Coordination_Service SHALL persist Coordination_Event_Logs as immutable records.
5. THE Coordination_Service SHALL reject updates and physical deletion of completed Coordination_Event_Logs.
6. WHEN an Operational_Attachment is uploaded, downloaded, deleted, or restored, THE File_Storage_Service SHALL enforce CTMS scope and THE Audit_Service SHALL record the action.
7. THE CTMS_Module SHALL not access or export Clinical_Attachments unless an explicit EDC permission and approved projection rule permit metadata-only reference.
8. WHEN an authorized User requests an operational export, THE Export_Job_Service SHALL create a job and THE CTMS_Module SHALL provide only CTMS-owned operational content and approved projections.
9. WHEN an authorized User requests a clinical export, THE EDC_System SHALL remain responsible for clinical content, clinical filtering, and clinical audit behavior.
10. WHEN an authorized User downloads an operational export, THE Export_Job_Service SHALL record the download in the shared audit trail with CTMS scope.
11. THE CTMS_Module SHALL exclude Clinical_Data values, source documents, credentials, unrestricted clinical messages, and unrestricted clinical audit history from Operational_Data and operational exports.
12. THE CTMS_Module SHALL define an allowlist of fields permitted in each CTMS_Operational_Projection and operational export.
13. THE Unified_Clinical_Platform SHALL retain CTMS records, coordination records, and audit records for the configured retention period.
14. THE Unified_Clinical_Platform SHALL preserve Clinical_Data when CTMS records, projections, or coordination workers fail.
15. THE EDC_System SHALL retain clinical/source attachment authority and clinical export authority when CTMS operational records are deleted or unavailable.

### Requirement 13: Dashboards, reports, notifications, health, and resilience

**User Story:** As a study operations lead, I want scoped operational reporting and resilient notifications, so that CTMS supports decisions without degrading clinical workflows.

#### Acceptance Criteria

1. WHEN an authorized User requests an operational study dashboard, THE Dashboard_Service SHALL return CTMS enrollment targets, approved operational progress, operational study readiness, site activation status, upcoming Monitoring_Activities, overdue Operational_Tasks, milestone progress, and approved Data_Quality_Signals.
2. WHEN an authorized User requests an operational site dashboard, THE Dashboard_Service SHALL return CTMS activation actions, Enrollment_Target progress, Monitoring_Activities, assigned Operational_Tasks, contacts, and approved data-quality progress.
3. WHEN an authorized User requests a monitoring report, THE Dashboard_Service SHALL return planned, completed, overdue, rescheduled, and cancelled Monitoring_Activities for the requested scope.
4. WHEN an authorized User requests an enrollment report, THE Dashboard_Service SHALL return CTMS target, approved operational actual, variance, and milestone trend data for the requested scope.
5. WHEN an authorized User requests an operational task report, THE Dashboard_Service SHALL return counts by owner, status, priority, and due-date category.
6. THE Dashboard_Service SHALL compute CTMS dashboards and reports only from records within the User's Authorization_Scope.
7. THE Dashboard_Service SHALL label projected clinical metrics as read-only projections and SHALL identify their source timestamp.
8. WHEN a Monitoring_Activity is assigned or rescheduled, THE Notification_Service SHALL create a notification for the assigned User.
9. WHEN a Monitoring_Activity becomes overdue, THE Notification_Service SHALL create a notification for authorized CTMS operational recipients.
10. WHEN a Coordination_Event enters Failed_Event status, THE Notification_Service SHALL notify an authorized CTMS_Admin.
11. THE Notification_Service SHALL support the statuses Unread, Read, and Archived for CTMS notifications.
12. WHEN an authorized CTMS_Admin requests CTMS health, THE Health_Observability_Service SHALL return worker status, pending event count, failed event count, conflict count, projection lag, and last successful processing time.
13. THE Health_Observability_Service SHALL exclude Clinical_Data values, sensitive audit contents, credentials, and raw event bodies from health responses and structured logs.
14. IF a CTMS worker is unavailable, THEN THE Coordination_Service SHALL retain accepted events and SHALL not block EDC clinical capture, clinical audit, authentication, clinical export, or clinical workflow operations.
15. IF coordination volume exceeds configured capacity, THEN THE Coordination_Service SHALL apply bounded backpressure or queueing while preserving accepted event ordering and idempotency.
16. THE CTMS_Module SHALL continue core EDC operations when no CTMS operational records have been configured.

### Requirement 14: Phased delivery and verification

**User Story:** As a delivery lead, I want the CTMS boundary delivered in independently verifiable phases, so that operational capability expands without destabilizing EDC clinical work.

#### Acceptance Criteria

1. THE CTMS_Module SHALL deliver Phase 1 with canonical study and site references, Operational_Study_Service, Operational_Site_Service, enrollment planning, operational milestones, CTMS roles, scoped authorization, shared audit use, and operational dashboards.
2. THE CTMS_Module SHALL deliver Phase 2 with Monitoring_Service, Operational_Task and Operational_Contact workflows, Operational_Attachments, CTMS_Operational_Projections, Coordination_Events, and notifications.
3. THE CTMS_Module SHALL deliver Phase 3 with approved query summaries, Data_Quality_Signals, retry handling, Failed_Event handling, Coordination_Conflict resolution, advanced operational reports, operational exports, and production qualification evidence.
4. THE EDC_System SHALL independently verify that CTMS commands cannot modify EDC-owned Study_Version, clinical subject identity, protocol Visit_Instances, Form_Instances, Field_Values, Query messages, SDV, review, freeze/lock, signatures, Clinical_Attachments, or clinical exports.
5. THE Unified_Clinical_Platform SHALL independently verify shared Authorization_Scope enforcement for CTMS actions and EDC actions.
6. THE Unified_Clinical_Platform SHALL independently verify immutable audit behavior, transaction atomicity, projection minimization, and canonical identity resolution for CTMS actions.
7. THE EDC_System SHALL independently verify that protocol visit windows and casebook initialization remain EDC-owned after Monitoring_Service delivery.
8. THE Unified_Clinical_Platform SHALL independently verify idempotency, ordering, projection rebuild safety, retries, Failed_Events, and Coordination_Conflicts.
9. THE Unified_Clinical_Platform SHALL provide automated backend, frontend, permission, audit, security, coordination, report, and export tests for every delivered CTMS phase.
10. THE Frontend_Application SHALL preserve all baseline EDC clinical workflows when CTMS functionality is disabled or has no configured operational records.

## Correctness Properties

Each property below SHALL map to one executable property-based test unless the implementation team documents an equivalent model-based test. Pure internal logic SHALL use generated identifiers, scopes, statuses, ownership rules, records, projections, event sequences, and failure modes. Tests SHALL use in-memory repositories and deterministic worker fakes rather than services outside the Unified_Clinical_Platform.

### Property 1: Explicit ownership boundary

*For any* shared record and Status_Ownership_Rule, only the authoritative module can change an owned field; the other module can read or receive an approved projection but cannot change the authoritative record or create a competing clinical record.

**Validates:** Requirements 1.1–1.10, 3.6–3.8, 4.5–4.8, 5.6–5.11, 6.1–6.2, 6.12–6.15, 11.6, 12.7–12.9.

### Property 2: Canonical identity stability

*For any* Study, Site, Subject, or Visit_Instance referenced by both modules, repeated resolution returns one canonical identifier, preserves source identity, and rejects display-name identity or ambiguous references.

**Validates:** Requirements 1.2–1.7, 3.6, 4.7, 5.4, 6.7, 9.4, 9.10–9.12.

### Property 3: Shared platform authorization

*For any* User, permission, study, site, module operation, and target record, the operation succeeds exactly when the shared Authorization_Scope contains the required permission and scope; otherwise no module, projection, coordination, or attachment state changes.

**Validates:** Requirements 2.1–2.3, 2.7, 3.9, 4.10, 7.10, 10.1–10.18, 13.6.

### Property 4: Operational study and site lifecycle validity

*For any* generated operational study or site status sequence, the service accepts only configured transitions, retains status history, records required reasons, and never changes EDC clinical configuration or records.

**Validates:** Requirements 3.1–3.10, 4.1–4.11.

### Property 5: Enrollment authority and clinical protection

*For any* operational enrollment target or subject milestone, CTMS persists the operational state and approved projections while Clinical_Subject_Registry identity, identifiers, study-version binding, Clinical_Data, and unconfigured EDC status remain unchanged.

**Validates:** Requirements 5.1–5.15, 8.10, 14.4.

### Property 6: Protocol and monitoring visit separation

*For any* Monitoring_Activity sequence and EDC Visit_Instance state, operational scheduling and completion can change CTMS records, but protocol visit definitions, dates, windows, casebook state, and Clinical_Data remain unchanged, including when the EDC visit is frozen or locked.

**Validates:** Requirements 6.1–6.15, 14.7.

### Property 7: Monitoring plan immutability

*For any* published Monitoring_Plan, direct changes are rejected, amendments create a new draft version with a reason, and prior published versions remain retrievable.

**Validates:** Requirements 6.3–6.5.

### Property 8: Operational work lifecycle

*For any* generated Operational_Task, Operational_Contact, dependency, or escalation sequence, the Work_Management_Service enforces configured statuses, assignment eligibility, scope, history, and required reasons without persisting Clinical_Data or unrestricted clinical messages.

**Validates:** Requirements 7.1–7.12.

### Property 9: Projection minimization

*For any* source record and projection allowlist, the CTMS_Operational_Projection contains exactly approved fields and rejects Field_Values, source documents, unrestricted messages, credentials, unrestricted audit data, and prohibited identifiers.

**Validates:** Requirements 8.1–8.9, 8.11–8.12, 12.11–12.12.

### Property 10: Idempotent internal coordination

*For any* Coordination_Event and Idempotency_Key, processing the event one or more times produces one logical projection update, one stable outcome, and no duplicate side effect.

**Validates:** Requirements 1.7, 9.2–9.8, 9.17–9.18.

### Property 11: Ordered and current projections

*For any* ordered event sequence for one correlated entity, the Coordination_Service applies source order, rejects stale updates, and never lets an older event overwrite a newer projection.

**Validates:** Requirements 8.11–8.12, 9.8–9.9, 9.17–9.18.

### Property 12: Retry and failure classification

*For any* worker result sequence, retryable failures retry only within the configured bound, while unknown, ambiguous, schema, authorization, ownership, and data-minimization failures become the configured Failed_Event or Coordination_Conflict without partial target mutation.

**Validates:** Requirements 9.10–9.16, 13.12–13.15.

### Property 13: Projection rebuild safety

*For any* authoritative CTMS or EDC record set, rebuilding a CTMS_Operational_Projection produces the same approved read model and never mutates an authoritative source record.

**Validates:** Requirements 8.1–8.7, 9.17, 14.6.

### Property 14: Shared audit completeness and atomicity

*For any* CTMS mutation, projection update, coordination event, failure, replay, conflict resolution, attachment action, or operational export action, immutable audit records contain actor or worker, UTC timestamp, action, scope, source/target, correlation, and reason when required; authoritative data and its audit event commit or roll back together.

**Validates:** Requirements 2.4–2.5, 3.5, 4.4, 7.8–7.11, 9.18, 12.1–12.10, 14.6.

### Property 15: End-to-end traceability

*For any* coordinated change, an authorized investigator can traverse canonical source record → Coordination_Event_Log → target projection or record → Audit_Event → final outcome without a missing correlation link.

**Validates:** Requirements 1.7, 2.5, 8.11, 9.3–9.8, 9.18, 12.2–12.5.

### Property 16: Dashboard and report scope

*For any* generated operational records and Authorization_Scope, CTMS dashboard and report totals equal only records in scope, distinguish operational values from projected clinical values, and exclude unauthorized records.

**Validates:** Requirements 8.6–8.7, 10.11, 13.1–13.7.

### Property 17: Export ownership and content separation

*For any* export request, shared job infrastructure preserves job lifecycle and download audit, CTMS exports contain only CTMS-owned operational data and approved projections, and clinical exports remain EDC-owned and contain no CTMS-only operational data unless an explicit approved field is defined.

**Validates:** Requirements 2.8, 11.5, 12.8–12.10, 12.13, 14.3.

### Property 18: Attachment ownership and access

*For any* attachment and User, shared storage permits access only under the owning module's authorization; Operational_Attachments remain CTMS-owned, Clinical_Attachments remain EDC-owned, and CTMS cannot read clinical content through operational permissions.

**Validates:** Requirements 2.7, 10.11, 12.6–12.7, 12.15.

### Property 19: Optional-module resilience

*For any* EDC clinical workflow with no CTMS operational records or an unavailable CTMS worker, baseline EDC authentication, capture, clinical audit, clinical export, and lifecycle operations retain their behavior while accepted CTMS work remains queued or reported unavailable.

**Validates:** Requirements 13.12–13.16, 14.4, 14.10.

### Property 20: API and UI ownership semantics

*For any* User permission set and CTMS object state, the API returns the shared error/pagination contract, the UI exposes only permitted actions, and each shared status displays its authoritative module while server-side authorization remains decisive.

**Validates:** Requirements 2.1–2.3, 10.12–10.16, 11.1–11.17.

## Error Handling

The CTMS_Module SHALL use the baseline EDC error envelope:

```json
{
  "error": {
    "code": "COORDINATION_CONFLICT",
    "message": "The requested operational change conflicts with the current ownership rule.",
    "details": {}
  }
}
```

CTMS-specific error codes SHALL include `CTMS_SCOPE_DENIED`, `CTMS_RECORD_NOT_FOUND`, `CTMS_DUPLICATE_RECORD`, `CTMS_INVALID_TRANSITION`, `CTMS_PLAN_PUBLISHED`, `CTMS_ASSIGNMENT_INVALID`, `PROJECTION_FIELD_NOT_ALLOWED`, `COORDINATION_REPLAY`, `COORDINATION_RETRYING`, `COORDINATION_FAILED_EVENT`, `COORDINATION_CONFLICT`, `COORDINATION_OUT_OF_ORDER`, `REPORT_SCOPE_DENIED`, `CTMS_RATE_LIMITED`, and `CTMS_REQUEST_TOO_LARGE`.

The API_Layer SHALL return `X-Request-ID` for every response. Asynchronous CTMS commands SHALL return a Correlation_Identifier and processing outcome. Error details SHALL not include Clinical_Data values, source documents, credentials, unrestricted query messages, raw event bodies, database errors, or stack traces. A CTMS command targeting an EDC-owned record SHALL return an ownership error rather than silently redirecting the command.

## Testing Strategy

Property-based tests SHALL use Hypothesis for canonical identity, ownership rules, authorization, projection minimization, idempotency, ordering, operational state machines, retry classification, conflict policies, report scoping, attachment boundaries, export separation, pagination, and serialization logic, with a minimum of 100 generated examples per property. Internal workers, repositories, file stores, notification providers, and export stores SHALL be deterministic fakes. Tests SHALL not call external services.

Each acceptance criterion in Requirements 1–14 SHALL map to at least one automated example, unit, module, security, UI, API-contract, or property-based test. A test SHALL verify each atomic response independently when a criterion contains multiple response obligations.

Example and module tests SHALL cover:

- canonical study/site/subject/visit references and duplicate-reference rejection;
- operational study and site lifecycle, readiness, activation, contacts, and scope;
- enrollment targets, operational subject milestones, status projections, and EDC clinical-state protection;
- distinction between Monitoring_Activities and EDC Visit_Instances, including frozen and locked EDC visits;
- monitoring plan versioning, CRA assignment, rescheduling, completion evidence, and cancellation;
- Operational_Task lifecycle, follow-ups linked to EDC Queries, assignment, dependencies, escalations, and contacts;
- projection allowlists, data minimization, stale-event handling, and sanitized failure records;
- shared authorization, server-side denial, permission-aware frontend actions, and authoritative status labels;
- shared audit immutability, transaction atomicity, request/correlation propagation, and traceability;
- Operational_Attachment versus Clinical_Attachment access and retention;
- CTMS operational exports versus EDC clinical exports using shared export job infrastructure;
- operational dashboards, reports, notifications, health responses, worker outage, backpressure, retention, and frontend fallback behavior.

Qualification tests SHALL cover the ownership matrix, canonical identity, CTMS non-modification of EDC Study_Version and Clinical_Subject_Registry records, protocol visit and monitoring visit separation, subject enrollment projection rules, authorization scope, audit immutability, data minimization, idempotency, ordering, retries, Failed_Events, Coordination_Conflicts, operational export content, attachment separation, backup/restore, retention, worker outage behavior, and production rollout controls.

Frontend tests SHALL cover CTMS workspaces, operational status ownership labels, permission-aware actions, sanitized failure display, enrollment and monitoring workflows, operational dashboards, operational export filters, task/contact workflows, operational attachment access, and CTMS_Viewer read-only behavior. EDC frontend tests SHALL verify that baseline clinical workflows and protocol visit/casebook behavior remain unchanged when CTMS functionality is disabled or unavailable.

## Traceability Summary

- Requirement 1 defines the canonical identity and explicit module ownership boundary.
- Requirement 2 defines shared platform services and separates shared primitives from module-owned data.
- Requirements 3–5 define CTMS operational study, site, enrollment, and subject operations.
- Requirement 6 preserves EDC protocol visits and defines separate CTMS monitoring visits.
- Requirement 7 defines CTMS operational work management and contacts.
- Requirement 8 defines projection minimization and clinical-data protection.
- Requirement 9 defines internal coordination, idempotency, ordering, retries, failures, and rebuilds.
- Requirement 10 defines shared authorization and CTMS roles.
- Requirement 11 defines CTMS API and frontend ownership presentation.
- Requirement 12 defines audit, attachment, export, privacy, and retention boundaries.
- Requirement 13 defines operational dashboards, reports, notifications, health, resilience, and optional-module behavior.
- Requirement 14 defines phased delivery and independent verification of the ownership boundary.
- Properties 1–4 verify canonical identity, ownership, shared authorization, and operational lifecycle behavior.
- Properties 5–8 verify enrollment, monitoring, work management, and clinical-state protection.
- Properties 9–15 verify projection minimization, coordination correctness, audit, and traceability.
- Properties 16–18 verify reporting, export, and attachment ownership boundaries.
- Properties 19–20 verify resilience, API behavior, UI authorization, and authoritative status presentation.
- The EDC requirements document remains authoritative for EDC Requirements 5, 7–19, 21–25, 27, and 30–31 as narrowed by the Feature Ownership Matrix; this document does not transfer those clinical capabilities to CTMS.

## Clarifying Questions Before Technical Design

1. Which exact operational subject transitions may Enrollment_Service initiate as coordinated transitions to an EDC clinical access status, if any, and which transitions must remain CTMS projection-only?
2. Should CTMS operational study statuses and operational site statuses be authoritative for their operational fields in all phases, or should Phase 1 use a smaller status set before adding readiness and suspension states?
3. Which Work_Management_Service capabilities are required in Phase 1: tasks only, tasks plus follow-ups, contacts, dependencies, escalations, or operational attachments?
4. Which enrollment target dimensions are required for the initial release: study, country, site, cohort, treatment arm, planning period, or another dimension?
5. Which operational study and site fields require CTMS ownership beyond the fields explicitly listed in this document?
6. Which operational milestones and monitoring completion evidence are qualification-critical for the initial release?
7. Which minimized EDC clinical progress and Data_Quality_Signals may be projected to CTMS in the initial release, and what minimum subject or query references are permitted?
8. Which operational export formats and filters are required in the initial release, distinct from the EDC clinical export formats and filters?
9. Which operational attachment types, retention period, and download permissions are required for the initial release?
10. Which operational dashboards and reports are qualification-critical for Phase 1, and which belong in later phases?
11. What retention periods and response-time targets should apply to CTMS Operational_Data, projections, Coordination_Event_Logs, Failed_Events, operational exports, and operational attachments?
12. Which shared-platform notification triggers and recipient rules are required for Phase 1 beyond task assignment, monitoring assignment, overdue monitoring, and coordination failures?
