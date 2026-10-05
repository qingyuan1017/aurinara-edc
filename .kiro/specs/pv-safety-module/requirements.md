# Requirements Document

## Introduction

This document specifies the requirements for the PV_Safety_Module (pharmacovigilance and safety) inside the Unified_Clinical_Platform. The PV_Safety_Module is a third co-equal first-party module in the same authenticated application as the EDC_System and CTMS_Module. It owns the regulated safety case lifecycle: adverse event and serious adverse event case intake and capture, case workflow (initial, follow-up, closure), seriousness/causality/expectedness/severity assessments, MedDRA medical coding and WHODrug drug coding, case narratives, regulatory reporting and expedited submission timelines (ICSR/E2B(R3) concepts and regulatory clocks), safety reconciliation with EDC-captured adverse events, safety notifications and workflow, the immutable PV safety audit trail, safety exports, and safety dashboards and reports.

The Unified_Clinical_Platform contains the co-equal first-party EDC_System, CTMS_Module, and PV_Safety_Module. The modules share one authenticated application boundary, canonical Study and Site identity, and shared platform capabilities, but they own different records and workflows. EDC owns clinical study configuration, clinical subject records, protocol visits, clinical data, clinical quality workflows, clinical exports, and clinical dashboards. CTMS owns operational study/site profiles/readiness/activation/contacts, operational enrollment targets and milestones, monitoring plans and activities, operational work management, and operational dashboards/reports/exports. PV is authoritative for the safety capabilities listed above and is the safety case system of record. PV is not an external integration and shall not create duplicate clinical subjects or protocol visits, modify EDC clinical records, own the EDC clinical query lifecycle, or become a second clinical data-capture system of record.

The PV_Safety_Module references EDC Subject and Visit_Instance identities and EDC-captured adverse event data through approved, minimized, read-only projections and Coordination_Events, and it reconciles safety cases against EDC-captured adverse events without mutating EDC clinical records. The EDC_System remains the clinical data-capture system of record; the PV_Safety_Module remains the safety case system of record.

The system is built on a defined technology baseline. The backend uses FastAPI on Python 3.11+, Pydantic v2 for schema validation, SQLAlchemy 2.x with Alembic migrations over a PostgreSQL database, served by Uvicorn/Gunicorn, organized under `backend/app/` into api, core, models, repositories, schemas, services, workers, and tests. The frontend is a single-page application under `frontend/src/` built with React, TypeScript, Vite, shadcn/ui, Tailwind CSS, TanStack Query for server state, React Hook Form with Zod for form validation, and TanStack Router/Table for navigation and high-density listings. Optional AWS services may be configured per environment, including Cognito (authentication), S3 (file and export storage), RDS (PostgreSQL), ECS/Fargate (deployment), CloudWatch (logs and metrics), and Bedrock AgentCore (the optional AI assistant).

The system is intended for regulated clinical safety environments and is delivered in phases. Phase 1 delivers the PV MVP: shared authentication and authorization scope enforcement, safety case intake and capture bound to canonical Study/Site and referenced EDC Subject identity, the case workflow state machine, seriousness assessment, the immutable PV safety audit trail, and safety CSV export. Phase 2 adds MedDRA and WHODrug coding, causality/expectedness/severity assessments, case narratives, and EDC adverse-event reconciliation. Phase 3 adds regulatory reporting with expedited timelines, ICSR/E2B(R3) export, advanced safety exports, and the optional AI assistant. EDC and CTMS delivery phases are defined in their own requirements documents. Three cross-cutting concerns drive every PV requirement: authorization scope enforcement, immutable auditability, and safety data integrity under lifecycle controls. Terminology in this document is aligned with the approved EDC and CTMS requirements and designs so requirements remain consistent across the unified platform.

## Glossary

