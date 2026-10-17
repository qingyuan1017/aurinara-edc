# Designer ODM 2.0 JSON Design

The adapter separates database loading, typed ODM mapping, and JSON serialization. Pydantic models define the Aurinara profile and validate cross-references before any import writes occur. Import uses the request transaction so version creation and every child definition commit or roll back together.

Core mappings are StudyVersion→MetaDataVersion, VisitDefinition→StudyEvent, FormDefinition→Form, FormSection→ItemGroup, FieldDefinition→Item, Codelist→CodeList, MeasurementUnitDefinition→MeasurementUnit, EditCheck→Condition, DerivationDefinition→Method, and SoA entries→event FormRefs. Aurinara-only presentation, coding settings, CRF access, and executable rule metadata live under the declared extension namespace.

SubjectPhaseDefinition and SubjectPhaseTransition use stable persisted ODM OIDs and round-trip through `subjectPhases` and `subjectPhaseTransitions` in the metadata-version Aurinara extension. Phase visit membership references StudyEvent OIDs, so import creates phases only after visits have been persisted. Existing untouched default phases are treated as empty-draft scaffolding and may be replaced atomically; authored phase flows block import. Documents without the phase extension retain the default flow.

Existing operational ODM XML export remains independent and unchanged.
