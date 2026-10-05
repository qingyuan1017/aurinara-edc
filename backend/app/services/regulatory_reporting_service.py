"""PV Regulatory reporting service boundary.

Owns reportability evaluation, expedited Regulatory_Clocks, the report status
state machine, and ICSR/E2B(R3) produce/parse. ``compute_clock``, ``is_overdue``,
``produce_e2b``, and ``parse_e2b`` are pure, deterministic functions with no I/O
so they can be exercised directly by property-based tests. Concrete behavior
lands in the regulatory reporting and ICSR tasks; this module establishes the
additive service boundary and interface.

ICSR/E2B(R3) handling (Requirement 9) is modeled as an internal serializer and
parser, not a live regulatory gateway. ``produce_e2b`` serializes a reportable
Safety_Case into an E2B(R3)-structured XML message containing the case
identifier, every mandatory field, and the Coding_Dictionary_Versions used;
``parse_e2b`` parses a structurally valid message back into that representation.
Both functions are pure (no session, no I/O) and satisfy the round-trip
invariant ``produce -> parse -> produce`` for case identifier, mandatory fields,
and Coding_Dictionary_Versions (Requirement 9.5).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any
from uuid import UUID
from xml.etree.ElementTree import ParseError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext, ReportStatus, utc_now
from app.models.pv.regulatory import (
    TIMELINE_DAYS_MAX,
    TIMELINE_DAYS_MIN,
    RegulatoryReport,
)
from app.repositories.pv.regulatory_reporting_repository import (
    RegulatoryReportingRepository,
)
from app.services.pv_atomicity_service import pv_atomicity_service

# ReportStatus values that stop the expedited clock (Requirement 8.6).
_CLOCK_STOPPED_STATUSES: frozenset[ReportStatus] = frozenset(
    {ReportStatus.SUBMITTED, ReportStatus.ACKNOWLEDGED, ReportStatus.CANCELLED}
)

# Permitted Regulatory_Report status transitions (Requirement 8.5).
_ALLOWED_TRANSITIONS: dict[ReportStatus, frozenset[ReportStatus]] = {
    ReportStatus.PENDING: frozenset({ReportStatus.SUBMITTED, ReportStatus.CANCELLED}),
    ReportStatus.SUBMITTED: frozenset(
        {ReportStatus.ACKNOWLEDGED, ReportStatus.REJECTED}
    ),
    ReportStatus.ACKNOWLEDGED: frozenset(),
    ReportStatus.REJECTED: frozenset({ReportStatus.PENDING}),
    ReportStatus.CANCELLED: frozenset(),
}

# --- E2B(R3) structure --------------------------------------------------------
#
# The E2B(R3) message is modeled as a compact ICSR XML document. The element
# names mirror the E2B(R3) safety-report data elements the round-trip property
# cares about; they are an internal representation, not a full ICH schema.
_ROOT_TAG = "ichicsr"
_SAFETY_REPORT_TAG = "safetyreport"
_CASE_ID_TAG = "safetyreportid"
_DICTIONARY_VERSIONS_TAG = "codingdictionaryversions"
_DICTIONARY_VERSION_TAG = "codingdictionaryversion"
_DICTIONARY_NAME_ATTR = "dictionary"

# Fields designated mandatory by the E2B(R3) structure for a reportable case.
# A reportable Safety_Case that is missing any of these cannot be serialized.
E2B_MANDATORY_FIELDS: tuple[str, ...] = (
    "sender_identifier",
    "receiver_identifier",
    "report_type",
    "seriousness",
    "primary_source_country",
    "patient_reference",
    "reaction_verbatim",
    "reaction_onset_date",
    "suspect_product",
)

# The case identifier is mandatory but is carried in its own element rather than
# in the generic mandatory-field block, so it is validated separately.
_CASE_IDENTIFIER_KEY = "case_identifier"
_DICTIONARY_VERSIONS_KEY = "dictionary_versions"


def _stringify(value: Any) -> str:
    """Render a scalar E2B field value as a deterministic string."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date):
        # date and datetime both serialize via isoformat; dates use YYYY-MM-DD.
        return value.isoformat()
    return str(value)


