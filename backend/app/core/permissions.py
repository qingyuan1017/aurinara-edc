"""Permission codes, role-capability map, and database seeding.

Satisfies Requirements:
  - 2.1: Authorization_Scope resolved as the union of permission codes of assigned roles.
  - 3.3: Roles carry system/study/site scope with associated permission codes.
  - 3.6: Sponsor Viewer role granted read-only permissions only.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Stable permission codes
# ---------------------------------------------------------------------------

PERMISSION_CODES: set[str] = {
    # User management
    "user.list",
    "user.create",
    "user.update",
    "user.deactivate",
    "user.assign",
    # Role management
    "role.list",
    "role.create",
    "role.update",
    # Study management
    "study.create",
    "study.configure",
    "study.read",
    # Version management
    "version.publish",
    # ---------------------------------------------------------------------
    # Designer_Module (design-time authoring) permission codes.
    #
    # These are the proper module-scoped codes for the designer routers that
    # previously reused the shared ``study.configure``/``study.read``
    # placeholders. They are only ever effective when granted through a
    # Designer_Role (see DESIGNER_PERMISSION_CODES / module classification
    # below). Codes are additive — existing operational codes are untouched.
    # ---------------------------------------------------------------------
    "designer.study_version.read",
    "designer.study_version.create",
    "designer.study_version.amend",
    "designer.version.publish",
    "designer.form.read",
    "designer.form.configure",
    "designer.field.configure",
    "designer.editcheck.configure",
    "designer.editcheck.test",
    "designer.codelist.read",
    "designer.codelist.configure",
    "designer.subject_phase.configure",
    "designer.soa.read",
    "designer.soa.configure",
    "designer.cycle.configure",
    "designer.visit.read",
    "designer.visit.configure",
    "designer.arm.configure",
    "designer.crf_access.configure",
    "designer.raw_data_variable.configure",
    "designer.coding_setting.configure",
    # Site management
    "site.manage",
    "site.read",
    # Subject management
    "subject.create",
    "subject.read",
    "subject.update",
    # Form management
    "form.configure",
    "form.read",
    "form.enter",
    "form.submit",
    # Query management
    "query.create",
    "query.respond",
    "query.close",
    "query.reopen",
    "query.cancel",
    # Edit check management
    "editcheck.configure",
    # SDV, review, lock
    "sdv.manage",
    "review.manage",
    "lock.manage",
    # Signature
    "signature.sign",
    # Audit and export
    "audit.read",
    "data.export",
    "file.upload",
    # CTMS operational access (shared EDC/CTMS authorization namespace)
    "ctms.operational_data_read",
    "ctms.operational_study_management",
    "ctms.operational_site_management",
    "ctms.monitoring_activity_management",
    "ctms.enrollment_management",
    "ctms.conflict_management",
    "ctms.coordination_replay",
    # PV/Safety access (shared authorization namespace; no EDC/CTMS authority)
    # Requirements 1.x, 2.x, 18.4. Phase 1 seeds (safety_case.enter/read/
    # lifecycle, safety_assessment.record, safety_audit.read) are also written
    # by migration 0038; the remaining PV codes are additive (migration 0039).
    "safety_case.enter",
    "safety_case.read",
    "safety_case.lifecycle",
    "safety_assessment.record",
    "safety_coding.assign",
    "safety_narrative.write",
    "safety_report.manage",
    "safety_reconciliation.run",
    "safety_export.create",
    "safety_audit.read",
}

# ---------------------------------------------------------------------------
# Role definitions: name -> scope + permission codes
# ---------------------------------------------------------------------------

CTMS_PERMISSION_CODES: frozenset[str] = frozenset(
    {
        "ctms.operational_data_read",
        "ctms.operational_study_management",
        "ctms.operational_site_management",
        "ctms.monitoring_activity_management",
        "ctms.enrollment_management",
        "ctms.conflict_management",
        "ctms.coordination_replay",
    }
)

# The complete PV/Safety permission namespace. PV roles are composed only from
# these codes so a PV role can never be granted an EDC clinical or CTMS
# operational mutation permission (Requirements 2.6, 18.4).
PV_PERMISSION_CODES: frozenset[str] = frozenset(
    {
        "safety_case.enter",
        "safety_case.read",
        "safety_case.lifecycle",
        "safety_assessment.record",
        "safety_coding.assign",
        "safety_narrative.write",
        "safety_report.manage",
        "safety_reconciliation.run",
        "safety_export.create",
        "safety_audit.read",
    }
)

# ---------------------------------------------------------------------------
# Module-scoped permission classification (Requirement 10)
# ---------------------------------------------------------------------------
#
# Every permission code belongs to one authorization *module*:
#   - "designer"    design-time authoring in the Designer_Module. Grantable
#                   and effective ONLY through a Designer_Role.
#   - "operational" study-conduct permissions in the EDC_Module. Grantable and
#                   effective ONLY through an Operational_Role.
#   - None          shared/platform codes (user/role admin, audit, CTMS, PV)
#                   that are exempt from Designer/EDC module isolation. These
#                   keep their existing behavior and are NOT constrained by the
#                   module gate added in this refactor.
#
# The classification is the single source of truth for enforcing R10.1-R10.6:
# PermissionService consults it to decide whether a resolved grant is permitted
# to satisfy a required permission, defaulting to deny when it cannot be
# confirmed that the grant's role owns the permission's module.

DESIGNER_PERMISSION_CODES: frozenset[str] = frozenset(
    {
        "designer.study_version.read",
        "designer.study_version.create",
        "designer.study_version.amend",
        "designer.version.publish",
        "designer.form.read",
        "designer.form.configure",
        "designer.field.configure",
        "designer.editcheck.configure",
        "designer.editcheck.test",
        "designer.codelist.read",
        "designer.codelist.configure",
        "designer.subject_phase.configure",
        "designer.soa.read",
        "designer.soa.configure",
        "designer.cycle.configure",
        "designer.visit.read",
        "designer.visit.configure",
        "designer.arm.configure",
        "designer.crf_access.configure",
        "designer.raw_data_variable.configure",
        "designer.coding_setting.configure",
    }
)

# Operational (EDC) permission codes: data entry, subjects, visit instances,
# queries, SDV, review, lock, signature, dashboards, reports, exports, and
# operational study-info reads. These are the existing operational codes that
# EDC routers already use; they are effective only through an Operational_Role.
OPERATIONAL_PERMISSION_CODES: frozenset[str] = frozenset(
    {
        "study.read",
        "subject.create",
        "subject.read",
        "subject.update",
        "form.read",
        "form.enter",
        "form.submit",
        "query.create",
        "query.respond",
        "query.close",
        "query.reopen",
        "query.cancel",
        "sdv.manage",
        "review.manage",
        "lock.manage",
        "signature.sign",
        "data.export",
        "file.upload",
    }
)


def permission_module(code: str) -> str | None:
    """Return the authorization module that owns a permission code.

    Returns ``"designer"`` for Designer_Module codes, ``"operational"`` for
    EDC_Module operational codes, and ``None`` for shared/platform codes that
    are exempt from Designer/EDC module isolation.
    """
    if code in DESIGNER_PERMISSION_CODES:
        return "designer"
    if code in OPERATIONAL_PERMISSION_CODES:
        return "operational"
    return None


def role_modules(
    permission_codes: frozenset[str] | set[str] | list[str],
) -> tuple[str, ...]:
    """Classify which authorization modules a role owns from its codes.

    A role owns the ``"designer"`` module if it grants any designer-module code
    and the ``"operational"`` module if it grants any operational-module code.
    A role may own neither (a purely shared/system/CTMS/PV role) or — as with
    the built-in System Administrator — both.

    The returned tuple is used to gate module-scoped permissions (Requirement
    10): a designer code is only effective when it comes from a grant whose
    role owns the designer module, and an operational code only from a grant
    whose role owns the operational module. Modeling ownership as a set (rather
    than a single module) keeps a role that legitimately spans both modules —
    for example System Administrator — able to satisfy both module gates, while
    a single-purpose Designer_Role or Operational_Role still owns exactly one.
    """
    codes = set(permission_codes)
    modules: list[str] = []
    if codes & DESIGNER_PERMISSION_CODES:
        modules.append("designer")
    if codes & OPERATIONAL_PERMISSION_CODES:
        modules.append("operational")
    return tuple(modules)


ROLE_DEFINITIONS: dict[str, dict[str, str | list[str]]] = {
    "System Administrator": {
        "scope": "system",
        # System administrators have every capability at system scope.
        # Keep this derived from PERMISSION_CODES so newly added permissions
        # are included automatically when the seeder is rerun.
        "permissions": sorted(PERMISSION_CODES),
    },
    "Study Administrator": {
        "scope": "study",
        "permissions": [
            "study.configure",
            "version.publish",
            "site.manage",
            "form.configure",
            "editcheck.configure",
            "user.assign",
        ],
    },
    "Data Manager": {
        "scope": "study",
        "permissions": [
            "query.create",
            "query.close",
            "query.reopen",
            "query.cancel",
            "editcheck.configure",
            "lock.manage",
            "data.export",
            "audit.read",
            "review.manage",
        ],
    },
    "CRA": {
        "scope": "study",
        "permissions": [
            "subject.read",
            "form.read",
            "sdv.manage",
            "query.create",
            "query.close",
            "audit.read",
        ],
    },
    "Investigator (PI)": {
        "scope": "site",
        "permissions": [
            "subject.read",
            "form.read",
            "form.enter",
            "form.submit",
            "query.respond",
            "signature.sign",
        ],
    },
    "Site Coordinator": {
        "scope": "site",
        "permissions": [
            "subject.create",
            "subject.read",
            "subject.update",
            "form.enter",
            "form.submit",
            "query.respond",
            "file.upload",
        ],
    },
    "Medical Reviewer": {
        "scope": "study",
        "permissions": [
            "form.read",
            "review.manage",
            "query.create",
            "audit.read",
        ],
    },
    # --- Designer / EDC module-scoped roles (Requirement 10) ---------------
    # Designer_Role carries the full Designer_Module permission set and nothing
    # else, so it can only authorize design-time authoring. Operational_Role
    # carries the EDC_Module operational set and nothing else. A user may hold
    # both; PermissionService enforces each set only within its own module
    # scope (R10.5, R10.6).
    "Designer_Role": {
        "scope": "study",
        "permissions": sorted(DESIGNER_PERMISSION_CODES),
    },
    "Operational_Role": {
        "scope": "study",
        "permissions": sorted(OPERATIONAL_PERMISSION_CODES),
    },
    "CTMS_Admin": {
        "scope": "system",
        "permissions": sorted(CTMS_PERMISSION_CODES),
    },
    "CTMS_Operations_User": {
        "scope": "study",
        "permissions": [
            "ctms.operational_data_read",
            "ctms.operational_study_management",
            "ctms.operational_site_management",
            "ctms.monitoring_activity_management",
            "ctms.enrollment_management",
        ],
    },
    "CTMS_Viewer": {
        "scope": "study",
        # Viewer is intentionally read-only: no CTMS mutation or remediation
        # permission is included here.
        "permissions": ["ctms.operational_data_read"],
    },
    # --- PV/Safety roles -----------------------------------------------------
    # Every PV role is composed only from PV_PERMISSION_CODES, so no PV role can
    # mutate an EDC clinical or CTMS operational record (Requirements 2.6, 18.4).
    "Safety_Admin": {
        "scope": "system",
        "permissions": sorted(PV_PERMISSION_CODES),
    },
    "Safety_Manager": {
        "scope": "study",
        # Full safety case workflow across a study: intake, lifecycle,
        # assessment, coding, narratives, reporting, reconciliation, export.
        "permissions": [
            "safety_case.enter",
            "safety_case.read",
            "safety_case.lifecycle",
            "safety_assessment.record",
            "safety_coding.assign",
            "safety_narrative.write",
            "safety_report.manage",
            "safety_reconciliation.run",
            "safety_export.create",
            "safety_audit.read",
        ],
    },
    "Safety_Associate": {
        "scope": "site",
        # Intake and capture at site scope; no reporting or reconciliation.
        "permissions": [
            "safety_case.enter",
            "safety_case.read",
            "safety_case.lifecycle",
            "safety_narrative.write",
        ],
    },
    "Safety_Physician": {
        "scope": "study",
        # Medical assessment and coding of captured cases.
        "permissions": [
            "safety_case.read",
            "safety_assessment.record",
            "safety_coding.assign",
            "safety_narrative.write",
        ],
    },
    "Safety_Coder": {
        "scope": "study",
        # MedDRA/WHODrug coding specialist.
        "permissions": [
            "safety_case.read",
            "safety_coding.assign",
        ],
    },
    "Regulatory_Reporter": {
        "scope": "study",
        # Reportability, regulatory clocks, ICSR/E2B submissions, and exports.
        "permissions": [
            "safety_case.read",
            "safety_report.manage",
            "safety_export.create",
            "safety_audit.read",
        ],
    },
    "Safety_Viewer": {
        "scope": "study",
        # Read-only: safety case read and safety audit read only.
        "permissions": [
            "safety_case.read",
            "safety_audit.read",
        ],
    },
}


# ---------------------------------------------------------------------------
# Seeding routine
# ---------------------------------------------------------------------------


async def seed_roles_and_permissions(session: AsyncSession) -> None:
    """Seed permission codes and built-in roles into the database.

    This function is idempotent: existing permissions and roles are skipped.
    It does NOT commit — the caller controls the transaction boundary.
    """
    from app.models.shared.identity import Permission, Role, RolePermission

    # --- Seed permissions ---
    existing_perms_result = await session.execute(select(Permission.code))
    existing_codes: set[str] = set(existing_perms_result.scalars().all())

    new_permissions: list[Permission] = []
    for code in sorted(PERMISSION_CODES):
        if code not in existing_codes:
            new_permissions.append(Permission(code=code))

    if new_permissions:
        session.add_all(new_permissions)
        await session.flush()

    # Build code -> Permission lookup (includes both pre-existing and newly added)
    all_perms_result = await session.execute(select(Permission))
    perm_by_code: dict[str, Permission] = {p.code: p for p in all_perms_result.scalars().all()}

    # --- Seed roles and role-permission associations ---
    existing_roles_result = await session.execute(select(Role))
    existing_roles: dict[str, Role] = {
        role.name: role for role in existing_roles_result.scalars().all()
    }

    for role_name, definition in ROLE_DEFINITIONS.items():
        role = existing_roles.get(role_name)
        if role is None:
            role = Role(
                name=role_name,
                scope_level=definition["scope"],  # type: ignore[arg-type]
                description=f"Built-in {role_name} role",
                is_system=True,
            )
            session.add(role)
            await session.flush()

        # Create role-permission associations
        permission_codes: list[str] = definition["permissions"]  # type: ignore[assignment]
        existing_permission_ids = set(
            (
                await session.execute(
                    select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
                )
            )
            .scalars()
            .all()
        )
        for perm_code in permission_codes:
            perm = perm_by_code.get(perm_code)
            if perm is not None and perm.id not in existing_permission_ids:
                session.add(RolePermission(role_id=role.id, permission_id=perm.id))

        await session.flush()
