# Requirements Document

## Introduction

This document specifies the requirements for a web-based Clinical Electronic Data Capture (EDC) system. The EDC_System manages the full clinical trial data lifecycle: study setup and versioning, site and subject management, visit scheduling, electronic Case Report Form (eCRF) design, clinical data capture, edit checks and validation, query management, source data verification, clinical review, freeze/lock controls, electronic signatures, immutable audit trails, data export, and operational dashboards.

The system is built on a defined technology baseline. The backend uses FastAPI on Python 3.11+, Pydantic v2 for schema validation, SQLAlchemy 2.x with Alembic migrations over a PostgreSQL database, served by Uvicorn/Gunicorn. The frontend is a single-page application built with React, TypeScript, Vite, shadcn/ui, Tailwind CSS, TanStack Query for server state, React Hook Form with Zod for form validation, and TanStack Router/Table for navigation and high-density listings. Optional AWS services may be configured per environment, including Cognito (authentication), S3 (file and export storage), RDS (PostgreSQL), ECS/Fargate (deployment), CloudWatch (logs and metrics), and Bedrock AgentCore (the optional AI assistant).

The system is intended for regulated clinical environments and is delivered in phases. Phase 1 delivers the MVP: authentication, authorization scope enforcement, study/site/subject setup, eCRF metadata and data capture, the immutable audit trail, manual queries, and CSV export. Phase 2 adds the edit-check engine, repeating records, SDV, review, and freeze/lock. Phase 3 adds electronic signatures, published-version amendments, and advanced exports. Three cross-cutting concerns drive every requirement: authorization scope enforcement (study/site), immutable auditability, and data integrity under lifecycle controls. Terminology in this document is aligned with `design.md` so requirements and design remain consistent.

## Glossary

- **EDC_System**: The complete Clinical Electronic Data Capture platform comprising the API_Layer, Frontend_Application, backend services, and PostgreSQL persistence.
- **API_Layer**: The FastAPI versioned REST/JSON interface that authenticates requests, enforces authorization, validates schemas, and delegates to backend services.
- **Frontend_Application**: The React/TypeScript single-page application providing the user interface for all clinical workflows.
- **Auth_Service**: The backend service handling login, token refresh, logout, current-user identity, password reset, optional MFA, and inactivity timeout.
- **Permission_Service**: The backend service that resolves and enforces permissions at route level and object level by study/site scope.
- **Study_Service**: The backend service that manages study records and the study status state machine.
- **Study_Version_Service**: The backend service that manages study version lifecycle and the immutability of published metadata.
- **Site_Service**: The backend service that manages study sites and site activation status.
- **Subject_Service**: The backend service that manages subject enrollment, subject identifiers, subject status, and instance initialization.
- **Visit_Service**: The backend service that manages visit definitions, visit instances, and visit window status.
- **Form_Metadata_Service**: The backend service that manages eCRF form definitions, sections, fields, and code lists within a study version.
- **Data_Capture_Service**: The backend service that loads, saves, submits, and edits clinical field values for form instances.
- **Repeating_Record_Service**: The backend service that adds, edits, soft-deletes, and restores rows for repeating forms.
- **Edit_Check_Engine**: The backend component that evaluates declarative JSON edit-check rules without executing user-provided code.
- **Query_Service**: The backend service that manages manual and system-generated queries and their threaded message history.
- **SDV_Service**: The backend service that records and clears source data verification status at field, form, visit, and subject level.
- **Review_Service**: The backend service that records and clears clinical review status on form instances.
- **Lock_Service**: The backend service that applies and removes freeze and lock controls across the object hierarchy.
- **Signature_Service**: The backend service that records electronic signatures after re-authentication and marks signatures stale when signed data changes.
- **Audit_Service**: The append-only backend service that records immutable Audit_Events for all clinical and configuration changes.
- **Export_Service**: The backend service that creates export jobs, tracks their status, stores export files, and audits downloads.
- **Dashboard_Service**: The backend service that computes read-only operational metrics scoped to the caller's authorization.
- **Notification_Service**: The backend service that records and delivers user notifications for clinical workflow events.
- **File_Attachment_Service**: The backend service that stores uploaded documents and links file metadata to clinical objects.
- **AI_Assistant_Service**: The optional backend service that exposes AI assistant endpoints backed by AWS Bedrock AgentCore.
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

