"""Listing fill — assemble Amazon workbooks from a completed generation job."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.dropbox import DropboxClient
from core.clients.gcs import GcsClient
from core.clients.openrouter import OpenRouterClient
from core.exceptions import (
    DropboxError,
    GcsError,
    JobNotFoundError,
    ListingFillError,
    ListingTemplateNotFoundError,
)
from dto.listing_config import ListingColumnConfig, ListingTemplateMetadata
from dto.response.listing import FillListingResponse, ListingFillGap
from entities.catalog.attribute_enums import (
    AttributeName,
    JobType,
    ListingFillType,
    ListingRequiredness,
)
from entities.catalog.listing_template_column import ListingTemplateColumn
from pipelines.listing import enum_select
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import category_marketplace as category_marketplace_repo
from repositories.catalog import job as job_repo
from repositories.catalog import listing_template as listing_template_repo
from repositories.catalog import listing_template_column as listing_template_column_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from repositories.catalog import sku_marketplace_attribute_value as attribute_value_repo
from repositories.catalog import sku_master as sku_master_repo
from utils import listing_workbook as workbook_utils

logger = logging.getLogger(__name__)

_LISTING_FILL_WORKERS = 10
_FILLED_FILE_SIGNED_URL_TTL_SECONDS = 3600
_REFERENCE_IMAGE_URL_TTL_SECONDS = 3600
_LISTING_OUTPUT_CONTENT_TYPE = "application/vnd.ms-excel.sheet.macroEnabled.12"


def fill_listing_for_job(
    session: Session,
    gcs: GcsClient,
    dropbox: DropboxClient,
    openrouter: OpenRouterClient,
    job_external_id: UUID,
) -> FillListingResponse:
    """Fill the category listing template for every SKU on a generation job."""
    job = job_repo.get_by_external_id(session, job_external_id)
    if job is None:
        raise JobNotFoundError(f"Job not found: {job_external_id}")
    if job.job_type != JobType.GENERATION.value:
        raise ListingFillError(f"Job {job_external_id} is not a GENERATION job")
    if job.marketplace_id is None or job.category_id is None:
        raise ListingFillError(f"Job {job_external_id} is missing marketplace_id or category_id")

    junction = category_marketplace_repo.get_by_marketplace_and_category(
        session, job.marketplace_id, job.category_id
    )
    if junction is None:
        raise ListingTemplateNotFoundError(
            f"No category_marketplace for marketplace_id={job.marketplace_id} "
            f"category_id={job.category_id}"
        )

    template = listing_template_repo.get_by_category_marketplace_id(session, junction.id)
    if template is None:
        raise ListingTemplateNotFoundError(
            f"No listing_template for category_marketplace id={junction.id}"
        )

    metadata = ListingTemplateMetadata.model_validate(template.metadata_ or {})
    columns = list(listing_template_column_repo.list_by_listing_template_id(session, template.id))
    if not columns:
        raise ListingFillError(f"listing_template id={template.id} has no columns")

    parsed_columns = [_ParsedColumn.from_row(row) for row in columns]
    bands = _group_by_display_order(parsed_columns)

    attribute_ids_by_name = _attribute_ids_by_name(session)
    sku_jobs = list(sku_generation_job_repo.list_by_job_id(session, job.id))
    if not sku_jobs:
        raise ListingFillError(f"Job {job_external_id} has no SKU generation jobs")

    gaps: list[ListingFillGap] = []
    sku_states: list[_SkuFillState] = []

    for sku_job in sku_jobs:
        sku = sku_master_repo.get_by_id(session, sku_job.sku_id)
        business_sku_id = _business_sku_id(sku, fallback=str(sku_job.sku_id))
        sku_states.append(
            _SkuFillState(
                business_sku_id=business_sku_id,
                pim_values=dict(sku.attributes or {}) if sku is not None else {},
                job_values=_job_values_bag(
                    session,
                    sku_generation_job_id=sku_job.id,
                    attribute_ids_by_name=attribute_ids_by_name,
                ),
                product_image_url=_one_product_image_url(gcs, business_sku_id),
            )
        )

    # Bands are sequential (later bands need already_filled). Within a band, SKUs
    # run concurrently (worker cap). Session reads are finished before this loop.
    for _order, band_columns in bands:
        workers = min(_LISTING_FILL_WORKERS, max(1, len(sku_states)))

        def _run_sku_band(
            state: _SkuFillState,
            cols: list[_ParsedColumn],
        ) -> list[ListingFillGap]:
            band_gaps: list[ListingFillGap] = []
            band_results = _resolve_band(
                cols,
                gcs=gcs,
                dropbox=dropbox,
                openrouter=openrouter,
                business_sku_id=state.business_sku_id,
                pim_values=state.pim_values,
                job_values=state.job_values,
                already_filled=state.already_filled,
                product_image_url=state.product_image_url,
            )
            for column_index, value, gap_reason, label in band_results:
                state.row_values[column_index] = value
                if value:
                    state.already_filled[label] = value
                if gap_reason:
                    band_gaps.append(
                        ListingFillGap(
                            sku_id=state.business_sku_id,
                            column_label=label,
                            reason=gap_reason,
                        )
                    )
            return band_gaps

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_sku_band, state, band_columns) for state in sku_states]
            for future in as_completed(futures):
                gaps.extend(future.result())

    filled_rows = [state.row_values for state in sku_states]

    try:
        template_bytes = gcs.download_bytes(template.gcs_object_key)
    except GcsError as exc:
        raise ListingFillError(f"Failed to download listing template: {exc}") from exc

    try:
        filled_bytes = workbook_utils.fill_workbook(
            template_bytes,
            metadata=metadata,
            rows=filled_rows,
        )
    except ValueError as exc:
        raise ListingFillError(str(exc)) from exc

    out_name = metadata.filename.rsplit(".", 1)[0] + "_filled.xlsm"
    object_key = workbook_utils.listing_output_object_key(job_external_id, out_name)
    try:
        gcs.upload_bytes(
            filled_bytes,
            object_key,
            content_type=_LISTING_OUTPUT_CONTENT_TYPE,
        )
        filled_url = gcs.signed_url(
            object_key, expiration_seconds=_FILLED_FILE_SIGNED_URL_TTL_SECONDS
        )
    except GcsError as exc:
        raise ListingFillError(f"Failed to upload filled listing: {exc}") from exc

    return FillListingResponse(
        job_external_id=job_external_id,
        filled_file_url=filled_url,
        gaps=gaps,
    )


@dataclass(frozen=True, slots=True)
class _JobAttrValue:
    """One generated attribute value from the job bag."""

    value: str
    external_id: UUID


class _SkuFillState:
    """Mutable per-SKU fill progress across sequential display_order bands."""

    __slots__ = (
        "business_sku_id",
        "pim_values",
        "job_values",
        "product_image_url",
        "row_values",
        "already_filled",
    )

    def __init__(
        self,
        *,
        business_sku_id: str,
        pim_values: dict[str, Any],
        job_values: dict[tuple[AttributeName, int], _JobAttrValue],
        product_image_url: str | None,
    ) -> None:
        self.business_sku_id = business_sku_id
        self.pim_values = pim_values
        self.job_values = job_values
        self.product_image_url = product_image_url
        self.row_values: dict[int, str | None] = {}
        self.already_filled: dict[str, str] = {}


class _ParsedColumn:
    __slots__ = ("column_index", "display_order", "config")

    def __init__(
        self,
        column_index: int,
        display_order: int,
        config: ListingColumnConfig,
    ) -> None:
        self.column_index = column_index
        self.display_order = display_order
        self.config = config

    @classmethod
    def from_row(cls, row: ListingTemplateColumn) -> _ParsedColumn:
        config = ListingColumnConfig.model_validate(row.config or {})
        return cls(row.column_index, row.display_order, config)


def _group_by_display_order(
    columns: list[_ParsedColumn],
) -> list[tuple[int, list[_ParsedColumn]]]:
    by_order: dict[int, list[_ParsedColumn]] = defaultdict(list)
    for col in columns:
        by_order[col.display_order].append(col)
    return sorted(by_order.items(), key=lambda item: item[0])


def _attribute_ids_by_name(session: Session) -> dict[AttributeName, int]:
    return {master.name: master.id for master in attribute_master_repo.list_all(session)}


def _job_values_bag(
    session: Session,
    *,
    sku_generation_job_id: int,
    attribute_ids_by_name: dict[AttributeName, int],
) -> dict[tuple[AttributeName, int], _JobAttrValue]:
    id_to_name = {attr_id: name for name, attr_id in attribute_ids_by_name.items()}
    rows = attribute_value_repo.list_latest_by_sku_generation_job_id(session, sku_generation_job_id)
    bag: dict[tuple[AttributeName, int], _JobAttrValue] = {}
    for row in rows:
        name = id_to_name.get(row.attribute_id)
        if name is None or not row.value:
            continue
        bag[(name, row.slot)] = _JobAttrValue(value=row.value, external_id=row.external_id)
    return bag


def _business_sku_id(sku: Any, *, fallback: str) -> str:
    if sku is None:
        return fallback
    attributes = dict(sku.attributes or {})
    value = str(attributes.get("SKU") or "").strip()
    return value or fallback


def _one_product_image_url(gcs: GcsClient, business_sku_id: str) -> str | None:
    from utils import flatfile as flatfile_utils

    prefix = flatfile_utils.product_image_prefix(business_sku_id)
    try:
        names = sorted(gcs.list_object_names(prefix))
    except GcsError:
        return None
    if not names:
        return None
    try:
        return gcs.signed_url(names[0], expiration_seconds=_REFERENCE_IMAGE_URL_TTL_SECONDS)
    except GcsError:
        return None


def _resolve_band(
    band_columns: list[_ParsedColumn],
    *,
    gcs: GcsClient,
    dropbox: DropboxClient,
    openrouter: OpenRouterClient,
    business_sku_id: str,
    pim_values: dict[str, Any],
    job_values: dict[tuple[AttributeName, int], _JobAttrValue],
    already_filled: dict[str, str],
    product_image_url: str | None,
) -> list[tuple[int, str | None, str | None, str]]:
    """Resolve one display_order band.

    Returns list of (column_index, value, gap_reason, label).
    """
    # ENUM columns: exact match first, then one batched LLM call for the rest.
    enum_pending: list[_ParsedColumn] = []
    results: dict[int, tuple[str | None, str | None, str]] = {}

    non_enum: list[_ParsedColumn] = []
    for col in band_columns:
        if col.config.fill_type == ListingFillType.ENUM:
            exact = None
            if col.config.source_key:
                exact = enum_select.match_exact(
                    _pim_get(pim_values, col.config.source_key),
                    col.config.valid_values or [],
                )
            if exact is not None:
                results[col.column_index] = (exact, None, col.config.label)
            else:
                enum_pending.append(col)
        else:
            non_enum.append(col)

    def _run_non_enum(col: _ParsedColumn) -> tuple[int, str | None, str | None, str]:
        value, gap = _resolve_simple(
            col,
            gcs=gcs,
            dropbox=dropbox,
            pim_values=pim_values,
            job_values=job_values,
        )
        return col.column_index, value, gap, col.config.label

    if non_enum:
        for col in non_enum:
            column_index, value, gap, label = _run_non_enum(col)
            results[column_index] = (value, gap, label)

    if enum_pending:
        enums_to_pick = [
            {
                "column_index": col.column_index,
                "label": col.config.label,
                "machine_key": col.config.machine_key,
                "valid_values": list(col.config.valid_values or []),
            }
            for col in enum_pending
        ]
        picks = enum_select.pick_enums(
            openrouter,
            sku_id=business_sku_id,
            product_attributes=pim_values,
            already_filled=already_filled,
            enums_to_pick=enums_to_pick,
            product_image_url=product_image_url,
        )
        for col in enum_pending:
            value = picks.get(col.column_index)
            gap = None
            if value is None:
                if col.config.requiredness == ListingRequiredness.ALWAYS:
                    gap = "ALWAYS empty"
                else:
                    gap = "ENUM not resolved"
            elif col.config.valid_values and value not in col.config.valid_values:
                gap = "ENUM not in valid_values"
                value = None
            results[col.column_index] = (value, gap, col.config.label)

    ordered: list[tuple[int, str | None, str | None, str]] = []
    for col in band_columns:
        value, gap, label = results.get(col.column_index, (None, None, col.config.label))
        ordered.append((col.column_index, value, gap, label))
    return ordered


def _resolve_simple(
    col: _ParsedColumn,
    *,
    gcs: GcsClient,
    dropbox: DropboxClient,
    pim_values: dict[str, Any],
    job_values: dict[tuple[AttributeName, int], _JobAttrValue],
) -> tuple[str | None, str | None]:
    config = col.config
    fill_type = config.fill_type

    if fill_type == ListingFillType.SKIP:
        return None, None

    if fill_type == ListingFillType.CONSTANT:
        return config.constant_value, None

    if fill_type == ListingFillType.DIRECT_MAP:
        value = _pim_get(pim_values, config.source_key or "")
        if value:
            return value, None
        gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
        return None, gap

    if fill_type == ListingFillType.LLM_TEXT:
        assert config.attribute_name is not None and config.slot is not None
        entry = job_values.get((config.attribute_name, config.slot))
        if entry is not None and entry.value:
            return entry.value, None
        gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
        return None, gap

    if fill_type == ListingFillType.IMAGE:
        assert config.attribute_name is not None and config.slot is not None
        entry = job_values.get((config.attribute_name, config.slot))
        if entry is None or not entry.value:
            gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
            return None, gap
        try:
            url = _gs_to_dropbox_url(
                gcs,
                dropbox,
                gs_uri=entry.value,
                attribute_value_external_id=entry.external_id,
            )
            return url, None
        except (GcsError, DropboxError, ListingFillError) as exc:
            logger.warning(
                "IMAGE Dropbox upload failed attribute_value=%s: %s",
                entry.external_id,
                exc,
            )
            return None, f"IMAGE upload failed: {exc}"

    return None, f"Unsupported fill_type {fill_type}"


def _pim_get(pim_values: dict[str, Any], key: str) -> str | None:
    if not key:
        return None
    raw = pim_values.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _gs_to_dropbox_url(
    gcs: GcsClient,
    dropbox: DropboxClient,
    *,
    gs_uri: str,
    attribute_value_external_id: UUID,
) -> str:
    """Upload image bytes to Dropbox under the attribute-value external_id folder."""
    object_name = gcs.object_name_from_gs_uri(gs_uri)
    if object_name is None:
        raise ListingFillError(f"Invalid image GCS URI: {gs_uri!r}")
    data = gcs.download_bytes(object_name)
    ext = "png"
    lower = object_name.lower()
    for candidate in ("png", "jpg", "jpeg", "webp", "gif"):
        if lower.endswith(f".{candidate}"):
            ext = "jpg" if candidate == "jpeg" else candidate
            break
    # Stable mapping: one Dropbox folder per sku_marketplace_attribute_value lineage.
    relative = f"{attribute_value_external_id}/image.{ext}"
    uploaded = dropbox.upload_bytes(data, relative)
    return uploaded.shared_url
