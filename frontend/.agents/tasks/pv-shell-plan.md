# Implementation Plan — Wire PV/Safety module into app shell navigation and module switcher

Frontend-only change. Mirror the existing CTMS integration pattern exactly; PV is purely additive. Run all commands from `e:\Work\EDETEK\Python\aurinara-edc\frontend`.

## Context discovered during exploration

- The EDC/CTMS "module switcher" is the `<select aria-label="Select module">` inside `moduleSwitcher()` in `AppSidebar.tsx` (NOT in `AppHeader.tsx`). It currently has two `<option>`s: `edc` and `ctms` (ctms `disabled={!showCTMS}`). Adding PV means adding a third option gated by `showPV`.
- `activeModule` is derived in `AppShell.tsx` from the pathname: `pathname.includes('/ctms') ? 'ctms' : 'edc'`. All PV routes contain the segment `/pv` (`/pv`, `/studies/$id/pv/*`, `/sites/$id/pv/dashboard`); no path contains both `/ctms` and `/pv`, so precedence is unambiguous.
- `resolveNavigationModel(state, permissions, scope)` currently takes only the CTMS capability state. Four callers exist and all must be updated when the signature gains a PV-state parameter:
  1. `src/components/layout/AppShell.tsx` (production)
  2. `src/__tests__/AppSidebar.test.tsx` (helper `renderResolvedSidebar` + two inline calls)
  3. `src/__tests__/NavigationModel.test.ts` (five calls)
  4. `src/__tests__/PVRoutes.test.ts` (one call, inside the PV-disabled baseline assertion)
- The PV barrel `src/features/pv/index.ts` already re-exports `resolvePVNavigation`, types `PVNavigationItem`/`PVNavigationSection`, `usePVCapabilityState`, and type `PVCapabilityState`. No new re-exports are needed.
- `PERMISSIONS.PV_SAFETY_CASE_READ` already exists (`'safety_case.read'`).
- `resolvePVNavigation(state, permissions, scope)` already returns `[]` when PV is not `ready` or the user lacks `safety_case.read`. The adapter must preserve this end to end.

## Design decisions (made here, grounded in the CTMS pattern)

- **Signature change shape:** add the PV capability state as the SECOND positional parameter: `resolveNavigationModel(ctmsState, pvState, permissions, scope)`. Rationale: it keeps the two capability states adjacent and reads naturally, and every caller is being updated anyway. (Alternative considered: appending PV state last to minimize churn — rejected because grouping the two states is clearer and all callers are touched regardless.)
- **`activeModule` derivation precedence:** check PV first, then CTMS, else EDC: `pathname.includes('/pv') ? 'pv' : pathname.includes('/ctms') ? 'ctms' : 'edc'`. Rationale: mirrors the existing single-expression derivation; segments are mutually exclusive so order is safe.
- **View-model adapter:** add `PVNavigationViewItem`/`PVNavigationViewSection` mirroring the CTMS ones (attach `search: preserveCurrentSearch` and `activeOptions: { exact: false }`). Rationale: PV links must retain current search and match descendant routes exactly like CTMS.
- **`showPV` gate:** mirror `showCTMS` precisely — `pvState.status === 'ready' && usePermission(PERMISSIONS.PV_SAFETY_CASE_READ)`. Rationale: identical capability+permission affordance gating; server stays authoritative.
- **Module navigation target:** switching to PV navigates to `/pv` (the registered PV root), mirroring CTMS → `/ctms` and EDC → `/`.

---

- [x] 1. Extend `AppModule` to include `'pv'` and update the localStorage guard and store doc comments.
     In `module-context.ts`: change `export type AppModule = 'edc' | 'ctms'` to `'edc' | 'ctms' | 'pv'`; in `readStoredModule` accept `'pv'` (`value === 'edc' || value === 'ctms' || value === 'pv'`); update the `/** The two top-level product modules... */` and `ModuleState`/`useModuleStore` doc comments to say EDC, CTMS, or PV (no longer "two").
     Files: `src/lib/module-context.ts`
     Verify: `npm run build` — TypeScript compiles with the widened union.

