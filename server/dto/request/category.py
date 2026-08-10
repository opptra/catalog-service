from pydantic import BaseModel, Field, field_validator


class ImportCategoryPathRequest(BaseModel):
    """Root-first category path to import.

    Index 0 is the root; each following name is a child of the previous node.
    """

    categories: list[str] = Field(
        min_length=1,
        description="Root-first path of category names (index 0 = parent-most).",
    )

    @field_validator("categories")
    @classmethod
    def normalize_names(cls, names: list[str]) -> list[str]:
        cleaned = [name.strip() for name in names]
        if any(not name for name in cleaned):
            raise ValueError("Category names must be non-empty")
        return cleaned