- **Unified_Clinical_Platform**: The single first-party application boundary containing the EDC_System, CTMS_Module, PV_Safety_Module, and shared platform services.
- **EDC_System**: The clinical module that owns clinical configuration, clinical subject records, protocol visits, clinical data, clinical quality workflows, clinical attachments, clinical exports, and clinical dashboards/reports.
- **CTMS_Module**: The operational module that owns operational study/site planning and readiness, enrollment operations, monitoring, work management, operational dashboards/reports, operational exports, and operational attachments.
- **PV_Safety_Module**: The pharmacovigilance and safety module within the Unified_Clinical_Platform that owns Safety_Case intake, safety case lifecycle, safety assessments, medical and drug coding, case narratives, regulatory reporting, safety reconciliation, safety attachments, safety exports, and safety dashboards/reports.
- **Shared_Platform_Service**: A service owned by the Unified_Clinical_Platform for capabilities used by all modules; shared primitive ownership does not transfer ownership of module-specific data or workflow semantics.
- **API_Layer**: The FastAPI versioned REST/JSON interface that authenticates requests, enforces authorization, validates schemas, delegates to the owning module service, and exposes EDC, CTMS, and PV routes under the `/api/v1` prefix.
- **Frontend_Application**: The React/TypeScript single-page application providing the user interface for EDC clinical workflows, CTMS operational workflows, and PV safety workflows.
- **Auth_Service**: The shared platform service handling login, token refresh, logout, current-user identity, password reset, optional MFA, inactivity timeout, invitations, and account deactivation for all modules.
- **Permission_Service**: The shared platform service that resolves and enforces permissions at route level and object level by system, study, and site scope for all modules.
- **Study_Service**: The shared canonical Study identity service used by all modules. EDC owns the clinical Study reference and Study_Version lifecycle; CTMS owns the operational study profile; PV owns the safety use of the Study reference. No module creates a competing Study identity.
- **Site_Service**: The shared canonical Site identity service. EDC owns clinical site use, CTMS owns operational site profile and status, and PV owns safety-reporting site use. No module creates a competing Site identity.
- **Subject_Reference**: The canonical EDC-owned Subject identity referenced by the PV_Safety_Module. PV references a Subject_Reference for a Safety_Case but does not create, allocate, or mutate the EDC clinical subject record.
- **Clinical_Subject_Registry**: The EDC-owned registry of clinical subject identity, identifiers, study/site and Study_Version binding, clinical access state, and clinical subject records.
- **Visit_Instance**: An EDC-owned protocol visit occurrence for a Subject that PV may reference for context without creating or mutating.
- **EDC_Adverse_Event**: An adverse event captured in EDC clinical Field_Values or Form_Records that the PV_Safety_Module reconciles against, exposed to PV only through an approved, minimized, read-only projection.
- **Safety_Case_Service**: The PV-owned service that manages Safety_Case intake, identifiers, case lifecycle, versioning, and case-level records.
- **Safety_Case**: The PV-owned safety case of record for one or more adverse events reported for a Subject_Reference under a Study and Site, with a case identifier, case type, and lifecycle state.
- **Adverse_Event_Record**: A PV-owned record of a single reported adverse event within a Safety_Case, including verbatim term, onset and resolution dates, outcome, and assessment references.
- **Case_Version**: A PV-owned versioned snapshot of a Safety_Case representing an initial or follow-up report, retained immutably once submitted.
- **Assessment_Service**: The PV-owned service that records seriousness, causality, expectedness, and severity assessments for an Adverse_Event_Record or Safety_Case.
- **Seriousness_Assessment**: A PV-owned assessment recording whether an adverse event meets one or more seriousness criteria (death, life-threatening, hospitalization, disability, congenital anomaly, other medically important).
- **Causality_Assessment**: A PV-owned assessment recording the assessed relationship between a suspect product and an adverse event.
- **Expectedness_Assessment**: A PV-owned assessment recording whether an adverse event is expected or unexpected against the reference safety information.
- **Severity_Grade**: A PV-owned severity classification recorded for an adverse event.
- **Coding_Service**: The PV-owned service that assigns and manages MedDRA medical codes and WHODrug drug codes for safety terms.
- **MedDRA_Coding**: A PV-owned assignment of a MedDRA dictionary term to a reported adverse event verbatim term, retaining the dictionary version.
- **WHODrug_Coding**: A PV-owned assignment of a WHODrug dictionary term to a reported product, retaining the dictionary version.
- **Coding_Dictionary_Version**: The identified version of a MedDRA or WHODrug dictionary used for a coding assignment.
- **Narrative_Service**: The PV-owned service that manages structured and free-text Case_Narratives for a Safety_Case.
- **Case_Narrative**: A PV-owned textual account of a Safety_Case with authorship, versioning, and audit history.
- **Regulatory_Reporting_Service**: The PV-owned service that determines reportability, computes regulatory clocks and due dates, produces submissions, and records submission status.
- **Regulatory_Report**: A PV-owned reportable submission for a Safety_Case to a defined regulatory destination, with a report type and submission status.
- **Regulatory_Clock**: A PV-owned computed reporting deadline derived from an awareness date and a configured reporting timeline for a report type and destination.
- **Awareness_Date**: The PV-owned date on which the reporting organization first became aware of the minimum information required to trigger a Regulatory_Clock.
- **Expedited_Report**: A Regulatory_Report subject to an expedited regulatory timeline (for example 7-day or 15-day reporting).
- **ICSR**: An Individual Case Safety Report, the structured safety report representation used for regulatory submission.
- **E2B_Message**: The structured ICSR message representation (E2B(R3) concepts) produced and parsed by the Regulatory_Reporting_Service.
- **Reconciliation_Service**: The PV-owned service that compares Safety_Cases against projected EDC_Adverse_Events and records reconciliation matches and discrepancies.
- **Reconciliation_Discrepancy**: A PV-owned record of a mismatch between a Safety_Case adverse event and a projected EDC_Adverse_Event.
- **Audit_Service**: The shared platform append-only service that records immutable Audit_Events. PV owns safety event content; EDC owns clinical event content; CTMS owns operational event content.
- **Export_Service**: The shared export-job infrastructure that creates jobs, tracks status, stores files, controls downloads, and audits downloads. PV owns safety export content and filtering.
- **Dashboard_Service**: The shared dashboard and reporting infrastructure that applies authorization scope and aggregation primitives. PV owns safety dashboard/report content and may display approved EDC/CTMS projections only as read-only, source-labeled projections.
- **Notification_Service**: The shared platform service that records and delivers notifications. PV owns safety workflow triggers.
- **File_Attachment_Service**: The shared file-storage and metadata primitive. PV owns Safety_Attachments and their safety access/content semantics.
- **Safety_Attachment**: A PV-owned file metadata record and file content associated with a Safety_Case or safety source record.
- **Coordination_Service**: The shared internal service that publishes, consumes, orders, deduplicates, retries, and records approved Coordination_Events between module boundaries.
- **Coordination_Event**: An immutable internal event describing an approved change or projection update between services in the Unified_Clinical_Platform.
- **Safety_Operational_Projection**: A minimized, authorized, read-only view containing only approved fields exchanged between the PV_Safety_Module and another module.
- **Safety_Data**: PV-owned Safety_Cases, Adverse_Event_Records, Case_Versions, assessments, coding assignments, Case_Narratives, Regulatory_Reports, reconciliation records, safety query/action messages, and Safety_Attachments.
- **AI_Assistant_Service**: The optional shared platform AI service that exposes approved PV-, EDC-, or CTMS-scoped assistant capabilities backed by AWS Bedrock AgentCore.
- **User**: An individual account with identity, status, and assigned roles. Accounts are one per individual and are never shared.
- **Role**: A named set of permission codes with a scope of system, study, or site.
- **Permission**: A stable permission code (for example `safety_case.enter`) that authorizes a specific action.
- **Authorization_Scope**: The resolved set of permission grants for a User, each applied at a study and/or site scope.
- **Study**: The canonical shared study identity referenced by all modules.
- **Site**: The canonical shared site identity belonging to a Study and referenced by all modules.
- **Audit_Event**: An immutable, append-only record capturing actor, timestamp, entity, action, old value, new value, reason, and request identifier.
- **Reason_For_Change**: A mandatory textual justification captured when submitted Safety_Data is modified.
- **Electronic_Signature**: A recorded attestation capturing signer identity, timestamp, and meaning, requiring re-authentication.
- **Soft_Deletion**: Logical deletion that retains the record and stores deletion actor, timestamp, and reason, without physical removal.
- **Environment**: An isolated deployment tier (local, development, test/QA, staging/UAT, production) with separate database, storage, secrets, and authentication configuration.
- **Traceability_Matrix**: The mapping of each requirement to its design reference and qualification test case (OQ/PQ).

## Ownership and Boundary Rules

The EDC_System, CTMS_Module, and PV_Safety_Module are co-equal first-party modules inside the Unified_Clinical_Platform. They share authentication, authorization, audit, notifications, file-storage primitives, export-job infrastructure, observability, environment/configuration, API conventions, optional AI controls, and Coordination_Service, but shared primitives do not make any module authoritative for another module's records.

PV is authoritative for the Safety_Case system of record: Safety_Cases and Case_Versions, Adverse_Event_Records, seriousness/causality/expectedness/severity assessments, MedDRA and WHODrug coding assignments, Case_Narratives, Regulatory_Reports and Regulatory_Clocks, reconciliation records, safety notifications triggered by safety workflow, Safety_Attachments, safety dashboards/reports, and safety exports. EDC remains authoritative for clinical study configuration, Clinical_Subject_Registry, protocol Visit_Instances, eCRF metadata and clinical data capture, EDC Queries, SDV, clinical review, freeze/lock, clinical Electronic_Signatures, Clinical_Attachments, and clinical exports. CTMS remains authoritative for operational study/site profiles, enrollment, monitoring, work management, operational attachments, and operational exports.

Study and Site use one canonical shared identity. PV references canonical Study and Site identity and the EDC Subject_Reference and Visit_Instance identity where applicable, but PV shall not create duplicate clinical subjects, allocate clinical subject identifiers, initialize clinical casebooks, create or mutate protocol Visit_Instances, or mutate any EDC clinical record. A Safety_Case is not an EDC clinical record and is not an EDC Query. PV may consume projected EDC_Adverse_Events for reconciliation, but reconciliation shall never modify EDC clinical data.

A Safety_Operational_Projection is an explicit, minimized, authorized, read-only view. Coordination_Service may apply only approved projection updates or explicitly configured coordinated transitions across module boundaries. A PV dashboard, report, export, or attachment requirement in this document refers only to PV safety content unless it explicitly identifies an approved read-only EDC or CTMS projection or shared infrastructure primitive. EDC clinical content remains specified by the EDC requirements document and CTMS operational content by the CTMS requirements document.

### Ownership disposition of affected service names

