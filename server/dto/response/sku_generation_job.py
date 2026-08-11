from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SkuGenerationJobAttributeValueResponse(BaseModel):
    external_id: UUID
    attribute_id: int
    name: str
    slot: int
    version: int
    value: str
    prompt: str | None = None


class SkuGenerationJobExecutionResponse(BaseModel):
    external_id: UUID
    status: str
    tasks: dict[str, Any]
    attributes: list[SkuGenerationJobAttributeValueResponse]
