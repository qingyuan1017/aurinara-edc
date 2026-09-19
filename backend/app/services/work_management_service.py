"""CTMS Work_Management_Service.

The service owns operational tasks, contacts, dependencies, and escalations.
Every mutation uses the caller's transaction; no method commits. EDC Query rows
are resolved as read-only references and query message text is never copied.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_actor, get_correlation_id
from app.models.ctms.work import (
    EscalationStatus,
    OperationalContact,
    OperationalContactStatus,
    OperationalTask,
    OperationalTaskPriority,
    OperationalTaskStatus,
    TaskDependency,
    TaskEscalation,
)
from app.models.identity import User, UserStatus
from app.models.query import Query
from app.models.site import Site
from app.models.study import Study
from app.services.ctms_atomicity_service import ctms_atomicity_service
from app.services.notification_service import notification_service

_TASK_TRANSITIONS: dict[str, set[str]] = {
    OperationalTaskStatus.OPEN.value: {
        OperationalTaskStatus.IN_PROGRESS.value,
        OperationalTaskStatus.COMPLETED.value,
        OperationalTaskStatus.BLOCKED.value,
        OperationalTaskStatus.CANCELLED.value,
        OperationalTaskStatus.ARCHIVED.value,
    },
    OperationalTaskStatus.IN_PROGRESS.value: {
        OperationalTaskStatus.OPEN.value,
        OperationalTaskStatus.BLOCKED.value,
        OperationalTaskStatus.COMPLETED.value,
        OperationalTaskStatus.CANCELLED.value,
        OperationalTaskStatus.ARCHIVED.value,
    },
    OperationalTaskStatus.BLOCKED.value: {
        OperationalTaskStatus.OPEN.value,
        OperationalTaskStatus.IN_PROGRESS.value,
        OperationalTaskStatus.CANCELLED.value,
        OperationalTaskStatus.ARCHIVED.value,
    },
    OperationalTaskStatus.COMPLETED.value: {OperationalTaskStatus.ARCHIVED.value},
    OperationalTaskStatus.CANCELLED.value: {OperationalTaskStatus.ARCHIVED.value},
    OperationalTaskStatus.ARCHIVED.value: set(),
}

_CONTACT_TRANSITIONS: dict[str, set[str]] = {
    OperationalContactStatus.ACTIVE.value: {
        OperationalContactStatus.INACTIVE.value,
        OperationalContactStatus.ARCHIVED.value,
    },
    OperationalContactStatus.INACTIVE.value: {
        OperationalContactStatus.ACTIVE.value,
        OperationalContactStatus.ARCHIVED.value,
    },
    OperationalContactStatus.ARCHIVED.value: set(),
}

_ESCALATION_TRANSITIONS: dict[str, set[str]] = {
    EscalationStatus.OPEN.value: {
        EscalationStatus.IN_PROGRESS.value,
        EscalationStatus.RESOLVED.value,
        EscalationStatus.CANCELLED.value,
    },
    EscalationStatus.IN_PROGRESS.value: {
        EscalationStatus.RESOLVED.value,
        EscalationStatus.CANCELLED.value,
    },
    EscalationStatus.RESOLVED.value: set(),
    EscalationStatus.CANCELLED.value: set(),
}

_TERMINAL_DEPENDENCY_STATUSES = {
    OperationalTaskStatus.COMPLETED.value,
    OperationalTaskStatus.CANCELLED.value,
    OperationalTaskStatus.ARCHIVED.value,
}

_FORBIDDEN_KEYS = {
    "clinical_data",
    "field_values",
    "form_instances",
    "source_document",
    "source_documents",
    "query_message",
    "query_messages",
    "message_history",
    "clinical_audit_history",
    "raw_event_body",
}


def _mapping(payload: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        return dict(dump(exclude_unset=True))
    raise ValidationError("Operational work payload must be a mapping")


def _actor(actor: Any | None = None, actor_id: UUID | None = None) -> UUID:
    value = actor_id or getattr(actor, "user_id", None) or getattr(actor, "id", None) or get_actor()
    if value is None:
        raise ValidationError("An actor is required for a CTMS work mutation")
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Actor identifier must be a UUID") from exc


def _correlation(value: UUID | str | None, actor: Any | None = None) -> str:
    return str(value or getattr(actor, "correlation_id", None) or get_correlation_id() or uuid4().hex)


def _correlation_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


def _status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("work timestamps must include timezone information")
    return value.astimezone(UTC)


def _reason(value: str | None, *, required: bool = True) -> str | None:
    if value is None or not str(value).strip():
        if required:
            raise ValidationError("A non-empty reason is required")
        return None
    return str(value).strip()


def _safe_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    """Reject prohibited content rather than persisting or forwarding it."""
    forbidden = {str(key).lower() for key in values} & _FORBIDDEN_KEYS
    if forbidden:
        raise ValidationError(
            "Operational work payload contains prohibited clinical content",
            {"reason": "PROHIBITED_CLINICAL_CONTENT", "fields": sorted(forbidden)},
        )
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
        elif isinstance(value, UUID):
            safe[str(key)] = str(value)
        elif isinstance(value, datetime):
            safe[str(key)] = value.astimezone(UTC).isoformat()
    return safe


class WorkManagementService:
    """Manage operational work without crossing EDC ownership boundaries."""

    def __init__(self, *, escalations_enabled: bool | None = None) -> None:
        self._escalations_enabled = escalations_enabled

    @property
    def escalations_enabled(self) -> bool:
        if self._escalations_enabled is not None:
            return self._escalations_enabled
        return bool(get_settings().ctms_escalations_enabled)

    async def _one(self, session: AsyncSession, model: type[Any], identifier: UUID) -> Any | None:
        result = await session.execute(select(model).where(model.id == identifier))
        rows = list(result.scalars().all())
        return next((row for row in rows if getattr(row, "id", None) == identifier), None)

    async def _active_user(self, session: AsyncSession, user_id: UUID | None) -> User | None:
        if user_id is None:
            return None
        user = await self._one(session, User, user_id)
        if user is None:
            raise NotFoundError("Assigned user was not found", {"reason": "RECORD_NOT_FOUND"})
        if str(getattr(user, "status", "")) not in {UserStatus.active.value, str(UserStatus.active)}:
            raise ConflictError("Operational work cannot be assigned to an inactive user", {"reason": "INACTIVE_USER"})
        return user

    async def _scope(self, session: AsyncSession, study_id: UUID, site_id: UUID | None) -> None:
        study = await self._one(session, Study, study_id)
        if study is None:
            raise NotFoundError("Canonical Study reference was not found", {"reason": "RECORD_NOT_FOUND"})
        if site_id is not None:
            site = await self._one(session, Site, site_id)
            if site is None:
                raise NotFoundError("Canonical Site reference was not found", {"reason": "RECORD_NOT_FOUND"})
            if site.study_id != study_id:
                raise ConflictError("Site is outside the requested study", {"reason": "REFERENCE_SCOPE_MISMATCH"})

    async def _record(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        study_id: UUID,
        site_id: UUID | None,
        actor_id: UUID,
        correlation_id: str,
        action: str,
        changed_fields: tuple[str, ...] = (),
        previous_status: str | None = None,
        status: str | None = None,
        reason: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            study_id=study_id,
            site_id=site_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            action=action,
            changed_fields=changed_fields,
            previous_status=previous_status,
            status=status,
            reason=reason,
            event_type=f"CTMS_{entity_type.upper()}_{action.upper()}",
            payload=_safe_payload(payload or {}),
        )

    async def create_task(
        self, session: AsyncSession, payload: Mapping[str, Any] | Any | None = None, actor_id: UUID | None = None,
        *, actor: Any | None = None, correlation_id: UUID | str | None = None, **values: Any,
    ) -> OperationalTask:
        data = _mapping(payload)
        data.update(values)
        _safe_payload(data)
        actor_uuid = _actor(actor, actor_id)
        study_id = data.get("study_id")
        site_id = data.get("site_id")
        if not isinstance(study_id, UUID):
            try:
                study_id = UUID(str(study_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError("study_id must be a canonical UUID") from exc
        if site_id is not None and not isinstance(site_id, UUID):
            try:
                site_id = UUID(str(site_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError("site_id must be a canonical UUID") from exc
        await self._scope(session, study_id, site_id)
        query_id = data.get("query_id")
        if query_id is not None:
            try:
                query_id = query_id if isinstance(query_id, UUID) else UUID(str(query_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError("query_id must be a canonical UUID") from exc
            query = await self._one(session, Query, query_id)
            if query is None:
                raise NotFoundError("EDC Query reference was not found", {"reason": "RECORD_NOT_FOUND"})
            if query.study_id != study_id or query.site_id != site_id:
                raise ConflictError("EDC Query reference is outside the task scope", {"reason": "REFERENCE_SCOPE_MISMATCH"})
        owner_id = data.get("owner_id")
        await self._active_user(session, owner_id)
        requested_status = _status(data.get("status", OperationalTaskStatus.OPEN))
        if requested_status != OperationalTaskStatus.OPEN.value:
            raise ValidationError("New operational tasks must start Open")
        priority = _status(data.get("priority", OperationalTaskPriority.NORMAL))
        if priority not in {item.value for item in OperationalTaskPriority}:
            raise ValidationError("Invalid operational task priority")
        title = str(data.get("title", "")).strip()
        if not title:
            raise ValidationError("Task title is required")
        correlation = _correlation(correlation_id or data.get("correlation_id"), actor)
        task = OperationalTask(
            study_id=study_id,
            site_id=site_id,
            title=title,
            description=data.get("description"),
            owner_id=owner_id,
            due_date=_utc(data.get("due_date")),
            priority=priority,
            status=requested_status,
            query_id=query_id,
            query_summary=data.get("query_summary"),
            retention_state="active",
            created_by=actor_uuid,
            updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(task)
        await session.flush()
        await self._record(
            session, entity_type="operational_task", entity_id=task.id, study_id=study_id, site_id=site_id,
            actor_id=actor_uuid, correlation_id=correlation, action="create",
            changed_fields=("title", "description", "owner_id", "due_date", "priority", "status", "query_id"),
            status=task.status, payload={"owner_id": owner_id, "priority": priority, "query_id": query_id},
        )
        if owner_id is not None:
            await notification_service.create_ctms_notification(
                session, user_ids=[owner_id], notification_type="ctms_task_assigned",
                payload={"task_id": str(task.id), "study_id": str(study_id), "site_id": str(site_id) if site_id else None, "priority": priority},
                study_id=study_id, site_id=site_id, correlation_id=correlation,
            )
        return task

    async def create_query_follow_up(
        self, session: AsyncSession, *, query_id: UUID, actor_id: UUID, title: str | None = None,
        approved_summary: str | None = None, owner_id: UUID | None = None, due_date: datetime | None = None,
        priority: OperationalTaskPriority | str = OperationalTaskPriority.NORMAL,
        correlation_id: UUID | str | None = None,
    ) -> OperationalTask:
        query = await self._one(session, Query, query_id)
        if query is None:
            raise NotFoundError("EDC Query reference was not found", {"reason": "RECORD_NOT_FOUND"})
        await self._active_user(session, owner_id)
        # Deliberately do not use query.text or query.messages. Only an explicitly
        # approved, bounded summary may cross the module boundary.
        summary = approved_summary.strip() if approved_summary else None
        if summary is not None and len(summary) > 512:
            raise ValidationError("Approved query summary is too long")
        return await self.create_task(
            session,
            actor_id=actor_id,
            correlation_id=correlation_id,
            study_id=query.study_id,
            site_id=query.site_id,
            title=title or f"Query follow-up {query.id}",
            description="Operational follow-up for an EDC Query",
            owner_id=owner_id,
            due_date=due_date,
            priority=priority,
            query_id=query.id,
            query_summary=summary,
        )

    async def transition_task_status(
        self, session: AsyncSession, task: OperationalTask | UUID, status: OperationalTaskStatus | str,
        actor_id: UUID, *, reason: str | None = None, correlation_id: UUID | str | None = None,
    ) -> OperationalTask:
        task = await self._resolve_task(session, task)
        target = _status(status)
        why = _reason(reason)
        if target not in {item.value for item in OperationalTaskStatus}:
            raise ValidationError("Invalid operational task status")
        if target not in _TASK_TRANSITIONS.get(_status(task.status), set()):
            raise BusinessRuleError("Invalid operational task status transition", {"from": _status(task.status), "to": target})
        if target == OperationalTaskStatus.COMPLETED.value and await self._unresolved_dependencies(session, task.id):
            raise ConflictError("A task cannot be completed while dependencies remain unresolved", {"reason": "DEPENDENCIES_INCOMPLETE"})
        old = _status(task.status)
        task.status = target
        task.updated_by = actor_id
        task.updated_at = datetime.now(UTC)
        await session.flush()
        correlation = _correlation(correlation_id or task.correlation_id)
        await self._record(
            session, entity_type="operational_task", entity_id=task.id, study_id=task.study_id, site_id=task.site_id,
            actor_id=actor_id, correlation_id=correlation, action="status_transition",
            changed_fields=("status",), previous_status=old, status=target, reason=why,
            payload={"query_id": task.query_id},
        )
        if target in _TERMINAL_DEPENDENCY_STATUSES:
            await self._unblock_dependents(session, task.id, actor_id, correlation)
        return task

    async def update_task(
        self, session: AsyncSession, task: OperationalTask | UUID, payload: Mapping[str, Any] | Any,
        actor_id: UUID, *, correlation_id: UUID | str | None = None,
    ) -> OperationalTask:
        task = await self._resolve_task(session, task)
        data = _mapping(payload)
        _safe_payload(data)
        await self._active_user(session, data.get("owner_id"))
        changed: list[str] = []
        for field in ("title", "description", "owner_id", "priority"):
            if field in data:
                value = data[field].strip() if isinstance(data[field], str) else data[field]
                if field == "title" and not value:
                    raise ValidationError("Task title is required")
                if field == "priority":
                    value = _status(value)
                    if value not in {item.value for item in OperationalTaskPriority}:
                        raise ValidationError("Invalid operational task priority")
                setattr(task, field, value)
                changed.append(field)
        if "due_date" in data:
            task.due_date = _utc(data["due_date"])
            changed.append("due_date")
        if not changed:
            raise ValidationError("No mutable operational task fields were supplied")
        task.updated_by = actor_id
        task.updated_at = datetime.now(UTC)
        await session.flush()
        correlation = _correlation(correlation_id or task.correlation_id)
        await self._record(
            session, entity_type="operational_task", entity_id=task.id, study_id=task.study_id, site_id=task.site_id,
            actor_id=actor_id, correlation_id=correlation, action="update", changed_fields=tuple(changed),
            payload={field: getattr(task, field) for field in changed if field in {"owner_id", "priority", "due_date"}},
        )
        if "owner_id" in changed and task.owner_id is not None:
            await notification_service.create_ctms_notification(
                session, user_ids=[task.owner_id], notification_type="ctms_task_assigned",
                payload={"task_id": str(task.id), "study_id": str(task.study_id), "site_id": str(task.site_id) if task.site_id else None},
                study_id=task.study_id, site_id=task.site_id, correlation_id=correlation,
            )
        return task

    async def _resolve_task(self, session: AsyncSession, task: OperationalTask | UUID) -> OperationalTask:
        if isinstance(task, OperationalTask):
            return task
        resolved = await self._one(session, OperationalTask, task)
        if resolved is None:
            raise NotFoundError("Operational task was not found", {"reason": "RECORD_NOT_FOUND"})
        return resolved

    async def create_contact(
        self, session: AsyncSession, payload: Mapping[str, Any] | Any | None = None, actor_id: UUID | None = None,
        *, actor: Any | None = None, correlation_id: UUID | str | None = None, **values: Any,
    ) -> OperationalContact:
        data = _mapping(payload)
        data.update(values)
        _safe_payload(data)
        actor_uuid = _actor(actor, actor_id)
        study_id = data.get("study_id")
        site_id = data.get("site_id")
        try:
            study_id = study_id if isinstance(study_id, UUID) else UUID(str(study_id))
            site_id = site_id if site_id is None or isinstance(site_id, UUID) else UUID(str(site_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Contact scope must use canonical UUIDs") from exc
        await self._scope(session, study_id, site_id)
        owner_id = data.get("owner_id") or actor_uuid
        await self._active_user(session, owner_id)
        status = _status(data.get("status", OperationalContactStatus.ACTIVE))
        if status != OperationalContactStatus.ACTIVE.value:
            raise ValidationError("New operational contacts must start Active")
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValidationError("Contact name is required")
        correlation = _correlation(correlation_id or data.get("correlation_id"), actor)
        contact = OperationalContact(
            study_id=study_id, site_id=site_id, name=name, role=data.get("role"),
            organization=data.get("organization"), channels=dict(data.get("channels") or {}), owner_id=owner_id,
            status=status, retention_state="active", created_by=actor_uuid, updated_by=actor_uuid,
            correlation_id=_correlation_uuid(correlation), created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        session.add(contact)
        await session.flush()
        await self._record(
            session, entity_type="operational_contact", entity_id=contact.id, study_id=study_id, site_id=site_id,
            actor_id=actor_uuid, correlation_id=correlation, action="create",
            changed_fields=("name", "role", "organization", "owner_id", "status"), status=status,
            payload={"owner_id": owner_id},
        )
        if owner_id is not None:
            await notification_service.create_ctms_notification(
                session, user_ids=[owner_id], notification_type="ctms_contact_assigned",
                payload={"contact_id": str(contact.id), "study_id": str(study_id), "site_id": str(site_id) if site_id else None},
                study_id=study_id, site_id=site_id, correlation_id=correlation,
            )
        return contact

    async def transition_contact_status(
        self, session: AsyncSession, contact: OperationalContact | UUID,
        status: OperationalContactStatus | str, actor_id: UUID, *, reason: str | None = None,
        correlation_id: UUID | str | None = None,
    ) -> OperationalContact:
        contact = await self._resolve_contact(session, contact)
        target = _status(status)
        why = _reason(reason)
        if target not in _CONTACT_TRANSITIONS.get(_status(contact.status), set()):
            raise BusinessRuleError("Invalid operational contact status transition", {"from": _status(contact.status), "to": target})
        old = _status(contact.status)
        contact.status = target
        contact.updated_by = actor_id
        contact.updated_at = datetime.now(UTC)
        await session.flush()
        correlation = _correlation(correlation_id or contact.correlation_id)
        await self._record(
            session, entity_type="operational_contact", entity_id=contact.id, study_id=contact.study_id, site_id=contact.site_id,
            actor_id=actor_id, correlation_id=correlation, action="status_transition", changed_fields=("status",),
            previous_status=old, status=target, reason=why,
        )
        return contact

    async def _resolve_contact(self, session: AsyncSession, contact: OperationalContact | UUID) -> OperationalContact:
        if isinstance(contact, OperationalContact):
            return contact
        resolved = await self._one(session, OperationalContact, contact)
        if resolved is None:
            raise NotFoundError("Operational contact was not found", {"reason": "RECORD_NOT_FOUND"})
        return resolved

    async def _dependencies(self, session: AsyncSession, task_id: UUID) -> list[TaskDependency]:
        result = await session.execute(select(TaskDependency).where(TaskDependency.task_id == task_id))
        return [row for row in result.scalars().all() if row.task_id == task_id]

    async def _unresolved_dependencies(self, session: AsyncSession, task_id: UUID) -> list[TaskDependency]:
        dependencies = await self._dependencies(session, task_id)
        unresolved: list[TaskDependency] = []
        for dependency in dependencies:
            prerequisite = await self._one(session, OperationalTask, dependency.depends_on_task_id)
            if prerequisite is None or _status(prerequisite.status) not in _TERMINAL_DEPENDENCY_STATUSES:
                unresolved.append(dependency)
        return unresolved

    async def _would_cycle(self, session: AsyncSession, task_id: UUID, prerequisite_id: UUID) -> bool:
        if task_id == prerequisite_id:
            return True
        visited: set[UUID] = set()
        pending = [prerequisite_id]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == task_id:
                return True
            for dependency in await self._dependencies(session, current):
                pending.append(dependency.depends_on_task_id)
        return False

    async def add_dependency(
        self, session: AsyncSession, task: OperationalTask | UUID, depends_on: OperationalTask | UUID,
        actor_id: UUID, *, reason: str | None = None, correlation_id: UUID | str | None = None,
    ) -> TaskDependency:
        dependent = await self._resolve_task(session, task)
        prerequisite = await self._resolve_task(session, depends_on)
        if dependent.id == prerequisite.id:
            raise ConflictError("A task cannot depend on itself", {"reason": "DEPENDENCY_CYCLE"})
        if dependent.study_id != prerequisite.study_id or dependent.site_id != prerequisite.site_id:
            raise ConflictError("Dependencies must share the task scope", {"reason": "SCOPE_MISMATCH"})
        if await self._would_cycle(session, dependent.id, prerequisite.id):
            raise ConflictError("Dependency would create a cycle", {"reason": "DEPENDENCY_CYCLE"})
        existing = [item for item in await self._dependencies(session, dependent.id) if item.depends_on_task_id == prerequisite.id]
        if existing:
            return existing[0]
        correlation = _correlation(correlation_id or dependent.correlation_id)
        link = TaskDependency(
            task_id=dependent.id, depends_on_task_id=prerequisite.id, created_by=actor_id,
            correlation_id=_correlation_uuid(correlation), created_at=datetime.now(UTC),
        )
        session.add(link)
        await session.flush()
        await self._record(
            session, entity_type="task_dependency", entity_id=link.id, study_id=dependent.study_id, site_id=dependent.site_id,
            actor_id=actor_id, correlation_id=correlation, action="create", changed_fields=("task_id", "depends_on_task_id"),
            reason=_reason(reason, required=False), payload={"task_id": dependent.id, "depends_on_task_id": prerequisite.id},
        )
        if _status(prerequisite.status) not in _TERMINAL_DEPENDENCY_STATUSES and _status(dependent.status) in {
            OperationalTaskStatus.OPEN.value, OperationalTaskStatus.IN_PROGRESS.value
        }:
            await self.transition_task_status(
                session, dependent, OperationalTaskStatus.BLOCKED, actor_id,
                reason=reason or "Blocked by an incomplete prerequisite", correlation_id=correlation,
            )
        return link

    async def remove_dependency(
        self, session: AsyncSession, dependency: TaskDependency | UUID, actor_id: UUID,
        *, reason: str | None = None, correlation_id: UUID | str | None = None,
    ) -> TaskDependency:
        if isinstance(dependency, UUID):
            result = await session.execute(select(TaskDependency).where(TaskDependency.id == dependency))
            dependency = next((row for row in result.scalars().all() if row.id == dependency), None)
        if dependency is None:
            raise NotFoundError("Task dependency was not found", {"reason": "RECORD_NOT_FOUND"})
        dependent = await self._resolve_task(session, dependency.task_id)
        await session.delete(dependency)
        await session.flush()
        correlation = _correlation(correlation_id or dependent.correlation_id)
        await self._record(
            session, entity_type="task_dependency", entity_id=dependency.id, study_id=dependent.study_id, site_id=dependent.site_id,
            actor_id=actor_id, correlation_id=correlation, action="delete", changed_fields=("dependency",),
            reason=_reason(reason), payload={"task_id": dependent.id},
        )
        if _status(dependent.status) == OperationalTaskStatus.BLOCKED.value and not await self._unresolved_dependencies(session, dependent.id):
            await self.transition_task_status(session, dependent, OperationalTaskStatus.OPEN, actor_id, reason="All prerequisites are complete", correlation_id=correlation)
        return dependency

    async def _unblock_dependents(self, session: AsyncSession, prerequisite_id: UUID, actor_id: UUID, correlation: str) -> None:
        result = await session.execute(select(TaskDependency).where(TaskDependency.depends_on_task_id == prerequisite_id))
        links = [row for row in result.scalars().all() if row.depends_on_task_id == prerequisite_id]
        for link in links:
            dependent = await self._one(session, OperationalTask, link.task_id)
            if dependent is not None and _status(dependent.status) == OperationalTaskStatus.BLOCKED.value and not await self._unresolved_dependencies(session, dependent.id):
                await self.transition_task_status(session, dependent, OperationalTaskStatus.OPEN, actor_id, reason="All prerequisites are complete", correlation_id=correlation)

    async def create_escalation(
        self, session: AsyncSession, payload: Mapping[str, Any] | Any, actor_id: UUID,
        *, correlation_id: UUID | str | None = None,
    ) -> TaskEscalation:
        if not self.escalations_enabled:
            raise BusinessRuleError("Escalations are disabled for this Environment", {"reason": "CAPABILITY_DISABLED"})
        data = _mapping(payload)
        _safe_payload(data)
        task = await self._resolve_task(session, data.get("task_id"))
        await self._active_user(session, data.get("owner_id"))
        reason = _reason(data.get("reason"))
        status = _status(data.get("status", EscalationStatus.OPEN))
        if status != EscalationStatus.OPEN.value:
            raise ValidationError("New escalations must start Open")
        correlation = _correlation(correlation_id or task.correlation_id)
        escalation = TaskEscalation(
            task_id=task.id, owner_id=data.get("owner_id"), status=status, reason=reason,
            deadline=_utc(data.get("deadline")), created_by=actor_id, updated_by=actor_id,
            correlation_id=_correlation_uuid(correlation), created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        session.add(escalation)
        await session.flush()
        await self._record(
            session, entity_type="task_escalation", entity_id=escalation.id, study_id=task.study_id, site_id=task.site_id,
            actor_id=actor_id, correlation_id=correlation, action="create", changed_fields=("task_id", "owner_id", "status", "reason", "deadline"),
            status=status, reason=reason, payload={"task_id": task.id, "owner_id": data.get("owner_id"), "deadline": data.get("deadline")},
        )
        if escalation.owner_id is not None:
            await notification_service.create_ctms_notification(
                session, user_ids=[escalation.owner_id], notification_type="ctms_task_escalated",
                payload={"task_id": str(task.id), "escalation_id": str(escalation.id), "study_id": str(task.study_id)},
                study_id=task.study_id, site_id=task.site_id, correlation_id=correlation,
            )
        return escalation

    async def transition_escalation_status(
        self, session: AsyncSession, escalation: TaskEscalation | UUID, status: EscalationStatus | str,
        actor_id: UUID, *, reason: str | None = None, correlation_id: UUID | str | None = None,
    ) -> TaskEscalation:
        if not self.escalations_enabled:
            raise BusinessRuleError("Escalations are disabled for this Environment", {"reason": "CAPABILITY_DISABLED"})
        if isinstance(escalation, UUID):
            escalation = await self._one(session, TaskEscalation, escalation)
        if escalation is None:
            raise NotFoundError("Escalation was not found", {"reason": "RECORD_NOT_FOUND"})
        task = await self._resolve_task(session, escalation.task_id)
        target = _status(status)
        why = _reason(reason)
        if target not in _ESCALATION_TRANSITIONS.get(_status(escalation.status), set()):
            raise BusinessRuleError("Invalid escalation status transition", {"from": _status(escalation.status), "to": target})
        old = _status(escalation.status)
        escalation.status = target
        escalation.updated_by = actor_id
        escalation.updated_at = datetime.now(UTC)
        await session.flush()
        correlation = _correlation(correlation_id or escalation.correlation_id)
        await self._record(
            session, entity_type="task_escalation", entity_id=escalation.id, study_id=task.study_id, site_id=task.site_id,
            actor_id=actor_id, correlation_id=correlation, action="status_transition", changed_fields=("status",),
            previous_status=old, status=target, reason=why,
        )
        return escalation

    async def process_reminders(self, session: AsyncSession, *, now: datetime | None = None, actor_id: UUID | None = None) -> int:
        """Create bounded overdue and dependency reminders for operational owners."""
        timestamp = _utc(now or datetime.now(UTC))
        result = await session.execute(select(OperationalTask))
        tasks = [task for task in result.scalars().all() if _status(task.status) not in _TERMINAL_DEPENDENCY_STATUSES]
        reminded = 0
        for task in tasks:
            overdue = task.due_date is not None and task.due_date <= timestamp
            blocked = _status(task.status) == OperationalTaskStatus.BLOCKED.value
            if not (overdue or blocked) or task.owner_id is None:
                continue
            notification_type = "ctms_task_overdue" if overdue else "ctms_task_dependency_reminder"
            await notification_service.create_ctms_notification(
                session, user_ids=[task.owner_id], notification_type=notification_type,
                payload={"task_id": str(task.id), "study_id": str(task.study_id), "site_id": str(task.site_id) if task.site_id else None},
                study_id=task.study_id, site_id=task.site_id, correlation_id=str(task.correlation_id),
            )
            reminded += 1
        return reminded


work_management_service = WorkManagementService()

__all__ = ["WorkManagementService", "work_management_service"]
