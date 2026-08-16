"""Marketplace listing — thin service over the marketplace repository."""

from sqlalchemy.orm import Session

from dto.response.marketplace import MarketplaceListResponse, MarketplaceResponse
from repositories.catalog import marketplace as marketplace_repo


def list_marketplaces(session: Session) -> MarketplaceListResponse:
    rows = marketplace_repo.list_all(session)
    return MarketplaceListResponse(
        items=[MarketplaceResponse(external_id=row.external_id, name=row.name) for row in rows]
    )
