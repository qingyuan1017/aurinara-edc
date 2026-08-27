"""Standard eCRF form template seeding.

Seeds a draft Study_Version with the standard clinical trial form templates
(AE, CM, DM, MH, VS, LB, EX, DS, EG, Visit Date) including representative
sections and fields.

The seeder is idempotent — if form definitions already exist for the target
version it skips without error.

Satisfies Requirements:
  - 9.3: All field control types are represented across the standard templates.
  - 9.4: Field attributes (label, variable_name, data_type, is_required, unit,
          min/max values, help_text) are populated for representative fields.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.study import StudyVersion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

# Each template is a dict with form-level metadata and a list of sections,
# each section containing a list of field specs.
# Field specs: (variable_name, label, control_type, data_type, is_required, extra)
# where extra is an optional dict of additional FieldDefinition attrs.

_FieldSpec = tuple[str, str, str, str, bool, dict | None]
_SectionSpec = tuple[str, list[_FieldSpec]]
_FormSpec = tuple[str, str, bool, list[_SectionSpec]]

STANDARD_FORMS: list[_FormSpec] = [
    # --- AE (Adverse Events) — repeating ---
    (
        "Adverse Events",
        "AE",
        True,
        [
            (
                "Adverse Event Details",
                [
                    ("AETERM", "AE Term", "text", "string", True, None),
                    ("AESTDAT", "Start Date", "date", "date", True, None),
                    ("AEENDAT", "End Date", "date", "date", False, None),
                    (
                        "AESEV",
                        "Severity",
                        "dropdown",
                        "string",
                        True,
                        {"help_text": "Mild / Moderate / Severe"},
                    ),
                    ("AESER", "Serious", "boolean", "boolean", True, None),
                    (
                        "AEOUT",
                        "Outcome",
                        "dropdown",
                        "string",
                        True,
                        {"help_text": ("Recovered, Recovering, Not Recovered, Fatal, Unknown")},
                    ),
                    (
                        "AEREL",
                        "Relationship to Treatment",
                        "dropdown",
                        "string",
                        True,
                        {"help_text": "Related / Not Related / Possibly Related"},
                    ),
                    (
                        "AEACN",
                        "Action Taken",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": ("None, Dose Reduced, Drug Withdrawn, Other")},
                    ),
                ],
            ),
        ],
    ),
    # --- CM (Concomitant Medications) — repeating ---
    (
        "Concomitant Medications",
        "CM",
        True,
        [
            (
                "Medication Details",
                [
                    ("CMTRT", "Drug Name", "text", "string", True, None),
                    ("CMINDC", "Indication", "text", "string", True, None),
                    ("CMSTDAT", "Start Date", "date", "date", True, None),
                    ("CMENDAT", "End Date", "date", "date", False, None),
                    ("CMDOSE", "Dose", "decimal", "decimal", False, None),
                    (
                        "CMROUTE",
                        "Route",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": "Oral, IV, IM, SC, Topical, Other"},
                    ),
                    (
                        "CMDOSFRQ",
                        "Frequency",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": "QD, BID, TID, QID, PRN, Other"},
                    ),
                ],
            ),
        ],
    ),
    # --- DM (Demographics) — single ---
    (
        "Demographics",
        "DM",
        False,
        [
            (
                "Demographics",
                [
                    ("BRTHDTC", "Date of Birth", "date", "date", True, None),
                    (
                        "SEX",
                        "Sex",
                        "radio",
                        "string",
                        True,
                        {"help_text": "Male / Female / Other / Unknown"},
                    ),
                    (
                        "RACE",
                        "Race",
                        "dropdown",
                        "string",
                        True,
                        {
                            "help_text": (
                                "American Indian or Alaska Native, Asian, "
                                "Black or African American, Native Hawaiian "
                                "or Other Pacific Islander, White, Other"
                            )
                        },
                    ),
                    (
                        "ETHNIC",
                        "Ethnicity",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": ("Hispanic or Latino / Not Hispanic or Latino")},
                    ),
                    (
                        "HEIGHT",
                        "Height",
                        "decimal",
                        "decimal",
                        False,
                        {"unit": "cm", "min_value": 50, "max_value": 250},
                    ),
                    (
                        "WEIGHT",
                        "Weight",
                        "decimal",
                        "decimal",
                        False,
                        {"unit": "kg", "min_value": 20, "max_value": 300},
                    ),
                ],
            ),
        ],
    ),
    # --- MH (Medical History) — repeating ---
    (
        "Medical History",
        "MH",
        True,
        [
            (
                "Medical History Details",
                [
                    ("MHTERM", "Condition", "text", "string", True, None),
                    ("MHSTDAT", "Start Date", "date", "date", False, None),
                    (
                        "MHONGO",
                        "Ongoing",
                        "boolean",
                        "boolean",
                        True,
                        {"help_text": "Is the condition still ongoing?"},
                    ),
                    ("MHENDAT", "End Date", "date", "date", False, None),
                ],
            ),
        ],
    ),
    # --- VS (Vital Signs) — repeating ---
    (
        "Vital Signs",
        "VS",
        True,
        [
            (
                "Vital Signs Measurements",
                [
                    ("VSDTC", "Date/Time", "datetime", "datetime", True, None),
                    (
                        "SYSBP",
                        "Systolic BP",
                        "integer",
                        "integer",
                        True,
                        {"unit": "mmHg", "min_value": 60, "max_value": 260},
                    ),
                    (
                        "DIABP",
                        "Diastolic BP",
                        "integer",
                        "integer",
                        True,
                        {"unit": "mmHg", "min_value": 30, "max_value": 160},
                    ),
                    (
                        "HR",
                        "Heart Rate",
                        "integer",
                        "integer",
                        True,
                        {"unit": "bpm", "min_value": 30, "max_value": 220},
                    ),
                    (
                        "TEMP",
                        "Temperature",
                        "decimal",
                        "decimal",
                        True,
                        {
                            "unit": "°C",
                            "min_value": 34,
                            "max_value": 42,
                            "decimal_precision": 1,
                        },
                    ),
                    (
                        "RESP",
                        "Respiratory Rate",
                        "integer",
                        "integer",
                        False,
                        {"unit": "breaths/min", "min_value": 8, "max_value": 40},
                    ),
                    (
                        "VSWEIGHT",
                        "Weight",
                        "decimal",
                        "decimal",
                        False,
                        {"unit": "kg", "min_value": 20, "max_value": 300},
                    ),
                ],
            ),
        ],
    ),
    # --- LB (Laboratory) — repeating ---
    (
        "Laboratory",
        "LB",
        True,
        [
            (
                "Lab Results",
                [
                    ("LBTEST", "Test Name", "text", "string", True, None),
                    ("LBORRES", "Result", "text", "string", True, None),
                    ("LBORRESU", "Unit", "text", "string", False, None),
                    (
                        "LBORNRLO",
                        "Normal Low",
                        "decimal",
                        "decimal",
                        False,
                        None,
                    ),
                    (
                        "LBORNRHI",
                        "Normal High",
                        "decimal",
                        "decimal",
                        False,
                        None,
                    ),
                    (
                        "LBNRIND",
                        "Flag",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": "Normal / Low / High / Critical"},
                    ),
                ],
            ),
        ],
    ),
    # --- EX (Exposure) — repeating ---
    (
        "Exposure",
        "EX",
        True,
        [
            (
                "Drug Exposure Details",
                [
                    ("EXTRT", "Drug", "text", "string", True, None),
                    ("EXDOSE", "Dose", "decimal", "decimal", True, None),
                    ("EXDOSU", "Unit", "text", "string", True, None),
                    (
                        "EXDOSFRQ",
                        "Frequency",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": "QD, BID, TID, QID, PRN, Other"},
                    ),
                    (
                        "EXROUTE",
                        "Route",
                        "dropdown",
                        "string",
                        False,
                        {"help_text": "Oral, IV, IM, SC, Topical, Other"},
                    ),
                    ("EXSTDAT", "Start Date", "date", "date", True, None),
                    ("EXENDAT", "End Date", "date", "date", False, None),
                ],
            ),
        ],
    ),
    # --- DS (Disposition) — single ---
    (
        "Disposition",
        "DS",
        False,
        [
            (
                "Disposition Details",
                [
                    (
                        "DSDECOD",
                        "Disposition Event",
                        "dropdown",
                        "string",
                        True,
                        {
                            "help_text": (
                                "Completed, Withdrawn, Lost to Follow-up, Screen Failure, Other"
                            )
                        },
                    ),
                    ("DSSTDAT", "Date", "date", "date", True, None),
                    ("DSREAS", "Reason", "textarea", "string", False, None),
                ],
            ),
        ],
    ),
    # --- EG (ECG) — repeating ---
    (
        "ECG",
        "EG",
        True,
        [
            (
                "ECG Results",
                [
                    ("EGDTC", "Date", "date", "date", True, None),
                    (
                        "EGHR",
                        "Heart Rate",
                        "integer",
                        "integer",
                        True,
                        {"unit": "bpm", "min_value": 30, "max_value": 220},
                    ),
                    (
                        "EGINTP",
                        "Interpretation",
                        "dropdown",
                        "string",
                        True,
                        {
                            "help_text": "Normal / Abnormal — Clinically Significant / Abnormal — Not Clinically Significant"
                        },
                    ),
                    ("EGCOM", "Comments", "textarea", "string", False, None),
                ],
            ),
        ],
    ),
    # --- Visit Date — single ---
    (
        "Visit Date",
        "VISITDT",
        False,
        [
            (
                "Visit Date",
                [
                    ("VISITDTC", "Visit Date", "date", "date", True, None),
                ],
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------


async def seed_standard_forms(
    session: AsyncSession,
    version: StudyVersion,
    actor_id: UUID,
) -> list[FormDefinition]:
    """Seed the standard eCRF form templates into a draft Study_Version.

    This function is **idempotent**: if any form definitions already exist for
    the given version, it returns early without creating duplicates.

    Args:
        session: Active async session (caller manages transaction).
        version: The target StudyVersion (must be draft).
        actor_id: UUID of the acting user (for audit trail context).

    Returns:
        List of created FormDefinition objects (empty if skipped).

    Satisfies Requirements 9.3 (control types) and 9.4 (field attributes).
    """
    # Idempotency check: skip if forms already exist for this version
    existing = await session.execute(
        select(FormDefinition.id).where(FormDefinition.study_version_id == version.id).limit(1)
    )
    if existing.scalars().first() is not None:
        logger.info(
            "Standard forms already exist for version_id=%s — skipping seed.",
            version.id,
        )
        return []

    created_forms: list[FormDefinition] = []

    for display_order, (form_name, form_code, is_repeating, sections) in enumerate(STANDARD_FORMS):
        form = FormDefinition(
            study_version_id=version.id,
            name=form_name,
            form_code=form_code,
            display_order=display_order,
            is_repeating=is_repeating,
        )
        session.add(form)
        await session.flush()  # Assign form.id

        for section_order, (section_name, fields) in enumerate(sections):
            section = FormSection(
                form_definition_id=form.id,
                name=section_name,
                display_order=section_order,
            )
            session.add(section)
            await session.flush()  # Assign section.id

            for field_order, field_spec in enumerate(fields):
                variable_name, label, control_type, data_type, is_required, extras = field_spec

                field_kwargs: dict = {
                    "form_section_id": section.id,
                    "variable_name": variable_name,
                    "label": label,
                    "control_type": control_type,
                    "data_type": data_type,
                    "is_required": is_required,
                    "display_order": field_order,
                }

                if extras:
                    field_kwargs.update(extras)

                field = FieldDefinition(**field_kwargs)
                session.add(field)

            await session.flush()  # Flush all fields for this section

        created_forms.append(form)

    logger.info(
        "Seeded %d standard form templates for version_id=%s actor=%s",
        len(created_forms),
        version.id,
        actor_id,
    )
    return created_forms
