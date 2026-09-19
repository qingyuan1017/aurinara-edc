# Requirements Document

## Introduction

This document specifies the requirements for the EDC_System clinical module inside the Unified_Clinical_Platform. The EDC_System owns the regulated clinical data lifecycle: clinical study versioning and configuration, clinical subject identity and casebooks, protocol visit scheduling, electronic Case Report Form (eCRF) design, clinical data capture, edit checks and validation, query management, source data verification, clinical review, freeze/lock controls, electronic signatures, immutable clinical audit trails, clinical data export, and clinical dashboards and reports.

The Unified_Clinical_Platform contains the co-equal first-party EDC_System and CTMS_Module. The modules share one authenticated application boundary, canonical Study and Site identity, and shared platform capabilities, but they own different records and workflows. CTMS owns operational study and site profiles/readiness/activation/contacts, operational enrollment targets and milestones, monitoring plans and activities, operational work management and follow-ups, and operational dashboards, reports, exports, and attachments. EDC remains authoritative for the clinical capabilities listed above. CTMS is not an external integration and shall not create duplicate clinical subjects or protocol visits, modify EDC clinical records, own EDC query lifecycle or unrestricted query messages, or become a second clinical system of record.

The system is built on a defined technology baseline. The backend uses FastAPI on Python 3.11+, Pydantic v2 for schema validation, SQLAlchemy 2.x with Alembic migrations over a PostgreSQL database, served by Uvicorn/Gunicorn. The frontend is a single-page application built with React, TypeScript, Vite, shadcn/ui, Tailwind CSS, TanStack Query for server state, React Hook Form with Zod for form validation, and TanStack Router/Table for navigation and high-density listings. Optional AWS services may be configured per environment, including Cognito (authentication), S3 (file and export storage), RDS (PostgreSQL), ECS/Fargate (deployment), CloudWatch (logs and metrics), and Bedrock AgentCore (the optional AI assistant).

The system is intended for regulated clinical environments and is delivered in phases. Phase 1 delivers the EDC MVP: authentication, shared authorization scope enforcement, canonical clinical study/site/subject setup, eCRF metadata and data capture, the immutable clinical audit trail, manual clinical queries, and clinical CSV export. Phase 2 adds the clinical edit-check engine, repeating records, SDV, review, and freeze/lock. Phase 3 adds electronic signatures, published-version amendments, and advanced clinical exports. CTMS delivery phases are defined in the CTMS requirements document. Three cross-cutting concerns drive every EDC requirement: authorization scope enforcement, immutable auditability, and clinical data integrity under lifecycle controls. Terminology in this document is aligned with the approved CTMS requirements and design so requirements remain consistent across the unified platform.

## Glossary

- **Unified_Clinical_Platform**: The single first-party application boundary containing the EDC_System, CTMS_Module, and shared platform services.
- **EDC_System**: The clinical module within the Unified_Clinical_Platform that owns clinical configuration, clinical subject records, protocol visits, clinical data, clinical quality workflows, clinical attachments, clinical exports, and clinical dashboards/reports.
- **CTMS_Module**: The co-equal operational module within the Unified_Clinical_Platform that owns operational study/site planning and readiness, enrollment operations, monitoring, work management, operational dashboards/reports, operational exports, and operational attachments.
- **Shared_Platform_Service**: A service owned by the Unified_Clinical_Platform for capabilities used by both modules; shared primitive ownership does not transfer ownership of module-specific data or workflow semantics.
- **API_Layer**: The FastAPI versioned REST/JSON interface that authenticates requests, enforces authorization, validates schemas, delegates to the owning module service, and exposes both EDC and CTMS routes under the `/api/v1` prefix.
- **Frontend_Application**: The React/TypeScript single-page application providing the user interface for EDC clinical workflows and CTMS operational workflows.
- **Auth_Service**: The shared platform service handling login, token refresh, logout, current-user identity, password reset, optional MFA, inactivity timeout, invitations, and account deactivation for both modules.
- **Permission_Service**: The shared platform service that resolves and enforces permissions at route level and object level by system, study, and site scope for both modules.
- **Study_Service**: The shared canonical Study identity service used by both modules. EDC owns the clinical Study reference and Study_Version lifecycle; CTMS owns the operational study profile and operational lifecycle. Neither module creates a competing Study identity.
- **Study_Version_Service**: The EDC-owned service that manages Study_Version lifecycle and the immutability of published clinical metadata.
- **Site_Service**: The shared canonical Site identity and EDC clinical site-reference service. CTMS owns the operational site profile, activation/readiness, contacts, and operational status; EDC owns clinical site use and access metadata. Neither module creates a competing Site identity.
- **Clinical_Subject_Registry**: The EDC-owned registry of clinical subject identity, subject identifiers, study/site and Study_Version binding, clinical access state, and clinical subject records.
- **Subject_Service**: The EDC-owned service that manages Clinical_Subject_Registry records, clinical subject identifiers, clinical subject status, and clinical casebook initialization. CTMS Enrollment_Service owns separate operational enrollment targets, milestones, and operational subject statuses.
- **Protocol_Visit_Service**: The EDC-owned service that manages protocol visit definitions, Visit_Instances, visit dates, visit-window status, missed visits, and casebook schedule state.
- **Visit_Service**: The EDC-owned protocol-visit service represented by Protocol_Visit_Service. CTMS Monitoring_Service owns separate Monitoring_Activities that may reference, but never create or mutate, EDC Visit_Instances.
- **Form_Metadata_Service**: The EDC-owned service that manages eCRF form definitions, sections, fields, and code lists within a Study_Version.
- **Data_Capture_Service**: The EDC-owned service that loads, saves, submits, and edits clinical field values for Form_Instances.
- **Repeating_Record_Service**: The EDC-owned service that adds, edits, soft-deletes, and restores rows for clinical repeating forms.
- **Edit_Check_Engine**: The EDC-owned backend component that evaluates declarative JSON edit-check rules without executing user-provided code.
- **Query_Service**: The EDC-owned service that manages manual and system-generated Query lifecycle and threaded message history. CTMS may reference approved Query identifiers and summaries for operational follow-up but does not own Query state or unrestricted messages.
- **SDV_Service**: The EDC-owned service that records and clears source data verification status at field, form, visit, and subject level.
- **Review_Service**: The EDC-owned service that records and clears clinical review status on Form_Instances.
- **Lock_Service**: The EDC-owned service that applies and removes freeze and lock controls across the clinical object hierarchy.
- **Signature_Service**: The EDC-owned service that records electronic signatures after re-authentication and marks signatures stale when signed clinical data changes.
- **Audit_Service**: The shared platform append-only service that records immutable Audit_Events. EDC owns clinical event content and CTMS owns operational, projection, coordination, and operational attachment/export event content.
- **Export_Service**: The shared export-job infrastructure that creates jobs, tracks status, stores files, controls downloads, and audits downloads. EDC owns clinical export content and filtering; CTMS owns operational export content and filtering.
- **Dashboard_Service**: The shared dashboard and reporting infrastructure that applies authorization scope and aggregation primitives. EDC owns clinical dashboard/report content; CTMS owns operational dashboard/report content. EDC may display approved CTMS projections only as read-only, source-labeled projections.
- **Notification_Service**: The shared platform service that records and delivers notifications. EDC owns clinical workflow triggers and CTMS owns operational workflow triggers.
- **File_Attachment_Service**: The shared file-storage and metadata primitive. EDC owns Clinical_Attachments and their clinical access/content semantics; CTMS owns Operational_Attachments and their operational access/content semantics.
- **Coordination_Service**: The shared internal service that publishes, consumes, orders, deduplicates, retries, and records approved Coordination_Events between module boundaries.
- **Coordination_Event**: An immutable internal event describing an approved change or projection update between services in the Unified_Clinical_Platform.
- **CTMS_Operational_Projection**: A minimized, authorized, read-only CTMS or EDC view containing only approved fields from the other module.
- **Operational_Data**: CTMS-owned planning, readiness, enrollment, monitoring, work-management, operational attachment, dashboard, report, and export records.
- **Clinical_Data**: EDC-owned Field_Values, Form_Instances, Form_Records, clinical subject and visit records, source documents, clinical query messages, SDV, review, freeze/lock, and signatures.
- **Monitoring_Activity**: A CTMS-owned operational monitoring record that may reference an EDC Visit_Instance without becoming or changing a Protocol_Visit_Service record.
- **Operational_Attachment**: A CTMS-owned file metadata record and file content associated with operational work.
- **Clinical_Attachment**: An EDC-owned file metadata record and file content associated with a clinical object or source record.
- **AI_Assistant_Service**: The optional shared platform AI service that exposes approved EDC- or CTMS-scoped assistant capabilities backed by AWS Bedrock AgentCore.
- **User**: An individual account with identity, status, and assigned roles. Accounts are one per individual and are never shared.
- **Role**: A named set of permission codes with a scope of system, study, or site.
- **Permission**: A stable permission code (for example `form.enter`) that authorizes a specific action.
- **Authorization_Scope**: The resolved set of permission grants for a User, each applied at a study and/or site scope.
- **Study**: A clinical trial record with metadata and a status state machine.
- **Study_Version**: A versioned set of study metadata (visits, forms, fields, code lists, edit checks) that becomes immutable once published.
- **Site**: A clinical investigation location belonging to a Study, with a site number unique within the Study.
- **Subject**: An enrolled participant bound to a Site and a published Study_Version, with a subject number unique within the Study.
- **Visit_Instance**: A scheduled or unscheduled visit occurrence for a Subject, derived from a visit definition.
- **Form_Instance**: A specific eCRF occurrence for a Subject and Visit_Instance, holding clinical data and a workflow status.
- **Form_Record**: A row within a repeating Form_Instance, supporting soft deletion and restoration.
- **Field_Value** (also **Item_Value**): A normalized stored value for a single field within a Form_Instance or Form_Record.
- **Audit_Event**: An immutable, append-only record capturing actor, timestamp, entity, action, old value, new value, reason, and request identifier.
- **Query**: A data-clarification item linked to exactly one affected clinical object, with a lifecycle state machine.
- **SDV**: Source Data Verification, the act of verifying captured data against source documents.
- **Reason_For_Change**: A mandatory textual justification captured when submitted clinical data is modified.
- **Electronic_Signature**: A recorded attestation capturing signer identity, timestamp, and meaning, requiring re-authentication.
- **Soft_Deletion**: Logical deletion that retains the record and stores deletion actor, timestamp, and reason, without physical removal.
- **Environment**: An isolated deployment tier (local, development, test/QA, staging/UAT, production) with separate database, storage, secrets, and authentication configuration.
- **Traceability_Matrix**: The mapping of each requirement to its design reference and qualification test case (OQ/PQ).

