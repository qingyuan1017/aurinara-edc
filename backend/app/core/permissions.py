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
}


# ---------------------------------------------------------------------------
# Seeding routine
# ---------------------------------------------------------------------------


async def seed_roles_and_permissions(session: AsyncSession) -> None:
    """Seed permission codes and built-in roles into the database.

    This function is idempotent: existing permissions and roles are skipped.
    It does NOT commit — the caller controls the transaction boundary.
    """
    from app.models.identity import Permission, Role, RolePermission

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
    perm_by_code: dict[str, Permission] = {
        p.code: p for p in all_perms_result.scalars().all()
    }

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
                    select(RolePermission.permission_id).where(
                        RolePermission.role_id == role.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for perm_code in permission_codes:
            perm = perm_by_code.get(perm_code)
            if perm is not None and perm.id not in existing_permission_ids:
                session.add(
                    RolePermission(role_id=role.id, permission_id=perm.id)
                )

        await session.flush()
