from pydantic import BaseModel, Field


class ImageQuantities(BaseModel):
    hero: int = Field(default=0, ge=0, le=5)
    infographic: int = Field(default=0, ge=0, le=5)
    lifestyle: int = Field(default=0, ge=0, le=5)
    a_plus: int = Field(default=0, ge=0, le=5)

    def total(self) -> int:
        return self.hero + self.infographic + self.lifestyle + self.a_plus

    def selected(self) -> dict[str, int]:
        return {
            key: qty
            for key, qty in {
                "hero": self.hero,
                "infographic": self.infographic,
                "lifestyle": self.lifestyle,
                "a_plus": self.a_plus,
            }.items()
            if qty > 0
        }


class GenerateJobRequest(BaseModel):
    product_keys: list[str] | None = None
    generate_text: bool = True
    images: ImageQuantities = Field(default_factory=ImageQuantities)
    text_model: str | None = None
    image_model: str | None = None
    persist_to_db: bool = False


class GeneratedTextResult(BaseModel):
    title: str
    bullet_points: list[str]
    item_highlights: list[str]


class GeneratedImageResult(BaseModel):
    image_type: str
    variant: int
    url: str
    relative_path: str


class SkuGenerateResult(BaseModel):
    product_key: str
    text: GeneratedTextResult | None = None
    images: list[GeneratedImageResult] = Field(default_factory=list)
    openrouter_calls: int = 0
    error: str | None = None


class GenerateJobResponse(BaseModel):
    run_id: str
    status: str
    sku_results: list[SkuGenerateResult]
    total_openrouter_calls: int
    job_external_id: str | None = None
