class CategoryNotFoundError(Exception):
    """No category exists for the given external_id."""


class AmbiguousCategoryError(Exception):
    """More than one category matches the requested name under the same parent."""


class InvalidCategoryPathError(Exception):
    """Category path failed validation for import."""
