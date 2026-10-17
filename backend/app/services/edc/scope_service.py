"""EDC object and collection authorization helpers.

Route path IDs are not trusted as scope. Object checks derive scope from the
loaded clinical record; collection checks return the exact site intersection
available to a site-scoped user.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import AuthorizationError
from app.models.edc.form_data import FormInstance
from app.models.edc.query import Query
from app.models.edc.subject import Subject
from app.models.shared.identity import User
from app.services.shared.permission_service import PermissionService


class EDCScopeService:
    @staticmethod
    def require_subject(
        user: User,
        permissions: PermissionService,
        permission: str,
        subject: Subject,
    ) -> None:
        EDCScopeService.require_scope(
            user,
            permissions,
            permission,
            study_id=subject.study_id,
            site_id=subject.site_id,
        )

    @staticmethod
    def require_form(
        user: User,
        permissions: PermissionService,
        permission: str,
        form_instance: FormInstance,
    ) -> None:
        subject = form_instance.subject
        EDCScopeService.require_scope(
            user,
            permissions,
            permission,
            study_id=subject.study_id,
            site_id=subject.site_id,
        )

    @staticmethod
    def require_query(
        user: User,
        permissions: PermissionService,
        permission: str,
        query: Query,
    ) -> None:
        EDCScopeService.require_scope(
            user,
            permissions,
            permission,
            study_id=query.study_id,
            site_id=query.site_id,
        )

    @staticmethod
    def require_scope(
        user: User,
        permissions: PermissionService,
        permission: str,
        *,
        study_id: UUID,
        site_id: UUID | None,
    ) -> None:
        try:
            permissions.require(
                user,
                permission,
                study_id=study_id,
                site_id=site_id,
            )
        except AuthorizationError:
            raise AuthorizationError(
                message="Access denied",
                details={"reason": "EDC_SCOPE_DENIED", "required_permission": permission},
            ) from None

    @staticmethod
    def authorized_site_ids(
        user: User,
        permissions: PermissionService,
        permission: str,
        study_id: UUID,
    ) -> set[UUID] | None:
        """Return ``None`` for whole-study access or an authorized site set."""
        scope = permissions.resolve_scope(user)
        if scope.has_system_grant(permission) or scope.has_permission(
            permission, study_id=study_id
        ):
            return None
        site_ids = {
            grant.site_id
            for grant in scope.grants
            if grant.study_id == study_id
            and grant.site_id is not None
            and scope.has_permission(
                permission,
                study_id=study_id,
                site_id=grant.site_id,
            )
        }
        if not site_ids:
            raise AuthorizationError(
                message="Access denied",
                details={"reason": "EDC_SCOPE_DENIED", "required_permission": permission},
            )
        return site_ids


edc_scope_service = EDCScopeService()

__all__ = ["EDCScopeService", "edc_scope_service"]
