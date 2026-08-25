from uuid import UUID

from pydantic import BaseModel, Field

from dto.marketplace_attribute_config import MarketplaceAttributeConfig


class UploadListingTemplateResponse(BaseModel):
    """Returned after a listing template is stored for a category × marketplace."""

    category_external_id: UUID = Field(description="Category the template was stored for.")
    marketplace_external_id: UUID = Field(description="Marketplace the template was stored for.")
    gcs_object_key: str = Field(description="GCS object key where the template is stored.")


class MarketplaceSelectionAttributeItemResponse(BaseModel):
    """Concrete attribute under a selection group (used when creating a generation job)."""

    external_id: UUID
    name: str
    allows_quantity: bool
    quantity: int = Field(description="Default slot count from marketplace_attribute.config.")
    config: MarketplaceAttributeConfig = Field(
        description="Marketplace rules for this attribute (text limits / image settings).",
    )


class MarketplaceSelectionAttributeResponse(BaseModel):
    """Attribute group shown in the marketplace selection UI."""

    id: str = Field(description="Stable id (attribute group label).")
    label: str = Field(description="Display name for the attribute group.")
    items: list[MarketplaceSelectionAttributeItemResponse] = Field(
        description="Attributes in this group — sent as attribute_external_id on job create.",
    )


class MarketplaceSelectionMarketplaceResponse(BaseModel):
    """One marketplace and the attribute groups it offers."""

    external_id: UUID
    name: str
    attributes: list[MarketplaceSelectionAttributeResponse]


class MarketplaceSelectionResponse(BaseModel):
    """Payload for the marketplace selection step (attributes are per marketplace)."""

    marketplaces: list[MarketplaceSelectionMarketplaceResponse]