## Ownership and Boundary Rules

The EDC_System and CTMS_Module are co-equal first-party modules inside the Unified_Clinical_Platform. They share authentication, authorization, audit, notifications, file-storage primitives, export-job infrastructure, observability, environment/configuration, API conventions, optional AI controls, and Coordination_Service, but shared primitives do not make either module authoritative for the other's records.

EDC is authoritative for Study_Version and clinical study configuration, Clinical_Subject_Registry and clinical subject identity, protocol visit definitions and Visit_Instances, eCRF metadata and clinical data capture, Queries and complete query message history, SDV, clinical review, freeze/lock, Electronic_Signatures, Clinical_Attachments, clinical dashboards/reports, and clinical exports. CTMS is authoritative for operational study and site profiles/readiness/activation/contacts, enrollment targets and operational milestones/statuses, Monitoring_Plans and Monitoring_Activities, Operational_Tasks and operational follow-ups, operational dashboards/reports, Operational_Attachments, and operational exports.

Study and Site use one canonical shared identity. EDC owns clinical Study and Site references and clinical use; CTMS owns operational profiles and operational status. CTMS operational records reference EDC Subject and Visit_Instance identifiers when approved, but CTMS shall not create duplicate clinical subjects, allocate clinical subject identifiers, initialize clinical casebooks, create protocol Visit_Instances, or mutate EDC clinical records. A CTMS Monitoring_Activity is not an EDC protocol visit. CTMS may reference an EDC Query identifier and an approved minimized summary for an operational follow-up, but Query_Service remains the sole authority for Query lifecycle and unrestricted messages.

A CTMS_Operational_Projection is an explicit, minimized, authorized, read-only view. Coordination_Service may apply only approved projection updates or explicitly configured coordinated transitions. An EDC dashboard, report, export, or attachment requirement in this document refers only to EDC clinical content unless it explicitly identifies an approved read-only CTMS projection or shared infrastructure primitive. CTMS operational content remains specified by the CTMS requirements document.

### Ownership disposition of affected service names

| Service name | Unified platform disposition | EDC responsibility | CTMS responsibility |
|---|---|---|---|
| `Study_Service` | Shared canonical identity with split module semantics | Clinical Study reference and Study_Version/configuration use | Operational study profile, planning, readiness, and operational lifecycle |
| `Site_Service` | Shared canonical identity with split module semantics | Clinical site reference, clinical access, and clinical assignment use | Operational site profile, activation/readiness, contacts, and operational lifecycle |
| `Subject_Service` | Split by clinical versus operational subject data | Clinical_Subject_Registry, identifiers, binding, clinical status, and casebook initialization | Enrollment targets, operational milestones, and operational subject status using EDC references |
| `Visit_Service` | Split by protocol versus monitoring records | Protocol_Visit_Service, protocol definitions, Visit_Instances, dates, windows, missed state | Monitoring_Plans and Monitoring_Activities; no protocol visit writes |
| `Dashboard_Service` | Shared scope and aggregation primitives with module-owned content | Clinical subject, form, Query, SDV, review, and clinical lifecycle metrics; approved CTMS projections are read-only | Operational study/site, enrollment, monitoring, task, readiness, and operational reports |
| `Export_Service` | Shared export-job infrastructure with module-owned content | Clinical data and clinical audit export content, filters, and authorization | Operational export content and filters |
| `File_Attachment_Service` | Shared storage, metadata, access, retention, and soft-deletion primitives | Clinical_Attachments and clinical/source access rules | Operational_Attachments and operational access rules |

## Requirements

### Requirement 1: Authentication and Session Management

**User Story:** As a system user, I want to authenticate securely and maintain a protected session, so that only authorized individuals access clinical data.

#### Acceptance Criteria

1. WHEN a User submits valid credentials, THE Auth_Service SHALL issue an access token valid for no longer than 3,600 seconds and a refresh token valid for no longer than 30 days.
2. IF a User submits invalid credentials, THEN THE Auth_Service SHALL reject the request and SHALL NOT issue any token.
3. WHEN a valid, unexpired, and unrevoked refresh token is presented, THE Auth_Service SHALL issue a new access token without issuing a new refresh token.
4. WHEN a User logs out, THE Auth_Service SHALL revoke the associated refresh token.
5. WHEN an authenticated User requests current-user information, THE Auth_Service SHALL return the User identity and the resolved Authorization_Scope.
6. WHEN a User requests a password reset, THE Auth_Service SHALL issue a single-use reset token that expires after 24 hours, and IF the token is invalid, expired, or already used, THEN THE Auth_Service SHALL reject the reset and SHALL NOT change the password.
7. WHERE Cognito is configured as the identity provider, THE Auth_Service SHALL validate Cognito-issued JWT access tokens and map the token subject to an internal User.
8. WHILE a session has had no authenticated activity for more than 1,800 seconds, THE Auth_Service SHALL reject access tokens for that session until re-authentication occurs.
9. WHERE multi-factor authentication is enabled for a User, THE Auth_Service SHALL issue tokens only after receiving a valid MFA code for the current authentication attempt.

