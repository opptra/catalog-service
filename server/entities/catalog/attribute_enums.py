from enum import StrEnum


class AttributeName(StrEnum):
    TITLE = "TITLE"
    ITEM_HIGHLIGHTS = "ITEM_HIGHLIGHTS"
    BULLET_POINTS = "BULLET_POINTS"
    KEY_FEATURES = "KEY_FEATURES"
    DESCRIPTION = "DESCRIPTION"
    BACKEND_KEYWORDS = "BACKEND_KEYWORDS"
    IMAGE = "IMAGE"
    A_PLUS = "A_PLUS"


class AttributeDataType(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"


class AttributeGroupLabel(StrEnum):
    IMAGES = "IMAGES"


class JobType(StrEnum):
    GENERATION = "GENERATION"
    FLATFILE_UPLOAD = "FLATFILE_UPLOAD"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FlatfileJobStatus(StrEnum):
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SkuGenerationJobStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ListingFillType(StrEnum):
    """How listing fill resolves a template column (stored in column config only).

    - SKIP: leave cell blank
    - CONSTANT: write ``constant_value``
    - ENUM: pick from valid_values (fill-time AI / exact match)
    - DIRECT_MAP: copy an existing value from ``source`` (GENERATION or SKU_MASTER)
    - AI_TEXT: fill-time free-text generation (batched; PIM + product images)
    - IMAGE: copy a generated image from ``source``, expose as Dropbox HTTPS URL
    """

    SKIP = "SKIP"
    CONSTANT = "CONSTANT"
    ENUM = "ENUM"
    DIRECT_MAP = "DIRECT_MAP"
    AI_TEXT = "AI_TEXT"
    IMAGE = "IMAGE"


class ListingValueSourceFrom(StrEnum):
    """Where a DIRECT_MAP / IMAGE / ENUM-hint value is read from."""

    GENERATION = "GENERATION"  # sku_marketplace_attribute_value for this job
    SKU_MASTER = "SKU_MASTER"  # sku_master.attributes (PIM bag)


class ListingRequiredness(StrEnum):
    ALWAYS = "ALWAYS"
    OPTIONAL = "OPTIONAL"
