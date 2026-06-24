"""Unit tests for the SiteService.

Validates Requirements:
  - 6.1: create_site persists site metadata with status active.
  - 6.2: create_site rejects duplicate site numbers within a study (ConflictError).
  - 6.4: deactivate_site sets status inactive and retains the record.
  - 6.5: assign_user records the site-level user assignment.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.models.site import Site, SiteStatus, StudySiteUser
from app.schemas.site import SiteCreate
from app.services.site_service import SiteService, site_service


@pytest.fixture
def service():
    """Fresh SiteService instance for each test."""
    return SiteService()


@pytest.fixture
def mock_session():
    """Mock AsyncSession that tracks add/flush calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def site_create_data():
    """Valid SiteCreate schema."""
    return SiteCreate(
        site_number="SITE-001",
        name="Main Hospital",
        principal_investigator="Dr. Smith",
        country="US",
        region="Northeast",
        address="123 Medical Ave, Boston, MA",
    )


@pytest.fixture
def actor_id():
    """Actor UUID for audit purposes."""
    return uuid.uuid4()


@pytest.fixture
def study_id():
    """Study UUID."""
    return uuid.uuid4()


def _make_site(
    study_id: uuid.UUID | None = None,
    status: SiteStatus = SiteStatus.active,
) -> Site:
    """Create a Site instance for testing."""
    site = Site(
        id=uuid.uuid4(),
        study_id=study_id or uuid.uuid4(),
        site_number="SITE-001",
        name="Test Site",
        principal_investigator="Dr. Test",
        country="US",
        region="Northeast",
        address="123 Test St",
        status=status,
        created_at=datetime.now(UTC),
    )
    return site


class TestCreateSite:
    """Tests for SiteService.create_site()."""

    async def test_create_site_checks_uniqueness(
        self, service, mock_session, site_create_data, actor_id, study_id
    ):
        """create_site raises ConflictError when site_number already exists within the study (Req 6.2)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = _make_site(study_id)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ConflictError) as exc_info:
            await service.create_site(mock_session, study_id, site_create_data, actor_id)

        assert "already exists" in exc_info.value.message
        assert exc_info.value.details["site_number"] == "SITE-001"

    async def test_create_site_persists_metadata(
        self, service, mock_session, site_create_data, actor_id, study_id
    ):
        """create_site creates a Site with correct metadata and active status (Req 6.1)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            site = await service.create_site(
                mock_session, study_id, site_create_data, actor_id
            )

        assert site.site_number == "SITE-001"
        assert site.name == "Main Hospital"
        assert site.principal_investigator == "Dr. Smith"
        assert site.country == "US"
        assert site.region == "Northeast"
        assert site.address == "123 Medical Ave, Boston, MA"
        assert site.status == SiteStatus.active
        assert site.study_id == study_id

    async def test_create_site_writes_audit_event(
        self, service, mock_session, site_create_data, actor_id, study_id
    ):
        """create_site writes an Audit_Event (implied by design)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_site(mock_session, study_id, site_create_data, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "site"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["actor_id"] == actor_id
            assert call_kwargs["study_id"] == study_id


class TestDeactivateSite:
    """Tests for SiteService.deactivate_site()."""

    async def test_deactivate_sets_status_inactive(
        self, service, mock_session, actor_id
    ):
        """deactivate_site sets the site status to inactive (Req 6.4)."""
        site = _make_site()

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.deactivate_site(mock_session, site, actor_id)

        assert result.status == SiteStatus.inactive
        assert result.updated_at is not None

    async def test_deactivate_retains_record(self, service, mock_session, actor_id):
        """deactivate_site does not set deleted_at — the record is retained (Req 6.4)."""
        site = _make_site()

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.deactivate_site(mock_session, site, actor_id)

        assert result.deleted_at is None

    async def test_deactivate_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        """deactivate_site writes an Audit_Event with old and new status."""
        site = _make_site(status=SiteStatus.active)

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.deactivate_site(mock_session, site, actor_id)

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "site"
            assert call_kwargs["action"] == "deactivate"
            assert call_kwargs["field_name"] == "status"
            assert call_kwargs["old_value"] == "active"
            assert call_kwargs["new_value"] == "inactive"
            assert call_kwargs["actor_id"] == actor_id


class TestAssignUser:
    """Tests for SiteService.assign_user()."""

    async def test_assign_user_creates_assignment(
        self, service, mock_session, actor_id, study_id
    ):
        """assign_user creates a StudySiteUser assignment (Req 6.5)."""
        user_id = uuid.uuid4()
        site_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            assignment = await service.assign_user(
                mock_session, study_id, site_id, user_id, actor_id
            )

        assert assignment.study_id == study_id
        assert assignment.site_id == site_id
        assert assignment.user_id == user_id
        assert assignment.assigned_by == actor_id

    async def test_assign_user_rejects_duplicate(
        self, service, mock_session, actor_id, study_id
    ):
        """assign_user raises ConflictError if user is already assigned."""
        user_id = uuid.uuid4()
        site_id = uuid.uuid4()

        existing_assignment = StudySiteUser(
            id=uuid.uuid4(),
            study_id=study_id,
            site_id=site_id,
            user_id=user_id,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = existing_assignment
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ConflictError) as exc_info:
            await service.assign_user(
                mock_session, study_id, site_id, user_id, actor_id
            )

        assert "already assigned" in exc_info.value.message

    async def test_assign_user_writes_audit_event(
        self, service, mock_session, actor_id, study_id
    ):
        """assign_user writes an Audit_Event."""
        user_id = uuid.uuid4()
        site_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.site_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.assign_user(
                mock_session, study_id, site_id, user_id, actor_id
            )

            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["entity_type"] == "study_site_user"
            assert call_kwargs["action"] == "assign"
            assert call_kwargs["study_id"] == study_id
            assert call_kwargs["site_id"] == site_id
            assert call_kwargs["actor_id"] == actor_id


class TestGetSite:
    """Tests for SiteService.get_site()."""

    async def test_get_site_returns_site(self, service, mock_session):
        """get_site returns the site when found."""
        expected_site = _make_site()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected_site
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_site(mock_session, expected_site.id)
        assert result == expected_site

    async def test_get_site_raises_not_found(self, service, mock_session):
        """get_site raises NotFoundError when no site exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_site(mock_session, uuid.uuid4())

        assert "not found" in exc_info.value.message


class TestListSites:
    """Tests for SiteService.list_sites()."""

    async def test_list_sites_returns_paginated_response(self, service, study_id):
        """list_sites returns a PaginatedResponse."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        from app.api.deps import PaginationParams

        pagination = PaginationParams(page=1, page_size=25)
        result = await service.list_sites(mock_session, study_id, pagination)

        assert result.page == 1
        assert result.page_size == 25
        assert result.total == 0
        assert result.items == []


class TestSiteServiceSingleton:
    """Tests for the module-level singleton."""

    def test_singleton_exists(self):
        """The module exports a singleton site_service instance."""
        assert site_service is not None
        assert isinstance(site_service, SiteService)