| Service name | Unified platform disposition | PV responsibility | Other-module responsibility |
|---|---|---|---|
| `Study_Service` | Shared canonical identity with split module semantics | Safety use of the Study reference for cases and reporting | EDC clinical Study/Study_Version; CTMS operational study profile |
| `Site_Service` | Shared canonical identity with split module semantics | Safety-reporting site reference and safety access use | EDC clinical site use; CTMS operational site profile/status |
| `Subject_Reference` | Referenced EDC clinical identity, no PV duplication | Reference a Subject for a Safety_Case using the EDC clinical identifier | EDC owns clinical subject identity, identifiers, and lifecycle |
| `Dashboard_Service` | Shared scope and aggregation primitives with module-owned content | Safety case, assessment, coding, reconciliation, and reporting metrics; approved EDC/CTMS projections are read-only | EDC clinical metrics; CTMS operational metrics |
| `Export_Service` | Shared export-job infrastructure with module-owned content | Safety case, ICSR/E2B, and safety audit export content, filters, and authorization | EDC clinical export content; CTMS operational export content |
| `File_Attachment_Service` | Shared storage, metadata, access, retention, and soft-deletion primitives | Safety_Attachments and safety/source access rules | EDC Clinical_Attachments; CTMS Operational_Attachments |
| `Audit_Service` | Shared immutable append-only primitive with module-owned content | PV safety Audit_Event content and safety audit search/export | EDC clinical and CTMS operational audit content |

## Requirements

### Requirement 1: Shared Authentication and Session Reuse

**User Story:** As a safety user, I want to authenticate through the shared platform and maintain a protected session, so that only authorized individuals access safety data without a second identity system.

#### Acceptance Criteria

1. THE PV_Safety_Module SHALL authenticate every request through the shared Auth_Service and SHALL NOT introduce a separate PV identity or session system.
2. WHEN a User with a valid, unexpired, unrevoked access token requests a PV route, THE Auth_Service SHALL resolve the User identity and Authorization_Scope for that request before the request reaches any Safety_Data operation.
3. IF a User presents an invalid, expired, or revoked token to a PV route, THEN THE API_Layer SHALL reject the request, SHALL return an authentication error indicating that valid authentication is required without disclosing whether the token was invalid, expired, or revoked, and SHALL NOT change any Safety_Data.
4. WHILE a session has had no authenticated activity for more than 1,800 seconds, THE Auth_Service SHALL reject access tokens for PV routes until re-authentication occurs.
5. WHEN a PV route request is rejected due to the 1,800-second inactivity limit, THE Auth_Service SHALL require the User to re-authenticate before granting access to any PV route and SHALL NOT change any Safety_Data.
6. WHERE Cognito is configured as the identity provider, THE Auth_Service SHALL validate Cognito-issued JWT access tokens for PV routes and map the token subject to an internal User.

### Requirement 2: Authorization and Permission Enforcement for Safety

**User Story:** As a security officer, I want every PV action authorized server-side by study and site scope, so that users access only the safety data they are permitted to.

#### Acceptance Criteria

1. WHEN a request targets a protected PV route, THE Permission_Service SHALL permit the request only if the resolved Authorization_Scope contains the required Permission for the target study and site.
2. IF the resolved Authorization_Scope lacks the required Permission for the target study or site, THEN THE API_Layer SHALL return an authorization error identifying the missing permission and target scope, SHALL leave all Safety_Data unchanged, and SHALL NOT change Safety_Data.
3. WHEN a User requests a list of Safety_Cases or Regulatory_Reports, THE Permission_Service SHALL return only records whose study and site scopes are contained in the User's Authorization_Scope, and SHALL return an empty list when no records qualify.
4. IF a User requests a PV object belonging to a study or site outside the User's Authorization_Scope, THEN THE Permission_Service SHALL deny access, SHALL return an access-denied indication that does not disclose whether the requested PV object exists, and SHALL NOT change Safety_Data.
5. THE Permission_Service SHALL enforce PV authorization independently of any Frontend_Application permission checks.
6. THE Permission_Service SHALL support PV-specific safety roles without granting those roles authority to mutate EDC-owned clinical records or CTMS-owned operational records.

### Requirement 3: Safety Case Intake and Capture

**User Story:** As a safety associate, I want to intake and capture adverse event cases, so that reported safety events are recorded under the correct study, site, and subject reference.

#### Acceptance Criteria

1. WHEN a User with safety case-intake authorization creates a Safety_Case under a valid Study and Site with a valid Subject_Reference and a case type, THE Safety_Case_Service SHALL persist exactly one Safety_Case bound to that Study, Site, and Subject_Reference.
2. THE Safety_Case_Service SHALL generate a safety case identifier that is unique within the Unified_Clinical_Platform.
3. WHEN an authorized User adds an Adverse_Event_Record to a Safety_Case, THE Safety_Case_Service SHALL persist a verbatim term of 1 to 200 characters, an onset date, and an outcome.
4. WHERE an Adverse_Event_Record includes a resolution date, THE Safety_Case_Service SHALL persist the resolution date only when it is no earlier than the onset date.
5. IF a Safety_Case creation references a Subject_Reference, Study, or Site that does not exist in canonical identity, THEN THE Safety_Case_Service SHALL reject the request, return an error identifying the missing reference, and persist no Safety_Case.
6. IF a Safety_Case creation supplies a safety case identifier that already exists in the Unified_Clinical_Platform, THEN THE Safety_Case_Service SHALL reject the request, return an error indicating a duplicate identifier, and change no existing record.
7. IF an Adverse_Event_Record supplies a resolution date earlier than the onset date or a verbatim term outside 1 to 200 characters, THEN THE Safety_Case_Service SHALL reject the request, return an error identifying the invalid field, and persist no Adverse_Event_Record.
8. WHEN valid safety case data is saved, THE Audit_Service SHALL record exactly one PV safety Audit_Event capturing the change.
9. IF submitted safety case data is invalid, THEN THE Safety_Case_Service SHALL persist neither the invalid data nor any change event.
10. THE Safety_Case_Service SHALL reference the EDC Subject_Reference and SHALL NOT create, allocate, or mutate an EDC clinical subject record.

### Requirement 4: Safety Case Lifecycle and Versioning

**User Story:** As a safety manager, I want a controlled case lifecycle with initial and follow-up versions, so that case progression is traceable and submitted versions are immutable.

#### Acceptance Criteria

1. THE Safety_Case_Service SHALL permit only these case lifecycle transitions: Open to In Review, In Review to Follow-up Required or Ready to Report or Closed, Follow-up Required to In Review, Ready to Report to Reported or In Review, Reported to Closed or Follow-up Required, and Closed to Reopened.
2. IF a lifecycle transition other than those enumerated in criterion 1 is requested, THEN THE Safety_Case_Service SHALL reject the request, SHALL leave the Safety_Case state and content unchanged, and SHALL return an error indicating the transition is not permitted.
3. WHEN an authorized User submits a Case_Version and no prior submitted Case_Version exists for that Safety_Case, THE Safety_Case_Service SHALL record the version as the initial version with sequence number 1.
4. WHEN an authorized User submits a Case_Version and at least one prior submitted Case_Version exists for that Safety_Case, THE Safety_Case_Service SHALL record the version as a follow-up version with a sequence number equal to the highest existing sequence number plus 1.
5. WHILE a Case_Version is in submitted status, IF any modification to that version's captured content is requested, THEN THE Safety_Case_Service SHALL reject the modification, SHALL preserve the submitted version's captured content unchanged, and SHALL return an error indicating the version is immutable.
6. IF an authorized User changes submitted Safety_Data and the accompanying Reason_For_Change is empty or exceeds 4,000 characters, THEN THE Safety_Case_Service SHALL reject the change, SHALL leave the submitted Safety_Data unchanged, and SHALL return an error indicating a valid Reason_For_Change is required.
7. WHEN an authorized User changes submitted Safety_Data with a Reason_For_Change that is non-empty and no more than 4,000 characters, THE Safety_Case_Service SHALL persist the change together with the Reason_For_Change.
8. THE Safety_Case_Service SHALL retain all prior submitted Case_Versions for traceability such that no submitted Case_Version is deleted or overwritten.
9. WHEN a case lifecycle transition or Case_Version submission occurs, THE Audit_Service SHALL record exactly one PV safety Audit_Event capturing the action, the acting User, and the timestamp.

