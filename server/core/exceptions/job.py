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


class SkuJobExecutionFailedError(Exception):
    """Raised when a SKU job run finishes without every task COMPLETED."""

    pass
