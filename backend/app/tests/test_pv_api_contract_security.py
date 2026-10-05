"""PV API contract, security, and permission tests (Task 8.5).

**Validates: Requirements 1.3, 2.1, 2.2, 2.3, 2.4, 16.3, 16.6, 23.4, 23.5**

These tests exercise the real FastAPI application (``create_app``) with an
in-memory SQLite database and the shared PV authorization dependency. They
complement the existing PV route/authorization/observability suites rather than
duplicating them:

  - ``test_pv_api_routes.py`` covers happy-path wiring, one viewer denial, one
    unauthenticated denial, and a small OpenAPI path list.
  - ``test_pv_task_1_3_api_contracts.py`` covers the shared request-ID /
    pagination / sanitization contracts against a *minimal* app.
  - ``test_pv_authorization.py`` and ``test_property_pv_authorization_scope.py``
    cover the guard/scope logic against *stub* identities.

This file adds the through-the-real-API contract, security, and permission
coverage required by task 8.5:

  - OpenAPI *publication* of PV enums, error codes, pagination schemas, error
    responses, and the absence of EDC/CTMS mutation paths on the PV router;
  - authentication rejection for missing and invalid tokens, non-disclosing;
  - authorization scoping (403 ``PV_SCOPE_DENIED``) across every PV role,
    out-of-scope reads, viewer mutations, inactive users, and after scope
    removal, each leaving PV / audit / export / projection state unchanged;
  - the sanitized error envelope across representative failure modes with no
    stack traces, DB errors, prohibited safety data, raw payloads, or
    credentials, and no resource existence disclosure;
  - ``X-Request-ID`` echo on success and every failure mode;
  - EDC/CTMS-owned field injection and duplicate-identifier rejection;
  - the cross-module ownership boundary: no PV route mutates an EDC clinical or
    CTMS operational record.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.database import Base
from app.core.openapi import PV_ERROR_RESPONSES
from app.core.permissions import PV_PERMISSION_CODES, ROLE_DEFINITIONS
from app.core.pv import CaseState as CoreCaseState
from app.core.pv import ReportStatus as CoreReportStatus
from app.core.security import create_access_token
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.models.pv.coordination import CoordinationRef, EdcAeProjection
from app.models.pv.reconciliation import ReconciliationDiscrepancy, ReconciliationRun
from app.models.pv.safety_case import SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.schemas.pv.contracts import PV_MAX_PAGE_SIZE, PVErrorCode
from app.schemas.pv.export import PVExportCreate, PVExportFilters
from app.schemas.pv.resources import (
    AdverseEventCreate,
    CaseChangeRequest,
    CaseTransitionRequest,
    CausalityRequest,
    ExpectednessRequest,
    MedDraCodingRequest,
    NarrativeCreate,
    NarrativeRevise,
    RecodeRequest,
    ReconciliationRunRequest,
    ReportabilityRequest,
    ReportSubmitRequest,
    ReportTransitionRequest,
    SafetyAttachmentDeleteRequest,
    SafetyCaseCreate,
    SeriousnessRequest,
    SeverityRequest,
    WhoDrugCodingRequest,
)

# ---------------------------------------------------------------------------
# Fixtures: real app, in-memory DB, and seeded identity/scope (mirrors
# test_pv_api_routes.py so behavior is exercised through the same wiring).
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401 - register every mapped model

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.commit()


def _role_with_permissions(name: str, codes, permissions: dict[str, Permission]) -> Role:
    role = Role(id=uuid4(), name=f"{name} {uuid4()}", scope_level="system", is_system=True)
    return role


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, Any]:
    """Seed canonical identity plus a set of PV users at various scopes.

    Users created:
      - ``safety_user``: system-scoped, holds every PV permission;
      - ``viewer``: holds only ``safety_case.read`` (read-only);
      - ``study_b_user``: full PV permissions but scoped to a *different* study
        (out-of-scope for the seeded study);
      - ``inactive_user``: full PV permissions but status inactive;
      - ``scoped_user``: full PV permissions scoped to the seeded study;
      - ``no_role_user``: authenticates but holds no PV role at all.
    """

    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    permissions = {
        code: Permission(id=uuid4(), code=code, description=code)
        for code in PV_PERMISSION_CODES
    }
    db_session.add_all(permissions.values())

    safety_role = Role(
        id=uuid4(), name=f"Safety Admin {uuid4()}", scope_level="system", is_system=True
    )
    viewer_role = Role(
        id=uuid4(), name=f"Safety Viewer {uuid4()}", scope_level="system", is_system=True
    )
    study_scoped_role = Role(
        id=uuid4(), name=f"Safety Manager {uuid4()}", scope_level="study", is_system=True
    )
    db_session.add_all([safety_role, viewer_role, study_scoped_role])
    await db_session.flush()

    db_session.add_all(
        [
            RolePermission(role_id=safety_role.id, permission_id=permission.id)
            for permission in permissions.values()
        ]
        + [
            RolePermission(
                role_id=viewer_role.id, permission_id=permissions["safety_case.read"].id
            )
        ]
        + [
            RolePermission(role_id=study_scoped_role.id, permission_id=permission.id)
            for permission in permissions.values()
        ]
    )

    def _user(prefix: str, status: UserStatus = UserStatus.active) -> User:
        return User(
            id=uuid4(), email=f"{prefix}-{uuid4()}@example.test", first_name="PV",
            last_name=prefix, status=status, last_activity=now,
        )

    safety_user = _user("admin")
    viewer = _user("viewer")
    study_b_user = _user("studyb")
    inactive_user = _user("inactive", status=UserStatus.inactive)
    scoped_user = _user("scoped")
    no_role_user = _user("norole")
    db_session.add_all(
        [safety_user, viewer, study_b_user, inactive_user, scoped_user, no_role_user]
    )
    await db_session.flush()

    study = Study(
        id=uuid4(), study_code=f"PV-{uuid4()}", title="Safety study",
        status=StudyStatus.active, created_by=safety_user.id, created_at=now,
    )
    other_study = Study(
        id=uuid4(), study_code=f"PV-{uuid4()}", title="Other study",
        status=StudyStatus.active, created_by=safety_user.id, created_at=now,
    )
    db_session.add_all([study, other_study])
    await db_session.flush()

    db_session.add_all(
        [
            UserRole(user_id=safety_user.id, role_id=safety_role.id),
            UserRole(user_id=viewer.id, role_id=viewer_role.id),
            # study_b_user is scoped to other_study only -> out of scope here.
            UserRole(
                user_id=study_b_user.id,
                role_id=study_scoped_role.id,
                study_id=other_study.id,
            ),
            UserRole(user_id=inactive_user.id, role_id=safety_role.id),
            UserRole(
                user_id=scoped_user.id,
                role_id=study_scoped_role.id,
                study_id=study.id,
            ),
            # no_role_user intentionally has no role assignment.
        ]
    )

    version = StudyVersion(
        id=uuid4(), study_id=study.id, version_number="1.0",
        status=StudyVersionStatus.published, published_at=now,
        published_by=safety_user.id, created_at=now,
    )
    site = Site(
        id=uuid4(), study_id=study.id, site_number="001", name="Site A", created_at=now,
    )
    db_session.add_all([version, site])
    await db_session.flush()

    subject = Subject(
        id=uuid4(), study_id=study.id, site_id=site.id, study_version_id=version.id,
        subject_number="S-001", created_by=safety_user.id, created_at=now,
    )
    db_session.add(subject)
    await db_session.commit()

    return {
        "safety_user": safety_user,
        "viewer": viewer,
        "study_b_user": study_b_user,
        "inactive_user": inactive_user,
        "scoped_user": scoped_user,
        "no_role_user": no_role_user,
        "study": study,
        "other_study": other_study,
        "site": site,
        "subject": subject,
        "version": version,
    }


@pytest.fixture
def app(async_engine):
    application = create_app()

    async def override_get_db():
        factory = async_sessionmaker(
            bind=async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _case_payload(seeded: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload = {
        "study_id": str(seeded["study"].id),
        "site_id": str(seeded["site"].id),
        "subject_reference": str(seeded["subject"].id),
        "case_type": "Adverse Event",
    }
    payload.update(overrides)
    return payload


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def _create_case(client: AsyncClient, seeded: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/pv/cases",
        json=_case_payload(seeded),
        headers=_auth(seeded["safety_user"]),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assert_error_envelope(body: dict[str, Any]) -> dict[str, Any]:
    assert isinstance(body.get("error"), dict), body
    error = body["error"]
    assert {"code", "message", "details"}.issubset(error), error
    return error


# Content that must never appear in any PV error/response body.
_LEAK_TOKENS = (
    "traceback",
    "sqlalchemy",
    "psycopg",
    "select ",
    "password",
    "secret",
    "postgres://",
    "postgresql://",
)


def _assert_no_leakage(text: str) -> None:
    lowered = text.lower()
    for token in _LEAK_TOKENS:
        assert token not in lowered, f"leaked sensitive token: {token!r}"


# ===========================================================================
# 1. OpenAPI contract publication
# ===========================================================================


class TestPVOpenAPIPublication:
    """16.3 / 23.4 / 23.5: PV contract is fully published under /api/v1/pv."""

    def test_pv_enums_error_codes_and_pagination_published(self, app):
        schema = app.openapi()
        info = schema["info"]

        # Every PV error code enum value is published in the vocabulary.
        published_error_codes = set(info["x-pv-error-codes"])
        for code in PVErrorCode:
            assert code.value in published_error_codes, code

        # PV enum values (case state, report status) are published.
        pv_enums = info["x-pv-enums"]
        for state in CoreCaseState:
            assert state.value in pv_enums["case_state"], state
        for status in CoreReportStatus:
            assert status.value in pv_enums["report_status"], status
        assert set(pv_enums["pv_error_code"]) == {c.value for c in PVErrorCode}

        # The PV pagination contract advertises the 1..1000 page-size range.
        pagination = info["x-pv-pagination"]
        assert pagination["schema"] == "PVPaginationContract"
        assert pagination["properties"]["page"]["minimum"] == 1
        assert pagination["properties"]["page_size"]["minimum"] == 1
        assert pagination["properties"]["page_size"]["maximum"] == PV_MAX_PAGE_SIZE

        # The component schemas are registered for client generation.
        component_schemas = schema["components"]["schemas"]
        assert "PVPaginationContract" in component_schemas
        assert "PVErrorCode" in component_schemas

    def test_pv_error_responses_are_published_for_failure_statuses(self, app):
        schema = app.openapi()
        published = schema["info"]["x-pv-error-responses"]
        for status_code in (400, 401, 403, 404, 409, 422, 500, 503):
            assert str(status_code) in published, status_code
        # The published set matches the PV error-response registry.
        assert set(published) == {str(code) for code in PV_ERROR_RESPONSES}

    def test_pv_router_exposes_no_edc_or_ctms_mutation_paths(self, app):
        """23.4 / 23.5: no PV path targets an EDC clinical or CTMS record."""
        schema = app.openapi()
        pv_paths = [p for p in schema["paths"] if p.startswith("/api/v1/pv")]
        assert pv_paths, "PV routes must be mounted"

        forbidden_fragments = (
            "/subjects",
            "/visits",
            "/queries",
            "/forms",
            "/field-values",
            "/signatures",
            "/sdv",
            "/locks",
            "/clinical",
            "/ctms",
            "/operational",
            "/study-versions",
        )
        for path in pv_paths:
            for fragment in forbidden_fragments:
                assert fragment not in path, f"{path} exposes {fragment}"

    def test_pv_paginated_list_routes_use_pagination_envelope(self, app):
        """16.3: PV list responses publish the {items,page,page_size,total} shape."""
        schema = app.openapi()
        listing = schema["paths"]["/api/v1/pv/cases"]["get"]
        content = listing["responses"]["200"]["content"]["application/json"]["schema"]
        ref = content.get("$ref", "")
        model_name = ref.rsplit("/", 1)[-1] if ref else ""
        model = schema["components"]["schemas"].get(model_name, content)
        assert {"items", "page", "page_size", "total"}.issubset(model["properties"])

    def test_pv_openapi_paths_and_methods_match_snapshot(self, app):
        """16.3 / 23.4 / 23.5: the versioned PV surface is stable and additive."""
        schema = app.openapi()
        actual = {
            path: sorted(set(operation).intersection({"get", "post", "patch", "put", "delete"}))
            for path, operation in schema["paths"].items()
            if path.startswith("/api/v1/pv")
        }
        expected = {
            "/api/v1/pv/adverse-events/{ae_id}/causality": ["post"],
            "/api/v1/pv/adverse-events/{ae_id}/expectedness": ["post"],
            "/api/v1/pv/adverse-events/{ae_id}/meddra-codings": ["post"],
            "/api/v1/pv/adverse-events/{ae_id}/seriousness": ["post"],
            "/api/v1/pv/adverse-events/{ae_id}/severity": ["post"],
            "/api/v1/pv/attachments/{attachment_id}": ["delete"],
            "/api/v1/pv/attachments/{attachment_id}/download": ["get"],
            "/api/v1/pv/audit/events": ["get"],
            "/api/v1/pv/audit/exports": ["post"],
            "/api/v1/pv/capabilities": ["get"],
            "/api/v1/pv/cases": ["get", "post"],
            "/api/v1/pv/cases/{case_id}": ["get"],
            "/api/v1/pv/cases/{case_id}/adverse-events": ["get", "post"],
            "/api/v1/pv/cases/{case_id}/attachments": ["post"],
            "/api/v1/pv/cases/{case_id}/changes": ["post"],
            "/api/v1/pv/cases/{case_id}/narratives": ["post"],
            "/api/v1/pv/cases/{case_id}/reportability": ["post"],
            "/api/v1/pv/cases/{case_id}/reports": ["get"],
            "/api/v1/pv/cases/{case_id}/transition": ["post"],
            "/api/v1/pv/cases/{case_id}/versions": ["post"],
            "/api/v1/pv/codings/{prior_coding_id}/recode": ["post"],
            "/api/v1/pv/exports/{export_id}": ["get"],
            "/api/v1/pv/exports/{export_id}/download": ["get"],
            "/api/v1/pv/health": ["get"],
            "/api/v1/pv/icsr/import": ["post"],
            "/api/v1/pv/icsr/produce": ["post"],
            "/api/v1/pv/metrics": ["get"],
            "/api/v1/pv/narratives/{narrative_id}": ["get"],
            "/api/v1/pv/narratives/{narrative_id}/revisions": ["post"],
            "/api/v1/pv/narratives/{narrative_id}/versions": ["get"],
            "/api/v1/pv/ready": ["get"],
            "/api/v1/pv/reconciliation/discrepancies/{discrepancy_id}/resolve": ["post"],
            "/api/v1/pv/reconciliation/runs": ["post"],
            "/api/v1/pv/reconciliation/runs/{run_id}": ["get"],
            "/api/v1/pv/reports/{report_id}": ["get"],
            "/api/v1/pv/reports/{report_id}/submit": ["post"],
            "/api/v1/pv/reports/{report_id}/transition": ["post"],
            "/api/v1/pv/sites/{site_id}/dashboard": ["get"],
            "/api/v1/pv/studies/{study_id}/dashboard": ["get"],
            "/api/v1/pv/studies/{study_id}/exports": ["get", "post"],
            "/api/v1/pv/whodrug-codings": ["post"],
        }
        assert actual == expected

    def test_pv_resources_are_pydantic_v2_models_and_published(self, app):
        """16.3: request/response contracts use Pydantic v2 and appear in OpenAPI."""
        schema_names = set(app.openapi()["components"]["schemas"])
        models = (
            SafetyCaseCreate,
            AdverseEventCreate,
            CaseTransitionRequest,
            CaseChangeRequest,
            SeriousnessRequest,
            CausalityRequest,
            ExpectednessRequest,
            SeverityRequest,
            MedDraCodingRequest,
            WhoDrugCodingRequest,
            RecodeRequest,
            NarrativeCreate,
            NarrativeRevise,
            ReportabilityRequest,
            ReportTransitionRequest,
            ReportSubmitRequest,
            ReconciliationRunRequest,
            SafetyAttachmentDeleteRequest,
            PVExportCreate,
            PVExportFilters,
        )
        for model in models:
            assert issubclass(model, PydanticBaseModel)
            assert callable(model.model_json_schema)
            assert model.__name__ in schema_names
            # Every request model rejects unknown fields from EDC/CTMS payloads.
            assert model.model_config.get("extra") == "forbid", model.__name__

        for model_name in (
            "SafetyCaseResponse",
            "AdverseEventResponse",
            "AssessmentResponse",
            "CodingResponse",
            "NarrativeResponse",
            "RegulatoryReportResponse",
            "ReconciliationRunResponse",
            "SafetyAttachmentResponse",
            "PVExportResponse",
            "PVPaginationContract",
            "PVErrorCode",
        ):
            assert model_name in schema_names


# ===========================================================================
# 2. Authentication rejection (401), non-disclosing
# ===========================================================================


class TestPVAuthentication:
    @pytest.mark.asyncio
    async def test_missing_token_is_rejected_with_request_id(self, client, seeded):
        """1.3 / 16.6: an unauthenticated read is rejected and echoes X-Request-ID."""
        response = await client.get(
            "/api/v1/pv/cases", params={"study_id": str(seeded["study"].id)}
        )
        assert response.status_code == 401, response.text
        assert response.headers.get("X-Request-ID")
        error = _assert_error_envelope(response.json())
        # Non-disclosing: no study/site/object detail is revealed.
        assert "study_id" not in error["details"]
        _assert_no_leakage(response.text)

    @pytest.mark.asyncio
    async def test_invalid_token_is_rejected_non_disclosing(self, client, seeded):
        """1.3: a malformed/invalid bearer token is rejected without disclosure."""
        response = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded),
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert response.status_code == 401, response.text
        assert response.headers.get("X-Request-ID")
        error = _assert_error_envelope(response.json())
        # The message names no internal token detail beyond a generic reason.
        assert "invalid" in error["message"].lower() or "auth" in error["message"].lower()
        _assert_no_leakage(response.text)

    @pytest.mark.asyncio
    async def test_token_for_unknown_user_is_rejected(self, client):
        """1.3: a well-formed token for a nonexistent user is rejected."""
        response = await client.get(
            "/api/v1/pv/cases",
            params={"study_id": str(uuid4())},
            headers={"Authorization": f"Bearer {create_access_token(uuid4())}"},
        )
        assert response.status_code == 401, response.text
        assert response.headers.get("X-Request-ID")


# ===========================================================================
# 3. Authorization scoping (403 PV_SCOPE_DENIED), no state change
# ===========================================================================


class TestPVAuthorizationScoping:
    @pytest.mark.asyncio
    async def test_viewer_cannot_mutate_and_state_is_unchanged(
        self, client, db_session, seeded
    ):
        """2.1 / 2.2: a read-only user is denied a mutation with no state change."""
        before_cases = await _count(db_session, SafetyCase)
        before_audit = await _count(db_session, AuditEvent)

        response = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded),
            headers=_auth(seeded["viewer"]),
        )
        assert response.status_code == 403, response.text
        error = _assert_error_envelope(response.json())
        assert error["details"].get("reason") == PVErrorCode.PV_SCOPE_DENIED.value

        assert await _count(db_session, SafetyCase) == before_cases
        assert await _count(db_session, AuditEvent) == before_audit

    @pytest.mark.asyncio
    async def test_out_of_scope_study_user_is_denied(self, client, db_session, seeded):
        """2.3: a user scoped to another study cannot mutate in this study."""
        before = await _count(db_session, SafetyCase)
        response = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded),
            headers=_auth(seeded["study_b_user"]),
        )
        assert response.status_code == 403, response.text
        error = _assert_error_envelope(response.json())
        assert error["details"].get("reason") == PVErrorCode.PV_SCOPE_DENIED.value
        assert await _count(db_session, SafetyCase) == before

    @pytest.mark.asyncio
    async def test_user_without_any_pv_role_is_denied(self, client, seeded):
        """2.1: an authenticated user with no PV role is denied every PV op."""
        response = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded),
            headers=_auth(seeded["no_role_user"]),
        )
        assert response.status_code == 403, response.text
        error = _assert_error_envelope(response.json())
        assert error["details"].get("reason") == PVErrorCode.PV_SCOPE_DENIED.value

    @pytest.mark.asyncio
    async def test_inactive_user_is_rejected(self, client, seeded):
        """2.x: an inactive account is rejected even though it holds the role."""
        response = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded),
            headers=_auth(seeded["inactive_user"]),
        )
        # Inactive accounts fail authentication (401), never proceed to mutate.
        assert response.status_code == 401, response.text
        assert response.headers.get("X-Request-ID")

    @pytest.mark.asyncio
    async def test_denied_reads_never_disclose_object_existence(self, client, seeded):
        """2.4 / 16.6: a denied read does not reveal whether a record exists."""
        case = await _create_case(client, seeded)
        # study_b_user is out of scope; reading a real case id must be denied
        # with the same non-disclosing envelope as an unknown id.
        real = await client.get(
            f"/api/v1/pv/cases/{case['id']}", headers=_auth(seeded["study_b_user"])
        )
        missing = await client.get(
            f"/api/v1/pv/cases/{uuid4()}", headers=_auth(seeded["study_b_user"])
        )
        # Neither response discloses the case's study/site or existence detail.
        for response in (real, missing):
            assert response.status_code in {403, 404}, response.text
            error = _assert_error_envelope(response.json())
            assert "study_id" not in error["details"]
            assert "site_id" not in error["details"]
            _assert_no_leakage(response.text)

    @pytest.mark.asyncio
    async def test_role_definitions_carry_no_edc_or_ctms_mutation_permission(self):
        """2.6 / 23.4: no seeded PV role can hold an EDC/CTMS mutation permission."""
        pv_role_names = {
            "Safety_Admin",
            "Safety_Manager",
            "Safety_Associate",
            "Safety_Physician",
            "Safety_Coder",
            "Regulatory_Reporter",
            "Safety_Viewer",
        }
        for name in pv_role_names:
            perms = set(ROLE_DEFINITIONS[name]["permissions"])
            assert perms <= PV_PERMISSION_CODES, name


# ===========================================================================
# 4. Sanitized error envelope + X-Request-ID across failure modes
# ===========================================================================


class TestPVSanitizedErrorEnvelope:
    @pytest.mark.asyncio
    async def test_representative_failure_modes_use_sanitized_envelope(
        self, client, seeded
    ):
        """16.3: every failure mode returns the sanitized envelope + request id."""
        headers = _auth(seeded["safety_user"])
        case = await _create_case(client, seeded)

        # (a) 422 schema validation: missing required fields.
        schema_error = await client.post("/api/v1/pv/cases", json={}, headers=headers)
        # (b) 400/409/422 business rule: resolution earlier than onset.
        business_error = await client.post(
            f"/api/v1/pv/cases/{case['id']}/adverse-events",
            json={
                "verbatim_term": "Rash",
                "onset_date": "2025-02-01",
                "outcome": "Ongoing",
                "resolution_date": "2025-01-01",
            },
            headers=headers,
        )
        # (c) 404 not found: unknown case id.
        not_found = await client.get(
            f"/api/v1/pv/cases/{uuid4()}", headers=headers
        )
        # (d) 422 verbatim too long (>200 chars).
        too_long = await client.post(
            f"/api/v1/pv/cases/{case['id']}/adverse-events",
            json={
                "verbatim_term": "x" * 201,
                "onset_date": "2025-01-02",
                "outcome": "Recovered",
            },
            headers=headers,
        )

        for response, expected in (
            (schema_error, {422}),
            (business_error, {400, 409, 422}),
            (not_found, {404}),
            (too_long, {422}),
        ):
            assert response.status_code in expected, response.text
            assert response.headers.get("X-Request-ID")
            _assert_error_envelope(response.json())
            _assert_no_leakage(response.text)

    @pytest.mark.asyncio
    async def test_success_response_echoes_request_id(self, client, seeded):
        """16.6: the request identifier is echoed on a successful PV response."""
        response = await client.get(
            "/api/v1/pv/cases",
            params={"study_id": str(seeded["study"].id)},
            headers=_auth(seeded["safety_user"]),
        )
        assert response.status_code == 200, response.text
        assert response.headers.get("X-Request-ID")

    @pytest.mark.asyncio
    async def test_provided_request_id_is_propagated(self, client, seeded):
        """16.6: a caller-provided X-Request-ID is echoed back unchanged."""
        headers = _auth(seeded["safety_user"]) | {"X-Request-ID": "pv-contract-abc"}
        response = await client.get(
            "/api/v1/pv/cases",
            params={"study_id": str(seeded["study"].id)},
            headers=headers,
        )
        assert response.headers.get("X-Request-ID") == "pv-contract-abc"

    @pytest.mark.asyncio
    async def test_logs_and_errors_redact_credentials_and_projection_payloads(
        self, client, seeded, caplog
    ):
        """16.3: failures and structured PV logs never contain secrets/raw payloads."""
        caplog.clear()
        secret_token = "Bearer secret-password-token"
        raw_projection = {
            "study_id": str(seeded["study"].id),
            "raw_coordination_payload": {
                "clinical_subject_identifier": "SUBJECT-PRIVATE",
                "password": "secret-value",
            },
        }
        response = await client.post(
            "/api/v1/pv/reconciliation/runs",
            json=raw_projection,
            headers={"Authorization": secret_token},
        )
        assert response.status_code in {401, 403, 422}
        combined = f"{response.text}\\n{caplog.text}"
        _assert_no_leakage(combined)
        assert secret_token not in combined
        assert "SUBJECT-PRIVATE" not in combined
        assert "raw_coordination_payload" not in combined



class TestPVSecurityInjectionAndBoundary:
    @pytest.mark.asyncio
    async def test_edc_and_ctms_field_injection_is_rejected(
        self, client, db_session, seeded
    ):
        """16.6 / 23.4: an EDC/CTMS-owned field in a PV payload is rejected."""
        headers = _auth(seeded["safety_user"])
        before = await _count(db_session, SafetyCase)

        for injected in (
            {"study_version_id": str(uuid4())},
            {"visit_instance_id": str(uuid4())},
            {"form_instance_id": str(uuid4())},
            {"clinical_subject_id": str(uuid4())},
            {"operational_site_id": str(uuid4())},
            {"query_id": str(uuid4())},
            # Projection fields are not writable through any PV command.
            {"raw_coordination_payload": {"verbatim_term": "clinical"}},
            {"edc_projection": {"subject_reference": str(uuid4())}},
            {"clinical_subject_identifier": "SUBJECT-PRIVATE"},
        ):
            response = await client.post(
                "/api/v1/pv/cases",
                json=_case_payload(seeded, **injected),
                headers=headers,
            )
            # extra="forbid" on the request schema rejects the unknown field.
            assert response.status_code == 422, (injected, response.text)
            _assert_error_envelope(response.json())

        # No safety case was created by any injection attempt.
        assert await _count(db_session, SafetyCase) == before

    @pytest.mark.asyncio
    async def test_duplicate_case_identifier_is_rejected(
        self, client, db_session, seeded
    ):
        """23.4: a duplicate globally unique case identifier is rejected."""
        headers = _auth(seeded["safety_user"])
        identifier = f"CASE-{uuid4()}"

        first = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded, case_identifier=identifier),
            headers=headers,
        )
        assert first.status_code == 201, first.text
        before = await _count(db_session, SafetyCase)

        duplicate = await client.post(
            "/api/v1/pv/cases",
            json=_case_payload(seeded, case_identifier=identifier),
            headers=headers,
        )
        assert duplicate.status_code in {400, 409, 422}, duplicate.text
        _assert_error_envelope(duplicate.json())
        _assert_no_leakage(duplicate.text)
        # The duplicate created no additional case.
        assert await _count(db_session, SafetyCase) == before


# ===========================================================================
# 6. Ownership boundary: no PV mutation route for EDC/CTMS records
# ===========================================================================


_OWNED_MODELS = (
    SafetyCase,
    AuditEvent,
    FileAttachment,
    Export,
    EdcAeProjection,
    CoordinationRef,
    ReconciliationRun,
    ReconciliationDiscrepancy,
    Subject,
    StudyVersion,
)


async def _snapshot(session: AsyncSession) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for model in _OWNED_MODELS:
        rows = list((await session.scalars(select(model))).all())
        columns = [c.key for c in inspect(model).mapper.column_attrs]
        encoded = [tuple((c, repr(getattr(row, c))) for c in columns) for row in rows]
        snapshot[model.__tablename__] = tuple(sorted(encoded))
    return snapshot


class TestPVDirectPermissionStateBoundaries:
    @pytest.mark.asyncio
    async def test_role_denials_preserve_all_pv_and_cross_module_state(
        self, client, db_session, seeded
    ):
        """1.3 / 2.1-2.4: every denied API operation is side-effect free."""
        case = await _create_case(client, seeded)
        before = await _snapshot(db_session)
        study_id = str(seeded["study"].id)
        case_id = case["id"]

        attempts = [
            # Viewer can read but cannot create cases, exports, reconciliation,
            # or safety attachments.
            client.post(
                "/api/v1/pv/cases",
                json=_case_payload(seeded),
                headers=_auth(seeded["viewer"]),
            ),
            client.post(
                f"/api/v1/pv/studies/{study_id}/exports",
                json={"export_type": "csv", "filters": {}},
                headers=_auth(seeded["viewer"]),
            ),
            client.post(
                "/api/v1/pv/reconciliation/runs",
                json={"study_id": study_id},
                headers=_auth(seeded["viewer"]),
            ),
            client.post(
                f"/api/v1/pv/cases/{case_id}/attachments",
                files={"file": ("private.txt", b"private", "text/plain")},
                headers=_auth(seeded["viewer"]),
            ),
            # An authenticated user scoped to another study cannot perform the
            # same operations against this study.
            client.post(
                "/api/v1/pv/cases",
                json=_case_payload(seeded),
                headers=_auth(seeded["study_b_user"]),
            ),
            client.post(
                f"/api/v1/pv/studies/{study_id}/exports",
                json={"export_type": "csv", "filters": {}},
                headers=_auth(seeded["study_b_user"]),
            ),
            client.post(
                "/api/v1/pv/reconciliation/runs",
                json={"study_id": study_id},
                headers=_auth(seeded["study_b_user"]),
            ),
            # Inactive users are rejected before any PV dependency executes.
            client.get(
                "/api/v1/pv/cases",
                params={"study_id": study_id},
                headers=_auth(seeded["inactive_user"]),
            ),
        ]
        responses = await asyncio.gather(*attempts)
        for response in responses:
            assert response.status_code in {401, 403}, response.text
            _assert_error_envelope(response.json())
        assert await _snapshot(db_session) == before

    @pytest.mark.asyncio
    async def test_removed_study_scope_denies_reads_without_state_change(
        self, client, db_session, seeded
    ):
        """2.1-2.4: removing a live grant immediately denies direct API access."""
        study_id = str(seeded["study"].id)
        headers = _auth(seeded["scoped_user"])
        allowed = await client.get(
            "/api/v1/pv/cases", params={"study_id": study_id}, headers=headers
        )
        assert allowed.status_code == 200, allowed.text

        before = await _snapshot(db_session)
        await db_session.execute(
            delete(UserRole).where(UserRole.user_id == seeded["scoped_user"].id)
        )
        await db_session.commit()

        denied = await client.get(
            "/api/v1/pv/cases", params={"study_id": study_id}, headers=headers
        )
        assert denied.status_code == 403, denied.text
        error = _assert_error_envelope(denied.json())
        assert error["details"].get("reason") == PVErrorCode.PV_SCOPE_DENIED.value
        assert "study_id" not in error["details"]
        assert "site_id" not in error["details"]
        assert await _snapshot(db_session) == before


class TestPVOwnershipBoundary:
    @pytest.mark.asyncio
    async def test_no_pv_route_mutates_edc_or_ctms_records(
        self, client, db_session, seeded
    ):
        """23.4 / 23.5: PV publishes no route that writes an EDC/CTMS record."""
        before = await _snapshot(db_session)
        headers = _auth(seeded["safety_user"])
        subject_id = seeded["subject"].id
        study_id = seeded["study"].id

        attempts = [
            await client.post(
                f"/api/v1/pv/subjects/{subject_id}",
                json={"subject_number": "PV-COMPETING"},
                headers=headers,
            ),
            await client.patch(
                f"/api/v1/pv/subjects/{subject_id}",
                json={"subject_number": "PV-COMPETING"},
                headers=headers,
            ),
            await client.patch(
                f"/api/v1/pv/visits/{uuid4()}",
                json={"status": "Completed"},
                headers=headers,
            ),
            await client.post(
                f"/api/v1/pv/studies/{study_id}/versions",
                json={"version_number": "2.0"},
                headers=headers,
            ),
            await client.post(
                f"/api/v1/pv/queries/{uuid4()}/respond",
                json={"message": "clinical"},
                headers=headers,
            ),
            await client.post(
                f"/api/v1/pv/forms/{uuid4()}/submit",
                json={"value": "x"},
                headers=headers,
            ),
            await client.post(
                f"/api/v1/pv/ctms/sites/{uuid4()}/activate",
                json={},
                headers=headers,
            ),
        ]
        for response in attempts:
            # These paths do not exist on the PV router (thin, additive boundary).
            assert response.status_code in {404, 405}, response.text

        assert await _snapshot(db_session) == before
