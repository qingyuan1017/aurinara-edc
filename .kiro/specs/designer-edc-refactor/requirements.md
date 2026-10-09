# Requirements Document

## Introduction

This document specifies the requirements for refactoring the existing combined EDC capability of the Unified_Clinical_Platform into two clearly separated first-party modules: the Designer_Module and the EDC_Module.

Today, design-time concerns (study metadata, visit and form definitions, edit-check rules, codelists) and operational concerns (clinical data capture, study operations, and reporting) are bundled together in one EDC capability. This refactor formalizes the existing but informal boundary between study design and study operations into two cohesive modules with an explicit contract between them.

The Designer_Module owns all design-time definitions and metadata: subject phase definitions, CRF design (schedule of assessment, visits and cycles, arms, CRF access, raw data variable settings, coding settings), rule design (edit checks and validation rules), and codelists. The Designer_Module produces versioned, published study designs.

The EDC_Module owns all operational and clinical work: sequential data entry, study information and operational configuration, and the full reporting surface. The EDC_Module consumes published designs produced by the Designer_Module and never authors design-time definitions directly.

The contract between the two modules is a published, versioned Study_Design. Designs flow one direction: Designer_Module authors and publishes; EDC_Module consumes read-only and binds operational and clinical records to a specific published version. The refactor is a reorganization: existing functionality from the current combined EDC capability is redistributed across the two modules without data loss, and existing versioned designs remain consumable by the EDC_Module. Access control enforces separation of duties between designer roles and operational roles.

This document builds on the terminology and ownership rules already established in the Unified_Clinical_Platform (EDC and CTMS) and refines the EDC side into Designer and operational EDC concerns. It does not change CTMS ownership.

## Glossary

- **Unified_Clinical_Platform**: The single first-party application boundary containing the Designer_Module, the EDC_Module, the CTMS_Module, and shared platform services.
- **Designer_Module**: The design-time module that owns subject phase definitions, CRF design, rule design, and codelists, and that produces published, versioned study designs. Also referred to as the "Designer".
- **EDC_Module**: The operational module that owns clinical data capture, study operational information, and reporting, and that consumes published study designs. Also referred to as the operational "EDC".
- **CTMS_Module**: The co-equal operational module whose ownership is unchanged by this refactor.
- **Study_Design**: The versioned bundle of all design-time definitions authored in the Designer_Module (subject phase definitions, schedule of assessment, visits/cycles, arms, CRF access, raw data variable settings, coding settings, edit-check rules, and codelists) for one Study. This is the published artifact that forms the contract between the Designer_Module and the EDC_Module. It corresponds to the existing study-version metadata boundary.
- **Design_Version**: A single immutable published revision of a Study_Design. Equivalent to the existing published Study_Version metadata set.
- **Designer_Definition**: Any individual design-time artifact owned by the Designer_Module (for example, a subject phase definition, visit definition, form definition, field definition, arm, edit-check rule, or codelist).
- **Published_Design**: A Design_Version whose status is published and therefore immutable and available for consumption by the EDC_Module.
- **Draft_Design**: A Design_Version whose status is draft and therefore editable only within the Designer_Module and not consumable by the EDC_Module.
- **Design_Consumption_Contract**: The read-only interface through which the EDC_Module reads a Published_Design; the EDC_Module reads definitions through this contract and never writes to Designer_Definitions.
- **Operational_Record**: Any EDC_Module-owned record created during study conduct (subject records, visit instances, form instances, form records, field values, queries, SDV, SDR, lab data, reports, and operational configuration).
- **Subject_Phase_Definition**: A Designer_Module artifact describing a phase of subject participation (for example screening, treatment, follow-up) used by downstream operational subject phase tracking.
- **Schedule_Of_Assessment**: A Designer_Module artifact mapping forms and procedures to visits and cycles across a study.
- **Visit_Definition**: A Designer_Module artifact defining a scheduled visit, including visit windows and cycle membership.
- **Cycle_Definition**: A Designer_Module artifact defining a repeating group of visits.
- **Arm_Definition**: A Designer_Module artifact defining a study arm or treatment group.
- **CRF_Access_Definition**: A Designer_Module artifact defining, at design time, which roles may read or write which forms and fields.
- **Raw_Data_Variable_Setting**: A Designer_Module artifact defining export/raw-data variable names, types, and attributes for captured items.
- **Coding_Setting**: A Designer_Module artifact defining medical coding configuration (for example dictionaries and auto-coding rules) for coded items.
- **Edit_Check_Rule**: A Designer_Module declarative validation rule evaluated by the EDC_Module at data entry.
- **Codelist**: A Designer_Module controlled vocabulary of codelist items referenced by field definitions.
- **Data_Entry_Flow**: The EDC_Module sequential operational workflow: select site, select subject, select visit, select form, enter data.
- **Study_Info_Area**: The EDC_Module operational configuration and management surface, including study information, CRF version management, metrics, alerts, subject, SDV, SDR, lab, external data source, adjudication, SAE, conversion, data validation, system integration, eDiary, eCOA, workflow, site payment, translation, and IRT integration.
- **Report_Area**: The EDC_Module reporting surface, including data summary, CRF status, query report, enrollment status, eCOA/eDiary report, on-demand report, KRI/central monitoring, SDV/SDR workload, data analysis, end of study, comment report, and source document tracker.
- **Designer_Role**: A Role scoped to design-time permissions in the Designer_Module.
- **Operational_Role**: A Role scoped to operational permissions in the EDC_Module (for example data entry, monitoring, reporting).
- **Audit_Service**: The shared append-only service that records immutable audit events for both modules.
- **Migration_Process**: The one-time reorganization that redistributes existing combined EDC functionality and data into the Designer_Module and the EDC_Module without data loss.

