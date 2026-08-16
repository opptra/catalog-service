from uuid import UUID

from pydantic import BaseModel


class MarketplaceResponse(BaseModel):
    external_id: UUID
    name: str


class MarketplaceListResponse(BaseModel):
    items: list[MarketplaceResponse]