- [x] 2. Add PV view-model types and populate `pvSections` in the navigation model.
     In `navigation-model.ts`: import `resolvePVNavigation` and types `PVNavigationItem`, `PVNavigationSection`, `PVCapabilityState` from `@/features/pv`. Add `PVNavigationViewItem extends PVNavigationItem { readonly search: SearchPreserver; readonly activeOptions: { readonly exact: false } }` and `PVNavigationViewSection extends Omit<PVNavigationSection, 'items'> { readonly items: readonly PVNavigationViewItem[] }`, mirroring the CTMS view types. Add `readonly pvSections: readonly PVNavigationViewSection[]` to `NavigationModel`. Change the signature to `resolveNavigationModel(state: CTMSCapabilityState, pvState: PVCapabilityState, permissions, scope = {})`; build `pvSections` by calling `resolvePVNavigation(pvState, permissions, scope)` and mapping each section/item to attach `search: preserveCurrentSearch` and `activeOptions: { exact: false as const }` (same `.map` shape as `ctmsSections`); return it alongside `edcSections` and `ctmsSections`. Keep `createNavigationModel = resolveNavigationModel`.
     Files: `src/lib/navigation-model.ts`
     Verify: `npm run build` (compiles) and `npm run test` for the model (`npx vitest run src/__tests__/NavigationModel.test.ts`) after step 6 updates its calls — expect pass.

- [x] 3. Add `pvSections`/`showPV` to `AppSidebar` and render a gated PV section group plus the PV switcher option.
     In `AppSidebar.tsx`: import `PVNavigationViewSection` from `@/lib/navigation-model`. Add `pvSections: readonly PVNavigationViewSection[]` and `showPV: boolean` to `AppSidebarProps`. Add a `PVSection` renderer mirroring `CTMSSection` (use `sectionHeadingId('pv', section.id)`, render `item.activeOptions`). Widen the `NavigationLink` `item` prop union to also accept `PVNavigationViewSection['items'][number]`. In `NavigationSections`, add `pvSections`/`showPV` params and render a PV block mirroring the CTMS block, gated by `showPV && (activeModule === undefined || activeModule === 'pv')`, with heading text `PV` and `aria-label="PV navigation"`. Pass `pvSections`/`showPV` into both `NavigationSections` call sites (desktop + mobile). Update `moduleLabel` to resolve `'pv' → 'PV'` (e.g. `activeModule === 'ctms' ? 'CTMS' : activeModule === 'pv' ? 'PV' : 'EDC'`). In `moduleSwitcher`, add `<option value="pv" disabled={!showPV}>PV{!showPV ? ' (Unavailable)' : ''}</option>` after the CTMS option. Add `pvSections`/`showPV` to the `AppSidebar` destructured props.
     Files: `src/components/layout/AppSidebar.tsx`
     Verify: `npm run build` (compiles) and `npm run test` for the sidebar (`npx vitest run src/__tests__/AppSidebar.test.tsx`) after step 5 updates the test helper — expect pass.

- [x] 4. Wire PV into `AppShell`: resolve PV capability state, compute `showPV`, pass new props, extend `activeModule` and `handleModuleChange`.
     In `AppShell.tsx`: import `usePVCapabilityState` from `@/features/pv`; add `const pvState = usePVCapabilityState()` and `const canReadPV = usePermission(PERMISSIONS.PV_SAFETY_CASE_READ)`. Change the `resolveNavigationModel(ctmsState, ...)` call to `resolveNavigationModel(ctmsState, pvState, user?.permissions ?? [], { studyId, siteId })`. Change `activeModule` derivation to `pathname.includes('/pv') ? 'pv' : pathname.includes('/ctms') ? 'ctms' : 'edc'`. Add `const showPV = pvState.status === 'ready' && canReadPV`. In `handleModuleChange`, navigate to `/pv` when `module === 'pv'` (extend the ternary: `module === 'ctms' ? '/ctms' : module === 'pv' ? '/pv' : '/'`). Pass `pvSections={navigationModel.pvSections}` and `showPV={showPV}` to `<AppSidebar>`.
     Files: `src/components/layout/AppShell.tsx`
     Verify: `npm run build` — compiles with the new props and signature.