## Module Boundary Rules

The Designer_Module is authoritative for all Designer_Definitions and for the Study_Design lifecycle (draft, publish, version, amend). The EDC_Module is authoritative for all Operational_Records produced during study conduct. The two modules share the canonical Study and Site identity, authentication, authorization, and audit, but neither module may author the other's records.

Designs flow one direction only. The Designer_Module publishes a Design_Version; the EDC_Module reads a Published_Design through the Design_Consumption_Contract and binds Operational_Records to a specific Design_Version. The EDC_Module never creates or mutates Designer_Definitions, and the Designer_Module never creates or mutates Operational_Records. This boundary corresponds to the existing separation between study metadata (studies, study versions, visit definitions, form definitions, form sections, field definitions, codelists, codelist items, edit checks) and clinical subject data (subjects, visit instances, form instances, form records, field values); the refactor formalizes that boundary into two modules.

## Requirements

### Requirement 1: Module Separation and Boundary

**User Story:** As a platform architect, I want design-time concerns and operational concerns separated into two modules, so that study design and study conduct have clear, independent ownership.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL expose the Designer_Module as the sole owner of all Designer_Definitions and the Study_Design lifecycle.
2. THE Unified_Clinical_Platform SHALL expose the EDC_Module as the sole owner of all Operational_Records.
3. IF the EDC_Module requests creation or modification of a Designer_Definition, THEN THE Unified_Clinical_Platform SHALL reject the request, SHALL NOT change any Designer_Definition, and SHALL return an error indication that the Designer_Definition is owned by the Designer_Module.
4. IF the Designer_Module requests creation or modification of an Operational_Record, THEN THE Unified_Clinical_Platform SHALL reject the request, SHALL NOT change any Operational_Record, and SHALL return an error indication that the Operational_Record is owned by the EDC_Module.
5. THE Designer_Module and THE EDC_Module SHALL share the canonical Study identity and the canonical Site identity without creating competing identities.
6. IF a module attempts to create a Study identity or a Site identity that competes with the canonical identity, THEN THE Unified_Clinical_Platform SHALL reject the attempt and SHALL return an error indication identifying the conflicting identity.
7. WHEN a Designer_Definition or an Operational_Record changes, THE Audit_Service SHALL record one immutable audit event identifying the owning module, the actor, the entity, the change, and the event timestamp.

### Requirement 2: Design Publication and Consumption Contract

**User Story:** As a study designer, I want to publish a versioned study design that the operational module consumes read-only, so that study conduct always runs against an immutable, approved design.

