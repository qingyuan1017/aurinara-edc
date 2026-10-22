# Implementation Plan: Designer / EDC Refactor

## Overview

This plan reorganizes the existing combined EDC capability into a new `designer`
domain subpackage and a slimmed operational `edc` subpackage, connected by a
read-only `Design_Consumption_Contract`. It is a **refactor**, not a greenfield
build: existing SQLAlchemy models, services, repositories, schemas, and routes
move or stay per the design's MOVE/STAY/NEW ownership mapping, stored values are
never altered, and all changes are **additive** at the schema layer.

The sequencing is chosen so operational flows never break at any intermediate
step: the `designer` package and its read port are created and wired **before**
the `edc` aggregate is slimmed; `design_version_id` binding columns are added
**nullable and backfilled before** not-null is enforced. Each task builds on the
prior one and ends by wiring new code into `app/main.py` or into the consuming
EDC services, leaving no orphaned code.

Implementation language is **Python** (FastAPI + SQLAlchemy 2.0 `Mapped`/
`mapped_column`), matching the existing backend and the concrete code in the
design document. Migrations use **Alembic** (`backend/alembic.ini`); property
tests use **Hypothesis** (already present) run through **pytest**, minimum 100
iterations each, tagged `# Feature: designer-edc-refactor, Property {n}: {text}`.

Conventions preserved everywhere: UUID primary keys, soft-delete via
`deleted_at`, timezone-aware timestamps, domain-isolated router aggregates,
server-side default-deny authorization via the shared `permission_service`.

## Tasks

- [x] 1. Snapshot & migration guards (Phase 0)
  - [x] 1.1 Build the pre-migration snapshot module
    - Create `app/services/designer/migration/snapshot_service.py` that records
      per-record-set counts and value checksums for the design-time sets
      (studies, study_versions, visit_definitions, form_definitions,
      form_sections, field_definitions, codelists, codelist_items, edit_checks)
      and operational sets (subjects, visit_instances, form_instances,
      form_records, field values)
    - Expose a stable serializable snapshot structure to feed Phase 5 verification
    - _Requirements: 11.1, 11.2, 11.5_
  - [x] 1.2 Write unit tests for snapshot counts and checksums
    - Assert counts and value checksums are stable and order-independent per set
    - _Requirements: 11.5_

- [x] 2. Create the Designer package scaffolding and read port surface (Phase 1 start)
  - [x] 2.1 Create empty designer subpackages across all layers
    - Add `app/models/designer/`, `app/services/designer/`,
      `app/repositories/designer/`, `app/schemas/designer/`, and
      `app/api/routes/designer/` each with `__init__.py`
    - Add `app/services/designer/migration/__init__.py`
    - _Requirements: 1.1, 11.1_
  - [x] 2.2 Define read-only published-design view schemas
    - In `app/schemas/designer/views.py` define frozen/read-only view models
      (`PublishedDesignView`, `FormDefinitionView`, `FieldDefinitionView`,
      `VisitDefinitionView`, `CycleDefinitionView`, `ArmDefinitionView`,
      `EditCheckRuleView`, `CodelistView`, `SubjectPhaseDefinitionView`,
      `ScheduleOfAssessmentView`, `CrfAccessDefinitionView`,
      `RawDataVariableSettingView`, `CodingSettingView`) exposing no mutation path
    - _Requirements: 2.6_

