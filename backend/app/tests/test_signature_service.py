"""Unit tests for SignatureService and signed-form data-change integration."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import hash_password
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.identity import User, UserStatus
from app.models.signature import Signature, SignatureStatus
from app.services.data_capture_service import DataCaptureService
from app.services.signature_service import SignatureService, signature_service


@pytest.fixture
def service() -> SignatureService:
    return SignatureService()


@pytest.fixture
def actor() -> User:
    return User(
        id=uuid.uuid4(),
        email="investigator@example.test",
        password_hash=hash_password("signature-password"),
        first_name="Investigator",
        last_name="Test",
        status=UserStatus.active,
    )


def _form(status: FormInstanceStatus = FormInstanceStatus.submitted) -> FormInstance:
    return FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=status,
        data_jsonb={"weight": "72", "consent": True},
        created_at=datetime.now(UTC),
    )


def _result(*, first=None, all_items=None):
    result = MagicMock()
    result.scalars.return_value.first.return_value = first
    result.scalars.return_value.all.return_value = (
        list(all_items) if all_items is not None else []
    )
    return result


class TestSign:
    async def test_sign_requires_reauthentication(self, service, actor):
        session = AsyncMock()
        session.add = MagicMock()
        form = _form()

        with patch(
            "app.services.signature_service.verify_re_auth", return_value=False
        ) as verify, pytest.raises(AuthenticationError, match="Re-authentication failed"):
            await service.sign(
                session, form, "I attest this data is accurate.", "wrong", actor
            )

        verify.assert_called_once_with(actor.password_hash, "wrong")
        session.add.assert_not_called()

    async def test_sign_persists_identity_hash_and_audit(self, service, actor):
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        form = _form()

        with patch("app.services.signature_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.sign(
                session,
                form,
                "I attest this data is accurate.",
                "signature-password",
                actor,
            )

        assert result.object_type == "form"
        assert result.object_id == form.id
        assert result.signed_by == actor.id
        assert result.signature_meaning == "I attest this data is accurate."
        assert len(result.data_hash) == 64
        assert result.status == SignatureStatus.valid
        assert result.signed_at.tzinfo == UTC
        assert form.status == FormInstanceStatus.signed
        audit.record.assert_awaited_once()
        audit_kwargs = audit.record.call_args.kwargs
        assert audit_kwargs["action"] == "sign"
        assert audit_kwargs["entity_type"] == "signature"
        assert audit_kwargs["actor_id"] == actor.id
        assert result.data_hash in audit_kwargs["new_value"]

    async def test_sign_accepts_credential_mapping(self, service, actor):
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        form = _form()

        with patch("app.services.signature_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.sign(
                session,
                form,
                "I attest.",
                {"user": actor, "password": "signature-password"},
            )

        assert result.signed_by == actor.id


class TestInvalidateIfChanged:
    async def test_changed_data_marks_valid_signature_stale_and_audits(
        self, service, actor
    ):
        form = _form()
        signature = Signature(
            id=uuid.uuid4(),
            object_type="form",
            object_id=form.id,
            signed_by=actor.id,
            signature_meaning="I attest.",
            data_hash=service.hash_snapshot({"weight": "71"}),
            status=SignatureStatus.valid,
        )
        session = AsyncMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(return_value=_result(all_items=[signature]))

        with patch("app.services.signature_service.audit_service") as audit:
            audit.record = AsyncMock()
            stale = await service.invalidate_if_changed(
                session,
                form,
                actor_id=actor,
                reason="Corrected transcription error",
            )

        assert stale == [signature]
        assert signature.status == SignatureStatus.stale
        assert signature.stale_reason == "Corrected transcription error"
        audit.record.assert_awaited_once()
        audit_kwargs = audit.record.call_args.kwargs
        assert audit_kwargs["action"] == "invalidate"
        assert audit_kwargs["field_name"] == "status"
        assert audit_kwargs["old_value"] == "valid"
        assert audit_kwargs["new_value"] == "stale"
        assert audit_kwargs["reason"] == "Corrected transcription error"

    async def test_unchanged_data_is_idempotent(self, service, actor):
        form = _form()
        signature = Signature(
            id=uuid.uuid4(),
            object_type="form",
            object_id=form.id,
            signed_by=actor.id,
            signature_meaning="I attest.",
            data_hash=service.hash_snapshot(form.data_jsonb),
            status=SignatureStatus.valid,
        )
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result(all_items=[signature]))

        with patch("app.services.signature_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.invalidate_if_changed(session, form, actor)

        assert result == []
        assert signature.status == SignatureStatus.valid
        audit.record.assert_not_awaited()
        session.flush.assert_not_awaited()


class TestDataCaptureSignatureIntegration:
    async def test_signed_form_change_invalidates_signature(self, actor):
        form = _form(status=FormInstanceStatus.signed)
        field_id = uuid.uuid4()
        existing = FieldValue(
            id=uuid.uuid4(),
            form_instance_id=form.id,
            field_definition_id=field_id,
            value="old",
            is_not_applicable=False,
            created_at=datetime.now(UTC),
        )
        lookup = _result(first=existing)
        sync = _result(all_items=[existing])
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(side_effect=[lookup, sync])

        with (
            patch(
                "app.services.data_capture_service.lock_service.is_modification_blocked",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.services.data_capture_service.audit_service") as audit,
            patch.object(signature_service, "invalidate_if_changed", new_callable=AsyncMock) as invalidate,
        ):
            audit.record = AsyncMock()
            result = await DataCaptureService().change_value(
                session,
                form,
                field_id,
                "new",
                "Corrected transcription error",
                actor.id,
            )

        assert result is form
        invalidate.assert_awaited_once_with(
            session,
            form,
            actor_id=actor.id,
            reason="Corrected transcription error",
        )