#### Acceptance Criteria

1. WHEN an authorized Designer_Role user publishes a Draft_Design that passes design validation, THE Designer_Module SHALL transition the Design_Version to Published_Design.
2. WHEN the Designer_Module transitions a Design_Version to Published_Design, THE Designer_Module SHALL record the publication actor and the publication timestamp.
3. IF an authorized Designer_Role user publishes a Draft_Design that fails design validation, THEN THE Designer_Module SHALL reject the publication, SHALL leave the Design_Version as a Draft_Design, and SHALL return an error indication identifying the failing validation.
4. WHILE a Design_Version is a Published_Design, THE Designer_Module SHALL reject every modification to that Design_Version and its child Designer_Definitions.
5. WHEN the EDC_Module reads design information through the Design_Consumption_Contract, THE Designer_Module SHALL return only Published_Design content and SHALL NOT return Draft_Design content.
6. THE EDC_Module SHALL read Designer_Definitions only through the Design_Consumption_Contract and SHALL treat all consumed definitions as read-only.
7. WHEN an authorized Operational_Role user starts study conduct for a Subject, THE EDC_Module SHALL bind the Subject to exactly one Published_Design identified by its Design_Version.
8. IF an authorized Operational_Role user starts study conduct for a Subject when no Published_Design exists, THEN THE EDC_Module SHALL reject the start and SHALL return an error indication that no Published_Design is available.
9. WHEN an authorized Designer_Role user amends a Published_Design with an amendment reason of 1 to 4,000 characters inclusive, THE Designer_Module SHALL create one new Draft_Design.
10. IF an authorized Designer_Role user amends a Published_Design with an amendment reason that is empty or exceeds 4,000 characters, THEN THE Designer_Module SHALL reject the amendment and SHALL NOT create a new Draft_Design.
11. THE Designer_Module SHALL retain all prior Published_Design versions for traceability.

### Requirement 3: Designer — Subject Phase Design

**User Story:** As a study designer, I want to design subject phase definitions, so that operational subject phase tracking has a controlled set of phases.

#### Acceptance Criteria

1. WHEN an authorized Designer_Role user creates a Subject_Phase_Definition within a Draft_Design with a phase name of 1 to 100 characters that is unique within the Draft_Design and a display order of 1 to 999, THE Designer_Module SHALL persist the Subject_Phase_Definition in that Draft_Design.
2. IF a requested Subject_Phase_Definition name is not unique within the Draft_Design, THEN THE Designer_Module SHALL reject the request, SHALL NOT persist the Subject_Phase_Definition, and SHALL return an error indication identifying the duplicate name.
3. THE Designer_Module SHALL associate each Subject_Phase_Definition with exactly one Design_Version.

### Requirement 4: Designer — CRF Design

**User Story:** As a study designer, I want to design the CRF structure, so that the operational module can present and capture data against an approved form and schedule structure.

#### Acceptance Criteria

1. WHEN an authorized Designer_Role user defines a Schedule_Of_Assessment within a Draft_Design, THE Designer_Module SHALL persist the mapping of forms and procedures to Visit_Definitions and Cycle_Definitions.
2. WHEN an authorized Designer_Role user defines a Visit_Definition within a Draft_Design with a visit name of 1 to 100 characters, a visit number of 1 to 9999, an integer target day of 0 to 99999, and integer lower and upper window bounds of 0 to 99999 where the lower bound is no greater than the upper bound, THE Designer_Module SHALL persist the Visit_Definition.
3. IF a requested Visit_Definition has a lower window bound greater than its upper window bound, THEN THE Designer_Module SHALL reject the request, SHALL NOT persist the Visit_Definition, and SHALL return an error indication identifying the invalid window.
4. WHEN an authorized Designer_Role user defines a Cycle_Definition within a Draft_Design, THE Designer_Module SHALL persist the Cycle_Definition and its member Visit_Definitions.
5. WHEN an authorized Designer_Role user defines an Arm_Definition within a Draft_Design, THE Designer_Module SHALL persist the Arm_Definition.
6. WHEN an authorized Designer_Role user defines a CRF_Access_Definition within a Draft_Design, THE Designer_Module SHALL persist the design-time read and write access of each Operational_Role to each form and field.
7. WHEN an authorized Designer_Role user defines a Raw_Data_Variable_Setting for a captured item within a Draft_Design, THE Designer_Module SHALL persist the raw-data variable name, type, and attributes.
8. WHEN an authorized Designer_Role user defines a Coding_Setting for a coded item within a Draft_Design, THE Designer_Module SHALL persist the coding dictionary reference and coding rule.
9. IF any CRF Designer_Definition fails design validation, THEN THE Designer_Module SHALL reject the publication of the containing Design_Version and SHALL return an error indication identifying the failing definition.

