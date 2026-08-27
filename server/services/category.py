from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from core.exceptions import AmbiguousCategoryError, CategoryNotFoundError, InvalidCategoryPathError
from dto.response.category import (
    CategoryPathNode,
    CategoryTemplateField,
    CategoryTemplateResponse,
    ImportCategoryPathResponse,
    ImportedCategoryNode,
    LeafCategoryPageResponse,
    LeafCategoryResponse,
)
from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.category import Category
from entities.catalog.category_closure import CategoryClosure
from repositories.catalog import attribute_master as attribute_master_repository
from repositories.catalog import category as category_repository
from repositories.catalog import category_closure as category_closure_repository

DEFAULT_LEAF_PAGE_SIZE = 10


def import_category_path(session: Session, names: list[str]) -> ImportCategoryPathResponse:
    """Walk a root-first name path, reusing existing nodes and creating only gaps.

    Idempotent: a second call with the same path creates nothing and returns the
    same external ids. Matching is by exact name under the same parent (roots
    have no parent). Ambiguous duplicates under one parent raise.
    """
    if not names:
        raise InvalidCategoryPathError("Category path must contain at least one name")

    path: list[ImportedCategoryNode] = []
    parent: Category | None = None
    created_count = 0

    for name in names:
        existing = _resolve_existing(session, parent=parent, name=name)
        if existing is not None:
            path.append(
                ImportedCategoryNode(
                    external_id=existing.external_id,
                    name=existing.name,
                    created=False,
                )
            )
            parent = existing
            continue

        created = _create_under_parent(session, parent=parent, name=name)
        created_count += 1
        path.append(
            ImportedCategoryNode(
                external_id=created.external_id,
                name=created.name,
                created=True,
            )
        )
        parent = created

    return ImportCategoryPathResponse(
        path=path,
        created_count=created_count,
        reused_count=len(path) - created_count,
    )


def _resolve_existing(session: Session, *, parent: Category | None, name: str) -> Category | None:
    matches = (
        list(category_repository.list_roots_by_name(session, name))
        if parent is None
        else list(category_repository.list_children_by_name(session, parent.id, name))
    )
    if len(matches) > 1:
        scope = "root" if parent is None else f"parent external_id={parent.external_id}"
        raise AmbiguousCategoryError(
            f"Multiple categories named {name!r} under {scope}; cannot import safely"
        )
    return matches[0] if matches else None


def _create_under_parent(session: Session, *, parent: Category | None, name: str) -> Category:
    category = category_repository.save(session, Category(name=name))
    closure_rows: list[CategoryClosure] = [
        CategoryClosure(
            ancestor_id=category.id,
            descendant_id=category.id,
            depth=0,
        )
    ]
    if parent is not None:
        for ancestor_row in category_closure_repository.list_ancestor_rows(session, parent.id):
            closure_rows.append(
                CategoryClosure(
                    ancestor_id=ancestor_row.ancestor_id,
                    descendant_id=category.id,
                    depth=ancestor_row.depth + 1,
                )
            )
    category_closure_repository.save_all(session, closure_rows)
    return category


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

    ordered_entries, mandatory_keys = _attribute_spec_entries(category)
    attributes_by_id = _attributes_by_id(session, ordered_entries)

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


def allowed_product_attribute_names(session: Session, category: Category) -> frozenset[str]:
    """Spreadsheet field names from ``attribute_spec.allowed`` ∪ ``mandatory``."""
    return allowed_product_attribute_names_for_categories(session, [category])[category.id]


def allowed_product_attribute_names_for_categories(
    session: Session, categories: Sequence[Category]
) -> dict[int, frozenset[str]]:
    """Resolve allowed field names for many categories with one attribute-master load."""
    if not categories:
        return {}
    entries_by_id: dict[int, list[object]] = {}
    all_entries: list[object] = []
    for category in categories:
        ordered, _mandatory_keys = _attribute_spec_entries(category)
        entries_by_id[category.id] = ordered
        all_entries.extend(ordered)
    attributes_by_id = _attributes_by_id(session, all_entries)
    return {
        category_id: frozenset(_field_name(entry, attributes_by_id) for entry in entries)
        for category_id, entries in entries_by_id.items()
    }


def _attribute_spec_entries(category: Category) -> tuple[list[object], set[str]]:
    spec = category.attribute_spec if isinstance(category.attribute_spec, dict) else {}
    allowed_raw = list(spec.get("allowed") or [])
    mandatory_raw = list(spec.get("mandatory") or [])
    mandatory_keys = {_spec_key(entry) for entry in mandatory_raw}

    # Preserve allowed order; append any mandatory-only entries at the end.
    ordered_entries: list[object] = list(allowed_raw)
    seen = {_spec_key(entry) for entry in allowed_raw}
    for entry in mandatory_raw:
        key = _spec_key(entry)
        if key not in seen:
            ordered_entries.append(entry)
            seen.add(key)
    return ordered_entries, mandatory_keys


def _attributes_by_id(session: Session, entries: list[object]) -> dict[int, AttributeMaster]:
    attribute_ids = list({entry for entry in entries if isinstance(entry, int)})
    return {
        attribute.id: attribute
        for attribute in attribute_master_repository.list_by_ids(session, attribute_ids)
    }


def _spec_key(entry: object) -> str:
    return str(entry)


def _field_name(entry: object, attributes_by_id: dict[int, AttributeMaster]) -> str:
    if isinstance(entry, int):
        attribute = attributes_by_id.get(entry)
        if attribute is not None:
            return str(attribute.name)
        return f"attribute_{entry}"
    if isinstance(entry, str):
        return entry
    return str(entry)


def _to_template_field(
    entry: object,
    *,
    mandatory: bool,
    attributes_by_id: dict[int, AttributeMaster],
) -> CategoryTemplateField:
    return CategoryTemplateField(
        name=_field_name(entry, attributes_by_id),
        mandatory=mandatory,
    )
