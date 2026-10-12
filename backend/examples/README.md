# Designer JSON import examples

These files can be uploaded with **Import JSON** from the Forms, Codelists,
Edit Checks, or Visits Designer pages. They target the current draft study
version and use the atomic bulk-import endpoint:

```text
POST /api/v1/designer/studies/{study_id}/bulk-import
```

Files:

- `designer-bulk-import-complete.json` creates related codelists, forms, edit
  checks, and visits together.
- `designer-forms.json` creates two forms without external codelist references.
- `designer-edit-checks.json` demonstrates comparison, boolean, list, and regex
  rules in the safe edit-check DSL.
- `designer-codelists.json` creates several controlled vocabularies.
- `designer-visits.json` demonstrates screening, scheduled, cycle, and
  unscheduled visit definitions.

Use `codelist_code` in an imported field to reference a codelist created in the
same file or an existing codelist in the target draft. Codes must be unique in
that draft. The whole request is transactional: if any definition is invalid or
the user lacks a required permission, none of the definitions are committed.

These are additive examples. Uploading the same file twice can produce duplicate
forms, edit checks, or visits, and duplicate codelist names/codes are rejected.