### Requirement 2: Authorization and Permission Enforcement

**User Story:** As a security officer, I want every action authorized server-side by study and site scope, so that users access only the data they are permitted to.

#### Acceptance Criteria

1. THE Permission_Service SHALL resolve a User's Authorization_Scope as the union of the permission codes of that User's assigned Roles, each applied at the study and site scope of its assignment.
2. WHEN a request targets a protected route, THE Permission_Service SHALL permit the request only if the resolved Authorization_Scope contains the required Permission for the target study and site.
3. IF the resolved Authorization_Scope lacks the required Permission for the target study or site, THEN THE API_Layer SHALL return an authorization error identifying the missing permission and target scope, and SHALL NOT change clinical or operational state.
4. WHEN a User requests a list of studies or sites, THE Permission_Service SHALL return only records whose study and site scopes are contained in the User's Authorization_Scope, and SHALL return an empty list when no records qualify.
5. IF a User requests an object belonging to a study or site outside the User's Authorization_Scope, THEN THE Permission_Service SHALL deny access.
6. THE Permission_Service SHALL enforce authorization independently of any Frontend_Application permission checks.

### Requirement 3: Shared User, Role, and Invitation Management

**User Story:** As a system administrator, I want to manage users, roles, and invitations for both first-party modules, so that access is granted, scoped, and revoked in a controlled and auditable way.

#### Acceptance Criteria

1. WHEN an administrator invites a User, THE Unified_Clinical_Platform SHALL create one pending User record and issue one single-use invitation token that expires after 24 hours.
2. WHEN an invited User accepts a valid, unused invitation, THE Unified_Clinical_Platform SHALL activate the User account, apply the assigned Roles at their assigned scopes, and invalidate the invitation token.
3. THE Unified_Clinical_Platform SHALL assign each Role a scope of system, study, or site and a set of permission codes usable by EDC and CTMS operations.
4. WHEN an administrator deactivates a User, THE Auth_Service SHALL set the User status to inactive, revoke all active sessions, retain the User record and history for both modules, and cause the Audit_Service to record the deactivation.
5. IF an inactive User attempts to authenticate, THEN THE Auth_Service SHALL deny the request for both EDC and CTMS routes.
6. THE Permission_Service SHALL grant the Sponsor Viewer Role read-only access to EDC clinical and CTMS operational records only within that Role's permitted system, study, and site scopes.
7. THE Permission_Service SHALL support CTMS-specific operational roles without granting those roles authority to mutate EDC-owned clinical records.

### Requirement 4: Clinical Study Management

**User Story:** As a study administrator, I want to manage the EDC clinical study identity and clinical lifecycle, so that clinical configuration is controlled and traceable without conflating it with CTMS operational planning.

#### Acceptance Criteria

1. WHEN an authorized User creates a Study with a study code, protocol number, title, and clinical status reference that satisfy the applicable field validation rules, THE Study_Service SHALL persist one canonical clinical Study record.
2. THE Study_Service SHALL enforce that each study code is unique across the Unified_Clinical_Platform.
3. THE Study_Service SHALL permit only these clinical status transitions: Draft to UAT, UAT to Active, Active to Enrollment Closed, Enrollment Closed to Locked, and Locked to Archived; IF any other transition is requested, THEN THE Study_Service SHALL reject it without changing the Study.
4. WHEN an authorized User requests an EDC clinical study dashboard, THE Dashboard_Service SHALL return only EDC clinical metrics for Studies within the User's Authorization_Scope, including the count of Studies by clinical status.
5. WHEN EDC clinical study identity or clinical metadata changes, THE Audit_Service SHALL record an EDC clinical Audit_Event capturing the change.
6. WHERE an approved, minimized, read-only CTMS_Operational_Projection is available for the Study, THE EDC_System SHALL expose only the approved projected CTMS operational fields and SHALL label them as CTMS-sourced without allowing EDC mutation of those fields.
7. THE EDC_System SHALL not use the clinical Study record or Study_Version to store or mutate CTMS operational study planning, readiness, or operational lifecycle fields.

### Requirement 5: Study Versioning

**User Story:** As a study administrator, I want versioned study metadata, so that published study definitions remain immutable and amendments are traceable.

#### Acceptance Criteria

1. WHEN an authorized User publishes a draft Study_Version that passes its metadata validation, THE Study_Version_Service SHALL transition it to published and record the publication actor and timestamp.
2. WHILE a Study_Version is published, THE Study_Version_Service SHALL reject every modification to that version or its child visits, forms, fields, code lists, and edit checks, and SHALL preserve the published data.
3. WHEN an authorized User creates an amendment for a published Study_Version, THE Study_Version_Service SHALL create one new draft Study_Version and SHALL require a non-empty amendment reason of no more than 4,000 characters.
4. THE Study_Version_Service SHALL retain all prior published Study_Versions for traceability.
5. THE Study_Version_Service SHALL associate each form definition with exactly one Study_Version.

### Requirement 6: Clinical Site Management

**User Story:** As a study administrator, I want to manage EDC clinical site references and access, so that site users are limited to their assigned clinical sites while CTMS manages operational site readiness separately.

#### Acceptance Criteria

1. WHEN an authorized User creates a Site with a unique site number, a valid Study reference, and an EDC clinical access status, THE Site_Service SHALL persist one canonical Site identity and its EDC clinical site reference.
2. THE Site_Service SHALL enforce that each site number is unique within its Study across the Unified_Clinical_Platform.
3. WHEN an authorized User requests an EDC clinical site dashboard, THE Dashboard_Service SHALL return clinical site progress metrics scoped to the User's Authorization_Scope.
4. WHEN an authorized User deactivates a Site for EDC clinical access, THE Site_Service SHALL set the EDC clinical site status to inactive, retain the Site record, and prevent new EDC clinical access assignments to that Site.
5. WHEN an authorized User assigns or removes a User's clinical access to a Site, THE Site_Service SHALL create or remove the corresponding site-level assignment through the shared Permission_Service without changing CTMS operational site access.
6. THE EDC_System SHALL not use Site_Service to mutate CTMS operational site profile, activation, readiness, contact, or operational status fields.
7. WHERE an approved, minimized, read-only CTMS_Operational_Projection is available for the Site, THE EDC_System SHALL expose only its approved CTMS operational status fields as read-only and SHALL not persist those fields as EDC clinical site status.

### Requirement 7: Clinical Subject Management

**User Story:** As a site user, I want to create and track clinical subjects, so that subject-level clinical data is captured under the correct study, site, and Study_Version.

#### Acceptance Criteria