### Requirement 5: Safety Assessments

**User Story:** As a safety physician, I want to record seriousness, causality, expectedness, and severity assessments, so that each adverse event is characterized for reporting decisions.

#### Acceptance Criteria

1. WHEN an authorized User records a Seriousness_Assessment marking an Adverse_Event_Record as serious, THE Assessment_Service SHALL persist the serious determination together with at least one seriousness criterion among death, life-threatening, hospitalization, disability, congenital anomaly, and other medically important condition.
2. WHEN an authorized User records a Seriousness_Assessment marking an Adverse_Event_Record as not serious, THE Assessment_Service SHALL persist the not-serious determination.
3. IF a Seriousness_Assessment marks an Adverse_Event_Record as serious without at least one seriousness criterion, THEN THE Assessment_Service SHALL reject the assessment, return an error indicating a seriousness criterion is required, and preserve the existing assessment state.
4. WHEN an authorized User records a Causality_Assessment, THE Assessment_Service SHALL persist the assessed suspect product, the causality category, and the assessing actor and timestamp.
5. WHEN an authorized User records an Expectedness_Assessment, THE Assessment_Service SHALL persist an expected or unexpected determination against the referenced safety information.
6. WHEN an authorized User records a Severity_Grade, THE Assessment_Service SHALL persist the configured severity classification for the Adverse_Event_Record.
7. IF an assessment references an Adverse_Event_Record or suspect product that does not exist, THEN THE Assessment_Service SHALL reject the assessment, return an error identifying the missing reference, and persist no assessment.
8. IF the parent Safety_Case is Closed, THEN THE Assessment_Service SHALL reject new or changed assessments, return an error indicating the Safety_Case is Closed, and preserve the existing assessment state.
9. WHEN an assessment is created or changed, THE Audit_Service SHALL record exactly one PV safety Audit_Event capturing the acting User, the timestamp, the prior value, and the new value.

### Requirement 6: MedDRA and WHODrug Coding

**User Story:** As a coding specialist, I want to code events and products with MedDRA and WHODrug, so that safety terms are standardized and version-controlled.

#### Acceptance Criteria

1. WHEN a User with coding authorization assigns a MedDRA_Coding to an Adverse_Event_Record verbatim term, THE Coding_Service SHALL persist the selected MedDRA term, the Coding_Dictionary_Version used, and the assigning User and timestamp.
2. WHEN a User with coding authorization assigns a WHODrug_Coding to a reported product, THE Coding_Service SHALL persist the selected WHODrug term, the Coding_Dictionary_Version used, and the assigning User and timestamp.
3. IF a coding assignment references a dictionary term that does not exist in the identified Coding_Dictionary_Version, THEN THE Coding_Service SHALL reject the assignment, return an error identifying the invalid term and version, and persist no coding.
4. IF a coding assignment references a Coding_Dictionary_Version that is missing or unavailable, THEN THE Coding_Service SHALL reject the assignment, return an error indicating the dictionary version is unavailable, and persist no coding.
5. WHEN an authorized User recodes a previously coded term, THE Coding_Service SHALL retain the prior coding assignment and its Coding_Dictionary_Version immutably and SHALL record the traceability link from the prior assignment to the new assignment.
6. WHEN a coding assignment is created or changed, THE Audit_Service SHALL record one PV safety Audit_Event capturing the acting User, the timestamp, the prior value, the new value, and the Coding_Dictionary_Version.

### Requirement 7: Case Narratives

**User Story:** As a safety writer, I want to author and revise case narratives, so that each case has a clear, version-controlled account of events.

#### Acceptance Criteria

1. WHEN an authorized User creates a Case_Narrative for a Safety_Case with narrative text that is non-empty after trimming leading and trailing whitespace and is no more than 20,000 characters, THE Narrative_Service SHALL persist the narrative text with the authoring actor and timestamp.
2. WHEN an authorized User revises a Case_Narrative with a Reason_For_Change that is non-empty after trimming leading and trailing whitespace and is no more than 4,000 characters, THE Narrative_Service SHALL retain the prior narrative version and record the revising actor, timestamp, and the Reason_For_Change.
3. IF an authorized User attempts to create a Case_Narrative with narrative text that is empty after trimming whitespace or exceeds 20,000 characters, or attempts to revise a Case_Narrative with a Reason_For_Change that is empty after trimming whitespace or exceeds 4,000 characters, THEN THE Narrative_Service SHALL reject the operation, return an error indication identifying the invalid field, and preserve the existing narrative state.
4. IF the parent Safety_Case is Closed, THEN THE Narrative_Service SHALL reject new or revised narratives, return an error indication that the Safety_Case is Closed, and preserve the existing narrative state.
5. WHEN a Case_Narrative is created or revised, THE Audit_Service SHALL record one PV safety Audit_Event capturing the change.

### Requirement 8: Regulatory Reporting and Expedited Timelines

**User Story:** As a regulatory safety officer, I want reportability determination and regulatory clocks, so that expedited safety reports are submitted within required timelines.

#### Acceptance Criteria

1. WHEN a Safety_Case satisfies exactly one configured reportability rule, THE Regulatory_Reporting_Service SHALL create one Regulatory_Report with a report type, a destination, and a status of Pending.
2. WHEN a Safety_Case satisfies more than one configured reportability rule, THE Regulatory_Reporting_Service SHALL create one Regulatory_Report per matched rule, each with a report type, a destination, and a status of Pending.
3. WHEN a Regulatory_Report is created, THE Regulatory_Reporting_Service SHALL compute the Regulatory_Clock due date by adding the configured reporting-timeline days, constrained to a whole number between 1 and 90 inclusive, to the Awareness_Date, counting whole calendar days in UTC where the Awareness_Date counts as day zero.
4. IF a Regulatory_Report is created while its Awareness_Date is absent, THEN THE Regulatory_Reporting_Service SHALL reject the creation without creating the Regulatory_Report and SHALL return an error indicating that the Awareness_Date is required.
5. THE Regulatory_Reporting_Service SHALL permit only these Regulatory_Report transitions: Pending to Submitted or Cancelled, Submitted to Acknowledged or Rejected, and Rejected to Pending; IF any other transition is requested, THEN THE Regulatory_Reporting_Service SHALL reject it without changing the Regulatory_Report and SHALL return an error indicating the transition is not permitted.
6. WHERE a Regulatory_Report is an Expedited_Report, WHEN its overdue status is evaluated, THE Regulatory_Reporting_Service SHALL flag the report as overdue if the current UTC date is later than its Regulatory_Clock due date and the report status is not Submitted, Acknowledged, or Cancelled.
7. WHEN an authorized User marks a Regulatory_Report as Submitted, THE Regulatory_Reporting_Service SHALL record the submitting actor identifier, the submission timestamp in UTC, and the submitted E2B_Message reference.
8. IF an authorized User marks a Regulatory_Report as Submitted without a valid E2B_Message reference, THEN THE Regulatory_Reporting_Service SHALL reject the submission, retain the report in its prior status, and return an error indicating the E2B_Message reference is required.
9. WHEN a Regulatory_Report action occurs, THE Audit_Service SHALL record one PV safety Audit_Event capturing the action.

