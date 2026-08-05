from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions import CategoryNotFoundError
from dto.response.category import (
    CategoryPathNode,
    CategoryTemplateField,
    CategoryTemplateResponse,
    LeafCategoryPageResponse,
    LeafCategoryResponse,
)
from entities.catalog.attribute_master import AttributeMaster
from repositories.catalog import attribute_master as attribute_master_repository
from repositories.catalog import category as category_repository

DEFAULT_LEAF_PAGE_SIZE = 10


def list_leaf_categories(
    session: Session,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LEAF_PAGE_SIZE,
) -> LeafCategoryPageResponse:
    rows, has_more = category_repository.list_leaf_categories_with_paths(
        session,
        offset=offset,
        limit=limit,
    )
    return LeafCategoryPageResponse(
        items=[
            LeafCategoryResponse(
                external_id=row.external_id,
                name=row.name,
                path=[
                    CategoryPathNode(external_id=node.external_id, name=node.name)
                    for node in row.path
                ],
            )
            for row in rows
        ],
        offset=offset,
        limit=limit,
        has_more=has_more,
    )


def get_category_template(session: Session, external_id: UUID) -> CategoryTemplateResponse:
    category = category_repository.get_by_external_id(session, external_id)
    if category is None:
        raise CategoryNotFoundError(f"Category not found: {external_id}")

    spec = category.attribute_spec if isinstance(category.attribute_spec, dict) else {}
    allowed_raw = list(spec.get("allowed") or [])
    mandatory_raw = list(spec.get("mandatory") or [])
    mandatory_keys = {_spec_key(entry) for entry in mandatory_raw}

    # Preserve allowed order; append any mandatory-only entries at the end.
    ordered_entries: list[object] = list(allowed_raw)
    allowed_keys = {_spec_key(entry) for entry in allowed_raw}
    for entry in mandatory_raw:
        key = _spec_key(entry)
        if key not in allowed_keys:
            ordered_entries.append(entry)
            allowed_keys.add(key)

    attribute_ids = [entry for entry in ordered_entries if isinstance(entry, int)]
    attributes_by_id = {
        attribute.id: attribute
        for attribute in attribute_master_repository.list_by_ids(session, attribute_ids)
    }

    fields: list[CategoryTemplateField] = []
    for entry in ordered_entries:
        fields.append(
            _to_template_field(
                entry,
                mandatory=_spec_key(entry) in mandatory_keys,
                attributes_by_id=attributes_by_id,
            )
        )

    return CategoryTemplateResponse(
        external_id=category.external_id,
        name=category.name,
        fields=fields,
    )


def _spec_key(entry: object) -> str:
    return str(entry)


def _to_template_field(
    entry: object,
    *,
    mandatory: bool,
    attributes_by_id: dict[int, AttributeMaster],
) -> CategoryTemplateField:
    if isinstance(entry, int):
        attribute = attributes_by_id.get(entry)
        if attribute is not None:
            return CategoryTemplateField(
                name=str(attribute.name),
                mandatory=mandatory,
            )
        return CategoryTemplateField(name=f"attribute_{entry}", mandatory=mandatory)

    if isinstance(entry, str):
        return CategoryTemplateField(name=entry, mandatory=mandatory)

    return CategoryTemplateField(name=str(entry), mandatory=mandatory)