1. WHEN an authorized User creates a clinical Subject under a valid Study and Site with one selected published Study_Version, THE Subject_Service SHALL persist one Clinical_Subject_Registry record bound to that Study, Site, and Study_Version.
2. THE Subject_Service SHALL generate the clinical subject identifier using the configured rule of the bound Study and SHALL reject any identifier that is not unique within that Study.
3. THE Subject_Service SHALL permit only configured transitions among Screening, Screen Failed, Enrolled, Randomized, On Treatment, Completed, Early Terminated, Lost to Follow-up, and Withdrawn; IF a requested transition is not configured, THEN THE Subject_Service SHALL reject it without changing the Subject.
4. WHEN a clinical Subject is created, THE Subject_Service SHALL initialize every Visit_Instance and Form_Instance defined by the bound Study_Version, and IF initialization cannot complete, THEN THE Subject_Service SHALL retain neither the new Subject nor a partial casebook.
5. WHEN an authorized User requests a subject casebook, THE EDC_System SHALL return the clinical Subject visit and form structure with EDC clinical status.
6. WHEN an EDC clinical subject status changes, THE Audit_Service SHALL record an EDC clinical Audit_Event capturing the change.
7. THE EDC_System SHALL keep EDC clinical subject status separate from CTMS operational subject status, even when both use the same status labels.
8. THE EDC_System SHALL consume CTMS operational enrollment status or milestones only through an approved, minimized, read-only CTMS_Operational_Projection or an explicitly configured coordinated transition.
9. THE Subject_Service SHALL reject a command that attempts to create a duplicate clinical subject from a CTMS operational milestone or replace the EDC clinical subject identifier with an operational display identifier.

### Requirement 8: Protocol Visit Schedule

**User Story:** As a study administrator, I want to configure EDC protocol visits, so that subjects follow a defined clinical visit schedule with window tracking.

#### Acceptance Criteria

1. WHEN an authorized User defines a protocol visit within a draft Study_Version, THE Protocol_Visit_Service SHALL persist a unique visit definition with a name, visit number, visit type, integer target day, integer lower and upper window bounds in days where the lower bound is no greater than the upper bound, display order, and required flag.
2. WHEN a clinical Subject is created, THE Protocol_Visit_Service SHALL create EDC Visit_Instances from the protocol visit definitions of the bound Study_Version.
3. WHEN a protocol visit date is recorded, THE Protocol_Visit_Service SHALL calculate the EDC visit window status from the difference in calendar days between the visit date and the Subject's protocol reference date, using the configured bounds, as Early, In Window, or Late.
4. WHERE an unscheduled protocol visit is permitted by the bound Study_Version, THE Protocol_Visit_Service SHALL allow an authorized User to create an unscheduled EDC Visit_Instance that is not assigned a scheduled visit number.
5. WHEN an authorized User marks a protocol visit as missed, THE Protocol_Visit_Service SHALL set the EDC Visit_Instance status to missed.
6. THE EDC_System SHALL keep Protocol_Visit_Service records separate from CTMS Monitoring_Activities, and IF a CTMS command attempts to create or mutate an EDC Visit_Instance or its Clinical_Data, THEN THE API_Layer SHALL reject the command without changing either module's authoritative state.

### Requirement 9: eCRF Form Builder

**User Story:** As a study administrator, I want to design metadata-driven eCRFs, so that forms, sections, and fields can be configured without code.

#### Acceptance Criteria

1. WHILE the owning Study_Version is in draft, THE Form_Metadata_Service SHALL allow an authorized User to create, edit, and order form definitions only when each definition has a unique name within that Study_Version.
2. WHILE the owning Study_Version is in draft, THE Form_Metadata_Service SHALL allow an authorized User to create and order sections and fields only when each field has a unique variable name within its form definition.
3. THE Form_Metadata_Service SHALL support the field control types text, textarea, integer, decimal, date, datetime, time, radio, checkbox, dropdown, multi-select, boolean, file upload, calculated, repeating table, and coded term.
4. THE Form_Metadata_Service SHALL support field attributes including label, variable name, data type, required flag, code list reference, default value, help text, unit, minimum value, maximum value, maximum length, decimal precision, regex validation, visibility rule, read-only flag, and calculated flag, and SHALL enforce that minimum value is no greater than maximum value, maximum length is a non-negative integer, decimal precision is a non-negative integer, and every referenced code list exists in the same Study_Version.
5. THE Form_Metadata_Service SHALL support code lists and code list items referenced by fields.
6. WHEN valid form metadata is created, edited, or reordered, THE Audit_Service SHALL record an Audit_Event for the change, and IF the metadata is invalid, THEN THE Form_Metadata_Service SHALL persist neither the invalid metadata nor its change event.

### Requirement 10: Clinical Data Entry

**User Story:** As a site user, I want to capture eCRF data with validation and change control, so that clinical data is accurate, complete, and traceable.

#### Acceptance Criteria

1. WHEN an authorized User saves valid draft data, THE Data_Capture_Service SHALL persist the Field_Values and set the Form_Instance status to In Progress; IF validation fails, THEN THE Data_Capture_Service SHALL preserve the prior persisted values and status.
2. THE Data_Capture_Service SHALL support the Form_Instance statuses Not Started, In Progress, Submitted, Reviewed, Frozen, Locked, and Signed.
3. WHEN an authorized User submits a Form_Instance, THE Data_Capture_Service SHALL set the status to Submitted only after required-field, data-type, range, code-list, and conditional-rule validation succeeds.
4. IF submission validation fails, THEN THE Data_Capture_Service SHALL return an error for every failing field, preserve all previously persisted Field_Values and the prior Form_Instance status, and SHALL NOT create a submission audit event.
5. IF an authorized User changes a Field_Value after submission, THEN THE Data_Capture_Service SHALL require a non-empty Reason_For_Change of no more than 4,000 characters before persisting the change.
6. WHEN an authorized User marks a Field_Value as not applicable, THE Data_Capture_Service SHALL persist the not-applicable state and SHALL exclude that Field_Value from required-value validation.
7. IF a Form_Instance is Frozen or Locked, THEN THE Data_Capture_Service SHALL reject every Field_Value modification and preserve the Field_Values and Form_Instance status.
8. WHEN a Field_Value is created or changed, THE Data_Capture_Service SHALL record an Audit_Event within the same database transaction as the data write.

### Requirement 11: Repeating Records

**User Story:** As a site user, I want to manage rows in repeating forms, so that multi-record clinical data such as adverse events and medications is captured with full history.

#### Acceptance Criteria

1. WHEN an authorized User adds a row to a repeating Form_Instance, THE Repeating_Record_Service SHALL create one Form_Record with a positive sequence number greater than every previously assigned sequence number in that Form_Instance, including soft-deleted rows.
2. WHEN an authorized User edits an active Form_Record, THE Repeating_Record_Service SHALL persist the change and record an Audit_Event; IF the Form_Record is soft-deleted, THEN THE Repeating_Record_Service SHALL reject the edit.
3. WHEN an authorized User deletes an active Form_Record, THE Repeating_Record_Service SHALL apply Soft_Deletion only when a non-empty reason of no more than 4,000 characters is provided and SHALL retain the row.
4. WHEN an authorized User restores a soft-deleted Form_Record, THE Repeating_Record_Service SHALL clear the deletion state, retain the original sequence number, and record an Audit_Event; IF the row is not soft-deleted, THEN THE Repeating_Record_Service SHALL reject the restore.

### Requirement 12: Edit Checks and Validation

**User Story:** As a data manager, I want configurable edit checks, so that data quality issues are detected and queries are generated automatically.

#### Acceptance Criteria

1. WHEN an authorized User defines an edit check, THE Edit_Check_Engine SHALL persist it only if its JSON rule definition conforms to the supported operator and condition schema; IF validation fails, THEN THE Edit_Check_Engine SHALL return a validation error and SHALL NOT persist the rule.
2. THE Edit_Check_Engine SHALL support the rule types required field, range check, date comparison, cross-field logic, cross-form logic, code list validation, format validation, duplicate record check, missing visit or form check, conditional required check, and lab abnormality check.
3. THE Edit_Check_Engine SHALL support the severities info, warning, error, and query, where info and warning results do not block submission, error results block submission, and query results request Query_Service creation.
4. WHEN an authorized User tests an edit check against sample data, THE Edit_Check_Engine SHALL return the rule outcome, severity, and affected clinical object without persisting the sample data, rule, or Query.
5. WHEN a query-severity edit check condition is met for an affected clinical object, THE Edit_Check_Engine SHALL request Query_Service to create one system Query linked to that object and SHALL not create a second identical open system Query for the same rule and object.
6. THE Edit_Check_Engine SHALL bind each edit check to exactly one Study_Version and SHALL evaluate that check only against clinical data governed by that Study_Version.
7. THE Edit_Check_Engine SHALL evaluate rules without executing user-provided code.