- [x] 3. Move Design_Version lifecycle into designer
  - [x] 3.1 Reassign study-version model/repository/schemas to designer
    - Move the design-time version metadata aspects of `study` model and
      `study_version_repository` into `app/models/designer/` and
      `app/repositories/designer/study_version_repository.py`; keep `Study`
      identity canonical/shared (no competing identity)
    - Reuse existing `StudyVersion` fields (`version_number`, `status`
      draft/published, `amendment_reason`, `amended_from_version_id`,
      `published_at`, `published_by`) as `Design_Version`
    - _Requirements: 1.1, 1.5, 2.1, 2.2, 11.1_
  - [x] 3.2 Move study_version_service into designer and implement lifecycle rules
    - Move to `app/services/designer/study_version_service.py`: create draft,
      validate, publish (transition draft→published recording actor/timestamp),
      amend (reason 1–4000 chars creates exactly one new draft), reject invalid
      publish/amend leaving the version unchanged, retain prior published versions
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.9, 2.10, 2.11_
  - [x] 3.3 Write property test for amendment
    - **Property 5: Amendment creates one draft and retains history**
    - **Validates: Requirements 2.9, 2.11**
  - [x] 3.4 Write property test for published-design immutability
    - **Property 3: Published-design immutability**
    - **Validates: Requirements 2.4**
  - [x] 3.5 Write edge-case + example tests for publish/amend
    - Publish valid draft records actor/timestamp (R2.1, R2.2); amendment-reason
      bounds at 0, 1, 4000, 4001 chars; publish-validation success/failure
    - _Requirements: 2.1, 2.2, 2.3, 2.10_

- [x] 4. Move CRF form metadata into designer
  - [x] 4.1 Reassign form metadata model/schemas/service to designer
    - Move `FormDefinition`, `FormSection`, `FieldDefinition` (and their schemas)
      into `app/models/designer/form_metadata.py` and
      `app/schemas/designer/form_metadata.py`; move `form_metadata_service` and
      `form_templates` into `app/services/designer/`; keep FK to `study_versions`
    - _Requirements: 4.1, 4.2, 11.1_
  - [x] 4.2 Implement visit definition authoring in designer
    - Move `VisitDefinition` into `app/models/designer/visit.py` and the
      definition-authoring parts of `visit_service` into
      `app/services/designer/visit_definition_service.py`; persist name (1–100),
      number (1–9999), target day (0–99999), window bounds (0–99999, lower ≤
      upper); reject lower > upper with window-identifying error
    - _Requirements: 4.2, 4.3, 4.4_
  - [x] 4.3 Write property test for visit-window validity
    - **Property 9: Designer definition persistence round-trip** (visit defs
      subset — valid/invalid windows embedded in strategy)
    - **Validates: Requirements 4.1, 4.2, 4.4, 4.6, 4.7, 4.8**
  - [x] 4.4 Write edge-case tests for visit-window ordering
    - Window ordering at equality and inversion; invalid-window rejection (R4.3)
    - _Requirements: 4.2, 4.3_

- [x] 5. Move edit-check rule design into designer
  - [x] 5.1 Reassign edit-check model/repository/service/examples to designer
    - Move `edit_check` model, `edit_check_repository`, `edit_check_service`,
      `edit_check_examples` into `app/{models,repositories,services}/designer/`;
      store rules declaratively (no in-process user-code execution); FK to `study_versions`
    - Validate rules against the declarative schema before persistence; reject
      schema violations without persisting
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 11.1_
  - [x] 5.4 Add governed custom Python function versions
    - Separate author/approve/execute permissions, maker-checker lifecycle, immutable source hashes, remote sandbox-only execution, validated command output, and payload-free audit metadata
    - _Requirements: 5.7_
  - [x] 5.2 Implement design-time rule testing with no operational side effects
    - In the designer edit-check service, evaluate a provided test case returning
      pass/fail without creating any Operational_Record
    - _Requirements: 5.3_
  - [x] 5.3 Write property test for rule testing side-effect freedom
    - **Property 10: Rule testing produces no operational side effects**
    - **Validates: Requirements 5.3, 5.5**