## Requirements

### Requirement 1: Authentication and Session Management

**User Story:** As a system user, I want to authenticate securely and maintain a protected session, so that only authorized individuals access clinical data.

#### Acceptance Criteria

1. WHEN a User submits valid credentials, THE Auth_Service SHALL issue a signed access token and a refresh token.
2. IF a User submits invalid credentials, THEN THE Auth_Service SHALL reject the request and SHALL NOT issue any token.
3. WHEN a valid refresh token is presented, THE Auth_Service SHALL issue a new access token.
4. WHEN a User logs out, THE Auth_Service SHALL revoke the associated refresh token.
5. WHEN an authenticated User requests current-user information, THE Auth_Service SHALL return the User identity and the resolved Authorization_Scope.
6. WHEN a User requests a password reset, THE Auth_Service SHALL issue a single-use reset token and SHALL update the password only when a valid reset token is presented.
7. WHERE Cognito is configured as the identity provider, THE Auth_Service SHALL validate Cognito-issued JWT access tokens and map the token subject to an internal User.
8. WHILE a session is idle beyond the configured inactivity window, THE Auth_Service SHALL reject access tokens for that session until re-authentication occurs.
9. WHERE multi-factor authentication is enabled for a User, THE Auth_Service SHALL require a valid MFA code before issuing tokens.

### Requirement 2: Authorization and Permission Enforcement

**User Story:** As a security officer, I want every action authorized server-side by study and site scope, so that users access only the data they are permitted to.

#### Acceptance Criteria

1. THE Permission_Service SHALL resolve a User's Authorization_Scope as the union of the permission codes of that User's assigned Roles, each applied at the study and site scope of its assignment.
2. WHEN a request targets a protected route, THE Permission_Service SHALL permit the request only if the resolved Authorization_Scope contains the required Permission for the target study and site.
3. IF the resolved Authorization_Scope lacks the required Permission, THEN THE API_Layer SHALL return an authorization error with a clear message.
4. WHEN a User requests a list of studies or sites, THE Permission_Service SHALL return only the studies and sites within the User's Authorization_Scope.
5. IF a User requests an object belonging to a study or site outside the User's Authorization_Scope, THEN THE Permission_Service SHALL deny access.
6. THE Permission_Service SHALL enforce authorization independently of any Frontend_Application permission checks.

### Requirement 3: User, Role, and Invitation Management

**User Story:** As a system administrator, I want to manage users, roles, and invitations, so that access is granted, scoped, and revoked in a controlled and auditable way.

#### Acceptance Criteria

1. WHEN an administrator invites a User, THE EDC_System SHALL create a pending User record and issue a single-use invitation token.
2. WHEN an invited User accepts a valid invitation, THE EDC_System SHALL activate the User account and apply the assigned Roles at their study and site scope.
3. THE EDC_System SHALL assign each Role a scope of system, study, or site and a set of permission codes.
4. WHEN an administrator deactivates a User, THE EDC_System SHALL set the User status to inactive, revoke active sessions, and retain the User record and history.
5. IF an inactive User attempts to authenticate, THEN THE Auth_Service SHALL deny the request.
6. THE Permission_Service SHALL grant the Sponsor Viewer Role read-only permissions only.

### Requirement 4: Study Management

**User Story:** As a study administrator, I want to create and manage studies and their lifecycle status, so that study configuration is controlled and traceable.

#### Acceptance Criteria

