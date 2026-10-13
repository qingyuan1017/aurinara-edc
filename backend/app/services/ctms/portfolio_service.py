"""Permission-scoped CTMS portfolio read service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.models.shared.identity import User
from app.repositories.ctms.portfolio_repository import (
    PortfolioRepository,
    PortfolioScope,
    portfolio_repository,
)
from app.schemas.shared.permission import normalize_permission_code
from app.services.shared.permission_service import PermissionService

READ_PERMISSION = "ctms.operational_data_read"


class PortfolioService:
    def __init__(
        self,
        repository: PortfolioRepository | None = None,
        permission_service: PermissionService | None = None,
    ) -> None:
        self.repository = repository or portfolio_repository
        self.permission_service = permission_service or PermissionService()

    async def resolve_scope(self, session: AsyncSession, user: User) -> PortfolioScope:
        authorization = self.permission_service.resolve_scope(user)
        has_read_grant = any(
            normalize_permission_code(grant.permission_code) == READ_PERMISSION
            for grant in authorization.grants
        )
        if not has_read_grant:
            raise AuthorizationError(
                message="Insufficient permissions",
                details={"required_permission": READ_PERMISSION},
            )

        study_candidates, site_study_ids = await self.repository.scope_catalog(session)
        filtered_studies = self.permission_service.filter_studies(user, study_candidates)
        study_wide = tuple(
            study_id
            for study_id in filtered_studies
            if authorization.has_permission(READ_PERMISSION, study_id=study_id)
        )
        filtered_sites = self.permission_service.filter_sites(
            user, list(site_study_ids), site_study_ids
        )
        site_ids = tuple(
            site_id
            for site_id in filtered_sites
            if authorization.has_permission(
                READ_PERMISSION,
                study_id=site_study_ids[site_id],
                site_id=site_id,
            )
        )
        visible_studies = tuple(
            dict.fromkeys((*study_wide, *(site_study_ids[site_id] for site_id in site_ids)))
        )
        return PortfolioScope(
            study_ids=visible_studies,
            study_wide_ids=study_wide,
            site_ids=site_ids,
        )

    async def monitoring_summary(self, session: AsyncSession, user: User):
        return await self.repository.monitoring_summary(
            session, await self.resolve_scope(session, user)
        )

    async def monitoring_activities(self, session: AsyncSession, user: User, **filters):
        return await self.repository.monitoring_activities(
            session, await self.resolve_scope(session, user), **filters
        )

    async def monitoring_workload(self, session: AsyncSession, user: User, **filters):
        return await self.repository.monitoring_workload(
            session, await self.resolve_scope(session, user), **filters
        )

    async def monitoring_findings(self, session: AsyncSession, user: User, **filters):
        return await self.repository.monitoring_findings(
            session, await self.resolve_scope(session, user), **filters
        )

    async def contract_summary(self, session: AsyncSession, user: User):
        return await self.repository.contract_summary(
            session, await self.resolve_scope(session, user)
        )

    async def contracts(self, session: AsyncSession, user: User, **filters):
        return await self.repository.contracts(
            session, await self.resolve_scope(session, user), **filters
        )

    async def financial_summary(self, session: AsyncSession, user: User):
        return await self.repository.financial_summary(
            session, await self.resolve_scope(session, user)
        )

    async def financial_report(self, session: AsyncSession, user: User, **filters):
        return await self.repository.financial_report(
            session, await self.resolve_scope(session, user), **filters
        )

    async def payables(self, session: AsyncSession, user: User, **filters):
        return await self.repository.payables(
            session, await self.resolve_scope(session, user), **filters
        )

    async def invoices(self, session: AsyncSession, user: User, **filters):
        return await self.repository.invoices(
            session, await self.resolve_scope(session, user), **filters
        )

    async def payments(self, session: AsyncSession, user: User, **filters):
        return await self.repository.payments(
            session, await self.resolve_scope(session, user), **filters
        )


portfolio_service = PortfolioService()

__all__ = ["PortfolioService", "portfolio_service"]
