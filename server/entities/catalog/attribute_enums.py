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


class ListingFillGapReason(StrEnum):
    """Operator-facing listing-fill gap codes (API ``gaps[].reason``).

    Add new team-triage cases here instead of free-text reason strings.
    ``message`` is the sentence we show operators for that code.
    """

    TOO_MANY_DROPDOWN_VALUES = "TOO_MANY_DROPDOWN_VALUES"
    UNRESOLVED_DROPDOWN = "UNRESOLVED_DROPDOWN"
    ENUM_HAS_NO_VALID_VALUES = "ENUM_HAS_NO_VALID_VALUES"
    ENUM_PARENT_NOT_FILLED = "ENUM_PARENT_NOT_FILLED"
    ENUM_NO_VALUES_FOR_PARENT = "ENUM_NO_VALUES_FOR_PARENT"
    ENUM_MISSING_PARENT_MAP = "ENUM_MISSING_PARENT_MAP"
    ENUM_NOT_IN_VALID_VALUES = "ENUM_NOT_IN_VALID_VALUES"
    ENUM_NO_VALID_VALUE = "ENUM_NO_VALID_VALUE"
    REQUIRED_EMPTY = "REQUIRED_EMPTY"
    IMAGE_UPLOAD_FAILED = "IMAGE_UPLOAD_FAILED"
    UNSUPPORTED_FILL_TYPE = "UNSUPPORTED_FILL_TYPE"

    @property
    def message(self) -> str:
        return LISTING_FILL_GAP_MESSAGES[self]


LISTING_FILL_GAP_MESSAGES: dict[ListingFillGapReason, str] = {
    ListingFillGapReason.TOO_MANY_DROPDOWN_VALUES: (
        "Dropdown has too many allowed values to send to the fill model. "
        "Filled only when PIM matches a value exactly."
    ),
    ListingFillGapReason.UNRESOLVED_DROPDOWN: (
        "Template has a dropdown but allowed values were not extracted."
    ),
    ListingFillGapReason.ENUM_HAS_NO_VALID_VALUES: ("ENUM column has no allowed-values list."),
    ListingFillGapReason.ENUM_PARENT_NOT_FILLED: (
        "Parent dropdown is empty, so this dependent dropdown cannot be filled."
    ),
    ListingFillGapReason.ENUM_NO_VALUES_FOR_PARENT: (
        "No allowed values for the filled parent dropdown value."
    ),
    ListingFillGapReason.ENUM_MISSING_PARENT_MAP: (
        "Dependent dropdown is missing a parent → values map."
    ),
    ListingFillGapReason.ENUM_NOT_IN_VALID_VALUES: (
        "Fill model picked a value that is not in the template dropdown."
    ),
    ListingFillGapReason.ENUM_NO_VALID_VALUE: (
        "Product evidence does not match any allowed dropdown value."
    ),
    ListingFillGapReason.REQUIRED_EMPTY: "Required listing cell was left empty.",
    ListingFillGapReason.IMAGE_UPLOAD_FAILED: (
        "Generated image could not be uploaded for the listing URL."
    ),
    ListingFillGapReason.UNSUPPORTED_FILL_TYPE: "Column fill_type is not supported.",
}

if set(LISTING_FILL_GAP_MESSAGES) != set(ListingFillGapReason):
    missing = set(ListingFillGapReason) - set(LISTING_FILL_GAP_MESSAGES)
    extra = set(LISTING_FILL_GAP_MESSAGES) - set(ListingFillGapReason)
    raise RuntimeError(
        f"LISTING_FILL_GAP_MESSAGES must cover every ListingFillGapReason "
        f"(missing={sorted(m.value for m in missing)} extra={sorted(e.value for e in extra)})"
    )
