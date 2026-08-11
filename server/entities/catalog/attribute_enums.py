from enum import StrEnum


class AttributeName(StrEnum):
    TITLE = "TITLE"
    BULLET_POINTS = "BULLET_POINTS"
    DESCRIPTION = "DESCRIPTION"
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
