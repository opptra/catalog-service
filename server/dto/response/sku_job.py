from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SkuJobAttributeValueResponse(BaseModel):
    external_id: UUID
    attribute_id: int
    name: str
    slot: int
    version: int
    value: str


class SkuJobExecutionResponse(BaseModel):
    external_id: UUID
    status: str
    tasks: dict[str, Any]
    attributes: list[SkuJobAttributeValueResponse]