1. WHEN an authorized User creates a Study, THE Study_Service SHALL persist the study metadata including study code, protocol number, title, sponsor, phase, therapeutic area, indication, and status.
2. THE Study_Service SHALL enforce that each study code is unique across the EDC_System.
3. THE Study_Service SHALL enforce study status transitions through the states Draft, UAT, Active, Enrollment Closed, Locked, and Archived.
4. WHEN an authorized User requests a study dashboard, THE Dashboard_Service SHALL return study-level metrics scoped to the User's Authorization_Scope.
5. WHEN study metadata changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 5: Study Versioning

**User Story:** As a study administrator, I want versioned study metadata, so that published study definitions remain immutable and amendments are traceable.

#### Acceptance Criteria

1. WHEN an authorized User publishes a Study_Version, THE Study_Version_Service SHALL transition the version status from draft to published and record the publication actor and timestamp.
2. WHILE a Study_Version is published, THE Study_Version_Service SHALL reject modifications to that version and its child visits, forms, fields, code lists, and edit checks.
3. WHEN an authorized User creates an amendment, THE Study_Version_Service SHALL create a new draft Study_Version with an amendment reason.
4. THE Study_Version_Service SHALL retain all prior published Study_Versions for traceability.
5. THE Study_Version_Service SHALL associate each form definition with exactly one Study_Version.

### Requirement 6: Site Management

**User Story:** As a study administrator, I want to manage study sites and assignments, so that site users are limited to their assigned sites.

#### Acceptance Criteria

1. WHEN an authorized User creates a Site, THE Site_Service SHALL persist the site metadata including site number, name, principal investigator, country, region, address, and status.
2. THE Site_Service SHALL enforce that each site number is unique within its Study.
3. WHEN an authorized User requests a site dashboard, THE Dashboard_Service SHALL return site-level progress metrics scoped to the User's Authorization_Scope.
4. WHEN an authorized User deactivates a Site, THE Site_Service SHALL set the site status to inactive and retain the site record.
5. WHEN an authorized User assigns a User to a Site, THE Site_Service SHALL record the site-level assignment.

### Requirement 7: Subject Management

**User Story:** As a site user, I want to create and track subjects, so that subject-level clinical data is captured under the correct study and site.

#### Acceptance Criteria

1. WHEN an authorized User creates a Subject under a Study and Site, THE Subject_Service SHALL persist the subject metadata and bind the Subject to the applicable published Study_Version.
2. THE Subject_Service SHALL generate a subject identifier by the configured rule and SHALL enforce that the subject number is unique within the Study.
3. THE Subject_Service SHALL enforce subject status transitions through the states Screening, Screen Failed, Enrolled, Randomized, On Treatment, Completed, Early Terminated, Lost to Follow-up, and Withdrawn.
4. WHEN a Subject is created, THE Subject_Service SHALL initialize the Visit_Instances and Form_Instances defined by the bound Study_Version.
5. WHEN an authorized User requests a subject casebook, THE EDC_System SHALL return the Subject visit and form structure with clinical status.
6. WHEN a subject status changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 8: Visit Schedule

**User Story:** As a study administrator, I want to configure study visits, so that subjects follow a defined visit schedule with window tracking.

#### Acceptance Criteria

1. WHEN an authorized User defines a visit, THE Visit_Service SHALL persist the visit definition including name, visit number, visit type, target day, window bounds, display order, and required flag.
2. WHEN a Subject is created, THE Visit_Service SHALL create Visit_Instances from the visit definitions of the bound Study_Version.
3. WHEN a visit date is recorded, THE Visit_Service SHALL calculate the visit window status from the visit date relative to the configured window bounds.
4. WHERE an unscheduled visit is permitted, THE Visit_Service SHALL allow an authorized User to create an unscheduled Visit_Instance.
5. WHEN an authorized User marks a visit as missed, THE Visit_Service SHALL set the Visit_Instance status to missed.

### Requirement 9: eCRF Form Builder

**User Story:** As a study administrator, I want to design metadata-driven eCRFs, so that forms, sections, and fields can be configured without code.

#### Acceptance Criteria

