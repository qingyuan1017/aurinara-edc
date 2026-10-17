"""Monotonic clinical-data revision propagation."""

from __future__ import annotations

from app.models.edc.form_data import FieldValue, FormInstance


class ClinicalRevisionService:
    @staticmethod
    def bump_visit(visit) -> int:
        visit.data_revision = int(visit.data_revision or 0) + 1
        subject = getattr(visit, "subject", None)
        if subject is not None:
            subject.data_revision = int(subject.data_revision or 0) + 1
        return visit.data_revision

    @staticmethod
    def bump_form(
        form_instance: FormInstance,
        *,
        field_value: FieldValue | None = None,
    ) -> int:
        if field_value is not None:
            field_value.data_revision = int(field_value.data_revision or 0) + 1
        form_instance.data_revision = int(form_instance.data_revision or 0) + 1
        visit = getattr(form_instance, "visit_instance", None)
        if visit is not None:
            visit.data_revision = int(visit.data_revision or 0) + 1
        subject = getattr(form_instance, "subject", None)
        if subject is not None:
            subject.data_revision = int(subject.data_revision or 0) + 1
        return form_instance.data_revision


clinical_revision_service = ClinicalRevisionService()

__all__ = ["ClinicalRevisionService", "clinical_revision_service"]
