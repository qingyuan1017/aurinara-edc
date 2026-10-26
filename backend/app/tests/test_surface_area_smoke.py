"""Surface-area smoke tests for task 20.3.

Assert that every newly-wired Study_Info_Area sub-area endpoint (R8.1-R8.2,
R8.4-R8.13) and every Report_Area report endpoint (R9.1-R9.7) is mounted under
``/api/v1`` and responds successfully for a seeded, authorized user.

These are *surface-area* smoke tests: they prove each endpoint exists, is wired
into the EDC aggregate, passes the server-side ``study.read`` authorization
guard, and returns its structured response (HTTP 200). They intentionally do
not assert deep business behavior — that is covered by the focused service and
property tests. The fixture/seed/auth pattern mirrors
``test_edit_check_routes.py``: an in-memory SQLite engine, ``create_app()`` with
``get_db`` overridden, and a seeded study + system-scope user holding
``study.read``.

The user is given a **system-scope** ``Operational_Role`` carrying
``study.read`` so the shared ``permission_service`` scope filtering passes for
every study (no study/site narrowing is needed) and the reads return 200
instead of an empty-but-authorized payload.

Design-dependent CRF Version reads (``edit-check-testing-cases`` and
``access-control``) resolve through the ``DesignConsumptionService``, which only
exposes *published* designs; the fixture therefore seeds a published
``StudyVersion`` and exercises those endpoints against its id.

Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13,
9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import (
    Study,
    StudyStatus,
    StudyVersion,
    StudyVersionStatus,
)
from app.models.edc.subject import Subject, SubjectStatus
from app.models.shared.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession):
    """Seed a study, a published design version, a site + subject, and a
    system-scope operational user holding ``study.read``.

    ``study.read`` is an operational-module code, so the granting role must own
    the operational module. A role carrying ``study.read`` already does (the
    code is itself operational), so a single-permission system-scope role is a
    valid Operational_Role for this surface and its grants are effective.
    """
    permission = Permission(
        id=uuid.uuid4(),
        code="study.read",
        description="Read operational study info and reports",
    )
    # ``subject.read`` is only needed for the optional R8.6/R8.7 Subject/SDV
    # smoke check; it is likewise an operational-module code so the role stays a
    # valid Operational_Role.
    subject_read = Permission(
        id=uuid.uuid4(),
        code="subject.read",
        description="Read subjects",
    )
    role = Role(
        id=uuid.uuid4(),
        name="Operational_Role",
        scope_level="system",
        is_system=True,
    )
    user = User(
        id=uuid.uuid4(),
        email="surface-area@example.test",
        password_hash=hash_password("pw"),
        first_name="Surface",
        last_name="Area",
        status=UserStatus.active,
        mfa_enabled=False,
        last_activity=datetime.now(UTC),
    )
    db_session.add_all([permission, subject_read, role, user])
    await db_session.flush()
    db_session.add_all(
        [
            RolePermission(role_id=role.id, permission_id=permission.id),
            RolePermission(role_id=role.id, permission_id=subject_read.id),
            # System-scope assignment: study_id/site_id left None so the grant
            # matches any study/site (passes require() everywhere).
            UserRole(user_id=user.id, role_id=role.id),
        ]
    )

    study = Study(
        id=uuid.uuid4(),
        study_code="SA-001",
        title="Surface Area Study",
        sponsor="Acme Sponsor",
        phase="Phase II",
        therapeutic_area="Oncology",
        indication="NSCLC",
        status=StudyStatus.active,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    # A *published* design version: the Design_Consumption_Contract only exposes
    # published designs, so edit-check-testing-cases / access-control need one.
    published_version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=user.id,
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="101",
        name="Test Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    subject = Subject(
        id=uuid.uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=published_version.id,
        subject_number="101-0001",
        status=SubjectStatus.enrolled,
        created_by=user.id,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([study, published_version, site, subject])
    await db_session.flush()
    return {
        "user": user,
        "study": study,
        "site": site,
        "subject": subject,
        "design_version": published_version,
    }


@pytest.fixture
def app(async_engine):
    from app.api.deps import get_db

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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


API = "/api/v1"


class TestStudyInfoAreaSurface:
    """Every Study_Info_Area sub-area endpoint is mounted and responds 200."""

    async def test_study_information_sub_area(self, client, seeded):
        """R8.1 — Study Information / Status Config / ID Config."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id

        info = await client.get(
            f"{API}/studies/{study_id}/study-information", headers=headers
        )
        assert info.status_code == 200, info.text
        assert info.json()["study_id"] == str(study_id)

        status = await client.get(
            f"{API}/studies/{study_id}/status-configuration", headers=headers
        )
        assert status.status_code == 200, status.text
        assert status.json()["current_status"] == StudyStatus.active.value

        id_config = await client.get(
            f"{API}/studies/{study_id}/id-configuration", headers=headers
        )
        assert id_config.status_code == 200, id_config.text
        # Resolved against the study's latest published design.
        assert id_config.json()["design_version_id"] == str(
            seeded["design_version"].id
        )

    async def test_crf_version_management_sub_area(self, client, seeded):
        """R8.2 — Version History, Edit Check Testing Cases, Access Control."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        design_version_id = seeded["design_version"].id

        history = await client.get(
            f"{API}/studies/{study_id}/crf-version-history", headers=headers
        )
        assert history.status_code == 200, history.text
        version_ids = [e["design_version_id"] for e in history.json()["entries"]]
        assert str(design_version_id) in version_ids

        # These resolve through the Design_Consumption_Contract (published-only).
        testing_cases = await client.get(
            f"{API}/design-versions/{design_version_id}/edit-check-testing-cases",
            headers=headers,
        )
        assert testing_cases.status_code == 200, testing_cases.text
        assert testing_cases.json()["design_version_id"] == str(design_version_id)

        access_control = await client.get(
            f"{API}/design-versions/{design_version_id}/access-control",
            headers=headers,
        )
        assert access_control.status_code == 200, access_control.text
        assert access_control.json()["design_version_id"] == str(design_version_id)

    async def test_metrics_sub_area(self, client, seeded):
        """R8.4 — Metrics (study dashboard + query metrics)."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id

        dashboard = await client.get(
            f"{API}/studies/{study_id}/dashboard", headers=headers
        )
        assert dashboard.status_code == 200, dashboard.text
        assert "subject_counts_by_status" in dashboard.json()

        metrics = await client.get(
            f"{API}/studies/{study_id}/query-metrics", headers=headers
        )
        assert metrics.status_code == 200, metrics.text
        assert "open_count" in metrics.json()

    @pytest.mark.parametrize(
        ("path", "requirement"),
        [
            ("alerts", "R8.5"),
            ("sdr", "R8.8"),
            ("lab", "R8.9"),
            ("external-data-source", "R8.10"),
            ("adjudication", "R8.11"),
            ("saes", "R8.12"),
            ("integrations", "R8.13"),
        ],
    )
    async def test_backing_model_free_sub_areas(
        self, client, seeded, path, requirement
    ):
        """R8.5, R8.8-R8.13 — structured sub-area surfaces are mounted."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id

        response = await client.get(
            f"{API}/studies/{study_id}/{path}", headers=headers
        )
        assert response.status_code == 200, (requirement, response.text)
        body = response.json()
        assert body["study_id"] == str(study_id)
        assert body["available"] is True
        # Design-dependent reads report the bound published design version.
        assert body["design_version_id"] == str(seeded["design_version"].id)
        assert len(body["items"]) >= 1

    async def test_subject_and_sdv_surfaces_smoke(self, client, seeded):
        """R8.6/R8.7 — existing Subject/SDV surfaces respond for the study."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id

        subjects = await client.get(
            f"{API}/studies/{study_id}/subjects", headers=headers
        )
        assert subjects.status_code == 200, subjects.text