1. WHILE the owning Study_Version is in draft, THE Form_Metadata_Service SHALL allow an authorized User to create, edit, and order form definitions.
2. WHILE the owning Study_Version is in draft, THE Form_Metadata_Service SHALL allow an authorized User to create and order sections and fields within a form definition.
3. THE Form_Metadata_Service SHALL support the field control types text, textarea, integer, decimal, date, datetime, time, radio, checkbox, dropdown, multi-select, boolean, file upload, calculated, repeating table, and coded term.
4. THE Form_Metadata_Service SHALL support field attributes including label, variable name, data type, required flag, code list reference, default value, help text, unit, minimum value, maximum value, maximum length, decimal precision, regex validation, visibility rule, read-only flag, and calculated flag.
5. THE Form_Metadata_Service SHALL support code lists and code list items referenced by fields.
6. WHEN form metadata changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 10: Clinical Data Entry

**User Story:** As a site user, I want to capture eCRF data with validation and change control, so that clinical data is accurate, complete, and traceable.

#### Acceptance Criteria

1. WHEN an authorized User saves a draft, THE Data_Capture_Service SHALL persist the Field_Values and set the Form_Instance status to In Progress.
2. THE Data_Capture_Service SHALL support the Form_Instance statuses Not Started, In Progress, Submitted, Reviewed, Frozen, Locked, and Signed.
3. WHEN an authorized User submits a Form_Instance, THE Data_Capture_Service SHALL validate required fields, data types, ranges, code list membership, and conditional rules before setting the status to Submitted.
4. IF submission validation fails, THEN THE Data_Capture_Service SHALL return field-level errors and SHALL preserve the previously entered Field_Values.
5. IF an authorized User changes a Field_Value after submission, THEN THE Data_Capture_Service SHALL require a Reason_For_Change before persisting the change.
6. WHEN an authorized User marks a field as not applicable, THE Data_Capture_Service SHALL persist the not-applicable state for that Field_Value.
7. IF a Form_Instance is Frozen or Locked, THEN THE Data_Capture_Service SHALL reject modifications to its Field_Values.
8. WHEN a Field_Value is created or changed, THE Data_Capture_Service SHALL record an Audit_Event within the same database transaction as the data write.

### Requirement 11: Repeating Records

**User Story:** As a site user, I want to manage rows in repeating forms, so that multi-record clinical data such as adverse events and medications is captured with full history.

#### Acceptance Criteria

1. WHEN an authorized User adds a row to a repeating Form_Instance, THE Repeating_Record_Service SHALL create a Form_Record with a monotonically assigned sequence number.
2. WHEN an authorized User edits a Form_Record, THE Repeating_Record_Service SHALL persist the change and record an Audit_Event.
3. WHEN an authorized User deletes a Form_Record, THE Repeating_Record_Service SHALL apply Soft_Deletion by recording the deletion actor, timestamp, and reason and retaining the row.
4. WHEN an authorized User restores a soft-deleted Form_Record, THE Repeating_Record_Service SHALL clear the deletion state and record an Audit_Event.

### Requirement 12: Edit Checks and Validation

**User Story:** As a data manager, I want configurable edit checks, so that data quality issues are detected and queries are generated automatically.

#### Acceptance Criteria

1. WHEN an authorized User defines an edit check, THE Edit_Check_Engine SHALL validate the JSON rule definition against the supported operator and condition schema before persisting it.
2. THE Edit_Check_Engine SHALL support the rule types required field, range check, date comparison, cross-field logic, cross-form logic, code list validation, format validation, duplicate record check, missing visit or form check, conditional required check, and lab abnormality check.
3. THE Edit_Check_Engine SHALL support the severities info, warning, error, and query.
4. WHEN an authorized User tests an edit check against sample data, THE Edit_Check_Engine SHALL return the evaluation outcome without persisting clinical data.
5. WHEN a query-severity edit check condition is met at runtime, THE Edit_Check_Engine SHALL request the Query_Service to create a system Query linked to the affected object.
6. THE Edit_Check_Engine SHALL version edit checks with their owning Study_Version.
7. THE Edit_Check_Engine SHALL evaluate rules without executing user-provided code.