### Requirement 13: Query Management

**User Story:** As a data manager, I want full query lifecycle management, so that data clarifications are tracked from creation through closure.

#### Acceptance Criteria

1. WHEN a Query is created, THE Query_Service SHALL link it to exactly one existing affected object among Subject, Visit_Instance, Form_Instance, Form_Record, or Field_Value, and SHALL reject a request with zero or multiple affected objects.
2. THE Query_Service SHALL permit only these Query transitions: Open to Answered or Cancelled, Answered to Closed, Reopened, or Cancelled, Closed to Reopened, and Reopened to Answered or Cancelled; IF any other transition is requested, THEN THE Query_Service SHALL reject it without changing the Query.
3. WHEN a site User responds to an Open Query, THE Query_Service SHALL append one message containing the responding User and timestamp and SHALL transition the Query to Answered.
4. WHEN an authorized User closes a Query, THE Query_Service SHALL transition the Query status to Closed and record the closing actor and timestamp.
5. WHEN an authorized User reopens a Closed Query, THE Query_Service SHALL transition the Query status to Reopened.
6. THE Query_Service SHALL preserve every Query message in insertion order with its author and timestamp and SHALL reject update or deletion of an existing message.
7. WHEN a Query action occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.

### Requirement 14: Source Data Verification

**User Story:** As a clinical research associate, I want to verify captured data against source documents, so that source data verification progress is recorded and tracked.

#### Acceptance Criteria

1. WHEN an authorized User sets SDV status on an existing Field_Value, Form_Instance, Visit_Instance, or Subject, THE SDV_Service SHALL persist verified status with the verifying actor and timestamp.
2. WHEN an authorized User clears SDV status, THE SDV_Service SHALL set the target status to not verified, retain the prior verification history, and record the clearing actor and timestamp.
3. WHEN an authorized User requests SDV progress for a scope, THE SDV_Service SHALL return verified count, not-verified count, and total count, where total count equals the sum of the two counts for that scope.
4. WHEN an SDV status changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 15: Clinical Review

**User Story:** As a medical reviewer, I want to mark forms as reviewed, so that clinical review progress is recorded and tracked.

#### Acceptance Criteria

1. WHEN an authorized User marks an existing Form_Instance as reviewed, THE Review_Service SHALL persist reviewed status with the reviewing actor and timestamp.
2. WHEN an authorized User clears review status, THE Review_Service SHALL set the Form_Instance to not reviewed, retain the prior review history, and record the clearing actor and timestamp.
3. WHEN an authorized User requests review progress for a scope, THE Review_Service SHALL return reviewed count, not-reviewed count, and total count, where total count equals the sum of the two counts for that scope.
4. WHEN a review status changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 16: Freeze, Lock, and Unlock

**User Story:** As a data manager, I want to freeze, lock, and unlock clinical data, so that data is protected from modification at controlled points in the workflow.

#### Acceptance Criteria

1. WHEN an authorized User freezes an eligible field, form, visit, subject, site, or study, THE Lock_Service SHALL set that target's freeze state to frozen without changing its lock state.
2. WHEN an authorized User locks an eligible field, form, visit, subject, site, or study, THE Lock_Service SHALL set that target's lock state to locked without changing its freeze state.
3. IF any ancestor of a target Field_Value in the hierarchy Field_Value, Form_Instance, Visit_Instance, Subject, Site, Study is frozen or locked, THEN THE Lock_Service SHALL reject modification of that Field_Value and preserve its prior value.
4. WHEN an authorized User unlocks or unfreezes an object whose corresponding control is set, THE Lock_Service SHALL require a non-empty reason of no more than 4,000 characters and SHALL clear only the requested control; IF that control is not set, THEN THE Lock_Service SHALL reject the request.
5. WHEN a freeze, lock, or unlock action occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.

### Requirement 17: Electronic Signatures

**User Story:** As an investigator, I want to electronically sign clinical data, so that attestation is captured with regulatory rigor.

#### Acceptance Criteria

1. WHEN a User initiates an Electronic_Signature, THE Signature_Service SHALL record a signature only after successful re-authentication for that User; IF re-authentication fails, THEN THE Signature_Service SHALL record no Electronic_Signature.
2. WHEN an Electronic_Signature is recorded for an eligible clinical object, THE Signature_Service SHALL persist the signer identity, timestamp, non-empty signature meaning of no more than 500 characters, signed object reference, and hash of the signed data.
3. IF any signed clinical data changes after an Electronic_Signature is recorded, THEN THE Signature_Service SHALL mark that Electronic_Signature as stale and persist a non-empty stale reason.
4. WHEN an Electronic_Signature action occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.

### Requirement 18: Clinical Audit Trail

**User Story:** As a regulatory reviewer, I want a complete and immutable audit trail for EDC clinical activity, so that every regulated clinical change is attributable and traceable.

#### Acceptance Criteria

1. WHEN an EDC clinical data or configuration change occurs, THE Audit_Service SHALL record one immutable EDC clinical Audit_Event containing actor, UTC timestamp, entity type, entity identifier, study, site, and action, plus old value and new value for value changes and Reason_For_Change for post-submission changes.
2. IF a caller requests an update or delete of an Audit_Event, THEN THE Audit_Service SHALL reject the request and SHALL not change any existing Audit_Event.
3. WHEN a clinical field change occurs after submission, THE Audit_Service SHALL record the captured Reason_For_Change in the EDC clinical Audit_Event.
4. WHEN a Clinical_Attachment upload, download, or deletion occurs, THE Audit_Service SHALL record an EDC clinical Audit_Event capturing the action.
5. WHEN an authorized User searches EDC clinical audit history, THE Audit_Service SHALL return only EDC clinical Audit_Events within the User's Authorization_Scope and SHALL support exact filtering by user, inclusive UTC date range, entity, Subject, and Field_Value.
6. WHEN an authorized User exports EDC clinical audit history, THE Audit_Service SHALL produce an export containing exactly the authorized EDC clinical Audit_Events selected by the request and SHALL record the export action.
7. THE Audit_Service SHALL provide the same immutable append-only primitive to CTMS, and IF a CTMS operation attempts to alter an EDC clinical Audit_Event, THEN THE Audit_Service SHALL reject it without changing EDC clinical audit state.

### Requirement 19: Clinical Data Export

**User Story:** As a data manager, I want to export EDC clinical data in multiple formats, so that clinical data can be analyzed and submitted downstream.

#### Acceptance Criteria

