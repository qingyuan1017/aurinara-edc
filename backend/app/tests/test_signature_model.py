"""Focused validation for the electronic signature model and migration."""

from datetime import UTC
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect

from app.models import Signature, SignatureObjectType, SignatureStatus


class TestSignatureModel:
    """Validate the persistence contract required before SignatureService work."""

    def test_signature_is_registered_and_has_required_columns(self):
        mapper = sa_inspect(Signature)
        assert Signature.__tablename__ == "signatures"
        assert {
            "id",
            "object_type",
            "object_id",
            "signed_by",
            "signed_at",
            "signature_meaning",
            "data_hash",
            "status",
            "stale_reason",
        } <= set(mapper.columns.keys())
        assert mapper.columns["id"].primary_key is True
        assert mapper.columns["signed_by"].nullable is False
        assert mapper.columns["signed_by"].foreign_keys
        assert next(iter(mapper.columns["signed_by"].foreign_keys)).target_fullname == "users.id"

    def test_signature_status_and_object_type_values(self):
        assert {member.value for member in SignatureStatus} == {"valid", "stale"}
        assert {member.value for member in SignatureObjectType} == {
            "field",
            "form",
            "visit",
            "subject",
            "site",
            "study",
        }

    def test_signature_timestamp_is_timezone_aware_utc_by_default(self):
        column = sa_inspect(Signature).columns["signed_at"]
        assert column.type.timezone is True
        assert column.default is not None
        timestamp = column.default.arg(None)
        assert timestamp.tzinfo == UTC

    def test_signature_defaults_to_valid_and_indexes_signed_object(self):
        column = sa_inspect(Signature).columns["status"]
        assert column.default is not None
        assert column.default.arg is SignatureStatus.valid
        index_names = {index.name for index in Signature.__table__.indexes}
        assert "ix_signatures_object_type_object_id" in index_names
        assert {"object_type", "object_id"} <= {
            column.name
            for index in Signature.__table__.indexes
            if index.name == "ix_signatures_object_type_object_id"
            for column in index.columns
        }

    def test_signature_can_represent_valid_and_stale_attestations(self):
        valid = Signature(
            object_type=SignatureObjectType.form,
            object_id=uuid4(),
            signed_by=uuid4(),
            signature_meaning="I attest that the form data is complete.",
            data_hash="a" * 64,
        )
        stale = Signature(
            object_type=SignatureObjectType.subject,
            object_id=uuid4(),
            signed_by=uuid4(),
            signature_meaning="I attest to the subject record.",
            data_hash="b" * 64,
            status=SignatureStatus.stale,
            stale_reason="Signed form data was corrected after attestation.",
        )
        assert valid.signature_meaning
        assert valid.data_hash == "a" * 64
        assert stale.status is SignatureStatus.stale
        assert stale.stale_reason == "Signed form data was corrected after attestation."


class TestSignatureMigration:
    """Validate migration coverage without requiring a live PostgreSQL server."""

    def test_migration_creates_required_columns_defaults_and_indexes(self):
        migration_path = (
            Path(__file__).parents[2] / "alembic" / "versions" / "0023_create_signatures.py"
        )
        source = migration_path.read_text()

        assert 'revision: str = "0023"' in source
        assert 'down_revision: str | None = "0022"' in source
        for column in (
            "object_type",
            "object_id",
            "signed_by",
            "signed_at",
            "signature_meaning",
            "data_hash",
            "status",
            "stale_reason",
        ):
            assert f'"{column}"' in source
        assert 'server_default=sa.text("now()")' in source
        assert "server_default=sa.text(\"'valid'\")" in source
        assert "sa.DateTime(timezone=True)" in source
        assert 'sa.ForeignKey("users.id", ondelete="RESTRICT")' in source
        for index in (
            "ix_signatures_object_type_object_id",
            "ix_signatures_signed_by",
            "ix_signatures_status",
            "ix_signatures_signed_at",
        ):
            assert index in source

    def test_migration_drops_indexes_before_table(self):
        migration_path = (
            Path(__file__).parents[2] / "alembic" / "versions" / "0023_create_signatures.py"
        )
        source = migration_path.read_text()
        downgrade = source.split("def downgrade() -> None:", maxsplit=1)[1]
        assert downgrade.index('op.drop_table("signatures")') > downgrade.index(
            'op.drop_index("ix_signatures_signed_at"'
        )
