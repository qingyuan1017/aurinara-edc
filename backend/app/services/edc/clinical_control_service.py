"""Lock readiness and maker-checker clinical control workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.request_context import get_request_context
from app.models.designer.edit_check import ValidationResult
from app.models.designer.form_metadata import FormDefinition
from app.models.edc.form_data import FormInstance
from app.models.edc.operations import (
    ClinicalControlRequest,
    ClinicalControlRequestStatus,
    SDRSetting,
)
from app.models.edc.query import Query
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.schemas.edc.operations import (
    ClinicalControlRequestCreate,
    LockReadinessResponse,
    ReadinessBlocker,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.lock_service import lock_service
from app.services.edc.operational_service import edc_operational_service

_NON_TERMINAL = (
    ClinicalControlRequestStatus.pending_approval.value,
    ClinicalControlRequestStatus.approved.value,
)


class ClinicalControlService:
    async def readiness(self, session: AsyncSession, study_id: UUID) -> LockReadinessResponse:
        study = await session.get(Study, study_id)
        if study is None:
            raise NotFoundError(message="Study not found", details={})
        forms = list(
            (
                await session.execute(
                    select(FormInstance)
                    .join(Subject, Subject.id == FormInstance.subject_id)
                    .where(Subject.study_id == study_id, Subject.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        statuses = await edc_operational_service.form_statuses(session, forms)
        blockers: list[ReadinessBlocker] = []

        incomplete = sum(form.data_entry_status != "Submitted" for form in forms)
        self._add_blocker(
            blockers,
            "INCOMPLETE_FORMS",
            incomplete,
            "Required forms are not submitted",
            f"/studies/{study_id}/form-worklist?state=incomplete",
        )
        active_queries = int(
            await session.scalar(
                select(func.count(Query.id)).where(
                    Query.study_id == study_id,
                    Query.status.in_(("Open", "Answered", "Reopened")),
                )
            )
            or 0
        )
        self._add_blocker(
            blockers,
            "ACTIVE_QUERIES",
            active_queries,
            "Queries remain active",
            f"/studies/{study_id}/queries/open",
        )
        validation_findings = int(
            await session.scalar(
                select(func.count(ValidationResult.id))
                .join(FormInstance, FormInstance.id == ValidationResult.form_instance_id)
                .join(Subject, Subject.id == FormInstance.subject_id)
                .where(
                    Subject.study_id == study_id,
                    ValidationResult.is_resolved.is_(False),
                    ValidationResult.severity.in_(("error", "query")),
                )
            )
            or 0
        )
        self._add_blocker(
            blockers,
            "VALIDATION_FINDINGS",
            validation_findings,
            "Error or query edit-check findings remain unresolved",
            f"/studies/{study_id}/edc/data-review/listings",
        )
        submitted_statuses = [
            statuses[form.id] for form in forms if form.data_entry_status == "Submitted"
        ]
        pending_review = sum(status.review != "Reviewed" for status in submitted_statuses)
        pending_sdv = sum(
            status.sdv not in {"Verified", "Not Required"} for status in submitted_statuses
        )
        self._add_blocker(
            blockers,
            "PENDING_REVIEW",
            pending_review,
            "Clinical review is missing or stale",
            f"/studies/{study_id}/edc/data-review/forms",
        )
        self._add_blocker(
            blockers,
            "PENDING_SDV",
            pending_sdv,
            "SDV is incomplete or stale",
            f"/studies/{study_id}/edc/data-review/sdv-sdr",
        )
        required_sdr_versions = set(
            (
                await session.execute(
                    select(SDRSetting.study_version_id).where(
                        SDRSetting.is_required_for_lock.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        pending_sdr = sum(
            status.sdr not in {"Complete", "Not Selected"}
            for form in forms
            if form.design_version_id in required_sdr_versions
            for status in [statuses[form.id]]
        )
        self._add_blocker(
            blockers,
            "PENDING_SDR",
            pending_sdr,
            "Required SDR is incomplete or stale",
            f"/studies/{study_id}/edc/data-review/sdv-sdr",
        )
        required_signature_forms = {
            row[0]
            for row in (
                await session.execute(
                    select(FormInstance.id)
                    .join(FormDefinition, FormDefinition.id == FormInstance.form_definition_id)
                    .join(Subject, Subject.id == FormInstance.subject_id)
                    .where(
                        Subject.study_id == study_id,
                        FormDefinition.requires_signature.is_(True),
                        FormInstance.data_entry_status == "Submitted",
                    )
                )
            ).all()
        }
        missing_signatures = sum(
            statuses[form_id].signature != "Valid" for form_id in required_signature_forms
        )
        self._add_blocker(
            blockers,
            "SIGNATURES",
            missing_signatures,
            "Required signatures are missing or stale",
            f"/studies/{study_id}/edc/subjects",
        )
        evaluated_at = datetime.now(UTC)
        payload = {
            "study_id": str(study_id),
            "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return LockReadinessResponse(
            study_id=study_id,
            ready=not blockers,
            evaluated_at=evaluated_at,
            blockers=blockers,
            snapshot_hash=snapshot_hash,
        )

    async def create_request(
        self,
        session: AsyncSession,
        study_id: UUID,
        data: ClinicalControlRequestCreate,
        actor_id: UUID,
    ) -> ClinicalControlRequest:
        await self.resolve_target(session, study_id, data.scope_type, data.scope_id)
        exists = await session.scalar(
            select(ClinicalControlRequest.id).where(
                ClinicalControlRequest.study_id == study_id,
                ClinicalControlRequest.scope_type == data.scope_type,
                ClinicalControlRequest.scope_id == data.scope_id,
                ClinicalControlRequest.action == data.action,
                ClinicalControlRequest.status.in_(_NON_TERMINAL),
            )
        )
        if exists:
            raise ConflictError(
                message="A non-terminal clinical control request already exists",
                details={"request_id": str(exists)},
            )
        readiness = await self.readiness(session, study_id)
        context = get_request_context()
        request = ClinicalControlRequest(
            id=uuid4(),
            study_id=study_id,
            scope_type=data.scope_type,
            scope_id=data.scope_id,
            action=data.action,
            reason=data.reason.strip(),
            requested_by=actor_id,
            readiness_snapshot=readiness.model_dump(mode="json"),
            readiness_hash=readiness.snapshot_hash,
            correlation_id=context.correlation_id,
            request_id=context.request_id,
        )
        try:
            async with session.begin_nested():
                session.add(request)
                await session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                message="A non-terminal clinical control request already exists",
                details={},
            ) from exc
        await self._audit(session, request, "request", actor_id)
        return request

    async def approve(
        self, session: AsyncSession, request_id: UUID, actor_id: UUID
    ) -> ClinicalControlRequest:
        request = await self._get(session, request_id, for_update=True)
        self._require_status(request, ClinicalControlRequestStatus.pending_approval)
        if request.requested_by == actor_id:
            raise BusinessRuleError(
                message="The requester cannot approve their own clinical control request",
                details={"reason": "MAKER_CHECKER_VIOLATION"},
            )
        request.status = ClinicalControlRequestStatus.approved.value
        request.approved_by = actor_id
        request.approved_at = datetime.now(UTC)
        request.updated_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, request, "approve", actor_id)
        return request

    async def reject(
        self, session: AsyncSession, request_id: UUID, actor_id: UUID, reason: str
    ) -> ClinicalControlRequest:
        request = await self._get(session, request_id, for_update=True)
        self._require_status(request, ClinicalControlRequestStatus.pending_approval)
        if request.requested_by == actor_id:
            raise BusinessRuleError(
                message="The requester cannot reject their own clinical control request",
                details={"reason": "MAKER_CHECKER_VIOLATION"},
            )
        request.status = ClinicalControlRequestStatus.rejected.value
        request.failure_details = {"reason": reason.strip()}
        request.updated_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, request, "reject", actor_id, reason=reason)
        return request

    async def cancel(
        self, session: AsyncSession, request_id: UUID, actor_id: UUID
    ) -> ClinicalControlRequest:
        request = await self._get(session, request_id, for_update=True)
        self._require_status(request, ClinicalControlRequestStatus.pending_approval)
        if request.requested_by != actor_id:
            raise BusinessRuleError(
                message="Only the requester may cancel a pending request", details={}
            )
        request.status = ClinicalControlRequestStatus.cancelled.value
        request.updated_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, request, "cancel", actor_id)
        return request

    async def execute(
        self, session: AsyncSession, request_id: UUID, actor_id: UUID
    ) -> ClinicalControlRequest:
        request = await self._get(session, request_id, for_update=True)
        self._require_status(request, ClinicalControlRequestStatus.approved)
        await session.execute(
            select(Study.id).where(Study.id == request.study_id).with_for_update()
        )
        if request.action in {"freeze", "lock"}:
            readiness = await self.readiness(session, request.study_id)
            request.readiness_snapshot = readiness.model_dump(mode="json")
            request.readiness_hash = readiness.snapshot_hash
            if not readiness.ready:
                raise BusinessRuleError(
                    message="Study is not ready for the requested clinical control",
                    details={
                        "reason": "LOCK_READINESS_FAILED",
                        "blockers": [item.model_dump(mode="json") for item in readiness.blockers],
                    },
                )
        target = await self.resolve_target(
            session, request.study_id, request.scope_type, request.scope_id
        )
        try:
            async with session.begin_nested():
                if request.action == "freeze":
                    await lock_service.freeze(session, target, actor_id)
                elif request.action == "lock":
                    await lock_service.lock(session, target, actor_id)
                elif request.action == "unfreeze":
                    await lock_service.unfreeze(session, target, request.reason, actor_id)
                else:
                    await lock_service.unlock(session, target, request.reason, actor_id)
        except Exception as exc:
            request.status = ClinicalControlRequestStatus.failed.value
            request.failure_details = {"error": type(exc).__name__}
            request.updated_at = datetime.now(UTC)
            await session.flush()
            await self._audit(session, request, "fail", actor_id)
            return request
        request.status = ClinicalControlRequestStatus.executed.value
        request.executed_by = actor_id
        request.executed_at = datetime.now(UTC)
        request.updated_at = datetime.now(UTC)
        await session.flush()
        await self._audit(session, request, "execute", actor_id)
        return request

    async def list_requests(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
    ) -> PaginatedResponse[ClinicalControlRequest]:
        conditions = [ClinicalControlRequest.study_id == study_id]
        if status:
            conditions.append(ClinicalControlRequest.status == status)
        total = int(
            await session.scalar(select(func.count(ClinicalControlRequest.id)).where(*conditions))
            or 0
        )
        items = list(
            (
                await session.execute(
                    select(ClinicalControlRequest)
                    .where(*conditions)
                    .order_by(ClinicalControlRequest.requested_at.desc())
                    .offset((pagination.page - 1) * pagination.page_size)
                    .limit(pagination.page_size)
                )
            )
            .scalars()
            .all()
        )
        return PaginatedResponse(
            items=items, page=pagination.page, page_size=pagination.page_size, total=total
        )

    async def resolve_target(
        self,
        session: AsyncSession,
        study_id: UUID,
        scope_type: str,
        scope_id: UUID,
    ):
        target = None
        target_study_id = None
        if scope_type == "study":
            target = await session.get(Study, scope_id)
            target_study_id = getattr(target, "id", None)
        elif scope_type == "site":
            target = await session.get(Site, scope_id)
            target_study_id = getattr(target, "study_id", None)
        elif scope_type == "subject":
            target = await session.get(Subject, scope_id)
            target_study_id = getattr(target, "study_id", None)
        elif scope_type == "visit":
            target = await session.get(VisitInstance, scope_id)
            target_study_id = target.subject.study_id if target else None
        elif scope_type == "form":
            target = await session.get(FormInstance, scope_id)
            target_study_id = target.subject.study_id if target else None
        if target is None or target_study_id != study_id:
            raise NotFoundError(message="Clinical control target not found", details={})
        return target

    async def _get(
        self, session: AsyncSession, request_id: UUID, *, for_update: bool = False
    ) -> ClinicalControlRequest:
        stmt = select(ClinicalControlRequest).where(ClinicalControlRequest.id == request_id)
        if for_update:
            stmt = stmt.with_for_update()
        request = (await session.execute(stmt)).scalars().first()
        if request is None:
            raise NotFoundError(message="Clinical control request not found", details={})
        return request

    @staticmethod
    def _require_status(
        request: ClinicalControlRequest, expected: ClinicalControlRequestStatus
    ) -> None:
        if request.status != expected.value:
            raise ConflictError(
                message="Clinical control request is not in the required state",
                details={"current_status": request.status, "required_status": expected.value},
            )

    @staticmethod
    def _add_blocker(
        blockers: list[ReadinessBlocker],
        code: str,
        count: int,
        message: str,
        drilldown: str,
    ) -> None:
        if count:
            blockers.append(
                ReadinessBlocker(code=code, count=count, message=message, drilldown=drilldown)
            )

    @staticmethod
    async def _audit(
        session: AsyncSession,
        request: ClinicalControlRequest,
        action: str,
        actor_id: UUID,
        *,
        reason: str | None = None,
    ) -> None:
        await audit_service.record(
            session,
            entity_type="clinical_control_request",
            entity_id=request.id,
            action=action,
            study_id=request.study_id,
            actor_id=actor_id,
            new_value=f"{request.action}:{request.status}:{request.scope_type}:{request.scope_id}",
            reason=reason or request.reason,
            correlation_id=request.correlation_id,
        )


clinical_control_service = ClinicalControlService()

__all__ = ["ClinicalControlService", "clinical_control_service"]
