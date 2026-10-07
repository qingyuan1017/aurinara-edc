# PV shell wiring — verification evidence

Scope: wire the already-built PV/Safety module into the app shell navigation and
module switcher. Implementation landed in commit `a9b1552`
(`feat: wire PV/Safety module into app shell navigation and switcher`), parent `ee3daa6`.

This document records the lint / test / build evidence requested by the review
(`pv-shell-review.json`, finding: "Missing verification evidence"). The code diff
was reviewed as correct and faithful to the CTMS pattern; the only blocking item was
the absence of recorded verification output.

All commands run from `e:\Work\EDETEK\Python\aurinara-edc\frontend`.

## 1. `npm run lint` — PASS

```
> eslint .
✖ 11 problems (0 errors, 11 warnings)
```

- Exit code: 0.
- 0 errors. The 11 warnings are all the pre-existing
  `react-hooks/incompatible-library` ("Compilation Skipped") warnings on
  `useReactTable` / React Hook Form `watch()` call sites across the codebase
  (AppTheme.test, admin pages, ctms/pv forms, exports, sites, studies, subjects).
  None originate from the files changed by this task, and lint was already emitting
  them before the change.

## 2. `npm run build` — PASS

```
> tsc -b && vite build
vite v8.1.0 building client environment for production...
✓ 481 modules transformed.
dist/index.html                     0.47 kB │ gzip:   0.29 kB
dist/assets/index-*.css            48.22 kB │ gzip:   9.21 kB
dist/assets/index-*.js          1,024.14 kB │ gzip: 285.08 kB
✓ built in 499ms
```

- Exit code: 0.
- `tsc -b` type-checks the whole project. Its success confirms the new
  `resolveNavigationModel(ctmsState, pvState, permissions, scope)` signature and the
  new `pvSections` / `showPV` props compile across every production caller and every
  test caller (no stale arity survives). The remaining output is the standard
  "chunk larger than 500 kB" advisory, not an error.

## 3. `npm run test` (`vitest run`)

### 3a. PV-scoped suites (the files this task owns / affects) — PASS

```
npx vitest run \
  src/__tests__/AppSidebar.test.tsx \
  src/__tests__/NavigationModel.test.ts \
  src/__tests__/PVRoutes.test.ts \
  src/__tests__/PVWorkspace.test.tsx \
  src/__tests__/PVCapabilities.test.ts \
  src/__tests__/PVPresentation.test.tsx \
  src/__tests__/PVForms.test.tsx

 Test Files  7 passed (7)
      Tests  58 passed (58)
```

- Exit code: 0.
- Covers the shell wiring tests (`AppSidebar`, `NavigationModel`, `PVRoutes`) and the
  full PV feature suite (`PVWorkspace`, `PVCapabilities`, `PVPresentation`, `PVForms`).
  All green — the PV test suite the delegation asked to keep green is green.

### 3b. Full suite — 19 failures, all pre-existing and unrelated to this change

```
 Test Files  9 failed | 54 passed (63)
      Tests  19 failed | 310 passed (329)
```

The 9 failing files are:

| File | Failure cause (all from uncommitted WIP, not this task) |
| --- | --- |
| `CTMSPersonaWorkspace.test.tsx` (9) | `@tanstack/react-router` mock missing `useLocation` / `useSearch` exports |
| `CTMSServerAuthority.property.test.tsx` (1) | duplicate "Current filtered row" element |
| `CTMSOperationalMutationContract.test.tsx` (1) | multiple elements with role `status` |
| `DashboardListPages.test.tsx` (1) | "Failed to load studies" / expected text not found |
| `CTMSExportLifecycle.property.test.tsx` (1) | test timed out (5000 ms) |
| `CTMSOwnershipFreshness.property.test.tsx` (1) | test timed out (5000 ms) |
| `CTMSResilience.test.tsx` (2) | expected "CTMS" nav text not found |
| `CTMSClinicalAuthority.property.test.tsx` (1) | test timed out (5000 ms) |
| `SourceMigrationChecks.test.ts` (2) | import-rule violation on `DataTableShell.tsx` EmptyState import |

Why these are not caused by this task:

- None of the 9 files call `resolveNavigationModel`, import `navigation-model`,
  `module-context`, `AppSidebar`, or any file in commit `a9b1552`
  (verified by grep: no matches in `CTMSPersonaWorkspace.test.tsx` or
  `CTMSResilience.test.tsx`).
- Every failing file (or the source it exercises) is part of the unrelated,
  uncommitted working-tree WIP visible in `git status` at the time of verification:
  modified `CTMS*` tests, `CTMS` feature source (`api.ts`, `state.ts`, forms,
  components), `components/patterns/MutationFeedback.tsx`, `api/mutator.ts`,
  `lib/api.ts`, `DataTableShell.tsx`, etc. These changes belong to other work in
  progress and are outside the scope of the PV shell task.
- The 7 PV-scoped suites (which exercise exactly the files this task changed) all
  pass, demonstrating the PV shell wiring itself is correct and green.

Conclusion: lint and build pass clean; all tests covering this task's change pass.
The full-suite failures are confined to unrelated CTMS/dashboard/source-migration
WIP in the working tree and are not introduced by the PV shell commit.
