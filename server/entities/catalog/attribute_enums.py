from enum import StrEnum


class AttributeName(StrEnum):
    TITLE = "TITLE"
    BULLET_POINTS = "BULLET_POINTS"
    DESCRIPTION = "DESCRIPTION"
    HERO = "HERO"
    INFOGRAPHIC = "INFOGRAPHIC"
    LIFESTYLE = "LIFESTYLE"
    A_PLUS = "A_PLUS"


class AttributeDataType(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"


class AttributeGroupLabel(StrEnum):
    IMAGE = "IMAGE"


class SkuJobStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