- [x] 6. Move codelist design into designer
  - [x] 6.1 Split codelists out of form metadata into designer
    - Move `Codelist`, `CodelistItem` into `app/models/designer/codelist.py` and
      create `app/services/designer/codelist_service.py`; persist name (1–100,
      unique within draft design) and 1–1000 items; reject duplicate names and
      publication referencing a missing codelist; FK to `study_versions`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 11.1_
  - [x] 6.2 Write property test for name uniqueness within a draft design
    - **Property 7: Name uniqueness within a draft design** (codelists + phases)
    - **Validates: Requirements 3.1, 3.2, 6.1, 6.2**
  - [x] 6.3 Write edge-case tests for codelist bounds
    - Codelist item counts at 1 and 1000; duplicate-name collisions; missing
      codelist reference on publish (R6.3)
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 7. Add NEW designer tables, models, and services
  - [x] 7.1 Add subject phase definition model and service
    - Create `app/models/designer/subject_phase_definition.py`
      (`design_version_id` FK, name 1–100 unique-in-version, display_order 1–999)
      and `app/services/designer/subject_phase_service.py` with uniqueness
      rejection returning the duplicate name
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 7.1.1 Seed and require the standard subject phase flow
    - Seed new draft designs with the standard subject lifecycle phases and transitions.
    - Block publication when no active subject phase or no registered starting phase is configured.
    - _Requirements: 3.14, 3.15_
  - [x] 7.1.2 Author transitions and edit phases directly from the flow canvas
    - Create transitions by dragging between phase handles; remove the separate add-transition form.
    - Select a phase node to edit its name, type, and applicable visit membership.
    - Color-code phase nodes by type with a visible legend and expose a reliable selected-link delete action.
    - _Requirements: 3.16, 3.17_
  - [x] 7.2 Add cycle and arm definition models and services
    - Create `cycle_definitions` (FK `study_versions`, membership to
      `visit_definitions`) and `arm_definitions` (FK `study_versions`) models and
      `cycle_service`, `arm_service` in designer
    - _Requirements: 4.4, 4.5_
  - [x] 7.3 Add schedule-of-assessment model and service
    - Create `schedule_of_assessment` model (FK `study_versions`, mapping forms/
      procedures to visit and cycle definitions) and
      `schedule_of_assessment_service`
    - _Requirements: 4.1_
  - [x] 7.4 Add CRF access, raw-data variable, and coding setting models and services
    - Create `crf_access_definitions` (per-role read/write per form/field),
      `raw_data_variable_settings` (name/type/attributes per captured item), and
      `coding_settings` (dictionary ref + rule per coded item) models each FK to
      `study_versions`, plus `crf_access_service`, `raw_data_variable_service`,
      `coding_setting_service`
    - _Requirements: 4.6, 4.7, 4.8_
  - [x] 7.5 Write property test for Designer-child single-version binding
    - **Property 8: Designer child binds to exactly one design version**
    - **Validates: Requirements 3.3, 5.4, 6.4**
  - [x] 7.6 Write property test for Designer definition round-trip
    - **Property 9: Designer definition persistence round-trip**
    - **Validates: Requirements 4.1, 4.2, 4.4, 4.6, 4.7, 4.8**
  - [x] 7.7 Write example test for arm definition persistence
    - Persist and read back an arm definition (R4.5)
    - _Requirements: 4.5_

- [x] 8. Implement the Design_Consumption_Contract read port
  - [x] 8.1 Implement DesignConsumptionService (published-only, read-only)
    - Create `app/services/designer/design_consumption_service.py` exposing
      `get_published_design`, `get_latest_published_design`, `list_forms`,
      `get_form_fields`, `list_visit_definitions`, `list_cycle_definitions`,
      `list_arm_definitions`, `list_edit_check_rules`, `list_codelists`,
      `list_subject_phase_definitions`, `get_schedule_of_assessment`,
      `list_crf_access_definitions`, `list_raw_data_variable_settings`,
      `list_coding_settings`, `permits_unscheduled_visits`
    - Reject any draft `design_version_id` (not-found/validation); return frozen
      view objects only (never ORM entities)
    - _Requirements: 2.5, 2.6, 7.5_
  - [x] 8.2 Write property test for one-directional, published-only consumption
    - **Property 2: One-directional, published-only consumption**
    - **Validates: Requirements 2.5, 2.6**

- [x] 9. Build and mount the designer_router (Phase 1 complete)
  - [x] 9.1 Create designer resource routers
    - Move design-authoring route handlers (study version create/publish/amend,
      forms/fields definition authoring, edit-check authoring/testing) into
      `app/api/routes/designer/` and add routers for codelists, subject phases,
      SoA, cycles, arms, CRF access, raw-data variables, coding settings
    - _Requirements: 2.1, 4.1, 4.5, 4.6, 4.7, 4.8, 5.1, 5.3, 6.1_
  - [x] 9.2 Aggregate designer_router and mount under /designer in main.py
    - Build `app/api/routes/designer/__init__.py` aggregate and
      `app.include_router(designer_router, prefix=f"{api_v1_prefix}/designer")`,
      mounted after PV and before EDC; preserve CTMS/PV mounting unchanged
    - _Requirements: 1.1, 2.1_

