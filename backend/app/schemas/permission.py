"""Permission and authorization scope schemas.

Satisfies Requirements:
  - 2.1: AuthorizationScope resolved as the union of permission codes of assigned roles,
          each applied at the study/site scope of its assignment.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PermissionGrant(BaseModel):
    """A single permission code granted at a specific study/site scope.

    A grant with study_id=None and site_id=None indicates a system-level grant
    that applies regardless of study or site.
    """

    model_config = ConfigDict(frozen=True)

    permission_code: str
    study_id: UUID | None = None
    site_id: UUID | None = None


class AuthorizationScope(BaseModel):
    """The resolved set of permission grants for a user.

    Represents the union of all permission codes across the user's assigned roles,
    each tagged with the study_id/site_id from its user_role assignment.
    """

    grants: list[PermissionGrant] = []

    def has_permission(
        self,
        permission: str,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> bool:
        """Check whether the scope contains the required permission for the given context.

        A system-scope grant (study_id=None, site_id=None) satisfies any study/site request.
        A study-scope grant (study_id set, site_id=None) satisfies requests for that study
        or any site within it.
        A site-scope grant (study_id set, site_id set) satisfies only that exact site.
        """
        for grant in self.grants:
            if grant.permission_code != permission:
                continue

            # System-scope grant: matches everything
            if grant.study_id is None and grant.site_id is None:
                return True

            # Study-scope grant: matches if target study matches
            # (covers all sites within that study)
            if grant.study_id is not None and grant.site_id is None:
                if study_id == grant.study_id:
                    return True
                # If caller asks for a site within this study, study-scope covers it
                if site_id is not None and study_id == grant.study_id:
                    return True

            # Site-scope grant: matches only the exact study+site
            if (
                grant.study_id is not None
                and grant.site_id is not None
                and study_id == grant.study_id
                and site_id == grant.site_id
            ):
                return True

        return False

    def get_study_ids(self) -> set[UUID]:
        """Return all study IDs the user has any grant for (including system-scope)."""
        result: set[UUID] = set()
        for grant in self.grants:
            if grant.study_id is not None:
                result.add(grant.study_id)
        return result

    def has_system_grant(self, permission: str | None = None) -> bool:
        """Check whether the user holds any system-scope grant.

        If permission is provided, checks for that specific permission at system scope.
        If permission is None, checks for any system-scope grant.
        """
        for grant in self.grants:
            if (
                grant.study_id is None
                and grant.site_id is None
                and (permission is None or grant.permission_code == permission)
            ):
                return True
        return False

    def get_site_ids(self) -> set[UUID]:
        """Return all site IDs the user has any grant for."""
        result: set[UUID] = set()
        for grant in self.grants:
            if grant.site_id is not None:
                result.add(grant.site_id)
        return result
