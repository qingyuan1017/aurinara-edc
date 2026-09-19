"""Signature_Service — re-authenticated electronic signatures.

The service keeps signature rows and their Audit_Events in the caller's
transaction.  A signature is bound to a deterministic snapshot of the signed
clinical data; later changes can therefore stale the original attestation
without rewriting it.

Satisfies Requirements 17.1-17.4 and 21.4.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.request_context import get_actor
from app.core.security import verify_re_auth
from app.models.form_data import FieldValue, FormInstance
from app.models.identity import User, UserStatus
from app.models.signature import Signature, SignatureObjectType, SignatureStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SignedTarget:
    """Normalized polymorphic reference and available audit context."""

    object_type: SignatureObjectType
    object_id: UUID
    study_id: UUID | None = None
    site_id: UUID | None = None
    subject_id: UUID | None = None


@dataclass(frozen=True)
class _Signer:
    """Signer identity and password hash resolved for re-authentication."""

    user_id: UUID
    email: str | None
    password_hash: str


class SignatureService:
    """Record signatures and stale previous attestations after data changes."""

    async def sign(
        self,
        session: AsyncSession,
        target: Any,
        meaning: str,
        credentials: Any = None,
        actor_id: Any = None,
        *,
        object_type: SignatureObjectType | str | None = None,
        object_id: UUID | None = None,
        password: str | None = None,
        signed_data: Any = None,
    ) -> Signature:
        """Record an electronic signature after successful re-authentication.

        ``credentials`` may be a password string, or a mapping/object with a
        ``password`` and a ``user``/``actor``/``user_id`` member.  Callers can
        also pass ``actor_id`` separately, which is useful for authenticated
        route handlers.  A User-like actor is accepted directly and avoids an
        extra lookup when its password hash is already loaded.

        ``signed_data`` is an optional explicit snapshot for callers signing a
        representation that is not an ORM object.  Normal clinical objects
        derive their snapshot from their current persisted values.
        """
        normalized_meaning = meaning.strip() if isinstance(meaning, str) else ""
        if not normalized_meaning:
            raise ValidationError(
                message="Signature meaning is required",
                details={"meaning": "must not be blank"},
            )

        signer = await self._resolve_signer(
            session,
            credentials=credentials,
            actor=actor_id,
            password=password,
        )
        try:
            reauthenticated = verify_re_auth(
                signer.password_hash, self._password(credentials, password)
            )
        except (TypeError, ValueError):
            reauthenticated = False
        if not reauthenticated:
            raise AuthenticationError(
                message="Re-authentication failed",
                details={"reason": "invalid signing credentials"},
            )

        target_ref = self._normalize_target(
            target,
            object_type=object_type,
            object_id=object_id,
        )
        snapshot = signed_data if signed_data is not None else self.snapshot(target)
        data_hash = self.hash_snapshot(snapshot)

        signature = Signature(
            object_type=target_ref.object_type.value,
            object_id=target_ref.object_id,
            signed_by=signer.user_id,
            signed_at=datetime.now(UTC),
            signature_meaning=normalized_meaning,
            data_hash=data_hash,
            status=SignatureStatus.valid,
            stale_reason=None,
        )
        session.add(signature)

        # The Signed form state is the integration point used by data capture
        # to invalidate this attestation on any later post-signature edit.
        if isinstance(target, FormInstance):
            from app.models.form_data import FormInstanceStatus

            target.status = FormInstanceStatus.signed
            target.updated_at = datetime.now(UTC)

        await session.flush()
        await audit_service.record(
            session,
            entity_type="signature",
            entity_id=signature.id,
            action="sign",
            study_id=target_ref.study_id,
            site_id=target_ref.site_id,
            subject_id=target_ref.subject_id,
            actor_id=signer.user_id,
            actor_email=signer.email,
            new_value=(
                f"object_type={target_ref.object_type.value}, "
                f"object_id={target_ref.object_id}, data_hash={data_hash}"
            ),
        )

        logger.info(
            "Electronic signature recorded: signature_id=%s object=%s:%s actor=%s",
            signature.id,
            target_ref.object_type.value,
            target_ref.object_id,
            signer.user_id,
        )
        return signature

    async def invalidate_if_changed(
        self,
        session: AsyncSession,
        target: Any,
        actor_id: Any = None,
        *,
        object_type: SignatureObjectType | str | None = None,
        object_id: UUID | None = None,
        reason: str | None = None,
        signed_data: Any = None,
    ) -> list[Signature]:
        """Mark valid signatures stale when the current data hash differs.

        The original signature row is retained.  Each newly stale signature
        receives a reason and its own audit event in the same caller-owned
        transaction.  Already-stale signatures are left untouched so repeated
        calls are idempotent.
        """
        target_ref = self._normalize_target(
            target,
            object_type=object_type,
            object_id=object_id,
        )
        snapshot = signed_data if signed_data is not None else self.snapshot(target)
        current_hash = self.hash_snapshot(snapshot)
        result = await session.execute(
            select(Signature).where(
                Signature.object_type == target_ref.object_type.value,
                Signature.object_id == target_ref.object_id,
                Signature.status == SignatureStatus.valid,
            )
        )
        signatures = list(result.scalars().all())
        changed = [signature for signature in signatures if signature.data_hash != current_hash]
        if not changed:
            return []

        actor_uuid, actor_email = self._normalize_actor(actor_id)
        stale_reason = (reason or "Signed data changed after the signature was recorded.").strip()
        if not stale_reason:
            stale_reason = "Signed data changed after the signature was recorded."

        for signature in changed:
            signature.status = SignatureStatus.stale
            signature.stale_reason = stale_reason

        await session.flush()
        for signature in changed:
            await audit_service.record(
                session,
                entity_type="signature",
                entity_id=signature.id,
                action="invalidate",
                study_id=target_ref.study_id,
                site_id=target_ref.site_id,
                subject_id=target_ref.subject_id,
                actor_id=actor_uuid,
                actor_email=actor_email,
                field_name="status",
                old_value=SignatureStatus.valid.value,
                new_value=SignatureStatus.stale.value,
                reason=stale_reason,
            )

        logger.info(
            "Electronic signatures invalidated: object=%s:%s count=%d actor=%s",
            target_ref.object_type.value,
            target_ref.object_id,
            len(changed),
            actor_uuid,
        )
        return changed

    @staticmethod
    def snapshot(target: Any) -> Any:
        """Return the clinical data represented by a signed target.

        Timestamps, identifiers, and audit metadata are excluded from generic
        ORM snapshots.  Form and field snapshots deliberately contain only
        clinical values, so a harmless metadata update cannot stale an
        attestation while a value change always changes its hash.
        """
        if isinstance(target, FieldValue):
            return {
                "value": target.value,
                "is_not_applicable": bool(target.is_not_applicable),
            }
        if isinstance(target, FormInstance):
            if isinstance(target.data_jsonb, Mapping):
                return target.data_jsonb
            values = getattr(target, "field_values", None) or []
            return {
                str(value.field_definition_id): {
                    "value": value.value,
                    "is_not_applicable": bool(value.is_not_applicable),
                }
                for value in values
            }
        if isinstance(target, Mapping):
            return target

        table = getattr(target, "__table__", None)
        if table is not None:
            ignored = {
                "id",
                "created_at",
                "updated_at",
                "deleted_at",
                "signed_at",
                "published_at",
                "submitted_at",
            }
            return {
                column.name: getattr(target, column.name, None)
                for column in table.columns
                if column.name not in ignored
            }
        return target

    @classmethod
    def hash_snapshot(cls, snapshot: Any) -> str:
        """Hash a canonical JSON representation of a signed data snapshot."""
        canonical = json.dumps(
            cls._json_safe(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "model_dump"):
            return cls._json_safe(value.model_dump(mode="json"))
        return value

    async def _resolve_signer(
        self,
        session: AsyncSession,
        *,
        credentials: Any,
        actor: Any,
        password: str | None,
    ) -> _Signer:
        credential_user = self._credential_value(credentials, "user")
        if credential_user is None:
            credential_user = self._credential_value(credentials, "actor")
        if credential_user is None:
            credential_user = self._credential_value(credentials, "user_id")
        resolved_actor = actor if actor is not None else credential_user
        if resolved_actor is None:
            resolved_actor = get_actor()
        if resolved_actor is None:
            raise AuthenticationError(
                message="A signer identity is required",
                details={},
            )

        if isinstance(resolved_actor, User):
            user = resolved_actor
        else:
            user_id = UUID(str(getattr(resolved_actor, "id", resolved_actor)))
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if user is None:
                raise AuthenticationError(
                    message="Signer identity could not be resolved",
                    details={"user_id": str(user_id)},
                )

        if user.status != UserStatus.active:
            raise AuthenticationError(
                message="Inactive users cannot sign clinical data",
                details={"user_id": str(user.id)},
            )
        if not user.password_hash:
            raise AuthenticationError(
                message="Re-authentication is unavailable for this user",
                details={"user_id": str(user.id)},
            )
        return _Signer(UUID(str(user.id)), user.email, user.password_hash)

    @staticmethod
    def _password(credentials: Any, password: str | None) -> str:
        if password is not None:
            return password
        if isinstance(credentials, str):
            return credentials
        value = SignatureService._credential_value(credentials, "password")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _credential_value(credentials: Any, name: str) -> Any:
        if isinstance(credentials, Mapping):
            return credentials.get(name)
        return getattr(credentials, name, None) if credentials is not None else None

    @staticmethod
    def _normalize_actor(actor: Any) -> tuple[UUID | None, str | None]:
        if actor is None:
            return None, None
        actor_id = actor if isinstance(actor, UUID) else getattr(actor, "id", actor)
        return UUID(str(actor_id)), getattr(actor, "email", None)

    @staticmethod
    def _normalize_target(
        target: Any,
        *,
        object_type: SignatureObjectType | str | None,
        object_id: UUID | None,
    ) -> _SignedTarget:
        explicit_type = object_type.value if isinstance(object_type, SignatureObjectType) else object_type
        if explicit_type is not None:
            try:
                normalized_type = SignatureObjectType(str(explicit_type))
            except ValueError as exc:
                raise ValidationError(
                    message="Invalid signature object type",
                    details={"object_type": str(explicit_type)},
                ) from exc
            resolved_id = object_id or (
                target if isinstance(target, UUID) else getattr(target, "id", None)
            )
            if resolved_id is None:
                raise ValidationError(
                    message="A signed object id is required",
                    details={"object_type": normalized_type.value},
                )
        else:
            if target is None or isinstance(target, UUID):
                raise ValidationError(
                    message="A signed object type is required",
                    details={},
                )
            class_to_type = {
                "FieldValue": SignatureObjectType.field,
                "FieldDefinition": SignatureObjectType.field,
                "FormInstance": SignatureObjectType.form,
                "FormDefinition": SignatureObjectType.form,
                "VisitInstance": SignatureObjectType.visit,
                "Subject": SignatureObjectType.subject,
                "Site": SignatureObjectType.site,
                "Study": SignatureObjectType.study,
            }
            normalized_type = class_to_type.get(target.__class__.__name__)
            resolved_id = getattr(target, "id", None)
            if normalized_type is None or resolved_id is None:
                raise ValidationError(
                    message="Unsupported signed object",
                    details={"target_type": target.__class__.__name__},
                )

        context_target = target if not isinstance(target, UUID) else None
        subject = context_target.__dict__.get("subject") if context_target is not None else None
        study = context_target.__dict__.get("study") if context_target is not None else None
        site = context_target.__dict__.get("site") if context_target is not None else None
        return _SignedTarget(
            object_type=normalized_type,
            object_id=UUID(str(resolved_id)),
            study_id=getattr(context_target, "study_id", None) or getattr(subject, "study_id", None) or getattr(study, "id", None),
            site_id=getattr(context_target, "site_id", None) or getattr(subject, "site_id", None) or getattr(site, "id", None),
            subject_id=getattr(context_target, "subject_id", None) or getattr(subject, "id", None),
        )


signature_service = SignatureService()

__all__ = ["SignatureService", "signature_service"]