- [x] 5. Update `AppSidebar.test.tsx` for the new signature and props, and add a focused PV test.
     In `src/__tests__/AppSidebar.test.tsx`: import `normalizePVCapabilities`, `unavailablePVCapabilities`, `PV_DISABLED_MANIFEST` from `@/features/pv`. Add PV capability states: a `pvReadyState = normalizePVCapabilities({ module: 'PV', enabled: true, phase: 1, capabilities: [...] })` whose capabilities include the codes PV nav needs for phase 1 (`safety_case_intake`, `safety_dashboards`, `safety_exports`, `shared_audit` — confirm against `PV_ACTION_ROUTE_MAP` so study `dashboard`/`cases`/`exports`/`audit` and `siteDashboard` resolve), a `pvDisabledState = normalizePVCapabilities(PV_DISABLED_MANIFEST)`, and a `pvUnavailableState = unavailablePVCapabilities(new Error('unavailable'))`. Update `renderResolvedSidebar` to accept a PV state (default `pvDisabledState`), call `resolveNavigationModel(state, pvState, permissions, scope)`, and pass `pvSections={model.pvSections}` and `showPV={pvState.status === 'ready' && permissions.includes(PERMISSIONS.PV_SAFETY_CASE_READ)}` to `<AppSidebar>`. Update the two inline `resolveNavigationModel(readyState, allPermissions, ...)` calls (in "reports module changes from the selector" and "uses compact collapse semantics...") to pass a PV state as the 2nd arg and add `pvSections`/`showPV` props to those inline `<AppSidebar>` renders. Add a focused test: with `pvReadyState`, `allPermissions`, and `activeModule='pv'`, assert the `PV` section heading / `PV navigation` region renders with expected PV links (e.g. a `Dashboard`/`Cases` PV link) and that the module `<select>` has a non-disabled `PV` option; and a test that with `pvDisabledState`/`pvUnavailableState` the EDC and CTMS navigation is unchanged (EDC `Dashboard` link present, no `PV navigation` region, PV option disabled).
     Files: `src/__tests__/AppSidebar.test.tsx`
     Verify: `npx vitest run src/__tests__/AppSidebar.test.tsx` — all tests pass.

- [x] 6. Update `NavigationModel.test.ts` and `PVRoutes.test.ts` for the new signature.
     In `src/__tests__/NavigationModel.test.ts`: import `normalizePVCapabilities`/`PV_DISABLED_MANIFEST` from `@/features/pv`; define a PV state constant; update all five `resolveNavigationModel(...)` calls to pass the PV state as the 2nd arg. Optionally add one assertion that `model.pvSections` is `[]` when PV is disabled (keeps EDC/CTMS assertions intact). In `src/__tests__/PVRoutes.test.ts`: update the `resolveNavigationModel(baselineCTMSState, allPermissions, {...})` calls to the new signature — compute `baseline` with a disabled PV state, and inside the `for (const pvState of pvStates)` loop call `resolveNavigationModel(baselineCTMSState, pvState, allPermissions, {...})` and assert it equals `baseline` (this now genuinely proves PV disabled/empty/unavailable never alters EDC/CTMS nav).
     Files: `src/__tests__/NavigationModel.test.ts`, `src/__tests__/PVRoutes.test.ts`
     Verify: `npx vitest run src/__tests__/NavigationModel.test.ts src/__tests__/PVRoutes.test.ts` — all tests pass.

- [x] 7. Full verification of the complete change.
     No new edits unless prior steps surfaced issues. Run the project's documented checks from `frontend/`.
     Files: none
     Verify: `npm run lint` (clean), `npm run test` (all suites pass), `npm run build` (tsc + vite build succeed).
     Result (recorded in `pv-shell-verification.md`):
     - `npm run lint` → PASS (exit 0; 0 errors, 11 pre-existing `react-hooks/incompatible-library` warnings).
     - `npm run build` → PASS (exit 0; `tsc -b` clean + Vite production bundle, 481 modules).
     - `npm run test` → PV-scoped suites (AppSidebar, NavigationModel, PVRoutes, PVWorkspace, PVCapabilities, PVPresentation, PVForms) all PASS: 7 files / 58 tests. Full suite shows 19 failures across 9 files (CTMS\*, DashboardListPages, SourceMigrationChecks) that are pre-existing failures from unrelated uncommitted working-tree WIP — none import this task's changed modules, and the PV change does not introduce them.

## Notes / assumptions

- `features/pv/index.ts` already re-exports every symbol needed (`resolvePVNavigation`, `PVNavigationItem`, `PVNavigationSection`, `PVCapabilityState`, `usePVCapabilityState`, `normalizePVCapabilities`, `unavailablePVCapabilities`, `PV_DISABLED_MANIFEST`). Add a re-export only if a referenced type turns out to be missing; do not touch other PV internals.
- Do NOT modify `src/lib/router.ts`, backend code, or PV feature internals (`api.ts`, `WorkspacePage.tsx`, forms, components).
- PV must be purely additive: when `pvState.status` is `disabled`/`unavailable` or the user lacks `safety_case.read`, `resolvePVNavigation` returns `[]`, `showPV` is false, the PV option is disabled, and EDC/CTMS navigation is unchanged. Preserve this end to end (verified by the updated `PVRoutes.test.ts` baseline-equality assertion).
- Verification commands (from `e:\Work\EDETEK\Python\aurinara-edc\frontend`): `npm run lint`, `npm run test`, `npm run build`.