### Requirement 9: ICSR and E2B Message Handling

**User Story:** As an integrator, I want ICSR messages produced and parsed in E2B(R3) form, so that safety cases exchange with regulatory destinations reliably.

#### Acceptance Criteria

1. WHEN an authorized User generates an ICSR for a reportable Safety_Case, THE Regulatory_Reporting_Service SHALL produce an E2B_Message that conforms to the E2B(R3) structure and contains the case identifier, every field designated mandatory by the E2B(R3) structure, and the Coding_Dictionary_Versions used.
2. IF a Safety_Case is missing a field designated mandatory by the E2B(R3) structure, THEN THE Regulatory_Reporting_Service SHALL return an error naming each missing mandatory field, SHALL produce no E2B_Message, and SHALL leave the Safety_Case unchanged.
3. WHEN an authorized User imports a structurally valid E2B_Message, THE Regulatory_Reporting_Service SHALL parse it into a Safety_Case representation containing the case identifier, the mandatory fields, and the Coding_Dictionary_Versions from the message.
4. IF an authorized User imports a structurally invalid E2B_Message, THEN THE Regulatory_Reporting_Service SHALL reject the message with a descriptive error and SHALL create no Safety_Case.
5. FOR ALL valid E2B_Messages produced by the Regulatory_Reporting_Service, parsing the produced message then producing a message SHALL yield an E2B_Message identical in case identifier, every mandatory field, and Coding_Dictionary_Versions (round-trip property).

### Requirement 10: EDC Adverse Event Reconciliation

**User Story:** As a data manager, I want to reconcile safety cases against EDC-captured adverse events, so that safety and clinical data agree without either module writing the other's records.

#### Acceptance Criteria

1. WHEN an authorized User runs reconciliation for a Study, THE Reconciliation_Service SHALL compare Safety_Cases against projected EDC_Adverse_Events for that Study within the User's Authorization_Scope on the reconciled field set of subject reference, verbatim term, onset date, and seriousness.
2. WHEN a Safety_Case adverse event and a projected EDC_Adverse_Event differ on any reconciled field, THE Reconciliation_Service SHALL record one Reconciliation_Discrepancy identifying the affected Safety_Case, the EDC reference, and each differing field.
3. WHEN a reconciliation run completes, THE Reconciliation_Service SHALL record the count of matches and discrepancies for that run within the User's Authorization_Scope.
4. THE Reconciliation_Service SHALL consume EDC_Adverse_Events only through an approved, minimized, read-only Safety_Operational_Projection delivered by the Coordination_Service.
5. IF the required Safety_Operational_Projection is unavailable or stale, THEN THE Reconciliation_Service SHALL not produce reconciliation results and SHALL return an error indicating the EDC projection is unavailable.
6. IF a reconciliation operation attempts to modify an EDC clinical record, THEN THE API_Layer SHALL reject the operation, return an error indicating EDC records are read-only to PV, and change neither EDC clinical state nor PV safety state.
7. WHEN a Reconciliation_Discrepancy is created or resolved, THE Audit_Service SHALL record one PV safety Audit_Event capturing the action.

### Requirement 11: PV Safety Audit Trail

**User Story:** As a regulatory reviewer, I want a complete and immutable audit trail for PV safety activity, so that every regulated safety change is attributable and traceable.

#### Acceptance Criteria

1. WHEN a PV Safety_Data change is committed, THE Audit_Service SHALL, within the same transaction as the change and no later than 1 second after commit, record exactly one immutable PV safety Audit_Event containing actor, UTC timestamp, entity type, entity identifier, study, site, and action, plus old value and new value for value changes and a Reason_For_Change for post-submission changes.
2. IF a caller requests an update or delete of a PV safety Audit_Event, THEN THE Audit_Service SHALL reject the request, SHALL return an error indicating that Audit_Events are immutable, and SHALL NOT change any existing Audit_Event.
3. WHEN a Safety_Attachment upload, download, or deletion occurs, THE Audit_Service SHALL record one PV safety Audit_Event capturing the action.
4. WHEN an authorized User searches PV safety audit history, THE Audit_Service SHALL return only PV safety Audit_Events within the User's Authorization_Scope, SHALL support exact filtering by user, inclusive UTC date range, entity, Safety_Case, and Regulatory_Report, and SHALL return matching Audit_Events ordered by UTC timestamp ascending with ties broken by Audit_Event identifier ascending.
5. WHEN an authorized User exports PV safety audit history, THE Audit_Service SHALL produce an export containing exactly the authorized PV safety Audit_Events selected by the request and SHALL record the export action.
6. THE Audit_Service SHALL provide the same immutable append-only primitive to PV as to EDC and CTMS, and IF a PV operation attempts to alter an EDC clinical or CTMS operational Audit_Event, THEN THE Audit_Service SHALL reject it without changing that module's audit state.
7. IF recording a PV safety Audit_Event fails while committing a PV Safety_Data change or Safety_Attachment action, THEN THE Audit_Service SHALL roll back the associated change so that no Safety_Data or Safety_Attachment state persists without its Audit_Event, and SHALL return an error indicating the audit failure.
8. IF a User requests to search or export PV safety audit history outside the User's Authorization_Scope, THEN THE Audit_Service SHALL reject the request, SHALL NOT return or export any out-of-scope Audit_Event, and SHALL return an error indicating insufficient authorization.

### Requirement 12: Safety Data Export

**User Story:** As a safety manager, I want to export PV safety data in multiple formats, so that safety data can be analyzed and submitted downstream.

#### Acceptance Criteria

1. WHEN an authorized User requests a PV safety export, THE Export_Service SHALL create one job in Queued, Running, Completed, or Failed state, SHALL permit only Queued to Running to Completed or Failed transitions, SHALL store the generated safety file when the job completes, and IF a job remains in Running for more than 900 seconds, THEN THE Export_Service SHALL transition it to Failed and retain a failure indication identifying the failure reason without producing a downloadable file.
2. WHEN an authorized User requests a safety case-list export, THE Export_Service SHALL produce only the Safety_Cases within the requested Authorization_Scope and SHALL produce an empty result when no case qualifies.
3. THE Export_Service SHALL apply study, site, subject reference, case status, seriousness, report status, and inclusive UTC date-range filters as intersections, and IF the requested UTC date-range span exceeds 1,830 days, THEN THE Export_Service SHALL reject the request without creating a Completed job.
4. WHEN an authorized User downloads their authorized completed PV safety export file within 900 seconds of job completion, THE Export_Service SHALL provide the file and SHALL record one PV safety Audit_Event for the download.
5. THE Export_Service SHALL accept and produce exactly the PV safety formats CSV, Excel, JSON, and E2B XML, and SHALL reject any other requested format without creating a Completed job.
6. THE PV_Safety_Module SHALL keep PV safety export content and filters separate from EDC clinical and CTMS operational export content, and WHERE an explicitly approved minimized projection is included, THE Export_Service SHALL label it as projected content and exclude unapproved fields.
7. IF a User requests download of a PV safety export file more than 900 seconds after job completion, or requests a completed job that does not belong to that User, THEN THE Export_Service SHALL deny the download and SHALL NOT provide the file.

### Requirement 13: Safety Dashboards and Reports

**User Story:** As a safety team member, I want PV safety dashboards and reports, so that I can monitor case volume, seriousness, and reporting compliance without conflating safety metrics with clinical or operational metrics.

#### Acceptance Criteria

