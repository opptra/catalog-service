from pydantic import BaseModel, Field


class InviteBrandUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
