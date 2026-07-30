class GenerateError(Exception):
    """Generate pipeline failed for a domain reason."""


class ProductNotFoundError(GenerateError):
    def __init__(self, product_key: str) -> None:
        self.product_key = product_key
        super().__init__(f"Product not found in local PIM: {product_key}")


class GenerateInputError(GenerateError):
    """Local generate input files are missing or invalid."""