### Requirement 5: Designer — Rule Design

**User Story:** As a study designer, I want to design edit-check and validation rules, so that the operational module validates captured data consistently.

#### Acceptance Criteria

1. WHEN an authorized Designer_Role user creates an Edit_Check_Rule within a Draft_Design, THE Designer_Module SHALL validate the rule against the declarative rule schema before persistence.
2. IF an Edit_Check_Rule fails schema validation, THEN THE Designer_Module SHALL reject the rule, SHALL NOT persist the rule, and SHALL return an error indication identifying the schema violation.
3. WHEN an authorized Designer_Role user tests an Edit_Check_Rule against a provided test case within a Draft_Design, THE Designer_Module SHALL return the pass or fail evaluation result without creating any Operational_Record.
4. THE Designer_Module SHALL associate each Edit_Check_Rule with exactly one Design_Version.
5. THE Designer_Module SHALL store Edit_Check_Rules as declarative definitions that the EDC_Module evaluates without executing user-provided code.

### Requirement 6: Designer — Codelist Design

**User Story:** As a study designer, I want to manage codelists, so that captured fields use controlled vocabularies.

#### Acceptance Criteria

1. WHEN an authorized Designer_Role user creates a Codelist with a name of 1 to 100 characters that is unique within the Draft_Design and 1 to 1000 codelist items, THE Designer_Module SHALL persist the Codelist and its items.
2. IF a requested Codelist name is not unique within the Draft_Design, THEN THE Designer_Module SHALL reject the request, SHALL NOT persist the Codelist, and SHALL return an error indication identifying the duplicate name.
3. IF a field definition references a Codelist that does not exist in the Draft_Design, THEN THE Designer_Module SHALL reject publication of the containing Design_Version and SHALL return an error indication identifying the missing Codelist reference.
4. THE Designer_Module SHALL associate each Codelist with exactly one Design_Version.

### Requirement 7: EDC — Sequential Data Entry Flow

**User Story:** As a site data-entry user, I want a sequential data entry flow, so that I capture data against the correct site, subject, visit, and form.

#### Acceptance Criteria

1. WHEN an authorized Operational_Role user begins the Data_Entry_Flow, THE EDC_Module SHALL present for selection only the Sites within the user's authorization scope and SHALL require a Site selection before enabling subject selection.
2. WHEN a Site is selected, THE EDC_Module SHALL require selection of an existing Subject or creation of a new Subject before enabling visit selection.
3. WHEN an authorized Operational_Role user adds a new Subject during the Data_Entry_Flow, THE EDC_Module SHALL create the Subject bound to the selected Site and to exactly one Published_Design.
4. WHEN a Subject is selected, THE EDC_Module SHALL require selection of a scheduled visit or creation of an unscheduled visit before enabling form selection.
5. WHERE the bound Published_Design permits unscheduled visits, THE EDC_Module SHALL allow an authorized Operational_Role user to create an unscheduled visit instance.
6. WHEN a visit is selected, THE EDC_Module SHALL require selection of a form defined by the bound Published_Design before enabling data entry.
7. WHEN a form is selected, THE EDC_Module SHALL present the form fields from the bound Published_Design and SHALL persist entered field values as Operational_Records.
8. IF the user attempts to advance to a later step in the Data_Entry_Flow before completing the required prior step, THEN THE EDC_Module SHALL reject the advance, SHALL retain the current step, and SHALL return an error indication identifying the incomplete prior step.
9. IF no Published_Design exists for the selected Site when a new Subject is added, THEN THE EDC_Module SHALL reject the Subject creation, SHALL return an error indication that no Published_Design is available, and SHALL leave study data unchanged.
10. IF a user attempts to select a Site outside the user's authorization scope, THEN THE EDC_Module SHALL reject the selection and SHALL return an error indication that the Site is not authorized.

