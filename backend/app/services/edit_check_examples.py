"""Seeded declarative edit-check examples for a draft study version.

The examples are data-only JSON DSL rules.  They describe the failure condition
that should be reported by the runtime engine, rather than executable code or
an implicit callback.  Seeding is idempotent for a version and follows the
same caller-owned transaction convention as the standard form seeder.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.edit_check import EditCheck
from app.models.study import StudyVersion
from app.services.edit_check_service import EditCheckService, edit_check_service
from app.services.study_version_service import study_version_service

logger = logging.getLogger(__name__)

# Each mapping is intentionally JSON-compatible and is validated by
# EditCheckService.create_edit_check before it is persisted.
EXAMPLE_EDIT_CHECKS: tuple[dict[str, Any], ...] = (
    {
        "name": "AE start date after end date",
        "description": "The adverse-event start date must be on or before the end date.",
        "rule_json": {
            "field": "AESTDAT",
            "operator": "after",
            "value_field": "AEENDAT",
        },
        "severity": "error",
    },
    {
        "name": "Informed consent after first procedure",
        "description": "The informed-consent date must be on or before the first procedure date.",
        "rule_json": {
            "field": "ICDAT",
            "operator": "after",
            "value_field": "PROCDAT",
        },
        "severity": "error",
    },
    {
        "name": "Serious AE missing seriousness criteria",
        "description": "A serious adverse event requires at least one seriousness criterion.",
        "rule_json": {
            "and": [
                {
                    "field": "AESER",
                    "operator": "in",
                    "value": [True, "Yes", "Y", "YES"],
                },
                {
                    "or": [
                        {"field": "AESCRIT", "operator": "is_null"},
                        {"field": "AESCRIT", "operator": "==", "value": ""},
                    ]
                },
            ]
        },
        "severity": "error",
    },
    {
        "name": "Fatal AE missing death date",
        "description": "A fatal adverse-event outcome requires a death date.",
        "rule_json": {
            "and": [
                {"field": "AEOUT", "operator": "==", "value": "Fatal"},
                {
                    "or": [
                        {"field": "DTHDAT", "operator": "is_null"},
                        {"field": "DTHDAT", "operator": "==", "value": ""},
                    ]
                },
            ]
        },
        "severity": "error",
    },
    {
        "name": "Visit date outside visit window",
        "description": "The visit date is outside the configured visit window.",
        "rule_json": {
            "or": [
                {
                    "field": "VISITDTC",
                    "operator": "before",
                    "value_field": "VISIT_WINDOW_START",
                },
                {
                    "field": "VISITDTC",
                    "operator": "after",
                    "value_field": "VISIT_WINDOW_END",
                },
            ]
        },
        "severity": "warning",
    },
)


async def seed_example_edit_checks(
    session: AsyncSession,
    version: StudyVersion,
    actor_id: UUID,
    *,
    service: EditCheckService | None = None,
) -> list[EditCheck]:
    """Seed the five standard edit-check examples into a draft version.

    The function is idempotent: if the target version already has any edit
    checks, it returns an empty list without adding duplicates.  The mutability
    guard is evaluated before the idempotency check so published versions can
    never be treated as writable, even when they already contain checks.
    The caller owns the transaction and must commit or roll back it.
    """
    study_version_service.guard_mutable(version)

    existing = await session.execute(
        select(EditCheck.id)
        .where(EditCheck.study_version_id == version.id)
        .limit(1)
    )
    if existing.scalars().first() is not None:
        logger.info(
            "Example edit checks already exist for version_id=%s — skipping seed.",
            version.id,
        )
        return []

    edit_check_engine = service or edit_check_service
    created: list[EditCheck] = []
    for definition in EXAMPLE_EDIT_CHECKS:
        created.append(
            await edit_check_engine.create_edit_check(
                session,
                version,
                definition,
                actor_id,
            )
        )

    logger.info(
        "Seeded %d example edit checks for version_id=%s actor=%s",
        len(created),
        version.id,
        actor_id,
    )
    return created


__all__ = ["EXAMPLE_EDIT_CHECKS", "seed_example_edit_checks"]