1. WHEN an authorized User requests an EDC clinical export, THE Export_Service SHALL create one job in Queued, Running, Completed, or Failed state, SHALL permit only Queued to Running to Completed or Failed transitions, SHALL store the generated clinical file when the job completes, and SHALL retain a failure indication when the job fails.
2. WHEN an authorized User requests a clinical subject-list export, THE Export_Service SHALL produce only the EDC clinical subjects within the requested Authorization_Scope and SHALL produce an empty result when no subject qualifies.
3. THE Export_Service SHALL apply study, site, clinical subject, protocol visit, form, domain, and inclusive UTC date-range filters as intersections; SHALL interpret changed-since-last-export as changes after the timestamp of the selected prior Completed export; and SHALL interpret locked-data-only and clean-data-only as predicates on the selected EDC clinical records.
4. WHEN an authorized User downloads an EDC clinical export file, THE Export_Service SHALL provide access only to that User's authorized completed job for no longer than 900 seconds and SHALL record one EDC clinical Audit_Event for the download.
5. THE Export_Service SHALL accept and produce exactly the EDC clinical formats CSV, Excel, JSON, SAS XPT, and ODM XML, and SHALL reject any other requested format without creating a Completed job.
6. THE EDC_System SHALL not generate or own CTMS operational export content. CTMS operational exports SHALL use the shared Export_Service job infrastructure while remaining CTMS-owned and separately authorized.
7. THE Export_Service SHALL keep EDC clinical export content and filters separate from CTMS operational export content, and WHERE an explicitly approved minimized projection is included, THE Export_Service SHALL label it as projected content and exclude unapproved fields.

### Requirement 20: Clinical Dashboards and Reports

**User Story:** As a clinical study team member, I want EDC clinical dashboards and reports, so that I can monitor clinical data-capture and clinical data-cleaning progress without conflating EDC metrics with CTMS operational metrics.

#### Acceptance Criteria

1. WHEN an authorized User requests an EDC clinical study dashboard, THE Dashboard_Service SHALL return subject counts grouped by each defined EDC clinical status, Form_Instance completion count and total count, and Query counts grouped by Open, Answered, and Closed status.
2. WHEN an authorized User requests an EDC clinical site dashboard, THE Dashboard_Service SHALL return only EDC clinical metrics for sites within the User's Authorization_Scope and SHALL return zero-valued metrics when no qualifying clinical records exist.
3. WHEN an authorized User requests EDC clinical Query metrics, THE Dashboard_Service SHALL return Open, Answered, and overdue Query counts, where overdue means the Query's due date is earlier than the current UTC date, and SHALL return Query aging as elapsed whole UTC days since Query creation.
4. THE Dashboard_Service SHALL compute all EDC clinical dashboard and report metrics from EDC records within the requesting User's Authorization_Scope.
5. WHERE an approved CTMS_Operational_Projection is available, THE Dashboard_Service SHALL display only its approved fields with a CTMS source label and SHALL prevent those fields from being used in EDC clinical metric calculations or mutated through EDC.
6. THE EDC_System SHALL not claim ownership of CTMS operational study/site dashboards, enrollment reports, monitoring reports, task reports, readiness reports, or operational status metrics.

### Requirement 21: Shared API Layer Standards

**User Story:** As an integrator, I want consistent versioned APIs for EDC and CTMS, so that clients interact with the Unified_Clinical_Platform predictably and safely.

#### Acceptance Criteria

1. THE API_Layer SHALL expose EDC endpoints under /api/v1 and CTMS endpoints under /api/v1/ctms, and SHALL return response bodies validated by Pydantic v2 schemas.
2. WHEN a list endpoint is requested, THE API_Layer SHALL return a pagination envelope containing items, page number greater than or equal to 1, page size from 1 through 1,000, and total count greater than or equal to 0.
3. IF a request fails, THEN THE API_Layer SHALL return a standard error envelope containing an error code, a message indicating the failed operation, and details limited to caller-safe validation or authorization information, without exposing internal database errors, prohibited clinical data, or raw coordination payloads.
4. WHEN a request changes EDC clinical data, THE API_Layer SHALL guarantee that the corresponding EDC clinical Audit_Event is written within the same database transaction as the clinical data change.
5. WHEN a request is received, THE API_Layer SHALL assign one request identifier, return that identifier in the response, and include the same identifier in every Audit_Event and Coordination_Event created by that request.
6. IF a CTMS route attempts to mutate an EDC-owned record, THEN THE API_Layer SHALL reject the request before either EDC or CTMS authoritative state or audit state changes.

### Requirement 22: Database and Persistence

**User Story:** As a platform engineer, I want a well-structured persistence model, so that clinical data is stored with integrity, retained, and efficiently queried.

#### Acceptance Criteria

1. THE EDC_System SHALL store study metadata separately from clinical subject data.
2. WHEN a Subject, Form_Instance, Form_Record, Query, Clinical_Attachment, or other EDC clinical record is deleted, THE EDC_System SHALL apply Soft_Deletion, retain the record and its deletion actor, timestamp, and reason, and SHALL not physically remove it or any related Audit_Event.
3. WHEN a Field_Value is created or changed, THE Data_Capture_Service SHALL persist equivalent value content in the Form_Instance JSON payload and exactly one normalized per-field row, or SHALL roll back both representations if either write fails.
4. THE EDC_System SHALL store every timestamp with UTC timezone information and SHALL preserve at least one-second precision; THE Frontend_Application SHALL convert timestamps to local time only for display.
5. THE EDC_System SHALL reject duplicate study codes globally, duplicate site numbers within one Study, and duplicate subject numbers within one Study without changing the existing records.
6. THE EDC_System SHALL use UUID primary keys and SHALL provide queryable indexes for study identifier, site identifier, subject identifier, form identifier, status, and creation timestamp.

### Requirement 23: Backend Architecture and Coding Rules

**User Story:** As a backend maintainer, I want enforced architectural layering, so that the codebase remains secure, testable, and consistent.

#### Acceptance Criteria

1. THE EDC_System SHALL keep route handlers limited to input validation, permission checks, and delegation, and SHALL execute business-rule decisions in the delegated service layer.
2. THE EDC_System SHALL permit database access only through repository-layer operations, and SHALL reject or fail verification for direct database access from routes or services.
3. WHEN a service mutates EDC clinical data, THE EDC_System SHALL commit the data change and corresponding Audit_Event together, and IF either write fails, THEN THE EDC_System SHALL commit neither.
4. WHEN a protected operation is requested, THE EDC_System SHALL resolve the required Permission and target scope through the Permission_Service before mutating data.

### Requirement 24: Frontend Application

**User Story:** As a user, I want a clear, permission-aware interface, so that I can perform clinical workflows efficiently and safely.

#### Acceptance Criteria

1. THE Frontend_Application SHALL display the same textual clinical status value for each Subject, Form_Instance, Query, SDV, review, freeze, lock, and signature state in list, casebook, and data-entry views.
2. WHEN a User enters data, THE Frontend_Application SHALL run the applicable Zod validation before submission, and IF client validation fails, THEN THE Frontend_Application SHALL send no request while the API_Layer remains authoritative.
3. WHEN a User edits submitted data, THE Frontend_Application SHALL require a non-empty Reason_For_Change of no more than 4,000 characters before sending the change to the API_Layer.
4. WHILE a clinical object is Frozen or Locked, THE Frontend_Application SHALL render its input controls as disabled.
5. WHEN a User opens audit history or a Query thread, THE Frontend_Application SHALL render the requested details in a dialog or sheet while keeping the originating clinical status view mounted and visible.
6. IF a User lacks permission for an action or route, THEN THE Frontend_Application SHALL hide the action or render an access-denied view, and SHALL rely on the API_Layer to enforce the same denial.

### Requirement 25: Compliance, Validation, and Environment Management