### Requirement 8: EDC — Study Info

**User Story:** As an operational study manager, I want a study information area, so that I can configure and manage operational aspects of a running study.

#### Acceptance Criteria

1. THE EDC_Module SHALL provide Study Information management, including Study Information, Status Configuration, and ID Configuration.
2. THE EDC_Module SHALL provide CRF Version management, including Version Upgrade, Version History, Edit Check Testing Case, and Access Control.
3. WHEN an authorized Operational_Role user upgrades a Subject or Site to a newer Published_Design through Version Upgrade, THE EDC_Module SHALL rebind the affected Operational_Records to the newer Design_Version and SHALL record the upgrade in the Audit_Service.
4. THE EDC_Module SHALL provide Metrics, including Study Summary and Subject Summary.
5. THE EDC_Module SHALL provide Alerts for AE, eDiary, CRF, Subject Phase, Query, Visit Window, Edit Check, Non-Compliance, and Payment.
6. THE EDC_Module SHALL provide Subject management, including Subject Phase, Subject Information, and Source Document.
7. THE EDC_Module SHALL provide SDV, including SDV Setting, SDV Workload, and SDV Result.
8. THE EDC_Module SHALL provide SDR, including SDR Setting, SDR Workload, and SDR Result.
9. THE EDC_Module SHALL provide Lab, including Lab Define, Site Normal Range, External Lab Data, Summary of Lab, Conversion Factor and Range Report, and Operational History.
10. THE EDC_Module SHALL provide External Data Source, including Data Import and Data Sync.
11. WHERE Adjudication is enabled for a Study, THE EDC_Module SHALL provide Adjudication.
12. THE EDC_Module SHALL provide SAEs, including SAE Form Define, Related Form, SAE Report Setting, SAE Alert, SAE Report, and SAE Audit.
13. THE EDC_Module SHALL provide Conversion, Data Validation, System Integration, eDiary, eCOA, Workflow, Site Payment, Translation, and IRT Integration.
14. THE EDC_Module SHALL read all design-dependent configuration in the Study_Info_Area from the bound Published_Design through the Design_Consumption_Contract.
15. IF a Version Upgrade fails before all affected Operational_Records are rebound, THEN THE EDC_Module SHALL leave the affected Operational_Records bound to their prior Design_Version, SHALL record the failed upgrade attempt in the Audit_Service, and SHALL return an error indication that the upgrade did not complete.

### Requirement 9: EDC — Reporting

**User Story:** As a study monitor, I want a reporting area, so that I can review study, subject, data, and quality status.

#### Acceptance Criteria

1. THE EDC_Module SHALL provide Data Summary reports, including Raw Data, CRF Data, Data Analysis, Item Data, Listings, Visit Data, Audit, and Log.
2. THE EDC_Module SHALL provide CRF Status reports, including Status Summary, Manually Disabled Status, Form Status Flow, Visit Status Details, Form Status Details, Record Status Details, Item Status Details, Subject Lab Normal Range, CRF Completion Status, Record Completion Status, Subject Form Links, and Subject Site Transfer.
3. THE EDC_Module SHALL provide Query Report, including Query Aging Report, Manual Query Details, System Query Details, All Query Report, Lab Query Report, and Exception Query Report.
4. THE EDC_Module SHALL provide Enrollment Status reports, including Subject Phase, Subject Enrollment, Enrollment Summary, and Subject Phase Report.
5. THE EDC_Module SHALL provide eCOA and eDiary Report, including Completion Rate Report, Data Quality Report, Site Performance Report, User Engagement Report, Non-Compliance Report, and Compliance Report.
6. THE EDC_Module SHALL provide On-Demand Report, KRI-Central Monitoring, SDV and SDR Workload, Data Analysis (Study Progress By Visit), Comment Report, and Source Document Tracker.
7. THE EDC_Module SHALL provide End of Study reports, including End of Study Overview and System Document.
8. WHEN an authorized Operational_Role user requests any Report_Area report, THE EDC_Module SHALL return only records within the user's authorization scope.
9. WHEN an authorized Operational_Role user requests a Report_Area report for which no records fall within the user's authorization scope, THE EDC_Module SHALL return an empty result set rather than records outside that scope.
10. IF a user requests a Report_Area report the user is not authorized to access, THEN THE EDC_Module SHALL reject the request and SHALL return an error indication that the report is not authorized.

