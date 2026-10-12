"""Atomic orchestration for importing Designer definitions from JSON."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.codelist import Codelist
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.schemas.designer.bulk_import import (
    DesignerBulkImportRequest,
    DesignerBulkImportResponse,
)
from app.schemas.designer.form_metadata import (
    FieldDefinitionCreate,
    FormDefinitionCreate,
    FormSectionCreate,
)
from app.services.designer.codelist_service import codelist_service
from app.services.designer.edit_check_service import edit_check_service
from app.services.designer.form_metadata_service import form_metadata_service
from app.services.designer.study_version_service import study_version_service
from app.services.designer.visit_definition_service import visit_definition_service


class DesignerBulkImportService:
    """Create a portable set of Designer definitions in one transaction."""

    async def get_target_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        study_version_id: UUID | None = None,
    ) -> StudyVersion:
        if study_version_id is not None:
            version = await study_version_service.get_version(session, study_version_id)
            if version.study_id != study_id:
                raise NotFoundError(
                    "Study version not found",
                    details={
                        "study_id": str(study_id),
                        "study_version_id": str(study_version_id),
                    },
                )
        else:
            result = await session.execute(
                select(StudyVersion)
                .where(
                    StudyVersion.study_id == study_id,
                    StudyVersion.status == StudyVersionStatus.draft,
                )
                .order_by(StudyVersion.created_at.desc())
                .limit(1)
            )
            version = result.scalars().first()
            if version is None:
                raise NotFoundError(
                    "No draft study version found for this study",
                    details={"study_id": str(study_id)},
                )

        study_version_service.guard_mutable(version)
        return version

    async def import_definitions(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: DesignerBulkImportRequest,
        actor_id: UUID,
    ) -> DesignerBulkImportResponse:
        study_version_service.guard_mutable(version)
        self._validate_payload_uniqueness(data)

        existing_codelists = list(
            (await session.execute(select(Codelist).where(Codelist.study_version_id == version.id)))
            .scalars()
            .all()
        )
        codelists_by_code = self._index_codelists(existing_codelists)

        codelist_items_created = 0
        for item in data.codelists:
            if item.code in codelists_by_code:
                raise ConflictError(
                    "Codelist code already exists in this study version",
                    details={"code": item.code},
                )
            created = await codelist_service.create_codelist(session, version, item, actor_id)
            codelists_by_code[created.code] = created
            codelist_items_created += len(item.items)

        sections_created = 0
        fields_created = 0
        for imported_form in data.forms:
            form = await form_metadata_service.create_form(
                session,
                version,
                FormDefinitionCreate.model_validate(imported_form.model_dump(exclude={"sections"})),
                actor_id,
            )
            for imported_section in imported_form.sections:
                section = await form_metadata_service.create_section(
                    session,
                    version,
                    form,
                    FormSectionCreate.model_validate(
                        imported_section.model_dump(exclude={"fields"})
                    ),
                    actor_id,
                )
                sections_created += 1
                for imported_field in imported_section.fields:
                    field_payload = imported_field.model_dump(exclude={"codelist_code"})
                    if imported_field.codelist_code is not None:
                        codelist = codelists_by_code.get(imported_field.codelist_code)
                        if codelist is None:
                            raise ValidationError(
                                "Field references an unknown codelist code",
                                details={
                                    "codelist_code": imported_field.codelist_code,
                                    "variable_name": imported_field.variable_name,
                                },
                            )
                        field_payload["codelist_id"] = codelist.id
                    elif imported_field.codelist_id is not None:
                        referenced = next(
                            (
                                codelist
                                for codelist in codelists_by_code.values()
                                if codelist.id == imported_field.codelist_id
                            ),
                            None,
                        )
                        if referenced is None:
                            raise ValidationError(
                                "Field codelist_id must belong to the target study version",
                                details={
                                    "codelist_id": str(imported_field.codelist_id),
                                    "variable_name": imported_field.variable_name,
                                },
                            )
                    await form_metadata_service.create_field(
                        session,
                        version,
                        section,
                        FieldDefinitionCreate.model_validate(field_payload),
                        actor_id,
                    )
                    fields_created += 1

        for edit_check in data.edit_checks:
            await edit_check_service.create_edit_check(session, version, edit_check, actor_id)

        for visit in data.visits:
            await visit_definition_service.define_visit(session, version, visit, actor_id)

        return DesignerBulkImportResponse(
            study_id=version.study_id,
            study_version_id=version.id,
            forms_created=len(data.forms),
            sections_created=sections_created,
            fields_created=fields_created,
            edit_checks_created=len(data.edit_checks),
            codelists_created=len(data.codelists),
            codelist_items_created=codelist_items_created,
            visits_created=len(data.visits),
        )

    @staticmethod
    def _duplicates(values: list[str | int]) -> list[str]:
        return sorted(str(value) for value, count in Counter(values).items() if count > 1)

    def _validate_payload_uniqueness(self, data: DesignerBulkImportRequest) -> None:
        checks = {
            "codelist codes": self._duplicates([item.code for item in data.codelists]),
            "codelist names": self._duplicates([item.name.strip() for item in data.codelists]),
            "form codes": self._duplicates([item.form_code for item in data.forms]),
            "edit-check names": self._duplicates([item.name for item in data.edit_checks]),
            "visit numbers": self._duplicates(
                [item.visit_number for item in data.visits if item.visit_number is not None]
            ),
        }
        for label, duplicates in checks.items():
            if duplicates:
                raise ValidationError(
                    f"Import contains duplicate {label}",
                    details={"duplicates": duplicates},
                )

    def _index_codelists(self, codelists: list[Codelist]) -> dict[str, Codelist]:
        duplicates = self._duplicates([item.code for item in codelists])
        if duplicates:
            raise ConflictError(
                "Existing codelist codes are ambiguous in this study version",
                details={"duplicates": duplicates},
            )
        return {item.code: item for item in codelists}


designer_bulk_import_service = DesignerBulkImportService()

__all__ = ["DesignerBulkImportService", "designer_bulk_import_service"]