### Requirement 13: Query Management

**User Story:** As a data manager, I want full query lifecycle management, so that data clarifications are tracked from creation through closure.

#### Acceptance Criteria

1. WHEN a Query is created, THE Query_Service SHALL link the Query to exactly one affected object among Subject, Visit_Instance, Form_Instance, Form_Record, or field.
2. THE Query_Service SHALL support the Query statuses Open, Answered, Closed, Reopened, and Cancelled.
3. WHEN a site user responds to an Open Query, THE Query_Service SHALL transition the Query status to Answered and append the response to the query message history.
4. WHEN an authorized User closes a Query, THE Query_Service SHALL transition the Query status to Closed and record the closing actor and timestamp.
5. WHEN an authorized User reopens a Closed Query, THE Query_Service SHALL transition the Query status to Reopened.
6. THE Query_Service SHALL preserve the complete threaded message history of each Query.
7. WHEN a Query action occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.

### Requirement 14: Source Data Verification

**User Story:** As a clinical research associate, I want to verify captured data against source documents, so that source data verification progress is recorded and tracked.

#### Acceptance Criteria

1. WHEN an authorized User sets SDV status on a field, form, visit, or subject, THE SDV_Service SHALL persist the verified status with the verifying actor and timestamp.
2. WHEN an authorized User clears SDV status, THE SDV_Service SHALL set the verified status to not verified.
3. WHEN an authorized User requests SDV progress, THE SDV_Service SHALL return the verified and not-verified counts for the requested scope.
4. WHEN an SDV status changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 15: Clinical Review

**User Story:** As a medical reviewer, I want to mark forms as reviewed, so that clinical review progress is recorded and tracked.

#### Acceptance Criteria

1. WHEN an authorized User marks a Form_Instance as reviewed, THE Review_Service SHALL persist the reviewed status with the reviewing actor and timestamp.
2. WHEN an authorized User clears review status, THE Review_Service SHALL set the reviewed status to not reviewed.
3. WHEN an authorized User requests review progress, THE Review_Service SHALL return the reviewed and not-reviewed counts for the requested scope.
4. WHEN a review status changes, THE Audit_Service SHALL record an Audit_Event capturing the change.

### Requirement 16: Freeze, Lock, and Unlock

**User Story:** As a data manager, I want to freeze, lock, and unlock clinical data, so that data is protected from modification at controlled points in the workflow.

#### Acceptance Criteria

1. WHEN an authorized User freezes a field, form, visit, subject, site, or study, THE Lock_Service SHALL set the freeze state on the target object.
2. WHEN an authorized User locks a field, form, visit, subject, site, or study, THE Lock_Service SHALL set the lock state on the target object.
3. IF any ancestor of a target field in the chain field, form, visit, subject, site, study is frozen or locked, THEN THE Lock_Service SHALL block modification of that field.
4. WHEN an authorized User unlocks an object, THE Lock_Service SHALL require a reason and SHALL clear the lock state.
5. WHEN a freeze, lock, or unlock action occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.

### Requirement 17: Electronic Signatures

**User Story:** As an investigator, I want to electronically sign clinical data, so that attestation is captured with regulatory rigor.

#### Acceptance Criteria

1. WHEN a User initiates an Electronic_Signature, THE Signature_Service SHALL require re-authentication before recording the signature.
2. WHEN an Electronic_Signature is recorded, THE Signature_Service SHALL persist the signer identity, timestamp, signature meaning, signed object reference, and a hash of the signed data.
3. IF signed data changes after an Electronic_Signature is recorded, THEN THE Signature_Service SHALL mark the Electronic_Signature as stale and record the stale reason.
4. WHEN an Electronic_Signature action occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.

### Requirement 18: Audit Trail