**User Story:** As a quality and compliance lead, I want regulatory-aligned controls and isolated environments across the Unified_Clinical_Platform, so that EDC clinical workflows support 21 CFR Part 11, GxP, ALCOA+, and HIPAA-aware operation while CTMS remains governed by the same platform controls.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL provide isolated local, development, test/QA, staging/UAT, and production Environments, and SHALL prevent each Environment from reading another Environment's database, object storage, secrets, authentication configuration, or logs.
2. THE Audit_Service SHALL derive EDC clinical Audit_Event timestamps from the server clock, store them as UTC, and maintain server-clock agreement within 5 seconds across participating services.
3. THE Unified_Clinical_Platform SHALL retain EDC clinical and CTMS operational records for at least 7 years, create at least one backup in every 24-hour period, and restore either module's records within 4 hours without restoring them into the other module's authoritative records.
4. THE EDC_System SHALL maintain a Traceability_Matrix mapping each EDC requirement to its design reference and qualification test case.
5. THE EDC_System SHALL represent Draft, Submitted, Reviewed, Frozen, Locked, and Signed as distinct clinical states, SHALL permit only configured transitions, and SHALL retain actor, timestamp, and reason data for every regulated clinical change.
6. THE Unified_Clinical_Platform SHALL provide qualification evidence that includes at least one passing OQ or PQ test for each listed capability: shared authentication, role-based access control, scope enforcement, EDC subject creation, clinical data capture, Reason_For_Change, audit immutability, clinical Query workflow, locking, and clinical export.
7. THE Unified_Clinical_Platform SHALL retain CTMS operational audit, coordination, projection, attachment, and export records under CTMS requirements without treating those records as EDC clinical records.

### Requirement 26: EDC Phased Delivery and Testing

**User Story:** As a delivery lead, I want EDC clinical delivery aligned to testing, so that the EDC MVP ships independently with verified clinical guarantees while CTMS delivery remains independently phased.

#### Acceptance Criteria

1. THE EDC_System SHALL designate Phase 1 complete only when shared authentication, EDC authorization scope enforcement, canonical clinical study/site/subject setup, eCRF metadata, clinical data capture, immutable EDC clinical audit, manual clinical Queries, and clinical CSV export each have a passing qualification test.
2. THE EDC_System SHALL designate Phase 2 complete only when the EDC Edit_Check_Engine, clinical repeating records, SDV, clinical review, and clinical freeze/lock each have a passing qualification test.
3. THE EDC_System SHALL designate Phase 3 complete only when EDC Electronic_Signatures, published Study_Version amendments, and advanced clinical exports each have a passing qualification test.
4. THE EDC_System SHALL complete at least one passing Phase 1 test for authorization scope enforcement, EDC clinical ownership, protocol-visit ownership, and audit immutability before declaring Phase 1 complete.
5. THE EDC_System SHALL provide automated backend, frontend, permission, audit, ownership-boundary, and clinical-regression tests for every delivered EDC capability, and SHALL not declare a phase complete while any required test is failing.
6. THE EDC_System SHALL treat CTMS operational delivery as governed only by the CTMS requirements document, and SHALL not count CTMS operational capabilities as EDC phase deliverables.

### Requirement 27: Clinical File Attachments

**User Story:** As a site user, I want to upload clinical supporting documents securely, so that source and supporting files are linked to EDC clinical objects with access control.

#### Acceptance Criteria

1. WHERE file upload is enabled for an EDC clinical field or object, THE File_Attachment_Service SHALL store a non-empty file no larger than 100 MB as a Clinical_Attachment in object storage and persist metadata linked to that EDC clinical object.
2. WHEN a User requests a Clinical_Attachment download, THE File_Attachment_Service SHALL grant access only when the User has read access to the parent EDC clinical object and SHALL reject the request without revealing file content otherwise.
3. WHEN an authorized User deletes an active Clinical_Attachment, THE File_Attachment_Service SHALL apply Soft_Deletion, retain the metadata and deletion reason, and prevent subsequent downloads through normal attachment access.
4. WHEN a Clinical_Attachment upload, download, or deletion completes, THE Audit_Service SHALL record one EDC clinical Audit_Event for that action, and IF the attachment action fails, THEN THE Audit_Service SHALL record no completed-action event.
5. WHILE the parent EDC clinical object is Frozen or Locked, THE File_Attachment_Service SHALL reject new Clinical_Attachment uploads and preserve existing attachment state.
6. THE EDC_System SHALL not own or mutate CTMS Operational_Attachments, and IF an EDC operation targets a CTMS Operational_Attachment, THEN THE File_Attachment_Service SHALL reject it without changing CTMS operational attachment state.

### Requirement 28: Clinical Notifications

**User Story:** As a clinical workflow user, I want notifications for relevant EDC clinical events, so that assigned clinical work is acted on promptly.

#### Acceptance Criteria

1. WHEN an EDC Query is assigned to a User's clinical Role, THE Notification_Service SHALL create one EDC clinical notification for each resolved assigned recipient within 60 seconds of the assignment.
2. WHEN an EDC Form_Instance is submitted, THE Notification_Service SHALL create one EDC clinical notification for each resolved responsible clinical reviewer within 60 seconds of submission.
3. WHEN an EDC clinical export job reaches Completed or Failed, THE Notification_Service SHALL create one EDC clinical notification for the requesting User within 60 seconds and SHALL identify the job outcome.
4. THE Notification_Service SHALL support only the EDC clinical notification statuses Unread, Read, and Archived, and SHALL permit only Unread to Read or Archived and Read to Archived transitions.
5. WHEN an authorized User requests unread EDC clinical notifications, THE Notification_Service SHALL return only notifications addressed to that User with status Unread and SHALL return an empty list when none qualify.
6. THE Notification_Service SHALL remain shared infrastructure while CTMS owns notifications triggered by CTMS operational tasks, monitoring activities, overdue work, and coordination failures.

### Requirement 29: Performance

**User Story:** As a study team member, I want responsive performance at scale, so that large studies remain usable.

#### Acceptance Criteria

1. WHEN a common read operation is requested under a load of 100 concurrent Users against a study containing up to 100 sites, 10,000 Subjects, 100 forms, and 1,000,000 Field_Values, THE API_Layer SHALL return a successful response within 1 second for at least 95 percent of requests.
2. WHEN a list endpoint is requested, THE API_Layer SHALL return a paginated result with no more than 1,000 items per page.
3. WHEN an export or batch validation processes at least 100,000 clinical records, THE EDC_System SHALL accept the request within 5 seconds and process it as an asynchronous job with a Queued, Running, Completed, or Failed status.
4. THE EDC_System SHALL support at least 100 concurrent authenticated Users while maintaining the common-read performance criterion.
5. THE EDC_System SHALL support a study containing at least 100 sites, 10,000 Subjects, 100 forms, and 1,000,000 Field_Values while maintaining successful reads, writes, lists, and exports.

### Requirement 30: Reliability and Observability

**User Story:** As an operator, I want health checks, structured logs, and monitoring, so that I can detect and diagnose production issues.

#### Acceptance Criteria

1. WHEN the liveness endpoint is requested, THE API_Layer SHALL return a health status of Healthy or Unhealthy within 1 second and SHALL report Unhealthy only when the service process cannot accept a request.
2. WHEN the readiness endpoint is requested, THE API_Layer SHALL return a readiness status of Ready or Not Ready within 1 second, where Not Ready indicates that a required configured dependency is unavailable.
3. WHEN the metrics endpoint is requested, THE API_Layer SHALL return current values for API latency, error rate, database connections, worker job failures, export failures, and authentication failures covering at least the preceding 5 minutes.
4. WHEN a request is processed, THE EDC_System SHALL emit one structured log entry containing the request identifier, UTC timestamp, operation outcome, and duration in milliseconds.
5. THE EDC_System SHALL record API latency in milliseconds, error rate as a percentage, database connections as a count, and worker job, export, and authentication failures as counts, and SHALL update these metrics at least once every 60 seconds.

### Requirement 31: Optional AI Assistant

**User Story:** As a data manager, I want an optional AI assistant for clinical data management tasks, so that I can draft edit checks and summarize queries with human oversight.

#### Acceptance Criteria