### Requirement 10: Access Control and Separation of Duties

**User Story:** As a security officer, I want designer and operational responsibilities separated by role, so that study design and study conduct are controlled independently.

#### Acceptance Criteria

1. THE Unified_Clinical_Platform SHALL assign Designer_Module permissions only to Designer_Roles and EDC_Module operational permissions only to Operational_Roles.
2. IF a user without a Designer_Role attempts to create or modify a Designer_Definition, THEN THE Unified_Clinical_Platform SHALL deny the request, SHALL NOT change any Designer_Definition, and SHALL return an authorization-denied result to the caller identifying that the Designer_Role requirement was not met.
3. IF a user without an Operational_Role attempts to create or modify an Operational_Record, THEN THE Unified_Clinical_Platform SHALL deny the request, SHALL NOT change any Operational_Record, and SHALL return an authorization-denied result to the caller identifying that the Operational_Role requirement was not met.
4. WHEN the Unified_Clinical_Platform receives any request to create or modify a Designer_Definition or an Operational_Record, THE Unified_Clinical_Platform SHALL evaluate authorization server-side independently of any frontend permission check and SHALL deny the request by default when server-side authorization for the request cannot be confirmed.
5. WHERE a single user holds exactly one of a Designer_Role or an Operational_Role, THE Unified_Clinical_Platform SHALL grant that user access only to the module scoped by that role and SHALL deny that user all permissions scoped to the other module.
6. WHERE a single user holds both a Designer_Role and an Operational_Role, THE Unified_Clinical_Platform SHALL enforce each permission set only within its own module scope and SHALL NOT allow one role's permissions to authorize an action in the other module.
7. IF the Unified_Clinical_Platform denies a request to create or modify a Designer_Definition or an Operational_Record, THEN THE Audit_Service SHALL record one immutable audit event identifying the actor, the attempted module scope, the attempted action, and the denial.

### Requirement 11: Migration and Backward Compatibility

**User Story:** As a platform owner, I want the existing combined EDC functionality reorganized without data loss, so that running studies continue to operate after the refactor.

#### Acceptance Criteria

1. WHEN the Migration_Process runs, THE Unified_Clinical_Platform SHALL reassign existing study metadata records (studies, study versions, visit definitions, form definitions, form sections, field definitions, codelists, codelist items, edit checks) to the Designer_Module without altering their stored values.
2. WHEN the Migration_Process runs, THE Unified_Clinical_Platform SHALL reassign existing clinical subject data records (subjects, visit instances, form instances, form records, field values) and operational configuration to the EDC_Module without altering their stored values.
3. THE Migration_Process SHALL preserve every existing published study version as a Published_Design that remains consumable by the EDC_Module through the Design_Consumption_Contract.
4. WHEN the Migration_Process completes, THE EDC_Module SHALL keep every existing operational data-entry, query, SDV, review, and lock flow operational against its bound Published_Design.
5. WHEN the Migration_Process completes, THE Migration_Process SHALL verify that, for every reassigned record set, the post-migration record count equals the pre-migration record count and that each reassigned record's stored values equal its pre-migration values.
6. IF the Migration_Process cannot reassign a record without data loss, THEN THE Migration_Process SHALL abort the migration, SHALL leave the pre-migration records unchanged, and SHALL report an abort result to the operator identifying the record set that could not be reassigned.
7. WHEN the Migration_Process reassigns records, THE Audit_Service SHALL record the reassignment as immutable audit events.
8. THE Migration_Process SHALL preserve all existing audit history across both modules without physical removal.