**User Story:** As a regulatory reviewer, I want a complete and immutable audit trail, so that every regulated change is attributable and traceable.

#### Acceptance Criteria

1. WHEN a clinical data change or key configuration change occurs, THE Audit_Service SHALL record an Audit_Event capturing actor, timestamp, entity type, entity identifier, study, site, action, and where applicable the field, old value, new value, and Reason_For_Change.
2. THE Audit_Service SHALL reject all update and delete operations on Audit_Events.
3. WHEN a field change occurs after submission, THE Audit_Service SHALL record the captured Reason_For_Change in the Audit_Event.
4. WHEN a file upload, download, or deletion occurs, THE Audit_Service SHALL record an Audit_Event capturing the action.
5. WHEN an authorized User searches the audit trail, THE Audit_Service SHALL return Audit_Events filterable by user, date, entity, subject, and field.
6. WHEN an authorized User exports the audit trail, THE Audit_Service SHALL produce an export of the selected Audit_Events.

### Requirement 19: Data Export

**User Story:** As a data manager, I want to export study data in multiple formats, so that data can be analyzed and submitted downstream.

#### Acceptance Criteria

1. WHEN an authorized User requests an export, THE Export_Service SHALL create an export job, store the generated file, and track the job status through the states Queued, Running, Completed, and Failed.
2. WHEN an authorized User requests a subject-list export, THE Export_Service SHALL produce the subject list for the requested scope.
3. THE Export_Service SHALL support filtering exports by study, site, subject, visit, form, domain, date range, changed-since-last-export, locked-data-only, and clean-data-only.
4. WHEN an authorized User downloads an export file, THE Export_Service SHALL provide the file through a signed URL or authenticated backend streaming and SHALL record an Audit_Event for the download.
5. THE Export_Service SHALL support the export formats CSV, Excel, JSON, SAS XPT, and ODM XML.

### Requirement 20: Dashboards and Reports

**User Story:** As a study team member, I want operational dashboards, so that I can monitor study, site, and data-cleaning progress.

#### Acceptance Criteria

1. WHEN an authorized User requests the study dashboard, THE Dashboard_Service SHALL return study-level metrics including subject counts by status, form completion, and open query counts.
2. WHEN an authorized User requests the site dashboard, THE Dashboard_Service SHALL return site-level progress metrics.
3. WHEN an authorized User requests query metrics, THE Dashboard_Service SHALL return open, answered, and overdue query counts and query aging.
4. THE Dashboard_Service SHALL compute all dashboard metrics scoped to the requesting User's Authorization_Scope.

### Requirement 21: API Layer Standards

**User Story:** As an integrator, I want a consistent versioned API, so that clients interact with the system predictably and safely.

#### Acceptance Criteria

1. THE API_Layer SHALL expose all endpoints under the version prefix `/api/v1` and SHALL return JSON validated by Pydantic v2 schemas.
2. WHEN a list endpoint is requested, THE API_Layer SHALL return a pagination envelope containing items, page, page size, and total.
3. IF a request fails, THEN THE API_Layer SHALL return a standard error envelope containing an error code, message, and details, without exposing internal database errors.
4. WHEN a request changes clinical data, THE API_Layer SHALL guarantee that the corresponding Audit_Event is written within the same database transaction as the data change.
5. WHEN a request is received, THE API_Layer SHALL assign a request identifier, return it in the response, and propagate it into every Audit_Event of that request.

### Requirement 22: Database and Persistence

**User Story:** As a platform engineer, I want a well-structured persistence model, so that clinical data is stored with integrity, retained, and efficiently queried.

#### Acceptance Criteria

