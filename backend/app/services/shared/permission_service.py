"""Permission_Service — scope resolution and enforcement.

Satisfies Requirements:
  - 2.1: Authorization_Scope resolved as the union of permission codes of assigned roles.
  - 2.2: Route-level permission enforcement by study/site scope.
  - 2.3: Authorization error when scope lacks required permission.
  - 2.4: filter_studies/filter_sites return only in-scope resources.
  - 2.5: Object-level access denial for out-of-scope objects.
  - 2.6: Enforcement independent of any frontend permission checks.
  - 10.1: Designer permissions grantable only to Designer_Roles; operational
          permissions only to Operational_Roles.
  - 10.2: Deny designer-definition authoring to users without a Designer_Role.
  - 10.3: Deny operational-record authoring to users without an Operational_Role.
  - 10.4: Server-side authorization with default-deny when it cannot be confirmed.
  - 10.5: Single-role users get only their module's scope, denied the other.
  - 10.6: Both-role users have each permission set enforced only within its own
          module scope; one role never authorizes an action in the other module.
  - 23.4: Every protected operation passes through Permission_Service before mutation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctms import Module
from app.core.exceptions import AuthenticationError, AuthorizationError, ServiceUnavailableError
from app.core.permissions import role_modules
from app.models.shared.identity import User, UserStatus
from app.schemas.shared.permission import AuthorizationScope, PermissionGrant
from app.services.shared.platform_authorization import (
    AuthorizationGateway,
    get_platform_authorization,
)

logger = logging.getLogger(__name__)


class PermissionService:
    """Single authority for access control.

    Resolves user permissions from their role assignments and enforces both
    route-level and object-level access checks.
    """

    def __init__(self, platform_gateway: AuthorizationGateway | None = None) -> None:
        self._platform_gateway = platform_gateway

    def _gateway(self) -> AuthorizationGateway:
        return self._platform_gateway or get_platform_authorization()

    def _ensure_active(self, user: User) -> None:
        """Reject deactivated accounts before resolving or enforcing scope.

        ``get_current_user`` performs the same check at the HTTP boundary, but
        keeping it here prevents direct service calls and background-triggered
        mutations from using a stale role assignment after deactivation.
        """
        status = getattr(user, "status", None)
        if status == UserStatus.inactive or status == UserStatus.inactive.value:
            raise AuthenticationError("Account is inactive")

    def resolve_scope(self, user: User) -> AuthorizationScope:
        """Compute the union of permission codes across the user's assigned roles.

        Each grant is tagged with the study_id/site_id from its user_role assignment.
        A role with scope_level='system' produces grants with study_id=None, site_id=None,
        which match any study/site.

        Requirement 2.1: Authorization_Scope is the union of permission codes of assigned roles,
        each applied at the study and site scope of its assignment.
        """
        self._ensure_active(user)
        grants: list[PermissionGrant] = []

        for user_role in user.user_roles:
            role = user_role.role
            if (
                getattr(role, "platform_managed", False) is True
                and getattr(role, "platform_status", "active") != "active"
            ):
                continue
            # Determine the study/site scope from the role assignment
            # System-level roles: study_id and site_id are None
            # Study-level roles: study_id is set, site_id is None
            # Site-level roles: both study_id and site_id are set
            study_id = user_role.study_id
            site_id = user_role.site_id

            role_permission_codes = {
                role_permission.permission.code for role_permission in role.role_permissions
            }
            # Classify which authorization modules this role owns (designer,
            # operational, both, or neither) from its own permission codes. Each
            # grant carries this so PermissionService can enforce module-scoped
            # separation of duties (Requirement 10): a designer code is
            # effective only through a role owning the designer module and an
            # operational code only through a role owning the operational
            # module, for both single- and both-role users.
            modules = role_modules(role_permission_codes)

            # Emit one grant per RolePermission entry (not per distinct code) so
            # the resolved scope mirrors the role's assignment exactly. Module
            # classification above is computed from the distinct code set, which
            # is correct regardless of per-entry duplication.
            for role_permission in role.role_permissions:
                grants.append(
                    PermissionGrant(
                        permission_code=role_permission.permission.code,
                        study_id=study_id,
                        site_id=site_id,
                        role_modules=modules,
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
        local_allowed = scope.has_permission(permission, study_id=study_id, site_id=site_id)
        gateway = self._gateway()
        if gateway.mode != "disabled":
            try:
                decision = gateway.decide(user, permission, study_id=study_id, site_id=site_id)
            except ServiceUnavailableError:
                if gateway.mode == "enforced":
                    raise
                logger.warning(
                    "platform authorization unavailable in shadow mode",
                    extra={"user_id": str(user.id), "permission": permission},
                )
                decision = None
            if decision is None:
                if not local_allowed:
                    raise AuthorizationError(
                        message="Insufficient permissions",
                        details={
                            "required_permission": permission,
                            "study_id": str(study_id) if study_id else None,
                            "site_id": str(site_id) if site_id else None,
                        },
                    )
                return
            if gateway.mode == "shadow" and decision.allowed != local_allowed:
                logger.warning(
                    "platform authorization shadow mismatch",
                    extra={
                        "user_id": str(user.id),
                        "permission": permission,
                        "study_id": str(study_id) if study_id else None,
                        "site_id": str(site_id) if site_id else None,
                        "local_allowed": local_allowed,
                        "platform_allowed": decision.allowed,
                        "policy_version": decision.policy_version,
                    },
                )
            if gateway.mode == "enforced":
                local_allowed = decision.allowed
        if not local_allowed:
            raise AuthorizationError(
                message="Insufficient permissions",
                details={
                    "required_permission": permission,
                    "study_id": str(study_id) if study_id else None,
                    "site_id": str(site_id) if site_id else None,
                },
            )

    async def require_audited(
        self,
        session: AsyncSession,
        user: User,
        permission: str,
        *,
        module: Module,
        action: str,
        entity_type: str,
        entity_id: UUID | None = None,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> None:
        """Enforce a create/modify permission and audit any denial exactly once.

        This is the auditing wrapper for ``require`` used on the mutating paths
        that author a Designer_Definition or an Operational_Record. On success
        it behaves exactly like ``require`` (no audit event — the mutation's own
        audit event records the change under R1.7). On denial it records exactly
        one immutable audit event identifying the actor, the *attempted* module
        scope, the attempted action, and the denial, then re-raises the original
        ``AuthorizationError`` so the request is rejected and the target is left
        unchanged (R10.2, R10.3, R10.7).

        The denial event is written through the shared, append-only audit
        service within the caller's transaction. Because ``require`` runs its
        checks *before* any mutation, the only row this transaction commits on a
        denial is the denial audit event itself — exactly one event per denied
        action. ``entity_id`` is optional because a denied *create* has no
        persisted entity yet; a synthetic id is used so the append-only row is
        still well-formed and attributable to the attempted action.

        Args:
            session: The active async session (caller's transaction).
            user: The acting user whose scope is evaluated.
            permission: The required permission code.
            module: The attempted module scope (``Module.DESIGNER`` for a
                Designer_Definition, ``Module.EDC`` for an Operational_Record).
            action: The attempted action (e.g. ``"create"``, ``"update"``).
            entity_type: The type of entity the action targeted.
            entity_id: Optional id of the targeted entity (absent for creates).
            study_id: Optional study scope used for the permission check.
            site_id: Optional site scope used for the permission check.
        """
        # Imported lazily to avoid a module-load cycle: ``app.core.audit`` pulls
        # in ``app.api.deps``, which imports this module.
        from app.core.audit import audit_service

        try:
            self.require(user, permission, study_id=study_id, site_id=site_id)
        except AuthorizationError as denial:
            await audit_service.record(
                session,
                entity_type=entity_type,
                entity_id=entity_id if entity_id is not None else uuid4(),
                action=action,
                module=module,
                actor_id=getattr(user, "id", None),
                actor_email=getattr(user, "email", None),
                study_id=study_id,
                site_id=site_id,
                new_value="authorization-denied",
                reason=(
                    f"required_permission={permission}; "
                    f"attempted_module={module.value}; attempted_action={action}"
                ),
            )
            raise denial

    def filter_studies(self, user: User, study_ids: list[UUID]) -> list[UUID]:
        """Return only the study IDs within the user's scope.

        Requirement 2.4: list requests return only in-scope studies.
        """
        scope = self.resolve_scope(user)

        allowed_study_ids = set(study_ids) if scope.has_system_grant() else scope.get_study_ids()
        local = [sid for sid in study_ids if sid in allowed_study_ids]
        gateway = self._gateway()
        if gateway.mode == "disabled":
            return local
        try:
            batch = getattr(gateway, "decide_batch", None)
            if batch is not None:
                decisions = batch(
                    user,
                    "study.read",
                    tuple((study_id, None) for study_id in study_ids),
                )
                central = [
                    study_id
                    for study_id, decision in zip(study_ids, decisions, strict=True)
                    if decision.allowed
                ]
            else:
                central = [
                    study_id
                    for study_id in study_ids
                    if gateway.decide(
                        user,
                        "study.read",
                        study_id=study_id,
                        site_id=None,
                    ).allowed
                ]
        except ServiceUnavailableError:
            if gateway.mode == "enforced":
                raise
            logger.warning("platform authorization unavailable for study-list shadow check")
            return local
        if gateway.mode == "shadow":
            if set(central) != set(local):
                logger.warning(
                    "platform authorization study-list shadow mismatch",
                    extra={"user_id": str(user.id)},
                )
            return local
        return central

    def filter_sites(
        self,
        user: User,
        site_ids: list[UUID],
        site_study_ids: Mapping[UUID, UUID] | None = None,
    ) -> list[UUID]:
        """Return only sites within the user's system/study/site scope.

        ``site_study_ids`` is optional for compatibility with callers that
        already query a single study. When supplied, study-scoped grants also
        include every site mapped to an authorized study.
        """
        scope = self.resolve_scope(user)

        allowed_site_ids = set(site_ids) if scope.has_system_grant() else scope.get_site_ids()
        allowed_study_ids = (
            set(site_study_ids.values())
            if scope.has_system_grant() and site_study_ids is not None
            else scope.get_study_ids()
        )
        local = [
            site_id
            for site_id in site_ids
            if site_id in allowed_site_ids
            or (site_study_ids is not None and site_study_ids.get(site_id) in allowed_study_ids)
        ]
        gateway = self._gateway()
        if gateway.mode == "disabled":
            return local
        try:
            resources = tuple(
                (site_study_ids.get(site_id) if site_study_ids else None, site_id)
                for site_id in site_ids
            )
            batch = getattr(gateway, "decide_batch", None)
            if batch is not None:
                decisions = batch(user, "site.read", resources)
                central = [
                    site_id
                    for site_id, decision in zip(site_ids, decisions, strict=True)
                    if decision.allowed
                ]
            else:
                central = [
                    site_id
                    for site_id, (study_id, resource_site_id) in zip(
                        site_ids, resources, strict=True
                    )
                    if gateway.decide(
                        user,
                        "site.read",
                        study_id=study_id,
                        site_id=resource_site_id,
                    ).allowed
                ]
        except ServiceUnavailableError:
            if gateway.mode == "enforced":
                raise
            logger.warning("platform authorization unavailable for site-list shadow check")
            return local
        if gateway.mode == "shadow":
            if set(central) != set(local):
                logger.warning(
                    "platform authorization site-list shadow mismatch",
                    extra={"user_id": str(user.id)},
                )
            return local
        return central

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