1. WHERE the AI assistant is enabled, THE AI_Assistant_Service SHALL expose chat, edit-check drafting, and query summarization operations backed by AWS Bedrock AgentCore; IF the AI assistant is disabled, THEN THE AI_Assistant_Service SHALL expose none of those operations.
2. WHERE the AI assistant is enabled, THE AI_Assistant_Service SHALL stream each response through Server-Sent Events or WebSocket and SHALL provide a terminal completion or error indication within the same stream.
3. BEFORE sending clinical context to the AI assistant, THE AI_Assistant_Service SHALL verify the requesting User's Authorization_Scope and SHALL send no clinical context when the requested context is outside that scope.
4. IF an AI suggestion would change study data, THEN THE AI_Assistant_Service SHALL require an explicit human confirmation for that specific change and SHALL apply no change when confirmation is absent or declined.
5. WHEN a confirmed AI-assisted action changes regulated EDC clinical data, THE Audit_Service SHALL record one EDC clinical Audit_Event identifying the User, the changed clinical object, the action, and the AI-assisted origin.

### Requirement 32: Unified Platform Clinical Ownership and Coordination

**User Story:** As a platform owner, I want the EDC and CTMS module boundary enforced explicitly, so that CTMS operational workflows can coexist with EDC clinical workflows without creating competing clinical authority.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL assign exactly one authoritative module to each persisted field of a Study, Site, Subject, Visit_Instance, projection, clinical record, and operational record, and SHALL reject any field assignment that has zero or more than one authoritative module.
2. THE Unified_Clinical_Platform SHALL use one canonical shared identity for each Study and Site, and SHALL require every CTMS reference to a Subject or Visit_Instance to use the EDC clinical identifier without creating a duplicate clinical identity.
3. IF a CTMS command attempts to create or mutate an EDC-owned Study_Version, Clinical_Subject_Registry record, Visit_Instance, Form_Instance, Field_Value, Query, SDV state, clinical review state, freeze/lock state, Electronic_Signature, Clinical_Attachment, or clinical export, THEN THE API_Layer SHALL reject the command and SHALL change neither EDC nor CTMS authoritative state.
4. WHEN EDC clinical progress or quality data is exposed to CTMS, THE Coordination_Service SHALL deliver only an approved, minimized, authorized CTMS_Operational_Projection containing its source identifier, rule version, correlation identifier, and processing outcome, and SHALL not deliver unapproved clinical fields.
5. WHEN CTMS operational status or milestone data is exposed to EDC, THE Coordination_Service SHALL deliver only an approved read-only projection or an explicitly configured coordinated transition, and SHALL not change EDC clinical status or clinical data unless the configured transition explicitly authorizes that change.
6. WHEN CTMS operational work references an EDC Query, THE Coordination_Service SHALL deliver only the approved Query identifier and minimized summary fields, and SHALL reject unrestricted Query messages while Query_Service remains authoritative for Query lifecycle and complete threaded messages.
7. THE Unified_Clinical_Platform SHALL use shared Auth_Service, Permission_Service, Audit_Service, Notification_Service, file-storage primitives, export-job infrastructure, observability, environment/configuration, API conventions, optional AI controls, and Coordination_Service without transferring EDC clinical authority to CTMS.
8. IF the CTMS_Module is disabled, empty, or unavailable, THEN THE EDC_System SHALL continue authentication, clinical data capture, clinical audit, clinical export, protocol visit, and clinical lifecycle operations using only EDC-owned state and SHALL return no CTMS-dependent clinical result as authoritative.

## Clinical Correctness Properties

The following properties preserve the EDC clinical invariants and SHALL map to automated unit, integration, security, or property-based tests. Tests SHALL use deterministic repositories and fakes for internal logic and SHALL not require CTMS or external services to verify EDC clinical authority.

### Property 1: Clinical identity and configuration integrity

For any valid Study, Study_Version, Site, Subject, and protocol visit sequence, canonical Study/Site identity remains stable, each clinical Subject has one EDC identifier and one bound published Study_Version, and each clinical form definition belongs to exactly one Study_Version.

**Validates:** Requirements 4, 5, 7, and 9.

### Property 2: Clinical lifecycle transition validity

For any generated EDC clinical Study, Subject, Form_Instance, Query, SDV, review, freeze/lock, and signature status sequence, the EDC services accept only configured transitions, preserve required history, and reject invalid transitions without partial mutation.

**Validates:** Requirements 4, 7, 10, 13, 14, 15, 16, and 17.

### Property 3: Protocol visit and casebook consistency

For any published Study_Version and clinical Subject, casebook initialization creates the configured protocol Visit_Instances and Form_Instances, visit-window calculations use configured bounds, and CTMS Monitoring_Activities cannot alter protocol visit state.

**Validates:** Requirements 5, 7, 8, and 32.

### Property 4: Clinical data validation and preservation

For any Field_Value payload, submission validates required fields, data types, ranges, code-list membership, and conditional rules; a failed validation preserves prior values; submitted changes require a Reason_For_Change; and frozen or locked objects reject clinical modifications.

**Validates:** Requirements 9, 10, 16, and 23.

### Property 5: Clinical audit atomicity and immutability

For any EDC clinical mutation, the clinical data change and its Audit_Event commit or roll back together, the event contains actor, timestamp, entity, action, and applicable old/new values and reason, and completed Audit_Events cannot be updated or deleted.

**Validates:** Requirements 10, 18, 21, 23, and 25.

### Property 6: Clinical authorization scope

For any User, clinical Permission, Study, Site, and EDC object, the operation succeeds exactly when the shared Authorization_Scope contains the required permission and target scope; otherwise no clinical, audit, attachment, export, or projection state changes.

**Validates:** Requirements 1, 2, 3, 18, 19, 21, 24, and 32.

### Property 7: Clinical and operational content separation

For any EDC clinical export, clinical dashboard/report, Clinical_Attachment, notification, or audit search, the result contains only authorized EDC clinical content and approved read-only projections; CTMS operational content remains CTMS-owned and cannot be written through EDC clinical operations.

**Validates:** Requirements 18, 19, 20, 27, 28, and 32.

### Property 8: Clinical round-trip serialization

For every valid EDC clinical API request and response model supported by Pydantic v2, serialization followed by deserialization produces an equivalent clinical value, while invalid or prohibited module-boundary data produces a standard validation or ownership error.

**Validates:** Requirements 9, 10, 19, 21, and 32.

## Traceability Summary

- Requirements 1–3 define shared authentication, authorization, identity, and account controls used by both modules.
- Requirements 4–9 define EDC clinical Study, Study_Version, Site, Subject, protocol Visit_Instance, and eCRF configuration authority; operational study/site/enrollment/monitoring behavior remains CTMS-owned.
- Requirements 10–18 define EDC clinical data capture, validation, quality workflows, signatures, and immutable clinical audit behavior.
- Requirements 19–20 define EDC clinical export and clinical dashboard/report content; shared infrastructure and CTMS operational content remain separately owned.
- Requirements 21–25 define shared API, persistence, architecture, frontend, compliance, and environment controls with EDC clinical scope.
- Requirements 26–31 define EDC delivery phases, clinical attachments, clinical notifications, performance, observability, and optional AI controls.
- Requirement 32 defines canonical identity, ownership, projection, coordination, and CTMS non-modification boundaries.
- Clinical Correctness Properties 1–8 provide the verification mapping for EDC identity, lifecycle, casebook, data integrity, auditability, authorization, content separation, and serialization.
- The CTMS requirements document remains authoritative for CTMS operational study/site/enrollment/monitoring/work-management behavior, operational dashboards/reports/exports/attachments, coordination recovery, and operational qualification. This document remains authoritative for EDC clinical behavior identified in the ownership rules and glossary.