1. THE EDC_System SHALL store study metadata separately from clinical subject data.
2. WHEN a clinical record is deleted, THE EDC_System SHALL apply Soft_Deletion and SHALL NOT physically remove subject, form, query, or audit data.
3. THE Data_Capture_Service SHALL store each Field_Value both in the Form_Instance JSON payload and as a normalized per-field row.
4. THE EDC_System SHALL store all timestamps as timezone-aware UTC values and SHALL convert to local time only in the Frontend_Application.
5. THE EDC_System SHALL enforce uniqueness constraints for study code, site number within a study, and subject number within a study.
6. THE EDC_System SHALL use UUID primary keys and SHALL index the common filter columns study identifier, site identifier, subject identifier, form identifier, status, and creation timestamp.

### Requirement 23: Backend Architecture and Coding Rules

**User Story:** As a backend maintainer, I want enforced architectural layering, so that the codebase remains secure, testable, and consistent.

#### Acceptance Criteria

1. THE EDC_System SHALL keep route handlers thin by restricting them to input validation, permission checks, and delegation to services that contain the business logic.
2. THE EDC_System SHALL access the database only through the repository layer.
3. WHEN a service mutates clinical data, THE EDC_System SHALL write the Audit_Event in the same database transaction as the data change.
4. THE EDC_System SHALL route every protected operation through the Permission_Service before mutating data.

### Requirement 24: Frontend Application

**User Story:** As a user, I want a clear, permission-aware interface, so that I can perform clinical workflows efficiently and safely.

#### Acceptance Criteria

1. THE Frontend_Application SHALL render clinical status for subjects, forms, queries, SDV, review, freeze, lock, and signature using consistent status indicators across list, casebook, and data-entry views.
2. WHEN a User enters data, THE Frontend_Application SHALL validate input with Zod on the client while the API_Layer remains authoritative.
3. WHEN a User edits submitted data, THE Frontend_Application SHALL collect a Reason_For_Change before sending the change to the API_Layer.
4. WHILE a clinical object is Frozen or Locked, THE Frontend_Application SHALL render its input controls as disabled.
5. THE Frontend_Application SHALL display audit history and query threads in dialog or sheet overlays so primary clinical status remains visible.
6. IF a User lacks permission for an action or route, THEN THE Frontend_Application SHALL hide the action or render an access-denied view, while treating frontend checks as convenience only.

### Requirement 25: Compliance, Validation, and Environment Management

**User Story:** As a quality and compliance lead, I want regulatory-aligned controls and isolated environments, so that the system supports 21 CFR Part 11, GxP, ALCOA+, and HIPAA-aware operation.

#### Acceptance Criteria

1. THE EDC_System SHALL provide isolated Environments for local, development, test/QA, staging/UAT, and production, each with separate database, object storage, secrets, authentication, and logging configuration.
2. THE EDC_System SHALL derive all Audit_Event timestamps from the synchronized server clock and store them as UTC.
3. THE EDC_System SHALL support data retention and SHALL provide backup and restore of the clinical database.
4. THE EDC_System SHALL maintain a Traceability_Matrix mapping each requirement to its design reference and qualification test case.
5. THE EDC_System SHALL maintain clear separation between the Draft, Submitted, Reviewed, Frozen, Locked, and Signed states so that every regulated data change remains attributable.
6. THE EDC_System SHALL support operational qualification and performance qualification test evidence covering authentication, role-based access control, scoping, subject creation, data capture, Reason_For_Change, audit immutability, query workflow, locking, and export.

### Requirement 26: Phased Delivery and Testing

**User Story:** As a delivery lead, I want a phased delivery aligned to testing, so that the MVP ships independently with verified core guarantees.

#### Acceptance Criteria

1. THE EDC_System SHALL deliver Phase 1 comprising authentication, authorization scope enforcement, study, site, and subject setup, eCRF metadata and data capture, the immutable audit trail, manual queries, and CSV export.
2. THE EDC_System SHALL deliver Phase 2 comprising the Edit_Check_Engine, repeating records, SDV, review, and freeze/lock.
3. THE EDC_System SHALL deliver Phase 3 comprising Electronic_Signatures, published-version amendments, and advanced exports.
4. THE EDC_System SHALL independently verify authorization scope enforcement and audit immutability within Phase 1.
5. THE EDC_System SHALL provide automated backend, frontend, permission, and audit test suites covering the delivered requirements.

