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
    """How listing fill resolves a template column (stored in column config only)."""

    DIRECT_MAP = "DIRECT_MAP"
    ENUM = "ENUM"
    LLM_TEXT = "LLM_TEXT"
    IMAGE = "IMAGE"
    CONSTANT = "CONSTANT"
    SKIP = "SKIP"


class ListingRequiredness(StrEnum):
    ALWAYS = "ALWAYS"
    OPTIONAL = "OPTIONAL"
