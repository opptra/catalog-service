from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SkuJobExecutionResponse(BaseModel):
    external_id: UUID
    status: str
    tasks: dict[str, Any]
    output_dir: str
    result_path: str
    image_paths: list[str]
