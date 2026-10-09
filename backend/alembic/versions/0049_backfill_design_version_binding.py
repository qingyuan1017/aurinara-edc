"""Backfill design_version_id on operational tables from the subject's binding.

Revision ID: 0049
Revises: 0048

Part of the Designer / EDC refactor (Phase 3). Migration 0048 added NULLABLE
``design_version_id`` columns to nine operational tables. This migration
backfills those columns so a follow-up migration (0050) can enforce not-null.

Binding source (R2.7, R7.3): a Subject is bound to exactly one published design
through its existing not-null ``subjects.study_version_id``. Every operational
record is traced back to its owning Subject and inherits that Subject's bound
design version. Records that cannot be traced to a Subject (polymorphic rows
scoped to a site/study, or orphaned/study-only queries) fall back to the
study's *current published version* — the published ``study_versions`` row for
that study with the most recent ``published_at`` (ties broken by ``id``).

All backfill statements are ``UPDATE ... FROM ...`` joins executed in SQL for
correctness and performance; no Python row loops are used. The backfill only
writes the previously-NULL ``design_version_id`` column — no other stored value
on any table is read-modified-written, satisfying R11.2 (stored values of
existing columns are unchanged).

The polymorphic tables (``sdv_status``, ``freezes_locks``, ``signatures``) carry
a ``scope_type``/``object_type`` discriminator and a bare id. They are resolved
to a Subject along every scope that has a Subject path (field -> form_instance,
form -> form_instance, visit -> visit_instance, subject -> subject directly),
and the site/study scopes fall back to the study's current published version.

Requirements:
  - 11.2: Reassign operational records without altering their stored values;
    binding columns are backfilled before not-null is enforced.
  - 2.7 / 7.3: Each Subject (and thus each of its operational records) binds to
    exactly one published design version.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A reusable scalar subquery selecting a study's current published design
# version: the published study_versions row with the latest published_at
# (NULL published_at sorts last), ties broken deterministically by id.
_CURRENT_PUBLISHED_FOR_STUDY = """
    SELECT sv.id
    FROM study_versions sv
    WHERE sv.study_id = {study_col}
      AND sv.status = 'published'
    ORDER BY sv.published_at DESC NULLS LAST, sv.id DESC
    LIMIT 1