- [~] 10. Checkpoint — designer package live, edc still intact
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Slim the EDC package to operational concerns (Phase 2)
  - [x] 11.1 Remove design-authoring routers from the edc aggregate
    - In `app/api/routes/edc/__init__.py` drop `forms`, `fields`, `edit_checks`
      and the design-authoring parts of `studies`; keep operational routers
      (subjects, visits instances, form_data, records, queries, sdv, reviews,
      locks, signatures, dashboards, exports, operational study-info reads) with
      no added prefix for backward compatibility
    - _Requirements: 11.4, 8.1_
  - [x] 11.2 Repoint EDC services to the consumption contract
    - Update `data_capture_service`, `form_instance_service`,
      `repeating_record_service`, `subject_service`, operational `visit_service`,
      `query_service`, `sdv_service`, `review_service`, `lock_service`,
      `signature_service`, operational `study_service`, `dashboard_service` to
      read all design-dependent config through `DesignConsumptionService` only;
      remove any direct imports of designer write services/repositories
    - _Requirements: 1.3, 2.6, 8.14, 11.4_
  - [x] 11.3 Write property test for module-ownership invariant
    - **Property 1: Module-ownership invariant**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
  - [x] 11.4 Write integration test for consumption read-path
    - Verify design-dependent study-info reads route through
      `DesignConsumptionService` and never touch designer write paths (R8.14)
    - _Requirements: 8.14_

- [x] 12. Additive design_version_id binding columns (Phase 3)
  - [x] 12.1 Add nullable binding columns via Alembic
    - Alembic migration adding nullable `design_version_id` to operational tables
      lacking one (subjects, visit_instances, form_instances, form_records, field
      values, queries, sdv, reviews, locks, signatures); additive only, no renames
    - _Requirements: 11.2_
  - [x] 12.2 Backfill then enforce not-null in a follow-up migration
    - Backfill `design_version_id` from the subject's bound version or the study's
      current published version, then a separate migration enforces not-null;
      stored values of existing columns unchanged
    - _Requirements: 11.2, 2.7, 7.3_
  - [x] 12.3 Write property test for subject single published-design binding
    - **Property 4: Single published-design binding at subject start**
    - **Validates: Requirements 2.7, 7.3**

- [x] 13. Implement the EDC Data Entry Flow state machine
  - [x] 13.1 Implement the sequential flow with step-ordering and gating
    - In `app/services/edc/` implement the state machine: scope-gated site
      selection (via `permission_service.filter_sites`), subject select/create
      binding to exactly one Published_Design, scheduled/unscheduled visit
      selection gated by `permits_unscheduled_visits`, design-driven form/field
      selection persisting values as Operational_Records; reject out-of-order
      advance retaining current step; reject subject add when no Published_Design
      leaving data unchanged; reject out-of-scope site
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 2.7, 2.8_
  - [x] 13.2 Write property test for data-entry step-ordering invariant
    - **Property 6: Data-entry step-ordering invariant**
    - **Validates: Requirements 7.1, 7.2, 7.4, 7.6, 7.7, 7.8**

- [~] 14. Checkpoint — operational EDC runs against bound published designs
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Study Info Area including Version Upgrade rebinding
  - [x] 15.1 Wire Study_Info_Area sub-areas as EDC operational services/routers
    - Group operational services/routers for Study Information, CRF Version
      management, Metrics, Alerts, Subject, SDV, SDR, Lab, External Data Source,
      Adjudication (where enabled), SAEs, and Conversion/Data Validation/System
      Integration/eDiary/eCOA/Workflow/Site Payment/Translation/IRT; read all
      design-dependent config through `DesignConsumptionService`
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14_
  - [x] 15.2 Implement transactional Version Upgrade rebind
    - Rebind affected Operational_Records to a newer `design_version_id` in a
      single transaction recording the upgrade in the shared audit service; on
      failure leave records on the prior version, audit the failed attempt, and
      return an error
    - _Requirements: 8.3, 8.15_
  - [x] 15.3 Write property test for atomic/complete version-upgrade rebind
    - **Property 11: Version upgrade rebind is atomic and complete**
    - **Validates: Requirements 8.3, 8.15**

