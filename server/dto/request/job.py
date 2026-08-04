from pydantic import BaseModel, Field


class CreateJobAttribute(BaseModel):
    attribute_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1)


class CreateJobRequest(BaseModel):
    sku_ids: list[int] = Field(min_length=1)
    marketplace_id: int = Field(gt=0)
    attributes: list[CreateJobAttribute] = Field(min_length=1)