1. WHEN an authorized User requests a PV safety study dashboard, THE Dashboard_Service SHALL return, within 5 seconds, Safety_Case counts grouped by case lifecycle status, adverse event counts grouped by seriousness, and Regulatory_Report counts grouped by report status, computed from PV records within the User's Authorization_Scope as of the request timestamp.
2. WHEN an authorized User requests PV reporting-compliance metrics, THE Dashboard_Service SHALL return, within 5 seconds, mutually exclusive counts of Regulatory_Reports classified as submitted when the report status is Submitted, overdue when the report is not Submitted and its Regulatory_Clock due date is earlier than the current UTC date, and on time when the report is not Submitted and its Regulatory_Clock due date is not earlier than the current UTC date.
3. WHEN an authorized User requests a PV safety site dashboard, THE Dashboard_Service SHALL return only PV safety metrics for sites within the User's Authorization_Scope and SHALL return zero-valued metrics when no qualifying safety records exist.
4. THE Dashboard_Service SHALL compute all PV safety dashboard and report metrics from PV records within the requesting User's Authorization_Scope.
5. WHERE an approved EDC or CTMS projection is available, THE Dashboard_Service SHALL display only its approved fields with a source label and SHALL prevent those fields from being used in PV safety metric calculations or mutated through PV.

### Requirement 14: Safety Notifications

**User Story:** As a safety workflow user, I want notifications for relevant PV safety events, so that assigned safety work and reporting deadlines are acted on promptly.

#### Acceptance Criteria

1. WHEN a Safety_Case that meets a serious seriousness criterion is created, THE Notification_Service SHALL create one PV safety notification for each resolved assigned safety recipient within 60 seconds of case creation.
2. WHEN a Regulatory_Clock due date is within a configured warning window of 1 through 30 days and the Regulatory_Report is not Submitted, THE Notification_Service SHALL create one PV safety notification identifying the report and its due date within 60 seconds of the warning window being entered.
3. WHEN a PV safety export job reaches Completed or Failed, THE Notification_Service SHALL create one PV safety notification for the requesting User within 60 seconds and SHALL identify the job outcome.
4. THE Notification_Service SHALL support only the PV safety notification statuses Unread, Read, and Archived, and SHALL permit only Unread to Read or Archived and Read to Archived transitions.
5. WHEN an authorized User requests unread PV safety notifications, THE Notification_Service SHALL return only notifications addressed to that User with status Unread and SHALL return an empty list when none qualify.
6. THE Notification_Service SHALL remain shared infrastructure while PV owns notifications triggered by PV safety workflow.
7. IF a Regulatory_Report warning-window condition is re-evaluated and an unarchived PV safety notification already exists for the same report and due date, THEN THE Notification_Service SHALL create no additional notification for that report and due date.
8. IF a Safety_Case that meets a serious seriousness criterion is created and no assigned safety recipient resolves, THEN THE Notification_Service SHALL create no per-recipient notification and SHALL record one PV safety Audit_Event indicating that no recipient was resolved.

### Requirement 15: Safety File Attachments

**User Story:** As a safety associate, I want to upload safety supporting documents securely, so that source and supporting files are linked to safety cases with access control.

#### Acceptance Criteria

1. WHERE file upload is enabled for a Safety_Case or safety object, THE File_Attachment_Service SHALL store a non-empty file no larger than 100 MB as a Safety_Attachment in object storage and persist metadata linked to that safety object, and IF the file is empty or larger than 100 MB, THEN THE File_Attachment_Service SHALL reject the upload with an error indication identifying the failed validation, store no Safety_Attachment, and persist no metadata.
2. WHEN a User requests a Safety_Attachment download, THE File_Attachment_Service SHALL grant access only when the User has read access to the parent Safety_Case and SHALL reject the request without revealing file content otherwise.
3. WHEN an authorized User deletes an active Safety_Attachment, THE File_Attachment_Service SHALL apply Soft_Deletion, retain the metadata and deletion reason, and prevent subsequent downloads through normal attachment access.
4. WHEN a Safety_Attachment upload, download, or deletion completes, THE Audit_Service SHALL record one PV safety Audit_Event for that action, and IF the attachment action fails, THEN THE Audit_Service SHALL record no completed-action event.
5. WHILE the parent Safety_Case is Closed, THE File_Attachment_Service SHALL reject new Safety_Attachment uploads and preserve existing attachment state.
6. THE PV_Safety_Module SHALL not own or mutate EDC Clinical_Attachments or CTMS Operational_Attachments, and IF a PV operation targets another module's attachment, THEN THE File_Attachment_Service SHALL reject it without changing that module's attachment state.
7. IF object storage is unavailable during a Safety_Attachment upload, THEN THE File_Attachment_Service SHALL reject the upload with an error indication, persist no Safety_Attachment metadata, and leave no partial file stored.

### Requirement 16: Shared API Layer Standards for Safety

**User Story:** As an integrator, I want consistent versioned APIs for PV, so that clients interact with the Unified_Clinical_Platform predictably and safely.

#### Acceptance Criteria

1. THE API_Layer SHALL expose PV endpoints under /api/v1/pv and SHALL return response bodies validated by Pydantic v2 schemas.
2. WHEN a PV list endpoint is requested, THE API_Layer SHALL return a pagination envelope containing items, page number greater than or equal to 1, page size from 1 through 1,000, and total count greater than or equal to 0.
3. IF a PV request fails, THEN THE API_Layer SHALL return a standard error envelope containing an error code, a message indicating the failed operation, and details limited to caller-safe validation or authorization information, without exposing internal database errors, prohibited safety data, or raw coordination payloads.
4. WHEN a request changes PV Safety_Data, THE API_Layer SHALL guarantee that the corresponding PV safety Audit_Event is written within the same database transaction as the safety data change.
5. WHEN a PV request is received, THE API_Layer SHALL assign one request identifier, return that identifier in the response, and include the same identifier in every Audit_Event and Coordination_Event created by that request.
6. IF a PV route attempts to mutate an EDC-owned or CTMS-owned record, THEN THE API_Layer SHALL reject the request before any module's authoritative state or audit state changes.

### Requirement 17: Database and Persistence for Safety

**User Story:** As a platform engineer, I want a well-structured PV persistence model, so that safety data is stored with integrity, retained, and efficiently queried.

#### Acceptance Criteria

1. THE PV_Safety_Module SHALL store Safety_Case data separately from EDC clinical data and CTMS operational data.
2. WHEN a Safety_Case, Adverse_Event_Record, Case_Narrative, Regulatory_Report, Safety_Attachment, or other PV safety record is deleted, THE PV_Safety_Module SHALL apply Soft_Deletion, retain the record and its deletion actor, timestamp, and reason, and SHALL not physically remove it or any related Audit_Event.
3. THE PV_Safety_Module SHALL store every timestamp with UTC timezone information and SHALL preserve at least one-second precision; THE Frontend_Application SHALL convert timestamps to local time only for display.
4. THE PV_Safety_Module SHALL reject duplicate safety case identifiers globally without changing the existing records.
5. THE PV_Safety_Module SHALL use UUID primary keys and SHALL provide queryable indexes for study identifier, site identifier, subject reference, case identifier, case status, report status, and creation timestamp.
6. THE PV_Safety_Module SHALL persist Coordination_Event references by correlation identifier so projected EDC references remain traceable without duplicating EDC clinical records.

### Requirement 18: Backend Architecture and Coding Rules for Safety

**User Story:** As a backend maintainer, I want enforced architectural layering in PV, so that the safety codebase remains secure, testable, and consistent with the platform.

#### Acceptance Criteria