"""


def _subject_backfill_statements() -> list[str]:
    """UPDATE ... FROM joins binding each table to subjects.study_version_id.

    Only rows still NULL are touched, and only the design_version_id column is
    written.
    """
    return [
        # visit_instances.subject_id -> subjects.study_version_id
        """
        UPDATE visit_instances AS vi
        SET design_version_id = s.study_version_id
        FROM subjects AS s
        WHERE vi.subject_id = s.id
          AND vi.design_version_id IS NULL
        """,
        # form_instances.subject_id -> subjects.study_version_id
        """
        UPDATE form_instances AS fi
        SET design_version_id = s.study_version_id
        FROM subjects AS s
        WHERE fi.subject_id = s.id
          AND fi.design_version_id IS NULL
        """,
        # form_records -> form_instances.subject_id -> subjects
        """
        UPDATE form_records AS fr
        SET design_version_id = s.study_version_id
        FROM form_instances AS fi
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE fr.form_instance_id = fi.id
          AND fr.design_version_id IS NULL
        """,
        # field_values -> form_instances.subject_id -> subjects
        """
        UPDATE field_values AS fv
        SET design_version_id = s.study_version_id
        FROM form_instances AS fi
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE fv.form_instance_id = fi.id
          AND fv.design_version_id IS NULL
        """,
        # review_status -> form_instances.subject_id -> subjects
        """
        UPDATE review_status AS rs
        SET design_version_id = s.study_version_id
        FROM form_instances AS fi
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE rs.form_instance_id = fi.id
          AND rs.design_version_id IS NULL
        """,
        # queries.subject_id -> subjects (subject_id is nullable; NULLs handled
        # by the study-fallback pass below)
        """
        UPDATE queries AS q
        SET design_version_id = s.study_version_id
        FROM subjects AS s
        WHERE q.subject_id = s.id
          AND q.design_version_id IS NULL
        """,
        # sdv_status (scope_type/scope_id) -> subject, per scope level
        #   field   -> field_values -> form_instances -> subjects
        """
        UPDATE sdv_status AS sdv
        SET design_version_id = s.study_version_id
        FROM field_values AS fv
        JOIN form_instances AS fi ON fi.id = fv.form_instance_id
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE sdv.scope_type = 'field'
          AND sdv.scope_id = fv.id
          AND sdv.design_version_id IS NULL
        """,
        #   form    -> form_instances -> subjects
        """
        UPDATE sdv_status AS sdv
        SET design_version_id = s.study_version_id
        FROM form_instances AS fi
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE sdv.scope_type = 'form'
          AND sdv.scope_id = fi.id
          AND sdv.design_version_id IS NULL
        """,
        #   visit   -> visit_instances -> subjects
        """
        UPDATE sdv_status AS sdv
        SET design_version_id = s.study_version_id
        FROM visit_instances AS vi
        JOIN subjects AS s ON s.id = vi.subject_id
        WHERE sdv.scope_type = 'visit'
          AND sdv.scope_id = vi.id
          AND sdv.design_version_id IS NULL
        """,
        #   subject -> subjects directly
        """
        UPDATE sdv_status AS sdv
        SET design_version_id = s.study_version_id
        FROM subjects AS s
        WHERE sdv.scope_type = 'subject'
          AND sdv.scope_id = s.id
          AND sdv.design_version_id IS NULL
        """,
        # freezes_locks (object_type/object_id) -> subject, per object level
        #   field   -> field_values -> form_instances -> subjects
        """
        UPDATE freezes_locks AS fl
        SET design_version_id = s.study_version_id
        FROM field_values AS fv
        JOIN form_instances AS fi ON fi.id = fv.form_instance_id
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE fl.object_type = 'field'
          AND fl.object_id = fv.id
          AND fl.design_version_id IS NULL
        """,
        #   form    -> form_instances -> subjects
        """
        UPDATE freezes_locks AS fl
        SET design_version_id = s.study_version_id
        FROM form_instances AS fi
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE fl.object_type = 'form'
          AND fl.object_id = fi.id
          AND fl.design_version_id IS NULL
        """,
        #   visit   -> visit_instances -> subjects
        """
        UPDATE freezes_locks AS fl
        SET design_version_id = s.study_version_id
        FROM visit_instances AS vi
        JOIN subjects AS s ON s.id = vi.subject_id
        WHERE fl.object_type = 'visit'
          AND fl.object_id = vi.id
          AND fl.design_version_id IS NULL
        """,
        #   subject -> subjects directly
        """
        UPDATE freezes_locks AS fl
        SET design_version_id = s.study_version_id
        FROM subjects AS s
        WHERE fl.object_type = 'subject'
          AND fl.object_id = s.id
          AND fl.design_version_id IS NULL
        """,
        # signatures (object_type/object_id) -> subject, per object level
        #   field   -> field_values -> form_instances -> subjects
        """
        UPDATE signatures AS sig
        SET design_version_id = s.study_version_id
        FROM field_values AS fv
        JOIN form_instances AS fi ON fi.id = fv.form_instance_id
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE sig.object_type = 'field'
          AND sig.object_id = fv.id
          AND sig.design_version_id IS NULL
        """,
        #   form    -> form_instances -> subjects
        """
        UPDATE signatures AS sig
        SET design_version_id = s.study_version_id
        FROM form_instances AS fi
        JOIN subjects AS s ON s.id = fi.subject_id
        WHERE sig.object_type = 'form'
          AND sig.object_id = fi.id
          AND sig.design_version_id IS NULL
        """,
        #   visit   -> visit_instances -> subjects
        """
        UPDATE signatures AS sig
        SET design_version_id = s.study_version_id
        FROM visit_instances AS vi
        JOIN subjects AS s ON s.id = vi.subject_id
        WHERE sig.object_type = 'visit'
          AND sig.object_id = vi.id
          AND sig.design_version_id IS NULL
        """,
        #   subject -> subjects directly
        """
        UPDATE signatures AS sig
        SET design_version_id = s.study_version_id
        FROM subjects AS s
        WHERE sig.object_type = 'subject'
          AND sig.object_id = s.id
          AND sig.design_version_id IS NULL
        """,
    ]


def _study_fallback_statements() -> list[str]:
    """Fallback: rows not traced to a Subject bind to the study's current
    published version.

    Only ``queries`` carries a direct ``study_id`` and so can be resolved to a
    study for rows whose ``subject_id`` is NULL (or whose subject was
    soft-deleted). Polymorphic site/study-scoped rows have no stored study path
    on their own table, so they are resolved via a global single-study fallback
    only when the deployment has exactly one study (the common single-study
    case); otherwise they are left for the not-null guard to surface, which is
    the intended best-effort behavior for untraceable edge cases.
    """
    return [
        # queries with no subject path -> study's current published version
        f"""
        UPDATE queries AS q
        SET design_version_id = (
            {_CURRENT_PUBLISHED_FOR_STUDY.format(study_col="q.study_id")}
        )
        WHERE q.design_version_id IS NULL
          AND EXISTS (
            SELECT 1 FROM study_versions sv2
            WHERE sv2.study_id = q.study_id AND sv2.status = 'published'
          )
        """,
        # Any remaining polymorphic rows (site/study scope) when the deployment
        # has a single study: bind to that study's current published version.
        """
        UPDATE sdv_status AS sdv
        SET design_version_id = (
            SELECT sv.id FROM study_versions sv
            WHERE sv.status = 'published'
            ORDER BY sv.published_at DESC NULLS LAST, sv.id DESC
            LIMIT 1
        )
        WHERE sdv.design_version_id IS NULL
          AND (SELECT COUNT(DISTINCT s.study_id) FROM subjects s) <= 1
          AND EXISTS (SELECT 1 FROM study_versions sv WHERE sv.status = 'published')
        """,
        """
        UPDATE freezes_locks AS fl
        SET design_version_id = (
            SELECT sv.id FROM study_versions sv
            WHERE sv.status = 'published'
            ORDER BY sv.published_at DESC NULLS LAST, sv.id DESC
            LIMIT 1
        )
        WHERE fl.design_version_id IS NULL
          AND (SELECT COUNT(DISTINCT s.study_id) FROM subjects s) <= 1
          AND EXISTS (SELECT 1 FROM study_versions sv WHERE sv.status = 'published')
        """,
        """
        UPDATE signatures AS sig
        SET design_version_id = (
            SELECT sv.id FROM study_versions sv
            WHERE sv.status = 'published'
            ORDER BY sv.published_at DESC NULLS LAST, sv.id DESC
            LIMIT 1
        )
        WHERE sig.design_version_id IS NULL
          AND (SELECT COUNT(DISTINCT s.study_id) FROM subjects s) <= 1
          AND EXISTS (SELECT 1 FROM study_versions sv WHERE sv.status = 'published')
        """,
    ]


# Tables backfilled by this migration; downgrade resets their column to NULL.
_BACKFILLED_TABLES: tuple[str, ...] = (
    "visit_instances",
    "form_instances",
    "form_records",
    "field_values",
    "queries",
    "sdv_status",
    "review_status",
    "freezes_locks",
    "signatures",
)


def upgrade() -> None:
    # Pass 1: bind every record reachable from its owning Subject (correct
    # join; preferred).
    for statement in _subject_backfill_statements():
        op.execute(sa.text(statement))
    # Pass 2: fall back to the study's current published version for rows that
    # could not be traced to a Subject.
    for statement in _study_fallback_statements():
        op.execute(sa.text(statement))


def downgrade() -> None:
    # Reverse the backfill by clearing the binding column back to NULL. This
    # restores the post-0048 state (nullable column, no values) without
    # touching any other stored value.
    for table in _BACKFILLED_TABLES:
        op.execute(sa.text(f"UPDATE {table} SET design_version_id = NULL"))
