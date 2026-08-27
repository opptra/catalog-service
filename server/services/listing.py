"""Listing fill — assemble Amazon workbooks from a completed generation job."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core.clients.dropbox import MAX_CONCURRENT_OPS, DropboxClient
from core.clients.gcs import GcsClient
from core.clients.openrouter import OpenRouterClient
from core.exceptions import (
    CategoryNotFoundError,
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
    ListingValueSourceFrom,
)
from entities.catalog.listing_template_column import ListingTemplateColumn
from pipelines.listing import ai_text, enum_select
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import category_marketplace as category_marketplace_repo
from repositories.catalog import job as job_repo
from repositories.catalog import listing_template as listing_template_repo
from repositories.catalog import listing_template_column as listing_template_column_repo
from repositories.catalog import sku_generation_job as sku_generation_job_repo
from repositories.catalog import sku_marketplace_attribute_value as attribute_value_repo
from repositories.catalog import sku_master as sku_master_repo
from services import product_attributes as product_attributes_service
from services import sku_image_export as sku_image_export_service
from utils import listing_workbook as workbook_utils

logger = logging.getLogger(__name__)

# SKU-level parallelism within a resolve stage (AI / enums / IMAGE). Dropbox
# traffic is additionally hard-capped by DropboxClient.MAX_CONCURRENT_OPS.
_LISTING_FILL_WORKERS = MAX_CONCURRENT_OPS
_FILLED_FILE_SIGNED_URL_TTL_SECONDS = 3600
_REFERENCE_IMAGE_URL_TTL_SECONDS = 3600
_MAX_PRODUCT_IMAGE_URLS = 7
_LISTING_OUTPUT_CONTENT_TYPE = "application/vnd.ms-excel.sheet.macroEnabled.12"


def fill_listing_for_group(
    session: Session,
    gcs: GcsClient,
    dropbox: DropboxClient,
    openrouter: OpenRouterClient,
    *,
    job_group_id: UUID,
    marketplace_external_id: UUID,
) -> FillListingResponse:
    """Resolve a group + marketplace to a child job, then fill its listing template."""
    job, _marketplace = sku_image_export_service.resolve_job_in_group(
        session, job_group_id, marketplace_external_id
    )
    return fill_listing_for_job(session, gcs, dropbox, openrouter, job.external_id)


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
    if job.marketplace_id is None:
        raise ListingFillError(f"Job {job_external_id} is missing marketplace_id")

    sku_jobs = list(sku_generation_job_repo.list_by_job_id(session, job.id))
    if not sku_jobs:
        raise ListingFillError(f"Job {job_external_id} has no SKU generation jobs")

    sku_rows = list(sku_master_repo.list_by_ids(session, [sj.sku_id for sj in sku_jobs]))
    sku_by_id = {sku.id: sku for sku in sku_rows}

    # Generation jobs store marketplace on the job row but leave category_id null;
    # category comes from the SKUs (same subcategory batch).
    category_id = job.category_id
    if category_id is None:
        category_ids = {sku.category_id for sku in sku_rows}
        if len(category_ids) != 1:
            raise ListingFillError(
                f"Job {job_external_id} SKUs do not share a single category "
                f"(found {sorted(category_ids) or 'none'})"
            )
        category_id = next(iter(category_ids))

    junction = category_marketplace_repo.get_by_marketplace_and_category(
        session, job.marketplace_id, category_id
    )
    if junction is None:
        raise ListingTemplateNotFoundError(
            f"No category_marketplace for marketplace_id={job.marketplace_id} "
            f"category_id={category_id}"
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
    stages = _group_by_resolve_stage(parsed_columns)

    attribute_ids_by_name = _attribute_ids_by_name(session)
    try:
        pim_by_sku_id = product_attributes_service.for_skus(session, sku_rows)
    except CategoryNotFoundError as exc:
        raise ListingFillError(str(exc)) from exc

    gaps: list[ListingFillGap] = []
    sku_states: list[_SkuFillState] = []

    for sku_job in sku_jobs:
        sku = sku_by_id.get(sku_job.sku_id)
        business_sku_id = _business_sku_id(sku, fallback=str(sku_job.sku_id))
        sku_states.append(
            _SkuFillState(
                business_sku_id=business_sku_id,
                pim_values=pim_by_sku_id.get(sku.id, {}) if sku is not None else {},
                job_values=_job_values_bag(
                    session,
                    sku_generation_job_id=sku_job.id,
                    attribute_ids_by_name=attribute_ids_by_name,
                ),
                product_image_urls=_product_image_urls(gcs, business_sku_id),
            )
        )

    # Stages are sequential (later stages need already_filled parents). Within a
    # stage, columns have no mutual dependency — SKUs run concurrently (cap).
    for _stage, stage_columns in stages:
        workers = min(_LISTING_FILL_WORKERS, max(1, len(sku_states)))

        def _run_sku_stage(
            state: _SkuFillState,
            cols: list[_ParsedColumn],
        ) -> list[ListingFillGap]:
            stage_gaps: list[ListingFillGap] = []
            stage_results = _resolve_stage(
                cols,
                gcs=gcs,
                dropbox=dropbox,
                openrouter=openrouter,
                business_sku_id=state.business_sku_id,
                pim_values=state.pim_values,
                job_values=state.job_values,
                already_filled=state.already_filled,
                already_filled_by_key=state.already_filled_by_key,
                product_image_urls=state.product_image_urls,
            )
            for column_index, value, gap_reason, label, machine_key in stage_results:
                state.row_values[column_index] = value
                if value:
                    state.already_filled[label] = value
                    if machine_key:
                        state.already_filled_by_key[machine_key] = value
                if gap_reason:
                    stage_gaps.append(
                        ListingFillGap(
                            sku_id=state.business_sku_id,
                            column_label=label,
                            reason=gap_reason,
                        )
                    )
            return stage_gaps

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_sku_stage, state, stage_columns) for state in sku_states]
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
    """Mutable per-SKU fill progress across sequential resolve_stage bands."""

    __slots__ = (
        "business_sku_id",
        "pim_values",
        "job_values",
        "product_image_urls",
        "row_values",
        "already_filled",
        "already_filled_by_key",
    )

    def __init__(
        self,
        *,
        business_sku_id: str,
        pim_values: dict[str, Any],
        job_values: dict[tuple[AttributeName, int], _JobAttrValue],
        product_image_urls: list[str],
    ) -> None:
        self.business_sku_id = business_sku_id
        self.pim_values = pim_values
        self.job_values = job_values
        self.product_image_urls = product_image_urls
        self.row_values: dict[int, str | None] = {}
        self.already_filled: dict[str, str] = {}
        # machine_key → value (for depends_on / valid_values_by_parent)
        self.already_filled_by_key: dict[str, str] = {}


class _ParsedColumn:
    __slots__ = ("column_index", "resolve_stage", "config")

    def __init__(
        self,
        column_index: int,
        resolve_stage: int,
        config: ListingColumnConfig,
    ) -> None:
        self.column_index = column_index
        self.resolve_stage = resolve_stage
        self.config = config

    @classmethod
    def from_row(cls, row: ListingTemplateColumn) -> _ParsedColumn:
        config = ListingColumnConfig.model_validate(row.config or {})
        return cls(row.column_index, row.resolve_stage, config)


def _group_by_resolve_stage(
    columns: list[_ParsedColumn],
) -> list[tuple[int, list[_ParsedColumn]]]:
    by_stage: dict[int, list[_ParsedColumn]] = defaultdict(list)
    for col in columns:
        by_stage[col.resolve_stage].append(col)
    return sorted(by_stage.items(), key=lambda item: item[0])


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


def _product_image_urls(gcs: GcsClient, business_sku_id: str) -> list[str]:
    """Signed HTTPS URLs for flatfile product photos (capped for model context)."""
    from utils import flatfile as flatfile_utils

    prefix = flatfile_utils.product_image_prefix(business_sku_id)
    try:
        names = sorted(gcs.list_object_names(prefix))
    except GcsError:
        return []
    urls: list[str] = []
    for name in names[:_MAX_PRODUCT_IMAGE_URLS]:
        try:
            urls.append(gcs.signed_url(name, expiration_seconds=_REFERENCE_IMAGE_URL_TTL_SECONDS))
        except GcsError:
            continue
    return urls


def _values_for_parent(
    valid_values_by_parent: dict[str, list[str]],
    parent_value: str,
) -> list[str]:
    """Match parent selection to a child list (exact, then case-insensitive)."""
    if parent_value in valid_values_by_parent:
        return list(valid_values_by_parent[parent_value])
    needle = parent_value.casefold()
    for key, values in valid_values_by_parent.items():
        if key.casefold() == needle:
            return list(values)
    return []


def _effective_enum_values(
    col: _ParsedColumn,
    *,
    already_filled_by_key: dict[str, str],
) -> tuple[list[str] | None, str | None]:
    """Allowed ENUM values after parent filtering.

    Hierarchical columns never expose the full stored map to the picker — only
    the list for the already-filled parent (Product Type → League → Team).
    """
    config = col.config
    if config.depends_on:
        parent_value = already_filled_by_key.get(config.depends_on)
        if not parent_value:
            return None, "parent not filled"
        if config.valid_values_by_parent:
            narrowed = _values_for_parent(config.valid_values_by_parent, parent_value)
            if not narrowed:
                return None, "no valid_values for parent"
            return narrowed, None
        # depends_on without a parent map: still do not invent a full unfiltered list
        return None, "ENUM missing valid_values_by_parent"
    if config.valid_values:
        return list(config.valid_values), None
    return None, "ENUM has no valid_values"


def _resolve_stage(
    stage_columns: list[_ParsedColumn],
    *,
    gcs: GcsClient,
    dropbox: DropboxClient,
    openrouter: OpenRouterClient,
    business_sku_id: str,
    pim_values: dict[str, Any],
    job_values: dict[tuple[AttributeName, int], _JobAttrValue],
    already_filled: dict[str, str],
    already_filled_by_key: dict[str, str],
    product_image_urls: list[str],
) -> list[tuple[int, str | None, str | None, str, str | None]]:
    """Resolve one resolve_stage band.

    Returns list of (column_index, value, gap_reason, label, machine_key).
    """
    enum_pending: list[tuple[_ParsedColumn, list[str]]] = []
    ai_text_pending: list[_ParsedColumn] = []
    results: dict[int, tuple[str | None, str | None, str, str | None]] = {}

    simple: list[_ParsedColumn] = []
    for col in stage_columns:
        fill = col.config.fill_type
        if fill == ListingFillType.ENUM:
            effective, gap = _effective_enum_values(
                col, already_filled_by_key=already_filled_by_key
            )
            if effective is None:
                results[col.column_index] = (
                    None,
                    gap,
                    col.config.label,
                    col.config.machine_key,
                )
                continue
            exact = None
            source = col.config.source
            if source is not None and source.from_ == ListingValueSourceFrom.SKU_MASTER:
                exact = enum_select.match_exact(
                    _pim_get(pim_values, source.key or ""),
                    effective,
                )
            elif col.config.source_key:
                exact = enum_select.match_exact(
                    _pim_get(pim_values, col.config.source_key),
                    effective,
                )
            if exact is not None:
                results[col.column_index] = (
                    exact,
                    None,
                    col.config.label,
                    col.config.machine_key,
                )
            else:
                enum_pending.append((col, effective))
        elif fill == ListingFillType.AI_TEXT:
            ai_text_pending.append(col)
        else:
            simple.append(col)

    for col in simple:
        value, gap = _resolve_simple(
            col,
            gcs=gcs,
            dropbox=dropbox,
            pim_values=pim_values,
            job_values=job_values,
        )
        results[col.column_index] = (
            value,
            gap,
            col.config.label,
            col.config.machine_key,
        )

    # Fold non-AI results into already_filled so batched AI calls see them.
    stage_filled = dict(already_filled)
    for col in stage_columns:
        packed = results.get(col.column_index)
        if packed is None:
            continue
        value, _gap, label, machine_key = packed
        if value:
            stage_filled[label] = value
            if machine_key:
                already_filled_by_key[machine_key] = value

    if enum_pending:
        enums_to_pick = [
            {
                "column_index": col.column_index,
                "label": col.config.label,
                "machine_key": col.config.machine_key,
                "valid_values": list(effective),
            }
            for col, effective in enum_pending
        ]
        picks = enum_select.pick_enums(
            openrouter,
            sku_id=business_sku_id,
            product_attributes=pim_values,
            already_filled=stage_filled,
            enums_to_pick=enums_to_pick,
            product_image_urls=product_image_urls,
        )
        for col, effective in enum_pending:
            value = picks.get(col.column_index)
            gap = None
            allowed = set(effective)
            if value is None:
                if col.config.requiredness == ListingRequiredness.ALWAYS:
                    gap = "ALWAYS empty"
                # OPTIONAL: intentional omit when evidence is weak — not a gap
            elif value not in allowed:
                gap = "ENUM not in valid_values"
                value = None
            results[col.column_index] = (
                value,
                gap,
                col.config.label,
                col.config.machine_key,
            )
            if value:
                stage_filled[col.config.label] = value
                if col.config.machine_key:
                    already_filled_by_key[col.config.machine_key] = value

    if ai_text_pending:
        fields = [
            {
                "column_index": col.column_index,
                "label": col.config.label,
                "machine_key": col.config.machine_key,
            }
            for col in ai_text_pending
        ]
        generated = ai_text.generate_texts(
            openrouter,
            sku_id=business_sku_id,
            product_attributes=pim_values,
            already_filled=stage_filled,
            fields=fields,
            product_image_urls=product_image_urls,
        )
        for col in ai_text_pending:
            value = generated.get(col.column_index)
            gap = None
            if not value:
                if col.config.requiredness == ListingRequiredness.ALWAYS:
                    gap = "ALWAYS empty"
                # OPTIONAL: intentional omit when evidence is weak — not a gap
                value = None
            results[col.column_index] = (
                value,
                gap,
                col.config.label,
                col.config.machine_key,
            )

    ordered: list[tuple[int, str | None, str | None, str, str | None]] = []
    for col in stage_columns:
        value, gap, label, machine_key = results.get(
            col.column_index,
            (None, None, col.config.label, col.config.machine_key),
        )
        ordered.append((col.column_index, value, gap, label, machine_key))
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

    if fill_type in (ListingFillType.DIRECT_MAP, ListingFillType.LLM_TEXT):
        return _resolve_from_source(
            config,
            pim_values=pim_values,
            job_values=job_values,
        )

    if fill_type == ListingFillType.IMAGE:
        value, gap = _resolve_from_source(
            config,
            pim_values=pim_values,
            job_values=job_values,
        )
        if value is None:
            return None, gap
        source = config.source
        assert source is not None and source.attribute_name is not None and source.slot is not None
        entry = job_values.get((source.attribute_name, source.slot))
        assert entry is not None
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

    if fill_type == ListingFillType.AI_TEXT:
        # Batched in _resolve_stage — should not reach here.
        return None, "AI_TEXT must be resolved in stage batch"

    return None, f"Unsupported fill_type {fill_type}"


def _resolve_from_source(
    config: ListingColumnConfig,
    *,
    pim_values: dict[str, Any],
    job_values: dict[tuple[AttributeName, int], _JobAttrValue],
) -> tuple[str | None, str | None]:
    """Copy a value from GENERATION job bag or SKU_MASTER PIM attributes."""
    source = config.source
    if source is None:
        gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
        return None, gap

    if source.from_ == ListingValueSourceFrom.SKU_MASTER:
        value = _pim_get(pim_values, source.key or "")
        if value:
            return value, None
        gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
        return None, gap

    assert source.attribute_name is not None and source.slot is not None
    entry = job_values.get((source.attribute_name, source.slot))
    if entry is not None and entry.value:
        text = _generation_source_text(entry.value, index=source.index)
        if text:
            return text, None
        gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
        return None, gap
    gap = "ALWAYS empty" if config.requiredness == ListingRequiredness.ALWAYS else None
    return None, gap


def _pim_get(pim_values: dict[str, Any], key: str) -> str | None:
    if not key:
        return None
    raw = pim_values.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _generation_source_text(raw: str, *, index: int | None) -> str | None:
    """Resolve a generation bag string: list index, joined list, or plain text."""
    if index is not None:
        return _json_list_element(raw, index)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        text = raw.strip()
        return text or None
    if isinstance(parsed, list):
        parts = [str(item).strip() for item in parsed if item is not None and str(item).strip()]
        return " ".join(parts) if parts else None
    text = str(parsed).strip() if parsed is not None else ""
    return text or None


def _json_list_element(raw: str, index: int) -> str | None:
    """1-based index into a JSON array string (e.g. BULLET_POINTS)."""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    pos = index - 1
    if pos < 0 or pos >= len(parsed):
        return None
    item = parsed[pos]
    if item is None:
        return None
    text = str(item).strip()
    return text or None


def _gs_to_dropbox_url(
    gcs: GcsClient,
    dropbox: DropboxClient,
    *,
    gs_uri: str,
    attribute_value_external_id: UUID,
) -> str:
    """Return a Dropbox URL for this attribute-value image.

    Uses ``ensure_shared_url`` (shared-link lookup → upload on miss).
    Folder key is the attribute-value external id.
    """
    folder = str(attribute_value_external_id)
    object_name = gcs.object_name_from_gs_uri(gs_uri)
    if object_name is None:
        raise ListingFillError(f"Invalid image GCS URI: {gs_uri!r}")

    ext = "png"
    lower = object_name.lower()
    for candidate in ("png", "jpg", "jpeg", "webp", "gif"):
        if lower.endswith(f".{candidate}"):
            ext = "jpg" if candidate == "jpeg" else candidate
            break

    def _load() -> bytes:
        return gcs.download_bytes(object_name)

    return dropbox.ensure_shared_url(
        relative_dir=folder,
        filename=f"image.{ext}",
        load_bytes=_load,
    )
