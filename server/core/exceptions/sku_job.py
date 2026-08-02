class SkuJobNotFoundError(Exception):
    """No sku_job exists for the given external_id."""


class ProductNotFoundError(Exception):
    """No product in the input data matches the sku_job's sku_id."""


class CategoryIntelligenceMissingError(Exception):
    """The category intelligence input file is missing or empty."""
