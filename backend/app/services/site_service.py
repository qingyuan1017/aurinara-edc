"""Site_Service — site lifecycle and user assignment management.

Satisfies Requirements:
  - 6.1: Persist site metadata (site number, name, PI, country, region, address, status).
  - 6.2: Enforce site number uniqueness within the study.
  - 6.4: Deactivate site (set status inactive, retain record).
  - 6.5: Record site-level user assignment.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.exceptions import ConflictError, NotFoundError
from app.models.site import Site, SiteStatus, StudySiteUser
from app.schemas.base import PaginatedResponse
from app.schemas.site import SiteCreate

logger = logging.getLogger(__name__)


class SiteService:
    """Manages site creation, deactivation, user assignment, and retrieval."""

    # ------------------------------------------------------------------
    # Create (Req 6.1, 6.2)
    # ------------------------------------------------------------------

    async def create_site(
        self,
        session: AsyncSession,
        study_id: UUID,
        data: SiteCreate,
        actor_id: UUID,
    ) -> Site:
        """Create a new Site with status active.

        Args:
            session: Active async database session (caller's transaction).
            study_id: UUID of the parent study.
            data: Validated SiteCreate schema.
            actor_id: UUID of the user performing the action.

        Returns:
            The created Site instance.

        Raises:
            ConflictError: If the site_number already exists within the study (Req 6.2).
        """
        # Check uniqueness of site_number within the study (Req 6.2)
        existing = await session.execute(
            select(Site).where(
                Site.study_id == study_id,
                Site.site_number == data.site_number,
                Site.deleted_at.is_(None),
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError(
                message="Site number already exists within this study",
                details={"site_number": data.site_number, "study_id": str(study_id)},
            )

        # Create the Site (Req 6.1)
        site = Site(
            study_id=study_id,
            site_number=data.site_number,
            name=data.name,
            principal_investigator=data.principal_investigator,
            country=data.country,
            region=data.region,
            address=data.address,
            status=SiteStatus.active,
        )
        session.add(site)
        await session.flush()  # Assign the id

        # Write Audit_Event
        await audit_service.record(
            session,
            entity_type="site",
            entity_id=site.id,
            action="create",
            study_id=study_id,
            site_id=site.id,
            actor_id=actor_id,
            new_value=f"site_number={site.site_number}, name={site.name}",
        )

        logger.info(
            "Site created: id=%s study_id=%s site_number=%s actor=%s",
            site.id,
            study_id,
            site.site_number,
            actor_id,
        )
        return site

    # ------------------------------------------------------------------
    # Deactivate (Req 6.4)
    # ------------------------------------------------------------------

    async def deactivate_site(
        self,
        session: AsyncSession,
        site: Site,
        actor_id: UUID,
    ) -> Site:
        """Deactivate a Site by setting status to inactive, retaining the record.

        Args:
            session: Active async database session.
            site: The Site instance to deactivate.
            actor_id: UUID of the user performing the action.

        Returns:
            The updated Site instance.
        """
        old_status = site.status
        site.status = SiteStatus.inactive
        site.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event
        await audit_service.record(
            session,
            entity_type="site",
            entity_id=site.id,
            action="deactivate",
            study_id=site.study_id,
            site_id=site.id,
            actor_id=actor_id,
            field_name="status",
            old_value=old_status if isinstance(old_status, str) else old_status.value,
            new_value=SiteStatus.inactive.value,
        )

        logger.info(
            "Site deactivated: id=%s study_id=%s actor=%s",
            site.id,
            site.study_id,
            actor_id,
        )
        return site

    # ------------------------------------------------------------------
    # Assign user (Req 6.5)
    # ------------------------------------------------------------------

    async def assign_user(
        self,
        session: AsyncSession,
        study_id: UUID,
        site_id: UUID,
        user_id: UUID,
        actor_id: UUID,
    ) -> StudySiteUser:
        """Assign a User to a Site within a Study.

        Args:
            session: Active async database session.
            study_id: UUID of the parent study.
            site_id: UUID of the site.
            user_id: UUID of the user to assign.
            actor_id: UUID of the user performing the action.

        Returns:
            The created StudySiteUser assignment.

        Raises:
            ConflictError: If the user is already assigned to this site in this study.
        """
        # Check for existing assignment
        existing = await session.execute(
            select(StudySiteUser).where(
                StudySiteUser.study_id == study_id,
                StudySiteUser.site_id == site_id,
                StudySiteUser.user_id == user_id,
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError(
                message="User is already assigned to this site",
                details={
                    "study_id": str(study_id),
                    "site_id": str(site_id),
                    "user_id": str(user_id),
                },
            )

        assignment = StudySiteUser(
            study_id=study_id,
            site_id=site_id,
            user_id=user_id,
            assigned_by=actor_id,
        )
        session.add(assignment)
        await session.flush()

        # Write Audit_Event
        await audit_service.record(
            session,
            entity_type="study_site_user",
            entity_id=assignment.id,
            action="assign",
            study_id=study_id,
            site_id=site_id,
            actor_id=actor_id,
            new_value=f"user_id={user_id}",
        )

        logger.info(
            "User assigned to site: study_id=%s site_id=%s user_id=%s actor=%s",
            study_id,
            site_id,
            user_id,
            actor_id,
        )
        return assignment

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_site(self, session: AsyncSession, site_id: UUID) -> Site:
        """Retrieve a Site by its primary key.

        Args:
            session: Active async database session.
            site_id: The UUID of the site.

        Returns:
            The Site instance.

        Raises:
            NotFoundError: If no site exists with the given ID or is soft-deleted.
        """
        result = await session.execute(
            select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
        )
        site = result.scalars().first()
        if site is None:
            raise NotFoundError(
                message="Site not found",
                details={"site_id": str(site_id)},
            )
        return site

    # ------------------------------------------------------------------
    # List (with pagination)
    # ------------------------------------------------------------------

    async def list_sites(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams,
    ) -> PaginatedResponse:
        """List non-deleted sites for a study with pagination.

        Args:
            session: Active async database session.
            study_id: UUID of the parent study.
            pagination: Page/page_size pagination parameters.

        Returns:
            PaginatedResponse containing Site instances.
        """
        query = (
            select(Site)
            .where(Site.study_id == study_id, Site.deleted_at.is_(None))
            .order_by(Site.created_at.desc())
        )
        return await paginate(session, query, pagination)


# Module-level singleton for convenience
site_service = SiteService()