- [x] 16. Report Area with server-side scope filtering
  - [x] 16.1 Wire Report_Area read-only services/routers
    - Group read-only reporting services/routers for Data Summary, CRF Status,
      Query Report, Enrollment Status, eCOA/eDiary Report, On-Demand/KRI/SDV-SDR
      Workload/Data Analysis/Comment/Source Document Tracker, and End of Study;
      scope-filter every report server-side via `permission_service` (in-scope
      only, empty set when none in scope, not-authorized on unauthorized access);
      output through the shared export service
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10_
  - [x] 16.2 Write property test for report scope-filtering invariant
    - **Property 12: Report scope-filtering invariant**
    - **Validates: Requirements 9.8, 9.9**

- [x] 17. Access control and separation of duties
  - [x] 17.1 Add module-scoped roles/permissions and enforce default-deny
    - Add `Designer_Role` and `Operational_Role` permission codes to the shared
      `permission_service`; enforce designer permissions only for Designer_Roles
      and operational permissions only for Operational_Roles; evaluate
      authorization server-side with default-deny; enforce each role only within
      its own module scope for single- and both-role users
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_
  - [x] 17.2 Enforce identity-conflict rejection on Study/Site
    - Reject attempts to mint a competing Study/Site identity with a conflict
      error identifying the conflicting identity
    - _Requirements: 1.6_
  - [x] 17.3 Write property test for module-scoped separation of duties
    - **Property 13: Module-scoped separation of duties with default-deny**
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6**

- [x] 18. Audit wiring for changes, denials, and reassignments
  - [x] 18.1 Record one immutable audit event per auditable action
    - Ensure every Designer_Definition/Operational_Record change, every
      authorization denial, and every migration reassignment records exactly one
      immutable audit event (owning/attempted module scope, actor, entity,
      action, timestamp) through the shared audit service
    - _Requirements: 1.7, 10.7, 11.7_
  - [x] 18.2 Write property test for exactly-one immutable audit event
    - **Property 14: Exactly one immutable audit event per auditable action**
    - **Validates: Requirements 1.7, 10.7, 11.7**

- [x] 19. Migration reassignment, verification, and abort (Phases 4–5)
  - [x] 19.1 Implement reassignment audit and audit-history preservation (Phase 4)
    - In the migration module, record reassignments as immutable audit events and
      preserve all existing audit history with no physical removal
    - _Requirements: 11.7, 11.8_
  - [x] 19.2 Implement post-migration verification and abort-on-data-loss (Phases 5–6)
    - Compare post-migration counts and per-record stored values against the
      Phase 0 snapshot for every reassigned set; on any data-loss risk abort,
      leave pre-migration records unchanged, and report the failing record set;
      preserve every pre-migration published version as a consumable
      Published_Design
    - _Requirements: 11.3, 11.5, 11.6_
  - [x] 19.3 Write property test for migration count/value preservation
    - **Property 15: Migration preserves record count and values**
    - **Validates: Requirements 11.1, 11.2, 11.5**
  - [x] 19.4 Write property test for post-migration design consumability
    - **Property 16: Published designs remain consumable after migration**
    - **Validates: Requirements 11.3**
  - [x] 19.5 Write property test for audit-history preservation
    - **Property 17: Audit history is preserved across migration**
    - **Validates: Requirements 11.8**

