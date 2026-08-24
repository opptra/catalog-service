"""Pydantic models for marketplace_attribute.config JSON."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CharLimit(BaseModel):
    """Character range. ``min`` is a soft prompt aim; ``max`` is the hard ceiling."""

    model_config = ConfigDict(extra="forbid")

    min: int | None = Field(default=None, ge=1)
    max: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _max_gte_min(self) -> "CharLimit":
        if self.min is not None and self.max is not None and self.max < self.min:
            raise ValueError("chars.max must be >= chars.min")
        return self


class ItemLimit(BaseModel):
    """List length and optional per-item character limits."""

    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(default=None, ge=1)
    min: int | None = Field(default=None, ge=1)
    max: int | None = Field(default=None, ge=1)
    chars: CharLimit | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "ItemLimit":
        if self.count is not None and (self.min is not None or self.max is not None):
            raise ValueError("items.count cannot be combined with items.min/max")
        if self.min is not None and self.max is not None and self.max < self.min:
            raise ValueError("items.max must be >= items.min")
        return self


class TextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chars: CharLimit | None = None
    items: ItemLimit | None = None


class ImageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1)
    aspect_ratio: str = Field(min_length=1)


class MarketplaceAttributeConfig(BaseModel):
    """Root config object stored on marketplace_attribute.config."""

    model_config = ConfigDict(extra="forbid")

    text: TextConfig | None = None
    image: ImageConfig | None = None
