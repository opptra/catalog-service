"""Marketplace identity for offline listing-mapping."""

from __future__ import annotations

from enum import StrEnum


class MarketplaceId(StrEnum):
    AMAZON = "AMAZON"
    FLIPKART = "FLIPKART"
    MYNTRA = "MYNTRA"


def parse_marketplace_id(raw: str) -> MarketplaceId:
    needle = raw.strip()
    try:
        return MarketplaceId(needle.upper())
    except ValueError as exc:
        known = ", ".join(m.value for m in MarketplaceId)
        raise ValueError(
            f"Unknown marketplace {raw!r}. Expected one of: {known}"
        ) from exc


__all__ = ["MarketplaceId", "parse_marketplace_id"]
