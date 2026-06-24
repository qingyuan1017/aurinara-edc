"""Form_Metadata_Service — eCRF form/section/field/codelist metadata management.

Manages eCRF metadata within a Study_Version. Form versioning is achieved
through the ``study_version_id`` relationship on ``form_definitions`` — there is
**no separate ``form_versions`` table**; a form's version is the version of its
owning Study_Version.

All metadata mutations are allowed **only while the owning Study_Version is in
draft** (enforced via ``study_version_service.guard_mutable``) and every mutation
writes an Audit_Event within the caller's transaction (data + audit commit
atomically).

Satisfies Requirements:
  - 5.2: Reject modifications to a published version and its child forms/fields/
          code lists (via guard_mutable).
  - 9.1: Create, edit, and order form definitions while the owning version is draft.
  - 9.2: Create and order sections and fields within a form definition.
  - 9.3: Support all field control types.
  - 9.4: Support all field attributes.
  - 9.5: Support code lists and code list items referenced by fields.
  - 9.6: Write an Audit_Event when form metadata changes.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import NotFoundError, ValidationError
from app.models.form_metadata import (
    Codelist,
    CodelistItem,
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.study import StudyVersion
from app.schemas.form_metadata import (
    CodelistCreate,
    CodelistItemCreate,
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FormDefinitionCreate,
    FormDefinitionUpdate,
    FormSectionCreate,
    FormSectionUpdate,
)
from app.services.study_version_service import study_version_service

logger = logging.getLogger(__name__)


class FormMetadataService:
    """Manages eCRF metadata (forms, sections, fields, code lists) for a version."""

    # ==================================================================
    # Form definitions (Requirement 9.1)
    # ==================================================================

    async def create_form(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: FormDefinitionCreate,
        actor_id: UUID,
    ) -> FormDefinition:
        """Create a form definition on a draft Study_Version (Req 9.1, 5.2).

        Args:
            session: Active async session (caller's transaction).
            version: The owning StudyVersion (must be draft).
            data: Validated FormDefinitionCreate schema.
            actor_id: UUID of the acting user.

        Returns:
            The created FormDefinition.

        Raises:
            BusinessRuleError: If the owning version is published (Req 5.2).
        """
        study_version_service.guard_mutable(version)

        form = FormDefinition(
            study_version_id=version.id,
            name=data.name,
            form_code=data.form_code,
            display_order=data.display_order,
            is_repeating=data.is_repeating,
        )
        session.add(form)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_definition",
            entity_id=form.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"name={form.name}, form_code={form.form_code}",
        )

        logger.info(
            "Form definition created: id=%s version_id=%s form_code=%s actor=%s",
            form.id,
            version.id,
            form.form_code,
            actor_id,
        )
        return form

    async def update_form(
        self,
        session: AsyncSession,
        version: StudyVersion,
        form: FormDefinition,
        data: FormDefinitionUpdate,
        actor_id: UUID,
    ) -> FormDefinition:
        """Edit a form definition on a draft Study_Version (Req 9.1, 5.2)."""
        study_version_service.guard_mutable(version)

        changes = data.model_dump(exclude_unset=True)
        old_values = {key: getattr(form, key) for key in changes}
        for key, value in changes.items():
            setattr(form, key, value)

        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_definition",
            entity_id=form.id,
            action="update",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=str(old_values),
            new_value=str(changes),
        )

        logger.info(
            "Form definition updated: id=%s version_id=%s actor=%s",
            form.id,
            version.id,
            actor_id,
        )
        return form

    async def delete_form(
        self,
        session: AsyncSession,
        version: StudyVersion,
        form: FormDefinition,
        actor_id: UUID,
    ) -> None:
        """Delete a form definition from a draft Study_Version (Req 9.1, 5.2)."""
        study_version_service.guard_mutable(version)

        form_id = form.id
        await session.delete(form)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_definition",
            entity_id=form_id,
            action="delete",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=f"name={form.name}, form_code={form.form_code}",
        )

        logger.info(
            "Form definition deleted: id=%s version_id=%s actor=%s",
            form_id,
            version.id,
            actor_id,
        )

    async def reorder_forms(
        self,
        session: AsyncSession,
        version: StudyVersion,
        ordered_ids: list[UUID],
        actor_id: UUID,
    ) -> list[FormDefinition]:
        """Reorder a version's form definitions by id (Req 9.1, 5.2).

        The position of each id in ``ordered_ids`` becomes its display_order.

        Raises:
            BusinessRuleError: If the version is published (Req 5.2).
            ValidationError: If ``ordered_ids`` does not match the version's forms.
        """
        study_version_service.guard_mutable(version)

        forms = await self.list_forms(session, version.id)
        forms_by_id = {form.id: form for form in forms}

        if set(ordered_ids) != set(forms_by_id) or len(ordered_ids) != len(forms):
            raise ValidationError(
                "ordered_ids must contain exactly the version's form ids",
                details={"version_id": str(version.id)},
            )

        for display_order, form_id in enumerate(ordered_ids):
            forms_by_id[form_id].display_order = display_order

        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_definition",
            entity_id=version.id,
            action="reorder",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=",".join(str(fid) for fid in ordered_ids),
        )

        logger.info(
            "Form definitions reordered: version_id=%s count=%d actor=%s",
            version.id,
            len(ordered_ids),
            actor_id,
        )
        return [forms_by_id[fid] for fid in ordered_ids]

    # ==================================================================
    # Sections (Requirement 9.2)
    # ==================================================================

    async def create_section(
        self,
        session: AsyncSession,
        version: StudyVersion,
        form: FormDefinition,
        data: FormSectionCreate,
        actor_id: UUID,
    ) -> FormSection:
        """Create a section within a form on a draft version (Req 9.2, 5.2)."""
        study_version_service.guard_mutable(version)

        section = FormSection(
            form_definition_id=form.id,
            name=data.name,
            display_order=data.display_order,
        )
        session.add(section)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_section",
            entity_id=section.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"name={section.name}, form_definition_id={form.id}",
        )

        logger.info(
            "Form section created: id=%s form_id=%s actor=%s",
            section.id,
            form.id,
            actor_id,
        )
        return section

    async def update_section(
        self,
        session: AsyncSession,
        version: StudyVersion,
        section: FormSection,
        data: FormSectionUpdate,
        actor_id: UUID,
    ) -> FormSection:
        """Edit a section on a draft version (Req 9.2, 5.2)."""
        study_version_service.guard_mutable(version)

        changes = data.model_dump(exclude_unset=True)
        old_values = {key: getattr(section, key) for key in changes}
        for key, value in changes.items():
            setattr(section, key, value)

        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_section",
            entity_id=section.id,
            action="update",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=str(old_values),
            new_value=str(changes),
        )

        logger.info(
            "Form section updated: id=%s actor=%s", section.id, actor_id
        )
        return section

    async def reorder_sections(
        self,
        session: AsyncSession,
        version: StudyVersion,
        form: FormDefinition,
        ordered_ids: list[UUID],
        actor_id: UUID,
    ) -> list[FormSection]:
        """Reorder a form's sections by id (Req 9.2, 5.2)."""
        study_version_service.guard_mutable(version)

        sections = await self.list_sections(session, form.id)
        sections_by_id = {section.id: section for section in sections}

        if set(ordered_ids) != set(sections_by_id) or len(ordered_ids) != len(sections):
            raise ValidationError(
                "ordered_ids must contain exactly the form's section ids",
                details={"form_definition_id": str(form.id)},
            )

        for display_order, section_id in enumerate(ordered_ids):
            sections_by_id[section_id].display_order = display_order

        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_section",
            entity_id=form.id,
            action="reorder",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=",".join(str(sid) for sid in ordered_ids),
        )

        logger.info(
            "Form sections reordered: form_id=%s count=%d actor=%s",
            form.id,
            len(ordered_ids),
            actor_id,
        )
        return [sections_by_id[sid] for sid in ordered_ids]

    # ==================================================================
    # Fields (Requirements 9.2, 9.3, 9.4)
    # ==================================================================

    async def create_field(
        self,
        session: AsyncSession,
        version: StudyVersion,
        section: FormSection,
        data: FieldDefinitionCreate,
        actor_id: UUID,
    ) -> FieldDefinition:
        """Create a field within a section on a draft version (Req 9.2-9.4, 5.2).

        Supports every control type (Req 9.3) and field attribute (Req 9.4).
        """
        study_version_service.guard_mutable(version)

        field = FieldDefinition(
            form_section_id=section.id,
            label=data.label,
            variable_name=data.variable_name,
            control_type=str(data.control_type),
            data_type=data.data_type,
            is_required=data.is_required,
            codelist_id=data.codelist_id,
            default_value=data.default_value,
            help_text=data.help_text,
            unit=data.unit,
            min_value=data.min_value,
            max_value=data.max_value,
            max_length=data.max_length,
            decimal_precision=data.decimal_precision,
            regex_validation=data.regex_validation,
            visibility_rule=data.visibility_rule,
            is_read_only=data.is_read_only,
            is_calculated=data.is_calculated,
            calculation_expression=data.calculation_expression,
            display_order=data.display_order,
        )
        session.add(field)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="field_definition",
            entity_id=field.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=(
                f"variable_name={field.variable_name}, "
                f"control_type={field.control_type}"
            ),
        )

        logger.info(
            "Field definition created: id=%s section_id=%s variable_name=%s actor=%s",
            field.id,
            section.id,
            field.variable_name,
            actor_id,
        )
        return field

    async def update_field(
        self,
        session: AsyncSession,
        version: StudyVersion,
        field: FieldDefinition,
        data: FieldDefinitionUpdate,
        actor_id: UUID,
    ) -> FieldDefinition:
        """Edit a field on a draft version (Req 9.3, 9.4, 5.2)."""
        study_version_service.guard_mutable(version)

        changes = data.model_dump(exclude_unset=True)
        if "control_type" in changes and changes["control_type"] is not None:
            changes["control_type"] = str(changes["control_type"])

        old_values = {key: getattr(field, key) for key in changes}
        for key, value in changes.items():
            setattr(field, key, value)

        await session.flush()

        await audit_service.record(
            session,
            entity_type="field_definition",
            entity_id=field.id,
            action="update",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=str(old_values),
            new_value=str(changes),
        )

        logger.info(
            "Field definition updated: id=%s actor=%s", field.id, actor_id
        )
        return field

    async def delete_field(
        self,
        session: AsyncSession,
        version: StudyVersion,
        field: FieldDefinition,
        actor_id: UUID,
    ) -> None:
        """Delete a field from a draft version (Req 9.2, 5.2)."""
        study_version_service.guard_mutable(version)

        field_id = field.id
        variable_name = field.variable_name
        await session.delete(field)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="field_definition",
            entity_id=field_id,
            action="delete",
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=f"variable_name={variable_name}",
        )

        logger.info(
            "Field definition deleted: id=%s actor=%s", field_id, actor_id
        )

    async def reorder_fields(
        self,
        session: AsyncSession,
        version: StudyVersion,
        section: FormSection,
        ordered_ids: list[UUID],
        actor_id: UUID,
    ) -> list[FieldDefinition]:
        """Reorder a section's fields by id (Req 9.2, 5.2)."""
        study_version_service.guard_mutable(version)

        fields = await self.list_fields(session, section.id)
        fields_by_id = {field.id: field for field in fields}

        if set(ordered_ids) != set(fields_by_id) or len(ordered_ids) != len(fields):
            raise ValidationError(
                "ordered_ids must contain exactly the section's field ids",
                details={"form_section_id": str(section.id)},
            )

        for display_order, field_id in enumerate(ordered_ids):
            fields_by_id[field_id].display_order = display_order

        await session.flush()

        await audit_service.record(
            session,
            entity_type="field_definition",
            entity_id=section.id,
            action="reorder",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=",".join(str(fid) for fid in ordered_ids),
        )

        logger.info(
            "Field definitions reordered: section_id=%s count=%d actor=%s",
            section.id,
            len(ordered_ids),
            actor_id,
        )
        return [fields_by_id[fid] for fid in ordered_ids]

    # ==================================================================
    # Code lists (Requirement 9.5)
    # ==================================================================

    async def create_codelist(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: CodelistCreate,
        actor_id: UUID,
    ) -> Codelist:
        """Create a code list (with optional initial items) on a draft version.

        Satisfies Requirements 9.5 and 5.2.
        """
        study_version_service.guard_mutable(version)

        codelist = Codelist(
            study_version_id=version.id,
            name=data.name,
            code=data.code,
        )
        session.add(codelist)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="codelist",
            entity_id=codelist.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"name={codelist.name}, code={codelist.code}",
        )

        for item_data in data.items:
            await self.add_codelist_item(
                session, version, codelist, item_data, actor_id
            )

        logger.info(
            "Codelist created: id=%s version_id=%s code=%s items=%d actor=%s",
            codelist.id,
            version.id,
            codelist.code,
            len(data.items),
            actor_id,
        )
        return codelist

    async def add_codelist_item(
        self,
        session: AsyncSession,
        version: StudyVersion,
        codelist: Codelist,
        data: CodelistItemCreate,
        actor_id: UUID,
    ) -> CodelistItem:
        """Add an item to a code list on a draft version (Req 9.5, 5.2)."""
        study_version_service.guard_mutable(version)

        item = CodelistItem(
            codelist_id=codelist.id,
            code=data.code,
            label=data.label,
            display_order=data.display_order,
            normal_low=data.normal_low,
            normal_high=data.normal_high,
        )
        session.add(item)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="codelist_item",
            entity_id=item.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"code={item.code}, label={item.label}",
        )

        logger.info(
            "Codelist item added: id=%s codelist_id=%s code=%s actor=%s",
            item.id,
            codelist.id,
            item.code,
            actor_id,
        )
        return item

    # ==================================================================
    # Getters
    # ==================================================================

    async def get_form(
        self, session: AsyncSession, form_id: UUID
    ) -> FormDefinition:
        """Retrieve a form definition by id, raising NotFoundError if missing."""
        result = await session.execute(
            select(FormDefinition).where(FormDefinition.id == form_id)
        )
        form = result.scalars().first()
        if form is None:
            raise NotFoundError(
                "Form definition not found",
                details={"form_definition_id": str(form_id)},
            )
        return form

    async def list_forms(
        self, session: AsyncSession, study_version_id: UUID
    ) -> list[FormDefinition]:
        """List a version's form definitions ordered by display_order."""
        result = await session.execute(
            select(FormDefinition)
            .where(FormDefinition.study_version_id == study_version_id)
            .order_by(FormDefinition.display_order)
        )
        return list(result.scalars().all())

    async def get_section(
        self, session: AsyncSession, section_id: UUID
    ) -> FormSection:
        """Retrieve a section by id, raising NotFoundError if missing."""
        result = await session.execute(
            select(FormSection).where(FormSection.id == section_id)
        )
        section = result.scalars().first()
        if section is None:
            raise NotFoundError(
                "Form section not found",
                details={"form_section_id": str(section_id)},
            )
        return section

    async def list_sections(
        self, session: AsyncSession, form_definition_id: UUID
    ) -> list[FormSection]:
        """List a form's sections ordered by display_order."""
        result = await session.execute(
            select(FormSection)
            .where(FormSection.form_definition_id == form_definition_id)
            .order_by(FormSection.display_order)
        )
        return list(result.scalars().all())

    async def get_field(
        self, session: AsyncSession, field_id: UUID
    ) -> FieldDefinition:
        """Retrieve a field by id, raising NotFoundError if missing."""
        result = await session.execute(
            select(FieldDefinition).where(FieldDefinition.id == field_id)
        )
        field = result.scalars().first()
        if field is None:
            raise NotFoundError(
                "Field definition not found",
                details={"field_definition_id": str(field_id)},
            )
        return field

    async def list_fields(
        self, session: AsyncSession, form_section_id: UUID
    ) -> list[FieldDefinition]:
        """List a section's fields ordered by display_order."""
        result = await session.execute(
            select(FieldDefinition)
            .where(FieldDefinition.form_section_id == form_section_id)
            .order_by(FieldDefinition.display_order)
        )
        return list(result.scalars().all())

    async def get_codelist(
        self, session: AsyncSession, codelist_id: UUID
    ) -> Codelist:
        """Retrieve a code list by id, raising NotFoundError if missing."""
        result = await session.execute(
            select(Codelist).where(Codelist.id == codelist_id)
        )
        codelist = result.scalars().first()
        if codelist is None:
            raise NotFoundError(
                "Codelist not found",
                details={"codelist_id": str(codelist_id)},
            )
        return codelist

    async def list_codelists(
        self, session: AsyncSession, study_version_id: UUID
    ) -> list[Codelist]:
        """List a version's code lists ordered by code."""
        result = await session.execute(
            select(Codelist)
            .where(Codelist.study_version_id == study_version_id)
            .order_by(Codelist.code)
        )
        return list(result.scalars().all())


# Module-level singleton for convenience
form_metadata_service = FormMetadataService()
