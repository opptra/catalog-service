from pydantic import BaseModel, Field


class SkuImageDownloadItem(BaseModel):
    marketplace: str = Field(description="Marketplace folder under the SKU root.")
    folder: str = Field(
        description="Zip folder under the marketplace (pdp_images or a_plus_images)."
    )
    filename: str = Field(description="File name inside that folder (e.g. 1.jpg).")
    url: str = Field(description="Signed HTTPS URL for the image bytes.")


class SkuImageDownloadResponse(BaseModel):
    sku_id: str
    filename: str = Field(description="Suggested zip filename for the client download.")
    images: list[SkuImageDownloadItem]