1. THE PV_Safety_Module SHALL keep route handlers limited to input validation, permission checks, and delegation, and SHALL execute business-rule decisions in the delegated service layer under `backend/app/services`.
2. THE PV_Safety_Module SHALL permit database access only through repository-layer operations under `backend/app/repositories`, and SHALL reject or fail verification for direct database access from routes or services.
3. WHEN a service mutates PV Safety_Data, THE PV_Safety_Module SHALL commit the data change and corresponding Audit_Event together, and IF either write fails, THEN THE PV_Safety_Module SHALL commit neither.
4. WHEN a protected PV operation is requested, THE PV_Safety_Module SHALL resolve the required Permission and target scope through the Permission_Service before mutating data.

### Requirement 19: Frontend Safety Application

**User Story:** As a safety user, I want a clear, permission-aware safety interface, so that I can perform safety workflows efficiently and safely.

#### Acceptance Criteria

1. THE Frontend_Application SHALL display the same textual status value for each Safety_Case, Case_Version, assessment, coding, Regulatory_Report, and reconciliation state in list and case-detail views.
2. WHEN a User enters safety data, THE Frontend_Application SHALL run the applicable Zod validation before submission, and IF client validation fails, THEN THE Frontend_Application SHALL send no request while the API_Layer remains authoritative.
3. WHEN a User edits submitted safety data, THE Frontend_Application SHALL require a non-empty Reason_For_Change of no more than 4,000 characters before sending the change to the API_Layer.
4. WHILE a Safety_Case is Closed, THE Frontend_Application SHALL render its input controls as disabled.
5. WHEN a User opens PV audit history or a case narrative history, THE Frontend_Application SHALL render the requested details in a dialog or sheet while keeping the originating safety status view mounted and visible.
6. IF a User lacks permission for a PV action or route, THEN THE Frontend_Application SHALL hide the action or render an access-denied view, and SHALL rely on the API_Layer to enforce the same denial.

### Requirement 20: Compliance, Validation, and Environment Management for Safety

**User Story:** As a quality and compliance lead, I want regulatory-aligned controls for PV across isolated environments, so that safety workflows support 21 CFR Part 11, GVP, ALCOA+, and HIPAA-aware operation under the same platform controls.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL provide isolated local, development, test/QA, staging/UAT, and production Environments for PV, and SHALL prevent each Environment from reading another Environment's database, object storage, secrets, authentication configuration, or logs.
2. THE Audit_Service SHALL derive PV safety Audit_Event timestamps from the server clock, store them as UTC, and maintain server-clock agreement within 5 seconds across participating services.
3. THE Unified_Clinical_Platform SHALL retain PV safety records for at least 7 years, create at least one backup in every 24-hour period, and restore PV records within 4 hours without restoring them into another module's authoritative records.
4. THE PV_Safety_Module SHALL maintain a Traceability_Matrix mapping each PV requirement to its design reference and qualification test case.
5. THE PV_Safety_Module SHALL represent Open, In Review, Ready to Report, Reported, and Closed as distinct case states, SHALL permit only configured transitions, and SHALL retain actor, timestamp, and reason data for every regulated safety change.
6. THE Unified_Clinical_Platform SHALL provide qualification evidence that includes at least one passing OQ or PQ test for each listed PV capability: shared authentication, scope enforcement, safety case intake, case lifecycle, seriousness assessment, audit immutability, regulatory clock computation, and safety export.

### Requirement 21: PV Phased Delivery and Testing

**User Story:** As a delivery lead, I want PV safety delivery aligned to testing, so that the PV MVP ships independently with verified safety guarantees while EDC and CTMS delivery remain independently phased.

#### Acceptance Criteria

1. THE PV_Safety_Module SHALL designate Phase 1 complete only when shared authentication, PV authorization scope enforcement, safety case intake bound to canonical identity, the case lifecycle state machine, seriousness assessment, immutable PV safety audit, and safety CSV export each have a passing qualification test.
2. THE PV_Safety_Module SHALL designate Phase 2 complete only when MedDRA coding, WHODrug coding, causality/expectedness/severity assessments, Case_Narratives, and EDC adverse-event reconciliation each have a passing qualification test.
3. THE PV_Safety_Module SHALL designate Phase 3 complete only when regulatory reporting with expedited timelines, ICSR/E2B message handling, advanced safety exports, and the optional AI assistant each have a passing qualification test.
4. THE PV_Safety_Module SHALL complete at least one passing Phase 1 test for authorization scope enforcement, PV safety ownership, EDC non-modification boundaries, and audit immutability before declaring Phase 1 complete.
5. THE PV_Safety_Module SHALL provide automated backend, frontend, permission, audit, ownership-boundary, and safety-regression tests for every delivered PV capability, and SHALL not declare a phase complete while any required test is failing.
6. THE PV_Safety_Module SHALL treat EDC clinical delivery and CTMS operational delivery as governed only by their own requirements documents, and SHALL not count their capabilities as PV phase deliverables.

### Requirement 22: Optional AI Assistant for Safety

**User Story:** As a safety physician, I want an optional AI assistant for safety tasks, so that I can draft case narratives and summarize cases with human oversight.

#### Acceptance Criteria

1. WHERE the AI assistant is enabled, THE AI_Assistant_Service SHALL expose chat, narrative-drafting, and case-summarization operations backed by AWS Bedrock AgentCore; IF the AI assistant is disabled, THEN THE AI_Assistant_Service SHALL expose none of those operations.
2. WHERE the AI assistant is enabled, WHEN a request is accepted, THE AI_Assistant_Service SHALL begin streaming the response through Server-Sent Events or WebSocket within 5 seconds and SHALL emit a terminal completion or error indication within the same stream within 120 seconds of request acceptance.
3. BEFORE sending safety context to the AI assistant, THE AI_Assistant_Service SHALL verify the requesting User's Authorization_Scope; IF the requested context is outside that scope, THEN THE AI_Assistant_Service SHALL send no safety context and SHALL return a rejection indication identifying the request as denied for authorization reasons.
4. IF an AI suggestion would change Safety_Data, THEN THE AI_Assistant_Service SHALL require an explicit human confirmation for that specific change and SHALL apply no change when confirmation is declined or when no confirmation is received within 300 seconds of the suggestion being presented.
5. WHEN a confirmed AI-assisted action changes regulated PV Safety_Data, THE Audit_Service SHALL record one PV safety Audit_Event identifying the User, the changed safety object, the action, and the AI-assisted origin.
6. IF the AWS Bedrock AgentCore backend or the response stream fails before a terminal completion indication is emitted, THEN THE AI_Assistant_Service SHALL emit an error indication within the same stream identifying the operation as failed and SHALL apply no change to Safety_Data.

### Requirement 23: Unified Platform Safety Ownership and Coordination

