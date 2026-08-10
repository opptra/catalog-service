from uuid import UUID

from pydantic import BaseModel, Field


class CategoryPathNode(BaseModel):
    external_id: UUID
    name: str


class LeafCategoryResponse(BaseModel):
    external_id: UUID
    name: str
    path: list[CategoryPathNode] = Field(
        description="Root-to-leaf path, including the leaf as the last node.",
    )


class LeafCategoryPageResponse(BaseModel):
    items: list[LeafCategoryResponse]
    offset: int
    limit: int
    has_more: bool


class CategoryTemplateField(BaseModel):
    name: str
    mandatory: bool


class CategoryTemplateResponse(BaseModel):
    external_id: UUID
    name: str
    fields: list[CategoryTemplateField]


class ImportedCategoryNode(BaseModel):
    external_id: UUID
    name: str
    created: bool = Field(description="True when this node was inserted on this request.")


class ImportCategoryPathResponse(BaseModel):
    path: list[ImportedCategoryNode] = Field(
        description="Resolved root-to-leaf path after import (or no-op reuse).",
    )
    created_count: int
    reused_count: int
