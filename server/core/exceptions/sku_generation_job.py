class SkuGenerationJobNotFoundError(Exception):
    """No sku_generation_job exists for the given external_id."""


class ProductNotFoundError(Exception):
    """No usable live SKU / attributes for generation."""


class BrandDnaMissingError(Exception):
    """Brand DNA is missing or empty on the brand row."""


class CategoryIntelligenceMissingError(Exception):
    """No usable category intelligence for this marketplace × category pair."""