### Requirement 27: File Attachments

**User Story:** As a site user, I want to upload supporting documents securely, so that source and supporting files are linked to clinical objects with access control.

#### Acceptance Criteria

1. WHERE file upload is enabled for a field or object, THE File_Attachment_Service SHALL store the uploaded file in object storage and SHALL persist the file metadata linked to its clinical object.
2. WHEN a User requests a file download, THE File_Attachment_Service SHALL grant access only if the User has read access to the parent object.
3. WHEN a User deletes a file attachment, THE File_Attachment_Service SHALL apply Soft_Deletion to the attachment.
4. WHEN a file upload, download, or deletion occurs, THE File_Attachment_Service SHALL record an Audit_Event capturing the action.
5. WHILE the parent clinical object is Frozen or Locked, THE File_Attachment_Service SHALL reject new uploads to that object.

### Requirement 28: Notifications

**User Story:** As a user, I want to be notified of relevant clinical workflow events, so that I can act on assigned work promptly.

#### Acceptance Criteria

1. WHEN a Query is assigned to a User's Role, THE Notification_Service SHALL create a notification for the assigned recipients.
2. WHEN a Form_Instance is submitted, THE Notification_Service SHALL create a notification for the responsible reviewers.
3. WHEN an export job completes, THE Notification_Service SHALL create a notification for the requesting User.
4. THE Notification_Service SHALL support the notification statuses Unread, Read, and Archived.
5. WHEN an authorized User requests unread notifications, THE Notification_Service SHALL return the notifications addressed to that User.

### Requirement 29: Performance

**User Story:** As a study team member, I want responsive performance at scale, so that large studies remain usable.

#### Acceptance Criteria

1. WHEN a common read operation is requested, THE API_Layer SHALL return a response within 1 second under typical study load.
2. WHEN a list endpoint is requested, THE API_Layer SHALL return paginated results.
3. WHEN an export or batch validation covers a large dataset, THE EDC_System SHALL process it as an asynchronous job.
4. THE EDC_System SHALL support at least 100 concurrent users in the initial production configuration.
5. THE EDC_System SHALL support studies of at least 100 sites, 10,000 subjects, 100 forms, and 1,000,000 Field_Values.

### Requirement 30: Reliability and Observability

**User Story:** As an operator, I want health checks, structured logs, and monitoring, so that I can detect and diagnose production issues.

#### Acceptance Criteria

1. WHEN the liveness endpoint is requested, THE API_Layer SHALL return the service health status.
2. WHEN the readiness endpoint is requested, THE API_Layer SHALL return the service readiness status.
3. WHEN the metrics endpoint is requested, THE API_Layer SHALL return operational metrics.
4. WHEN a request is processed, THE EDC_System SHALL emit a structured log entry correlated by the request identifier.
5. THE EDC_System SHALL record metrics for API latency, error rate, database connections, worker job failures, export failures, and authentication failures.

### Requirement 31: Optional AI Assistant

**User Story:** As a data manager, I want an optional AI assistant for clinical data management tasks, so that I can draft edit checks and summarize queries with human oversight.

#### Acceptance Criteria

1. WHERE the AI assistant is enabled, THE AI_Assistant_Service SHALL expose endpoints for chat, edit-check drafting, and query summarization backed by AWS Bedrock AgentCore.
2. WHERE the AI assistant is enabled, THE AI_Assistant_Service SHALL stream responses through Server-Sent Events or WebSocket.
3. BEFORE sending clinical context to the AI assistant, THE AI_Assistant_Service SHALL verify the requesting User's Authorization_Scope and SHALL restrict context to data within that scope.
4. IF an AI suggestion would change study data, THEN THE AI_Assistant_Service SHALL require human confirmation before the change is applied.
5. WHEN an AI-assisted action changes regulated data, THE Audit_Service SHALL record an Audit_Event capturing the action.
