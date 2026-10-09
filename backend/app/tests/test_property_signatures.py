"""Property-based tests for re-authenticated electronic signatures.

# Feature: clinical-edc-system, Property 30: Signatures require re-authentication and bind to signed data
**Validates: Requirements 17.1, 17.2, 17.3**

The property exercises the real SignatureService against a transactional SQLite
schema. Audit writes and the password verifier are isolated at their service
boundaries so the test focuses on the signature lifecycle: failed
re-authentication cannot persist a signature, successful signatures bind to the
canonical signed-data hash, and changed data stales the retained signature with
a reason.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import AuthenticationError
from app.models.edc.form_data import FormInstance, FormInstanceStatus
from app.models.edc.form_metadata import FormDefinition
from app.models.edc.signature import Signature, SignatureObjectType, SignatureStatus
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.shared.identity import User, UserStatus
from app.services.edc.signature_service import SignatureService

# Keep generated snapshots JSON-compatible while varying both structure and values.
json_scalar_strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100_000, max_value=100_000),
    st.text(
        alphabet=st.characters(categories=("L", "N", "P", "Zs")),
        max_size=80,
    ),
)
field_name_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Pc")),
    min_size=1,
    max_size=24,
).filter(lambda name: name != "__changed__")
signed_data_strategy = st.dictionaries(
    keys=field_name_strategy,
    values=json_scalar_strategy,
    min_size=1,
    max_size=8,
)


@pytest.fixture
async def session_factory():
    """Create a portable schema for each Hypothesis test invocation."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


class TestSignatureProperties:
    """Hypothesis coverage for Property 30."""

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(signed_data=signed_data_strategy)
    @pytest.mark.asyncio
    async def test_signatures_require_reauth_bind_hash_and_stale_on_data_change(
        self,
        session_factory,
        signed_data: dict[str, object],
    ) -> None:
        """Any signed snapshot follows the required signature lifecycle.

        **Validates: Requirements 17.1, 17.2, 17.3**
        """
        actor = User(
            id=uuid.uuid4(),
            email=f"signature-{uuid.uuid4().hex}@example.test",
            password_hash="stored-password-hash",
            first_name="Signature",
            last_name="Tester",
            status=UserStatus.active,
        )
        object_id = uuid.uuid4()
        changed_data = {**signed_data, "__changed__": True}
        service = SignatureService()

        async with session_factory() as session:
            session.add(actor)
            await session.flush()

            # Seed the owning operational chain so the SignatureService can
            # resolve the published-design binding (design_version_id) for the
            # signed form object. The FormInstance id IS the signed object_id.
            study = Study(
                id=uuid.uuid4(),
                study_code=f"SIG-{uuid.uuid4().hex[:8]}",
                title="Signature Study",
                status=StudyStatus.active,
                created_by=actor.id,
            )
            version = StudyVersion(
                id=uuid.uuid4(),
                study_id=study.id,
                version_number="1.0",
                status=StudyVersionStatus.published.value,
                published_by=actor.id,
            )
            site = Site(
                id=uuid.uuid4(),
                study_id=study.id,
                site_number=f"{uuid.uuid4().int % 100000:05d}",
                name="Signature Site",
                status=SiteStatus.active,
            )
            form_definition = FormDefinition(
                id=uuid.uuid4(),
                study_version_id=version.id,
                name="Signed Form",
                form_code="SIG",
                display_order=1,
            )
            subject = Subject(
                id=uuid.uuid4(),
                study_id=study.id,
                site_id=site.id,
                study_version_id=version.id,
                subject_number=f"S-{uuid.uuid4().hex[:8]}",
                status=SubjectStatus.enrolled,
                created_by=actor.id,
            )
            form_instance = FormInstance(
                id=object_id,
                subject_id=subject.id,
                form_definition_id=form_definition.id,
                design_version_id=version.id,
                status=FormInstanceStatus.submitted,
            )
            session.add_all(
                [study, version, site, form_definition, subject, form_instance]
            )
            await session.flush()

            # The verifier is called by the real service for both attempts; its
            # outcomes make the no-write-before-re-auth invariant deterministic.
            with (
                patch(
                    "app.services.edc.signature_service.verify_re_auth",
                    side_effect=[False, True],
                ) as verify_re_auth,
                patch(
                    "app.services.edc.signature_service.audit_service.record",
                    new_callable=AsyncMock,
                ),
            ):
                with pytest.raises(AuthenticationError):
                    await service.sign(
                        session,
                        object_id,
                        "Investigator attestation",
                        credentials="wrong-password",
                        actor_id=actor,
                        object_type=SignatureObjectType.form,
                        signed_data=signed_data,
                    )

                persisted_after_failure = await session.scalar(
                    select(Signature.id).where(Signature.object_id == object_id)
                )
                assert persisted_after_failure is None

                signature = await service.sign(
                    session,
                    object_id,
                    "Investigator attestation",
                    credentials="correct-password",
                    actor_id=actor,
                    object_type=SignatureObjectType.form,
                    signed_data=signed_data,
                )

                assert verify_re_auth.call_count == 2
                assert signature.signed_by == actor.id
                assert signature.object_type == SignatureObjectType.form.value
                assert signature.object_id == object_id
                assert signature.signature_meaning == "Investigator attestation"
                assert signature.status == SignatureStatus.valid
                assert signature.stale_reason is None
                assert signature.data_hash == service.hash_snapshot(signed_data)

                invalidated = await service.invalidate_if_changed(
                    session,
                    object_id,
                    actor_id=actor.id,
                    object_type=SignatureObjectType.form,
                    signed_data=changed_data,
                    reason="Clinical data changed after attestation.",
                )

            assert invalidated == [signature]
            assert signature.status == SignatureStatus.stale
            assert signature.stale_reason == "Clinical data changed after attestation."
            assert signature.data_hash != service.hash_snapshot(changed_data)
