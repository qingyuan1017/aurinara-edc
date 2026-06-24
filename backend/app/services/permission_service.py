"""Permission_Service — scope resolution and enforcement.

Satisfies Requirements:
  - 2.1: Authorization_Scope resolved as the union of permission codes of assigned roles.
  - 2.2: Route-level permission enforcement by study/site scope.
  - 2.3: Authorization error when scope lacks required permission.
  - 2.4: filter_studies/filter_sites return only in-scope resources.
  - 2.5: Object-level access denial for out-of-scope objects.
  - 2.6: Enforcement independent of any frontend permission checks.
  - 23.4: Every protected operation passes through Permission_Service before mutation.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import AuthorizationError
from app.models.identity import User
from app.schemas.permission import AuthorizationScope, PermissionGrant


class PermissionService:
    """Single authority for access control.

    Resolves user permissions from their role assignments and enforces both
    route-level and object-level access checks.
    """

    def resolve_scope(self, user: User) -> AuthorizationScope:
        """Compute the union of permission codes across the user's assigned roles.

        Each grant is tagged with the study_id/site_id from its user_role assignment.
        A role with scope_level='system' produces grants with study_id=None, site_id=None,
        which match any study/site.

        Requirement 2.1: Authorization_Scope is the union of permission codes of assigned roles,
        each applied at the study and site scope of its assignment.
        """
        grants: list[PermissionGrant] = []

        for user_role in user.user_roles:
            role = user_role.role
            # Determine the study/site scope from the role assignment
            # System-level roles: study_id and site_id are None
            # Study-level roles: study_id is set, site_id is None
            # Site-level roles: both study_id and site_id are set
            study_id = user_role.study_id
            site_id = user_role.site_id

            for role_permission in role.role_permissions:
                permission_code = role_permission.permission.code
                grants.append(
                    PermissionGrant(
                        permission_code=permission_code,
                        study_id=study_id,
                        site_id=site_id,
                    )
                )

        return AuthorizationScope(grants=grants)

    def require(
        self,
        user: User,
        permission: str,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> None:
        """Raise AuthorizationError if the user's scope lacks the required permission.

        A system-scope role grants access regardless of study/site.

        Requirements 2.2, 2.3, 23.4: route-level enforcement with clear error.
        """
        scope = self.resolve_scope(user)
        if not scope.has_permission(permission, study_id=study_id, site_id=site_id):
            raise AuthorizationError(
                message="Insufficient permissions",
                details={
                    "required_permission": permission,
                    "study_id": str(study_id) if study_id else None,
                    "site_id": str(site_id) if site_id else None,
                },
            )

    def filter_studies(self, user: User, study_ids: list[UUID]) -> list[UUID]:
        """Return only the study IDs within the user's scope.

        Requirement 2.4: list requests return only in-scope studies.
        """
        scope = self.resolve_scope(user)

        # System-scope users see all studies
        if scope.has_system_grant():
            return study_ids

        allowed_study_ids = scope.get_study_ids()
        return [sid for sid in study_ids if sid in allowed_study_ids]

    def filter_sites(self, user: User, site_ids: list[UUID]) -> list[UUID]:
        """Return only the site IDs within the user's scope.

        Requirement 2.4: list requests return only in-scope sites.
        """
        scope = self.resolve_scope(user)

        # System-scope users see all sites
        if scope.has_system_grant():
            return site_ids

        allowed_site_ids = scope.get_site_ids()
        # Also include sites that belong to studies the user has study-scope for
        # (study-scope grants cover all sites in that study — but we can't resolve
        # site→study here without the site objects, so we rely on explicit site grants
        # and study-scope grants are handled at a higher layer via filter_studies)
        return [sid for sid in site_ids if sid in allowed_site_ids]

    def assert_object_access(self, user: User, obj: object) -> None:
        """Check that the object's study_id/site_id is within the user's scope.

        Raises AuthorizationError if the user cannot access the given object.
        The object must have a `study_id` and optionally a `site_id` attribute.

        Requirement 2.5: deny access to objects whose study/site is out of scope.
        """
        scope = self.resolve_scope(user)

        # System-scope users have access to everything
        if scope.has_system_grant():
            return

        obj_study_id: UUID | None = getattr(obj, "study_id", None)
        obj_site_id: UUID | None = getattr(obj, "site_id", None)

        if obj_study_id is None:
            # Objects without a study_id are system-level; only system-scope users
            # can access them (already handled by has_system_grant above)
            raise AuthorizationError(
                message="Insufficient permissions",
                details={"reason": "Object has no study scope and user lacks system access"},
            )

        # Check if user has any grant that covers this study/site
        # We need any permission grant that covers the study/site (not a specific code)
        has_access = False
        for grant in scope.grants:
            # System-scope grant covers everything (already returned above)
            if grant.study_id is None and grant.site_id is None:
                has_access = True
                break

            # Study-scope grant covers the study and all its sites
            if grant.study_id == obj_study_id and grant.site_id is None:
                has_access = True
                break

            # Site-scope grant covers the exact study+site
            if grant.study_id == obj_study_id and grant.site_id == obj_site_id:
                has_access = True
                break

        if not has_access:
            raise AuthorizationError(
                message="Insufficient permissions",
                details={
                    "reason": "Object is outside user's authorization scope",
                    "object_study_id": str(obj_study_id) if obj_study_id else None,
                    "object_site_id": str(obj_site_id) if obj_site_id else None,
                },
            )