class TestReportAreaSurface:
    """Every Report_Area report endpoint is mounted and responds 200."""

    async def test_data_summary_report(self, client, seeded):
        """R9.1 — Data Summary."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/data-summary", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["report_group"] == "Data Summary"

    async def test_crf_status_report(self, client, seeded):
        """R9.2 — CRF Status."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/crf-status", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["report_group"] == "CRF Status"

    async def test_query_report(self, client, seeded):
        """R9.3 — Query Report."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/query-report", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["report_group"] == "Query Report"

    async def test_enrollment_status_report_study_scoped(self, client, seeded):
        """R9.4 — Enrollment Status (single study)."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/enrollment-status", headers=headers
        )
        assert response.status_code == 200, response.text
        # The seeded enrolled subject is counted (system-scope sees the study).
        rows = response.json()["rows"]
        assert any(row["study_id"] == str(study_id) for row in rows)

    async def test_enrollment_status_report_cross_study(self, client, seeded):
        """R9.4 — Enrollment Status (cross-study collection endpoint)."""
        headers = auth(seeded["user"])
        response = await client.get(
            f"{API}/reports/enrollment-status", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["report_group"] == "Enrollment Status"

    async def test_ecoa_ediary_report(self, client, seeded):
        """R9.5 — eCOA / eDiary Report."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/ecoa-ediary", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["report_group"] == "eCOA/eDiary Report"

    async def test_operational_report(self, client, seeded):
        """R9.6 — On-Demand / KRI / SDV-SDR Workload / Data Analysis / etc."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/operational", headers=headers
        )
        assert response.status_code == 200, response.text
        assert "report_group" in response.json()["meta"]

    async def test_end_of_study_report(self, client, seeded):
        """R9.7 — End of Study."""
        headers = auth(seeded["user"])
        study_id = seeded["study"].id
        response = await client.get(
            f"{API}/studies/{study_id}/reports/end-of-study", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["meta"]["report_group"] == "End of Study"