- [x] 20. Integration and smoke tests
  - [x] 20.1 Write router-mounting integration test
    - Verify `designer_router` mounts under `/designer`, the slimmed `edc_router`
      preserves existing operational paths with no added prefix, and CTMS/PV
      mounting is unchanged
    - _Requirements: 1.1, 11.4_
  - [x] 20.2 Write operational-continuity post-migration integration test
    - Run representative data-entry, query, SDV, review, and lock flows end-to-end
      against a bound Published_Design after a simulated migration; assert success
    - _Requirements: 11.4_
  - [x] 20.3 Write surface-area smoke tests
    - Assert each Study_Info_Area sub-area (R8.1–R8.2, R8.4–R8.13) and Report_Area
      report (R9.1–R9.7) endpoint is mounted and responds
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [x] 21. Final verification
  - [x] 21.1 Run the backend build, test suite, and migration verification
    - Run `pytest` (including all Hypothesis property tests at ≥100 iterations)
      and execute the Alembic migrations end-to-end; run the migration count +
      value-equality verification and confirm abort-on-data-loss behavior; fix
      any failures before completion
    - _Requirements: 11.4, 11.5, 11.6_

- [~] 22. Final checkpoint — ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 23. Expand Designer form and visit authoring
  - [x] 23.1 Add form type/access/domain/label, section output/help/access, and complete item metadata/control types
  - [x] 23.2 Add explicit visit/folder/cycle kinds, folder hierarchy, visit category/subtype, and editable cycle membership
  - [x] 23.3 Restrict SoA columns to real visits and add migration, API, UI, and focused tests
  - _Requirements: 4.10–4.15_

- [x] 24. Render control-specific form widgets
  - [x] 24.1 Preview each configured field control in the Form Builder
  - [x] 24.2 Render the corresponding interactive control in operational data entry
  - [x] 24.3 Preserve scalar, boolean, and multi-value field data across save and reload
  - _Requirements: 4.20_

- [x] 25. Generate form-owned raw-data variable schemas
  - [x] 25.1 Add the required fixed variables to every form dataset definition
  - [x] 25.2 Generate configurable codelist and numeric companion variables
  - [x] 25.3 Generate configurable date year, month, and day variables
  - [x] 25.4 Add dataset previews and per-field suffix configuration to Designer
  - _Requirements: 4.21_

- [x] 26. Make each cycle an owning folder for its own visits
  - [x] 26.1 Add cycle-owned `cycle_visit` definitions and nested authoring UI
  - [x] 26.2 Enforce same-version, single-cycle ownership for every cycle visit
  - [x] 26.3 Include standalone and cycle visits in the SoA while excluding containers
  - _Requirements: 4.13–4.15_

- [x] 27. Add typed operational subject phases to Study Data
  - [x] 27.1 Add registered, screen-failure, common, complete, and arm phase types
  - [x] 27.2 Enforce phase-specific visit membership rules in Designer
  - [x] 27.3 Persist and audit each subject's current phase and selected arm
  - [x] 27.4 Show cumulative visits from the audited phase path; make arm phases assignment-only and activate the phase/arm-SoA visit intersection on subsequent phases
  - [x] 27.5 Prompt for a configured arm when entering an arm phase and complete the subject when entering a complete phase
  - [x] 27.6 Restrict Study Data phase actions and API mutations to outgoing published phase-flow transitions
  - [x] 27.7 Show Site names and phase-consistent subject status in the Subjects list

- [x] 32. Move treatment scheduling from arms into the Schedule of Assessment
  - [x] 32.1 Keep arm authoring limited to name, order, and description
  - [x] 32.1.1 Add audited draft-only arm removal with arm-scoped SoA cleanup
  - [x] 32.2 Add common and per-arm SoA scopes with scoped replacement semantics
  - [x] 32.2.1 Copy the saved common SoA into an unsaved editable arm schedule
  - [x] 32.3 Require one saved SoA for every configured arm before publication
  - [x] 32.4 Derive arm-phase visit/form visibility from the selected arm's SoA
  - _Requirements: 3.7, 4.1, 4.5, 4.23–4.25_
  - _Requirements: 3.4–3.11_

- [x] 28. Preserve visit hierarchy in schedules and arm selection
  - [x] 28.1 Sort Schedule of Assessment columns at each hierarchy level and keep cycle visits at their cycle's top-level position
  - [x] 28.2 Add folder/cycle group selection with independently selectable descendants to the arm editor
  - [x] 28.3 Persist only real visit leaves in arm membership and reject container membership during authoring and publication
  - [x] 28.4 Add draft arm editing and expand legacy folder/cycle membership to real descendant visits for remediation
  - _Requirements: 4.22–4.23_

