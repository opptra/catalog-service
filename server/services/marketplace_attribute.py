"""Load and validate marketplace_attribute config for generation and UI."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.orm import Session

from dto.marketplace_attribute_config import MarketplaceAttributeConfig
from entities.catalog.attribute_enums import AttributeName
from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.marketplace_attribute import MarketplaceAttribute
from repositories.catalog import attribute_master as attribute_master_repo
from repositories.catalog import marketplace_attribute as marketplace_attribute_repo


class MarketplaceAttributeRules:
    """Validated mapping row + its attribute master."""

    __slots__ = ("mapping", "master", "config")

    def __init__(
        self,
        mapping: MarketplaceAttribute,
        master: AttributeMaster,
        config: MarketplaceAttributeConfig,
    ) -> None:
        self.mapping = mapping
        self.master = master
        self.config = config

    @property
    def name(self) -> AttributeName:
        return AttributeName(self.master.name)

    @property
    def image_quantity(self) -> int | None:
        if self.config.image is None:
            return None
        return self.config.image.quantity

    @property
    def aspect_ratio(self) -> str | None:
        if self.config.image is None:
            return None
        return self.config.image.aspect_ratio


def parse_config(raw: object) -> MarketplaceAttributeConfig:
    """Parse and validate a config JSON object. Empty/null → empty config."""
    if raw is None:
        return MarketplaceAttributeConfig()
    if not isinstance(raw, dict):
        raise ValueError("marketplace_attribute.config must be a JSON object")
    try:
        return MarketplaceAttributeConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid marketplace_attribute.config: {exc}") from exc


def list_rules_for_marketplace(
    session: Session, marketplace_id: int
) -> list[MarketplaceAttributeRules]:
    """Return validated attribute rules for one marketplace (empty if none seeded)."""
    rows = list(marketplace_attribute_repo.list_by_marketplace_id(session, marketplace_id))
    return _hydrate(session, rows)


def list_rules_by_marketplace_ids(
    session: Session, marketplace_ids: Sequence[int]
) -> dict[int, list[MarketplaceAttributeRules]]:
    """Return rules keyed by marketplace_id."""
    rows = list(marketplace_attribute_repo.list_by_marketplace_ids(session, marketplace_ids))
    by_marketplace: dict[int, list[MarketplaceAttribute]] = {mid: [] for mid in marketplace_ids}
    for row in rows:
        by_marketplace.setdefault(row.marketplace_id, []).append(row)
    return {
        marketplace_id: _hydrate(session, mappings)
        for marketplace_id, mappings in by_marketplace.items()
    }


def get_rules_for_attribute(
    session: Session,
    *,
    marketplace_id: int,
    attribute_id: int,
) -> MarketplaceAttributeRules | None:
    row = marketplace_attribute_repo.get_by_marketplace_and_attribute(
        session, marketplace_id, attribute_id
    )
    if row is None:
        return None
    hydrated = _hydrate(session, [row])
    return hydrated[0] if hydrated else None


def _hydrate(
    session: Session, rows: Sequence[MarketplaceAttribute]
) -> list[MarketplaceAttributeRules]:
    if not rows:
        return []
    masters = {
        master.id: master
        for master in attribute_master_repo.list_by_ids(session, [row.attribute_id for row in rows])
    }
    out: list[MarketplaceAttributeRules] = []
    for row in rows:
        master = masters.get(row.attribute_id)
        if master is None:
            continue
        out.append(
            MarketplaceAttributeRules(
                mapping=row,
                master=master,
                config=parse_config(row.config),
            )
        )
    return out