**User Story:** As a platform owner, I want the PV module boundary enforced explicitly, so that safety workflows coexist with clinical and operational workflows without creating competing clinical authority.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL assign exactly one authoritative module to each persisted field of a Study, Site, Subject, Visit_Instance, projection, clinical record, operational record, and safety record.
2. IF a field assignment has zero or more than one authoritative module, THEN THE Unified_Clinical_Platform SHALL reject the assignment and SHALL return an error indicating the ownership conflict.
3. THE Unified_Clinical_Platform SHALL use one canonical shared identity for each Study and Site, and SHALL require every PV reference to a Subject or Visit_Instance to use the EDC clinical identifier without creating a duplicate clinical identity.
4. IF a PV command attempts to create or mutate an EDC-owned Study_Version, Clinical_Subject_Registry record, Visit_Instance, Form_Instance, Field_Value, Query, SDV state, clinical review state, freeze/lock state, clinical Electronic_Signature, Clinical_Attachment, or clinical export, THEN THE API_Layer SHALL reject the command, SHALL return a rejection response indicating the target is EDC-owned, and SHALL change no module's authoritative state.
5. IF a PV command attempts to create or mutate a CTMS-owned operational record, THEN THE API_Layer SHALL reject the command, SHALL return a rejection response indicating the target is CTMS-owned, and SHALL change no module's authoritative state.
6. WHEN EDC clinical adverse-event data is exposed to PV, THE Coordination_Service SHALL deliver only an approved, authorized Safety_Operational_Projection containing solely the fields designated for PV release together with its source identifier, rule version, correlation identifier, and processing outcome, and SHALL not deliver unapproved clinical fields.
7. IF a requested projection across module boundaries is not approved or not authorized, THEN THE Coordination_Service SHALL deliver no projection content and SHALL record the denied projection request.
8. WHEN PV safety progress or reporting data is exposed to EDC or CTMS, THE Coordination_Service SHALL deliver only an approved read-only projection and SHALL not change EDC clinical or CTMS operational authoritative state.
9. THE Unified_Clinical_Platform SHALL use shared Auth_Service, Permission_Service, Audit_Service, Notification_Service, file-storage primitives, export-job infrastructure, observability, environment/configuration, API conventions, optional AI controls, and Coordination_Service without transferring EDC clinical or CTMS operational authority to PV.
10. IF the EDC_System or CTMS_Module is disabled, empty, or does not respond within 30 seconds of a coordination request, THEN THE PV_Safety_Module SHALL continue authentication, safety case capture, safety assessment, safety audit, safety export, and regulatory reporting using only PV-owned state and referenced canonical identity, and SHALL return no cross-module-dependent safety result as authoritative.

### Requirement 24: Performance

**User Story:** As a safety team member, I want responsive performance at scale, so that large safety databases remain usable.

#### Acceptance Criteria

1. WHEN a common PV read operation is requested under a load of 100 concurrent Users against a database containing up to 100,000 Safety_Cases and 500,000 Adverse_Event_Records, THE API_Layer SHALL return a successful response within 1 second for at least 95 percent of requests.
2. WHEN a PV list endpoint is requested, THE API_Layer SHALL return a paginated result with no more than 1,000 items per page.
3. WHEN a safety export or batch reconciliation processes at least 100,000 records, THE PV_Safety_Module SHALL accept the request within 5 seconds and process it as an asynchronous job with a Queued, Running, Completed, or Failed status.
4. THE PV_Safety_Module SHALL support at least 100 concurrent authenticated Users while maintaining the common-read performance criterion.

### Requirement 25: Reliability and Observability

**User Story:** As an operator, I want health checks, structured logs, and monitoring for PV, so that I can detect and diagnose production issues.

#### Acceptance Criteria

1. WHEN the liveness endpoint is requested, THE API_Layer SHALL return a health status of Healthy or Unhealthy within 1 second and SHALL report Unhealthy only when the service process cannot accept a request.
2. WHEN the readiness endpoint is requested, THE API_Layer SHALL return a readiness status of Ready or Not Ready within 1 second, where Not Ready indicates that a required configured dependency is unavailable.
3. WHEN a PV request is processed, THE PV_Safety_Module SHALL emit one structured log entry containing the request identifier, UTC timestamp, operation outcome, and duration in milliseconds.
4. WHEN the metrics endpoint is requested, THE API_Layer SHALL return current values for PV API latency, error rate, worker job failures, export failures, and overdue regulatory reports covering at least the preceding 5 minutes, and SHALL update these metrics at least once every 60 seconds.

## Safety Correctness Properties

The following properties preserve the PV safety invariants and SHALL map to automated unit, integration, security, or property-based tests. Tests SHALL use deterministic repositories and fakes for internal logic and SHALL not require EDC, CTMS, or external services to verify PV safety authority.

### Property 1: Safety identity and reference integrity

For any valid Study, Site, Subject_Reference, and Safety_Case sequence, canonical Study/Site identity remains stable, each Safety_Case references exactly one canonical Subject_Reference without duplicating EDC clinical identity, and each Adverse_Event_Record belongs to exactly one Safety_Case.

**Validates:** Requirements 3, 10, and 23.

### Property 2: Safety lifecycle transition validity

For any generated Safety_Case, Case_Version, Regulatory_Report, and notification status sequence, PV services accept only configured transitions, preserve required history, and reject invalid transitions without partial mutation.

**Validates:** Requirements 4, 8, and 14.

### Property 3: Safety data validation and preservation

For any assessment, coding, or narrative payload, submission validates required inputs; a failed validation preserves prior values; submitted changes require a Reason_For_Change; and Closed cases reject safety modifications.

**Validates:** Requirements 5, 6, 7, and 18.

### Property 4: Safety audit atomicity and immutability

For any PV Safety_Data mutation, the safety data change and its Audit_Event commit or roll back together, the event contains actor, timestamp, entity, action, and applicable old/new values and reason, and completed Audit_Events cannot be updated or deleted.

**Validates:** Requirements 11, 16, 18, and 20.

### Property 5: Safety authorization scope

For any User, PV Permission, Study, Site, and PV object, the operation succeeds exactly when the shared Authorization_Scope contains the required permission and target scope; otherwise no safety, audit, attachment, export, or projection state changes.

**Validates:** Requirements 1, 2, 11, 12, 16, 19, and 23.

### Property 6: Safety and cross-module content separation

For any PV safety export, safety dashboard/report, Safety_Attachment, notification, audit search, or reconciliation, the result contains only authorized PV safety content and approved read-only projections; EDC clinical and CTMS operational content remain owned by their modules and cannot be written through PV operations.

**Validates:** Requirements 10, 11, 12, 13, 15, and 23.

### Property 7: Regulatory clock correctness

For any Regulatory_Report with an Awareness_Date and a configured reporting-timeline, the computed Regulatory_Clock due date equals the Awareness_Date plus the configured whole calendar days, and overdue is true exactly when the current UTC date is later than the due date and the report is not Submitted.

**Validates:** Requirements 8 and 13.

### Property 8: ICSR round-trip serialization

For every reportable Safety_Case that produces a valid E2B_Message, parsing the produced message then producing a message yields an equivalent E2B_Message, while a structurally invalid message produces a descriptive parse error.

**Validates:** Requirements 9 and 16.

## Traceability Summary

- Requirements 1–2 define shared authentication reuse and PV authorization scope enforcement.
- Requirements 3–7 define PV safety case intake, lifecycle/versioning, assessments, medical/drug coding, and narratives as the safety system of record.
- Requirements 8–9 define regulatory reporting, expedited timelines, and ICSR/E2B message handling.
- Requirement 10 defines EDC adverse-event reconciliation through read-only projections without mutating EDC clinical records.
- Requirements 11–15 define PV audit trail, safety export, safety dashboards/reports, safety notifications, and safety attachments; shared infrastructure and other-module content remain separately owned.
- Requirements 16–20 define shared API, persistence, architecture, frontend, compliance, and environment controls with PV safety scope.
- Requirements 21–25 define PV delivery phases, optional AI controls, unified-platform ownership/coordination boundaries, performance, and observability.
- Safety Correctness Properties 1–8 provide the verification mapping for PV identity, lifecycle, data integrity, auditability, authorization, content separation, regulatory clocks, and ICSR serialization.
- The EDC requirements document remains authoritative for EDC clinical behavior and the CTMS requirements document for CTMS operational behavior. This document remains authoritative for PV safety behavior identified in the ownership rules and glossary.