- [x] 29. Delete unused draft edit checks
  - [x] 29.1 Add an authorized, draft-only, audited delete service and endpoint
  - [x] 29.2 Reject deletion when persisted validation results exist
  - [x] 29.3 Add a confirmed delete action to the Edit Check Builder
  - _Requirements: 5.6_

- [x] 30. View retained published designs
  - [x] 30.1 Add a shared Designer version selector that defaults to the current draft and persists while navigating between Designer modules
  - [x] 30.2 Link published rows in Version History to the normal Designer Forms module with the selected version
  - [x] 30.3 Read retained forms, visits, schedule, phases, arms, rules, codelists, and design settings through their standard Designer modules without mutation controls
  - _Requirements: 2.11–2.12_

- [x] 31. Preserve Study Data navigation context
  - [x] 31.1 Resolve subject and form breadcrumb labels from clinical record names instead of internal IDs
  - [x] 31.2 Persist the selected study and site across internal navigation and reloads, while clearing them on sign-out
  - [x] 31.3 Replace clinical study, subject, and form document-reload links with router navigation
  - _Requirements: 3.12–3.13_

- [x] 32. Add versioned SDR selection configuration
  - Add draft-only Designer SDR settings for all, deterministic percentage, and targeted-field strategies; validate targeted fields against the owning design and expose read/upsert contracts under the Designer API.
  - Materialize selections only from published designs in the EDC operational boundary and preserve selection identity across later reads.
  - _Requirements: 8.8, 10.1–10.6_

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP;
  core implementation tasks are never optional.
- Each task references the specific requirement sub-criteria and/or the design
  Property it implements for full traceability.
- Sequencing guarantees operational continuity: the designer package and read
  port exist before the edc aggregate is slimmed (tasks 2–10 before 11), and
  binding columns are added nullable and backfilled before not-null is enforced
  (12.1 before 12.2).
- One property-based test per design Property (1–17), each tagged
  `# Feature: designer-edc-refactor, Property {number}: {property_text}` and run
  with Hypothesis at a minimum of 100 iterations.
- Boundary/error criteria (R1.6, R2.3, R2.8, R2.10, R4.3, R4.9, R5.2, R6.3,
  R7.9, R7.10, R9.9, R9.10, R11.6) are exercised as edge cases inside the
  relevant property strategies and edge-case tests.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "4.1", "5.1", "6.1", "7.1"] },
    {
      "id": 3,
      "tasks": [
        "3.3",
        "3.4",
        "3.5",
        "4.2",
        "5.2",
        "6.2",
        "6.3",
        "7.2",
        "7.3",
        "7.4"
      ]
    },
    { "id": 4, "tasks": ["4.3", "4.4", "5.3", "7.5", "7.6", "7.7", "8.1"] },
    { "id": 5, "tasks": ["8.2", "9.1"] },
    { "id": 6, "tasks": ["9.2"] },
    { "id": 7, "tasks": ["11.1", "11.2"] },
    { "id": 8, "tasks": ["11.3", "11.4", "12.1"] },
    { "id": 9, "tasks": ["12.2"] },
    { "id": 10, "tasks": ["12.3", "13.1"] },
    { "id": 11, "tasks": ["13.2", "15.1", "16.1", "17.1"] },
    { "id": 12, "tasks": ["15.2", "16.2", "17.2", "17.3", "18.1"] },
    { "id": 13, "tasks": ["15.3", "18.2", "19.1"] },
    { "id": 14, "tasks": ["19.2"] },
    { "id": 15, "tasks": ["19.3", "19.4", "19.5", "20.1", "20.2", "20.3"] },
    { "id": 16, "tasks": ["21.1"] }
  ]
}
```

- [x] 24. Expand form layout settings and subject-phase visit membership
  - Rename CDASH domain/label contracts to domain/label.
  - Add grid row/column and header-details metadata, identifier display flags,
    CRF/ODM item identifiers, and right-side form/field settings drawers.
  - Add validated, ordered subject-phase-to-visit associations and expose them
    through authoring and published-design contracts.
