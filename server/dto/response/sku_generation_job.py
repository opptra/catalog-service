from typing import Any
from uuid import UUID

from pydantic import BaseModel

from dto.response.job_status import ImageVerificationResponse


class SkuGenerationJobAttributeValueResponse(BaseModel):
    external_id: UUID
    attribute_id: int
    name: str
    slot: int
    version: int
    value: str
    prompt: str | None = None
    verification: ImageVerificationResponse | None = None


class SkuGenerationJobExecutionResponse(BaseModel):
    external_id: UUID
    status: str
    tasks: dict[str, Any]
    attributes: list[SkuGenerationJobAttributeValueResponse]
