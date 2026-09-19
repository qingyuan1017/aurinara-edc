# shadcn-admin redesign validation

Task 7.4 validation was run from `/Users/jason/Aurinara/edc/frontend` on Node `v26.1.0` and npm `11.13.0`. No application behavior or API contract was changed during validation, and no commit was created.

## Command results

| Command | Exit | Result |
| --- | ---: | --- |
| `npm run lint` | 1 | Failed: 8 errors and 9 warnings. |
| `npm run build` | 2 | Failed during `tsc -b`; TypeScript reported 93 errors, so Vite bundling did not run. |
| `npm run test` | 1 | Failed: 53 test files ran; 45 passed and 8 failed. There were 258 tests; 242 passed and 16 failed. |
| `npm run e2e -- e2e/shadcn-admin-redesign.spec.ts` | 0 | Passed: all 4 one-shot Playwright tests passed in 6.2 seconds. |
| `npx vitest run src/__tests__/SourceMigrationChecks.test.ts src/__tests__/UIPrimitives.test.tsx src/__tests__/PagePatterns.test.tsx src/__tests__/AppSidebar.test.tsx src/__tests__/AppHeader.test.tsx src/__tests__/AppTheme.test.tsx src/__tests__/NavigationModel.test.ts src/__tests__/RouteContext.test.ts src/__tests__/FinalEDCRegression.test.tsx` | 0 | Passed: 9 files and 56 tests. |

The Playwright suite used the existing Vite dev server at `127.0.0.1:5173`; the Playwright invocation itself was one-shot and used no watch mode.

## Relevant failures and follow-up

The failures are not hidden or suppressed by this task. They must be resolved in a follow-up before a release can claim a green implementation matrix.

- Lint errors include `src/__tests__/CTMSPhase1Qualification.test.tsx:87` (two unnecessary escapes), `src/features/ctms/components/CTMSMutationFeedback.tsx:39,43` (Fast Refresh component-export rule), `src/features/ctms/components/CTMSMutationFeedback.tsx:61` (state update in effect), and `src/features/ctms/filters.ts:78` (unused `_page`, `_pageSize`, and `_cursor`). The remaining lint findings are React Compiler compatibility warnings.
- The build's 93 type errors span added/changed CTMS coverage and implementation. Representative failures are `src/__tests__/CTMSApiProperty.test.ts:118`, `src/__tests__/CTMSCachePolicy.property.test.ts:32`, `src/__tests__/CTMSClinicalAuthority.property.test.tsx:64-89`, `src/__tests__/CTMSOperationalBoundary.property.test.ts:89`, `src/__tests__/SourceMigrationChecks.test.ts:1-2,12,17,158,162`, `src/features/ctms/api.ts:1162`, `src/features/ctms/forms/OperationalWorkflowForms.tsx:154,173,175`, `src/features/ctms/hooks/useCTMSMutations.ts:72,85,215,232-234`, `src/features/ctms/offline.ts:69`, and `src/features/ctms/state.ts:77`.
- The full Vitest failures are in `CTMSClinicalAuthority.property.test.tsx`, `CTMSDashboardReports.test.tsx`, `CTMSExportLifecycle.property.test.tsx`, `CTMSOperationalMutationContract.test.tsx`, `CTMSOwnershipFreshness.property.test.tsx`, `CTMSPersonaWorkspace.test.tsx`, `CTMSRemediationProperty.test.tsx`, and `CTMSServerAuthority.property.test.tsx`. Observed causes include a 5-second property-test timeout, changed CTMS workspace/table expectations, duplicate rendered responsive content, and assertion/type-contract mismatches. The redesign-specific regression subset passes independently as recorded above.

## Product assumptions and implementation evidence

- **Breakpoint:** The implementation uses Tailwind's `md` breakpoint (the repository default is 768 CSS pixels): `AppSidebar` uses `hidden md:flex` and `md:hidden` for the mobile Sheet, while `AppHeader` uses `md:hidden` for the menu trigger. The browser fixture covers 375px mobile and 1280px desktop, and `AppSidebar.test.tsx` asserts the responsive classes. The exact product-approved breakpoint and an explicit 768px browser case remain unresolved; this is currently the documented implementation default from the design.
- **Density:** No separate persisted density mode or `--density` token is implemented. The compact dashboard treatment is represented by the collapsed sidebar width (`--sidebar-width-collapsed`), content spacing tokens, and shared compact control classes. A product-approved density scale/default remains unresolved and must not be inferred from these presentation defaults.
- **Font:** `frontend/src/index.css` defines the repository-owned fallback stack `--font-sans: ui-sans-serif, system-ui, sans-serif` and applies it to `body`; no external font dependency or network font is assumed.
- **Theme persistence:** `frontend/src/lib/theme.ts` uses the namespaced `edc-theme-mode` storage key, safely handles unavailable storage, supports `light`, `dark`, and `system`, and applies `data-theme`/`data-theme-mode` before the existing router tree. `theme.test.ts`, `AppTheme.test.tsx`, and the browser fixture cover persisted/system behavior and route-independent theme switching.
- **Global search:** `GlobalSearch.tsx` is an explicitly disabled, non-submitting affordance with accessible name `Global search unavailable`; it does not invent an API or mutate query state. `AppHeader.test.tsx` and the browser suite assert this behavior.
- **Notifications:** `AppHeader.tsx` links to the existing `/notifications` route with `search={(previous) => previous}` and an accessible `Notifications` label. `AppHeader.test.tsx`, route-context tests, and the browser shell fixture cover the affordance and search preservation.
- **Compatibility exceptions:** Search-preserving route helper aliases remain in `lib/route-context.ts`; navigation-model aliasing remains presentation-only; `StatusTransitionForm.tsx` retains `CTMSStatusTransitionDialog` and `StatusTransitionForm` compatibility aliases; `WorkspacePage.tsx` retains legacy capability-name aliases. Source migration checks and the redesign regression subset pass, but the full build remains blocked by unrelated/broader CTMS type errors.

## Release assessment

The task-specific shadcn-admin source checks and browser suite pass. The required release matrix does **not** pass because lint, build, and the complete Vitest suite fail. Release is blocked pending the listed lint/type/test follow-ups and product confirmation of the exact breakpoint and density decisions.