class RegulatoryReportingService:
    """Authoritative service for PV regulatory reporting and ICSR handling."""

    async def evaluate_reportability(
        self,
        session: AsyncSession,
        *,
        case_id: UUID,
        awareness_date: date | None,
        actor: ActorContext,
    ) -> list[RegulatoryReport]:
        """Create one Pending Regulatory_Report per matched configured rule.

        For a Safety_Case, each active configured ``ReportabilityRule`` for the
        case's study is treated as matched and yields exactly one
        ``RegulatoryReport`` with the rule's report type and destination and a
        status of ``Pending`` (Requirements 8.1, 8.2). Each report gets a
        Regulatory_Clock whose due date is computed from the Awareness_Date and
        the rule's configured whole-day timeline (Requirement 8.3).

        A report cannot be created without an Awareness_Date: if
        ``awareness_date`` is absent the evaluation is rejected before any state
        change and no report is created (Requirement 8.4). Each created report
        emits exactly one PV safety Audit_Event on the caller's transaction
        (Requirement 8.9).
        """

        repository = RegulatoryReportingRepository(session)
        case = await self._require_case(repository, case_id)

        if awareness_date is None:
            raise ValidationError(
                message="Awareness_Date is required to create a Regulatory_Report",
                details={"reason": "AWARENESS_DATE_REQUIRED", "field": "awareness_date"},
            )

        rules = await repository.active_rules_for_study(case.study_id)

        created: list[RegulatoryReport] = []
        for rule in rules:
            due_date = self.compute_clock(awareness_date, rule.timeline_days)
            report = await repository.add_report_with_clock(
                case_id=case.id,
                rule_id=rule.id,
                report_type=rule.report_type,
                destination=rule.destination,
                awareness_date=awareness_date,
                timeline_days=rule.timeline_days,
                due_date=due_date,
                actor_id=actor.user_id,
                correlation_id=actor.correlation_id,
            )
            await self._record_report_audit(
                session,
                report=report,
                case=case,
                action="create",
                actor=actor,
                old_value=None,
                new_value=ReportStatus.PENDING.value,
            )
            created.append(report)

        return created

    def compute_clock(self, awareness_date: date, timeline_days: int) -> date:
        """Return the Regulatory_Clock due date for a timeline (pure function).

        ``due_date = awareness_date + timedelta(days=timeline_days)`` counting
        whole calendar days in UTC where the Awareness_Date is day zero.
        ``timeline_days`` must be a whole number between 1 and 90 inclusive; any
        other value is rejected (Requirement 8.3).
        """

        if isinstance(timeline_days, bool) or not isinstance(timeline_days, int):
            raise ValidationError(
                message="timeline_days must be a whole number",
                details={"reason": "INVALID_TIMELINE_DAYS", "field": "timeline_days"},
            )
        if not TIMELINE_DAYS_MIN <= timeline_days <= TIMELINE_DAYS_MAX:
            raise ValidationError(
                message=(
                    "timeline_days must be between "
                    f"{TIMELINE_DAYS_MIN} and {TIMELINE_DAYS_MAX} inclusive"
                ),
                details={"reason": "INVALID_TIMELINE_DAYS", "field": "timeline_days"},
            )
        return awareness_date + timedelta(days=timeline_days)

    def is_overdue(self, due_date: date, status: ReportStatus, today_utc: date) -> bool:
        """Return whether an expedited report is overdue (pure predicate).

        A report is overdue exactly when the current UTC date is later than the
        Regulatory_Clock due date and the report status is not ``Submitted``,
        ``Acknowledged``, or ``Cancelled`` (Requirement 8.6).
        """

        resolved_status = status if isinstance(status, ReportStatus) else ReportStatus(status)
        if resolved_status in _CLOCK_STOPPED_STATUSES:
            return False
        return today_utc > due_date

    async def transition(
        self,
        session: AsyncSession,
        *,
        report_id: UUID,
        target: ReportStatus,
        actor: ActorContext,
    ) -> RegulatoryReport:
        """Apply a permitted Regulatory_Report status transition.

        Permits only Pending->Submitted/Cancelled, Submitted->Acknowledged/
        Rejected, and Rejected->Pending; any other transition is rejected
        without changing the report (Requirement 8.5). Submitting a report
        requires an E2B_Message reference, so submission is not reachable through
        this method and must go through :meth:`submit` (Requirement 8.7, 8.8).
        Emits one PV safety Audit_Event per transition (Requirement 8.9).
        """

        resolved_target = (
            target if isinstance(target, ReportStatus) else ReportStatus(target)
        )
        if resolved_target is ReportStatus.SUBMITTED:
            raise ValidationError(
                message="Use submit to mark a Regulatory_Report as Submitted",
                details={"reason": "SUBMIT_REQUIRES_E2B_REFERENCE"},
            )

        repository = RegulatoryReportingRepository(session)
        report, case = await self._require_report(repository, report_id)
        self._require_allowed_transition(report, resolved_target)

        prior_status = report.status
        await repository.update_report(
            report,
            status=resolved_target.value,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
        )
        await self._record_report_audit(
            session,
            report=report,
            case=case,
            action="transition",
            actor=actor,
            old_value=prior_status,
            new_value=resolved_target.value,
        )
        return report

    async def submit(
        self,
        session: AsyncSession,
        *,
        report_id: UUID,
        e2b_message_ref: str,
        actor: ActorContext,
    ) -> RegulatoryReport:
        """Mark a Pending Regulatory_Report as Submitted.

        Records the submitting actor, the UTC submission timestamp, and the
        submitted E2B_Message reference (Requirement 8.7). A submission without a
        valid E2B_Message reference is rejected, the report is retained in its
        prior status, and no state change is persisted (Requirement 8.8). Only a
        Pending report may transition to Submitted (Requirement 8.5). Emits one
        PV safety Audit_Event (Requirement 8.9).
        """

        reference = e2b_message_ref.strip() if isinstance(e2b_message_ref, str) else ""
        if not reference:
            raise ValidationError(
                message="A valid E2B_Message reference is required to submit a report",
                details={"reason": "E2B_MESSAGE_REFERENCE_REQUIRED", "field": "e2b_message_ref"},
            )

        repository = RegulatoryReportingRepository(session)
        report, case = await self._require_report(repository, report_id)
        self._require_allowed_transition(report, ReportStatus.SUBMITTED)

        prior_status = report.status
        await repository.update_report(
            report,
            status=ReportStatus.SUBMITTED.value,
            actor_id=actor.user_id,
            correlation_id=actor.correlation_id,
            submitted_at=utc_now(),
            submitted_by=actor.user_id,
            e2b_message_ref=reference,
        )
        await self._record_report_audit(
            session,
            report=report,
            case=case,
            action="submit",
            actor=actor,
            old_value=prior_status,
            new_value=ReportStatus.SUBMITTED.value,
        )
        return report

    # ------------------------------------------------------------------
    # Shared guards and helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _require_case(
        repository: RegulatoryReportingRepository, case_id: UUID
    ) -> Any:
        case = await repository.get_case(case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )
        return case

    @staticmethod
    async def _require_report(
        repository: RegulatoryReportingRepository, report_id: UUID
    ) -> tuple[RegulatoryReport, Any]:
        report = await repository.get_report(report_id)
        if report is None:
            raise NotFoundError(
                message="Regulatory_Report was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "regulatory_report"},
            )
        case = await repository.get_case(report.case_id)
        if case is None:
            raise NotFoundError(
                message="Safety_Case was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
            )
        return report, case

    @staticmethod
    def _require_allowed_transition(
        report: RegulatoryReport, target: ReportStatus
    ) -> None:
        """Reject a transition not permitted by the report state machine."""

        current = ReportStatus(report.status)
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise ValidationError(
                message="The requested Regulatory_Report transition is not permitted",
                details={
                    "reason": "TRANSITION_NOT_PERMITTED",
                    "from": current.value,
                    "to": target.value,
                },
            )

    @staticmethod
    async def _record_report_audit(
        session: AsyncSession,
        *,
        report: RegulatoryReport,
        case: Any,
        action: str,
        actor: ActorContext,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Emit exactly one PV safety Audit_Event for a report action.

        The event captures the acting user, timestamp, and status change on the
        caller's transaction so the report change and its Audit_Event commit or
        roll back together (Requirement 8.9).
        """

        await pv_atomicity_service.record_mutation(
            session,
            entity_type="regulatory_report",
            entity_id=report.id,
            action=action,
            actor=actor,
            study_id=case.study_id,
            site_id=case.site_id,
            subject_id=case.subject_reference,
            changed_fields=("status",),
            field_name="status",
            old_value=old_value,
            new_value=new_value,
        )

    def produce_e2b(self, case: Mapping[str, Any]) -> str:
        """Serialize a reportable Safety_Case into an E2B(R3) XML message.

        The produced message contains the case identifier, every field
        designated mandatory by the E2B(R3) structure, and the
        Coding_Dictionary_Versions used (Requirement 9.1). This is a pure
        function: it performs no I/O and never mutates ``case``.

        Args:
            case: A mapping describing the reportable Safety_Case. It must carry
                ``case_identifier``, each name in :data:`E2B_MANDATORY_FIELDS`,
                and a ``dictionary_versions`` mapping of dictionary name to the
                Coding_Dictionary_Version used.

        Returns:
            A UTF-8, deterministically ordered E2B(R3) XML string.

        Raises:
            ValidationError: If the case is missing the case identifier or any
                mandatory field. The error names every missing field, no message
                is produced, and the input case is left unchanged (Requirement
                9.2).
        """

        missing: list[str] = []
        if not self._present(case.get(_CASE_IDENTIFIER_KEY)):
            missing.append(_CASE_IDENTIFIER_KEY)
        for field in E2B_MANDATORY_FIELDS:
            if not self._present(case.get(field)):
                missing.append(field)

        if missing:
            raise ValidationError(
                "Safety_Case is missing mandatory E2B(R3) fields",
                {"reason": "PV_E2B_MISSING_MANDATORY_FIELDS", "missing_fields": missing},
            )

        root = ET.Element(_ROOT_TAG)
        report = ET.SubElement(root, _SAFETY_REPORT_TAG)

        case_id = ET.SubElement(report, _CASE_ID_TAG)
        case_id.text = _stringify(case[_CASE_IDENTIFIER_KEY])

        # Mandatory fields emitted in a stable, canonical order.
        for field in E2B_MANDATORY_FIELDS:
            element = ET.SubElement(report, field)
            element.text = _stringify(case[field])

        # Coding_Dictionary_Versions, ordered by dictionary name for determinism.
        versions = case.get(_DICTIONARY_VERSIONS_KEY) or {}
        versions_element = ET.SubElement(report, _DICTIONARY_VERSIONS_TAG)
        for name in sorted(versions):
            version_element = ET.SubElement(versions_element, _DICTIONARY_VERSION_TAG)
            version_element.set(_DICTIONARY_NAME_ATTR, str(name))
            version_element.text = _stringify(versions[name])

        return ET.tostring(root, encoding="unicode")

    def parse_e2b(self, message: str) -> Mapping[str, Any]:
        """Parse a structurally valid E2B(R3) message into a case representation.

        The returned representation contains the case identifier, the mandatory
        fields, and the Coding_Dictionary_Versions from the message (Requirement
        9.3). This is a pure function: it performs no I/O and creates no
        Safety_Case.

        Args:
            message: The E2B(R3) XML message to parse.

        Returns:
            A mapping with ``case_identifier``, each mandatory field name, and a
            ``dictionary_versions`` mapping. Producing from this representation
            reproduces an equivalent message (Requirement 9.5).

        Raises:
            ValidationError: If the message is not well-formed XML or does not
                conform to the expected E2B(R3) structure (missing root element,
                safety report, case identifier, or any mandatory field). No
                Safety_Case is created (Requirement 9.4).
        """

        if not isinstance(message, str) or not message.strip():
            raise self._invalid("message is empty")

        try:
            root = ET.fromstring(message)
        except ParseError as exc:
            raise self._invalid(f"message is not well-formed XML: {exc}") from exc

        if root.tag != _ROOT_TAG:
            raise self._invalid(f"expected root element <{_ROOT_TAG}>")

        report = root.find(_SAFETY_REPORT_TAG)
        if report is None:
            raise self._invalid(f"missing <{_SAFETY_REPORT_TAG}> element")

        case_id_element = report.find(_CASE_ID_TAG)
        if case_id_element is None or not self._present(case_id_element.text):
            raise self._invalid("missing case identifier")

        result: dict[str, Any] = {_CASE_IDENTIFIER_KEY: case_id_element.text}

        missing: list[str] = []
        for field in E2B_MANDATORY_FIELDS:
            element = report.find(field)
            if element is None or not self._present(element.text):
                missing.append(field)
            else:
                result[field] = element.text

        if missing:
            raise self._invalid(f"missing mandatory fields: {', '.join(missing)}")

        versions: dict[str, str] = {}
        versions_element = report.find(_DICTIONARY_VERSIONS_TAG)
        if versions_element is not None:
            for version_element in versions_element.findall(_DICTIONARY_VERSION_TAG):
                name = version_element.get(_DICTIONARY_NAME_ATTR)
                if name is None or not self._present(version_element.text):
                    raise self._invalid("malformed Coding_Dictionary_Version entry")
                versions[name] = version_element.text or ""
        result[_DICTIONARY_VERSIONS_KEY] = versions

        return result

    @staticmethod
    def _present(value: Any) -> bool:
        """Return whether a mandatory value is present (non-empty)."""

        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    @staticmethod
    def _invalid(reason: str) -> ValidationError:
        """Build a descriptive parse error for a structurally invalid message."""

        return ValidationError(
            "E2B(R3) message is structurally invalid",
            {"reason": "PV_E2B_INVALID_MESSAGE", "detail": reason},
        )


regulatory_reporting_service = RegulatoryReportingService()

__all__ = [
    "E2B_MANDATORY_FIELDS",
    "RegulatoryReportingService",
    "regulatory_reporting_service",
]
