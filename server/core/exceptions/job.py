class BrandNotFoundError(Exception):
    pass


class MarketplaceNotFoundError(Exception):
    pass


class SkuNotFoundError(Exception):
    pass


class AttributeNotFoundError(Exception):
    pass


class InvalidJobAttributesError(Exception):
    pass


class JobNotFoundError(Exception):
    pass


class SkuGenerationJobExecutionFailedError(Exception):
    """Raised when a SKU generation job run finishes without every task COMPLETED."""

    pass


class FlatfileValidationError(Exception):
    """Template / mandatory-attribute validation failed for a flatfile upload."""

    pass


class FlatfileUploadIncompleteError(Exception):
    """Required GCS objects for the flatfile job are missing."""

    pass
