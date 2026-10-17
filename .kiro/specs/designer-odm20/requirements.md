# Designer ODM 2.0 JSON Requirements

1. Designer JSON and persisted definitions remain authoritative; ODM 2.0 JSON is an interchange representation for design metadata only.
2. The system shall validate ODM profile structure, OID syntax and uniqueness, references, and extension namespaces without writing data.
3. The system shall export draft or published designs deterministically, including one master schedule of assessment.
4. The system shall import atomically into a new or empty draft and shall reject published or populated targets.
5. Imported OIDs shall be preserved. Native definitions shall receive persisted OIDs derived from immutable UUIDs; renames shall not change OIDs.
6. The supported profile is `urn:aurinara:odm:profile:designer-metadata:1`; the only executable extension namespace is `urn:aurinara:odm:extension:1`.
7. Unsupported namespaces, dangling references, alternate matrices, matrix actions, arbitrary function source, or unresolved executable definitions shall fail validation rather than be discarded.
8. Rules shall be versioned declarative data with qualified field scope, conditions, typed actions, and execution metadata. Derivations shall use a bounded safe expression tree.
9. Imported rules marked for retesting shall block publication until resolved.
10. Import/export actions shall be study-scoped, permission checked, audited with a document hash, and shall not log document payloads.
11. Medical coding configuration and role-scoped CRF access shall round-trip in the declared Aurinara extension without creating a second clinical-data owner.
12. Subject phase definitions, ordered visit membership, and phase transitions shall round-trip in the declared Aurinara extension with stable OIDs. Imports shall reject dangling visits or phases, duplicate identities, self-transitions, visits on arm phases, and visits that reference common study events. Complete phases may contain ordered visits. An absent phase extension shall retain the platform default phase flow; an explicit phase extension may replace only an untouched default scaffold in an otherwise empty draft.
